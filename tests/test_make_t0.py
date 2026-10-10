"""scripts/make_t0.py: a -t0 bundle is its source plus one line, `thinking_budget: 0`, in every configs yaml that has a
thinking_config, and on the 2026-10-09 scorer stack (adk_submission 0.2.13) that is the one switch that keeps thinking off.

The finding it answers (docs/a6000/V7C_FAILURE_ANALYSIS.md, section 8): the organisers' defaults merge thinking_budget 4096
into every bundle and the new resolver reads a positive budget as thinking ON, before include_thoughts. So the control
here compiles the untouched source and shows enable_thinking True with thinking_token_budget 4096; the -t0 copy shows
False and no budget. These compile checks need the new wheels in the venv (scripts/swe_compat.stack()['old_helpers'] is
False); on the old stack they are skipped, since there thinking was already off and the schema refuses a 0 budget.
Written before the script (test-first, 2026-10-10)."""
import filecmp, os, re, subprocess, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import make_t0, swe_compat  # noqa: E402

NEW_STACK = not swe_compat.stack()["old_helpers"]
needs_new = pytest.mark.skipif(not NEW_STACK, reason="the compile checks need the 2026-10-09 wheels (adk_submission 0.2.13) in the venv")


def all_files(d):
    return {str(p.relative_to(d)) for p in Path(d).rglob("*") if p.is_file()}


def thinking_of(bundle):
    """{stage: (enable_thinking, thinking_token_budget, reasoning_effort)} as the compiled LiteLlm clients would send it."""
    from unittest.mock import MagicMock
    from adk_submission import compile_submission, discover_adapters
    from swegemma.config import ALLOWED_ADAPTER_EXTENSIONS, build_submission_limits
    from swegemma.tools import create_tools
    limits, gen = build_submission_limits()
    root = compile_submission(submission_dir=str(bundle), adapter_manifest=discover_adapters(str(bundle), ALLOWED_ADAPTER_EXTENSIONS),
                              tool_registry=create_tools(MagicMock()), model_registry=swe_compat.compile_only_model_registry(swe_compat.declared_model(str(bundle))),
                              limits=limits, generation_constraints=gen)
    out, stack = {}, [root]
    while stack:
        a = stack.pop()
        stack += list(getattr(a, "sub_agents", []) or [])
        m = getattr(a, "model", None)
        if hasattr(m, "_additional_args"):
            body = (m._additional_args or {}).get("extra_body") or {}
            out[a.name] = ((body.get("chat_template_kwargs") or {}).get("enable_thinking"), body.get("thinking_token_budget"),
                           (m._additional_args or {}).get("reasoning_effort"))
    return out


@pytest.mark.parametrize("src", ["v7d", "v7c", "v5h2", "v4h2g_v11b_probe", "v6p"])
def test_the_copy_differs_from_its_source_only_by_the_one_line_in_each_thinking_yaml(tmp_path, src):
    s, d = ROOT / "submissions" / src, tmp_path / (src + "-t0")
    changed = make_t0.make_t0(s, d)
    assert all_files(d) == all_files(s)
    ys = {str(p.relative_to(s)) for p in make_t0.thinking_yamls(s)}
    assert set(changed) == ys and ys and all(rel.startswith("configs/") for rel in ys), (changed, ys)
    for rel in sorted(all_files(s)):
        if rel in ys:
            a, b = (s / rel).read_text().splitlines(), (d / rel).read_text().splitlines()
            assert len(b) == len(a) + 1 and [l for l in b if l != "  thinking_budget: 0"] == a, rel
            assert b[b.index("thinking_config:") + 1] == "  thinking_budget: 0", rel
        else:
            assert filecmp.cmp(s / rel, d / rel, shallow=False), rel
        assert os.stat(s / rel).st_mode == os.stat(d / rel).st_mode, rel


def test_v6ps_three_sampling_variants_all_get_the_line(tmp_path):
    changed = make_t0.make_t0(ROOT / "submissions" / "v6p", tmp_path / "v6p-t0")
    assert sorted(changed) == ["configs/sampling.yaml", "configs/sampling_a.yaml", "configs/sampling_b.yaml", "configs/sampling_c.yaml"]


def test_refusals(tmp_path):
    import shutil
    (tmp_path / "exists").mkdir()
    with pytest.raises(SystemExit, match="exists"):
        make_t0.make_t0(ROOT / "submissions" / "v7d", tmp_path / "exists")
    b = tmp_path / "already"
    shutil.copytree(ROOT / "submissions" / "v7d", b, ignore=shutil.ignore_patterns("__pycache__"))
    y = b / "configs" / "sampling.yaml"
    y.write_text(y.read_text() + "  thinking_level: low\n")
    with pytest.raises(SystemExit, match="already sets"):
        make_t0.make_t0(b, tmp_path / "already-t0")
    n = tmp_path / "none"
    shutil.copytree(ROOT / "submissions" / "v7d", n, ignore=shutil.ignore_patterns("__pycache__"))
    (n / "configs" / "sampling.yaml").write_text("temperature: 0.2\n")
    with pytest.raises(SystemExit, match="no configs"):
        make_t0.make_t0(n, tmp_path / "none-t0")
    assert not (tmp_path / "already-t0").exists() and not (tmp_path / "none-t0").exists()


