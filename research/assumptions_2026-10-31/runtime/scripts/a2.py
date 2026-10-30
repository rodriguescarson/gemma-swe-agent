import sys; sys.path.insert(0,'<scratch>/assume/runtime/scripts')
from extract import *
import collections, numpy as np
BASEPASS={'fastapi_14077','fastapi_14851','requests_6644'}
for run in ('v12','garble'):
    rr=rows(run); A=[analyse(run,i,rr) for i in VALID]
    print('=====',run)
    print(' rows with secs>=299:',sum(a['secs']>=299 for a in A))
    for a in sorted(A,key=lambda a:a['secs']):
        if a['secs']>=285 and not a['capped']:
            print('  secs>=285 not err-capped',a['id'],'secs',a['secs'],'last_el',round(a['last_el'],1),'solved',a['resolved'],'submit_t',a['submit_t'],'calls',a['calls'],'err',a['err'])
