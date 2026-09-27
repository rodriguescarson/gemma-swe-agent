"""Paired per-task comparison of two swegemma result dirs, with Wilson 95% CIs.
Usage: python eval/compare.py eval/runs/A eval/runs/B"""
import json, math, sys, collections
def load(d):
    r = {}
    for line in open(f"{d}/task_results.jsonl"):
        t = json.loads(line); r[t.get("instance_id") or t.get("task_id")] = bool(t.get("resolved"))
    return r
def wilson(k, n, z=1.96):
    if n == 0: return (0, 0)
    p = k/n; d = 1 + z*z/n; c = p + z*z/(2*n); h = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))
    return ((c-h)/d, (c+h)/d)
A, B = load(sys.argv[1]), load(sys.argv[2]); ids = sorted(set(A) & set(B))
for name, R in (("A", A), ("B", B)):
    k = sum(R[i] for i in ids); lo, hi = wilson(k, len(ids))
    by = collections.Counter(i.split('_')[0] for i in ids if R[i])
    print(f"{name}: {k}/{len(ids)} = {k/len(ids):.3f}  CI [{lo:.3f},{hi:.3f}]  by repo {dict(by)}")
bw = sum(B[i] and not A[i] for i in ids); aw = sum(A[i] and not B[i] for i in ids)
p = sum(math.comb(aw+bw, j) for j in range(0, min(aw, bw)+1)) / 2**(aw+bw) * 2 if aw+bw else 1.0
print(f"B-only wins {bw}, A-only wins {aw}, exact sign-test p={min(p,1):.3f}")
