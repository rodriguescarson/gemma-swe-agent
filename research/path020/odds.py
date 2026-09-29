# ESTIMATE model for PATH_TO_020.md. Inputs are the research reports' central values; see the doc.
import numpy as np
rng = np.random.default_rng(20261202)
M = 400_000
SIG_RUN = 0.033*58   # gap_6 run-noise SD on the fixed 58-task public LB = 1.91 tasks
base = 7.2           # v4 hidden (0.12 twice; speed.md H=7.2)
def lever(mean, sd, n):  # normal on hidden tasks
    return rng.normal(mean, sd, n)
# levers (hidden tasks), central / sd chosen to cover each report's stated range
v101   = lever(0.5, 0.6, M)   # speed.md: sub6 1.03-1.18x v4 landed solves; pod +3/74 x0.3 x58/74 = +0.7
speed  = lever(0.35,0.25,M)   # speed.md package +0.23..+0.84 (k=1.9..4); ~0 under mixture
robust = lever(0.4, 0.4, M)   # hidden.md T1 0..+1, T2 0..+0.5, T3 0..+0.5
temp   = np.maximum(lever(0.3, 0.8, M), 0) * 0.8   # adopted only if measured better; measurement imperfect
fixq   = lever(0.6, 0.6, M)   # completeness sweep 2.45 public flips x0.3 x58/74 = +0.6; 2nd fixer +0.17
nodist = base + v101 + speed + robust + temp + fixq
works  = rng.random(M) < 0.6*0.75*0.65   # LoRA alive (PLAN 0.6) x teacher allowed (0.75, INFERENCE) x lands by 8 Nov (0.65)
dgain  = np.exp(rng.normal(np.log(1.6), 0.45, M)) * 0.7  # distill.md +1.6 (0.7..3.5), 0.7 overlap with prompt levers
withd  = nodist + np.where(works, dgain, 0)
def rep(name, mu):
    p_true = (mu >= 11.6).mean()
    out = [name, f"mean {mu.mean():.1f}", f"p10-p90 {np.percentile(mu,10):.1f}-{np.percentile(mu,90):.1f}", f"P(true>=11.6) {p_true:.3f}"]
    for n in (1, 3, 10, 20):
        # displayed best of n independent reads of the final bundle
        reads = mu[:,None] + rng.normal(0, SIG_RUN, (len(mu), n))
        best = np.floor(reads.max(1) + 0.5)
        mean3 = None
        out.append(f"P(best of {n}>=12) {(best>=12).mean():.3f}")
    reads3 = mu[:,None] + rng.normal(0, SIG_RUN, (len(mu),3))
    out.append(f"P(mean of 3 reads>=11.5) {(reads3.mean(1)>=11.5).mean():.3f}")
    print(" | ".join(out))
rep("v10.1 only", base + v101)
rep("plan, no distill", nodist)
rep("plan, distill works", withd[works])
rep("plan, distill pursued", withd)
print("P(distill works)", works.mean())
