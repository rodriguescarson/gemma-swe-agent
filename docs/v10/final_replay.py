"""SPEC.md section 9 (reproduce with: .venv/bin/python docs/v10/final_replay.py). Synthesizer: counterfactual L4 replay of the FINAL v10 design (design A + grafts) on race-1 trajectories.
Reuses docs/v10/design_B_replay.py (loader, collapse rules, cost model) exactly like scratchpad/judge2/replay_abc.py."""
import importlib.util, statistics as st
import os
SP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "design_B_replay.py")
spec = importlib.util.spec_from_file_location("brep", SP); B = importlib.util.module_from_spec(spec); spec.loader.exec_module(B)
F, O, D, P, CAP = B.FUDGE, B.OVH, B.DEC, B.PRE, B.CAP
def call(n, out, unc, tool=0.0): return F * (n * O + out * D + unc * P) + tool
REPRO = 1.3 * call(1, 300, 500, 2.0)          # repro heredoc + one verify --repro-only run (judge2 value)
CLAIMS = call(0, 60, 0, 0.5)                  # '# CLAIM n:' header lines + per-claim processes (smaller than C's full spec)
def final(task, stretch=1.0, loc_cut=95.0, pessim=False):
    s = B.stages(task, drop_vgate=not pessim)
    t = call(2, 40, 6000, 0.4)                                   # setup
    loc = stretch * (s["locator"] + REPRO + CLAIMS)
    t += min(loc, (150.0 if pessim else loc_cut) - t)            # 75 s LOCATOR banner -> reply by ~95 s; EDIT NOW at 150
    fix = stretch * (s["fixer"] + call(1, 40, 700, 2.0))         # + one verify.py (cached original)
    t += min(fix, max(0.0, 210.0 - t))                           # FINISH footer at 210
    ver = call(5, 190, 3000 + 4 * 600, 8.0) + stretch * s["check"]   # status, verify, finalize(+quick eval), submit, reply
    t += min(ver, max(12.0, 262.0 - t))                          # TIME footer at 250 -> finalize + submit
    t += 0.05 * call(3, 60, 3500, 1.0)                           # submitter backstop
    return min(CAP, t)
data = {r: B.load(r) for r in B.RUNS}
v4 = st.mean(B.asis(t) for t in data["r_v4"].values())
print(f"v4 as-is {v4:.1f} s; +8% line {1.08*v4:.1f} s")
for label, fn in [("final central (locator reply by ~95 s)", lambda t: final(t)),
                  ("final, locator banner ignored (cut 150)", lambda t: final(t, loc_cut=150.0)),
                  ("final pessimistic (banners ignored, v9 verifier calls kept)", lambda t: final(t, pessim=True))]:
    print(f"{label:58s}", " ".join(f"{r[2:]}:{st.mean(fn(t) for t in data[r].values()):5.1f}({st.mean(fn(t) for t in data[r].values())/v4:.2f})" for r in B.RUNS))
print("x2 stretch; v4 x2 capped:", " ".join(f"{r[2:]}:{st.mean(min(CAP, 2*B.asis(t)) for t in data[r].values()):.0f}" for r in B.RUNS))
print("  final x2:", " ".join(f"{r[2:]}:{st.mean(final(t, stretch=2.0) for t in data[r].values()):.0f}" for r in B.RUNS))
print("  final x2 pessim:", " ".join(f"{r[2:]}:{st.mean(final(t, stretch=2.0, pessim=True) for t in data[r].values()):.0f}" for r in B.RUNS))
over = {r: sum(final(t) >= 295 for t in data[r].values()) for r in B.RUNS}
print("tasks projected >=295 s (central):", over, " v4 as-is:", sum(B.asis(t) >= 295 for t in data["r_v4"].values()))

# ---------------------------------------------------------------------------------------------------------------------
# Review round 2: the rows above are optimistic by construction. They cut every stage at its footer time (locator 95 s,
# fixer 210 s, verifier 262 s, even in the "pessimistic" row) and cap stage replies at 200/100/60 tokens (REPLY_CAP of
# design_B_replay.py), so no task can pass about 275 s and "0 at cap" is a property of the model, not a result. The rows
# below keep each trajectory's MEASURED replies, cut only at v10's max_output_tokens (locator 768 since review round 2,
# fixer and verifier 2,048), with the footers obeyed (a footer can only shorten a stage that heeds it) and with no footer
# cuts at all (the real pessimistic row: nothing makes gemma obey a footer). Race 2 must measure the obedience rate.
MEASURED_REPLY_CAP = {"locator": 768, "fixer": 2048, "verifier": 2048}


def parts(task, stretch=1.0):
    """final()'s stage costs before any footer cut: setup, locator, fixer, verifier, submitter (seconds)."""
    s = B.stages(task, drop_vgate=True)
    return (call(2, 40, 6000, 0.4), stretch * (s["locator"] + REPRO + CLAIMS), stretch * (s["fixer"] + call(1, 40, 700, 2.0)),
            call(5, 190, 3000 + 4 * 600, 8.0) + stretch * s["check"], 0.05 * call(3, 60, 3500, 1.0))


def nocut(task, stretch=1.0):
    return min(CAP, sum(parts(task, stretch)))


def measured(fn):
    """Run fn with the replay's reply caps set to v10's max_output_tokens (the measured replies), then restore them."""
    saved = dict(B.REPLY_CAP), dict(B.OUT_CAP)
    B.REPLY_CAP.update(MEASURED_REPLY_CAP)
    B.OUT_CAP["locator"] = MEASURED_REPLY_CAP["locator"]
    try:
        return fn()
    finally:
        B.REPLY_CAP.clear(); B.REPLY_CAP.update(saved[0])
        B.OUT_CAP.clear(); B.OUT_CAP.update(saved[1])


V4_X2 = st.mean(min(CAP, 2 * B.asis(t)) for t in data["r_v4"].values())   # r_v4 as-is, every call x2, capped


def honest_rows():
    """{label: {run: (mean s/task, ratio, tasks >= 295 s)}} for the review-round-2 rows; the ratio is to r_v4 as-is
    (x1 rows) or to r_v4 as-is x2 capped at 300 s (x2 rows)."""
    rows = {}
    for label, fn, ref in [("measured replies, footers obeyed", lambda t: final(t), v4),
                           ("measured replies, no footer cuts (pessimistic)", lambda t: nocut(t), v4),
                           ("x2 stretch, measured replies, footers obeyed", lambda t: final(t, stretch=2.0), V4_X2),
                           ("x2 stretch, measured replies, no footer cuts", lambda t: nocut(t, stretch=2.0), V4_X2)]:
        def one(fn=fn):
            return {r: [fn(t) for t in data[r].values()] for r in B.RUNS}
        got = measured(one)
        rows[label] = {r: (st.mean(v), st.mean(v) / ref, sum(x >= 295 for x in v)) for r, v in got.items()}
    return rows


print(f"review round 2 (measured replies cut at max_output_tokens 768/2048/2048; ratio to v4 as-is, x2 rows to v4 x2 "
      f"capped {V4_X2:.1f} s; tasks >= 295 s):")
for label, row in honest_rows().items():
    print(f"  {label:48s}", " ".join(f"{r[2:]}:{m:5.1f}({q:.2f}) cap{n}" for r, (m, q, n) in row.items()))
print("  12 h, every task at the cap (600 s startup + N x (300 + 3.6 setup + 5 overshoot + 1 teardown)):",
      " ".join(f"N={n}: {(600 + n * 309.6) / 3600:.2f} h" for n in (120, 130)))
