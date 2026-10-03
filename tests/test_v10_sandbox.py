"""v10 helpers inside the REAL harness sandboxes (SPEC R108-R112).

Every test runs the bundle's helpers (copied out of submissions/, so no __pycache__ lands there) through the installed
harness code paths the scorer uses: SubprocessManager (command-text rewriting of /tmp and /workspace, sanitised env,
inherited stdin), the swegemma run_command tool, and the ADK skill wrapper (skill_toolset.py:571). R112 reproduces the
Docker backend's contract (TEST_TMPDIR=/tmp-like dir, TMPDIR unset, PYTHONPATH unset, editable install, no rewriting).
"""
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v10_support import sandbox as S  # noqa: E402
from v10_support.compat import VERSION  # noqa: E402  (G4_BUNDLE may be v10.2)

try:
    from v10_support.repo import no_orphans  # noqa: F401,E402  (autouse, R120)
except ImportError:  # core's support module not present: same contract, minimal form
    import subprocess

    @pytest.fixture(autouse=True)
    def no_orphans(tmp_path):
        yield
        deadline, left = time.monotonic() + 1.0, []
        while True:
            ps = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True).stdout
            left = [line for line in ps.splitlines() if str(tmp_path) in line and "ps -axo" not in line]
            if not left or time.monotonic() > deadline:
                break
            time.sleep(0.1)
        assert not left, f"orphan processes survived the test: {left[:3]}"

pytest.importorskip("swegemma.sandbox.subprocess")
pytestmark = pytest.mark.skipif(S.v10_missing() is not None, reason=S.v10_missing() or "")

OPS = '''def add(a, b):
    """Add two numbers."""
    return a - b


def mul(a, b):
    return a * b
'''
FILES = {
    "calc/__init__.py": "",
    "calc/ops.py": OPS,
    "tests/__init__.py": "",
    "tests/test_ops.py": "from calc.ops import mul\n\n\ndef test_mul():\n    assert mul(2, 3) == 6\n",
}
CLAIM = "from calc.ops import add\n# CLAIM 1: add sums\nassert add(2, 3) == 5, add(2, 3)\n"
EDIT_BLOCK = "<<<<<<< SEARCH\n    return a - b\n=======\n    return a + b\n>>>>>>> REPLACE\n"


def out(r):
    """Model-visible text of a run_command reply (stdout, or the error text of a CommandError)."""
    return (r.get("stdout") or "") + (r.get("stderr") or "") + (r.get("error_message") or "")


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    return S.copy_bundle(tmp_path_factory.mktemp("bundle"))


@pytest.fixture(scope="module")
def shared_box(tmp_path_factory):
    b = S.make_box(FILES, base_dir=tmp_path_factory.mktemp("sbx"))
    yield b
    b.close()


@pytest.fixture
def box(shared_box):
    shared_box.reset()          # tree back to the baseline tag, helpers uninstalled
    return shared_box


# ---------------------------------------------------------------------------------------------------------------------
# R108
# ---------------------------------------------------------------------------------------------------------------------
def test_install_real_wrapper_reachable(box, bundle):
    assert "can't open file" in out(box.run_command("python3 /tmp/swe/status.py"))    # nothing installed yet
    r = box.run_skill("install.py", skill_dir=bundle / "skills" / "swe-tools")
    assert r["status"] == "success" and not r["stderr"], r
    first = r["stdout"].splitlines()[0]
    assert first.startswith("swe-tools %s ready in /tmp/swe (9 helpers)" % VERSION), first
    assert len(r["stdout"]) <= 400 and "[t=" in r["stdout"]
    assert r["_secs"] < 1.5, r["_secs"]                                                # wrapper + install, not 300 ms
    assert (box.swe / "VERSION").read_text().startswith("v10") and (box.swe / "t0").is_file()
    for h in S.HELPERS:                                                                 # every helper reachable, exit 0
        rr = box.run_command(f"python3 /tmp/swe/{h}.py")
        text = out(rr)
        assert rr["status"] == "ok" and "can't open file" not in text and "HELPER ERROR" not in text, (h, rr["_raw"][:400])
        assert "[t=" in text, (h, text[:300])
        assert rr["_secs"] < (8.0 if h == "verify" else 2.0), (h, rr["_secs"])
    rr = box.run_command('python3 /tmp/swe/run.py "echo marker-r108"')
    assert rr["stdout"].startswith("exit=0") and "marker-r108" in rr["stdout"]
    log = box.run_command("cat /tmp/swe/last.log")
    assert log["status"] == "ok" and "marker-r108" in log["stdout"]


