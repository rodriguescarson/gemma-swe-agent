"""Seconds each cut removes per task, ALL tasks (p1_v10 + r2_v10_1), public L4 and hidden-stretched (k=1.9, 2.5)."""
import random, statistics as st
from analyze import BY, T, dur, tasks_of
from replay import VARIANTS, P_OBEY
def run_all(run, k, cap, t_loc=75.0, p_obey=P_OBEY, hard=False, drop=None, reply_cut=0.0, fixed_save=0.0, clock_mult=1.0, rnd=None):
    k0=T[next(x for x in T if x[0]==run)]['scale']; out=[]
    for tid in tasks_of(run):
        steps=[dict(s,d=dur(s,k0)) for s in BY[(run,tid)]]
        t=-fixed_save; cut=False; work=0.0
        for i,s in enumerate(steps):
            if s['author']=='locator' and cut and s['fn'] is not None: continue
            if drop and drop(s,i,steps): continue
            d=s['d']*k
            if s['fn'] is None and s['author']=='locator' and reply_cut: d=max(0.0,(s['d']-reply_cut)*k)
            t+=d
            if s['author']=='locator' and s['fn'] is not None and not cut and t>=t_loc*clock_mult:
                if hard or rnd.random()<p_obey: cut=True
        out.append(t)
    return out
rnd=random.Random(3)
print('variant'.ljust(46)+'  public L4 s removed/task | hidden k=1.9: work removed, wall saved (cap) | k=2.5: work, wall')
base={}
for name,kw in VARIANTS:
    kw=dict(kw); cap=kw.pop('cap_',300.0)
    res=[]
    for k in (1.0,1.9,2.5):
        tot_w=tot_wall=n=0
        for run in ('p1_v10','r2_v10_1'):
            for _ in range(60):
                b=run_all(run,k,300.0,rnd=rnd)
                v=run_all(run,k,cap,rnd=rnd,**kw)
                for x,y in zip(b,v):
                    tot_w+=x-y; tot_wall+=min(x,300.0)-min(y,cap); n+=1
        res.append((tot_w/n,tot_wall/n))
    print(name.ljust(46)+f'  {res[0][0]:6.1f}                 | {res[1][0]:6.1f}  {res[1][1]:6.1f}                             | {res[2][0]:6.1f}  {res[2][1]:6.1f}')
