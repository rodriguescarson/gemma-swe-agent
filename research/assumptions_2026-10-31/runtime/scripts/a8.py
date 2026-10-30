import sys; sys.path.insert(0,'<scratch>/assume/runtime/scripts')
from extract import *
import collections, numpy as np, re
def classify_call(e):
    cats=[]
    for (n,a) in e['tools']:
        if n in ('edit_file','write_file'): cats.append('edit')
        elif n=='read_file': cats.append('read')
        elif n=='submit_patch': cats.append('submit')
        elif n=='run_command':
            c=str(a.get('command',''))
            if re.search(r'pytest|python.*test|unittest',c): cats.append('test')
            elif re.search(r'(^|\s)(grep|rg|find|ls|cat|head|tail|sed -n|git (grep|diff|log|show|status))',c) and not CMD_WRITE.search(c): cats.append('search')
            elif CMD_WRITE.search(c): cats.append('cmd_write')
            elif re.search(r'python',c): cats.append('run_py')
            else: cats.append('other_cmd')
        else: cats.append(n)
    return cats or ['no_tool']
rep={}
for run in ('v12','garble'):
    A=load_all(run)
    C=[a for a in A if a['end']=='cap' and not a['resolved']]
    print('=====',run,'capped unsolved',len(C))
    # first edit
    nofirst=[a for a in C if a['first_src_edit'] is None]
    print(' no source edit (to a file in final patch) at all:',len(nofirst),'| patch_len==0:',sum(a['patch_len']==0 for a in C))
    fe=[a['first_src_edit'] for a in C if a['first_src_edit'] is not None]
    print(' first src edit time quantiles 25/50/75:',np.percentile(fe,[25,50,75]).round(0) if fe else None,' (solved runs first edit median %.0f)'%np.median([a['first_src_edit'] for a in A if a['resolved'] and not a['base'] and a['first_src_edit'] is not None]))
    # last 60s: calls started after 240 s (agent clock)
    cat_calls=collections.Counter(); cat_time=collections.Counter(); gen_inflight=0; ncalls=0; tail_tok=[]; call_dur=[]
    patch_state=collections.Counter()
    for a in C:
        # activity in last 60 s of clock: [last_end-60, last_end] where last_end = max(300,...)
        for e in a['tl']:
            if e['kind']=='nudge': continue
            if e['call_t']>=240:
                cats=classify_call(e)
                for c in cats: cat_calls[c]+=1
                ncalls+=1; call_dur.append(e['call_t']-e['start_t']); tail_tok.append(e['ctoks'])
        # was a model call in flight at 300 s (trace ended before secs)?
        if a['secs']-a['last_el']>12: gen_inflight+=1
        # did it have a patch? src edit before 300?
        patch_state['has_src_edit' if a['last_src_edit'] is not None else 'no_src_edit']+=1
    print(' calls completed after 240 s clock:',ncalls,dict(cat_calls),'mean dur %.1f s, mean completion toks %.0f, max toks %d'%(np.mean(call_dur),np.mean(tail_tok),max(tail_tok)))
    print(' runs with a long in-flight model call at cap (secs-last_el>12 s):',gen_inflight,'of',len(C))
    print(' patch state at cap:',dict(patch_state))
    # per-run summary
    summ=[]
    for a in C:
        last=a['tl'][-1]; 
        summ.append((a['id'],a['calls'],round(a['first_src_edit']) if a['first_src_edit'] else None,round(a['last_src_edit']) if a['last_src_edit'] else None,round(a['last_el']),a['secs'],classify_call(last)))
    rep[run]=summ
    for s in summ: print('   ',s)
