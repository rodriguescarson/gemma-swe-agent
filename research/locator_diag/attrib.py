import json, re, sys, os, collections, glob
sys.path.insert(0, "/Users/carson/Projects/gemma-swe-agent/eval/golden")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import golden_metrics as GM
from analyze import cls  # noqa
SP = os.path.dirname(os.path.abspath(__file__))
FOOT = re.compile(r"\[t=(\d+)s\]")
rows = json.load(open(SP + "/rows_all.json"))
# ---- time attribution by call kind
secs = {"L": collections.Counter(), "P": collections.Counter()}
calls = {"L": collections.Counter(), "P": collections.Counter()}
# L: per-call L4 latency from router, mapped to tool uses in order
RUN = "/Users/carson/Projects/gemma-swe-agent/eval/golden/runs/L_dev_v101"
d = {c["eval_case_id"]: c for c in json.load(open(RUN + "/traces/L_dev.json"))["eval_cases"]}
per_case = {}
for f in sorted(glob.glob(RUN + "/cases/*/router.jsonl")):
    cid = f.split("/")[-2]
    if cid not in d:
        continue
    inst = GM.make_instance(d[cid]); c = GM._ctx(inst)
    if c["status"] != "ok":
        continue
    uses = GM._uses(GM._stage(c))
    recs = [json.loads(l) for l in open(f)]
    live = [r for r in recs if r.get("agent") == "locator" and r.get("served") == "upstream"]
    prev = None; lat = []
    for r in live:
        p, cc = r["prompt_tokens"], r["completion_tokens"]
        unc = p if prev is None else max(0, p - prev["prompt_tokens"] - prev["completion_tokens"])
        lat.append(0.102 + 0.02815 * cc + 0.000921 * unc); prev = r
    k = collections.Counter()
    for i, u in enumerate(uses):
        kind = cls(u["cmd"] or "", u["name"])
        s = lat[i] if i < len(lat) else 0.0
        secs["L"][kind] += s; calls["L"][kind] += 1; k[kind] += s
    final = sum(lat[len(uses):])
    secs["L"]["final_reply"] += final
    per_case[("L", c["g"]["task"])] = dict(k, final_reply=final)
# P: footer deltas
P = "/Users/carson/Projects/gemma-swe-agent/eval/pair1/eval/runs/p1_v10"
gold = {c["eval_case_id"].split("__")[1] for c in json.load(open("/Users/carson/Projects/gemma-swe-agent/eval/golden/datasets/L_dev.json"))["eval_cases"]}
for tid in sorted(gold):
    f = f"{P}/traces/trace_{tid}.json"
    if not os.path.exists(f):
        continue
    steps = json.load(open(f))["steps"]
    loc, started = [], False
    for s in steps:
        tcs = s.get("tool_calls") or []
        a = tcs[0].get("extra", {}).get("author") if tcs else (s.get("extra") or {}).get("author")
        if a == "locator":
            started = True; loc.append(s)
        elif started and a not in (None, "locator"):
            break
    last_t = None; k = collections.Counter()
    # start clock: the setup's install footer
    for s in steps:
        tcs = s.get("tool_calls") or []
        if tcs and tcs[0].get("extra", {}).get("author") == "setup":
            m = FOOT.findall(json.dumps(s.get("observation", {})))
            if m:
                last_t = int(m[-1])
    for s in loc:
        for tc in (s.get("tool_calls") or []):
            obs = json.dumps(s.get("observation", {}))
            m = FOOT.findall(obs)
            args = tc.get("arguments", {}) or {}
            cmd = args.get("command") if isinstance(args.get("command"), str) else ""
            kind = cls(cmd, tc["function_name"])
            calls["P"][kind] += 1
            if m and last_t is not None:
                dt = int(m[-1]) - last_t; last_t = int(m[-1])
                secs["P"][kind] += dt; k[kind] += dt
    per_case[("P", tid)] = dict(k)
for src in ("L", "P"):
    tot = sum(secs[src].values()); n = sum(calls[src].values())
    print(src, "total s", round(tot, 1), "calls", n)
    for kind, s in secs[src].most_common():
        print("   %-12s calls %4d (%4.1f%%)  L4 s %7.1f (%4.1f%%)" % (kind, calls[src][kind], 100 * calls[src][kind] / n, s, 100 * s / tot))
json.dump({"%s:%s" % k: v for k, v in per_case.items()}, open(SP + "/per_case_secs.json", "w"), indent=1)
