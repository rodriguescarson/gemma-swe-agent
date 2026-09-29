import os, sys
sys.dont_write_bytecode = True
_HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("SWE_PATH0", sys.path[0] if sys.path else "")
_STD = tuple({os.path.realpath(p) for p in (sys.base_prefix, sys.base_exec_prefix)})
sys.path[:] = [_HERE] + [p for p in sys.path if p and os.path.realpath(p).startswith(_STD) and "-packages" not in p]
for _n in [n for n, m in list(sys.modules.items()) if n.split(".")[0] in getattr(sys, "stdlib_module_names", ())
           and getattr(m, "__file__", None) and not os.path.realpath(m.__file__).startswith(_STD)]:
    del sys.modules[_n]
import _swe_common as C

import time

USAGE = "python3 /tmp/swe/finalize.py"
FLAGS = {}
NAME = "finalize"
MIN_EVAL = 2.0          # a quick evaluation needs this many real seconds before T_EVAL_END, else it is skipped
LARGE_PATCH = 200 * 1024
LARGE_FILES = 20
TARGET_LINES = 20       # EDIT TARGET: numbered lines shown on an empty tree (v10.1)
# v10.1 (race 2, fastapi_14873 submitted an empty patch at 72 s of 176): EMPTY says what an empty patch costs and how
# much time is left.
EMPTY_LINE = ("NOT READY: EMPTY at t=%ds (%ds left) - no source change. Do not submit an empty patch: it always "
              "fails. Make the plan's FIX (smallest plausible version) now, then run python3 /tmp/swe/finalize.py "
              "again.")


def _cut(s, n):
    s = str(s)
    return s if len(s) <= n else s[:n - 3] + "..."


def _git(args, timeout=10, env=None):
    return C.git_run(list(args), timeout=C.real_budget(timeout), env=env)


def _stat(diff):
    import _swe_gate as G
    facts = G.diff_facts(diff)
    plus = sum(f["plus"] for f in facts.values())
    minus = sum(f["minus"] for f in facts.values())
    added = sum(1 for f in facts.values() if f.get("new"))
    return facts, plus, minus, added


def roundtrip(diff):
    """The patch as the harness transmits it (UTF-8 text, errors replaced) must apply onto a fresh baseline index.
    -> None or the reason it does not."""
    text = diff.decode("utf-8", "replace")
    data = text.encode("utf-8")
    if not data.endswith(b"\n"):
        data += b"\n"
    swe = C.swe_dir()
    idx = os.path.join(swe, "fin_idx")
    pf = os.path.join(swe, "fin_patch.diff")
    with open(pf, "wb") as f:
        f.write(data)
    env = dict(os.environ, GIT_INDEX_FILE=idx)
    try:
        os.unlink(idx)
    except OSError:
        pass
    rc, _, err = _git(["read-tree", C.baseline()], 10, env=env)
    if rc != 0:
        return None
    rc, out, err = _git(["apply", "--check", "--cached", "--binary", "--whitespace=nowarn", pf], 15, env=env)
    for p in (idx, pf):
        try:
            os.unlink(p)
        except OSError:
            pass
    if rc == 0:
        return None
    why = (err or out).decode("utf-8", "replace").strip().split("\n")[0]
    if data != diff + (b"" if diff.endswith(b"\n") else b"\n"):
        why += " (the patch has non-UTF-8 bytes)"
    return _cut(why or "git apply --check failed", 200)


def _tidied(msg):
    """What K.restore() undid on the restored tree (review round 2: a checkpoint can hold test/config edits and scratch,
    and steps 1-2 ran before the restore): its lines after the first."""
    return [x for x in str(msg or "").split("\n")[1:] if x]


def _label(e):
    return "%s, t=%ds" % (e.get("verdict") or "?", int(float(e.get("t") or 0)))


def edit_target(st, room):
    """v10.1 (race 2, fastapi_14873): on an empty tree, the code to edit, ready for --lines: the last edit's region if
    one landed earlier (it was undone), else the latest real view of a source file (the locator's). At most
    TARGET_LINES numbered lines within `room` chars; [] when nothing fits or nothing was viewed."""
    cands = []
    for e in st.get("edits") or []:
        if isinstance(e, dict) and e.get("file") and isinstance(e.get("start"), int):
            a = max(1, int(e["start"]) - 2)
            cands.append((float(e.get("t") or 0), 1, e["file"], a, max(a, int(e.get("end") or a) + 2)))
    for f, lst in (st.get("views") or {}).items():
        for v in lst if isinstance(lst, list) else []:
            if isinstance(v, list) and len(v) == 3 and all(isinstance(x, (int, float)) for x in v):
                cands.append((float(v[2]), 0, f, int(v[0]), int(v[1])))
    ws = C.ws()
    for t, _, f, a, b in sorted(cands, reverse=True):
        if not f.endswith(".py") or C.write_protected(f):
            continue
        try:
            with open(os.path.join(ws, f), "rb") as fh:
                lines = fh.read().split(b"\n")
        except OSError:
            continue
        if lines and lines[-1] == b"":
            lines.pop()
        a, b = max(1, a), min(len(lines), b, a + TARGET_LINES - 1)
        if b < a:
            continue
        head = "EDIT TARGET (the code viewed or edited last): %s lines %d-%d" % (f, a, b)
        rows, used = [], len(head) + 1
        for n in range(a, b + 1):
            row = "%5d| %s" % (n, _cut(lines[n - 1].decode("utf-8", "replace").rstrip("\r"), 100))
            if used + len(row) + 1 > room - 90:
                break
            rows.append(row)
            used += len(row) + 1
        if len(rows) < min(3, b - a + 1):       # the room left cannot hold a useful target: try an older one
            continue
        last = a + len(rows) - 1
        head = "EDIT TARGET (the code viewed or edited last): %s lines %d-%d" % (f, a, last)
        return [head] + rows + ["use: python3 /tmp/swe/edit.py %s --lines %d-%d <<'EOF' ... EOF" % (f, a, last)]
    return []


