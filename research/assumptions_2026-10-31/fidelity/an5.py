import json, glob, os, re, collections
valid=set(l.strip() for l in open('<repo>/data/kaggle_valid_ids.txt') if l.strip())
rx=re.compile(r'swegemma_sandbox_[0-9a-f-]+_\w+')
for name,td in (('v12','tr_v12'),('garble','tr_garble')):
    runs=0; occ=0; nruns=0; extra=0; calls_with=0; calls=0
    for p in sorted(glob.glob(td+'/traces/trace_*.json')):
        i=os.path.basename(p)[6:-5]
        if i not in valid: continue
        nruns+=1
        t=json.load(open(p)); hit=0
        for s in t['steps']:
            obs=s.get('observation')
            txt=json.dumps(obs) if obs else ''
            calls+= 1 if obs else 0
            m=rx.findall(txt)
            if m: calls_with+=1
            hit+=len(m); extra+=sum(len(x) for x in m)
        if hit: runs+=1; occ+=hit
    print(name,'runs',nruns,'runs with sandbox-root path in observations',runs,'occurrences',occ,'chars',extra,'obs steps with',calls_with,'of',calls)
