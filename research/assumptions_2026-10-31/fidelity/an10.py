import json, glob, os, collections, re
valid=set(l.strip() for l in open('<repo>/data/kaggle_valid_ids.txt') if l.strip())
for name,td in (('v12','tr_v12'),('garble','tr_garble')):
    strat=collections.Counter(); msgs=collections.Counter(); occ=collections.Counter()
    for p in sorted(glob.glob(td+'/traces/trace_*.json')):
        i=os.path.basename(p)[6:-5]
        if i not in valid: continue
        t=json.load(open(p))
        for s in t['steps']:
            tcs=s.get('tool_calls') or []
            obs=s.get('observation')
            if not tcs or tcs[0]['function_name']!='edit_file' or not obs: continue
            c=obs.get('content') if isinstance(obs,dict) else None
            try: j=json.loads(c)
            except Exception: continue
            if j.get('status')=='ok': strat[j.get('strategy')]+=1; occ[j.get('occurrences')]+=1
            else:
                m=(j.get('error_message') or j.get('error') or '')[:70]
                m=re.sub(r"'[^']*'","'..'",m); m=re.sub(r'\d+','N',m)
                msgs[m]+=1
    print(name,'ok strategies',dict(strat),'occurrences',dict(occ))
    for m,c in msgs.most_common(5): print('    ',c,m)
