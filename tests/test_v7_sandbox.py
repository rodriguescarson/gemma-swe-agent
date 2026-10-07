"""v7 in the harness's real subprocess sandbox (swegemma.sandbox.subprocess.SubprocessManager: /tmp and /workspace are
rewritten in command text, TMPDIR is the sandbox's own tmp, PYTHONPATH the workspace; research/harness_runtime.md 2.3-2.4).
No model: the exact shell lines the v7 prompts show, in stage order (the pattern of tests/test_v6p_sandbox.py).

  fix 4  the verifier's repro: the quoted heredoc writes /tmp/repro.py into the sandbox tmp through run_command (write_file
         refuses any path outside the workspace), and `python3 /tmp/repro.py; echo EXIT=$?` says EXIT=1 before the fix and
         EXIT=0 after it
  fix 9  the cap ledger lives in the sandbox tmp next to view.py's views log, like the helpers themselves
  fix 1  view.py's range shapes through the rewrite. Written before the changes."""
import json, re, uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
V7 = ROOT / "submissions" / "v7"
SCRIPTS = V7 / "skills" / "swe-tools" / "scripts"
sub = pytest.importorskip("swegemma.sandbox.subprocess")
READ_CAP = "read cap reached before any edit: edit now with edit.py (fixer) or write the plan (locator)"
SEARCH_CAP = "search cap reached: use `git grep -n <name>` or write the plan now"


@pytest.fixture
def m():
    mgr = sub.SubprocessManager(timeout_seconds=60, system_site_packages=True)
    mgr.initialize({"pkg/__init__.py": "", "pkg/mod.py": "def f(x):\n    return x\n",
                    "tests/test_mod.py": "from pkg.mod import f\n\n\ndef test_f():\n    assert f(2) == 4\n",
                    "m.py": "".join(f"line{i}\n" for i in range(1, 301))})
    mgr.run_command("git init -q && git add -A && git -c user.email=a@b -c user.name=t commit -qm baseline")
    mgr.run_command("printf '.adk_exec_*.py\\n__pycache__/\\n' >> .git/info/exclude")
    yield mgr
    mgr.cleanup_all()


def skill(m, script, argv=()):
    """Like ADK's run_skill_script on the subprocess backend: a wrapper file in the workspace copies the skill into a
    TemporaryDirectory, chdirs there and runpy's the script (the setup stage's install)."""
    code = ("import os, runpy, shutil, sys, tempfile\n"
            f"src = {str(SCRIPTS)!r}\n"
            "with tempfile.TemporaryDirectory() as td:\n"
            "    shutil.copytree(src, os.path.join(td, 'scripts')); os.chdir(td)\n"
            f"    sys.argv = {['scripts/' + script] + list(argv)!r}\n"
            f"    runpy.run_path('scripts/{script}', run_name='__main__')\n")
    m.write_file(".adk_exec_v7.py", code)
    out = m.run_command(f"python3 {m.work_dir}/.adk_exec_v7.py")
    return out.stdout + out.stderr


def sandbox_tmp(m):
    return Path(m.run_command("echo $TMPDIR").stdout.strip())


def verifier_repro_lines():
    """The two repro shell lines exactly as verifier.md shows them: the heredoc block and the run line."""
    v = (V7 / "prompts" / "verifier.md").read_text()
    lines = v.splitlines()
    i = lines.index("cat > /tmp/repro.py <<'EOF'")
    j = lines.index("EOF", i)
    run = re.search(r"`(python3 /tmp/repro\.py; echo EXIT=\$\?)`", v).group(1)
    return lines[i], run


def test_the_verifier_repro_runs_in_the_sandbox_tmp_and_reports_exit_before_and_after_the_fix(m):
    assert "installed:" in skill(m, "install.py")
    head, run = verifier_repro_lines()
    mark = uuid.uuid4().hex
    r = m.run_command(f"{head}\nfrom pkg.mod import f\nassert f(3) == 6, ('{mark}', f(3))\nEOF")
    assert r.exit_code == 0, r.stderr
    tmp = sandbox_tmp(m)
    assert mark in (tmp / "repro.py").read_text()                          # the /tmp rewrite: the sandbox's own tmp
    host = Path("/tmp/repro.py")
    assert not (host.exists() and tmp != Path("/tmp") and mark in host.read_text())
    assert m.run_command("git status --porcelain").stdout.strip() == ""   # nothing written into the workspace
    before = m.run_command(run)
    assert before.exit_code == 0 and "EXIT=1" in before.stdout and "AssertionError" in before.stderr, (before.stdout, before.stderr)
    fix = m.run_command("python3 /tmp/swe/edit.py pkg/mod.py <<'EOF'\n<<<<<<< SEARCH\n    return x\n=======\n    return x * 2\n>>>>>>> REPLACE\nEOF")
    assert fix.stdout.startswith("OK pkg/mod.py"), fix.stdout + fix.stderr
    after = m.run_command(run)
    assert after.exit_code == 0 and "EXIT=0" in after.stdout, (after.stdout, after.stderr)
    assert m.run_command("git status --porcelain").stdout.split() == ["M", "pkg/mod.py"]


def test_the_cap_ledger_lives_in_the_sandbox_tmp_next_to_the_views_log(m):
    skill(m, "install.py")
    swe = sandbox_tmp(m) / "swe"
    assert json.loads((swe / ".ledger.json").read_text()) == {"locate": 0, "view": 0, "edited": False}   # install.py made it
    for _ in range(3):
        assert "workspace=" in m.run_command('python3 /tmp/swe/locate.py "f"').stdout
    assert m.run_command('python3 /tmp/swe/locate.py "f"').stdout.strip() == SEARCH_CAP
    for i in range(14):
        assert m.run_command(f"python3 /tmp/swe/view.py m.py {10 * i + 1}-{10 * i + 5}").stdout.startswith(f"{10 * i + 1}| ")
    assert m.run_command("python3 /tmp/swe/view.py m.py 200 210").stdout.strip() == READ_CAP
    led = json.loads((swe / ".ledger.json").read_text())
    assert led == {"locate": 3, "view": 14, "edited": False}, led
    assert (swe / ".views.json").exists()                                   # the ledger sits next to the views log
    assert json.loads(m.run_command("cat /tmp/swe/.ledger.json").stdout) == led   # the command's /tmp is that dir
    ok = m.run_command("python3 /tmp/swe/edit.py pkg/mod.py --lines 2-2 <<'EOF'\n    return x * 2\nEOF")
    assert ok.stdout.startswith("OK pkg/mod.py"), ok.stdout + ok.stderr
    assert json.loads((swe / ".ledger.json").read_text())["edited"] is True
    assert m.run_command("python3 /tmp/swe/view.py m.py 200 210").stdout.startswith("200| ")   # uncapped after the edit


def test_view_shapes_through_the_rewrite(m):
    skill(m, "install.py")
    a = m.run_command("python3 /tmp/swe/view.py m.py 30-40").stdout
    assert a.startswith("30| line30") and a.splitlines()[-1] == "40| line40", a
    assert m.run_command("python3 /tmp/swe/view.py m.py 30:40").stdout.startswith("ALREADY SHOWN")
    b = m.run_command("python3 /tmp/swe/view.py m.py").stdout
    assert b.startswith("1| line1") and b.strip().splitlines()[-1] == "120| line120", b[-200:]
