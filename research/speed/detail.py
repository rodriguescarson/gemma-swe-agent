import json,collections,statistics as st,sys
from analyze import BY,T,task_metrics,tasks_of,q,dur
runs=sys.argv[1:] or ['p1_v10','r2_v10_1']
for run in runs:
    k=T[next(x for x in T if x[0]==run)]['scale']
    print('\n=====',run)
    M={t:task_metrics(run,t) for t in tasks_of(run)}
    # locator detail
    rows=[]
    for tid,m in M.items():
        L=[s for s in BY[(run,tid)] if s['author']=='locator']
        if not L: continue
        n=len(L); tt=sum(dur(s,k) for s in L)
        rep=[s for s in L if s.get('helper')=='verify' and s.get('vk')=='repro']
        runs_=[s for s in L if s.get('helper')=='run']
        raw=[s for s in L if s.get('helper') in ('raw','read_file')]
        views=[s for s in L if s.get('helper')=='view']
        # hint
        hi=[i for i,s in enumerate(L) if 'LOCATOR:' in (s.get('hints') or []) or 'EDIT NOW:' in (s.get('hints') or []) or 'CONTEXT:' in (s.get('hints') or [])]
        after=(n-1-hi[0]) if hi else None
        t_after=sum(dur(s,k) for s in L[hi[0]+1:]) if hi else 0
        end=L[-1]['t_end']*k
        repro_ok=any(s.get('cat')=='repro_ok' for s in L)
        rows.append(dict(tid=tid,res=m['resolved'],n=n,t=tt,end=end,rep=len(rep),run=len(runs_),raw=len(raw),views=len(views),after=after,t_after=t_after,repro_ok=repro_ok,
            reptime=sum(dur(s,k) for s in rep), runtime=sum(dur(s,k) for s in runs_)))
    for lab,R in (('all',rows),('solved',[r for r in rows if r['res']]),('unsolved',[r for r in rows if not r['res']])):
        print(f"locator {lab:8} n={len(R)} steps p50 {q([r['n'] for r in R],.5):.0f} p90 {q([r['n'] for r in R],.9):.0f} mean {st.mean([r['n'] for r in R]):.1f} | secs mean {st.mean([r['t'] for r in R]):.1f} p50 {q([r['t'] for r in R],.5):.1f} p90 {q([r['t'] for r in R],.9):.1f} | end p50 {q([r['end'] for r in R],.5):.0f} | repro calls {st.mean([r['rep'] for r in R]):.2f} ({st.mean([r['reptime'] for r in R]):.1f}s) run.py {st.mean([r['run'] for r in R]):.2f} ({st.mean([r['runtime'] for r in R]):.1f}s) raw {st.mean([r['raw'] for r in R]):.2f} views {st.mean([r['views'] for r in R]):.2f} repro_ok {sum(r['repro_ok'] for r in R)}")
    hinted=[r for r in rows if r['after'] is not None]
    print(f"locator got LOCATOR/EDIT NOW/CONTEXT hint in {len(hinted)} tasks; steps after first hint: {sorted(r['after'] for r in hinted)}; secs after: mean {st.mean([r['t_after'] for r in hinted]) if hinted else 0:.1f}")
    # savings if locator capped at N steps (time of steps beyond N) 
    for N in (8,10,12,15):
        sv=[sum(dur(s,k) for s in [x for x in BY[(run,r['tid'])] if x['author']=='locator'][N:]) for r in rows]
        hit=sum(1 for r in rows if r['n']>N)
        hits=sum(1 for r in rows if r['n']>N and r['res'])
        print(f"  cap locator at {N} steps: saves mean {st.mean(sv):.1f} s/task; tasks over {hit} (solved among them {hits})")
    for TT in (45,60,75,90):
        sv=[]; hit=0; hits=0
        for r in rows:
            L=[x for x in BY[(run,r['tid'])] if x['author']=='locator']
            t0=(L[0]['t_end']-L[0]['llm_s']-L[0]['tool_s'])*k
            over=sum(dur(s,k) for s in L if s['t_end']*k - t0 > TT)
            sv.append(over); 
            if over>0: hit+=1; hits+=r['res']
        print(f"  cap locator at {TT}s of locator time: saves mean {st.mean(sv):.1f} s/task; tasks over {hit} (solved {hits})")
    # fixer / repair
    rows=[]
    for tid,m in M.items():
        L=BY[(run,tid)]
        F=[s for s in L if s['author']=='fixer']; V=[s for s in L if s['author']=='verifier']
        fv=[s for s in F if s.get('helper')=='verify' and s.get('vk') not in ('repro',None)]
        vv=[s for s in V if s.get('helper')=='verify' and s.get('vk') not in ('repro',None)]
        fe=[s for s in F if s.get('src_edit')]; ve=[s for s in V if s.get('src_edit')]
        first_ver=next((s for s in L if s.get('helper')=='verify' and s.get('vk') not in ('repro',None)),None)
        edits_after_first_verify=[s for s in L if s.get('src_edit') and first_ver and s['sid']>first_ver['sid']]
        first_vk=first_ver.get('vk') if first_ver else None
        rows.append(dict(tid=tid,res=m['resolved'],fv=len(fv),vv=len(vv),fe=len(fe),ve=len(ve),first_vk=first_vk,eafv=len(edits_after_first_verify),
            fsecs=sum(dur(s,k) for s in F), vsecs=sum(dur(s,k) for s in V), f_to_edit=((fe[0]['t_end']-(F[0]['t_end']-F[0]['llm_s']-F[0]['tool_s']))*k if fe and F else None),
            t_after_first_ver=(m['end']-first_ver['t_end']*k) if first_ver else None))
    for lab,R in (('solved',[r for r in rows if r['res']]),('unsolved',[r for r in rows if not r['res']])):
        print(f"{lab:8} n={len(R)} fixer verify {st.mean([r['fv'] for r in R]):.2f} verifier verify {st.mean([r['vv'] for r in R]):.2f} fixer edits {st.mean([r['fe'] for r in R]):.2f} verifier edits {st.mean([r['ve'] for r in R]):.2f} "
              f"| first verdict {collections.Counter(r['first_vk'] for r in R)} | tasks with edits after first verify {sum(1 for r in R if r['eafv'])} | verifier edited {sum(1 for r in R if r['ve'])} "
              f"| fixer secs {st.mean([r['fsecs'] for r in R]):.1f} verifier secs {st.mean([r['vsecs'] for r in R]):.1f} | fixer start->first edit p50 {q([r['f_to_edit'] for r in R if r['f_to_edit'] is not None],.5):.1f}")
