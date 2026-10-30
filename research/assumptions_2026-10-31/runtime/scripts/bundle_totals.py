import sys; sys.path.insert(0,'<scratch>/assume/runtime/scripts')
exec(open('scripts/pub024.py').read().split("for run,cap in (('p4_pub024',480)")[0])
import numpy as np
print('Projected 12-h clock (hours) = (S + N*(mean agent clock*k + ovh))/3600 with N=120, S=1000, ovh=10, per box bundle at its own cap')
for run,cap,outcome in (('p4_pub024',480,'hidden: RUNTIME x2 (sub18, sub19)'),('p4_pub024_6m',360,'never submitted (failed box gate)'),('p4_v12b6',360,'hidden: scored 0.15 (sub23)'),('p4_v12b',300,'hidden: scored 0.17 (sub20)'),('p4_v12',300,'hidden: scored 0.15/0.13 (sub14, sub21)'),('p4_v12a',480,'never submitted (box mean 314 s > gate)')):
    T=agent_times(run,cap)
    xs=[ (120*1000+0) ]
    row=[(1000+120*mean_clock(T,k,cap,10))/3600 for k in (1.0,1.1,1.2,1.3,1.5,1.7)]
    print(f'{run:13s} cap {cap/60:.0f} min | '+' '.join(f'k={k}: {x:5.2f}' for k,x in zip((1.0,1.1,1.2,1.3,1.5,1.7),row))+f' | {outcome}')
