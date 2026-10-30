import json, numpy as np
B='<repo>/eval/a6000/results'
V=[l.strip() for l in open('<repo>/data/kaggle_valid_ids.txt') if l.strip()]
for run,cap in (('p4_v12',300),('p4_v12b',300),('p4_v12b6',360),('p4_pub024',480),('p4_pub024_6m',360),('p4_v15b',300),('p4_v13',300),('p4_v12c',480),('p4_v12a',480)):
    rows={}
    try:
        for l in open(f'{B}/{run}/results.jsonl'):
            if l.strip():
                r=json.loads(l); rows[r['id']]=r
    except Exception as e: print(run,e); continue
    out=[(r['id'],r['secs'],r.get('err')) for i,r in rows.items() if r['secs']>cap+5.9]
    print(run,len(rows),out)
