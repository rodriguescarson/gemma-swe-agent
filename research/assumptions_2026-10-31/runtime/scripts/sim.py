import sys; sys.path.insert(0,'<scratch>/assume/runtime/scripts')
from extract import *
import numpy as np, json
# per-run records pooled over the two real-L4 thinking-on runs (base-failing 71 each)
def records():
    R=[]
    for run in ('v12','garble'):
        for a in load_all(run):
            if a['base']: continue
            capped=a['end']=='cap'
            t_end=None if capped else (a['submit_t'] if a['submit_t'] else a['last_el'])
            t_solve=a['last_src_edit'] if a['resolved'] else None
            R.append(dict(run=run,id=a['id'],solved=a['resolved'],capped=capped,t_end=t_end,t_solve=t_solve,secs=a['secs']))
    return R
R=records()
def outcome(r,k,C,vol=0.17):
    """per-run (clock seconds spent, solved?, capped?) under slowdown k and cap C (seconds, agent clock)"""
    if r['capped']:
        # ran to >=300 s locally; with slowdown it is still capped; for C>300 a share vol ends voluntarily early (mean at C - ~)
        t=C if C<=300 else 300+(C-300)*(1-0.5*vol*1.0)
        capped=True
        # extra solves for C>300 handled separately via hazard (see ext)
        solved=False if not r['solved'] else (k*(r['t_solve'] or 0)<=C)
        if r['solved']: t=min(t, C)
        return t,solved,capped
    te=k*r['t_end']
    if te>C: 
        return C, (r['solved'] and k*r['t_solve']<=C), True
    return te, r['solved'], False
def summarize(w=None,k=1.0,C=300,ovh=10,N=120,S=700,ext_hazard=0.0):
    """w: weights per record (default 1). returns dict"""
    if w is None: w=np.ones(len(R))
    w=np.asarray(w,float)/np.sum(w)
    ts=[];sol=[];cap=[]
    for r in R:
        t,s,c=outcome(r,k,C); ts.append(t);sol.append(s);cap.append(c)
    ts=np.array(ts);sol=np.array(sol,float);cap=np.array(cap,float)
    mean_t=float((w*ts).sum()); f=float((w*cap).sum()); p=float((w*sol).sum())
    total_h=(S+N*(mean_t+ovh))/3600
    return dict(mean_t=mean_t,f_cap=f,solve=p,total_h=total_h)
def reweight(p_target):
    sol=np.array([r['solved'] for r in R],float)
    ps=sol.mean()
    # weights so weighted solved fraction = p_target
    ws=p_target/ps; wu=(1-p_target)/(1-ps)
    return np.where(sol==1,ws,wu)
if __name__=='__main__':
    print('records',len(R),'solved frac',np.mean([r['solved'] for r in R]),'capped frac',np.mean([r['capped'] for r in R]))
    for label,w in (('public-like (as measured)',None),('solve-rate matched to 0.17',reweight(0.17)),('solve-rate matched to 0.10',reweight(0.10))):
        print('===',label)
        for k in (1.0,1.2,1.5,1.7):
            for C in (270,300,330,360):
                s=summarize(w,k,C)
                print(f'  k={k:.1f} C={C}: mean {s["mean_t"]:.0f}s f_cap {s["f_cap"]:.2f} solved {s["solve"]:.3f} total(N=120,S=700,ovh=10) {s["total_h"]:.2f} h')
