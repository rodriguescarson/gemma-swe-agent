"""Uniform-slowdown fit on the faithful public L4 v4 run: find k with mean(min(k*t_i, CAP)) + ovh = target hidden
in-clock s/task, then the share of public solves that would still land under the cap. Two readings of the hidden
in-clock time: gap_5 (sub3 v4 central 258 s, range 243-273) and a sub4 (v9_eog) cross-check."""
import json, statistics
R = "/Users/carson/Projects/gemma-swe-agent"
valid = [l.strip() for l in open(R + "/data/kaggle_valid_ids.txt") if l.strip()]
for run in ("g4-l4-v4", "g4-l4-v9-eog"):
    d = {json.loads(l)["id"]: json.loads(l) for l in open(R + "/eval/kaggle/%s/results.jsonl" % run)}
    t = [d[i]["secs"] for i in valid]
    solves = [d[i]["secs"] for i in valid if d[i]["resolved"]]
    CAP = 305.0
    print(run, "public mean %.1f s, capped %d/74, solves %d" % (statistics.mean(t), sum(1 for x in t if x >= 300), len(solves)))
    for target in (243, 258, 273):
        for ovh in (5, 12):
            lo, hi = 1.0, 20.0
            for _ in range(60):
                k = (lo + hi) / 2
                m = statistics.mean(min(k * x, CAP) for x in t) + ovh
                lo, hi = (k, hi) if m < target else (lo, k)
            capped = sum(1 for x in t if k * x >= 300) / len(t)
            land = sum(1 for x in solves if k * x <= 300) / len(solves)
            print("  target %d s ovh %2d: k=%.2f capped %.0f%% solves landing %.0f%% -> %.1f of %d" %
                  (target, ovh, k, 100 * capped, 100 * land, land * len(solves), len(solves)))