@needs_new
@pytest.mark.parametrize("src", ["v7d", "v5h2"])
def test_on_the_new_stack_the_source_thinks_and_the_copy_does_not(tmp_path, src):
    s, d = ROOT / "submissions" / src, tmp_path / (src + "-t0")
    make_t0.make_t0(s, d)
    before, after = thinking_of(s), thinking_of(d)
    assert before and set(before) == set(after)
    assert all(v == (True, 4096, None) for v in before.values()), before      # the finding: include_thoughts false no longer turns it off
    assert all(v == (False, None, None) for v in after.values()), after


@needs_new
def test_the_copy_passes_the_official_validator(tmp_path):
    d = tmp_path / "v7d-t0"
    make_t0.make_t0(ROOT / "submissions" / "v7d", d)
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(d)], capture_output=True, text=True, timeout=180)
    assert r.returncode == 0 and "OK model=gemma-4-31b-it-qat-w4a16-ct" in r.stdout, r.stdout[-500:] + r.stderr[-1500:]
    assert "'thinking_budget': 0" in r.stdout and "'thinking_budget': 4096" not in r.stdout, r.stdout[-1200:]


@pytest.mark.parametrize("name", ["v7c-t0", "v5h2-t0", "v4h2g_v11b_probe-t0", "v7d-t0"])
def test_the_committed_t0_bundles_are_what_the_script_makes(tmp_path, name):
    """The four -t0 bundles in submissions/ (the Saturday queue and v7d) are byte-for-byte what make_t0 produces today."""
    src, d = ROOT / "submissions" / name[:-3], ROOT / "submissions" / name
    if not d.is_dir():
        pytest.skip(f"{name} not made yet")
    fresh = tmp_path / name
    make_t0.make_t0(src, fresh)
    assert all_files(fresh) == all_files(d)
    for rel in sorted(all_files(d)):
        assert filecmp.cmp(fresh / rel, d / rel, shallow=False), rel
    text = (d / "configs" / "sampling.yaml").read_text()
    assert re.search(r"^thinking_config:\n  thinking_budget: 0\n", text, re.M), text


T0_KERNELS = {"g4-l4-v7c-t0-p312": ("v7c-t0", "g4-eval-v2-smoke"), "g4-l4-v5h2-t0-p312": ("v5h2-t0", "g4-eval74-v4"),
              "g4-l4-v11b-probe-t0-p312": ("v4h2g_v11b_probe-t0", "g4-eval74-v2")}   # the Saturday queue, on its three slugs


@pytest.mark.parametrize("kdir", sorted(T0_KERNELS))
def test_the_t0_kernels_ship_the_t0_bundle_bytes_on_the_queues_slugs(kdir):
    """kernels/ is gitignored (generated on the Mac): when a -t0 kernel dir is present it runs as the slug its non-t0 twin
    used, ships exactly the -t0 bundle, and its notebook differs from the twin's only in the FILES payload."""
    import base64, json
    bundle, slug = T0_KERNELS[kdir]
    kd = ROOT / "kernels" / kdir
    if not (kd / "kernel-metadata.json").exists():
        pytest.skip(f"kernels/{kdir} not generated on this machine")
    meta = json.loads((kd / "kernel-metadata.json").read_text())
    assert meta["id"] == "carsonrodrigues/" + slug and meta.get("enable_gpu") is True and meta.get("docker_image_pinning_type") == "original"
    nb = json.loads((kd / f"{slug}.ipynb").read_text())
    data = next(c["source"] for c in nb["cells"] if c["source"].startswith("FILES = "))
    files = json.loads(data[len("FILES = "):data.index("\nIDS = ")])
    want = ROOT / "submissions" / bundle
    shipped = {k: base64.b64decode(v) for k, v in files.items() if not k.startswith("adapters/")}
    assert shipped == {rel: (want / rel).read_bytes() for rel in all_files(want) if not rel.startswith("adapters/")}
    assert b"thinking_budget: 0" in shipped["configs/sampling.yaml"]
    twin = ROOT / "kernels" / kdir.replace("-t0", "")
    if (twin / f"{slug}.ipynb").exists():
        a = [c["source"] for c in json.loads((twin / f"{slug}.ipynb").read_text())["cells"]]
        b = [c["source"] for c in nb["cells"]]
        assert len(a) == len(b) and all(x == y for x, y in zip(a, b) if not x.startswith("FILES = "))
