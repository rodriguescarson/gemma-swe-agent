import numpy as np, sys
sys.path.insert(0,'.')
from proj import load
rng=np.random.default_rng(7)
T={'v12b6':load('p4_v12b6',360),'pub024':load('p4_pub024',480),'v12b':load('p4_v12b',300)}
def arr(T):
    te=np.array([a['te'] if a['te'] is not None else np.nan for a in T],float)
    cap=np.array([a['capped'] for a in T],bool)
    res=np.array([a['res'] for a in T],bool)
    return te,cap,res
A={k:arr(v) for k,v in T.items()}
def mean_clock(name,k,C,p,ovh,hang,over=6):
    te,cap,res=A[name]
    ps=res.mean()
    w=np.where(res,p/ps,(1-p)/(1-ps)); w=w/w.sum()
    t=k*te
    x=np.where(cap|np.isnan(te)|(t>C), C+over+hang, t+3)
    return (w*x).sum()+ovh
def total(name,k,C,p,ovh,hang,N,S):
    return (S+N*mean_clock(name,k,C,p,ovh,hang))/3600
M=200000
ks=np.exp(rng.uniform(np.log(0.8),np.log(2.5),M))
ps=rng.uniform(0.10,0.20,M)
Ss=rng.uniform(400,1200,M)
ovhs=rng.uniform(8,35,M)
hangs=rng.uniform(0,12,M)
Ns=rng.choice([116,118,120,122,125,130],M,p=[.1,.1,.4,.1,.2,.1])
sd=0.3
ok=np.zeros(M,bool)
res6=np.zeros(M); res55=np.zeros(M); res5=np.zeros(M); pub=np.zeros(M)
for i in range(M):
    k,p,S,o,h,N=ks[i],ps[i],Ss[i],ovhs[i],hangs[i],Ns[i]
    pub[i]=total('pub024',k,480,p,o,h,N,S)
    res6[i]=total('v12b6',k,360,p,o,h,N,S)
    res55[i]=total('v12b6',k,330,p,o,h,N,S)
    res5[i]=total('v12b6',k,300,p,o,h,N,S)
# condition: pub024 failed twice (2 independent noisy draws), v12b6 passed once
lik=np.zeros(M)
from math import erf
def Phi(x): return 0.5*(1+np.vectorize(erf)(x/np.sqrt(2)))
pf=1-Phi((12-pub)/sd)          # P(fail) per draw
pp=Phi((12-res6)/sd)           # P(pass) v12b6
lik=pf**2*pp
lik/=lik.sum()
def post_breach(res):
    pb=1-Phi((12-res)/sd)      # fresh draw with noise
    return (lik*pb).sum()
print('posterior mean k %.2f  p %.3f  ovh %.1f S %.0f N %.1f'%tuple((lik*x).sum() for x in (ks,ps,ovhs,Ss,Ns)))
print('P(breach) fresh draw: 5.0 min %.3f | 5.5 min %.3f | 6.0 min %.3f'%(post_breach(res5),post_breach(res55),post_breach(res6)))
print('posterior mean total h: 5.0 %.2f 5.5 %.2f 6.0 %.2f'%tuple((lik*x).sum() for x in (res5,res55,res6)))
# ess
print('ESS %.0f'%(1/(lik**2).sum()))
# sensitivity: no pub024 constraint
lik2=pp/pp.sum()
pb=lambda res:(lik2*(1-Phi((12-res)/sd))).sum()
print('without pub024 constraint: 5.0 %.3f 5.5 %.3f 6.0 %.3f'%(pb(res5),pb(res55),pb(res6)))
