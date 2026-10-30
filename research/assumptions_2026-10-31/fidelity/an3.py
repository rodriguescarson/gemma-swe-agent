import json, glob, os
valid=set(l.strip() for l in open('<repo>/data/kaggle_valid_ids.txt') if l.strip())
def last_elapsed(path):
    t=json.load(open(path)); m=0
    for s in t['steps']:
        e=s.get('extra')
        if isinstance(e,dict) and e.get('elapsed_s') is not None: m=max(m,e['elapsed_s'])
    return m
for name,rp,td in (('v12','<repo>/eval/kaggle/g4-l4-v12-p312/results.jsonl','tr_v12'),('garble','<repo>/eval/kaggle/g4-l4-v12b-garble-p312/results.jsonl','tr_garble')):
    rows=[json.loads(l) for l in open(rp)]
    out=[]
    for r in rows:
        if r['id'] not in valid: continue
        p=f'{td}/traces/trace_{r["id"]}.json'
        if not os.path.exists(p): continue
        a=last_elapsed(p)
        out.append((r['secs']-a, r['id'], r['secs'], round(a,1), r.get('exit'), r['resolved']))
    out.sort(reverse=True)
    print(name,'top overhead (secs - agent_elapsed) rows:')
    for o in out[:8]: print('  ',round(o[0],1),o[1:])
