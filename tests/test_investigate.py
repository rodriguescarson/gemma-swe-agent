"""investigate.py must stay under the harness's 5,000-char command-output cap and surface the definition of issue identifiers."""
import os, subprocess, sys, pathlib, shutil
ROOT = pathlib.Path(__file__).parent.parent
S = ROOT / "submissions/v7/skills/swe-tools/scripts"

def repo(tmp_path):
    w = tmp_path / "ws"; (w / "pkg").mkdir(parents=True); (w / "tests").mkdir()
    (w / "pkg/__init__.py").write_text("")
    (w / "pkg/core.py").write_text("def helper():\n    return 1\n\ndef parse_header(value):\n" + "    x = 1\n" * 60 + "    return value.split(';')[0]\n")
    (w / "tests/test_core.py").write_text("from pkg.core import parse_header\ndef test_p():\n    assert parse_header('a;b') == 'a'\n")
    for c in (["git", "init", "-q"], ["git", "add", "-A"], ["git", "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "b"]):
        subprocess.run(c, cwd=w, check=True)
    tmp = tmp_path / "_s"; shutil.copytree(S, tmp)
    return w, tmp

def run(w, tmp, q):
    env = {**os.environ, "SWE_WS": str(w), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, str(tmp / "investigate.py"), q], cwd=w, env=env, capture_output=True, text=True)

def test_finds_definition_and_tests_within_budget(tmp_path):
    w, tmp = repo(tmp_path)
    r = run(w, tmp, "`parse_header` drops the value after ';' incorrectly")
    assert r.returncode == 0, r.stderr
    assert "defined: parse_header -> pkg/core.py:4" in r.stdout
    assert "1. pkg/core.py" in r.stdout and "tests/test_core.py" in r.stdout
    assert len(r.stdout) <= 5000

def test_snippet_centres_on_issue_identifier_not_function_header(tmp_path):
    w, tmp = repo(tmp_path)
    r = run(w, tmp, "`parse_header` should handle `split` of value")
    assert "value.split" in r.stdout            # the relevant line (L65) is inside the window, not just the def line
