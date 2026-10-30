import sys; sys.path.insert(0,'<scratch>/assume/runtime/scripts')
from extract import *
import collections, numpy as np, json
allres={}
for run in ('v12','garble'):
    A=load_all(run)
    S=[a for a in A if a['resolved'] and not a['base']]
    print('=====',run,'solved base-failing',len(S))
    rows_=[]
    for a in sorted(S,key=lambda a:a['last_src_edit'] or 0):
        rows_.append((a['id'],round(a['first_src_edit'] or -1),round(a['last_src_edit'] or -1),round(a['submit_t']) if a['submit_t'] else None,round(a['last_el']),a['secs'],a['end']))
    for r in rows_: print('  ',r)
    le=np.array([a['last_src_edit'] for a in S]); sb=np.array([a['submit_t'] if a['submit_t'] else a['last_el'] for a in S])
    for T in (120,150,180,210,240,270,285,300):
        print(f'   last src edit > {T}s: {int((le>T).sum())}  |  end(submit or cap) > {T}s: {int((sb>T).sum())}')
    allres[run]=[(a['id'],a['first_src_edit'],a['last_src_edit'],a['submit_t'],a['last_el']) for a in S]
    print('  last edit quantiles 25/50/75/90/100:',np.percentile(le,[25,50,75,90,100]).round(0),' submit/end quantiles',np.percentile(sb,[25,50,75,90,100]).round(0))
    gap=[ (a['submit_t']-a['last_src_edit']) for a in S if a['submit_t']]
    print('  gap submit - last src edit: median %.1f mean %.1f max %.1f n %d'%(np.median(gap),np.mean(gap),np.max(gap),len(gap)))
json.dump(allres,open('solved_times.json','w'))
