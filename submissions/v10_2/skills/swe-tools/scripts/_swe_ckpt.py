"""swe-tools checkpoints (v10): every scored tree is kept as a binary diff against the baseline, and the best one can be
restored transactionally. Stdlib only.

  save(diff_bytes, score, key, verdict, quick) -> id | None
  best(key=None, quick=False) -> entry | None
  restore(rec) -> (ok, msg)                    refused at t >= T_NO_RESTORE; rolls back on any failure; tidies after
  auto_restore_if_empty() -> (ok, msg) | None  used by _swe_common.late_guard() and finalize.py
  clean_scratch() -> [removed]                 finalize.py step 2, and tidy() after every restore
v10.2 (SPEC_v10_2 5.8, R2): root scratch needs a separator after its prefix (C.scratch_name); a new root module or
directory that changed tracked code imports or references is kept, and the submit guard re-includes it.
"""
import fnmatch
import hashlib
import os
import shutil
import sys

import _swe_common as C

ROOT_FILES = ("test_*.py", "*_test.py")       # v10.2: the scratch prefixes are C.scratch_name (the separator rule)
ANY_FILES = ("*.log", "*.orig", "*.rej", "*.bak", "*.swp", ".coverage")
BIG_BYTES = 1024 * 1024


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
    env = C._unguarded_index_env()          # v10.1: protected files the submit guard hides are reset too
    try:
        rc, out, err = C.git_run(["diff", "--name-status", "-z", "--no-renames", bl], timeout=C.real_budget(10), env=env)
    finally:
        if env is not None:
            C._drop_index(env)
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
    rc, out, _ = _git(C.NO_GUARD + ["ls-files", "--others", "--exclude-standard", "-z"])
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


def _landed(data):
    """True when the worktree holds exactly the post-image of every file in `data` (git apply --reverse --check). The
    fallback check of restore(): a checkpoint saved before the submit guard was armed (v10.1) can hold a protected or
    scratch file that diff_bytes() no longer shows, so its sha cannot match even though the restore is exact
    (reset_to_baseline cleared every other change first)."""
    p = os.path.join(C.swe_dir(), "ckpt_check.patch")
    try:
        with open(p, "wb") as f:
            f.write(data)
    except OSError:
        return False
    rc, _, _ = _git(["apply", "--reverse", "--check", "--binary", "--whitespace=nowarn", p], 20)
    return rc == 0


def _set_tree(data):
    ok, why = reset_to_baseline()
    if not ok:
        return False, why
    return _apply(data)


def _z(b):
    return [p for p in b.decode("utf-8", "surrogateescape").split("\0") if p]


def _vendor_marker(parts):
    return any(x in ("site-packages", "_pytest") or x.endswith(".dist-info") for x in parts[:-1]) or \
        parts[-1].endswith(".dist-info")


_SPEC_PROBE = r"""
import importlib.util, sys
for n in sys.argv[1:]:
    try:
        s = importlib.util.find_spec(n)
    except BaseException:
        s = None
    o = ""
    if s is not None:
        o = s.origin if s.origin not in (None, "namespace") else ""
        if not o and s.submodule_search_locations:
            o = list(s.submodule_search_locations)[0]
        o = o or "?"
    sys.stdout.write("SWE-SPEC\t%s\t%s\n" % (n, o))
sys.stdout.flush()
"""


def shadowed(stems):
    """The names among `stems` that import from OUTSIDE the workspace once the workspace is off the path: an installed
    or stdlib module that a same-named untracked root file or directory would shadow under the grader's
    PYTHONPATH=<workspace> (the fastapi_14448 patch shipped typing_extensions.py and py.py; every test then failed to
    import). One child of the grader's python3, run from an empty directory. -> set (empty when it cannot run)."""
    stems = sorted({s for s in stems if s and s.isidentifier()})
    if not stems:
        return set()
    wsr = os.path.realpath(C.ws())
    std = {s for s in stems if C.is_stdlib_name(s)}
    rest = [s for s in stems if s not in std]
    if not rest:
        return std

    def inside(p):
        rp = os.path.realpath(p)
        return rp == wsr or rp.startswith(wsr + os.sep)
    env = C.grader_env(C.ws(), "spec")
    env["PYTHONPATH"] = os.pathsep.join(x for x in (env.get("PYTHONPATH") or "").split(os.pathsep)
                                        if x and not inside(x))
    py = "python3" if shutil.which("python3", path=env.get("PATH")) else (sys.executable or "python3")
    rc, out = C.sh([py, "-s", "-c", _SPEC_PROBE] + rest, C.real_budget(5), cwd=env["TMPDIR"], env=env)
    got = set(std)
    for ln in (out or "").splitlines():
        f = ln.split("\t")
        if len(f) == 3 and f[0] == "SWE-SPEC" and f[2] and (not os.path.isabs(f[2]) or not inside(f[2])):
            got.add(f[1])
    return got


