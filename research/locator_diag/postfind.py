import json, re, os, sys, collections, statistics, glob
sys.path.insert(0, "/Users/carson/Projects/gemma-swe-agent/eval/golden")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import golden_metrics as GM
from analyze import cls, case_p1, case_golden_L  # re-runs analyze prints; fine
FOOT = re.compile(r"\[t=(\d+)s\]")
gold = {c["eval_case_id"].split("__")[1]: c["golden"] for c in json.load(open("/Users/carson/Projects/gemma-swe-agent/eval/golden/datasets/L_dev.json"))["eval_cases"]}
SP = os.path.dirname(os.path.abspath(__file__))
# L: cumulative L4 time per use index
RUN = "/Users/carson/Projects/gemma-swe-agent/eval/golden/runs/L_dev_v101"
lat_by = {}
for f in sorted(glob.glob(RUN + "/cases/*/router.jsonl")):
    recs = [json.loads(l) for l in open(f)]
    live = [r for r in recs if r.get("agent") == "locator" and r.get("served") == "upstream"]
    prev = None; lat = []
    for r in live:
        p, cc = r["prompt_tokens"], r["completion_tokens"]
        unc = p if prev is None else max(0, p - prev["prompt_tokens"] - prev["completion_tokens"])
        lat.append(0.102 + 0.02815 * cc + 0.000921 * unc); prev = r
    lat_by[f.split("/")[-2].split("__")[1]] = lat
out = []
def gold_hit(u, g):
    fns = [x["name"] for x in g.get("gold_functions", [])]
    files = g.get("gold_files", [])
    kind = cls(u["cmd"], u["name"])
    if kind not in ("view", "read_file", "grep", "locate"):
        return False
    text = u["cmd"] + "\n" + u["out"]
    # a gold function's def line shown in the output, from a gold file
    for x in g.get("gold_functions", []):
        if x["file"] in text and re.search(r"def %s\b|class %s\b" % (re.escape(x["name"]), re.escape(x["name"])), u["out"]):
            return True
    if not fns:
        return any(f in u["cmd"] for f in files) and kind in ("view", "read_file")
    return False
for c in case_golden_L() + case_p1():
    g = gold[c["task"]]
    uses = c["uses"]
    if c["src"] == "L":
        lat = lat_by[c["task"]]
        cum = []; s = 0
        for i in range(len(uses)):
            s += lat[i] if i < len(lat) else 0
            cum.append(s)
        tend = sum(lat)
    else:
        cum = []; last = None
        for u in uses:
            m = FOOT.findall(u["out"])
            if m: last = int(m[-1])
            cum.append(last)
        tend = c["l4"]
    first = next((i for i, u in enumerate(uses) if gold_hit(u, g)), None)
    if first is None or tend is None or cum[first] is None:
        continue
    out.append(dict(src=c["src"], task=c["task"], first_idx=first + 1, calls=len(uses), t_first=round(cum[first], 1), t_end=round(tend, 1),
                    after=round(tend - cum[first], 1), calls_after=len(uses) - first - 1))
for src in ("L", "P"):
    R = [r for r in out if r["src"] == src]
    print(src, "n", len(R), "gold def first shown at call median", statistics.median(r["first_idx"] for r in R),
          "t_first median", statistics.median(r["t_first"] for r in R), "t_end median", statistics.median(r["t_end"] for r in R),
          "time after mean", round(statistics.mean(r["after"] for r in R), 1), "median", statistics.median(r["after"] for r in R),
          "calls after mean", round(statistics.mean(r["calls_after"] for r in R), 1), "share of locator time after", round(sum(r["after"] for r in R) / sum(r["t_end"] for r in R), 3))
json.dump(out, open(SP + "/postfind.json", "w"), indent=1)
for r in sorted(out, key=lambda r: -r["after"])[:14]:
    print(r)
