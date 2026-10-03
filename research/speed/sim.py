"""Hidden-set calibration, 12 h budget and time-starvation simulation (speed.md sect. 4-6). Stdlib only.

Hidden run facts (UTC):
  sub3 = v4 bundle: submitted 2026-09-27 00:01:12, COMPLETE between 10:20:50 and 10:31:05  -> T3 = 10.33-10.50 h
  sub4 = v9_eog:     submitted 2026-09-28 00:01:06, PENDING at 10:00:24, COMPLETE at 10:05:25 -> T4 = 9.99-10.07 h
  (gap_5 sect. 1; scratchpad/gap5c/sub4_poll.log)
  T = Q + S + A_tasks + V; V = 10 min + nonempty x (Vfull - 10 min), Vfull 1.5/2.0/2.5 h (host "IIRC ~2 h").
"""
import collections
import math
import random
import statistics as st
import sys

from analyze import BY, T, dur, q, task_metrics, tasks_of

S_START = 600.0          # scorer start-up before task 1 (planning value; 503-509 s ours, 562 s competitor; time_model 1.1)
OVH = 5.0                # per-task in-clock overhead outside the agent: setup 3.6 + teardown ~1 (time_model 1.2)
OVERSHOOT = 5.0          # run_command floor past the cap (execution.py)
H12 = 43200.0


def agent_times(run):
    M = [task_metrics(run, t) for t in tasks_of(run)]
    return [(m["end"], m["capped"]) for m in M]


def in_clock(times, k, cap, n, s=S_START, ovh=OVH):
    per = []
    for a, capped in times:
        x = cap + OVERSHOOT if capped else min(k * a, cap + OVERSHOOT)
        per.append(ovh + x)
    return s + n * st.mean(per), sum(1 for a, c in times if c or k * a >= cap) / len(times)


def solve_k(times, A_h, n, cap=300.0):
    lo, hi = 0.5, 30.0
    if in_clock(times, hi, cap, n)[0] < A_h * 3600:
        return float("inf")
    if in_clock(times, lo, cap, n)[0] > A_h * 3600:
        return float("nan")
    for _ in range(60):
        mid = (lo + hi) / 2
        if in_clock(times, mid, cap, n)[0] < A_h * 3600:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def mixture_p(times, A_h, n, cap=300.0):
    """share p of hidden tasks that behave like public ones; the rest run to the cap."""
    pub = in_clock(times, 1.0, cap, n)[0]
    full = S_START + n * (OVH + cap + OVERSHOOT)
    return (full - A_h * 3600) / (full - pub)


def V_of(nonempty, vfull_h):
    return 10 / 60 + nonempty * (vfull_h - 10 / 60)


def main():
    tv4, tv9 = agent_times("k_v4"), agent_times("k_v9_eog")
    ne4, ne9 = 61 / 74, 63 / 74   # non-empty patch rates on the 74 (gap_5 sect. 2, 10.3)
    print("== Calibration of a uniform hidden stretch k (in-clock A = T - V, Q = 0)")
    print("sub   Vfull  V(h)  A(h)   N   k(uniform)  capped@5.0  mixture p(public-like)")
    rows = []
    for name, times, T_h, ne in (("sub3", tv4, 10.42, ne4), ("sub4", tv9, 10.03, ne9)):
        for vf in (1.5, 2.0, 2.5):
            V = V_of(ne, vf)
            A = T_h - V
            for n in (120, 130):
                k = solve_k(times, A, n)
                cap_share = in_clock(times, k, 300, n)[1] if math.isfinite(k) else float("nan")
                p = mixture_p(times, A, n)
                rows.append((name, vf, n, k))
                print(f"{name}  {vf:4.1f}  {V:4.2f}  {A:5.2f}  {n}  {k:6.2f}      {cap_share:5.1%}      {p:5.2f}")
    print("\n== Same calibration on a grid of absolute validation times V (h), T3 = 10.42 / T4 = 10.03 (N, ovh 5 s)")
    print("sub   V(h)  A(h)  k@N=120  capped@5.0  k@N=130  capped@5.0")
    for name, times, T_h in (("sub3", tv4, 10.42), ("sub4", tv9, 10.03)):
        for V in (0.25, 0.4, 0.6, 0.8, 1.0, 1.3, 1.7, 2.0):
            A = T_h - V
            k1, k2 = solve_k(times, A, 120), solve_k(times, A, 130)
            c1 = in_clock(times, k1, 300, 120)[1] if math.isfinite(k1) else float("nan")
            c2 = in_clock(times, k2, 300, 130)[1] if math.isfinite(k2) else float("nan")
            print(f"{name}  {V:4.2f}  {A:5.2f}  {k1:6.2f}   {c1:5.0%}      {k2:6.2f}   {c2:5.0%}")
    # sub3 bracket extremes
    for T_h in (10.33, 10.50):
        k = solve_k(tv4, T_h - V_of(ne4, 2.0), 120)
        print(f"sub3 T={T_h} Vfull 2.0 N=120: k={k:.2f}")
    k4 = solve_k(tv9, 10.07 - V_of(ne9, 2.0), 120)
    print(f"sub4 T=10.07 Vfull 2.0 N=120: k={k4:.2f}")
    print("\n== What 'all-in per task' ratio each k implies (per-task in-clock / public per-task, v4):")
    pub = st.mean([OVH + (300 + OVERSHOOT if c else a) for a, c in tv4])
    for k in (1.9, 2.5, 3.0, 3.5, 4.0, 4.5):
        hid = st.mean([OVH + (300 + OVERSHOOT if c else min(k * a, 305)) for a, c in tv4])
        print(f"  k={k}: hidden per-task {hid:.0f} s vs public {pub:.0f} s -> ratio {hid/pub:.2f}; capped {in_clock(tv4,k,300,120)[1]:.0%}")


if __name__ == "__main__":
    main()
