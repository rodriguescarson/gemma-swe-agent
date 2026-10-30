import json, glob, os
valid=set(l.strip() for l in open('<repo>/data/kaggle_valid_ids.txt') if l.strip())
base_pass={'fastapi_14851','fastapi_14077','requests_6644'}
import statistics as st
for name,td,rp in (('v12','tr_v12','<repo>/eval/kaggle/g4-l4-v12-p312/results.jsonl'),('garble','tr_garble','<repo>/eval/kaggle/g4-l4-v12b-garble-p312/results.jsonl')):
    rows={json.loads(l)['id']:json.loads(l) for l in open(rp)}
    times=[]
    for i,r in rows.items():
        if i not in valid or not r['resolved'] or i in base_pass: continue
        p=f'{td}/traces/trace_{i}.json'
        t=json.load(open(p)); sub=None; last=0
        for s in t['steps']:
            e=s.get('extra') if isinstance(s.get('extra'),dict) else {}
            if e.get('elapsed_s') is not None: last=e['elapsed_s']
            for tc in (s.get('tool_calls') or []):
                if tc.get('function_name')=='submit_patch': sub=e.get('elapsed_s')
        times.append(sub if sub is not None else last)
    times.sort()
    n=len(times)
    print(name,'clean solved',n,'median finish',round(st.median(times)),'solves finishing after: 240s',sum(t>240 for t in times),'255s',sum(t>255 for t in times),'270s',sum(t>270 for t in times),'285s',sum(t>285 for t in times),'(cap 300)')
    # loss if effective time budget shrinks by x% (all steps slower by 1/(1-x)): solves with t > 300*(1-x)
    for x in (0.02,0.05,0.10,0.20):
        thr=300*(1-x); print('   slowdown',x,'-> loses',sum(t>thr for t in times),'of',n)
