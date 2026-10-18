"""Box 74-task solves vs the hidden public score of the same bundle (paper evidence C1): one row per bundle that has both a
box 74-read (eval/a6000/results/<run>/results.jsonl) and a Kaggle submission (eval/analysis/out/kaggle_submissions_*.json).
Hidden public scores are on ~58 hidden public tasks (0.02 ~ one task); a RUNTIME row exceeded Kaggle's 12-hour limit.
    python eval/analysis/calibration.py > eval/analysis/out/calibration.md"""
import json, glob, statistics as st
SUBS = json.load(open(sorted(glob.glob("eval/analysis/out/kaggle_submissions_*.json"))[-1]))["submissions"]
PAIRS = [("v12", ["p4_v12"], "sub14:"), ("v12-b1024", ["p4_b1024"], "sub15b:"), ("v0-think", ["p4_v0t2"], "sub16:"),
         ("v13", ["p4_v13", "p4_v13r"], "sub17:"), ("pub024", ["p4_pub024"], "sub18:"), ("pub024 (again)", ["p4_pub024"], "sub19:")]
def box(run):
    rows = [json.loads(l) for l in open(f"eval/a6000/results/{run}/results.jsonl") if l.strip()]
    return sum(bool(r["resolved"]) for r in rows), st.mean(r["secs"] for r in rows)
print("| bundle | box runs (solved/74) | box mean s/task | Kaggle ref | hidden public |\n|---|---|---|---|---|")
for name, runs, tag in PAIRS:
    s = next((x for x in SUBS if (x["description"] or "").startswith(tag)), None)
    b = [box(r) for r in runs]
    hid = "RUNTIME (12 h limit)" if s and s["error_description"] and "runtime" in s["error_description"] else (s["public_score"] if s else "-")
    print(f"| {name} | {', '.join(str(x[0]) for x in b)} | {st.mean(x[1] for x in b):.0f} | {s['ref'] if s else '-'} | {hid} |")
