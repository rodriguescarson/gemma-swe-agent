import sys; sys.path.insert(0,'<scratch>/assume/runtime/scripts')
from extract import *
import numpy as np
for run in ('v12','garble'):
    A=load_all(run)
    res=[];drops=[];maxp=[]
    nruns_over=0
    for a in A:
        prev=None; over=False
        pt=[e['ptoks'] for e in a['tl'] if e['kind']!='nudge']
        maxp.append(max(pt) if pt else 0)
        for e in a['tl']:
            if e['kind']=='nudge': continue
            d=e['call_t']-e['start_t']; r=d-(2.26+0.0281*e['ctoks'])
            res.append((r,e['ptoks'],e['ctoks']))
            if prev is not None and e['ptoks']<prev-3000:
                drops.append((a['id'],prev,e['ptoks'],round(r,1)))
            if e['ptoks']>14336: over=True
            prev=e['ptoks']
        nruns_over+=over
    r=np.array([x[0] for x in res])
    print(run,'steps',len(r),'resid mean %.2f s, p90 %.1f, p99 %.1f, >15 s: %d'%(r.mean(),np.percentile(r,90),np.percentile(r,99),(r>15).sum()))
    print('   max prompt tokens per run: median %d p90 %d max %d; runs whose prompt exceeded 14,336: %d/74'%(np.median(maxp),np.percentile(maxp,90),max(maxp),nruns_over))
    print('   prompt-token drops (>3000, i.e. compaction): %d events in %d runs; mean residual on that step %.1f s'%(len(drops),len({d[0] for d in drops}),np.mean([d[3] for d in drops]) if drops else 0))
