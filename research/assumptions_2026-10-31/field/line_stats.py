import numpy as np, math
from scipy.stats import norm, chi2, t as tdist
rng=np.random.default_rng(7)
# hidden reads in tasks of 58 (score = floor(100k/58)/100): 0.17->10, 0.15->9, 0.13->8, 0.10->6
reads={'v12':[9,8],'v12b':[10],'v12b6':[9],'edit6':[8],'ctx':[8],'v13':[8],'b1024':[6],'v15b':[6]}
print('reads',reads)
def summ(name,xs,sigma=1.5):
    xs=np.array(xs,float); n=len(xs); m=xs.mean(); s=xs.std(ddof=1)
    ss=((xs-m)**2).sum()
    lo=chi2.cdf(ss/sigma**2,n-1)
    print(f'{name:34s} n={n} mean={m:.2f} ({m/58:.3f}) sd={s:.2f}  SE(sigma=1.5)={sigma/math.sqrt(n):.2f}  95%CI(mean)={m-tdist.ppf(.975,n-1)*s/math.sqrt(n):.2f}..{m+tdist.ppf(.975,n-1)*s/math.sqrt(n):.2f} | z-CI w/ sigma=1.5: {m-1.96*sigma/math.sqrt(n):.2f}..{m+1.96*sigma/math.sqrt(n):.2f}  P(var this low | sigma=1.5)={lo:.2f}')
allr=lambda ks:[x for k in ks for x in reads[k]]
summ('byte-identical v12 pair',reads['v12'])
summ('core6 (v12 x2,v12b,v12b6,edit6,ctx)',allr(['v12','v12b','v12b6','edit6','ctx']))
summ('docs 8 reads at 5 min',allr(['v12','v12b','edit6','ctx','v13','b1024','v15b']))
summ('core6 + v13',allr(['v12','v12b','v12b6','edit6','ctx','v13']))
summ('all 9 reads (incl b1024,v15b,v12b6)',allr(list(reads)))
# pooled SD from byte-identical re-submissions
ss=0; df=0
# third party (reproduced from dataset): pooled sd 1.559 on 23 df
ss+=1.559**2*23; df+=23
# our v12 pair
ss+=0.5; df+=1
# victorzhong same-bytes (0.15,0.13,0.17)->9,8,10: SS=2, df=2
ss+=2.0; df+=2
# Idris v17 twice (0.17,0.13)->10,8 : SS=2, df=1
ss+=2.0; df+=1
sig=math.sqrt(ss/df)
print(f'pooled within-config SD from byte-identical draws: {sig:.2f} on {df} df; 95% CI {sig*math.sqrt(df/chi2.ppf(.975,df)):.2f}..{sig*math.sqrt(df/chi2.ppf(.025,df)):.2f}')
# hierarchical normal: k_cj ~ N(mu_c, sigma^2); mu_c ~ N(m, tau^2); flat m; tau half-normal(1)
def gibbs(sigma,nit=40000,burn=4000,tau_scale=1.0):
    names=list(reads); n_c=[len(reads[c]) for c in names]; sums=[sum(reads[c]) for c in names]
    C=len(names); mu=np.array([s/n for s,n in zip(sums,n_c)],float); m=mu.mean(); tau=1.0
    out=[]; 
    taus=np.linspace(0.01,4,400)
    for it in range(nit):
        # mu_c | rest
        prec=np.array(n_c)/sigma**2+1/tau**2
        mean=(np.array(sums)/sigma**2+m/tau**2)/prec
        mu=mean+rng.standard_normal(C)/np.sqrt(prec)
        # m | rest (flat)
        m=mu.mean()+rng.standard_normal()*tau/math.sqrt(C)
        # tau | rest: grid draw, prior half-normal(scale)
        ll=-C*np.log(taus)-((mu-m)**2).sum()/(2*taus**2)-taus**2/(2*tau_scale**2)
        p=np.exp(ll-ll.max()); p/=p.sum(); tau=rng.choice(taus,p=p)
        if it>=burn and it%4==0: out.append((m,tau,*mu))
    return names,np.array(out)
for sigma in (1.2,1.5,2.0):
    names,S=gibbs(sigma)
    m=S[:,0]; tau=S[:,1]; mu=S[:,2:]
    i=names.index('v12b'); j=names.index('v12')
    others=np.delete(mu,i,axis=1).mean(1)
    print(f'\nsigma={sigma}: line mean m = {m.mean():.2f} (95% {np.percentile(m,2.5):.2f}..{np.percentile(m,97.5):.2f}); tau median {np.median(tau):.2f} (95% up to {np.percentile(tau,95):.2f})')
    print(f'   mu_v12b posterior mean {mu[:,i].mean():.2f} (95% {np.percentile(mu[:,i],2.5):.2f}..{np.percentile(mu[:,i],97.5):.2f}); P(mu_v12b > m)={np.mean(mu[:,i]>m):.2f}; P(mu_v12b > mean of the other 7 configs)={np.mean(mu[:,i]>others):.2f}; P(mu_v12b > mu_v12)={np.mean(mu[:,i]>mu[:,j]):.2f}; P(mu_v12b is the highest of 8)={np.mean(mu.argmax(1)==i):.2f}')
    # predictive for next v12b read
    pred=mu[:,i]+sigma*rng.standard_normal(len(m))
    kk=np.rint(pred)
    print(f'   next v12b read (sub28): P(k>=10 i.e. >=0.17)={np.mean(kk>=10):.2f}; P(k>=12 i.e. >=0.20)={np.mean(kk>=12):.2f}; P(k<=8 i.e. <=0.13)={np.mean(kk<=8):.2f}; P(k<=6)={np.mean(kk<=6):.2f}; median {np.median(kk):.0f}')
