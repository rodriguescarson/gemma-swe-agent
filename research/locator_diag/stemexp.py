import json, os, re, sys, io, contextlib
SP = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True
sys.path.insert(0, SP)
import prep; prep.helpers(SP); prep.workspaces(SP)
sys.path.insert(0, SP + "/scripts")
import _swe_index as I
import locate as L
sys.path.insert(0, SP)
with contextlib.redirect_stdout(io.StringIO()):
    import rankexp as RX   # reuses first_q, gold, issues, rank_v, gold_rank (re-runs its experiment silently)
SUF = ("ings", "ing", "ions", "ion", "ed", "es", "s")
def stem(t):
    for s in SUF:
        if t.endswith(s) and len(t) - len(s) >= 4:
            return t[: -len(s)]
    return t
orig_word = I._word
def _word(w):
    r = I._MEMO.get(("S", w))
    if r is None:
        base = list(orig_word(w))
        extra = [stem(t) for t in base if stem(t) != t]
        r = tuple(base + [I._intern(t) for t in extra])
        I._MEMO[("S", w)] = r
    return r
rows = []
for mode in ("base", "stem"):
    I._word = orig_word if mode == "base" else _word
    for tid in sorted(os.listdir(SP + "/ws")):
        idx = I.build(os.path.join(SP, "ws", tid), use_cache=False)
        g = RX.gold[tid]
        qs = {"title": RX.issues[tid].strip().splitlines()[0], "issue": RX.issues[tid]}
        for src in ("L", "P"):
            if (src, tid) in RX.first_q:
                qs["model_" + src] = RX.first_q[(src, tid)]
        for qn, q in qs.items():
            rk = L.rank(idx, L.clean_query(q))
            rows.append((mode, tid, qn, RX.gold_rank(rk, g)))
import collections
for qn in ("title", "issue", "model_L", "model_P"):
    for mode in ("base", "stem"):
        R = [r for r in rows if r[0] == mode and r[2] == qn]
        print(qn, mode, "n", len(R), "@1", sum(r[3] == 1 for r in R), "@3", sum(r[3] <= 3 for r in R), "not@8", sum(r[3] > 8 for r in R))
b = {(r[1], r[2]): r[3] for r in rows if r[0] == "base"}
for r in rows:
    if r[0] == "stem" and b[(r[1], r[2])] != r[3]:
        print("CHANGED", r[1], r[2], b[(r[1], r[2])], "->", r[3])
