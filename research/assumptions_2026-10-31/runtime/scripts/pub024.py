import sys; sys.path.insert(0,'<scratch>/assume/runtime/scripts')
from box import *
import numpy as np
def brentq(f,a,b,it=80):
    fa=f(a); fb=f(b)
    if fa*fb>0: raise ValueError('no root')
    for _ in range(it):
        m=(a+b)/2; fm=f(m)
        if fa*fm<=0: b,fb=m,fm
        else: a,fa=m,fm
    return (a+b)/2
def agent_times(run,cap):
    A=load_box(run)
    T=[]
    for a in A:
        capped=(a['err'] and 'session timeout' in a['err']) or a['secs']>=cap-1 and a['submit_t'] is None
        te=None if capped else (a['submit_t'] if a['submit_t'] else a['last_el'])
        T.append((te,capped,a['secs'],a['resolved']))
    return T
def mean_clock(T,k,C,ovh,overshoot=6):
    xs=[]
    for te,capped,secs,sol in T:
        if capped or te is None: xs.append(C+overshoot)
        else:
            t=k*te
            xs.append(C+overshoot if t>C else t+3)   # +3 s: final msg / submit round trip
    return np.mean(xs)+ovh
for run,cap in (('p4_pub024',480),('p4_v12b6',360),('p4_v12b',300),('p4_v12',300),('p4_pub024_6m',360)):
    T=agent_times(run,cap)
    print(run,'n',len(T),'secs mean %.1f'%np.mean([x[2] for x in T]),'agent-clock mean at k=1 (ovh 0): %.1f'%mean_clock(T,1.0,cap,0),'capped',sum(x[1] for x in T))
T=agent_times('p4_pub024',480)
print('--- pub024 critical k where S+N*(mean_clock)=43200 s')
for N in (116,120,130):
    for S in (400,1000,1677):
        for ovh in (5,15):
            f=lambda k: S+N*mean_clock(T,k,480,ovh)-43200
            try: kc=brentq(f,0.5,3.0)
            except Exception as e: kc=None
            print(f'  N={N} S={S} ovh={ovh}: k_crit={kc:.3f}' if kc else f'  N={N} S={S} ovh={ovh}: none')

print('--- critical k (total=12 h) per bundle from box timelines')
def kcrit(run,cap,N,S,ovh):
    T=agent_times(run,cap)
    f=lambda k: S+N*mean_clock(T,k,cap,ovh)-43200
    try: return brentq(f,0.5,6.0)
    except Exception: return None
for run,cap in (('p4_pub024',480),('p4_v12b6',360),('p4_v12b',300),('p4_v12',300),('p4_pub024_6m',360)):
    row=[]
    for N,S,ovh in ((116,400,5),(120,1000,10),(120,1677,15),(130,1000,10)):
        kc=kcrit(run,cap,N,S,ovh); row.append(f'N{N}/S{S}/o{ovh}: '+(f'{kc:.2f}' if kc else 'never (cannot exceed 12 h even if every task capped)'))
    print(run,cap,' | '.join(row))
