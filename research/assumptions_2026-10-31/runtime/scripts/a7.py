import sys; sys.path.insert(0,'<scratch>/assume/runtime/scripts')
from extract import *
import numpy as np
# solve-time per run: for solved runs t_solve = last_src_edit (the state graded exists from then); for unsolved: inf. 'alive' at t = run has not ended by t (end time = submit_t or last_el/secs-based)
# End time of a run (agent clock): submit_t if submit else cap time (>=300)
rowsall=[]
for run in ('v12','garble'):
    for a in load_all(run):
        if a['base']: continue
        end=a['submit_t'] if a['submit_t'] else max(a['last_el'],300.0)
        ts=a['last_src_edit'] if a['resolved'] else None
        rowsall.append((run,a['id'],a['resolved'],ts,end,a['end']))
N=len(rowsall); print('runs',N,'solved',sum(r[2] for r in rowsall))
print('bin     alive_at_start  solved_in_bin(last edit)  ended_in_bin  hazard_solve  ended_unsolved_in_bin')
for lo in range(0,300,30):
    hi=lo+30
    alive=[r for r in rowsall if r[4]>lo]       # agent session still running at lo
    sol=[r for r in alive if r[2] and lo<r[3]<=hi]
    ended=[r for r in alive if r[4]<=hi]
    unsolved_end=[r for r in ended if not r[2]]
    print(f'{lo:3d}-{hi:3d}  {len(alive):4d}  {len(sol):3d}  {len(ended):3d}  {len(sol)/max(1,len(alive)):.3f}   {len(unsolved_end)}')
# Among runs alive at 240: outcome
for t in (180,210,240,270):
    alive=[r for r in rowsall if r[4]>t]
    sol_after=[r for r in alive if r[2] and r[3]>t]
    already=[r for r in alive if r[2] and r[3]<=t]
    print(f'alive at {t}: {len(alive)}; of them final solved with last edit <= {t}: {len(already)} (patch already final), last edit after {t}: {len(sol_after)}; never solved: {len(alive)-len(already)-len(sol_after)}')
