"""The kernel generators embed bundle files in os.walk order, which is the filesystem's directory order: APFS and ext4
disagree, so the same bundle produced byte-different notebooks on the Mac and in the Linux container (9 bundle tests failed
there on 2026-10-15 with a diff at the start of an embedded file). Both generators must walk in sorted order. Written first."""
import importlib.util, os, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    return spec, spec.loader


def test_make_eval_kernel_bundle_files_is_sorted_regardless_of_listing_order(tmp_path, monkeypatch):
    spec, loader = _load("make_eval_kernel")
    mek = importlib.util.module_from_spec(spec); loader.exec_module(mek)
    b = tmp_path / "bundle"; (b / "prompts").mkdir(parents=True); (b / "configs").mkdir()
    for rel in ("zeta.yaml", "prompts/b.md", "prompts/a.md", "configs/x.yaml", "agent.yaml"):
        (b / rel).write_text(rel)
    real_walk = os.walk
    def reversed_walk(top, *a, **k):              # the worst case: every listing in reverse order
        for root, dirs, files in real_walk(top, *a, **k):
            dirs.sort(reverse=True); files.sort(reverse=True)
            yield root, dirs, files
    monkeypatch.setattr(mek.os, "walk", reversed_walk)
    keys = list(mek.bundle_files(str(b)))
    # a sorted walk: the top directory's files in order, then each subdirectory in order (the order APFS happened to give
    # the v12/v13 bundles, so their committed kernels stay byte-identical)
    assert keys == ["agent.yaml", "zeta.yaml", "configs/x.yaml", "prompts/a.md", "prompts/b.md"]
    monkeypatch.setattr(mek.os, "walk", real_walk)
    assert list(mek.bundle_files(str(b))) == keys


def test_make_kernel_walks_in_sorted_order_statically():
    """make_kernel.py runs at import (module-level script), so it is checked statically: the walk sorts dirs and files."""
    t = (ROOT / "scripts" / "make_kernel.py").read_text()
    m = re.search(r"for root, (\w+), fs in os\.walk\(src\):\n(.*?)\n\s+for f in (.*?):", t, re.S)
    assert m, "walk loop not found"
    dirs_var, between, files_expr = m.groups()
    assert dirs_var != "_" and f"{dirs_var}.sort()" in between and files_expr == "sorted(fs)"
