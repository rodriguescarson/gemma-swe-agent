import sys; sys.path.insert(0,'<scratch>/assume/runtime/scripts')
from extract import *
import collections, numpy as np
for run in ('v12','garble'):
    rr=rows(run); A=[analyse(run,i,rr) for i in VALID]
    X=[];Y=[];P=[]; tot_llm=0; tot_tool=0; tot=0; tool_by=collections.Counter(); n_calls=0; ctok=0
    gaps=[]
    for a in A:
        prev_end=None
        for e in a['tl']:
            if e['kind']=='nudge': continue
            llm=e['call_t']-e['start_t']
            if e['ctoks']>0 and llm>=0:
                X.append(e['ctoks']); Y.append(llm); P.append(e['ptoks'])
            tot_llm+=max(llm,0); n_calls+=1; ctok+=e['ctoks']
            if e['obs_t'] is not None:
                d=e['obs_t']-e['call_t']; tot_tool+=d
                for (n,_) in e['tools']: tool_by[n]+=d
        tot+=a['last_el']
    X=np.array(X);Y=np.array(Y);P=np.array(P)
    # OLS Y = a + b*X + c*P
    M=np.c_[np.ones(len(X)),X,P/1000.0]
    coef,res,rk,sv=np.linalg.lstsq(M,Y,rcond=None)
    # robust: median ms/token for calls with >=300 tokens
    big=X>=300
    print('====',run,'calls',n_calls,'mean completion tokens/call %.1f'%(ctok/n_calls),'total ctoks',ctok)
    print(' OLS: intercept %.2f s + %.1f ms/token + %.2f s per 1k prompt tokens'%(coef[0],coef[1]*1000,coef[2]))
    print(' calls>=300 tok: median s/token ms = %.1f ; calls>=1000: %.1f'%(np.median(Y[big]/X[big])*1000, np.median(Y[X>=1000]/X[X>=1000])*1000))
    print(' share of agent wall: LLM %.1f%%, tools %.1f%%, other %.1f%% (total %.0f s over 74 tasks)'%(100*tot_llm/tot,100*tot_tool/tot,100*(tot-tot_llm-tot_tool)/tot,tot))
    print(' tool time by tool (s, share of total):',{k:(round(v),round(100*v/tot,1)) for k,v in tool_by.items()})
    print(' completion token quantiles per call 50/90/99:',np.percentile(X,[50,90,99]))
