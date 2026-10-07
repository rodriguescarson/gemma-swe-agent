"""Run targeted pytest and print a compact result. Stdlib only.
  python3 /tmp/swe/test.py --target tests/test_x.py[::test_name] [--k EXPR] [--timeout SECONDS]
First line: exit=<pytest exit code> <summary>. v7: a missing target, a timeout, a target pytest cannot find (exit 4) and a
target that selects no tests (exit 5) each print one line that says what to do next."""
import os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ws import ws
a = sys.argv[1:]; opt = {}
i = 0
while i < len(a):
    if a[i].startswith("--") and i + 1 < len(a): opt[a[i][2:]] = a[i+1]; i += 2
    else: i += 1
ROOT = ws(); tgt = opt.get("target", "").split()
if not tgt:
    print("NO TARGET: test.py needs a test file, so run python3 /tmp/swe/test.py --target tests/test_x.py (or tests/test_x.py::test_name) next"); sys.exit(0)
cmd = [sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", "-o", "addopts=", "--tb=short", "-rfE"] + tgt
if opt.get("k"): cmd += ["-k", opt["k"]]
t = int(opt["timeout"]) if opt.get("timeout", "").isdigit() else 150
try: r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=t)
except subprocess.TimeoutExpired:
    print("TIMEOUT: the tests ran past %d s, so run one test file or one test (tests/test_x.py::test_name) next instead" % t); sys.exit(0)
out = r.stdout + r.stderr; lines = out.splitlines()
nf = next((l.strip() for l in lines if re.match(r"\s*ERROR: (file or directory )?not found", l)), None)
if r.returncode == 4 and nf:
    print("exit=4 pytest could not find the target (%s), so check the path with git ls-files | grep test_ and run it next" % nf[:200]); sys.exit(0)
if r.returncode == 5:
    print("exit=5 no tests ran: the target selected no tests, so pick a test file that has tests (git grep -ln NAME -- tests) next"); sys.exit(0)
summary = [l for l in lines if re.search(r"\b(passed|failed|error|errors|no tests ran)\b", l) and "==" in l or re.match(r"^\d+ (passed|failed)", l)]
print(f"exit={r.returncode} " + (summary[-1].strip("= ") if summary else ""))
body = "\n".join(l for l in lines if not l.startswith(("platform ", "rootdir", "cachedir", "plugins")))
print(body[-2200:] if r.returncode else "all selected tests passed")
