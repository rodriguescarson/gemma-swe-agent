import numpy as np, sys, math
sys.path.insert(0,'.')
exec(open('mc.py').read().split("M=200000")[0])
Phi=lambda x: 0.5*(1+np.vectorize(math.erf)(np.asarray(x)/math.sqrt(2)))
def run(label,kdraw,M=40000,sd=0.3,ov=(8,15),S=(400,1000),hang=(0,6),N=(120,),pubcons=True):
    rng=np.random.default_rng(5)
    ks=kdraw(rng,M); ps=rng.uniform(0.10,0.20,M); Ss=rng.uniform(*S,M); ovs=rng.uniform(*ov,M); hg=rng.uniform(*hang,M); Ns=rng.choice(N,M)
    pub=np.array([total('pub024',ks[i],480,ps[i],ovs[i],hg[i],Ns[i],Ss[i]) for i in range(M)])
    r={C:np.array([total('v12b6',ks[i],C,ps[i],ovs[i],hg[i],Ns[i],Ss[i]) for i in range(M)]) for C in (300,330,360)}
    lik=Phi((12-r[360])/sd)*((1-Phi((12-pub)/sd))**2 if pubcons else 1.0); lik/=lik.sum()
    pb=lambda x:(lik*(1-Phi((12-x)/sd))).sum()
    print(f'{label:46s} k_post {np.sum(lik*ks):.2f} | breach 5.0: {pb(r[300]):.3f} 5.5: {pb(r[330]):.3f} 6.0: {pb(r[360]):.3f} | E[total 5.5/6.0]: {np.sum(lik*r[330]):.2f}/{np.sum(lik*r[360]):.2f}')
ln=lambda med,s:(lambda rng,M: np.exp(rng.normal(np.log(med),s,M)))
run('k lognormal med1.15 sd.20, noise .3',ln(1.15,0.20))
run('k lognormal med1.15 sd.30, noise .3',ln(1.15,0.30))
run('k lognormal med1.30 sd.25, noise .3',ln(1.30,0.25))
run('k loguniform 0.9-1.5, noise .3',lambda rng,M: np.exp(rng.uniform(np.log(.9),np.log(1.5),M)))
run('k loguniform 0.9-1.8, noise .3',lambda rng,M: np.exp(rng.uniform(np.log(.9),np.log(1.8),M)))
run('k lognormal med1.15 sd.30, noise .3, no pub024',ln(1.15,0.30),pubcons=False)
