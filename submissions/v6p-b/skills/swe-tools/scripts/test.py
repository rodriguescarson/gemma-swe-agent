"""Run targeted pytest and print a compact result. Stdlib only.
args={"target": "tests/test_x.py::test_y"} (file, node id, or -k expression via "k")."""
import os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ws import ws
import _budget                                      # v6p-b: the per-fixer call ledger and the pass flag
_refusal, _footer = _budget.enter(ws())
if _refusal:
    print(_refusal); sys.exit(0)
a = sys.argv[1:]; opt = {}
i = 0
while i < len(a):
    if a[i].startswith("--") and i + 1 < len(a): opt[a[i][2:]] = a[i+1]; i += 2
    else: i += 1
ROOT = ws(); tgt = opt.get("target", "").split()
if not tgt: print("give args={'target': 'tests/test_file.py[::test_name]'}"); sys.exit(0)
cmd = [sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", "-o", "addopts=", "--tb=short", "-rfE"] + tgt
if opt.get("k"): cmd += ["-k", opt["k"]]
# v6p: the sandbox exports PYTHONPATH=<workspace>; put the repo under test first so a fixer's copy tests its own code
env = dict(os.environ, PYTHONPATH=os.pathsep.join(p for p in (ROOT, os.environ.get("PYTHONPATH")) if p))
try: r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=int(opt.get("timeout", 150)), env=env)
except subprocess.TimeoutExpired: print("TIMEOUT: narrow the target"); sys.exit(0)
out = r.stdout + r.stderr; lines = out.splitlines()
summary = [l for l in lines if re.search(r"\b(passed|failed|error|errors|no tests ran)\b", l) and "==" in l or re.match(r"^\d+ (passed|failed)", l)]
print(f"exit={r.returncode} " + (summary[-1].strip("= ") if summary else ""))
body = "\n".join(l for l in lines if not l.startswith(("platform ", "rootdir", "cachedir", "plugins")))
print(body[-2200:] if r.returncode else "all selected tests passed")
if r.returncode == 0:
    _budget.mark_passed(ROOT)                        # the other fixers stop at their next helper call
if _footer:
    print(_footer)
