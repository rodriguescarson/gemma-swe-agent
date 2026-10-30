import json, glob, os, re, collections
valid=set(l.strip() for l in open('<repo>/data/kaggle_valid_ids.txt') if l.strip())
for name,td in (('v12','tr_v12'),('garble','tr_garble')):
    n=0; envfail=0; ex=collections.Counter(); samples=[]
    for p in sorted(glob.glob(td+'/traces/trace_*.json')):
        i=os.path.basename(p)[6:-5]
        if i not in valid: continue
        t=json.load(open(p))
        for s in t['steps']:
            for tc in (s.get('tool_calls') or []):
                if tc.get('function_name')!='run_command': continue
                cmd=(tc.get('arguments') or {}).get('command') or ''
                if 'pytest' not in cmd: continue
                obs=s.get('observation'); c=obs.get('content') if isinstance(obs,dict) else str(obs)
                n+=1
                try: j=json.loads(c)
                except Exception: j={}
                code=(j.get('exit_code') if 'exit_code' in j else (j.get('details') or {}).get('exit_code'))
                ex[code]+=1
                txt=c
                if re.search(r'ModuleNotFoundError|ImportError|No module named|ERROR collecting|fixture .* not found',txt):
                    envfail+=1; samples.append((i,re.search(r'(ModuleNotFoundError[^\\\n]*|No module named[^\\\n]*|ERROR collecting[^\\\n]*|fixture[^\\\n]*not found)',txt).group(1)[:90]))
    print(name,'pytest invocations',n,'exit codes',dict(ex),'env-looking failures',envfail)
    for s in samples[:6]: print('    ',s)
