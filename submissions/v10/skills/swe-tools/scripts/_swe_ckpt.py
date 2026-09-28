"""swe-tools checkpoints (v10): every scored tree is kept as a binary diff against the baseline, and the best one can be
restored transactionally. Stdlib only.

  save(diff_bytes, score, key, verdict, quick) -> id | None
  best(key=None, quick=False) -> entry | None
  restore(rec) -> (ok, msg)                    refused at t >= T_NO_RESTORE; rolls back on any failure
  auto_restore_if_empty() -> (ok, msg) | None  used by _swe_common.late_guard() and finalize.py
"""
import hashlib
import os
import shutil

import _swe_common as C


def _sha(b):
    return hashlib.sha1(b or b"").hexdigest()


def _dir():
    d = os.path.join(C.swe_dir(), "ckpt")
    os.makedirs(d, exist_ok=True)
    return d


def path_of(cid):
    return os.path.join(_dir(), "%d.diff" % int(cid))


def _git(args, timeout=10):
    return C.git_run(list(args), timeout=C.real_budget(timeout))


def entries():
    return list((C.state_load() or {}).get("ckpts") or [])


def entry_for_sha(sha):
    for e in entries():
        if e.get("sha") == sha:
            return e
    return None


def _write(cid, data):
    p = path_of(cid)
    try:
        with open(p, "rb") as f:
            if f.read() == data:
                return
    except OSError:
        pass
    with open(p + ".tmp", "wb") as f:
        f.write(data)
    os.replace(p + ".tmp", p)


_META = ("classes", "imp_def", "incomplete")


def save(diff_bytes, score, key, verdict, quick, rkey=None, meta=None):
    """Store a non-empty diff with its score. A diff sha already stored updates its entry, except that an unscored save
    never overwrites a score and a quick score never overwrites a full one under the same key. rkey is the repro-only
    key (what quick scores are comparable under). meta: _swe_gate.evidence() of the evaluation (classes, imp_def,
    incomplete), or a dict holding those keys (an evaluate() result)."""
    if not diff_bytes:
        return None
    sha = _sha(diff_bytes)
    t = round(float(C.clock()), 1)
    got = {}
    ev = {k: (meta or {}).get(k) for k in _META} if score is not None else {k: None for k in _META}

    def fn(s):
        ck = s.setdefault("ckpts", [])
        for e in ck:
            if e.get("sha") != sha:
                continue
            keep = (score is None and e.get("score") is not None) or (
                quick and not e.get("quick") and e.get("score") is not None and e.get("key") == key)
            if not keep:
                e.update(score=list(score) if score is not None else None, key=key, verdict=verdict, t=t,
                         quick=bool(quick), rkey=rkey, **ev)
            got["id"] = e["id"]
            return s
        nid = max([int(e.get("id") or 0) for e in ck] + [0]) + 1
        ck.append(dict({"id": nid, "sha": sha, "score": list(score) if score is not None else None, "key": key,
                        "verdict": verdict, "t": t, "quick": bool(quick), "rkey": rkey}, **ev))
        got["id"] = nid
        return s
    C.state_update(fn)
    _write(got["id"], diff_bytes)
    return got["id"]


def rank(e, quick=False):
    sc = e.get("score")
    if sc is None:
        return (1,)
    sc = tuple(sc)
    return sc[:5] if (quick or e.get("quick")) else sc


def best(key=None, quick=False):
    """The highest score among stored non-empty checkpoints with the same key (any key when key is None, where an
    unscored checkpoint still beats nothing); the latest wins ties."""
    cands = []
    for e in entries():
        if not os.path.isfile(path_of(e.get("id") or 0)):
            continue
        if key is not None and (e.get("key") != key or e.get("score") is None):
            continue
        cands.append(e)
    if not cands:
        return None
    return max(cands, key=lambda e: (rank(e, quick), float(e.get("t") or 0), int(e.get("id") or 0)))


def better(a, b):
    """True when entry a beats entry b strictly (same key assumed); 5-tuples when either side is quick."""
    q = bool(a.get("quick") or b.get("quick"))
    return rank(a, q) > rank(b, q)


def definitely_worse(cur, e):
    """cur's evaluation is incomplete (a claim UNKNOWN, e.g. finalize's 12 s evaluation ran out of time, or an import
    failure never compared with the original), so its lower score may be an artefact. It loses to e only on definite
    evidence: a claim FIXED in e that STILL FAILS or STILL HANGS in cur, a claim still passing in e (INVALID) that BROKE
    in cur, or a definite import failure in cur where e imports."""
    ce, cc = e.get("classes") or {}, cur.get("classes") or {}
    for i, k in ce.items():
        c = cc.get(i)
        if (k == "FIXED" and c in ("STILL FAILS", "STILL HANGS")) or (k == "INVALID" and c == "BROKE"):
            return True
    sc, se = list(cur.get("score") or []), list(e.get("score") or [])
    return len(sc) > 1 and len(se) > 1 and sc[1] == 0 and se[1] == 1 and bool(cur.get("imp_def"))


