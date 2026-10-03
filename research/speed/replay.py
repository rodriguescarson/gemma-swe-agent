"""Stretched replay of SOLVED v10 trajectories onto the hidden clock (speed.md sect. 5). Stdlib only.

Each solved trajectory is replayed step by step with every step's L4 duration multiplied by k (uniform stretch,
calibrated in sim.py; lognormal per-task k as a sensitivity). The locator can be cut short by the LOCATOR footer
(helper clock >= T_LOC): after each locator helper step that ends past T_LOC, the next step is the plan reply with
probability p_obey (measured 7/14 and 8/19 = 0.46 per occurrence), else the recorded trajectory continues.
When the locator is cut, the remaining locator tool steps are skipped and the recorded plan reply is kept.
A solve LANDS if its final patch (last source edit, or the restored checkpoint) exists by the cap.
Cuts remove recorded steps (repro retries, run.py probes) or shorten replies before the final patch.
ASSUMPTION (optimistic): a cut or truncation does not change what the later stages do. Quality effects are
what the golden-eval check in speed.md measures.
"""
import math
import random
import statistics as st
import sys

from analyze import BY, T, dur, task_metrics, tasks_of

RUNS = ("p1_v10", "r2_v10_1")
P_OBEY = 0.46


def solved(run):
    out = []
    k0 = T[next(x for x in T if x[0] == run)]["scale"]
    for tid in tasks_of(run):
        m = task_metrics(run, tid)
        if m["resolved"] and m["t_final_patch"] is not None:
            out.append((tid, m["t_final_patch"], [dict(s, d=dur(s, k0)) for s in BY[(run, tid)]], k0))
    return out


def replay(steps, fp, k, cap, t_loc=75.0, p_obey=P_OBEY, hard=False, drop=None, reply_cut=0.0, fixed_save=0.0,
           rnd=None, clock_mult=1.0):
    """-> hidden time at which the final patch exists (or inf if the patch step was skipped).
    clock_mult: helper thresholds scale (a 6-min cap with the helper clock rescaled uses 1.2)."""
    t = -fixed_save
    in_loc_cut = False
    t_loc_h = t_loc * clock_mult
    fp_t = None
    orig_t = 0.0
    for i, s in enumerate(steps):
        orig_t += s["d"]
        a = s["author"]
        if a == "locator" and in_loc_cut and s["fn"] is not None:
            continue                                  # truncated locator: tool steps skipped
        if drop and drop(s, i, steps):
            continue
        d = s["d"] * k
        if s["fn"] is None and a == "locator" and reply_cut:
            d = max(0.0, (s["d"] - reply_cut) * k)
        t += d
        if a == "locator" and s["fn"] is not None and not in_loc_cut and t >= t_loc_h:
            if hard or (rnd.random() < p_obey):
                in_loc_cut = True
        if orig_t >= fp - 1e-6 and fp_t is None:
            fp_t = t
    return fp_t if fp_t is not None else t


def land_rate(run, k, cap=300.0, sig=0.0, reps=400, **kw):
    S = solved(run)
    rnd = random.Random(7)
    hit = 0
    n = 0
    for _ in range(reps if (sig or kw.get("p_obey", P_OBEY) not in (0.0, 1.0)) else 1):
        for tid, fp, steps, _ in S:
            kk = k if not sig else math.exp(rnd.gauss(math.log(k) - sig * sig / 2, sig))
            x = replay(steps, fp, kk, cap, rnd=rnd, **kw)
            hit += x <= cap
            n += 1
    return hit / n, len(S)


# --- cuts -------------------------------------------------------------------------------------------------------
def drop_probes(s, i, steps):
    """locator run.py probes (python3 /tmp/swe/run.py ...) made before the plan reply"""
    return s["author"] == "locator" and s.get("helper") == "run"


