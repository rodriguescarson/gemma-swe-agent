import json, os, numpy as np
B='<repo>/eval/a6000/results'
V=[l.strip() for l in open('<repo>/data/kaggle_valid_ids.txt') if l.strip()]
def load(run,cap):
    rows={}
    for l in open(f'{B}/{run}/results.jsonl'):
        if l.strip():
            r=json.loads(l); rows[r['id']]=r
    out=[]
    for i in V:
        r=rows[i]
        p=f'{B}/{run}/results/traces/trace_{i}.json'
        t=json.load(open(p)) if os.path.exists(p) else None
        last=0; sub=None
        if t:
            for s in t['steps']:
                ex=s.get('extra') or {}
                for key in ('elapsed_s',):
                    if ex.get(key) is not None: last=max(last,ex[key])
                ob=s.get('observation')
                if ob:
                    e=(ob.get('extra') or {}).get('elapsed_s')
                    if e is not None: last=max(last,e)
                for tc in (s.get('tool_calls') or []):
                    if tc['function_name']=='submit_patch' and sub is None: sub=ex.get('elapsed_s')
        capped=('session timeout' in (r.get('err') or '')) or (r['secs']>=cap-1 and sub is None)
        out.append(dict(id=i,secs=r['secs'],capped=capped,te=None if capped else (sub if sub is not None else last),sub=sub,last=last,res=r['resolved']))
    return out
def mean_clock(T,k,C,ovh,over=6):
    xs=[]
    for a in T:
        if a['capped']: xs.append(C+over)
        else:
            t=k*a['te']; xs.append(C+over if t>C else t+3)
    return np.mean(xs)+ovh
def total(T,k,C,N=120,S=1000,ovh=10,over=6): return (S+N*mean_clock(T,k,C,ovh,over))/3600
if __name__=='__main__':
    for run,cap in (('p4_v12b',300),('p4_v12b6',360),('p4_pub024',480)):
        T=load(run,cap)
        print(run,'capped',sum(a['capped'] for a in T),'mean_clock(k=1,ovh0)=%.1f'%mean_clock(T,1.0,cap,0))
        print('   totals k=1.0/1.2/1.5/1.7:',[round(total(T,k,cap),2) for k in (1.0,1.2,1.5,1.7)])
    T=load('p4_v12b6',360)
    for C in (270,300,330,360):
        print('v12b6 timeline cap',C/60,'k=1.0/1.7:',round(total(T,1.0,C),2),round(total(T,1.7,C),2))
    # worst-case all capped
    for C in (300,330,360):
        for ovh in (0,10):
            print('all capped C',C,'ovh',ovh,'N120 S1000 over6: %.2f h'%((1000+120*(C+6+ovh))/3600))
