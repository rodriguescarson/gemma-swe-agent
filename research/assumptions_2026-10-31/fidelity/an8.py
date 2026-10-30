import json, glob, os, collections, ast
valid=set(l.strip() for l in open('<repo>/data/kaggle_valid_ids.txt') if l.strip())
res={}
for name,td in (('v12','tr_v12'),('garble','tr_garble')):
    keys=collections.defaultdict(collections.Counter)
    for p in sorted(glob.glob(td+'/traces/trace_*.json')):
        i=os.path.basename(p)[6:-5]
        if i not in valid: continue
        t=json.load(open(p))
        for s in t['steps']:
            tcs=s.get('tool_calls') or []
            obs=s.get('observation')
            if not tcs or not obs: continue
            c=obs.get('content') if isinstance(obs,dict) else None
            if c is None: continue
            try: j=json.loads(c)
            except Exception: continue
            if isinstance(j,dict):
                keys[tcs[0]['function_name']][tuple(sorted(j.keys()))]+=1
    res[name]=keys
for tool in sorted(set(res['v12'])|set(res['garble'])):
    a=res['v12'].get(tool,{}); b=res['garble'].get(tool,{})
    ks=set(a)|set(b)
    print(tool)
    for k in sorted(ks,key=lambda k:-(a.get(k,0)+b.get(k,0)))[:6]:
        print('   ',k,'v12',a.get(k,0),'garble',b.get(k,0))
