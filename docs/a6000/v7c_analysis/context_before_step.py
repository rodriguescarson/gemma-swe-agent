import json, glob, sys
t, a, b = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
d = (glob.glob(f'/home/jc/g4/runs/p2/items/v7c/{t}/') + glob.glob(f'/home/jc/g4/runs/p2/probe_v7c_T2/v7c/{t}/'))[0]
steps = json.load(open(glob.glob(d + 'traces/trace_*.json')[0]))['steps']
for s in steps:
    if a <= s['step_id'] <= b:
        ex = s.get('extra') or {}
        for c in s.get('tool_calls') or []:
            print(f"#{s['step_id']} [{(c.get('extra') or {}).get('author')}] {c['function_name']} {json.dumps(c.get('arguments'))[:700]}")
            print("   ->", (s.get('observation') or {}).get('content', '')[:900].replace('\n', '|'))
        if s.get('message'): print(f"#{s['step_id']} TEXT {s['message'][:700]}")
