"""Convention-related failure-mode counters, same definitions on P10 (v12, 468 non-public-repo tasks) and on the public
74 (Kaggle L4 v12 run + the A6000 v12 / v12b runs). Prints a table and writes out/failmodes.json."""
import json, re, glob, os, collections, sys
BASE = '<repo>'
TESTCMD = re.compile(r'(?:^|[\s;&|(])(?:python3?\s+-m\s+)?(pytest|py\.test|unittest|tox|nox)\b|make\s+test|\./?(?:run_)?tests?\.sh', re.I)
def is_testcmd(cmd): return bool(TESTCMD.search(cmd or ''))
def parse_res(r):
    if r is None: return None
    try: j = json.loads(r)
    except Exception: return {'status': '?', 'out': r}
    if not isinstance(j, dict): return {'status': '?', 'out': str(j)}
    d = j.get('details') or {}
    out = (j.get('stdout') or d.get('stdout') or '') + '\n' + (j.get('stderr') or d.get('stderr') or '') + '\n' + (j.get('error_message') or j.get('error') or '')
    ec = j.get('exit_code', d.get('exit_code'))
    return {'status': j.get('status'), 'etype': j.get('error_type'), 'out': out, 'exit': ec}
def classify_test(res):
    o = res['out']; ol = o.lower()
    if res.get('etype') == 'TimeoutExceeded' or res.get('exit') in (124, 137): return 'timeout'
    if re.search(r'file or directory not found|no such file or directory|not found: ', ol) and ('pytest' in ol or 'error' in ol): return 'path_not_found'
    if re.search(r'no module named pytest|unrecognized arguments|usage: pytest|error: unrecognized|unknown option', ol): return 'usage_or_missing_runner'
    if re.search(r'no tests ran|collected 0 items|no tests collected|ran 0 tests|0 tests ran', ol): return 'no_tests_collected'
    if re.search(r'error collecting|errors? during collection|importerror|modulenotfounderror', ol): return 'collect_or_import_error'
    if re.search(r'\bfailed\b|\bfailures?\b|assertionerror|\berror\b', ol) and not re.search(r'\d+ passed', ol) : return 'tests_failed'
    if re.search(r'\d+ passed|^ok$|\nok\n|ran \d+ tests?.*\n+ok', ol, re.S): return 'passed_or_failed_mixed' if re.search(r'\d+ failed', ol) else 'passed'
    return 'other'
def runs_from_p10():
    R = json.load(open('out/p10_runs.json'))
    res = {}
    for l in open(f'{BASE}/eval/a6000/results/p3_think/items/v12/{{}}'.format('x'), 'r') if False else []: pass
    out = {}
    for tid, v in R.items():
        tr = f'{BASE}/eval/a6000/results/p3_think/items/v12/{tid}/task_results.jsonl'
        solved = None
        if os.path.exists(tr):
            solved = json.loads(open(tr).readline()).get('resolved')
        calls = [{'name': c['name'], 'args': c['args'], 'res': parse_res(c['result'])} for c in v['calls']]
        out[tid] = {'calls': calls, 'solved': solved}
    return out
def runs_from_traces(tdir, results_jsonl=None):
    out = {}
    solved = {}
    if results_jsonl and os.path.exists(results_jsonl):
        for l in open(results_jsonl):
            r = json.loads(l); solved[r.get('id') or r.get('instance_id')] = r.get('resolved')
    for f in sorted(glob.glob(f'{tdir}/trace_*.json')):
        tid = os.path.basename(f)[6:-5]
        t = json.load(open(f))
        calls = []
        for s in t['steps']:
            tcs = s.get('tool_calls') or []
            ob = (s.get('observation') or {}).get('content')
            for i, tc in enumerate(tcs):
                calls.append({'name': tc['function_name'], 'args': tc.get('arguments') or {}, 'res': parse_res(ob if i == 0 else None)})
        out[tid] = {'calls': calls, 'solved': solved.get(tid)}
    return out
