import json, glob, os, statistics as st
valid=set(l.strip() for l in open('<repo>/data/kaggle_valid_ids.txt') if l.strip())
base_pass={'fastapi_14851','fastapi_14077','requests_6644'}
def edit_ok(s):
    obs=s.get('observation'); c=obs.get('content') if isinstance(obs,dict) else None
    try: j=json.loads(c)
    except Exception: return False
    return j.get('status')=='ok'
for name,td,rp in (('v12','tr_v12','<repo>/eval/kaggle/g4-l4-v12-p312/results.jsonl'),('garble','tr_garble','<repo>/eval/kaggle/g4-l4-v12b-garble-p312/results.jsonl')):
    rows={json.loads(l)['id']:json.loads(l) for l in open(rp)}
    T=[]
    for i,r in rows.items():
        if i not in valid or not r['resolved'] or i in base_pass: continue
        t=json.load(open(f'{td}/traces/trace_{i}.json')); last=None
        for s in t['steps']:
            e=s.get('extra') if isinstance(s.get('extra'),dict) else {}
            for tc in (s.get('tool_calls') or []):
                if tc.get('function_name') in ('edit_file','write_file') and edit_ok(s): last=e.get('elapsed_s')
        # run_command heredoc edits could also change; ignore
        T.append(last if last is not None else 0)
    T.sort(); n=len(T)
    print(name,'clean solved',n,'median last-edit time',round(st.median(T)),'max',round(max(T)))
    for x in (0.02,0.05,0.10,0.20,0.30):
        thr=300*(1-x); print('   if all steps took',round(1/(1-x),2),'x as long -> solves whose last edit lands after the cap:',sum(t>thr for t in T),'of',n)
