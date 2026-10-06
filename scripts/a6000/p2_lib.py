"""Pure logic of the P2 race (docs/v4h/GATE.md, 'P2 pre-registration'): queue order, probe slowdown, concurrency rule,
wall-time projection, Wilson interval, sign test and the verdict rule. No I/O, no model."""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "golden"))

SLOWDOWN_MAX = 1.15
THINK_ITEM_S = 360          # v6p-think is assumed to run to the 5-minute cap plus verification
WALL_LIMIT_H = 12.0
SCALE_MIN, SCALE_MAX = 0.2, 5.0     # the helpers' clock_scale range (scripts/run_eval.py)


def build_items(ids, arms):
    """(task, arm) in task order; the arm order of task i is the arm list rotated by i."""
    out = []
    for i, t in enumerate(ids):
        k = i % len(arms)
        out += [(t, a) for a in arms[k:] + arms[:k]]
    return out


def slowdown(rows):
    """rows: pace_proxy log rows. effective = sum max(latency, L4-model time) / sum L4-model time over 200-status calls (what the
    harness's cap sees, since a faster reply is held to the model time); raw = sum latency / sum L4-model time."""
    ok = [r for r in rows if r.get("status") == 200 and r.get("l4_target_s") is not None]
    tgt = sum(r["l4_target_s"] for r in ok)
    if not ok or tgt <= 0:
        return {"effective": float("nan"), "raw": float("nan"), "calls": len(ok)}
    return {"effective": sum(max(r["latency_s"], r["l4_target_s"]) for r in ok) / tgt,
            "raw": sum(r["latency_s"] for r in ok) / tgt, "calls": len(ok)}


def choose_concurrency(s):
    """s: {T: effective slowdown} for T in 1..4 -> (C, scale). Highest T within 1.15; if even T=2 is above it (addendum 1), the T in
    {2, 3, 4} with the most L4-equivalent work per wall second (T / S(T); a tie goes to the smaller T), harness clock scale 1/S(T)
    (cap and command timeout x S(T))."""
    if 2 in s and not s[2] <= SLOWDOWN_MAX:                     # NaN (no calls measured) counts as too slow
        cand = [t for t in (2, 3, 4) if t in s and s[t] == s[t] and s[t] > 0]
        if not cand:
            return 2, 1.0
        t = max(cand, key=lambda x: (round(x / s[x], 9), -x))
        return t, min(SCALE_MAX, max(SCALE_MIN, 1.0 / s[t]))
    ok = [t for t, v in s.items() if v <= SLOWDOWN_MAX]
    return (max(ok) if ok else min(s)), 1.0


def project_hours(m_seconds, c, scale, n_tasks):
    """n_tasks x (v4h2 m + v6p m + v6p-think THINK_ITEM_S) x S / C, in hours, S = 1/scale (addendum 1: every item stretched by S)."""
    return n_tasks * (2 * m_seconds + THINK_ITEM_S) / scale / c / 3600


def plan_stage(hours):
    """Tasks to run: all 200 when the projection fits 12 h, else stage 1 (the first 100)."""
    return 200 if hours <= WALL_LIMIT_H else 100


def wilson(k, n, z=1.959964):
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def sign_p(w, l):
    n = w + l
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(min(w, l) + 1)) / 2 ** n)


def verdict(wins, losses, cap_gap):
    """BETTER = net >= +5 and p < 0.10; WORSE = net <= -5 and p < 0.10; else NO EVIDENCE. cap_gap = the arm's cap-hit share minus
    v4h2's; >= 0.10 turns WORSE / NO EVIDENCE into UNRESOLVED (time pressure, not capability); BETTER stands."""
    net, p = wins - losses, sign_p(wins, losses)
    if net >= 5 and p < 0.10:
        return "BETTER"
    if cap_gap >= 0.10:
        return "UNRESOLVED"
    if net <= -5 and p < 0.10:
        return "WORSE"
    return "NO EVIDENCE"


# ------------------------------------------------------------------------------------------ addendum 2
ARMS = ("v4h2", "v6p", "v6p-think")


def arm_scale(s):
    """G4_L4_SCALE of one arm: 1 / its own S when S > 1.15 (the cap then means the same model work as on L4), else 1.0; clamped."""
    if not s == s or s <= SLOWDOWN_MAX:
        return 1.0
    return min(SCALE_MAX, max(SCALE_MIN, 1.0 / s))


def decide(per_level, n_tasks, think_m=THINK_ITEM_S):
    """per_level: {C: {arm: {"S": effective slowdown, "m": mean item wall s}}} for arms v4h2 and v6p (v6p-think is assumed to behave like v6p
    with m = think_m until it is measured; pass its own entry to override). -> {"C", "H": {C: hours}, "scales": {arm: scale at C}}.
    H(C) = n x sum_arm m_arm / scale_arm / C / 3600; the smaller H wins, a tie goes to the smaller C."""
    H, scales = {}, {}
    for c, arms in per_level.items():
        a = dict(arms)
        a.setdefault("v6p-think", {"S": a["v6p"]["S"], "m": think_m})
        sc = {k: arm_scale(v["S"]) for k, v in a.items()}
        H[c] = n_tasks * sum(v["m"] / sc[k] for k, v in a.items()) / c / 3600
        scales[c] = sc
    best = min(H, key=lambda c: (round(H[c], 9), c))
    return {"C": best, "H": H, "scales": scales[best]}


def plan_stage_ladder(h_by_n):
    """All 200 when H_200 <= 12 h, else the first 100 when H_100 <= 12 h, else the first 50 (stage 1a)."""
    for n in (200, 100):
        if h_by_n[n] <= WALL_LIMIT_H:
            return n
    return 50
