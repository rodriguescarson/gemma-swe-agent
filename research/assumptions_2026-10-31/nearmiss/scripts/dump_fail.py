import sys, json, re, collections
sys.path.insert(0,'<scratch>/assume/nearmiss/scripts')
from classify2 import *
tasks={json.loads(l)['instance_id']:json.loads(l) for l in open('<repo>/data/tasks.jsonl')}
def files(patch):
    return [m.group(2) for m in re.finditer(r'^diff --git a/(.*?) b/(.*)$',patch,re.M)] or [m.group(1) for m in re.finditer(r'^\+\+\+ b/(.*)$',patch,re.M)]
def is_test(f): 
    return bool(re.search(r'(^|/)(tests?|testing)/|(^|/)test_[^/]*\.py$|_test\.py$|conftest\.py$',f))
def failmsg(txt,node):
    m=re.search(r'^(?:FAILED|ERROR) '+re.escape(node)+r'(?: - (.*))?$',txt,re.M)
    return (m.group(1) or '')[:160] if m else ''
res=[]
cls={ (d['task'],d['cfg']):d for d in json.load(open(N+'/classified.json'))}
for i,(e,r,p) in main.items():
    d=classify(e['task'],r,p)
    if r['resolved']: continue
    t=e['task']; txt=open(f"{N}/gr/runs/nm_main/replay_logs/{i}_{t}.log",errors='replace').read()
    gf=[f for f in files(tasks[t]['patch'])]; af=files(e['patch'])
    gs={f for f in gf if not is_test(f)}; as_={f for f in af if not is_test(f)}
    f2p,p2p,_,_=sets(t)
    ff=sorted(f2p-{n for n,s in p['nodes'].items() if s in PASS})
    d.update(task=t,cfg=e['cfg'],idx=i,gold_files=sorted(gs),agent_files=sorted(as_),
             file_rel=('same' if gs==as_ else 'superset' if gs<as_ else 'subset' if as_<gs else 'overlap' if gs&as_ else 'disjoint'),
             msgs=[(n,failmsg(txt,n)) for n in ff[:3]],
             pfmsgs=[(n,failmsg(txt,n)) for n in sorted(p2p-{n for n,s in p['nodes'].items() if s in PASS})[:2]])
    res.append(d)
json.dump(res,open(N+'/fail_dump.json','w'),indent=1)
for d in sorted(res,key=lambda d:(d['cls'],d['task'])):
    print(f"## {d['task']} {d['cfg']} [{d['cls']}] files={d['file_rel']} gold={d['gold_files']} agent={d['agent_files']}")
    for n,m in d['msgs']: print('   F2P-fail:',n.split('/')[-1][:80],'|',m)
    for n,m in d['pfmsgs']: print('   P2P-fail:',n.split('/')[-1][:80],'|',m)
