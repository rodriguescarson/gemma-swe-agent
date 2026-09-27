"""Behaviour of the v9 helper scripts on a throwaway git repo (flat package + tests)."""
import os, pathlib, subprocess, sys, textwrap, pytest
H = pathlib.Path(__file__).resolve().parents[1] / "helpers_v9"

@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "ws"; (r / "pkg").mkdir(parents=True); (r / "tests").mkdir()
    (r / "pkg/__init__.py").write_text("")
    (r / "pkg/mathx.py").write_text("def add_numbers(a, b):\n    return a + b\n\ndef sub_numbers(a, b):\n    return a - b\n")
    (r / "tests/test_mathx.py").write_text(textwrap.dedent("""
        from pkg.mathx import add_numbers, sub_numbers
        def test_add(): assert add_numbers(2, 3) == 5
        def test_sub(): assert sub_numbers(5, 3) == 2
        def test_sub_neg(): assert sub_numbers(0, 3) == -3
    """))
    for c in ("git init -q", "git add -A", "git -c user.email=a@b -c user.name=t commit -qm init"):
        subprocess.run(c, cwd=r, shell=True, check=True)
    return r

def run(tool, args, repo, stdin=None):
    env = dict(os.environ, SWE_WS=str(repo))
    return subprocess.run([sys.executable, str(H / tool), *args], input=stdin, capture_output=True, text=True,
                          env=env, cwd=repo, timeout=120).stdout

def test_replace_edits_range_and_shows_context(repo):
    out = run("replace.py", ["--file", "pkg/mathx.py", "--start", "2", "--end", "2"], repo, "    return a + b + 0  # \\x1b stays raw\n")
    assert out.startswith("OK") and "\\x1b stays raw" in (repo / "pkg/mathx.py").read_text()

def test_replace_reverts_on_syntax_error(repo):
    before = (repo / "pkg/mathx.py").read_text()
    out = run("replace.py", ["--file", "pkg/mathx.py", "--start", "2", "--end", "2"], repo, "    return (a +\n")
    assert out.startswith("REVERTED") and (repo / "pkg/mathx.py").read_text() == before

def test_replace_insert_and_bad_range(repo):
    assert run("replace.py", ["--file", "pkg/mathx.py", "--start", "1", "--end", "0"], repo, "import math\n").startswith("OK")
    assert (repo / "pkg/mathx.py").read_text().startswith("import math\n")
    assert "outside file" in run("replace.py", ["--file", "pkg/mathx.py", "--start", "90", "--end", "95"], repo, "x\n")

def test_run_strips_ansi_truncates_and_times_out(repo):
    out = run("run.py", ["python3 -c \"print('\\x1b[31mred\\x1b[0m'); [print(i) for i in range(3000)]\""], repo)
    assert "\x1b" not in out and "red" in out and "middle cut" in out and len(out) < 4000
    assert "TIMEOUT after 1s" in run("run.py", ["--timeout", "1", "sleep 5"], repo)

def test_gate_reports_regression_and_leaves_workspace(repo):
    (repo / "pkg/mathx.py").write_text("def add_numbers(a, b):\n    return a + b\n\ndef sub_numbers(a, b):\n    return abs(a - b)\n")
    out = run("gate.py", [], repo)
    assert "tests/test_mathx.py::test_sub_neg" in out.split("NEWLY PASSING")[0] and "GATE: FAIL" in out
    assert "abs(" in (repo / "pkg/mathx.py").read_text()  # workspace untouched

def test_gate_pass_and_no_change(repo):
    assert "NO SOURCE CHANGE" in run("gate.py", [], repo)
    (repo / "pkg/mathx.py").write_text("def add_numbers(a, b):\n    return b + a\n\ndef sub_numbers(a, b):\n    return a - b\n")
    assert "GATE: PASS" in run("gate.py", [], repo)
