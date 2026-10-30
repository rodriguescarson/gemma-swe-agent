import sys, json, collections, re
sys.path.insert(0,'<scratch>/assume/nearmiss/scripts')
from classify import *

PASS=('PASSED','XPASS')
def sets(task):
    br,bp=bt[task]; gr,gp=gt[task]
    B=bp['nodes']; G=gp['nodes']
    gpass={n for n,s in G.items() if s in PASS}
    bpass={n for n,s in B.items() if s in PASS}
    f2p={n for n in gpass if n not in bpass}          # fails (or is not collected) on base, passes on gold
    p2p=gpass&bpass
    return f2p,p2p,br,gr

def classify(task,r,p):
    f2p,p2p,br,gr=sets(task)
    nodes=p['nodes']
    pp={n for n,s in nodes.items() if s in PASS}
    pf={n for n,s in nodes.items() if s in('FAILED','ERROR')}
    coll=bool(p['interrupted']) or (not pp and bool(p['collection_errors']))
    f2p_fail=f2p-pp           # F2P nodes not passing (failed, errored or never ran)
    p2p_fail=p2p-pp
    d=dict(f2p=len(f2p),p2p=len(p2p),f2p_pass=len(f2p&pp),f2p_fail=len(f2p_fail),p2p_fail=len(p2p_fail),
           coll=coll,kinds=p['kinds'],summary=r['test_summary'],base_resolved=br['resolved'],gold_resolved=gr['resolved'],
           f2p_fail_ids=sorted(f2p_fail)[:6],p2p_fail_ids=sorted(p2p_fail)[:6],collection_errors=p['collection_errors'][:3])
    if r['resolved']: d['cls']='resolved'
    elif coll: d['cls']='collection'
    elif d['p2p_fail']>0: d['cls']='regression'
    elif len(f2p)==0: d['cls']='no_f2p_but_fail'
    elif d['f2p_fail']==1 and len(f2p)>1: d['cls']='near_miss'
    elif d['f2p_fail']==1 and len(f2p)==1: d['cls']='single_f2p_fail'   # the task has just one F2P test and it fails -> "far" by definition, but one-test tasks
    elif d['f2p_pass']>0 and d['f2p_fail']>1: d['cls']='partial'
    elif d['f2p_pass']==0: d['cls']='far'
    else: d['cls']='unresolved_all_pass?'
    return d
if __name__=='__main__':
    t_f2p=collections.Counter(); out=[]
    for i,(e,r,p) in main.items():
        d=classify(e['task'],r,p); d.update(idx=i,task=e['task'],cfg=e['cfg'],resolved=r['resolved'])
        out.append(d)
    json.dump(out,open(N+'/classified.json','w'),indent=1)
    c=collections.Counter(d['cls'] for d in out); print(c)
    # F2P sizes
    print('F2P size distribution over unresolved tasks:',collections.Counter(d['f2p'] for d in out if not d['resolved']))
    print('gold resolved over tasks:',collections.Counter(g[0]['resolved'] for g in gt.values()), 'base resolved:',collections.Counter(b[0]['resolved'] for b in bt.values()))
    print('tasks with f2p==0:',[t for t in gt if not sets(t)[0]])
