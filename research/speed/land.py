import math, random, statistics as st
from analyze import task_metrics, tasks_of, q, T
RUNS=['p1_v10','r2_v10_1','p1_v4','k_v4','k_v9_eog','r2_v9_eog_1']
def tfp(run):
    out=[]
    for t in tasks_of(run):
        m=task_metrics(run,t)
        if m['resolved']:
            out.append((t, m['t_final_patch'] if m['t_final_patch'] is not None else m['end'], m['end']))
    return out
def f_uniform(ts,k,cap): return sum(1 for _,x,_ in ts if k*x<=cap)/len(ts)
def f_logn(ts,k,cap,sig=0.5,n=4000,seed=1):
    # per-task k_i lognormal with the same MEAN k (mean-preserving)
    rnd=random.Random(seed); mu=math.log(k)-sig*sig/2
    tot=0
    for _ in range(n):
        for _,x,_ in ts:
            tot+= (math.exp(rnd.gauss(mu,sig))*x<=cap)
    return tot/(n*len(ts))
if __name__=='__main__':
    for run in RUNS:
        ts=tfp(run)
        cap_solved=[t for t in tasks_of(run) if task_metrics(run,t)['resolved'] and task_metrics(run,t)['capped']]
        print(f"{run:12} solves {len(ts):2}  t_fp p50 {q([x for _,x,_ in ts],.5):5.1f} p75 {q([x for _,x,_ in ts],.75):5.1f} p90 {q([x for _,x,_ in ts],.9):5.1f} max {max(x for _,x,_ in ts):5.1f}  capped&solved {cap_solved}")
        line='   uniform k: '
        for k in (1.5,1.9,2.5,3.0):
            line+=f" k={k}: {f_uniform(ts,k,300):.2f}/{f_uniform(ts,k,330):.2f}/{f_uniform(ts,k,360):.2f} ({f_uniform(ts,k,300)*len(ts):4.1f})"
        print(line+'   [cap 300/330/360]')
        line='   lognormal sd0.5: '
        for k in (1.5,1.9,2.5,3.0):
            line+=f" k={k}: {f_logn(ts,k,300):.2f}/{f_logn(ts,k,360):.2f} ({f_logn(ts,k,300)*len(ts):4.1f})"
        print(line)
