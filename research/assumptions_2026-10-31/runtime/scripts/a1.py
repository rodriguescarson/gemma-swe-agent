import sys; sys.path.insert(0,'<scratch>/assume/runtime/scripts')
from extract import *
import collections, numpy as np
BASEPASS={'fastapi_14077','fastapi_14851','requests_6644'}
def q(x,ps=(10,25,50,75,90)): return [round(float(np.percentile(x,p)),1) for p in ps]
res={}
for run in ('v12','garble'):
    rr=rows(run)
    A=[analyse(run,i,rr) for i in VALID]
    res[run]=A
    B=[a for a in A if a['id'] not in BASEPASS]  # 71 base-failing
    print('=====',run,'all74 solved',sum(a['resolved'] for a in A),'| 71 base-failing solved',sum(a['resolved'] for a in B))
    for name,S in (('all74',A),('71',B)):
        secs=[a['secs'] for a in S]; cap=[a for a in S if a['capped']]
        sol=[a for a in S if a['resolved']]; uns=[a for a in S if not a['resolved']]
        print(f' [{name}] n={len(S)} mean secs {np.mean(secs):.1f} med {np.median(secs):.1f} | capped {len(cap)} ({len(cap)/len(S):.1%}) | secs>=299: {sum(s>=299 for s in secs)} | solved {len(sol)} mean secs {np.mean([a["secs"] for a in sol]):.1f} | unsolved {len(uns)} mean secs {np.mean([a["secs"] for a in uns]):.1f}; unsolved&capped {sum(a["capped"] for a in uns)} ({sum(a["capped"] for a in uns)/len(uns):.1%} of unsolved), solved&capped {sum(a["capped"] for a in sol)}')
        print('   secs quantiles 10/25/50/75/90', q(secs))
    # ended by: submit vs cap vs other
    kinds=collections.Counter()
    for a in A:
        k='capped' if a['capped'] else ('submit' if a['submit_t'] else 'other_end')
        kinds[(k,a['resolved'])]+=1
    print(' end kinds (kind, solved):',dict(kinds))
