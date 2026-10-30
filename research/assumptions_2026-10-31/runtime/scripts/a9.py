import sys; sys.path.insert(0,'<scratch>/assume/runtime/scripts')
from extract import *
import collections, numpy as np
for run in ('v12','garble'):
    A=load_all(run)
    groups={'solved':[a for a in A if a['resolved'] and not a['base']],
            'unsolved-submit':[a for a in A if (not a['resolved']) and a['end']=='submit'],
            'unsolved-cap':[a for a in A if (not a['resolved']) and a['end']=='cap']}
    print('=====',run)
    for g,S in groups.items():
        tl=[e for a in S for e in a['tl'] if e['kind']!='nudge']
        dur=np.array([max(e['call_t']-e['start_t'],0) for e in tl]); tok=np.array([e['ctoks'] for e in tl])
        big=tok>=1000
        ncalls=[len([e for e in a['tl'] if e['kind']!='nudge']) for a in S]
        wall=sum(a['last_el'] for a in S)
        print(f' {g:16s} n={len(S):2d} model steps/run {np.mean(ncalls):5.1f}; tokens/step mean {tok.mean():5.0f} median {np.median(tok):4.0f}; time/step {dur.mean():5.1f}s; steps>=1000 tok: {big.sum()} ({big.mean():.1%} of steps) = {dur[big].sum()/dur.sum():.1%} of LLM time; completion tok/run {tok.sum()/len(S):.0f}; wall/run {wall/len(S):.0f}s')
        # steps with >=2000 tokens
        b2=tok>=2000
        print(f'      steps>=2000 tok: {b2.sum()} = {dur[b2].sum()/dur.sum():.1%} of LLM time; runs with >=1 such step: {sum(any(e["ctoks"]>=2000 for e in a["tl"]) for a in S)}/{len(S)}')
