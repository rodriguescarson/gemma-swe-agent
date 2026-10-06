"""v6p end to end in the harness's real subprocess sandbox (swegemma.sandbox.subprocess.SubprocessManager), which rewrites
/tmp and /workspace in command text and exports PYTHONPATH=<workspace> (research/harness_runtime.md 2.3-2.4). No model:
every command below is the exact call shape the v6p prompts tell each stage to make, run in stage order.

setup install (skill-style) -> locator writes + runs /tmp/repro.py -> three fixers copy /workspace to /tmp/wK, edit,
test, repro and write /tmp/wK.diff -> selector runs select_best.py the way run_skill_script does (materialised skill in a
TemporaryDirectory, chdir into it, runpy) -> /workspace holds the pick."""
import pathlib, re
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
V6P = ROOT / "submissions" / "v6p"
SCRIPTS = V6P / "skills" / "swe-tools" / "scripts"
sub = pytest.importorskip("swegemma.sandbox.subprocess")

SRC = "def f(x):\n    return x\n"


def sandbox():
    m = sub.SubprocessManager(timeout_seconds=60, system_site_packages=True)
    m.initialize({"pkg/__init__.py": "", "pkg/mod.py": SRC,
                  "tests/test_mod.py": "from pkg.mod import f\n\n\ndef test_f():\n    assert f(2) == 4\n"})
    m.run_command("git init -q && git add -A && git -c user.email=a@b -c user.name=t commit -qm baseline")
    m.run_command("printf '.adk_exec_*.py\\n__pycache__/\\n' >> .git/info/exclude")
    return m


def skill(m, script, argv=()):
    """Like ADK's run_skill_script on the subprocess backend: a wrapper file in the workspace embeds the skill, runs
    python3 on it, the wrapper copies the skill into a TemporaryDirectory, chdirs there and runpy's the script."""
    code = ("import os, runpy, shutil, sys, tempfile\n"
            f"src = {str(SCRIPTS)!r}\n"
            "with tempfile.TemporaryDirectory() as td:\n"
            "    shutil.copytree(src, os.path.join(td, 'scripts')); os.chdir(td)\n"
            f"    sys.argv = {['scripts/' + script] + list(argv)!r}\n"
            f"    runpy.run_path('scripts/{script}', run_name='__main__')\n")
    m.write_file(".adk_exec_v6p.py", code)
    out = m.run_command(f"python3 {m.work_dir}/.adk_exec_v6p.py")
    return out.stdout + out.stderr


def edit_cmd(k, new_line):
    return (f"cd /tmp/w{k} && python3 /tmp/swe/edit.py pkg/mod.py <<'EOF'\n<<<<<<< SEARCH\n    return x\n=======\n"
            f"{new_line}\n>>>>>>> REPLACE\nEOF")


def test_full_v6p_call_sequence_in_the_rewriting_sandbox():
    m = sandbox()
    assert "select_best.py" in skill(m, "install.py")                      # setup stage
    # locator: repro from the issue's example, must fail on the unedited code
    r = m.run_command("cat > /tmp/repro.py <<'EOF'\nfrom pkg.mod import f\nassert f(3) == 6, f(3)\nEOF")
    assert r.exit_code == 0
    assert m.run_command("python3 /tmp/swe/repro.py").stdout.startswith("REPRO FAIL")
    # three fixers, one shared sandbox, interleaved the way ParallelAgent interleaves tool calls
    for k in "abc":
        out = m.run_command(f"rm -rf /tmp/w{k} && cp -a /workspace /tmp/w{k} && git -C /tmp/w{k} status --short | head -5")
        assert out.exit_code == 0, out.stderr
    fixes = {"a": "    return x + 1", "b": "    y = x * 2  # b, longer\n    return y", "c": "    return x * 2"}
    for k in "abc":
        assert "OK" in m.run_command(edit_cmd(k, fixes[k])).stdout, k
    for k in "abc":
        v = m.run_command(f"cd /tmp/w{k} && python3 /tmp/swe/view.py pkg/mod.py 1 3").stdout
        assert "ALREADY SHOWN" not in v and fixes[k].splitlines()[0].strip() in v, (k, v)   # each sees its own copy
    t = {k: m.run_command(f"cd /tmp/w{k} && python3 /tmp/swe/test.py --target tests/test_mod.py").stdout for k in "abc"}
    assert t["a"].startswith("exit=1") and t["b"].startswith("exit=0") and t["c"].startswith("exit=0"), t
    rp = {k: m.run_command(f"cd /tmp/w{k} && python3 /tmp/swe/repro.py").stdout for k in "abc"}
    assert rp["a"].startswith("REPRO FAIL") and rp["b"].startswith("REPRO PASS") and rp["c"].startswith("REPRO PASS"), rp
    for k in "abc":
        o = m.run_command(f"cd /tmp/w{k} && git -C /tmp/w{k} add -N . && git -C /tmp/w{k} diff > /tmp/w{k}.diff; "
                          f"git -C /tmp/w{k} diff --stat")
        assert "pkg/mod.py" in o.stdout, (k, o.stdout, o.stderr)
    assert m.run_command("git status --porcelain").stdout.strip() == ""   # nobody touched /workspace
    # selector
    rep = skill(m, "select_best.py", ["--test", "tests/test_mod.py"])
    assert re.search(r"^PICK c", rep, re.M), rep                           # passes repro + test, smaller than b
    assert len(rep) < 2000
    assert "return x * 2" in m.run_command("cat pkg/mod.py").stdout
    # verifier view of the result
    assert m.run_command("python3 /tmp/swe/repro.py").stdout.startswith("REPRO PASS")
    assert m.run_command("python3 /tmp/swe/test.py --target tests/test_mod.py").stdout.startswith("exit=0")
    d = m.run_command("git diff").stdout
    assert "pkg/mod.py" in d and "tests/" not in d
    assert m.run_command(f"ls {m.work_dir}/.adk_exec_v6p.py").exit_code == 0  # the wrapper survives the reset


def test_selector_fallback_through_run_command_works_too():
    m = sandbox()
    skill(m, "install.py")
    m.run_command("rm -rf /tmp/wa && cp -a /workspace /tmp/wa")
    m.run_command(edit_cmd("a", "    return x * 2"))
    out = m.run_command("python3 /tmp/swe/select_best.py --test tests/test_mod.py")
    assert re.search(r"^PICK a", out.stdout, re.M), out.stdout + out.stderr
    # and with select_best installed in /tmp/swe, the other helpers still import subprocess fine
    for c in ("python3 /tmp/swe/test.py --target tests/test_mod.py", "python3 /tmp/swe/check.py --mode preflight"):
        r = m.run_command(c)
        assert "Traceback" not in r.stdout + r.stderr, (c, r.stdout, r.stderr)
