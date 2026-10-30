import numpy as np, math, csv
from scipy.stats import norm
rows=list(csv.DictReader(open('lbnow/gemma-4-developer-agent-publicleaderboard-2026-10-30T12:52:00.csv',encoding='utf-8-sig')))
def kof(s):
    s=round(float(s),2)
    for k in range(59):
        if math.floor(100*k/58)/100==s: return k
N=np.array([int(r['SubmissionCount']) for r in rows]); K=np.array([kof(r['Score']) for r in rows])
obs={t:int((K>=t).sum()) for t in (11,12,13,14,15,17)}
print('observed teams >=t',obs,' total submissions',N.sum(),' teams',len(N))
def Ep(mu,sig,t,f):
    Ne=np.maximum(1,N*(1-f))
    F=norm.cdf((t-1+0.5-mu)/sig)
    return float((1-F**Ne).sum())
print('\nIf EVERY team ran a config with per-draw mean mu (sigma 1.5, 20% of submissions failed), expected # teams with board score >= t:')
print('mu   |  >=11 (obs 917) | >=12 (obs 305) | >=13 (obs 62) | >=14 (obs 7) | >=15 (obs 1) | >=17 (obs 1)')
for mu in (7.5,8.0,8.6,9.0,9.6,10.0,10.5,11.0,12.0):
    print(f'{mu:4.1f} | '+' | '.join(f'{Ep(mu,1.5,t,0.2):8.1f}' for t in (11,12,13,14,15,17)))
print('\nShare of all teams that can run a mean-mu config before the board would show MORE teams at t than observed (phi = obs/expected-if-all):')
for sig in (1.2,1.5,2.0):
    print(f'sigma={sig}')
    for mu in (8.6,9.6,10.0,11.0):
        phis=[min(1.0,obs[t]/max(1e-12,Ep(mu,sig,t,0.2))) for t in (12,13,14)]
        print(f'  mu={mu:4.1f}: phi_max(>=12,>=13,>=14) = '+', '.join(f'{p:.3f}' for p in phis))
# Yurnero: 17 with N=18
for mu in (8.6,10,11,12,13):
    for sig in (1.5,2.0,2.5):
        F=norm.cdf((17-1+0.5-mu)/sig); n=18*0.8
        print(f'Yurnero N=18 (14.4 eff) P(max>=17|mu={mu},sigma={sig})={1-F**n:.2e}',end=' | ')
    print()
