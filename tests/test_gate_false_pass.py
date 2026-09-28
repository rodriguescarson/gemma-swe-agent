"""Regression (2026-09-28, found by the pain-point sweep, reproduced locally): the shipped gate printed
'GATE: PASS' when the patched package crashed at import (collection error) and when pytest was missing.
Applies to helpers_v9/gate.py and, once it exists, to v10's gate."""
import os, pathlib, re, subprocess, sys, textwrap, pytest
ROOT = pathlib.Path(__file__).resolve().parents[1]
GATES = [p for p in (ROOT / "helpers_v9/gate.py", ROOT / "submissions/v10/skills/swe-tools/scripts/gate.py") if p.exists()]
PASS_VERDICT = re.compile(r"GATE:\s*PASS|verdict\W+pass\b", re.I)

@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "ws"; (r / "pkg").mkdir(parents=True); (r / "tests").mkdir()
    (r / "pkg/__init__.py").write_text("")
    (r / "pkg/mod.py").write_text("def parse_value(x):\n    return x\n")
    (r / "tests/test_mod.py").write_text("from pkg.mod import parse_value\ndef test_parse(): assert parse_value(1) == 1\n")
    for c in ("git init -q", "git add -A", "git -c user.email=a@b -c user.name=t commit -qm i"):
        subprocess.run(c, cwd=r, shell=True, check=True)
    return r

def _gate(gate, repo, python=sys.executable):
    env = dict(os.environ, SWE_WS=str(repo), TMPDIR=str(repo.parent / "tmp")); (repo.parent / "tmp").mkdir(exist_ok=True)
    r = subprocess.run([python, str(gate)], cwd=repo, env=env, capture_output=True, text=True, timeout=180)
    return r.stdout + r.stderr

@pytest.mark.parametrize("gate", GATES, ids=lambda p: p.parts[-5] if "submissions" in p.parts else "helpers_v9")
def test_import_crash_is_not_a_pass(gate, repo):
    (repo / "pkg/mod.py").write_text("def parse_value(x):\n    return x\nraise ImportError('boom at import')\n")
    out = _gate(gate, repo)
    assert not PASS_VERDICT.search(out), out[-800:]
    assert re.search(r"FAIL|BROKEN|import|collect", out, re.I), out[-800:]

@pytest.mark.parametrize("gate", GATES, ids=lambda p: p.parts[-5] if "submissions" in p.parts else "helpers_v9")
def test_missing_pytest_is_not_a_pass(gate, repo, tmp_path):
    venv = tmp_path / "nopytest"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True)
    (repo / "pkg/mod.py").write_text("def parse_value(x):\n    return x + 0\n")
    out = _gate(gate, repo, python=str(venv / "bin/python"))
    assert not PASS_VERDICT.search(out), out[-800:]

@pytest.mark.parametrize("gate", GATES, ids=lambda p: p.parts[-5] if "submissions" in p.parts else "helpers_v9")
def test_real_regression_still_fails_and_clean_change_passes(gate, repo):
    (repo / "pkg/mod.py").write_text("def parse_value(x):\n    return x + 1\n")
    assert re.search(r"FAIL", _gate(gate, repo))
    (repo / "pkg/mod.py").write_text("def parse_value(x):\n    return (x)\n")
    assert PASS_VERDICT.search(_gate(gate, repo))
