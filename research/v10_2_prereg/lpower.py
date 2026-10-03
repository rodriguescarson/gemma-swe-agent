"""Null false-pass and power of the pre-registered L gate (paired per-case mean diff >= +0.10), n cases, 2 samples.
Model: a share u of cases is unstable (hit with p = 0.5 in both arms), the rest deterministic. u from the only two-run
L evidence: L_dev_v101 vs pod p1_v10 on 22 common non-capped rich dev tasks, 3 discordant (0.136 = 2 u p (1-p))."""
import random
rng = random.Random(20260930)
def run(n, samples, u, gain_cases, reps=40000, thr=0.10, p_unst=0.5):
    ok = 0
    for _ in range(reps):
        d = 0.0
        for i in range(n):
            unstable = rng.random() < u
            pa = p_unst if unstable else (1.0 if rng.random() < 0.6 else 0.0)
            pb = pa
            if i < gain_cases:           # cases the change moves from miss to hit (deterministic misses become hits)
                pa, pb = 0.0, 1.0
            a = sum(rng.random() < pa for _ in range(samples)) / samples
            b = sum(rng.random() < pb for _ in range(samples)) / samples
            d += b - a
        ok += d / n >= thr - 1e-9
    return ok / reps
for u in (0.27, 0.40):
    for n in (30, 32):
        print("u=%.2f n=%d: null P(pass)=%.3f | power +2 cases %.2f, +3 %.2f, +4 %.2f, +5 %.2f" % (
            u, n, run(n, 2, u, 0), run(n, 2, u, 2), run(n, 2, u, 3), run(n, 2, u, 4), run(n, 2, u, 5)))
