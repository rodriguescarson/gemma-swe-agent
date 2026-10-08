import json, glob, os
dirs = glob.glob('/home/jc/g4/runs/p2/items/v7c/*/') + glob.glob('/home/jc/g4/runs/p2/probe_v7c_T2/v7c/*/')
seen = set()
for d in sorted(dirs):
    t = os.path.basename(d.rstrip('/'))
    if t in seen or not glob.glob(d + 'traces/trace_*.json'): continue
    seen.add(t)
    steps = json.load(open(glob.glob(d + 'traces/trace_*.json')[0]))['steps']
    seq = []
    for s in steps:
        for c in s.get('tool_calls') or []:
            seq.append(((c.get('extra') or {}).get('author'), c['function_name'], json.dumps(c.get('arguments')), (s.get('observation') or {}).get('content', ''), s['step_id']))
    i = 0
    while i < len(seq):
        j = i
        while j + 1 < len(seq) and seq[j + 1][1:3] == seq[i][1:3]: j += 1
        if j - i + 1 >= 8:
            same = len({x[3] for x in seq[i:j + 1]})
            print(f"{t} [{seq[i][0]}] steps {seq[i][4]}-{seq[j][4]} x{j-i+1} distinct_replies={same}\n   CALL {seq[i][2][:200]}\n   REPLY {seq[i][3][:260]!r}\n   LAST-REPLY {seq[j][3][:200]!r}")
        i = j + 1
