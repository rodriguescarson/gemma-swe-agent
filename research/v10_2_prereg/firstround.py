"""Fixer first round in F_dev_A0 / F_dev_B2 / F_dev_A0p: calls before the first full verify, by kind ($0)."""
import sys, re, collections, statistics
sys.path[:0] = ["scripts/golden", "eval/golden"]
import summary as S, golden_metrics as GM
KIND = re.compile(r"python3 /tmp/swe/(\w+)\.py")
for run in ("F_dev_A0", "F_dev_B2", "F_dev_A0p"):
    R = S.load_run("eval/golden/runs/" + run)
    rows = []
    for r in R["records"]:
        if r["status"] not in GM.COUNTED_STATUS or r["instance"] is None:
            continue
        c = GM._ctx(r["instance"])
        uses = GM._uses(GM._stage(c))
        cnt = collections.Counter()
        total = 0
        for u in uses:
            m = KIND.search(u["cmd"] or "")
            k = m.group(1) if m else u["name"]
            if k == "verify" and "--repro-only" not in (u["cmd"] or ""):
                break
            cnt[k] += 1
            total += 1
        rows.append((total, cnt["view"], cnt["edit"], cnt["grep"], cnt["run"], len(uses)))
    tot = [x[0] for x in rows]; v = [x[1] for x in rows]; e = [x[2] for x in rows]; allc = [x[5] for x in rows]
    q = lambda xs, p: sorted(xs)[int(p * (len(xs) - 1))]
    print(run, "n", len(rows), "| calls before 1st verify p50 %d p90 %d | views p50 %d p90 %d | edits p50 %d p90 %d max %d | "
          "share with edits>=3: %.2f | all calls p50 %d" % (q(tot, .5), q(tot, .9), q(v, .5), q(v, .9), q(e, .5), q(e, .9),
                                                             max(e), sum(1 for x in e if x >= 3) / len(e), q(allc, .5)))
