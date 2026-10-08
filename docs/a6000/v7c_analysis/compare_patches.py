import json, glob, re, sys
T = {}
for l in open('/home/jc/g4/gemma-swe-agent/data/heldout1k/harness_s200/tasks.jsonl'):
    r = json.loads(l); T[r['instance_id']] = r
for t in sys.argv[1:]:
    d = glob.glob(f'/home/jc/g4/runs/p2/items/v7c/{t}/') + glob.glob(f'/home/jc/g4/runs/p2/probe_v7c_T2/v7c/{t}/')
    d = d[0]
    mine = open(glob.glob(d + 'patches/*.patch')[0]).read()
    log = open(glob.glob(d + 'test_outputs/*.log')[0], errors='replace').read()
    es = [l for l in log.splitlines() if l.startswith('E ')][:6]
    print('='*100); print(t); print('STATEMENT:', T[t]['problem_statement'][:600].replace('\n', ' | '))
    print('--- GOLD:'); print(T[t]['patch'][:1400])
    print('--- AGENT:'); print(mine[:1400])
    print('--- FAIL MSG:'); print('\n'.join(es))
