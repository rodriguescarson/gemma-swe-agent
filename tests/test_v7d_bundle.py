"""v7d = v7c with step 1 of docs/a6000/V7C_FAILURE_ANALYSIS.md (the box's analysis of the v7c run, 2026-10-08): view.py
never answers a re-read with a bare refusal. Built in a new directory so v7c stays byte-identical (it is still running on
the A6000 and queued on Kaggle). Strict test-first: step 1, v7d was an exact copy (cp -a, byte-identical with the same
modes: commit "v7d step 1"); every later step names the files it may change.

  fix 1   view.py prints the lines of an identical re-read of an unchanged range again, under one SHOWN AGAIN line (the
          3rd identical re-read in a row still gets v7c's outline); _ws.py changes only in its docstring
          (tests/test_v7d_helpers.py, tests/test_v7d_sandbox.py)
  wording the two prompt spans that promised a refusal (locator.md, fixer.md) and the locator.yaml arithmetic comment
          say what view.py does now, every other line unchanged (tests/test_v7d_prompts.py, below)

No kernel yet: the plan re-probes on the A6000 (docs/a6000/V7C_FAILURE_ANALYSIS.md, section 3) before a Kaggle slot is
spent, and the Kaggle queue (v7c -> v5h2 -> v11b probe) is Carson's to change."""
import filecmp, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUB = ROOT / "submissions"
V7C, V7D = SUB / "v7c", SUB / "v7d"
CHANGED = set()


def all_files(d):
    """Every file under d, hidden ones included (a stray .DS_Store or __pycache__ is a difference too)."""
    return {str(p.relative_to(d)) for p in d.rglob("*") if p.is_file()}


def changed(a, b):
    return {rel for rel in all_files(a) & all_files(b) if not filecmp.cmp(a / rel, b / rel, shallow=False)}


def test_v7d_differs_from_v7c_only_in_the_listed_files():
    assert all_files(V7D) == all_files(V7C), all_files(V7D) ^ all_files(V7C)
    assert changed(V7C, V7D) == CHANGED, changed(V7C, V7D) ^ CHANGED
    for rel in sorted(all_files(V7C)):
        assert os.stat(V7C / rel).st_mode == os.stat(V7D / rel).st_mode, rel


# ------------------------------------------------------------------ the compiled tree, the helpers, packing

def test_the_official_compiler_builds_v7d_with_v7cs_tree():
    import ast, re
    from test_v7_bundle import TREE
    from test_v7b_bundle import compiled
    tree = compiled(V7D)
    assert tree == compiled(V7C)                                        # same stages, tools, models and sampling
    got = {m.group(1): ast.literal_eval(m.group(2)) for m in re.finditer(r"^\s*LlmAgent (\w+) model=\S+ tools=(\[.*\])$", "\n".join(tree), re.M)}
    assert got == TREE, got


def test_every_helper_installs_into_the_sandbox_tmp_and_every_prompt_helper_is_probed_on_kaggle(tmp_path):
    import json, subprocess, sys
    from test_v7_bundle import helpers_used, probe_keys
    scripts = V7D / "skills" / "swe-tools" / "scripts"
    helpers = {p.name for p in scripts.glob("*.py")} - {"install.py"}
    assert helpers == {"_ws.py", "check.py", "edit.py", "locate.py", "test.py", "view.py"}
    env = dict(os.environ, TMPDIR=str(tmp_path), TEST_TMPDIR=str(tmp_path), PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run([sys.executable, str(scripts / "install.py")], capture_output=True, text=True, env=env, cwd=tmp_path)
    assert p.returncode == 0 and "helpers in" in p.stdout, p.stdout + p.stderr
    assert all((tmp_path / "swe" / h).read_bytes() == (scripts / h).read_bytes() for h in helpers)
    assert json.loads((tmp_path / "swe" / ".ledger.json").read_text()) == {"locate": 0, "view": 0, "edited": False,
                                                                         "repeat_key": None, "repeat_run": 0}
    used = helpers_used(V7D)
    assert used == helpers - {"_ws.py"} == helpers_used(V7C), used       # _ws.py is a module the probed helpers import
    assert used <= probe_keys(), used - probe_keys()


def test_packs_small_and_complete(tmp_path):
    import subprocess, sys, zipfile
    z = tmp_path / "v7d.zip"
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "pack_bundle.py"), str(V7D), str(z)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert z.stat().st_size < 100_000
    names = zipfile.ZipFile(z).namelist()
    assert sorted(names) == sorted(all_files(V7D)) and not any("__pycache__" in n or n.endswith(".pyc") for n in names)
