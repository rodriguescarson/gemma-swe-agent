import json, glob, os, collections, re
base='<repo>/eval/a6000/results'
out=[]
for d in sorted(glob.glob(base+'/p4*/results/traces')):
    cfg=d.split('/')[-3]
    strat=collections.Counter(); fail=0; nedit=0
    for p in glob.glob(d+'/trace_*.json'):
        raw=open(p).read()
        for m in re.finditer(r'\\"strategy\\": \\"(\w+)\\"',raw): strat[m.group(1)]+=1
        fail+=len(re.findall(r'old_string not found',raw))
    ok=sum(strat.values())
    out.append((cfg,len(glob.glob(d+'/trace_*.json')),dict(strat),fail))
for o in out: print(o)
for name,td in (('KAGGLE v12','tr_v12'),('KAGGLE garble','tr_garble')):
    strat=collections.Counter(); fail=0
    for p in glob.glob(td+'/traces/trace_*.json'):
        raw=open(p).read()
        for m in re.finditer(r'\\"strategy\\": \\"(\w+)\\"',raw): strat[m.group(1)]+=1
        fail+=len(re.findall(r'old_string not found',raw))
    print(name,dict(strat),fail)
