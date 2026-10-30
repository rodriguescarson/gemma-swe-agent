import sys, numpy as np, json
sys.argv=['x','lbnow/gemma-4-developer-agent-publicleaderboard-2026-10-30T12:52:00.csv']
import npmle as M
from npmle import *
obs={t:int((M.K>=t).sum()) for t in (10,11,12,13,14,15,17)}
print('observed',obs)
out={}
for sigma in (1.2,1.56,2.0):
    for fail in (0.2,):
        L=M.loglik_matrix(sigma,fail)
        for cap in (None,9.0,10.0,11.0,12.0):
            pi,ll=M.em(L,cap,iters=1500)
            S=M.simulate(pi,sigma,fail,nsim=120,seed=3)
            row={}
            for t in (11,12,13,14,15,17):
                c=(S>=t).sum(1)
                row[t]=(float(c.mean()), float((c>=obs[t]).mean()))
            mx=S.max(1)
            print(f'sigma={sigma} fail={fail} cap={cap}: ' + ' '.join(f'>={t}: E={row[t][0]:.1f} P(>=obs)={row[t][1]:.2f}' for t in row) + f'  maxK mean={mx.mean():.1f} P(max>=17)={(mx>=17).mean():.2f} P(max>=14)={(mx>=14).mean():.2f}')
