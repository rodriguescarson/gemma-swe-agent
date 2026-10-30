import numpy as np, math, csv
from scipy.stats import norm
from scipy.optimize import nnls
rows=list(csv.DictReader(open('lbnow/gemma-4-developer-agent-publicleaderboard-2026-10-30T12:52:00.csv',encoding='utf-8-sig')))
def kof(s):
    s=round(float(s),2)
    for k in range(59):
        if math.floor(100*k/58)/100==s: return k
N=np.array([int(r['SubmissionCount']) for r in rows]); K=np.array([kof(r['Score']) for r in rows])
T=np.arange(1,18)
obs=np.array([(K>=t).sum() for t in T],float)
G=np.arange(2,13.01,0.5)
def Emat(sig,f):
    Ne=np.maximum(1,N*(1-f))
    return np.array([[ (1-(norm.cdf((t-0.5-mu)/sig))**Ne).mean() for mu in G] for t in T])   # expected share of teams with K>=t if all at mu
for sig in (1.0,1.2,1.3,1.4,1.5,1.6,1.7,1.8,2.0):
  for f in (0.0,0.2,0.4):
    E=Emat(sig,f)*len(N)           # expected counts if all teams at mu_g
    wts=1/np.sqrt(np.maximum(obs,1))
    A=np.vstack([E*wts[:,None], 1000*np.ones((1,len(G)))/len(N)*len(N)/len(N)*0+1000*np.ones((1,len(G)))])
    # simpler: variables w_g are team-shares; counts = E @ w ; weights; constraint sum w =1 via heavy row
    A=np.vstack([E*wts[:,None]/1.0, 1e4*np.ones((1,len(G)))])
    b=np.concatenate([obs*wts,[1e4]])
    w,rn=nnls(A,b)
    fit=E@w
    chi=((fit-obs)**2/np.maximum(fit,1)).sum()
    print(f'sigma={sig} fail={f}: chi2={chi:.1f}  share of teams with config mean >=9: {w[G>=9].sum():.3f}  >=10: {w[G>=10].sum():.3f}  >=11: {w[G>=11].sum():.3f}  >=12: {w[G>=12].sum():.3f}; mass-weighted mean mu {np.dot(w,G)/w.sum():.2f}')
    if sig==1.5 and f==0.2:
        print('   mixture support (mu:share) :',', '.join(f'{g:.1f}:{x:.3f}' for g,x in zip(G,w) if x>0.003))
        print('   t   observed fitted')
        for t,o,fv in zip(T,obs,fit): print(f'   {t:2d}  {o:6.0f} {fv:8.1f}')