def analyse(runs):
    n = len(runs); S = collections.Counter(); per = {}
    tot_calls = 0
    for tid, r in runs.items():
        calls = r['calls']; tot_calls += len(calls)
        test_calls = [c for c in calls if c['name'] == 'run_command' and is_testcmd((c['args'] or {}).get('command'))]
        cls = [classify_test(c['res']) if c['res'] else 'no_result' for c in test_calls]
        f = {'n_calls': len(calls), 'n_test_cmds': len(test_calls), 'test_classes': cls}
        f['no_check_attempted'] = len(test_calls) == 0
        f['check_never_ok'] = len(test_calls) > 0 and not any(c in ('passed', 'passed_or_failed_mixed', 'tests_failed') for c in cls)
        f['any_path_not_found'] = 'path_not_found' in cls
        f['any_no_tests'] = 'no_tests_collected' in cls
        f['any_collect_import'] = 'collect_or_import_error' in cls
        f['any_usage'] = 'usage_or_missing_runner' in cls
        f['any_timeout'] = 'timeout' in cls
        # first test command: wasted?
        f['first_test_bad'] = bool(cls) and cls[0] in ('path_not_found', 'no_tests_collected', 'usage_or_missing_runner', 'timeout', 'collect_or_import_error')
        # read_file not found
        f['read_not_found'] = sum(1 for c in calls if c['name'] == 'read_file' and c['res'] and c['res'].get('status') == 'error' and re.search(r'not found|no such|does not exist|is a directory', c['res']['out'].lower()))
        f['edit_old_string_miss'] = sum(1 for c in calls if c['name'] == 'edit_file' and c['res'] and re.search(r'old_string not found|not unique|multiple', c['res']['out'].lower()))
        f['modnotfound_any'] = any(c['res'] and 'modulenotfounderror' in c['res']['out'].lower() for c in calls if c['name'] == 'run_command')
        gr = [c for c in calls if c['name'] == 'run_command' and re.search(r'git grep|grep -r|grep -n', (c['args'] or {}).get('command') or '')]
        f['grep_empty_first'] = bool(gr) and gr[0]['res'] is not None and not (gr[0]['res']['out'].strip())
        # python invocation of the repo under test: 'python3 -m pytest' vs missing pytest plugin; also 'python' not found
        f['python_cmd_not_found'] = any(c['res'] and re.search(r'python: (command )?not found|python3: (command )?not found', c['res']['out'].lower()) for c in calls if c['name'] == 'run_command')
        per[tid] = f; 
    return per
def table(name, per, runs):
    n = len(per); print(f'--- {name}: n={n} runs, {sum(f["n_calls"] for f in per.values())} tool calls')
    keys = ['no_check_attempted', 'check_never_ok', 'any_path_not_found', 'any_no_tests', 'any_collect_import', 'any_usage', 'any_timeout', 'first_test_bad', 'grep_empty_first', 'modnotfound_any', 'python_cmd_not_found']
    rows = {}
    for k in keys:
        a = [t for t, f in per.items() if f[k]]
        s = [t for t in a if runs[t]['solved'] is True]; known = [t for t in a if runs[t]['solved'] is not None]
        rows[k] = (len(a), len(s), len(known))
        print(f'  {k:24s} runs {len(a):4d} ({100*len(a)/n:5.1f}%)  solved among them {len(s)}/{len(known)}' + (f' = {100*len(s)/len(known):.0f}%' if known else ''))
    for k in ('read_not_found', 'edit_old_string_miss'):
        a = [t for t, f in per.items() if f[k] > 0]
        print(f'  {k:24s} runs {len(a):4d} ({100*len(a)/n:5.1f}%)  total events {sum(f[k] for f in per.values())}')
    tc = collections.Counter(c for f in per.values() for c in f['test_classes'])
    print('  test-command outcome classes (events):', dict(tc.most_common()))
    sv = [r['solved'] for r in runs.values() if r['solved'] is not None]
    if sv: print(f'  solved {sum(sv)}/{len(sv)} = {100*sum(sv)/len(sv):.1f}%')
    return rows
if __name__ == '__main__':
    out = {}
    p10 = runs_from_p10(); per10 = analyse(p10); out['p10'] = per10
    table('P10 v12 on non-public repos (T=1.0, A6000)', per10, p10)
    K = f'{BASE}/eval/kaggle/g4-l4-v12-p312'
    pub = runs_from_traces(f'{K}/results/traces', f'{K}/results.jsonl')
    perk = analyse(pub); out['pub_kaggle_v12'] = perk
    table('PUBLIC 74, Kaggle 4xL4 v12 (T=1.0)', perk, pub)
    json.dump(out, open('out/failmodes.json', 'w'))
