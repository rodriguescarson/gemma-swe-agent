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
    names,S=gibbs(sigma,nit=60000)
    m=S[:,0]; mu=S[:,2:]; i=names.index('v12b')
    print(f'sigma={sigma}: P(line mean >= 9.0)={np.mean(m>=9.0):.3f}  P(line mean >= 9.6)={np.mean(m>=9.6):.4f}  P(mu_v12b >= 9.6)={np.mean(mu[:,i]>=9.6):.3f}  P(mu_v12b >= 9.0)={np.mean(mu[:,i]>=9.0):.3f}  P(mu_v12b>=10)={np.mean(mu[:,i]>=10):.3f}')
# compare line vs public best lineage (later draws mean 9.57 over 21 draws, SD 1.5) : difference distribution (normal approx)
for name,mline,seline in (('core6 (n=6)',8.67,1.5/math.sqrt(6)),('docs 8 reads (n=8)',7.88,1.5/math.sqrt(8)),('core6+v13 (n=7)',8.57,1.5/math.sqrt(7))):
    for lname,ml,nl in (('lineage later-draw pool 9.57 n=21',9.57,21),('V5 10.0 n=10',10.0,10),('4 file sets >=3 draws pooled 9.57..',9.57,21)):
        se=math.sqrt(seline**2+1.5**2/nl); z=(ml-mline)/se
        from scipy.stats import norm
        print(f'{name:22s} vs {lname:36s}: diff {ml-mline:+.2f} tasks, SE {se:.2f}, z={z:.2f}, one-sided p={1-norm.cdf(z):.3f}, two-sided p={2*(1-norm.cdf(abs(z))):.3f}')
    break
for name,mline,n in (('core6',8.67,6),('docs 8',7.88,8),('core6+v13',8.57,7)):
    for lname,ml,nl in (('later-draw pool 9.57',9.57,21),('V5 10.0',10.0,10)):
        se=1.5*math.sqrt(1/n+1/nl); z=(ml-mline)/se
        print(f'{name:10s} vs {lname:20s}: diff {ml-mline:+.2f} SE {se:.2f} z={z:.2f} two-sided p={2*(1-norm.cdf(abs(z))):.3f}')
