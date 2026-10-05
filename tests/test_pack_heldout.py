"""scripts/heldout/pack_heldout.py: heldout1k rows -> the Pallets harness layout (scripts/pallets/pack.py) on three small
synthetic tasks in two fake repos (fake clones, a fake wheel cache, no network, no Docker).

Checked: tasks.jsonl carries exactly harness_holdout's keys; each snapshot is a single-commit repo whose tree equals
base_commit (no history objects), with the competition identity; the miner's env recipe (python, freeze, own package,
scm-version prep) is carried into env.json and wheels/_extra-<REPO_PKG>.txt; packing twice gives identical bytes."""
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import zipfile
from importlib import metadata as importlib_metadata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "heldout"))
import pack_heldout as P  # noqa: E402

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main",
       "-c", "protocol.file.allow=always"]
HOLDOUT_KEYS = ("instance_id", "repo", "base_commit", "patch", "test_patch", "problem_statement", "hints_text",
                "created_at")


def sh(*a, cwd=None):
    return subprocess.run([*GIT, *a] if a[0] != "raw" else list(a[1:]), cwd=cwd, check=True, capture_output=True,
                          text=True, env={**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
                                          "GIT_AUTHOR_DATE": "2024-01-02T03:04:05Z",
                                          "GIT_COMMITTER_DATE": "2024-01-02T03:04:05Z"}).stdout.strip()


def commit(repo, files, msg):
    for rel, body in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    sh("-C", str(repo), "add", "-A")
    sh("-C", str(repo), "commit", "-qm", msg)
    return sh("-C", str(repo), "rev-parse", "HEAD")


