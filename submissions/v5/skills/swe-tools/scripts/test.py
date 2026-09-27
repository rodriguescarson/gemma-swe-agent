"""Run targeted pytest and print a compact result. Stdlib only.
args={"target": "tests/test_x.py::test_y"} (file, node id, or -k expression via "k")."""
import os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ws import ws
a = sys.argv[1:]; opt = {}
i = 0
while i < len(a):
    if a[i].startswith("--") and i + 1 < len(a): opt[a[i][2:]] = a[i+1]; i += 2
    else: i += 1
ROOT = ws()
if opt.get("cand"): ROOT = os.path.join(ROOT, ".cand_" + opt["cand"])
tgt = opt.get("target", "").split()
env = dict(os.environ); env["PYTHONPATH"] = os.pathsep.join([ROOT, os.path.join(ROOT, "src")] + [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p])
if not tgt: print("give args={'target': 'tests/test_file.py[::test_name]'}"); sys.exit(0)
cmd = [sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", "-o", "addopts=", "--tb=short", "-rfE"] + tgt
if opt.get("k"): cmd += ["-k", opt["k"]]
try: r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=int(opt.get("timeout", 150)), env=env)
except subprocess.TimeoutExpired: print("TIMEOUT: narrow the target"); sys.exit(0)
out = r.stdout + r.stderr; lines = out.splitlines()
summary = [l for l in lines if re.search(r"\b(passed|failed|error|errors|no tests ran)\b", l) and "==" in l or re.match(r"^\d+ (passed|failed)", l)]
print(f"exit={r.returncode} " + (summary[-1].strip("= ") if summary else ""))
body = "\n".join(l for l in lines if not l.startswith(("platform ", "rootdir", "cachedir", "plugins")))
print(body[-2200:] if r.returncode else "all selected tests passed")
