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

import fnmatch
import shutil
import time

USAGE = "python3 /tmp/swe/finalize.py"
FLAGS = {}
NAME = "finalize"
ROOT_FILES = ("repro*", "reproduce*", "scratch*", "debug*", "tmp*", "temp*", "try*", "demo*", "test_*.py", "*_test.py")
ROOT_DIRS = ("repro*", "reproduce*", "scratch*", "debug*", "tmp*", "temp*", "try*", "demo*")
ANY_FILES = ("*.log", "*.orig", "*.rej", "*.bak", "*.swp", ".coverage")
MIN_EVAL = 2.0          # a quick evaluation needs this many real seconds before T_EVAL_END, else it is skipped
BIG_BYTES = 1024 * 1024
LARGE_PATCH = 200 * 1024
LARGE_FILES = 20


def _cut(s, n):
    s = str(s)
    return s if len(s) <= n else s[:n - 3] + "..."


def _z(b):
    return [p for p in b.decode("utf-8", "surrogateescape").split("\0") if p]


def _git(args, timeout=10, env=None):
    return C.git_run(list(args), timeout=C.real_budget(timeout), env=env)


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


def clean_scratch():
    """Delete untracked scratch and vendored trees. Untracked .py files inside directories with tracked files stay (new
    modules); a root-level one stays only when C.root_module_kept says it is a module. Any untracked root file or
    directory whose name shadows an installed or stdlib module is deleted. -> [removed paths]."""
    ws = C.ws()
    rc, out, _ = _git(["ls-files", "--others", "--exclude-standard", "-z"])
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
    for p in untracked:
        parts = p.split("/")
        base = parts[-1]
        if len(parts) > 1 and parts[0] not in tracked_dirs and any(fnmatch.fnmatchcase(parts[0], x) for x in ROOT_DIRS):
            kill_dirs.add(parts[0])
            continue
        if len(parts) == 1 and any(fnmatch.fnmatchcase(base, x) for x in ROOT_FILES):
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


def _label(e):
    return "%s, t=%ds" % (e.get("verdict") or "?", int(float(e.get("t") or 0)))


def main():
    C.bootstrap()
    if C.parse_args(sys.argv[1:], FLAGS, []) is None:
        return
    import _swe_gate as G
    import _swe_ckpt as K
    notes = []
    rev = C.hygiene_revert() or []
    if rev:
        notes.append(C.hygiene_note(rev))
    removed = clean_scratch()
    if removed:
        more = len(removed) - 6
        notes.append("CLEANED: removed %s%s" % (", ".join(removed[:6]), " (+%d more)" % more if more > 0 else ""))
    ch = G.changes()
    if not G.nonempty(ch):
        rec = K.best(None)
        if rec is not None:
            ok, msg = K.restore(rec)
            if ok:
                notes.append("RESTORED: checkpoint #%s (%s) (the tree had no source change)" % (rec["id"], _label(rec)))
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
                    ch = G.changes()
                else:
                    notes.append(msg)
    first = None
    fsha = None
    bad = G.compile_check([p for p in ch["source"] if p.endswith(".py")])
    if bad:
        first = "NOT READY: SYNTAX ERROR %s:%d: %s. Fix it with edit.py, then run finalize.py again." % (
            bad[0], bad[1], _cut(bad[2], 150))
    elif not G.nonempty(ch):
        first = ("NOT READY: EMPTY - no source change. Make the plan's FIX (smallest plausible version) with edit.py, "
                 "then run finalize.py again.")
    else:
        diff = C.diff_bytes()
        why = roundtrip(diff)
        if why:
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
        C.state_update(unfin)
    try:
        C.journal({"h": NAME, "first": first, "msg": first.split(":")[0]})
    except Exception:
        pass
    body = "\n".join(_cut(n, 300) for n in notes)
    C.emit(NAME, _cut(first, 600), body, C.CAPS[NAME], src=G.nonempty(ch), sha=fsha)


if __name__ == "__main__":
    C.safe_main(NAME, main)
