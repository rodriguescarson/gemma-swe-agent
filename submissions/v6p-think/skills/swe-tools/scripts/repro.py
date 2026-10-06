"""Run the locator's reproduction script (/tmp/repro.py, docs/GAPS_2026-10-06.md S3) against the repository this helper
is started in, so `cd /tmp/wK && python3 /tmp/swe/repro.py` checks fixer K's copy and plain `python3 /tmp/swe/repro.py`
checks /workspace. Stdlib only, Python 3.11.

The script runs with cwd = the repo root, the repo root as sys.argv[1], and the repo root FIRST on PYTHONPATH: the
sandbox exports PYTHONPATH=<workspace> and a script under /tmp has /tmp as sys.path[0], so without this a repro run
from a copy would import the unedited /workspace. Always exits 0 and prints one status line first:
REPRO PASS | REPRO FAIL exit=N | REPRO TIMEOUT | REPRO MISSING.
usage: python3 /tmp/swe/repro.py [--timeout 30] [--file /tmp/repro.py]"""
import os, signal, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ws import ws

OUT_MAX = 1500


def find_repro(explicit=None):
    if explicit:
        return explicit if os.path.isfile(explicit) else None
    for base in (os.environ.get("TEST_TMPDIR"), os.environ.get("TMPDIR"), tempfile.gettempdir(), "/tmp"):
        if base and os.path.isfile(os.path.join(base, "repro.py")):
            return os.path.join(base, "repro.py")
    return None


def run_repro(path, root, timeout):
    """-> (status, exit code or None, combined output)."""
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(p for p in (root, os.environ.get("PYTHONPATH")) if p))
    p = subprocess.Popen([sys.executable, path, root], cwd=root, env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, start_new_session=True)
    try:
        out, _ = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            p.kill()
        p.communicate()
        return "TIMEOUT", None, ""
    return ("PASS" if p.returncode == 0 else "FAIL"), p.returncode, out.decode("utf-8", "replace")


def main(argv):
    opt = {}
    i = 0
    while i < len(argv):
        if argv[i].startswith("--") and i + 1 < len(argv):
            opt[argv[i][2:]] = argv[i + 1]; i += 2
        else:
            i += 1
    path = find_repro(opt.get("file"))
    if not path:
        print("REPRO MISSING: no /tmp/repro.py (the plan says REPRO: none); run the TEST file instead")
        return
    root = ws()
    timeout = float(opt.get("timeout", 30))
    status, code, out = run_repro(path, root, timeout)
    if status == "TIMEOUT":
        print("REPRO TIMEOUT after %ds in %s" % (timeout, root))
    elif status == "PASS":
        print("REPRO PASS in %s" % root)
        if out.strip():
            print(out.strip()[-300:])
    else:
        print("REPRO FAIL exit=%d in %s" % (code, root))
        out = out.strip()
        print(out if len(out) <= OUT_MAX else "...\n" + out[-OUT_MAX:])


if __name__ == "__main__":
    main(sys.argv[1:])