def _root_match(name, patterns):
    """Root scratch names match in any letter case (v10.1: KPI 8 is case-insensitive, so a root Repro.txt that
    finalize kept still counted as a scratch patch)."""
    low = name.lower()
    return any(fnmatch.fnmatchcase(low, x) for x in patterns)


def root_scratch_file(name):
    """A root-level file that is scratch by name: a scratch prefix plus a separator (v10.2), or a test file name."""
    return C.scratch_name(name) or _root_match(name, ROOT_FILES)


def save_edited(diff=None):
    """v10.1 (race 2, fastapi_15280): an unscored checkpoint of every tree with a source change that edit.py wrote or
    status.py saw, so a landed edit the model later undid can still be restored by finalize's EMPTY branch and the
    late guard. rank() puts an unscored entry below every scored one, so best_against() is unchanged. -> id | None."""
    try:
        if diff is None:
            if not C.source_changed():
                return None
            diff = C.diff_bytes()
        cid = save(diff, None, None, "EDITED", False) if diff else None
    except Exception:
        return None
    try:                                     # v10.2 (R2): edit.py and status.py re-arm the guard's kept entries
        C.refresh_guard_keep()
    except Exception:
        pass
    return cid


def clean_scratch():
    """Delete untracked scratch and vendored trees. Untracked .py files inside directories with tracked files stay (new
    modules); a root-level one stays only when C.root_module_kept says it is a module. Any untracked root file or
    directory whose name shadows an installed or stdlib module is deleted. -> [removed paths]."""
    ws = C.ws()
    rc, out, _ = _git(C.NO_GUARD + ["ls-files", "--others", "--exclude-standard", "-z"])
    if rc != 0:
        return []
    untracked = _z(out)
    if not untracked:
        return []
    rc, out, _ = _git(["ls-files", "-z"])
    tracked_dirs = {""}
    for p in _z(out) if rc == 0 else []:
        d = os.path.dirname(p)
        while d and d not in tracked_dirs:
            tracked_dirs.add(d)
            d = os.path.dirname(d)
    wsr = os.path.realpath(ws)

    def top_untracked(p):
        """The highest ancestor directory of p that holds no tracked file (None if p's own dir holds tracked files)."""
        d = os.path.dirname(p)
        best = None
        while d and d not in tracked_dirs:
            best = d
            d = os.path.dirname(d)
        return best

    kill_dirs, kill_files, root_py = set(), set(), []
    changed = None
    for p in untracked:
        parts = p.split("/")
        base = parts[-1]
        if len(parts) > 1 and parts[0] not in tracked_dirs and C.scratch_name(parts[0]):
            if changed is None:
                rc, out, _ = _git(["diff", "--name-only", "-z", "--no-renames", C.baseline()])
                changed = _z(out) if rc == 0 else []
            if not C.references_name(parts[0], changed):     # v10.2: a new root dir tracked code uses is kept
                kill_dirs.add(parts[0])
                continue
        if len(parts) == 1 and root_scratch_file(base) and not (base.endswith(".py") and C.scratch_name(base)):
            kill_files.add(p)
            continue
        if any(fnmatch.fnmatchcase(base, x) for x in ANY_FILES):
            kill_files.add(p)
            continue
        if _vendor_marker(parts) or (base == "setup.py" and len(parts) > 1):
            top = top_untracked(p)
            if top:
                kill_dirs.add(top)
                continue
        try:
            if os.path.getsize(os.path.join(ws, p)) > BIG_BYTES:
                kill_files.add(p)
                continue
        except OSError:
            pass
        if len(parts) == 1 and base.endswith(".py") and not C.is_protected(p):
            root_py.append(p)
    if root_py:
        rc, out, _ = _git(["diff", "--name-only", "-z", "--no-renames", C.baseline()])
        tracked = [q for q in _z(out) if q.endswith(".py")] if rc == 0 else []
        for p in root_py:
            if not C.root_module_kept(p, tracked):
                kill_files.add(p)
    # names at the root that would shadow an installed or stdlib module (files and untracked top-level dirs)
    roots = {}
    for p in untracked:
        parts = p.split("/")
        if parts[0] in kill_dirs or p in kill_files:
            continue
        if len(parts) == 1:
            stem, ext = os.path.splitext(parts[0])
            if ext in (".py", ".pyi", ".pyc", ".so", ".pyd"):
                roots.setdefault(stem.split(".")[0], ("file", p))
        elif parts[0] not in tracked_dirs:
            roots.setdefault(parts[0], ("dir", parts[0]))
    if roots:
        for stem in sorted(shadowed(list(roots))):
            kind, what = roots[stem]
            (kill_dirs if kind == "dir" else kill_files).add(what)
    removed = []
    for d in sorted(kill_dirs):
        fp = os.path.join(ws, d)
        rp = os.path.realpath(fp)
        if not rp.startswith(wsr + os.sep) or os.path.islink(fp):
            continue
        shutil.rmtree(fp, ignore_errors=True)
        removed.append(d + "/")
    for p in sorted(kill_files):
        if any(p.startswith(d + "/") for d in kill_dirs):
            continue
        fp = os.path.join(ws, p)
        try:
            os.unlink(fp)
            removed.append(p)
        except OSError:
            pass
        d = os.path.dirname(fp)
        while d and os.path.realpath(d).startswith(wsr + os.sep):
            try:
                os.rmdir(d)
            except OSError:
                break
            d = os.path.dirname(d)
    return removed


