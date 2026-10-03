"""Pipeline outcome (p1_v10, one run) vs the fixer given a golden plan (F_dev_A0, majority of 3 samples) on the dev tasks
both cover, split by whether the p1 locator named every gold file."""
import json, glob, collections, os
SP = os.path.dirname(os.path.abspath(__file__))
fp = collections.defaultdict(list)
for f in glob.glob("/Users/carson/Projects/gemma-swe-agent/eval/golden/runs/F_dev_A0/cases/*.json"):
    d = json.load(open(f))
    hp = (d.get("exec_checks") or {}).get("hidden_pass")
    if d.get("status") == "ok" and hp is not None:
        fp[d["task"]].append(bool(hp))
F = {t: sum(v) * 2 > len(v) for t, v in fp.items()}
rows = [r for r in json.load(open(SP + "/rows_all.json")) if r["src"] == "P" and r["task"] in F]
ct = collections.Counter((r["named"] == r["ngold"], F[r["task"]], bool(r["resolved"])) for r in rows)
print("tasks in both:", len(rows))
for k, v in sorted(ct.items()):
    print("p1 locator named all gold files=%s | F golden-plan majority pass=%s | p1 resolved=%s : %d" % (k + (v,)))
print("named + F passes + p1 failed:", sorted(r["task"] for r in rows if r["named"] == r["ngold"] and F[r["task"]] and not r["resolved"]))
