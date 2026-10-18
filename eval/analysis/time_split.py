"""Where a task's wall time goes, from the box's own logs: model time = the summed latency of every proxied model call that
ended inside the task's window (trace start .. start + secs); tool and harness time = secs - model time. For rows that hit
the cap, also what was in flight at the cap: a model call spanning start + cap, or else a tool call.
    python eval/analysis/time_split.py p4_v12 p4_v12b ..."""
import glob, json, statistics as st, sys
import yaml
ROOT = "eval/a6000/results"
BUNDLE = {"p4_v12": "v12", "p4_v12a": "v12a", "p4_v12b": "v12b", "p4_v12c": "v12c", "p4_pub024": "pub024",
          "p4_pub024_6m": "pub024_6m", "p4_v15": "v15", "p4_v13": "v13", "p4_v13r": "v13", "p4_b1024": "v12-b1024", "p4_v16": "v16", "p4_v14": "v14"}
def start(tr):
    for s in tr["steps"]:
        ex = s.get("extra") or {}
        if isinstance(ex, dict) and "timestamp" in ex: return ex["timestamp"] - ex.get("elapsed_s", 0)
for run in sys.argv[1:]:
    cap = yaml.safe_load(open(f"submissions/{BUNDLE[run]}/eval_config.yaml"))["evaluation"]["max_time_minutes"] * 60
    rows = [json.loads(l) for l in open(f"{ROOT}/{run}/results.jsonl") if l.strip()]
    proxy = [json.loads(l) for l in open(f"{ROOT}/{run}_proxy.jsonl") if l.strip()]
    per = []
    for r in rows:
        p = glob.glob(f"{ROOT}/{run}/results/traces/trace_{r['id']}.json") + glob.glob(f"{ROOT}/{run}/traces/trace_{r['id']}.json")
        if not p: continue
        t0 = start(json.load(open(p[0])))
        if t0 is None: continue
        calls = [q for q in proxy if t0 <= q["t"] <= t0 + r["secs"] + 2]
        model = min(r["secs"], sum(q["latency_s"] for q in calls)); toks = sum(q["completion"] for q in calls)
        capped = r["secs"] >= cap - 5
        fl = None
        if capped: fl = "model" if any(q["t"] - q["latency_s"] < t0 + cap - 2 < q["t"] for q in proxy) else "tool"
        per.append(dict(id=r["id"], secs=r["secs"], model=model, n=len(calls), toks=toks, solved=bool(r["resolved"]), capped=capped, fl=fl))
    tot = sum(x["secs"] for x in per); mod = sum(x["model"] for x in per)
    cap_rows = [x for x in per if x["capped"]]
    print(f"== {run} (cap {cap:.0f} s): {len(per)} tasks; model calls {mod/tot:.0%} of wall time, tools+harness {1-mod/tot:.0%}; "
          f"median {st.median(x['n'] for x in per):.0f} model calls/task, median {st.median(x['toks'] for x in per):.0f} generated tokens/task, "
          f"{sum(x['toks'] for x in per)/mod:.1f} tok/s while generating")
    for lab, grp in (("solved", [x for x in per if x["solved"]]), ("unsolved, ended early", [x for x in per if not x["solved"] and not x["capped"]]), ("hit the cap", cap_rows)):
        if grp: print(f"   {lab:22s} n={len(grp):2d}  mean {st.mean(x['secs'] for x in grp):4.0f} s, model share {sum(x['model'] for x in grp)/sum(x['secs'] for x in grp):.0%}, "
                      f"mean tokens {st.mean(x['toks'] for x in grp):5.0f}, mean calls {st.mean(x['n'] for x in grp):4.1f}")
    if cap_rows:
        print(f"   at the cap, in flight: model {sum(x['fl']=='model' for x in cap_rows)}, tool {sum(x['fl']=='tool' for x in cap_rows)}")
