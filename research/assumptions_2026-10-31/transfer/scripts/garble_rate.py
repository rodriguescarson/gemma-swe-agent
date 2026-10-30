import json, re, glob, os, collections, sys
sys.path.insert(0,'scripts')
BASE='<repo>'
def garbled(a):
    if 'old_string' not in a and 'new_string' in a: return 'nokey'
    o=a.get('old_string','') or ''; n=a.get('new_string','') or ''
    if re.search(r'\\"', o+n) or ('\n' not in o and re.search(r'(?<!\\)\\n', o)): return 'escape'
    return None
def from_trace_dir(tdir):
    calls=[]
    for f in sorted(glob.glob(f'{tdir}/trace_*.json')):
        t=json.load(open(f)); tid=os.path.basename(f)[6:-5]
        for s in t['steps']:
            for i,tc in enumerate(s.get('tool_calls') or []):
                if tc['function_name']!='edit_file': continue
                ob=(s.get('observation') or {}).get('content') or ''
                calls.append((tid, tc.get('arguments') or {}, ob if i==0 else ''))
    return calls
def stats(name, calls, nruns):
    e=len(calls); fail=sum(1 for _,a,o in calls if 'old_string not found' in o)
    g=sum(1 for _,a,o in calls if garbled(a)); gf=sum(1 for _,a,o in calls if garbled(a) and 'old_string not found' in o)
    # garbled but succeeded?
    print(f'{name:38s} runs {nruns:4d} edit_calls {e:5d} ({e/nruns:4.1f}/run) not_found {fail:4d} ({100*fail/max(e,1):4.0f}% of edits, {fail/nruns:4.2f}/run) garbled-looking {g:4d} (of which failed {gf})')
# P10
R=json.load(open('out/p10_runs.json'))
c10=[(tid,c['args'],c['result'] or '') for tid,v in R.items() for c in v['calls'] if c['name']=='edit_file']
stats('P10 v12 non-public (box, T1.0)', c10, len(R))
# time pattern within P10: by task order
items=[json.loads(l) for l in open('p3/items.jsonl')]
order={i['task']:k for k,i in enumerate(sorted(items,key=lambda x:x['t0']))}
for q in range(4):
    sub=[x for x in c10 if q*117<=order[x[0]]<(q+1)*117]
    f=sum(1 for _,a,o in sub if 'old_string not found' in o)
    print(f'   P10 quarter {q+1}: edits {len(sub)} not_found {f} ({100*f/len(sub):.0f}%)')
for name,d in [('PUBLIC Kaggle L4 v12 (T1.0)',f'{BASE}/eval/kaggle/g4-l4-v12-p312/results/traces'),
               ('PUBLIC Kaggle L4 v12b-garble',f'{BASE}/eval/kaggle/g4-l4-v12b-garble-p312/results/traces')]:
    cl=from_trace_dir(d); stats(name, cl, len(glob.glob(d+'/trace_*.json')))
tot=[];nr=0
for arm in ['p4_v12','p4_v12a','p4_v12b','p4_v12b6','p4_v12c','p4_v12r','p4_b1024','p4_pub024','p4_v0t2']:
    d=f'{BASE}/eval/a6000/results/{arm}/results/traces'
    cl=from_trace_dir(d); n=len(glob.glob(d+'/trace_*.json')); stats('PUBLIC box '+arm, cl, n); tot+=cl; nr+=n
stats('PUBLIC box all 9 arms pooled', tot, nr)
