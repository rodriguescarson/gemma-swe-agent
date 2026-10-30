import sys; sys.path.insert(0,'<scratch>/assume/runtime/scripts')
from extract import *
import collections, numpy as np
for run in ('v12','garble'):
    A=load_all(run)
    print('=====',run)
    for name,S in (('74',A),('71 base-failing',[a for a in A if not a['base']])):
        c=collections.Counter((a['end'],a['resolved']) for a in S)
        n=len(S)
        cap=[a for a in S if a['end']=='cap']; sub=[a for a in S if a['end']=='submit']; oth=[a for a in S if a['end']=='other']
        print(f' [{name}] cap {len(cap)} ({len(cap)/n:.1%}) solved {sum(a["resolved"] for a in cap)} | submit {len(sub)} solved {sum(a["resolved"] for a in sub)} | other {len(oth)} solved {sum(a["resolved"] for a in oth)}')
        print('   mean secs: cap %.1f submit %.1f other %.1f ; overall %.1f'%(np.mean([a['secs'] for a in cap]),np.mean([a['secs'] for a in sub]),np.mean([a['secs'] for a in oth]) if oth else 0,np.mean([a['secs'] for a in S])))
        print('   solved: n %d, mean secs %.1f, median %.1f; solves that are cap-ended: %d'%(sum(a['resolved'] for a in S),np.mean([a['secs'] for a in S if a['resolved']]),np.median([a['secs'] for a in S if a['resolved']]),sum(a['resolved'] and a['end']=='cap' for a in S)))
    print('  other-end rows:',[(a['id'],a['resolved'],round(a['last_el']),a['secs'],a['err']) for a in A if a['end']=='other'])
