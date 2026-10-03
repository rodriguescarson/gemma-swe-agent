import sys, random, collections
sys.path[:0] = ["scripts/golden", "eval/golden"]
import summary as S
R = {k: S.load_run("eval/golden/runs/" + k) for k in ("F_dev_A0", "F_dev_A0p", "F_dev_B2")}
ok = lambda X: [r for r in X["records"] if r["status"] in S.GM.COUNTED_STATUS and r["instance"] is not None]
pc = {k: S.per_case(ok(v), "f_hidden_pass") for k, v in R.items()}
common = sorted(set.intersection(*[set(v) for v in pc.values()]))
pool = collections.defaultdict(list)
for k in pc:
    for i in common:
        pool[i] += pc[k][i]
pbar = {i: sum(pool[i]) / len(pool[i]) for i in common}
rng = random.Random(7)
def sim(n, s, thr, reps=40000):
    bad = 0
    for _ in range(reps):
        d = 0.0
        for _ in range(n):
            i = rng.choice(common)
            d += (sum(rng.random() < pbar[i] for _ in range(s)) - sum(rng.random() < pbar[i] for _ in range(s))) / s
        bad += d / n <= thr + 1e-12
    return bad / reps
print("chain veto null P(d <= -0.10), n=30, 1 sample: %.3f" % sim(30, 1, -0.10))
print("chain veto null P(d <= -0.10), n=30, 2 samples: %.3f" % sim(30, 2, -0.10))
