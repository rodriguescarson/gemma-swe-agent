import json, hashlib, collections, re, sys
sys.path.insert(0,'scripts')
from failmodes import analyse, parse_res
CAP='<repo>/eval/kaggle/g1_devstral/capture_devstral.jsonl'
def text(u): return u if isinstance(u,str) else ''.join(x.get('text','') if isinstance(x,dict) else str(x) for x in u)
by=collections.defaultdict(list)
for l in open(CAP):
    d=json.loads(l); ms=d['body']['messages']
    if len(ms)<2: continue
    u=text(ms[1]['content'])
    key=hashlib.md5(u.encode()).hexdigest() if u.startswith('You are evaluating') else 'cont'
    by[key].append(d)
print('groups', len(by), 'cont calls', len(by.get('cont',[])))
runs={}
for k,recs in by.items():
    if k=='cont': continue
    recs.sort(key=lambda d:d['t'])
    calls=[]; results={}
    for d in recs:
        m=d['response']['choices'][0]['message']
        for tc in (m.get('tool_calls') or []):
            try: a=json.loads(tc['function']['arguments'])
            except Exception: a={'_raw':tc['function']['arguments']}
            calls.append({'id':tc['id'],'name':tc['function']['name'],'args':a})
        for mm in d['body']['messages']:
            if mm['role']=='tool': results[mm.get('tool_call_id')]=mm['content'] if isinstance(mm['content'],str) else json.dumps(mm['content'])
    # continuations: attach by id later
    runs[k]={'calls':calls,'results':results,'recs':recs}
# attach continuation calls by shared tool ids
idx={}
for k,r in runs.items():
    for c in r['calls']: idx[c['id']]=k
for d in sorted(by.get('cont',[]), key=lambda d:d['t']):
    ids=[m.get('tool_call_id') for m in d['body']['messages'] if m['role']=='tool']
    ks=[idx[i] for i in ids if i in idx]
    if not ks: continue
    k=collections.Counter(ks).most_common(1)[0][0]
    m=d['response']['choices'][0]['message']
    for tc in (m.get('tool_calls') or []):
        try: a=json.loads(tc['function']['arguments'])
        except Exception: a={'_raw':tc['function']['arguments']}
        runs[k]['calls'].append({'id':tc['id'],'name':tc['function']['name'],'args':a}); idx[tc['id']]=k
    for mm in d['body']['messages']:
        if mm['role']=='tool': runs[k]['results'][mm.get('tool_call_id')]=mm['content'] if isinstance(mm['content'],str) else json.dumps(mm['content'])
out={}
for k,r in runs.items():
    seen=set(); cl=[]
    for c in r['calls']:
        if c['id'] in seen: continue
        seen.add(c['id']); cl.append({'name':c['name'],'args':c['args'],'res':parse_res(r['results'].get(c['id']))})
    out[k]={'calls':cl,'solved':None}
res=[json.loads(l) for l in open('<repo>/eval/kaggle/g1_devstral/results.jsonl')]
print('tasks', len(res), 'solved', sum(r['resolved'] for r in res), 'mean tool calls', sum(r['tool_calls'] for r in res)/len(res))
per=analyse(out)
n=len(per)
print('runs', n, 'tool calls', sum(f['n_calls'] for f in per.values()))
for k in ['no_check_attempted','check_never_ok','any_path_not_found','any_no_tests','any_collect_import','any_usage','any_timeout','first_test_bad','grep_empty_first','modnotfound_any']:
    print(f'  {k:22s} {sum(1 for f in per.values() if f[k])}/{n}')
print('  edit_old_string_miss events', sum(f['edit_old_string_miss'] for f in per.values()), 'read_not_found events', sum(f['read_not_found'] for f in per.values()))
e=sum(1 for r in out.values() for c in r['calls'] if c['name']=='edit_file'); print('  edit calls', e)
tc=collections.Counter(c for f in per.values() for c in f['test_classes']); print('  test cmd classes', dict(tc))
print('--- path_not_found commands')
from failmodes import is_testcmd, classify_test
shown=0
for k,r in out.items():
    for c in r['calls']:
        if c['name']=='run_command' and c['res'] and is_testcmd((c['args'] or {}).get('command')) and classify_test(c['res'])=='path_not_found':
            if shown<8: print('  CMD:', ((c['args'] or {}).get('command') or '')[:140].replace('\n',' '), '| OUT:', c['res']['out'].strip()[:110].replace('\n',' '))
            shown+=1
print('--- flasgger output context')
n=0
for k,r in out.items():
    for c in r['calls']:
        if c['res'] and 'flasgger' in c['res']['out'] and n<2:
            print('CMD:', ((c['args'] or {}).get('command') or '')[:150].replace('\n',' '))
            print(c['res']['out'][:900]); print('=====')
            n+=1
tot=sum(1 for r in out.values() for c in r['calls'] if c['res'] and 'flasgger' in c['res']['out'])
print('calls with flasgger warning in output:', tot, 'of', sum(len(r['calls']) for r in out.values()))
