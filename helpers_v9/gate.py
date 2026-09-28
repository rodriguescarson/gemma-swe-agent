"""Regression gate: run the tests related to the files you changed on your version AND on the untouched original,
and report what your change broke or fixed. Does not modify /workspace. Stdlib only.
Usage: python3 /tmp/swe/gate.py [--target tests/test_x.py] [--timeout 60]"""
import os, re, shutil, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ws import ws, SWE
a = sys.argv[1:]; opt = {}
i = 0
while i < len(a):
    if a[i].startswith("--") and i + 1 < len(a): opt[a[i][2:]] = a[i + 1]; i += 2
    else: i += 1
ROOT = ws(); T = int(opt.get("timeout", 60))
sh = lambda c, cwd=ROOT: subprocess.run(c, cwd=cwd, shell=True, capture_output=True, text=True, errors="replace").stdout
TESTRE = re.compile(r"(^|/)(tests?|testing)/|(^|/)test_[^/]*\.py$|_test\.py$|conftest\.py$")
changed = [p for p in sh("git add -N . >/dev/null 2>&1; git diff HEAD --name-only").split() if p.endswith(".py") and not TESTRE.search(p) and not os.path.basename(p).startswith(".")]
if not changed: print("NO SOURCE CHANGE: git diff has no edited source .py file. Make the fix first."); sys.exit(0)
diff = sh("git diff HEAD -U0")
names = set(re.findall(r"^@@.*@@\s*(?:async\s+)?(?:def|class)\s+(\w+)", diff, re.M))
names |= set(re.findall(r"^[+-]\s*(?:async\s+)?def\s+(\w+)", diff, re.M))
mods = {os.path.splitext(os.path.basename(p))[0] for p in changed} - {"__init__"}
score = {}
for term in sorted(names | mods):
    if len(term) < 4: continue
    for f in sh(f"git grep -l -w -e {term!r} -- 'tests' 'test' 'testing' '*test_*.py'").split():
        if f.endswith(".py") and "conftest" not in f: score[f] = score.get(f, 0) + (2 if term in names else 1)
files = sorted(score, key=lambda f: -score[f])[:3]
if opt.get("target"): files = [opt["target"]] + [f for f in files if f != opt["target"]][:2]
if not files: print(f"No existing test file mentions {sorted(names | mods)[:8]}. Write a repro in /tmp instead."); sys.exit(0)
def run(root, extra_env):
    """Returns (failing node ids | None on timeout, summary line, status) where status is
    OK (pytest ran and reported), BROKEN (import/collection/internal error, exit 2-4, or no summary), NOPYTEST."""
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "addopts=", "--tb=line", "-rfE"] + files
    env = dict(os.environ, **extra_env)
    try: r = subprocess.run(cmd, cwd=root, capture_output=True, text=True, errors="replace", timeout=T, env=env)
    except subprocess.TimeoutExpired: return None, "TIMEOUT", "TIMEOUT"
    out = r.stdout + r.stderr
    if "No module named pytest" in out: return set(), "pytest is not installed", "NOPYTEST"
    fails = set(re.findall(r"^(?:FAILED|ERROR) (\S+)", out, re.M))
    summ = [l.strip("= ") for l in out.splitlines() if re.search(r"\d+ (passed|failed|error)", l)]
    status = "OK" if summ and r.returncode in (0, 1) else "BROKEN"
    tail = " | ".join(l.strip() for l in out.strip().splitlines()[-4:])[-400:]
    return fails, (summ[-1] if summ else "no summary (exit %d): %s" % (r.returncode, tail)), status
now_fail, now_sum, now_st = run(ROOT, {})
base = os.path.join(SWE, "base_") + sh("git rev-parse --short HEAD").strip()
if not os.path.isdir(base):
    os.makedirs(base, exist_ok=True); subprocess.run(f"git archive HEAD | tar -x -C {base}", cwd=ROOT, shell=True)
pp = os.pathsep.join(p for p in (os.path.join(base, "src"), base) if os.path.isdir(p))
base_fail, base_sum, base_st = run(base, {"PYTHONPATH": pp + os.pathsep + os.environ.get("PYTHONPATH", "")})
print("TESTS RUN:", " ".join(files))
print(f"YOUR VERSION: {now_sum}\nORIGINAL:     {base_sum}")
if now_st == "NOPYTEST": print("GATE: UNAVAILABLE (pytest missing): verify with a repro script instead"); sys.exit(0)
if now_fail is None: print("Your version TIMED OUT: the change may cause an infinite loop.\nGATE: FAIL"); sys.exit(0)
if now_st == "BROKEN" and base_st != "BROKEN":
    print("Your version cannot even run the tests (import/collection error or crash); the original can.\nGATE: FAIL"); sys.exit(0)
if base_fail is None: base_fail = set()
broke, fixed, still = sorted(now_fail - base_fail), sorted(base_fail - now_fail), sorted(now_fail & base_fail)
print("REGRESSIONS (passed before, fail now: you must fix these):\n  " + ("\n  ".join(broke[:12]) or "none"))
print("NEWLY PASSING:\n  " + ("\n  ".join(fixed[:8]) or "none"))
if still: print(f"FAILING BEFORE AND AFTER ({len(still)}): " + " ".join(still[:5]))
if now_st == "BROKEN": print("NOTE: tests cannot run on the original either; rely on a repro script.")
print("GATE: " + ("FAIL" if broke else ("INCONCLUSIVE" if now_st == "BROKEN" else "PASS")))
