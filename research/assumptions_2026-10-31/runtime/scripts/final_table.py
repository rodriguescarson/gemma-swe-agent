import sys; sys.path.insert(0,'<scratch>/assume/runtime/scripts')
from sim import *
import numpy as np
n_capuns=sum(1 for r in R if r['capped'] and not r['solved'])/len(R)   # share of runs capped & unsolved locally
print('local capped&unsolved share of base-failing runs: %.3f'%n_capuns)
scen=[('S1 public-like k=1.0',None,1.0,0.408),('S2 central: solve 0.17, k=1.15',reweight(0.17),1.15,0.17),('S3 slow: solve 0.17, k=1.7',reweight(0.17),1.7,0.17),('S4 slow+hard: solve 0.10, k=1.7',reweight(0.10),1.7,0.10)]
H60=0.08
print('cap(min) | for each scenario: f_cap, mean agent clock s, total h (N=120,S=700,ovh=10), d_solves_vs_5min on 58 tasks [recoveries + hazard-extension]')
for name,w,k,p in scen:
    print('==',name)
    base=summarize(w,k,300)
    wn=np.ones(len(R))/len(R) if w is None else np.asarray(w)/np.sum(w)
    capuns_w=sum(wi for wi,r in zip(wn,R) if r['capped'] and not r['solved'])
    for C in (270,300,330,360):
        s=summarize(w,k,C)
        sh=p/0.408; ext=capuns_w*H60*sh*max(0,(C-300))/60.0
        dsol=(s['solve']-base['solve']+ext)*58
        # worst-case range for the extension hazard 0.04-0.12
        lo=(s['solve']-base['solve']+capuns_w*0.04*sh*max(0,(C-300))/60.0)*58
        hi=(s['solve']-base['solve']+capuns_w*0.12*sh*max(0,(C-300))/60.0)*58
        print(f'  {C/60:4.1f} min: f_cap {s["f_cap"]:.2f} mean {s["mean_t"]:.0f}s total {s["total_h"]:.2f} h  d_solves {dsol:+.2f} [{lo:+.2f},{hi:+.2f}]')
