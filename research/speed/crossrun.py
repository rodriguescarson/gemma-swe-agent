import collections, statistics as st
from analyze import BY,T,task_metrics,tasks_of,q,waste,dur
runs=['p1_v10','p1_v4','r2_v10_1','r2_v9_eog_1','k_v4','k_v9_eog','r_v4','r_v9_eog','r_v9_c','r_v9_eg','r_v9_eo','r_v9_og','p_v4','p_v6','p_v7','p_v8']
print('run          n  solved capped  s/task  calls  out_tok  llm%  | first edit p50 (solved) | final patch p50/p90/max (solved) | after-fp p50 | waste s/task (fail+repeat+reread+text)')
for run in runs:
    M=[task_metrics(run,t) for t in tasks_of(run)]; n=len(M)
    k=T[(run,M[0]['tid'])]['scale']
    sol=[m for m in M if m['resolved']]
    calls=sum(m['n'] for m in M)/n
    ct=sum(s['ct'] for m in M for s in BY[(run,m['tid'])])/n
    llm=sum(s['llm_s'] for m in M for s in BY[(run,m['tid'])]); tool=sum(s['tool_s'] for m in M for s in BY[(run,m['tid'])])
    fe=[m['t_first_edit'] for m in sol if m['t_first_edit'] is not None]
    fp=[m['t_final_patch'] for m in sol if m['t_final_patch'] is not None]
    af=[m['end']-m['t_final_patch'] for m in sol if m['t_final_patch'] is not None]
    W=collections.Counter()
    for m in M:
        for c,v in waste(run,m['tid']).items(): W[c]+=v[1]
    wf=sum(v for c,v in W.items() if c.startswith('failed') or 'ALREADY' in c)/n
    wr=sum(v for c,v in W.items() if 'repeat' in c or 'SAME' in c or 'NOTE' in c)/n
    wrr=W['re-read (same stage)']/n; wt=(W['stage-ending text reply']+W['tool call written as text'])/n
    print(f"{run:12} {n:2} {len(sol):5} {sum(m['capped'] for m in M):6} {st.mean(m['end'] for m in M):7.1f} {calls:6.1f} {ct:7.0f} {llm/(llm+tool):5.1%} | {q(fe,.5):6.1f} | {q(fp,.5):5.1f} / {q(fp,.9):5.1f} / {max(fp):5.1f} | {q(af,.5):5.1f} | {wf:5.1f} {wr:5.1f} {wrr:5.1f} {wt:5.1f}")
