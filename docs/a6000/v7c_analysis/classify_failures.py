import json, glob, os, re, collections, sys
TASKS = {}
for l in open('/home/jc/g4/gemma-swe-agent/data/heldout1k/harness_s200/tasks.jsonl'):
    r = json.loads(l); TASKS[r['instance_id']] = r
def files_of(diff): return set(re.findall(r'^diff --git a/(\S+) b/', diff or '', re.M))
dirs = glob.glob('/home/jc/g4/runs/p2/items/v7c/*/') + glob.glob('/home/jc/g4/runs/p2/probe_v7c_T2/v7c/*/')
seen = {}
for d in dirs:
    t = os.path.basename(d.rstrip('/'))
    if t in seen or not glob.glob(d + 'task_results.jsonl') or not glob.glob(d + 'traces/trace_*.json'): continue
    seen[t] = d
rows = []
for t, d in sorted(seen.items()):
    res = json.loads(open(d + 'task_results.jsonl').readline())
    steps = json.load(open(glob.glob(d + 'traces/trace_*.json')[0]))['steps']
    patch = open(glob.glob(d + 'patches/*.patch')[0]).read() if glob.glob(d + 'patches/*.patch') else ''
    log = open(glob.glob(d + 'test_outputs/*.log')[0], errors='replace').read() if glob.glob(d + 'test_outputs/*.log') else ''
    gold = files_of(TASKS[t]['patch']); mine = files_of(patch)
    ttests = files_of(TASKS[t]['test_patch'])
    calls = []
    for s in steps:
        for c in s.get('tool_calls') or []:
            calls.append(((c.get('extra') or {}).get('author'), c['function_name'], json.dumps(c.get('arguments')), (s.get('observation') or {}).get('content', '')))
    ran_tests = any(re.search(r'pytest|swe/test\.py|unittest', a[2]) and a[1] == 'run_command' for a in calls)
    wasted = sum(1 for i in range(1, len(calls)) if calls[i][1:3] == calls[i - 1][1:3])
    failed = re.findall(r'^FAILED (\S+)', log, re.M); errors = re.findall(r'^ERROR (\S+)', log, re.M)
    fail_in_target = [f for f in failed if any(f.split('::')[0] == x for x in ttests)]
    regress = [f for f in failed if f not in fail_in_target]
    m = re.search(r'(\d+) failed', log); nfail = int(m.group(1)) if m else 0
    hit = 'all' if gold and gold <= mine else ('part' if gold & mine else 'none')
    if res['resolved']: cls = 'SOLVED'
    elif res['agent_patch_size'] == 0: cls = 'E empty patch'
    elif res['tool_calls'] >= 68 and wasted >= 10: cls = 'A budget burned by loop'
    elif res['tool_calls'] >= 68: cls = 'A2 budget exhausted (no loop)'
    elif errors and not failed: cls = 'D collect/import error (names/API mismatch)'
    elif hit == 'none': cls = 'B localization miss (gold files untouched)'
    elif regress and len(regress) >= 3: cls = 'F regressions (breaks passing tests)'
    else: cls = 'C right file, wrong fix'
    rows.append((t, cls, hit, res['tool_calls'], wasted, ran_tests, len(fail_in_target), len(regress), len(errors), sorted(gold), sorted(mine)))
c = collections.Counter(r[1] for r in rows)
print('items', len(rows)); [print(f'  {v:>3}  {k}') for k, v in c.most_common()]
print('\nlocalization (agent patch vs gold files): ', collections.Counter(r[2] for r in rows))
print('verifier/anyone ran tests at all:', sum(r[5] for r in rows), 'of', len(rows), '| unsolved that never ran tests:', sum((not r[5]) for r in rows if r[1] != 'SOLVED'))
print()
for r in rows:
    print(f'{r[0]:<16} {r[1][:34]:<34} loc={r[2]:<4} calls={r[3]:>2} wasted={r[4]:>3} ran_tests={int(r[5])} tgtfail={r[6]} regress={r[7]} err={r[8]} gold={r[9]} mine={r[10]}')
