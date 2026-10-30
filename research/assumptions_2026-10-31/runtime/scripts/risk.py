import sys; sys.path.insert(0,'<scratch>/assume/runtime/scripts')
exec(open('scripts/pub024.py').read().split("for run,cap in (('p4_pub024',480)")[0])   # reuse helpers only
import numpy as np
T6=agent_times('p4_v12b6',360)   # box timeline at 6 min (capped rows are those >=359 s)
def total_h(T,k,C,N,S,ovh,over=6):
    return (S+N*mean_clock(T,k,C,ovh,overshoot=over))/3600
print('Box v12b6 timeline truncated/scaled. total hours = (S + N*(mean agent clock + ovh))/3600; overshoot 6 s; 12 h limit = 12.00')
print('N S ovh | k | 4.5min 5min 5.5min 6min')
for N,S,ovh in ((116,500,10),(120,1000,10),(120,1677,15),(125,1000,15),(130,1000,10)):
    for k in (1.0,1.3,1.7,2.0):
        row=[total_h(T6,k,C,N,S,ovh) for C in (270,300,330,360)]
        print(f'{N:3d} {S:4d} {ovh:2d} | {k:.1f} | '+'  '.join(f'{x:5.2f}' for x in row))
print()
# fraction of rows capped under k and C
for k in (1.0,1.3,1.7):
    print('k',k,'capped share at C=270/300/330/360:',[round(np.mean([ (te is None) or (k*te>C) for te,capd,secs,sol in T6]),2) for C in (270,300,330,360)])
