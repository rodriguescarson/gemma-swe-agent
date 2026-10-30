import sys; sys.path.insert(0,'<scratch>/assume/runtime/scripts')
from extract import *
import collections, numpy as np
BASEPASS={'fastapi_14077','fastapi_14851','requests_6644'}
def hit_cap(a):
    # session ended by the clock: err string, or no submit and the last event past 295 s
    return a['capped'] or (a['submit_t'] is None and a['last_el']>=295 or a['secs']>=299)
out={}
for run in ('v12','garble'):
    rr=rows(run); A=[analyse(run,i,rr) for i in VALID]
    for a in A: a['hit']=hit_cap(a)
    out[run]=A
    for name,S in (('74',A),('71',[a for a in A if a['id'] not in BASEPASS])):
        n=len(S); h=[a for a in S if a['hit']]
        sol=[a for a in S if a['resolved']]; 
        print(f'== {run} [{name}] n={n}: hit cap {len(h)} ({len(h)/n:.1%}); of which solved {sum(a["resolved"] for a in h)}, unsolved {sum(not a["resolved"] for a in h)}; solved total {len(sol)} ({sum(a["hit"] for a in sol)} at cap = {sum(a["hit"] for a in sol)/max(1,len(sol)):.0%} of solves)')
        print(f'    secs mean {np.mean([a["secs"] for a in S]):.1f}; mean secs hit {np.mean([a["secs"] for a in h]):.1f}; not-hit {np.mean([a["secs"] for a in S if not a["hit"]]):.1f}; ended-before-cap share {1-len(h)/n:.1%}')
    print('   solved&hit ids:',[(a['id'],round(a['last_src_edit'] or -1),round(a['last_el'])) for a in A if a['hit'] and a['resolved']])
# solved-at-cap: solve rate among capped
