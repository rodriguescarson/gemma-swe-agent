"""Per-task tool usage from ATIF traces: counts, exact repeats, malformed args, skill use, tokens.
Usage: python eval/trace_stats.py eval/runs/<run>"""
import json, glob, collections, sys, os
rows = []
for f in sorted(glob.glob(os.path.join(sys.argv[1], "traces", "trace_*.json"))):
    t = json.load(open(f)); steps = t.get("steps", [])
    calls = [((tc.get("function_name") or tc.get("name")), json.dumps(tc.get("arguments"), sort_keys=True))
             for s in steps for tc in (s.get("tool_calls") or [])]
    names = collections.Counter(c[0] for c in calls)
    dup = sum(v - 1 for v in collections.Counter(calls).values() if v > 1)
    bad = sum(1 for c in calls if ',start_line:' in c[1] or '\\\\\\"' in c[1])
    fm = t.get("final_metrics", {}) or {}
    rows.append((os.path.basename(f)[6:-5], len(calls), dup, bad, names.get("run_skill_script", 0), fm.get("total_completion_tokens"), dict(names.most_common(5))))
print(f"{'task':16} calls repeat malformed skill compl_tok  top tools")
for r in rows: print(f"{r[0]:16} {r[1]:5} {r[2]:6} {r[3]:9} {r[4]:5} {str(r[5]):9}  {r[6]}")
