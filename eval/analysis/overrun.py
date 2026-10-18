"""Per task: how far past its cap did it run, and what was in flight when the cap passed (a model call or a tool call)?
Inputs per run: results.jsonl (secs per id), traces/trace_<id>.json (step timestamps), <run>_proxy.jsonl (every model call: end
time t, latency_s, completion tokens). A model call is 'in flight at the cap' when it started before start+cap and ended
after it; otherwise the time after the cap is a tool call (the session timeout is checked only between steps)."""
import json, sys, glob, os, statistics as st
ROOT = "eval/a6000/results"
def cap_of(run):
    import yaml
    b = {"p4_v12": "v12", "p4_v12a": "v12a", "p4_v12b": "v12b", "p4_v12c": "v12c", "p4_pub024": "pub024", "p4_pub024_6m": "pub024_6m",
         "p4_v15": "v15", "p4_v13": "v13", "p4_b1024": "v12-b1024"}[run]
    ev = yaml.safe_load(open(f"submissions/{b}/eval_config.yaml"))["evaluation"]
    return ev["max_time_minutes"] * 60, ev["timeout_seconds"]
def start_ts(tr):
    for s in tr["steps"]:
        ex = s.get("extra") or {}
        if isinstance(ex, dict) and "timestamp" in ex: return ex["timestamp"] - ex.get("elapsed_s", 0)
    return None
def last_cmd(tr):
    for s in reversed(tr["steps"]):
        for c in (s.get("tool_calls") or []):
            return c.get("function_name"), str((c.get("arguments") or {}).get("command", ""))[:90]
    return None, ""
for run in sys.argv[1:]:
    cap, tmo = cap_of(run)
    rows = [json.loads(l) for l in open(f"{ROOT}/{run}/results.jsonl") if l.strip()]
    proxy = [json.loads(l) for l in open(f"{ROOT}/{run}_proxy.jsonl") if l.strip()] if os.path.exists(f"{ROOT}/{run}_proxy.jsonl") else []
    over = []; kinds = {"model": [], "tool": [], "unknown": []}
    for r in rows:
        if r["secs"] <= cap + 5: continue
        p = glob.glob(f"{ROOT}/{run}/results/traces/trace_{r['id']}.json") + glob.glob(f"{ROOT}/{run}/traces/trace_{r['id']}.json")
        if not p: kinds["unknown"].append(r["secs"] - cap); continue
        tr = json.load(open(p[0])); t0 = start_ts(tr)
        if t0 is None: kinds["unknown"].append(r["secs"] - cap); continue
        tc = t0 + cap
        inflight = [q for q in proxy if q["t"] - q["latency_s"] < tc < q["t"] and t0 <= q["t"] <= t0 + r["secs"] + 5]
        o = r["secs"] - cap
        if inflight:
            q = inflight[-1]; kinds["model"].append(o); over.append((r["id"], round(o), "model", f"call {q['latency_s']:.0f}s, {q['completion']} tok"))
        else:
            fn, cmd = last_cmd(tr); kinds["tool"].append(o); over.append((r["id"], round(o), "tool", f"{fn}: {cmd}"))
    secs = [r["secs"] for r in rows]
    print(f"== {run}: cap {cap:.0f} s, per-command timeout {tmo} s | n {len(rows)} mean {st.mean(secs):.0f} max {max(secs):.0f} | rows > cap+5 s: {len(over)}")
    for k, v in kinds.items():
        if v: print(f"   {k:7s} n={len(v):2d} overrun mean {st.mean(v):.0f} s, max {max(v):.0f} s, total {sum(v):.0f} s")
    for x in sorted(over, key=lambda x: -x[1])[:6]: print("     ", x)