# ---------------------------------------------------------------------------------------------------------------------
# R109
# ---------------------------------------------------------------------------------------------------------------------
CASES = {   # name: (script, dict args, positional args, expected first-line prefix, extra check)
    "install": ("install.py", None, None, "swe-tools %s ready in /tmp/swe" % VERSION, None),
    "locate": ("locate.py", {"query": "add numbers"}, None, "LOCATE:", "calc/ops.py"),
    "locate_positional": ("locate.py", None, ["add numbers"], "LOCATE:", "calc/ops.py"),
    "grep": ("grep.py", {"regex": "def add"}, None, "GREP: 1 hits in 1 files", "calc/ops.py"),
    "view": ("view.py", {"file": "calc/ops.py", "start": 1, "end": 3}, None, "calc/ops.py lines 1-3 of 7", "return a - b"),
    "view_positional": ("view.py", None, ["calc/ops.py", "1", "3"], "calc/ops.py lines 1-3 of 7", "return a - b"),
    "edit": ("edit.py", {"file": "calc/ops.py", "lines": "3-3", "text": "    return a + b"}, None, "OK", "return a + b"),
    "run": ("run.py", {"cmd": "echo hi-from-skill"}, None, "exit=0", "hi-from-skill"),
    "verify": ("verify.py", {"repro-only": True, "text": CLAIM}, None, "REPRO: fails on original", "claim 1"),
    "finalize": ("finalize.py", None, None, "NOT READY: EMPTY", None),
    "status": ("status.py", None, None, "STATUS [t=", "helpers " + VERSION),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_every_helper_as_skill_script(box, bundle, case):
    script, args, pos, first, extra = CASES[case]
    code = box.wrapper_code(script, args, pos, skill_dir=bundle / "skills" / "swe-tools")
    assert "os.chdir(td)" in code and "runpy.run_path" in code                        # the real wrapper shape
    r = box.run_skill(script, args, pos, skill_dir=bundle / "skills" / "swe-tools")
    assert r["status"] == "success" and not r["stderr"], r
    lines = r["stdout"].splitlines()
    assert lines and lines[0].startswith(first), r["stdout"][:600]
    if extra:
        assert extra in r["stdout"], r["stdout"][:600]
    assert "HELPER ERROR" not in r["stdout"] and "USAGE ERROR" not in r["stdout"]
    missing = [h for h in S.HELPERS if not (box.swe / f"{h}.py").is_file()]         # ($SWE also holds repro.py)
    assert not missing, missing                                                       # self-installed the rest
    assert "can't open file" not in out(box.run_command("python3 /tmp/swe/status.py"))
    if case == "edit":                                                                 # it edited the WORKSPACE file
        assert "return a + b" in (box.ws / "calc" / "ops.py").read_text()
    assert r["_secs"] < 10.0


# ---------------------------------------------------------------------------------------------------------------------
# R110
# ---------------------------------------------------------------------------------------------------------------------
def test_heredoc_path_roundtrip(box, bundle):
    box.run_skill("install.py", skill_dir=bundle / "skills" / "swe-tools")
    body = 'A = "/tmp/x"\nB = "/workspace/y"\nC = "/usr/local/bin/tool"\n'
    r = box.run_command(f"python3 /tmp/swe/edit.py calc/paths.py --create <<'EOF'\n{body}EOF")
    assert out(r).startswith("OK"), out(r)
    assert (box.ws / "calc" / "paths.py").read_text() == body                        # literals, not sandbox paths
    r = box.run_command("python3 /tmp/swe/edit.py calc/ops.py <<'EOF'\n<<<<<<< SEARCH\n    return a - b\n=======\n"
                        "    return open(\"/tmp/x\").read() or \"/workspace/y\"\n>>>>>>> REPLACE\nEOF")
    assert out(r).startswith("OK"), out(r)
    src = (box.ws / "calc" / "ops.py").read_text()
    assert 'open("/tmp/x")' in src and '"/workspace/y"' in src and str(box.root) not in src
    # control (harness_runtime 2.3): a raw heredoc through run_command gets the sandbox path baked in
    box.run_command("cat > raw_note.txt <<'EOF'\npath=/tmp/x\nEOF")
    raw = (box.ws / "raw_note.txt").read_text()
    assert "path=/tmp/x" not in raw and str(box.tmp) in raw, raw


# ---------------------------------------------------------------------------------------------------------------------
# R111
# ---------------------------------------------------------------------------------------------------------------------
def test_stdin_inherited_in_sandbox(box, bundle):
    box.run_skill("install.py", skill_dir=bundle / "skills" / "swe-tools")
    before = (box.ws / "calc" / "ops.py").read_bytes()
    probe = 'python3 -c "import select,sys; r,_,_=select.select([sys.stdin],[],[],0.5); print(\'readable\' if r else \'silent\')"'
    def fd0():
        try:
            st = os.fstat(0)
            return st.st_dev, st.st_ino
        except OSError:
            return None
    before_fd0 = fd0()
    with S.inherited_silent_stdin():
        assert box.run_command(probe)["stdout"].strip() == "silent"     # the fixture really hands an open, silent pipe
        for cmd, want in (("python3 /tmp/swe/edit.py calc/ops.py --lines 3-3", "ERROR: no text on stdin"),
                          ("python3 /tmp/swe/edit.py calc/ops.py", None),
                          ("python3 /tmp/swe/verify.py --repro-only", "REPRO: none saved"),
                          ('python3 /tmp/swe/locate.py "add"', "LOCATE:")):
            r = box.run_command(cmd)
            assert r["_secs"] <= 2.0, (cmd, r["_secs"])
            text = out(r)
            assert "HELPER ERROR" not in text and "can't open file" not in text, (cmd, text[:300])
            if want:
                assert want in text, (cmd, text[:400])
    assert (box.ws / "calc" / "ops.py").read_bytes() == before                       # nothing was edited
    assert fd0() == before_fd0                                                        # the fixture restored fd 0


# ---------------------------------------------------------------------------------------------------------------------
# R112
# ---------------------------------------------------------------------------------------------------------------------
WHEELS = S.ROOT / "data" / "raw" / "wheels"
PYPROJECT = ('[build-system]\nrequires = ["setuptools>=61"]\nbuild-backend = "setuptools.build_meta"\n\n'
             '[project]\nname = "calcpkg"\nversion = "0.1"\n\n[tool.setuptools]\npackages = ["calc"]\n')


@pytest.mark.skipif(not any(WHEELS.glob("setuptools-*.whl")), reason="offline setuptools wheel absent (data/raw/wheels)")
def test_docker_like_env(tmp_path, bundle):
    d = S.make_docker_box(tmp_path / "dock", {**FILES, "pyproject.toml": PYPROJECT}, wheels=WHEELS)
    assert "TMPDIR" not in d.env and "PYTHONPATH" not in d.env and d.env["TEST_TMPDIR"] == str(d.tmp)
    # the editable install is live: with PYTHONPATH unset and cwd elsewhere, calc imports from the workspace
    r = d.sh(f"cd {d.root} && python3 -c 'import calc.ops; print(calc.ops.__file__)'")
    assert r.returncode == 0 and r.stdout.strip() == str(d.ws / "calc" / "ops.py"), r.stdout + r.stderr
    # install exactly like the skill wrapper: scripts materialised in a temp dir, run from there
    td = tmp_path / "wrap"
    shutil.copytree(bundle / "skills" / "swe-tools" / "scripts", td / "scripts")
    r = d.sh(f"cd {td} && python3 scripts/install.py")
    assert r.stdout.startswith("swe-tools %s ready in /tmp/swe (9 helpers)" % VERSION), r.stdout + r.stderr
    assert (d.swe / "VERSION").is_file() and not (d.root / "swe").exists()
    checks = [(("locate", "add numbers"), "LOCATE:"), (("grep", "def add"), "GREP: 1 hits"),
              (("view", "calc/ops.py", "1", "3"), "calc/ops.py lines 1-3 of 7"), (("run", "echo dock"), "exit=0"),
              (("status",), "STATUS [t="), (("verify",), "VERIFY: NO SOURCE CHANGE")]
    for args, want in checks:
        t = time.perf_counter()
        r = d.helper(*args)
        assert r.returncode == 0 and r.stdout.startswith(want), (args, r.stdout[:400], r.stderr[:400])
        assert time.perf_counter() - t < 8.0
    r = d.helper("edit", "calc/ops.py", stdin_data=EDIT_BLOCK)
    assert r.stdout.startswith("OK (exact)"), r.stdout + r.stderr
    # base-tree runs import the BASE copy even though the editable install points at the workspace:
    # the original side must fail (a - b) while the current side passes (a + b)
    r = d.helper("verify", "--repro-only", stdin_data=CLAIM)
    assert r.stdout.startswith("REPRO: 1/1 claims fixed"), r.stdout + r.stderr
    r = d.helper("verify")
    assert r.stdout.startswith("VERIFY: GREEN"), r.stdout
    assert "calc from workspace" in r.stdout or "IMPORT: ok" in r.stdout, r.stdout
    r = d.helper("finalize")
    assert r.stdout.startswith("READY: 1 files changed"), r.stdout
    assert not any(p.name == "__pycache__" for p in (bundle / "skills" / "swe-tools" / "scripts").iterdir())
    assert os.environ.get("TEST_TMPDIR") != str(d.tmp)                              # nothing leaked into the test env
