import json, re, sys, os
sys.path.insert(0, "/Users/carson/Projects/gemma-swe-agent/eval/golden")
import golden_metrics as GM
P = "/Users/carson/Projects/gemma-swe-agent/eval/pair1/eval/runs/p1_v10"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dumps", "p1")
os.makedirs(OUT, exist_ok=True)
split = json.load(open("/Users/carson/Projects/gemma-swe-agent/eval/golden/split.json"))["tasks"]
gold = {}
for c in json.load(open("/Users/carson/Projects/gemma-swe-agent/eval/golden/datasets/L_dev.json"))["eval_cases"]:
    g = c["golden"]; tid = c["eval_case_id"].split("__")[1]
    gold[tid] = g
res = {}
for l in open(P + "/task_results.jsonl"):
    r = json.loads(l); res[r["instance_id"]] = r
FOOT = re.compile(r"\[t=(\d+)s\]")
rows = []
for tid in sorted(gold):
    assert split[tid]["split"] == "dev"
    f = f"{P}/traces/trace_{tid}.json"
    if not os.path.exists(f):
        print("no trace", tid); continue
    d = json.load(open(f))
    steps = d["steps"]
    issue = re.search(r"Problem Statement:\n(.*?)\n## Task Budget", steps[0]["message"], re.S)
    issue = issue.group(1) if issue else ""
    loc = []
    reply = ""
    started = False
    for s in steps:
        tcs = s.get("tool_calls") or []
        auth = None
        if tcs:
            auth = tcs[0].get("extra", {}).get("author")
        else:
            auth = (s.get("extra") or {}).get("author")
        if auth == "locator":
            started = True
            loc.append(s)
        elif started and auth not in (None, "locator"):
            break
    uses = []
    llm_out = 0
    for s in loc:
        for tc in (s.get("tool_calls") or []):
            obs = s.get("observation", {})
            content = obs.get("content") if isinstance(obs, dict) else None
            if isinstance(obs, dict) and "results" in obs:
                content = json.dumps(obs["results"])
            uses.append((tc["function_name"], tc.get("arguments", {}), content or "", tc.get("extra", {}).get("usage", {})))
        if not s.get("tool_calls") and s.get("message") and s.get("source") == "agent":
            reply = s["message"]
    g = gold[tid]
    gf = g.get("gold_files", [])
    fn = [x["name"] for x in g.get("gold_functions", []) if x.get("name") and x["name"].lower() not in GM.VACUOUS_FUNCTIONS]
    files_named = [x for x in gf if GM._path_named(reply, x)]
    fn_named = [n for n in fn if re.search(r"(?<!\w)" + re.escape(n) + r"(?!\w)", reply)]
    ts = []
    for u in uses:
        ts += [int(x) for x in FOOT.findall(u[2])]
    t_end = ts[-1] if ts else None
    lines = [f"##### p1_v10 {tid} resolved={res.get(tid,{}).get('resolved')} dur={res.get(tid,{}).get('duration_seconds')}",
             "GOLD FILES: " + ", ".join(gf), "GOLD FUNCS: " + ", ".join(fn),
             f"FILES NAMED {len(files_named)}/{len(gf)}  FUNCS NAMED {len(fn_named)}/{len(fn)}  calls={len(uses)} t_end={t_end}",
             f"ISSUE ({len(issue)} chars):\n" + issue[:1500], "----- LOCATOR TOOL USES"]
    for k, (nm, args, content, usage) in enumerate(uses):
        cmd = args.get("command") if isinstance(args, dict) else None
        cmd = cmd if isinstance(cmd, str) else json.dumps(args)[:300]
        try:
            cj = json.loads(content); o = cj.get("stdout") or cj.get("result") or content
        except Exception:
            o = content
        o = o if isinstance(o, str) else json.dumps(o)
        tt = FOOT.findall(o); t = tt[-1] if tt else "?"
        lines.append(f"[{k+1}] t={t} out_tok={usage.get('completion_tokens')} {nm}: {cmd[:500]}")
        lines.append("    OUT: " + o[:(1400 if 'locate.py' in cmd else 350)].replace("\n", "\n    "))
    lines.append("----- REPLY:\n" + reply)
    open(f"{OUT}/{tid}.txt", "w").write("\n".join(lines))
    rows.append(dict(task=tid, resolved=res.get(tid, {}).get("resolved"), gold_files=len(gf), files_named=len(files_named),
                     all_files=int(len(files_named) == len(gf)) if gf else None, funcs=len(fn), funcs_named=len(fn_named),
                     calls=len(uses), t_end=t_end, plan_ok=reply.lstrip().startswith("FILES:"), reply_words=len(reply.split()), issue_len=len(issue)))
json.dump(rows, open(OUT + "/rows.json", "w"), indent=1)
for r in rows:
    print(r)
n = len(rows)
print("n", n, "all_files", sum(r["all_files"] or 0 for r in rows) / n, "mean calls", sum(r["calls"] for r in rows) / n,
      "t_end mean", sum(r["t_end"] or 0 for r in rows) / n)
