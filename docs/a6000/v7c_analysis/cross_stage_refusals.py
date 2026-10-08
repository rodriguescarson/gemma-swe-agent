import json, glob, os, collections, sys
def analyze(label, pattern):
    rows = []
    for tf in glob.glob(pattern):
        d = os.path.dirname(os.path.dirname(tf))
        rf = glob.glob(d + '/task_results.jsonl')
        if not rf: continue
        res = json.loads(open(rf[0]).readline())
        steps = json.load(open(tf))['steps']
        seq = []
        for s in steps:
            for c in s.get('tool_calls') or []:
                seq.append(((c.get('extra') or {}).get('author'), c['function_name'], json.dumps(c.get('arguments')), (s.get('observation') or {}).get('content', '')))
        by = collections.Counter(a for a in seq if 'ALREADY SHOWN' in a[3] for a in [a[0]])
        fixer = [x for x in seq if x[0] == 'fixer']
        first_view = next((x for x in fixer if 'view.py' in x[2]), None)
        cross = first_view is not None and 'ALREADY SHOWN' in first_view[3]
        # any fixer view refused whose range the LOCATOR had viewed (cross-stage refusal)
        loc_calls = {x[2] for x in seq if x[0] == 'locator'}
        cross_n = sum(1 for x in fixer if 'ALREADY SHOWN' in x[3] and x[2] in loc_calls)
        rows.append((os.path.basename(d), res['resolved'], by, cross, cross_n, sum(1 for x in seq if 'ALREADY SHOWN' in x[3])))
    n = len(rows)
    if not n: print(label, 'no items'); return
    tot = sum(r[5] for r in rows)
    fx = sum(r[2].get('fixer', 0) for r in rows); lc = sum(r[2].get('locator', 0) for r in rows); vf = sum(r[2].get('verifier', 0) for r in rows)
    first = [r for r in rows if r[3]]
    print(f'{label}: items {n} solved {sum(r[1] for r in rows)} | ALREADY SHOWN replies {tot} (locator {lc}, fixer {fx}, verifier {vf})')
    print(f'   items whose FIRST fixer view was refused (stage-crossing): {len(first)} -> solved {sum(r[1] for r in first)}; others {n-len(first)} -> solved {sum(r[1] for r in rows if not r[3])}')
    print(f'   fixer refusals on a call identical to a locator call: {sum(r[4] for r in rows)}')
analyze('v7c s50+probe', '/home/jc/g4/runs/p2/items/v7c/*/traces/trace_*.json')
analyze('v7c probe', '/home/jc/g4/runs/p2/probe_v7c_T2/v7c/*/traces/trace_*.json')
analyze('v7  s50', '/home/jc/g4/runs/p2/items/v7/*/traces/trace_*.json')
analyze('v7  P4 (public 74)', '/home/jc/g4/runs/p4_v7/results/traces/trace_*.json')
analyze('v5h2 P4', '/home/jc/g4/runs/p4/results/traces/trace_*.json')