@pytest.fixture()
def world(tmp_path):
    """clones/acme_widget (src layout, hatch-vcs version file, 3 commits) and clones/httpie_cli (flat, a submodule)."""
    clones = tmp_path / "clones"
    a = clones / "acme_widget"
    a.mkdir(parents=True)
    sh("init", "-q", str(a))
    pyproject = ('[project]\nname = "widget"\n[tool.hatch.build.hooks.vcs]\nversion-file = "src/widget/_version.py"\n')
    c1 = commit(a, {"pyproject.toml": pyproject, ".gitignore": "src/widget/_version.py\n",
                    "src/widget/__init__.py": "X = 1\n",
                    "src/widget/core.py": "def f():\n    return g()\n\n\ndef g():\n    return 1\n", "tests/test_w.py": "def test_x():\n    assert True\n"}, "one")
    c2 = commit(a, {"src/widget/__init__.py": "X = 2\n", "big_history_blob.txt": "h" * 5000}, "two")
    commit(a, {"src/widget/__init__.py": "X = 3\n"}, "three")
    # a submodule repo, gitlinked into the flat repo at tests/suite
    sub = tmp_path / "suite_src"
    sub.mkdir()
    sh("init", "-q", str(sub))
    commit(sub, {"case.toml": "a = 1\n"}, "s")
    b = clones / "httpie_cli"
    b.mkdir()
    sh("init", "-q", str(b))
    commit(b, {"httpie/__init__.py": "V = 1\n", "tests/test_h.py": "def test_v():\n    pass\n"}, "h1")
    sh("-C", str(b), "submodule", "add", "-q", str(sub), "tests/suite")
    commit(b, {"run.sh": "#!/bin/sh\necho hi\n"}, "h2")
    sh("-C", str(b), "update-index", "--chmod=+x", "run.sh")
    sh("-C", str(b), "commit", "-qm", "exec bit")
    c3 = sh("-C", str(b), "rev-parse", "HEAD")

    def row(tid, repo, base, deps, title_only=False):
        return {"instance_id": tid, "repo": repo, "base_commit": base, "fix_commit": "f" * 40, "pr_number": 7,
                "created_at": "2024-01-01T00:00:00Z", "merged_at": "2024-01-02T00:00:00Z",
                "problem_statement": f"Fix {tid}\n\nbody", "statement_title_only": title_only, "hints_text": "",
                "patch": "diff --git a/x b/x\n", "test_patch": "diff --git a/tests/t b/tests/t\n",
                "test_files": ["tests/test_w.py"], "FAIL_TO_PASS": ["tests/test_w.py::test_x"], "PASS_TO_PASS": [],
                "env": {"python": "3.12.14", "deps": deps, "env_id": repo.split("/")[1] + "-2024-01-02"},
                "validation": {"os": "darwin", "base_rc": 1, "gold_rc": [0, 0]}}

    wdeps = ["iniconfig==2.3.0", "pytest==8.4.2", "widget==1.0.0", "zope-interface==8.6"]
    hdeps = ["httpie==3.2.4", "pytest==8.4.2", "requests==2.34.2", "widget==1.0.0"]   # widget = acme/widget's own
    rows = [row("widget_aaa1111", "acme/widget", c1, wdeps), row("widget_bbb2222", "acme/widget", c2, wdeps, True),
            row("httpie_ccc3333", "httpie/cli", c3, hdeps)]
    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text("".join(json.dumps(r) + "\n" for r in rows))
    ids = tmp_path / "ids.txt"
    ids.write_text("httpie_ccc3333\nwidget_aaa1111\nwidget_bbb2222\n")
    wheels = tmp_path / "wheelcache"
    wheels.mkdir()
    for f in ("iniconfig-2.3.0-py3-none-any.whl", "pytest-8.4.2-py3-none-any.whl", "flit_core-3.12.0-py3-none-any.whl",
              "zope_interface-8.6-cp312-cp312-manylinux_2_17_x86_64.whl",
              "zope_interface-8.6-cp312-cp312-manylinux_2_17_aarch64.whl", "requests-2.34.2-py3-none-any.whl",
              "widget-1.0.0-py3-none-any.whl", "unrelated-9.9-py3-none-any.whl"):
        (wheels / f).write_bytes(b"w:" + f.encode())
    # the own distribution as a real wheel: code + dist-info (METADATA, entry points)
    with zipfile.ZipFile(wheels / "widget-1.0.0-py3-none-any.whl", "w") as z:
        z.writestr("widget/__init__.py", "X = 'released'\n")
        z.writestr("widget-1.0.0.dist-info/METADATA", "Metadata-Version: 2.1\nName: widget\nVersion: 1.0.0\n")
        z.writestr("widget-1.0.0.dist-info/entry_points.txt", "[pytest11]\nwidget = widget.plugin\n")
        z.writestr("widget-1.0.0.dist-info/WHEEL", "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        z.writestr("widget-1.0.0.dist-info/RECORD", "")
    return {"tmp": tmp_path, "clones": clones, "tasks": tasks, "ids": ids, "wheels": wheels, "rows": rows,
            "c1": c1, "c2": c2, "c3": c3, "sub": sub}


def pack(world, out, *extra):
    argv = ["--tasks", str(world["tasks"]), "--ids", str(world["ids"]), "--out", str(out), "--clones",
            str(world["clones"]), "--wheel-cache", str(world["wheels"]), "--no-fetch", "--no-graphs", *extra]
    assert P.main(argv) == 0
    return out


def extract(tgz, dest):
    dest.mkdir(parents=True)
    with tarfile.open(tgz) as t:
        t.extractall(dest, filter="tar")
    return dest


def test_tasks_jsonl_has_exactly_the_holdout_harness_keys_in_ids_order(world, tmp_path):
    out = pack(world, tmp_path / "h")
    rows = [json.loads(ln) for ln in (out / "tasks.jsonl").read_text().splitlines()]
    hold = ROOT / "data" / "pallets" / "harness_holdout" / "tasks.jsonl"
    keys = tuple(json.loads(hold.open().readline())) if hold.is_file() else HOLDOUT_KEYS
    assert set(keys) == set(HOLDOUT_KEYS)
    assert [tuple(r) for r in rows] == [keys] * 3
    assert [r["instance_id"] for r in rows] == ["httpie_ccc3333", "widget_aaa1111", "widget_bbb2222"]
    src = {r["instance_id"]: r for r in world["rows"]}
    for r in rows:
        for k in keys:
            assert r[k] == src[r["instance_id"]][k]
    assert (out / "ids.txt").read_text() == "httpie_ccc3333\nwidget_aaa1111\nwidget_bbb2222\n"


def test_snapshot_is_a_single_commit_repo_at_base_commit(world, tmp_path):
    out = pack(world, tmp_path / "h")
    tgz = out / "snapshots" / "widget_bbb2222.tgz"
    with tarfile.open(tgz) as t:
        names = t.getnames()
    assert names[0] == "." and all(n.startswith("./") for n in names[1:])   # the Pallets member style
    ws = extract(tgz, tmp_path / "x")
    log = sh("-C", str(ws), "log", "--format=%s").splitlines()
    assert log == ["baseline"]
    # the tree is exactly base_commit's tree: same paths, same blob ids
    want = sh("-C", str(world["clones"] / "acme_widget"), "ls-tree", "-r", world["c2"])
    got = sh("-C", str(ws), "ls-tree", "-r", "HEAD")
    assert got == want
    assert (ws / "src" / "widget" / "__init__.py").read_text() == "X = 2\n"
    # no history: neither base_commit nor its parent is in the object store
    for c in (world["c1"], world["c2"]):
        assert subprocess.run(["git", "-C", str(ws), "cat-file", "-e", c], capture_output=True).returncode != 0
    cfg = (ws / ".git" / "config").read_text()
    assert "email = agent@eval" in cfg and "name = Agent" in cfg
    assert "ignorecase" not in cfg and "precomposeunicode" not in cfg  # macOS git-init keys never reach the Linux harness
    assert sh("-C", str(ws), "status", "--porcelain") == ""             # clean worktree after extraction
    assert (ws / ".git" / "info").is_dir()                              # the harness appends to .git/info/exclude


def test_snapshot_keeps_exec_bits_and_vendors_submodules(world, tmp_path):
    out = pack(world, tmp_path / "h")
    ws = extract(out / "snapshots" / "httpie_ccc3333.tgz", tmp_path / "x")
    assert os.access(ws / "run.sh", os.X_OK)
    assert (ws / "tests" / "suite" / "case.toml").read_text() == "a = 1\n"   # submodule content at its gitlink
    assert not (ws / "tests" / "suite" / ".git").exists()
    env = json.loads((out / "env.json").read_text())
    assert env["httpie_ccc3333"]["submodules"] == ["tests/suite"]


def test_scm_version_prep_is_applied_and_left_untracked(world, tmp_path):
    out = pack(world, tmp_path / "h")
    ws = extract(out / "snapshots" / "widget_aaa1111.tgz", tmp_path / "x")
    assert (ws / "src" / "widget" / "_version.py").read_text().startswith('__version__ = version = "0.0.0"')
    assert sh("-C", str(ws), "status", "--porcelain") == ""             # gitignored, as after `pip install -e`
    env = json.loads((out / "env.json").read_text())
    assert env["widget_aaa1111"]["prep"] == ["src/widget/_version.py"]
    assert env["httpie_ccc3333"]["prep"] == []


def test_env_recipe_is_carried_into_env_json_and_extra_files(world, tmp_path):
    out = pack(world, tmp_path / "h")
    env = json.loads((out / "env.json").read_text())
    w = env["widget_aaa1111"]
    assert w["python"] == "3.12.14" and w["venv"] == "widget-2024-01-02"
    assert w["pins"] == world["rows"][0]["env"]["deps"]
    assert w["own"] == "widget" and w["statement"] == "pr"
    assert env["widget_bbb2222"]["statement"] == "title_only"
    # one _extra file per REPO_PKG (= repo short name, lower-case, as run_eval.faithful_install computes it): the miner's
    # full freeze INCLUDING the repo's own distribution. Its metadata is part of the validation venv (isort's
    # _version.py calls importlib.metadata.version("isort"); preflight run 1 without it: 12/12 isort gold collection
    # errors); the code itself still comes from /workspace, which precedes site-packages
    # Pins are `===` (string-exact), so no repo can be served another repo's metadata-only stub of a shared package
    # (packaging, pluggy, attrs are both an own distribution and someone else's dependency); the own distribution is
    # pinned to its stub's local version
    assert (out / "wheels" / "_extra-widget.txt").read_text() == \
        "iniconfig===2.3.0\npytest===8.4.2\nwidget==1.0.0+g4meta\nzope-interface===8.6\n"
    assert (out / "wheels" / "_extra-cli.txt").read_text() == "httpie==3.2.4+g4meta\npytest===8.4.2\nrequests===2.34.2\nwidget===1.0.0\n"


def test_wheelhouse_holds_exactly_the_pins_for_both_arches(world, tmp_path):
    out = pack(world, tmp_path / "h")
    whl = sorted(f.name for f in (out / "wheels").glob("*.whl"))
    assert "unrelated-9.9-py3-none-any.whl" not in whl
    assert "widget-1.0.0+g4meta-py3-none-any.whl" in whl                # own distribution: metadata-only stub
    # ... and the real wheel too, because httpie's freeze needs widget's code (s200 run 3: isort lost black, httpie
    # lost mistune when the real wheel of another repo's own distribution was dropped)
    assert "widget-1.0.0-py3-none-any.whl" in whl
    assert {"zope_interface-8.6-cp312-cp312-manylinux_2_17_x86_64.whl",
            "zope_interface-8.6-cp312-cp312-manylinux_2_17_aarch64.whl", "flit_core-3.12.0-py3-none-any.whl",
            "requests-2.34.2-py3-none-any.whl"} <= set(whl)
    man = json.loads((out / "manifest.json").read_text())
    assert man["missing_wheels"] == ["httpie==3.2.4"]                   # no wheel for it in the fake cache
    assert man["n_tasks"] == 3


def test_missing_pin_is_reported_not_invented(world, tmp_path):
    (world["wheels"] / "requests-2.34.2-py3-none-any.whl").unlink()
    out = pack(world, tmp_path / "h")
    man = json.loads((out / "manifest.json").read_text())
    assert "requests==2.34.2" in man["missing_wheels"]
    assert not list((out / "wheels").glob("requests-*"))


def digest(d):
    h = {}
    for p in sorted(Path(d).rglob("*")):
        if p.is_file() and p.name != "manifest.json":
            h[str(p.relative_to(d))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return h


def test_packing_is_deterministic(world, tmp_path):
    a = digest(pack(world, tmp_path / "a"))
    b = digest(pack(world, tmp_path / "b"))
    assert a == b and len([k for k in a if k.endswith(".tgz")]) == 3


def test_repack_skips_up_to_date_snapshots(world, tmp_path):
    out = pack(world, tmp_path / "h")
    tgz = out / "snapshots" / "widget_aaa1111.tgz"
    m0 = tgz.stat().st_mtime_ns
    pack(world, out)
    assert tgz.stat().st_mtime_ns == m0


def test_graph_files_use_the_harness_key(world, tmp_path, monkeypatch):
    calls = []

    def fake_embed(graph_json, npz, python):
        calls.append(Path(graph_json).name)
        Path(npz).write_bytes(b"x" * 200)
        return True

    monkeypatch.setattr(P, "build_embeddings", fake_embed)
    argv = ["--tasks", str(world["tasks"]), "--ids", str(world["ids"]), "--out", str(tmp_path / "h"), "--clones",
            str(world["clones"]), "--wheel-cache", str(world["wheels"]), "--no-fetch"]
    assert P.main(argv) == 0
    g = tmp_path / "h" / "graphs" / f"widget_{world['c1']}.json"       # <repo short>_<base_commit> (graph_repo_key)
    assert g.is_file() and (tmp_path / "h" / "embeddings" / f"widget_{world['c1']}.npz").is_file()
    data = json.loads(g.read_text())
    assert {"directed", "multigraph", "nodes", "edges"} <= set(data)
    assert {"src.widget.core.f", "src.widget.core.g"} <= {n["id"] for n in data["nodes"]}
    assert {"source": "src.widget.core.f", "target": "src.widget.core.g", "type": "calls", "key": 0} in data["edges"]
    assert (tmp_path / "h" / "graphs" / f"cli_{world['c3']}.json").is_file()   # httpie/cli -> repo short "cli"
    assert len(calls) == 3


def test_unknown_id_fails_loudly(world, tmp_path):
    world["ids"].write_text("nope_123\n")
    with pytest.raises(SystemExit):
        pack(world, tmp_path / "h")


def test_own_distribution_ships_as_a_metadata_only_wheel(world, tmp_path):
    """The miner's venv gave the repo's own distribution for importlib.metadata only (code from the workspace via
    PYTHONPATH). Installed as a real wheel it shadows /workspace/src (site-packages precedes .pth paths): preflight
    run 2 lost black 4/5, cattrs 13/13, cleo 1/2 that resolved in run 1. So the stub keeps dist-info, drops the code."""
    out = pack(world, tmp_path / "h")
    stub = out / "wheels" / "widget-1.0.0+g4meta-py3-none-any.whl"
    di = "widget-1.0.0+g4meta.dist-info"
    with zipfile.ZipFile(stub) as z:
        names = sorted(z.namelist())
        assert all(n.startswith(di + "/") for n in names)
        assert z.read(f"{di}/METADATA").decode() == "Metadata-Version: 2.1\nName: widget\nVersion: 1.0.0+g4meta\n"
        assert b"[pytest11]" in z.read(f"{di}/entry_points.txt")
        rec = z.read(f"{di}/RECORD").decode()
        assert all(n in rec for n in names)
        z.extractall(tmp_path / "site")
    d = next(importlib_metadata.distributions(name="widget", path=[str(tmp_path / "site")]))
    assert d.version == "1.0.0+g4meta"
    other = digest(pack(world, tmp_path / "h2"))["wheels/widget-1.0.0+g4meta-py3-none-any.whl"]
    assert other == hashlib.sha256(stub.read_bytes()).hexdigest()        # deterministic zip


def test_real_own_wheel_dropped_when_no_other_repo_needs_it(world, tmp_path):
    world["ids"].write_text("widget_aaa1111\n")
    out = pack(world, tmp_path / "h")
    whl = {f.name for f in (out / "wheels").glob("*.whl")}
    assert "widget-1.0.0+g4meta-py3-none-any.whl" in whl and "widget-1.0.0-py3-none-any.whl" not in whl
