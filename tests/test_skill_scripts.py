"""fork.py / select.py behaviour on a tiny git repo: candidate copies never enter the patch; test-only edits are ignored."""
import os, subprocess, sys, pathlib, shutil
ROOT = pathlib.Path(__file__).parent.parent
S = ROOT / "submissions/v5/skills/swe-tools/scripts"

def repo(tmp_path):
    w = tmp_path / "ws"; (w / "pkg").mkdir(parents=True); (w / "tests").mkdir()
    (w / "pkg/__init__.py").write_text(""); (w / "pkg/m.py").write_text("def f():\n    return 1\n")
    (w / "tests/test_m.py").write_text("from pkg.m import f\ndef test_f():\n    assert f() == 2\n")
    for c in (["git", "init", "-q"], ["git", "add", "-A"], ["git", "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "b"]):
        subprocess.run(c, cwd=w, check=True)
    return w

def run(script, w, *args):
    # run from a temp copy with bytecode disabled so tests never leave __pycache__ inside a submission bundle
    tmp = w.parent / "_scripts"
    if not tmp.exists(): shutil.copytree(S, tmp)
    env = {**os.environ, "SWE_WS": str(w), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, str(tmp / script), *args], cwd=w, env=env, capture_output=True, text=True)

def test_fork_copies_are_invisible_to_git(tmp_path):
    w = repo(tmp_path); run("fork.py", w)
    assert (w / ".cand_a/pkg/m.py").exists()
    assert subprocess.run(["git", "status", "--porcelain"], cwd=w, capture_output=True, text=True).stdout.strip() == ""

def test_select_applies_best_source_change_and_ignores_test_edits(tmp_path):
    w = repo(tmp_path); run("fork.py", w)
    (w / ".cand_b/pkg/m.py").write_text("def f():\n    return 2\n")              # real fix
    (w / ".cand_c/tests/test_m.py").write_text("def test_f():\n    pass\n")       # cheating edit
    r = run("pick_candidate.py", w, "--target", "tests/test_m.py")
    assert "APPLIED .cand_b" in r.stdout, r.stdout + r.stderr
    assert (w / "pkg/m.py").read_text().endswith("return 2\n")
    assert (w / "tests/test_m.py").read_text().endswith("== 2\n")

def test_select_reports_when_no_candidate(tmp_path):
    w = repo(tmp_path); run("fork.py", w)
    assert "NO USABLE CANDIDATE" in run("pick_candidate.py", w, "--target", "tests/test_m.py").stdout
