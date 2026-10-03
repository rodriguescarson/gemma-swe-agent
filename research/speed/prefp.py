"""Where the time before the final patch goes, in SOLVED v10 tasks (L4 s)."""
import collections, statistics as st, sys
from analyze import BY, T, task_metrics, tasks_of, q, dur, waste
runs=sys.argv[1:] or ['p1_v10','r2_v10_1']
for run in runs:
    k=T[next(x for x in T if x[0]==run)]['scale']
    agg=collections.defaultdict(float); n=0
    wagg=collections.defaultdict(lambda:[0,0.0])
    helpers=collections.defaultdict(lambda:[0,0.0,0])
    for tid in tasks_of(run):
        m=task_metrics(run,tid)
        if not m['resolved'] or m['t_final_patch'] is None: continue
        n+=1; fp=m['t_final_patch']
        L=[s for s in BY[(run,tid)] if s['t_end']*k<=fp+1e-6]
        for s in L:
            agg[s['author']]+=dur(s,k)
            h=s.get('helper') or ('text' if s['fn'] is None else s['fn'])
            helpers[(s['author'],h)][0]+=1; helpers[(s['author'],h)][1]+=dur(s,k); helpers[(s['author'],h)][2]+=s['ct']
        # waste restricted to pre-fp: recompute quickly by filtering waste on a copy
        saved=BY[(run,tid)]
        BY[(run,tid)]=L
        for c,v in waste(run,tid).items():
            wagg[c][0]+=v[0]; wagg[c][1]+=v[1]
        BY[(run,tid)]=saved
    print(f'\n== {run}: {n} solved; mean pre-final-patch time by stage (L4 s/task):', {a:round(v/n,1) for a,v in agg.items()}, 'total', round(sum(agg.values())/n,1))
    print('  waste before the final patch (steps/task, s/task):')
    for c,v in sorted(wagg.items(), key=lambda kv:-kv[1][1]): print(f'    {c:30} {v[0]/n:5.2f} {v[1]/n:6.1f}')
    print('  by stage x helper (calls/task, s/task, ct/task):')
    for (a,h),v in sorted(helpers.items(), key=lambda kv:-kv[1][1])[:16]: print(f'    {a:9} {h:10} {v[0]/n:5.2f} {v[1]/n:6.1f} {v[2]/n:6.0f}')