def best_against(cur):
    """The stored checkpoint that strictly beats `cur`, or None (ties keep the current tree). Same key and both full:
    the whole score; otherwise the same repro (rkey) and the quick 5-tuples, because a quick evaluation has no test
    files. An incomplete `cur` (UNKNOWN is neutral, never a loss) is beaten only by definitely_worse evidence. Among
    several, the highest quick tuple, then full score, then the latest."""
    ck, rk = cur.get("key"), cur.get("rkey") or cur.get("key")
    partial = bool(cur.get("incomplete"))
    wins = []
    for e in entries():
        if e.get("sha") == cur.get("sha") or e.get("score") is None or not os.path.isfile(path_of(e.get("id") or 0)):
            continue
        if e.get("key") == ck and not e.get("quick") and not cur.get("quick"):
            q = False
        elif (e.get("rkey") or e.get("key")) == rk:
            q = True
        else:
            continue
        if rank(e, q) > rank(cur, q) and (not partial or definitely_worse(cur, e)):
            wins.append(e)
    if not wins:
        return None
    return max(wins, key=lambda e: (rank(e, True), rank(e, False), float(e.get("t") or 0), int(e.get("id") or 0)))


def _remove(rel):
    ws = C.ws()
    fp = os.path.join(ws, rel)
    try:
        if os.path.isdir(fp) and not os.path.islink(fp):
            shutil.rmtree(fp)
        elif os.path.lexists(fp):
            os.unlink(fp)
    except OSError:
        return
    d = os.path.dirname(fp)
    wsr = os.path.realpath(ws)
    while d and os.path.realpath(d) != wsr and os.path.realpath(d).startswith(wsr + os.sep):
        try:
            os.rmdir(d)
        except OSError:
            break
        d = os.path.dirname(d)


def reset_to_baseline():
    """Path-scoped reset of every changed path: tracked ones by `git checkout <baseline> -- <path>` (one path per call),
    files the baseline lacks and untracked files by removal. -> (ok, why)."""
    bl = C.baseline()
    rc, out, err = _git(["diff", "--name-status", "-z", "--no-renames", bl])
    if rc != 0:
        return False, "git diff failed: " + err.decode("utf-8", "replace").strip()[:120]
    items = [x for x in out.decode("utf-8", "surrogateescape").split("\0") if x]
    bad = []
    for i in range(0, len(items) - 1, 2):
        st, p = items[i], items[i + 1]
        if st.startswith("A"):
            _remove(p)
            continue
        rc, _, err = _git(["--literal-pathspecs", "checkout", bl, "--", p])
        if rc != 0:
            bad.append(p)
    rc, out, _ = _git(["ls-files", "--others", "--exclude-standard", "-z"])
    if rc == 0:
        for p in [x for x in out.decode("utf-8", "surrogateescape").split("\0") if x]:
            _remove(p)
    if bad:
        return False, "could not reset " + ", ".join(bad[:3])
    return True, ""


def _apply(data):
    if not data:
        return True, ""
    p = os.path.join(C.swe_dir(), "ckpt_apply.patch")
    with open(p, "wb") as f:
        f.write(data)
    rc, out, err = _git(["apply", "--binary", "--whitespace=nowarn", p], 20)
    if rc != 0:
        return False, "git apply failed: " + (err or out).decode("utf-8", "replace").strip().split("\n")[0][:160]
    return True, ""


def _set_tree(data):
    ok, why = reset_to_baseline()
    if not ok:
        return False, why
    return _apply(data)


def restore(rec):
    """Transactional restore of checkpoint `rec`: refused at t >= T_NO_RESTORE; the current tree is saved first and put
    back byte-exactly if anything fails."""
    t = float(C.clock())
    if t >= C.T_NO_RESTORE:
        return False, "RESTORE REFUSED: t=%ds is past %ds; kept the current tree." % (int(t), C.T_NO_RESTORE)
    try:
        with open(path_of(rec["id"]), "rb") as f:
            data = f.read()
    except (OSError, KeyError, TypeError, ValueError):
        return False, "RESTORE FAILED: checkpoint file missing; kept the current tree."
    cur = C.diff_bytes()
    if _sha(cur) == rec.get("sha"):
        return True, "checkpoint #%s is already the current tree" % rec.get("id")
    if cur:
        save(cur, None, None, "SAVED", False)
    ok, why = _set_tree(data)
    if ok:
        now = _sha(C.diff_bytes())
        if now != rec.get("sha"):
            ok, why = False, "the tree does not match the checkpoint after applying it"
    if not ok:
        ok2, why2 = _set_tree(cur)
        back = _sha(C.diff_bytes()) == _sha(cur) if ok2 else False
        return False, "RESTORE FAILED: %s; %s" % (
            why, "the current tree was kept" if back else "rollback also failed (%s)" % (why2 or "tree differs"))
    try:
        C.journal({"h": "restore", "id": rec.get("id"), "verdict": rec.get("verdict"), "ok": True})
    except Exception:
        pass
    return True, "restored checkpoint #%s" % rec.get("id")


def auto_restore_if_empty():
    """When no source change exists and a non-empty checkpoint is stored, restore the best one (any key).
    -> (ok, msg) or None when nothing applies."""
    ch = C.changes() or {}
    if ch.get("source"):
        return None
    if any(not C.is_protected(p) for p in ch.get("deleted") or []):
        return None
    rec = best(None)
    if rec is None:
        return None
    ok, msg = restore(rec)
    if ok:
        return True, "RESTORED checkpoint #%s: the tree had no source change at t=%ds." % (rec.get("id"), int(C.clock()))
    return False, msg
