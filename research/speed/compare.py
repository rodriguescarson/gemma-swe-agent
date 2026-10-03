import statistics as st
from replay import land_rate, VARIANTS
from land import tfp, f_uniform, f_logn
ks=(1.5,1.9,2.5,3.0,4.0)
print('Expected landed solves (public-equivalent counts): v4 naive stretch (no clock) vs v10.1 replay with its footers')
for sig in (0.0,0.5,1.0):
    print(f'-- per-task k: {"uniform" if not sig else "lognormal sd %.1f"%sig}')
    for run in ('p1_v4','k_v4','r2_v9_eog_1','k_v9_eog'):
        ts=tfp(run)
        vals=[(f_uniform(ts,k,300) if not sig else f_logn(ts,k,300,sig=sig,n=1500))*len(ts) for k in ks]
        print(f'   {run:12} ({len(ts)} solves) '+'  '.join(f'k={k}: {v:5.1f}' for k,v in zip(ks,vals)))
    for run in ('p1_v10','r2_v10_1'):
        vals=[]
        for k in ks:
            r,m=land_rate(run,k,cap=300.0,sig=sig,reps=150)
            vals.append(r*m)
        print(f'   {run:12} ({m} solves) '+'  '.join(f'k={k}: {v:5.1f}' for k,v in zip(ks,vals)))
print('\nTime-starved curve, v10.1 as shipped (pooled 52 solves): share landing with X extra seconds (cap 300+X, footers unchanged)')
for sig in (0.0,0.5):
    for k in ks:
        row=[]
        for X in (0,15,30,60,90,120):
            h=n=0
            for run in ('p1_v10','r2_v10_1'):
                r,m=land_rate(run,k,cap=300.0+X,sig=sig,reps=150); h+=r*m; n+=m
            row.append(h/n)
        print(f'  {"uniform" if not sig else "logn0.5"} k={k}: '+'  '.join(f'+{X}s {v:.3f}' for X,v in zip((0,15,30,60,90,120),row)))