def main():
    C.bootstrap()
    if C.parse_args(sys.argv[1:], FLAGS, []) is None:
        return
    import _swe_gate as G
    import _swe_ckpt as K
    notes = []
    try:
        C.arm_submit_guard()          # v10.1: re-arm (a failed install, or a read-tree/reset that dropped the flags)
    except Exception:
        pass
    rev = C.hygiene_revert() or []
    if rev:
        notes.append(C.hygiene_note(rev))
    removed = K.clean_scratch()
    if removed:
        notes.append(K.scratch_note(removed))
    ch = G.changes()
    if not G.nonempty(ch):
        rec = K.best(None)
        if rec is not None:
            ok, msg = K.restore(rec)
            if ok:
                notes.append("RESTORED: checkpoint #%s (%s) (the tree had no source change)" % (rec["id"], _label(rec)))
                notes += _tidied(msg)
            else:
                notes.append(msg)
            ch = G.changes()
    else:
        diff = C.diff_bytes()
        sha = G.sha1(diff)
        cur = K.entry_for_sha(sha)
        secs = G.end_budget(C.FINALIZE_QUICK, C.T_EVAL_END)
        if (cur is None or cur.get("score") is None) and secs >= MIN_EVAL:
            try:
                R = G.evaluate(quick=True, run_tests=False, advice=False, deadline=time.time() + secs, diff=diff, ch=ch)
                word = G.verdict(R)[2]
                K.save(diff, R["score"], R["key"], word, True, rkey=R.get("rkey"), meta=R)
                cur = K.entry_for_sha(sha)
            except Exception as e:
                notes.append(_cut("NOTE: quick evaluation failed (%s)" % type(e).__name__, 100))
        if cur is not None and cur.get("score") is not None:
            b = K.best_against(cur)
            if b is not None:
                ok, msg = K.restore(b)
                if ok:
                    notes.append("RESTORED: checkpoint #%s (%s) replaced the current tree (%s)." % (
                        b["id"], _label(b), _label(cur)))
                    notes += _tidied(msg)
                    ch = G.changes()
                else:
                    notes.append(msg)
    first = None
    fsha = None
    tail = []
    bad = G.compile_check([p for p in ch["source"] if p.endswith(".py")])
    if bad:
        first = ("NOT READY: SYNTAX ERROR %s:%d: %s. Fix it with python3 /tmp/swe/edit.py, then run "
                 "python3 /tmp/swe/finalize.py again." % (bad[0], bad[1], _cut(bad[2], 150)))
    elif not G.nonempty(ch):
        t = C.clock()
        first = EMPTY_LINE % (int(t), max(0, int(C.CAP_S - t)))
    else:
        diff = C.diff_bytes()
        undone = C.enforce_patch_rules(diff)     # v10.1: never READY while the patch carries a test/config or scratch file
        if undone:
            notes.append(_cut("CLEANED: the patch carried %s; undone" % ", ".join(
                "%s (%s)" % (p, w) for p, w in undone[:4]), 300))
            diff = C.diff_bytes()
            ch = G.changes()
        left = C.patch_violations(C.patch_file_list(diff))
        why = roundtrip(diff)
        if not G.nonempty(ch):
            t = C.clock()
            first = EMPTY_LINE % (int(t), max(0, int(C.CAP_S - t)))
        elif left:
            first = "NOT READY: the patch still carries %s (graders own these files); remove them, then run " \
                    "python3 /tmp/swe/finalize.py again." % _cut(", ".join(p for p, _ in left), 200)
        elif why:
            first = "NOT READY: patch does not apply cleanly: %s" % why
        else:
            facts, plus, minus, added = _stat(diff)
            paths = sorted(facts)
            first = "READY: %d files changed (+%d -%d): %s. Next step: submit the patch." % (
                len(paths), plus, minus, _cut(" ".join(paths), 300))
            if len(diff) > LARGE_PATCH or added > LARGE_FILES:
                notes.append("NOTE: large patch (%d files, %d kB); fine if the issue needs it." % (
                    len(paths), len(diff) // 1024))
            sha = fsha = G.sha1(diff)
            t = round(float(C.clock()), 1)

            def fin(s):
                s["final_done"], s["final_sha"], s["final_t"] = True, sha, t
                return s
            C.state_update(fin)
    if not first.startswith("READY"):
        def unfin(s):
            s["final_done"] = False
            return s
        st = C.state_update(unfin)
        if first.startswith("NOT READY: EMPTY"):
            tail = edit_target(st, C.CAPS[NAME] - len(first) - sum(len(n) + 1 for n in notes) - 300)
    try:
        C.journal({"h": NAME, "first": first, "msg": first.split(":")[0]})
    except Exception:
        pass
    body = "\n".join([_cut(n, 300) for n in notes] + tail)
    C.emit(NAME, _cut(first, 600), body, C.CAPS[NAME], src=G.nonempty(ch), sha=fsha)


if __name__ == "__main__":
    C.safe_main(NAME, main)