def drop_repro_retries(s, i, steps):
    """every locator verify --repro-only after the first one"""
    if s["author"] != "locator" or s.get("vk") != "repro":
        return False
    return any(x["author"] == "locator" and x.get("vk") == "repro" for x in steps[:i])


def drop_both(s, i, steps):
    return drop_probes(s, i, steps) or drop_repro_retries(s, i, steps)


def drop_waste(s, i, steps):
    """same-stage exact repeats with the same output, same-stage re-reads, helper NOTE repeats, SAME AS LAST RUN"""
    return bool(s.get("reread_stage")) or s.get("cat") in ("repeat_note", "verify_same")


VARIANTS = [
    ("naive stretch (no footer cut)", dict(p_obey=0.0)),
    ("v10.1 as shipped: soft LOCATOR at 75 (p=0.46)", dict()),
    ("hard LOCATOR stop at 75", dict(hard=True)),
    ("hard LOCATOR stop at 60", dict(hard=True, t_loc=60.0)),
    ("hard LOCATOR stop at 45", dict(hard=True, t_loc=45.0)),
    ("no locator run.py probes", dict(drop=drop_probes)),
    ("one repro attempt only", dict(drop=drop_repro_retries)),
    ("no probes + one repro", dict(drop=drop_both)),
    ("plan reply -100 tokens (2.9 s L4)", dict(reply_cut=2.9)),
    ("drop repeats/re-reads/NOTE/SAME", dict(drop=drop_waste)),
    ("setup stage merged (-2.7 s fixed)", dict(fixed_save=2.7)),
    ("cap 5.5 min, helper clock x1.1", dict(cap_=330.0, clock_mult=1.1)),
    ("cap 6.0 min, helper clock x1.2", dict(cap_=360.0, clock_mult=1.2)),
    ("cap 6.0 + hard stop 60 (x1.2 = 72)", dict(cap_=360.0, clock_mult=1.2, hard=True, t_loc=60.0)),
    ("cap 6.0 + hard 60 + no probes + one repro", dict(cap_=360.0, clock_mult=1.2, hard=True, t_loc=60.0,
                                                     drop=drop_both)),
    ("cap 5.0 + hard 60 + no probes + one repro", dict(hard=True, t_loc=60.0, drop=drop_both)),
    ("cap 5.5 + hard 60 + no probes + one repro", dict(cap_=330.0, clock_mult=1.1, hard=True, t_loc=60.0,
                                                     drop=drop_both)),
    ("cap 5.5 + hard 60 + probes/repro + reply-100", dict(cap_=330.0, clock_mult=1.1, hard=True, t_loc=60.0,
                                                        drop=drop_both, reply_cut=2.9)),
]


def main():
    ks = [float(x) for x in (sys.argv[1:] or ["1.5", "1.9", "2.5", "3.0"])]
    reps = 120
    for sig in (0.0, 0.5):
        res = {}
        for name, kw in VARIANTS:
            kw = dict(kw)
            cap = kw.pop("cap_", 300.0)
            for k in ks:
                hits, n = 0.0, 0
                for run in RUNS:
                    r, m = land_rate(run, k, cap=cap, sig=sig, reps=reps, **kw)
                    hits += r * m
                    n += m
                res[(name, k)] = hits / n
        print(f"\n### per-task k {'uniform' if not sig else 'lognormal sd %.1f (mean k)' % sig}; landed share of "
              f"solves (p1_v10 27 + r2_v10_1 25 pooled); [delta vs shipped in hidden public-LB tasks at H=7.2/60]")
        print("variant".ljust(46) + "".join(f"   k={k:<11}" for k in ks))
        for name, _ in VARIANTS:
            line = name.ljust(46)
            for k in ks:
                v, b = res[(name, k)], res[("v10.1 as shipped: soft LOCATOR at 75 (p=0.46)", k)]
                line += f"  {v:5.3f} [{7.2 * (v / b - 1):+5.2f}]"
            print(line)


if __name__ == "__main__":
    main()
