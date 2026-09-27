"""Test every candidate copy on the target tests; copy the best candidate's changed files into /workspace.
Usage: python3 /tmp/swe/select.py --target tests/test_x.py[::name]"""
import filecmp, os, re, shutil, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ws import ws
a = sys.argv[1:]; tgt = a[a.index("--target") + 1].split() if "--target" in a else []
W = ws(); cands = sorted(d for d in os.listdir(W) if d.startswith(".cand_"))
def changed(c):
    out = []
    root = os.path.join(W, c)
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in ("__pycache__", ".pytest_cache") and not d.endswith(".egg-info")]
        for f in fns:
            if f.endswith(".pyc"): continue
            p = os.path.join(dp, f); rel = os.path.relpath(p, root); orig = os.path.join(W, rel)
            if not os.path.exists(orig) or not filecmp.cmp(p, orig, shallow=False): out.append(rel)
    return out
def is_test(rel): return bool(re.search(r"(^|/)(tests?|testing)/|(^|/)test_[^/]*\.py$|_test\.py$|conftest\.py$", rel))
res = []
for c in cands:
    ch = [r for r in changed(c) if not is_test(r)]
    if not ch: res.append((c, -1, 0, 0, ch, "no source changes")); continue
    root = os.path.join(W, c)
    env = dict(os.environ); env["PYTHONPATH"] = os.pathsep.join([root, os.path.join(root, "src")])
    ok = all(subprocess.run([sys.executable, "-m", "py_compile", os.path.join(root, r)], capture_output=True).returncode == 0 for r in ch if r.endswith(".py"))
    if not ok: res.append((c, -1, 0, 0, ch, "syntax error")); continue
    if tgt:
        try:
            r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "addopts=", "--tb=no"] + tgt, cwd=root, env=env, capture_output=True, text=True, timeout=150)
            out = r.stdout + r.stderr
            passed = sum(int(x) for x in re.findall(r"(\d+) passed", out)); failed = sum(int(x) for x in re.findall(r"(\d+) (?:failed|error)", out))
            res.append((c, 1 if r.returncode == 0 else 0, passed, -failed, ch, f"exit={r.returncode} passed={passed} failed={failed}"))
        except subprocess.TimeoutExpired:
            res.append((c, 0, 0, -99, ch, "tests timed out"))
    else:
        res.append((c, 0, 0, 0, ch, "no target given"))
for r in res: print(f"{r[0]}: {r[5]} | changed: {', '.join(r[4]) or '-'}")
best = sorted([r for r in res if r[1] >= 0], key=lambda r: (r[1], r[2], r[3], -len(r[4])), reverse=True)
if not best: print("NO USABLE CANDIDATE: make the fix directly in /workspace"); sys.exit(0)
b = best[0]
for rel in b[4]:
    dst = os.path.join(W, rel); os.makedirs(os.path.dirname(dst), exist_ok=True); shutil.copy2(os.path.join(W, b[0], rel), dst)
print(f"APPLIED {b[0]} to /workspace ({len(b[4])} files). Now run preflight and submit.")
