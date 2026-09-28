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
