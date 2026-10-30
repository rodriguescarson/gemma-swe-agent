import json, numpy as np
B='<repo>/eval/a6000/results'
V=[l.strip() for l in open('<repo>/data/kaggle_valid_ids.txt') if l.strip()]
print(len(V))
for run,cap in (('p4_v12',300),('p4_v12b',300),('p4_v12b6',360),('p4_pub024',480),('p4_pub024_6m',360),('p4_v15b',300),('p4_v13',300)):
    rows={}
    for l in open(f'{B}/{run}/results.jsonl'):
        if l.strip():
            r=json.loads(l); rows[r['id']]=r
    R=[rows[i] for i in V if i in rows]
    secs=np.array([r['secs'] for r in R])
    capd=[r for r in R if r.get('err') and 'session timeout' in r['err']]
    ov=np.array([r['secs']-cap for r in capd])
    print(run,'n',len(R),'mean secs %.1f'%secs.mean(),'solved',sum(r['resolved'] for r in R),'capped(err)',len(capd),'overshoot mean %.1f median %.1f max %.1f'%(ov.mean(),np.median(ov),ov.max()),'sum>5s: %d'%((ov>5).sum()),'| n secs>cap+5:',int((secs>cap+5).sum()), ' secs>=cap-1:',int((secs>=cap-1).sum()))
    # mean secs if overshoot truncated to 6
    s2=np.where(secs>cap+6,cap+6,secs)
    print('    mean secs with overshoot truncated at +6: %.1f ; non-capped rows mean %.1f'%(s2.mean(), np.mean([r['secs'] for r in R if r not in capd])))
