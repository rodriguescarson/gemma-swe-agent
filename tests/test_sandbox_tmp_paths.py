"""Regression (2026-09-27): v4 installed its helpers into the HOST /tmp/swe, but the harness subprocess sandbox rewrites
"/tmp" in command text to its private tmp dir, so `python3 /tmp/swe/locate.py` failed 81/85 times in v4's fair run.
This test runs install exactly like a skill script (Python file executed by sandbox.run_command, from a temp dir)
and then calls the helpers the way the prompts tell the model to."""
import pathlib, subprocess, sys, pytest
ROOT = pathlib.Path(__file__).resolve().parents[1]
sub = pytest.importorskip("swegemma.sandbox.subprocess")

def sandbox_with_repo():
    m = sub.SubprocessManager(timeout_seconds=60, system_site_packages=True)
    m.initialize({"pkg/__init__.py": "", "pkg/mod.py": "def parse_header(x):\n    return x\n",
                  "tests/test_mod.py": "from pkg.mod import parse_header\ndef test_p(): assert parse_header(1) == 1\n"})
    m.run_command("git init -q && git add -A && git -c user.email=a@b -c user.name=t commit -qm i")
    return m

def install_like_skill(m, scripts_dir):
    # mirrors adk skill execution: a .py file in the workspace, run with python3, copies the skill into a TemporaryDirectory
    code = ("import os, shutil, subprocess, sys, tempfile\n"
            f"src = {str(scripts_dir)!r}\n"
            "with tempfile.TemporaryDirectory() as td:\n"
            "    d = os.path.join(td, 'scripts'); shutil.copytree(src, d)\n"
            "    r = subprocess.run([sys.executable, os.path.join(d, 'install.py')], cwd=td, capture_output=True, text=True)\n"
            "    print(r.stdout, r.stderr)\n")
    m.write_file(".adk_exec_test.py", code)
    out = m.run_command(f"python3 {m.work_dir}/.adk_exec_test.py"); m.run_command(f"rm -f {m.work_dir}/.adk_exec_test.py")
    return out.stdout

def calls(m):
    return [m.run_command(c) for c in ('python3 /tmp/swe/locate.py "parse_header"', "python3 /tmp/swe/test.py --target tests/test_mod.py",
                                       'python3 /tmp/swe/run.py --timeout 5 "echo hi"', "python3 /tmp/swe/gate.py")]

def test_v4_as_submitted_cannot_reach_helpers():
    m = sandbox_with_repo()
    assert "installed:" in install_like_skill(m, ROOT / "submissions/v4/skills/swe-tools/scripts")
    r = m.run_command('python3 /tmp/swe/locate.py "parse_header"')
    assert "can't open file" in (r.stdout + r.stderr)   # documents the bug the score of sub3 was measured with

def test_variant_helpers_reachable_in_sandbox(tmp_path):
    out = tmp_path / "v"
    subprocess.run([sys.executable, str(ROOT / "scripts/make_variant.py"), str(ROOT / "submissions/v4"), str(out), "--edit", "--output", "--gate"],
                   check=True, capture_output=True)
    m = sandbox_with_repo()
    assert "gate.py" in install_like_skill(m, out / "skills/swe-tools/scripts")
    loc, test, run, gate = calls(m)
    for r in (loc, test, run, gate): assert "can't open file" not in (r.stdout + r.stderr), r.stdout + r.stderr
    assert "mod.py" in loc.stdout and "all selected tests passed" in test.stdout and "hi" in run.stdout
    assert "NO SOURCE CHANGE" in gate.stdout
    log = m.run_command("cat /tmp/swe/last.log"); assert "hi" in log.stdout   # run.py log is where the model will look
