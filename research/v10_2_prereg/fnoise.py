"""F noise floor and repair-round usage from existing runs ($0). Reads F_dev_A0, F_dev_A0p, F_dev_B2, L_dev_v101."""
import sys, collections, random, statistics, json
sys.path[:0] = ["scripts/golden", "eval/golden"]
import summary as S
R = {k: S.load_run("eval/golden/runs/" + k) for k in ("F_dev_A0", "F_dev_A0p", "F_dev_B2", "L_dev_v101")}
ok = lambda X: [r for r in X["records"] if r["status"] in S.GM.COUNTED_STATUS and r["instance"] is not None]
pc = {k: S.per_case(ok(v), "f_hidden_pass") for k, v in R.items() if k.startswith("F")}
vr = S.per_case(ok(R["F_dev_B2"]), "f_verify_rounds")
common = sorted(set(pc["F_dev_A0"]) & set(pc["F_dev_A0p"]) & set(pc["F_dev_B2"]))
print("common F cases", len(common))
# per-case sample pass rates
for k in pc:
    xs = [sum(pc[k][i]) / len(pc[k][i]) for i in common]
    print(k, "sample pass rate %.3f" % (sum(xs) / len(xs)), "n samples", sum(len(pc[k][i]) for i in common))
# unstable cases: 0<p<1 in any arm
pool = collections.defaultdict(list)
for k in pc:
    for i in common:
        pool[i] += pc[k][i]
unst = [i for i in common if 0 < sum(pool[i]) < len(pool[i])]
print("cases with mixed outcomes over 9 samples:", len(unst), unst)
pbar = {i: sum(pool[i]) / len(pool[i]) for i in common}
# null simulation: two identical arms, 2 samples each, n cases drawn from the 28 with p=pbar
rng = random.Random(20260930)
def sim(n, samples=2, reps=20000, thr=-0.05):
    fails = 0; ds = []
    for _ in range(reps):
        ids = [rng.choice(common) for _ in range(n)]
        d = 0.0
        for i in ids:
            a = sum(rng.random() < pbar[i] for _ in range(samples)) / samples
            b = sum(rng.random() < pbar[i] for _ in range(samples)) / samples
            d += b - a
        d /= n; ds.append(d)
        fails += d < thr
    ds.sort()
    return fails / reps, statistics.pstdev(ds), ds[int(0.05 * reps)]
for n in (20, 24, 28, 30, 36):
    for s in (2, 3):
        f, sd, q05 = sim(n, s)
        print("null F guard n=%d samples=%d: P(d < -0.05) = %.3f, SD(d) = %.3f, 5th pct %.3f" % (n, s, f, sd, q05))
# repair rounds in B2 vs outcome
rows = collections.Counter()
for i in pc["F_dev_B2"]:
    for p, v in zip(pc["F_dev_B2"][i], vr.get(i, [])):
        rows[(int(v), int(p))] += 1
print("B2 (verify rounds, pass) counts:", sorted(rows.items()))
