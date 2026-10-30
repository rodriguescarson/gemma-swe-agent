import sys,json; sys.path.insert(0,'<scratch>/assume/runtime/scripts')
from load import *
import numpy as np
for run in ('v12','garble'):
    X=[];Y=[]
    for i in VALID:
        t=trace(run,i)
        for s in t['steps']:
            if s['source']!='agent' or not s.get('metrics'): continue
            msg=len(str(s.get('message') or ''))
            args=sum(len(json.dumps(tc.get('arguments') or {})) for tc in (s.get('tool_calls') or []))
            X.append((msg,args)); Y.append(s['metrics']['completion_tokens'])
    X=np.array(X,float);Y=np.array(Y,float)
    M=np.c_[X,np.ones(len(X))]
    c,_,_,_=np.linalg.lstsq(M,Y,rcond=None)
    pred=M@c
    visible_tok_est=X[:,0]/3.6+X[:,1]/3.0
    print(run,'steps',len(Y),'ctoks = %.3f*msg_chars + %.3f*arg_chars + %.1f'%tuple(c),' R2 %.3f'%(1-((Y-pred)**2).sum()/((Y-Y.mean())**2).sum()))
    print('   total ctoks',int(Y.sum()),'est visible (msg/3.6+args/3.0) tokens',int(visible_tok_est.sum()),'=> unexplained (thinking not shown) share %.1f%%'%(100*(1-visible_tok_est.sum()/Y.sum())))
    print('   msg chars total',int(X[:,0].sum()),'args chars',int(X[:,1].sum()),' steps with empty message: %d'%int((X[:,0]==0).sum()))
