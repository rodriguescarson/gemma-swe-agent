import json, glob, os, re, collections
base='<repo>/eval/a6000/results'
valid=set(l.strip() for l in open('<repo>/data/kaggle_valid_ids.txt') if l.strip())
rx_tmp=re.compile(r'(?<![\w.-])/tmp\b'); rx_pt=re.compile(r'pytest')
for d in sorted(glob.glob(base+'/p4*/results/traces')):
    cfg=d.split('/')[-3]
    n=0; tmp=0; pt=0; pip=0
    for p in glob.glob(d+'/trace_*.json'):
        i=os.path.basename(p)[6:-5]
        if i not in valid: continue
        n+=1; t=json.load(open(p)); a=b=c=False
        for s in t['steps']:
            for tc in (s.get('tool_calls') or []):
                if tc.get('function_name')=='run_command':
                    cmd=(tc.get('arguments') or {}).get('command') or ''
                    a|=bool(rx_tmp.search(cmd)); b|=bool(rx_pt.search(cmd)); c|=bool(re.search(r'pip3? install',cmd))
        tmp+=a; pt+=b; pip+=c
    if n>=70: print(f'{cfg:14s} runs {n} /tmp {tmp:3d} pytest {pt:3d} pip {pip}')
