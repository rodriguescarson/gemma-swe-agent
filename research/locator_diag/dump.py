import json, re, sys, os
sys.path.insert(0, "/Users/carson/Projects/gemma-swe-agent/eval/golden")
import golden_metrics as GM
RUN = "/Users/carson/Projects/gemma-swe-agent/eval/golden/runs/L_dev_v101"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dumps")
d = json.load(open(RUN + "/traces/L_dev.json"))["eval_cases"]
FOOT = re.compile(r"\[t=(\d+)s\]")
rows = []
for case in d:
    inst = GM.make_instance(case)
    c = GM._ctx(inst)
    if c["status"] != "ok":
        continue
    g = c["g"]
    scores = {}
    for name in GM.metric_names("L") + ["x_capped", "x_clean", "x_malformed_calls", "x_runaway_outputs"]:
        try:
            r = GM._score(name, inst)
            scores[name] = (r["score"], json.loads(r["explanation"]))
        except Exception as e:
            scores[name] = (None, str(e))
    run = GM._stage(c)
    uses = GM._uses(run)
    reply = GM._reply(c)
    issue = ""
    ev0 = case["agent_data"]["turns"][0]["events"][0]
    txt = ev0["content"]["parts"][0]["text"]
    m = re.search(r"Problem Statement:\n(.*?)\n## Task Budget", txt, re.S)
    issue = m.group(1) if m else txt[:2000]
    calls = [r for r in g.get("llm_calls", []) if r.get("agent") == "locator" and r.get("live")]
    lat = [r.get("latency_s", 0) for r in calls]
    retries = [r.get("retries", 0) for r in calls]
    tid = g["task"]
    lines = []
    lines.append(f"##### {c['inst']['eval_case_id']}  task={tid}")
    lines.append("GOLD FILES: " + ", ".join(g.get("gold_files", [])))
    lines.append("GOLD FUNCS: " + ", ".join(f"{x['file']}::{x['qualname']}" for x in g.get("gold_functions", [])))
    lines.append("GOLD NEW: " + str(g.get("gold_new_files")))
    lines.append("SCORES: " + json.dumps({k: v[0] for k, v in scores.items()}))
    lines.append("FUNC DETAIL: " + json.dumps(scores.get("l_gold_functions_named", (0, ""))[1]))
    lines.append(f"LIVE CALLS: n={len(calls)} lat_sum={sum(lat):.1f} lat_max={max(lat) if lat else 0:.1f} retries={sum(retries)} lat_list={[round(x,1) for x in lat]}")
    lines.append(f"ISSUE ({len(issue)} chars):\n" + issue[:1800])
    lines.append("----- LOCATOR TOOL USES")
    for k, u in enumerate(uses):
        cmd = u["cmd"] or json.dumps(u["args"])[:300]
        out = GM._stdout(u["resp"]) if u["resp"] is not None else "<no resp>"
        ts = FOOT.findall(out if isinstance(out, str) else "")
        t = ts[-1] if ts else "?"
        o = out if isinstance(out, str) else json.dumps(out)
        lines.append(f"[{k+1}] t={t} {u['name']}: {cmd[:600]}")
        # summary of output
        if "locate.py" in cmd:
            lines.append("    OUT: " + o[:1500].replace("\n", "\n    "))
        else:
            lines.append("    OUT: " + o[:500].replace("\n", "\n    "))
    lines.append("----- REPLY:\n" + reply)
    lines.append("----- REPRO (exec): fails_orig=%s passes_gold=%s" % (g.get("exec_checks", {}).get("repro_fails_orig"), g.get("exec_checks", {}).get("repro_passes_gold")))
    os.makedirs(OUT, exist_ok=True); open(f"{OUT}/{tid}.txt", "w").write("\n".join(lines))
    rows.append({"task": tid, "gold_files": g.get("gold_files"), "gold_funcs": [x["qualname"] for x in g.get("gold_functions", [])],
                 **{k: v[0] for k, v in scores.items()}, "lat_sum": round(sum(lat), 1), "retries": sum(retries), "n_live": len(calls), "issue_len": len(issue)})
json.dump(rows, open(f"{OUT}/rows.json", "w"), indent=1)
for r in rows:
    print(r["task"], "files", r["l_gold_files_named"], "funcs", r["l_gold_functions_named"], "t", r["l_t_end"], "calls", r["l_calls"], "cap", r["x_capped"], "repro", r["l_repro_valid"], "fmt", r["l_plan_format"], "lat", r["lat_sum"], "retr", r["retries"], "n", r["n_live"], "ilen", r["issue_len"])
