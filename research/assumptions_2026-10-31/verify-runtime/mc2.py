import numpy as np, sys
sys.path.insert(0,'.')
exec(open('mc.py').read().split("M=200000")[0])
from math import erf
import math
Phi=lambda x: 0.5*(1+np.vectorize(math.erf)(np.asarray(x)/math.sqrt(2)))
def run(label,kr,pr,Sr,or_,hr,Nc,Np,sd,M=40000,pubcons=True):
    rng=np.random.default_rng(11)
    ks=np.exp(rng.uniform(np.log(kr[0]),np.log(kr[1]),M)); ps=rng.uniform(*pr,M); Ss=rng.uniform(*Sr,M)
    ov=rng.uniform(*or_,M); hg=rng.uniform(*hr,M); Ns=rng.choice(Nc,M,p=Np)
    pub=np.array([total('pub024',ks[i],480,ps[i],ov[i],hg[i],Ns[i],Ss[i]) for i in range(M)])
    r={C:np.array([total('v12b6',ks[i],C,ps[i],ov[i],hg[i],Ns[i],Ss[i]) for i in range(M)]) for C in (300,330,360)}
    lik=Phi((12-r[360])/sd)*((1-Phi((12-pub)/sd))**2 if pubcons else 1)
    lik/=lik.sum()
    pb=lambda x:(lik*(1-Phi((12-x)/sd))).sum()
    print(f'{label:55s} k_post {np.sum(lik*ks):.2f} ovh {np.sum(lik*ov):.0f} | P(breach) 5.0: {pb(r[300]):.3f} 5.5: {pb(r[330]):.3f} 6.0: {pb(r[360]):.3f} | mean tot 6.0: {np.sum(lik*r[360]):.2f}')
# finding-like priors
run('finding-like: k .9-1.8 p.10-.20 S400-1000 ovh8-15 N120 hang0 sd.3',(0.9,1.8),(0.10,0.20),(400,1000),(8,15),(0,0.001),[120],[1],0.3)
run('same, sd 0.15',(0.9,1.8),(0.10,0.20),(400,1000),(8,15),(0,0.001),[120],[1],0.15)
run('same, sd 0.5',(0.9,1.8),(0.10,0.20),(400,1000),(8,15),(0,0.001),[120],[1],0.5)
run('ovh 8-35',(0.9,1.8),(0.10,0.20),(400,1000),(8,35),(0,0.001),[120],[1],0.3)
run('N 116-130',(0.9,1.8),(0.10,0.20),(400,1000),(8,15),(0,0.001),[116,120,125,130],[.2,.5,.2,.1],0.3)
run('hang 0-12',(0.9,1.8),(0.10,0.20),(400,1000),(8,15),(0,12),[120],[1],0.3)
run('all wide',(0.8,2.5),(0.10,0.20),(400,1200),(8,35),(0,12),[116,120,125,130],[.2,.5,.2,.1],0.3)
run('all wide, no pub024',(0.8,2.5),(0.10,0.20),(400,1200),(8,35),(0,12),[116,120,125,130],[.2,.5,.2,.1],0.3,False)
