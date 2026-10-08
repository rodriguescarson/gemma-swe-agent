import json, glob, os, collections, re, sys
base = sys.argv[1]
rows = []
for d in sorted(glob.glob(base + "/*/")):
    t = os.path.basename(d.rstrip("/"))
    tr = glob.glob(d + "traces/trace_*.json"); rs = glob.glob(d + "task_results.jsonl")
    if not tr or not rs: continue
    res = json.loads(open(rs[0]).readline())
    steps = json.load(open(tr[0]))["steps"]
    calls = []; per = collections.Counter(); capsteps = []; errs = collections.Counter(); notfound = 0
    for s in steps:
        ex = s.get("extra") or {}
        m = s.get("metrics") or {}
        if m.get("completion_tokens", 0) >= 4000: capsteps.append((s["step_id"], ex.get("author"), round(ex.get("elapsed_s", 0))))
        for c in s.get("tool_calls") or []:
            a = (c.get("extra") or {}).get("author", "?"); per[a] += 1
            calls.append((c["function_name"], json.dumps(c.get("arguments"), sort_keys=True), a))
        obs = (s.get("observation") or {}).get("content", "") if s.get("tool_calls") else ""
        if "file or directory not found" in obs: notfound += 1
        if "syntax error near unexpected token" in obs: errs["heredoc_syntax"] += 1
        if "Traceback" in obs and "/tmp/swe/" in obs: errs["helper_traceback"] += 1
    # identical consecutive repeats
    wasted = 0; maxrun = 0; run = 1; loopby = collections.Counter()
    for i in range(1, len(calls)):
        if calls[i][:2] == calls[i - 1][:2]: run += 1; wasted += 1; loopby[calls[i][0]] += 1
        else: maxrun = max(maxrun, run); run = 1
    maxrun = max(maxrun, run)
    rows.append(dict(t=t, ok=res["resolved"], patch=res["agent_patch_size"], calls=res["tool_calls"], dur=res["duration_seconds"], per=dict(per), wasted=wasted, maxrun=maxrun,
                     loopby=dict(loopby), cap=capsteps, notfound=notfound, **errs))
n = len(rows); print("items", n, "solved", sum(r["ok"] for r in rows), "empty patch", sum(r["patch"] == 0 for r in rows))
print("items with a loop (>=5 identical in a row):", sum(r["maxrun"] >= 5 for r in rows), "| calls wasted on repeats:", sum(r["wasted"] for r in rows), "of", sum(r["calls"] for r in rows))
print("loop calls by tool:", dict(sum((collections.Counter(r["loopby"]) for r in rows), collections.Counter())))
print("items with a 4096-token (cap) completion:", sum(bool(r["cap"]) for r in rows), "| total cap steps", sum(len(r["cap"]) for r in rows), "| seconds in them", sum(c[2] for r in rows for c in r["cap"]))
print("items with a pytest 'file not found' by the model:", sum(r["notfound"] > 0 for r in rows))
print("heredoc syntax errors:", sum(r.get("heredoc_syntax", 0) for r in rows), "| helper tracebacks:", sum(r.get("helper_traceback", 0) for r in rows))
print("calls by stage (mean):", {k: round(sum(r["per"].get(k, 0) for r in rows) / n, 1) for k in ("setup", "locator", "fixer", "verifier")})
print("durations: median", sorted(r["dur"] for r in rows)[n // 2], "| >=290s:", sum(r["dur"] >= 290 for r in rows), "| calls>=68:", sum(r["calls"] >= 68 for r in rows))
print()
for r in rows:
    print(f"{r['t']:<18} ok={int(r['ok'])} patch={r['patch']:>6} calls={r['calls']:>3} dur={r['dur']:>5.0f} loc/fix/ver={r['per'].get('locator',0)}/{r['per'].get('fixer',0)}/{r['per'].get('verifier',0)} maxrun={r['maxrun']:>2} loop={r['loopby']} cap={r['cap']} nf={r['notfound']}")