def scratch_note(removed):
    """The one line finalize prints after clean_scratch() removed something ('' when nothing was)."""
    if not removed:
        return ""
    more = len(removed) - 6
    return "CLEANED: removed %s%s" % (", ".join(removed[:6]), " (+%d more)" % more if more > 0 else "")


def tidy():
    """Clean a just-restored tree (review round 2). A checkpoint stores the tree as it was scored: verify --repro-only
    saves the raw diff before any hygiene and full verify keeps root scratch, so a restore can bring back a test/config
    edit (the hidden test_patch then fails to apply: a 0) and scratch that finalize had already deleted. Reverts
    protected paths, then deletes scratch. -> [note lines], empty when nothing was done."""
    notes = []
    try:
        rev = C.hygiene_revert() or []
    except Exception:
        rev = []
    if rev:
        notes.append(C.hygiene_note(rev))
    try:
        removed = clean_scratch()
    except Exception:
        removed = []
    if removed:
        notes.append(scratch_note(removed))
    return notes


def _tidy_msg(msg):
    return "\n".join([msg] + tidy())


def restore(rec):
    """Transactional restore of checkpoint `rec`: refused at t >= T_NO_RESTORE; the current tree is saved first and put
    back byte-exactly if anything fails. After a successful restore (checked against rec's sha first), tidy() reverts
    protected paths and deletes scratch; msg is 'restored checkpoint #k' plus one line per thing tidy() undid."""
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
        return True, _tidy_msg("checkpoint #%s is already the current tree" % rec.get("id"))
    if cur:
        save(cur, None, None, "SAVED", False)
    ok, why = _set_tree(data)
    if ok:
        now = _sha(C.diff_bytes())
        if now != rec.get("sha") and not _landed(data):
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
    return True, _tidy_msg("restored checkpoint #%s" % rec.get("id"))


def auto_restore_if_empty():
    """When no source change exists and a non-empty checkpoint is stored, restore the best one (any key).
    -> (ok, msg) or None when nothing applies. msg is ONE line (late_guard prefixes a helper's output with it): what
    tidy() undid follows in parentheses."""
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
        undid = [x for x in msg.split("\n")[1:] if x]
        return True, "RESTORED checkpoint #%s: the tree had no source change at t=%ds.%s" % (
            rec.get("id"), int(C.clock()), (" (then %s)" % "; ".join(undid)) if undid else "")
    return False, msg
