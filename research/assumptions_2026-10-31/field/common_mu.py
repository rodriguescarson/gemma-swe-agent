import sys, numpy as np, math, csv
from scipy.stats import norm, binom
from scipy.optimize import brentq
rows=list(csv.DictReader(open('lbnow/gemma-4-developer-agent-publicleaderboard-2026-10-30T12:52:00.csv',encoding='utf-8-sig')))
def kof(s):
    s=round(float(s),2)
    for k in range(59):
        if math.floor(100*k/58)/100==s: return k
N=np.array([int(r['SubmissionCount']) for r in rows]); K=np.array([kof(r['Score']) for r in rows])
def Fnorm(mu,sigma,t):   # P(k<=t) discretised normal
    return norm.cdf((t+0.5-mu)/sigma)
def Fbin(mu,R,t):
    return binom.cdf(t,R,min(0.999,mu/R))
def expect(Ns,mu,t,F):
    # E #teams with max >= t = sum 1-F(t-1)^N
    return float((1-F(mu,t-1)**Ns).sum())
print('subset sizes: N>=1',len(N),' N>=10',(N>=10).sum(),' N>=13',(N>=13).sum(),' N>=18',(N>=18).sum())
for fail in (0.0,0.2):
  for subset_name,mask in (('all',N>=1),('N>=10',N>=10),('N>=18',N>=18)):
    Ns=np.maximum(1,N[mask]*(1-fail))
    print(f'--- subset {subset_name} ({mask.sum()} teams), failure share {fail}')
    for shape in ('normal s=1.2','normal s=1.56','normal s=2.0','binom R=14 (sd~1.6)','binom R=20 (sd~2.2)'):
        if shape.startswith('normal'):
            s=float(shape.split('=')[1]); F=lambda mu,t,s=s:Fnorm(mu,s,t)
        else:
            R=int(shape.split('R=')[1].split(' ')[0]); F=lambda mu,t,R=R:Fbin(mu,R,t)
        line=f'{shape:22s}'
        for t in (11,12,13,14,17):
            obs=int((K[mask]>=t).sum())
            f=lambda mu:expect(Ns,mu,t,F)-obs
            try:
                lo,hi=0.5,13.5 if not shape.startswith('binom R=14') else 13.9
                mu=brentq(f,lo,hi)
                line+=f' | t>={t}: obs {obs:4d} -> mu*={mu:5.2f}'
            except Exception as e:
                line+=f' | t>={t}: obs {obs:4d} -> none'
        print(line)
