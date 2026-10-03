import json, glob, os, sys
RUN = sys.argv[1] if len(sys.argv) > 1 else "/Users/carson/Projects/gemma-swe-agent/eval/golden/runs/L_dev_v101"
rows = {}
for f in sorted(glob.glob(RUN + "/cases/*/router.jsonl")):
    cid = f.split("/")[-2]
    recs = [json.loads(l) for l in open(f)]
    loc = [r for r in recs if r.get("agent") == "locator"]
    live = [r for r in loc if r.get("served") == "upstream"]
    if not live:
        continue
    l4 = 0.0; tool = 0.0; prev = None; out_tok = 0
    for i, r in enumerate(live):
        p, c = r["prompt_tokens"], r["completion_tokens"]
        unc = p if prev is None else max(0, p - prev["prompt_tokens"] - prev["completion_tokens"])
        l4 += 0.102 + 0.02815 * c + 0.000921 * unc
        out_tok += c
        if prev is not None:
            tool += max(0.0, r["t_in"] - prev["t_out"])
        prev = r
    capped = any(r.get("served") == "cap" for r in loc)
    wall = live[-1]["t_out"] - live[0]["t_in"]
    rows[cid] = dict(n=len(live), out_tok=out_tok, l4_llm=round(l4, 1), tool=round(tool, 1), l4_total=round(l4 + tool, 1),
                     proxy_wall=round(wall, 1), proxy_lat=round(sum(r["latency_s"] for r in live), 1),
                     retries=sum(r.get("retries", 0) for r in live), capped=capped,
                     runaway=sum(1 for r in live if r["completion_tokens"] >= 730))
for k, v in rows.items():
    print(k, v)
json.dump(rows, open(os.path.dirname(os.path.abspath(__file__)) + "/l4_" + os.path.basename(RUN) + ".json", "w"), indent=1)
