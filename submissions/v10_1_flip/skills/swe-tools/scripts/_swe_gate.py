"""swe-tools gate library (v10): base tree, claim-structured reproductions, import check, test discovery and runs,
SIBLINGS, SPEC GAPS and the checkpoint score. Stdlib only. Never imports repository code or pytest in-process: every
repository import happens in a child process under the grader environment."""
import hashlib
import os
import re
import shutil
import threading
import time

import _swe_common as C

MAX_CLAIMS = 6
DISABLED_TEXT = "pytest is disabled in this environment"
IGNORED_MAX_FILES = 2000
IGNORED_MAX_BYTES = 50 * 1024 * 1024
TEST_MAX_BYTES = 300 * 1024
DISCOVER_MAX = 3
SIB_MAX = 6
GAP_MAX = 4
RERUN_MAX = 20
HANG_ORIG_CAP = 15.0        # ORIGINAL pytest side when the reproduction already hangs on the original
ORIG_TESTS_KEEP = 4         # cached ORIGINAL test results, per file set
PHASE_MIN = 3.0            # a phase that would start with less than this left is skipped as UNKNOWN (no time)

_SEM = threading.BoundedSemaphore(max(1, int(getattr(C, "MAX_PAR", 2))))
_HDR = re.compile(r"^#\s*CLAIM\s*(\d+)\s*:(.*)$", re.M)
_NEW_HDR = re.compile(r"^\s*#\s*NEW\s*:(.*)$", re.M)
_MSG_HDR = re.compile(r"^\s*#\s*MESSAGE\s*:(.*)$", re.M)
_FRAME = re.compile(r'^\s*File "([^"]+)", line (\d+)')
_EXC_TYPE = re.compile(r"^([A-Za-z_][\w.]*)(:|$)")
_EXC_SUFFIX = ("Error", "Exception", "Exit", "Interrupt", "Warning", "Iteration", "Failure", "Timeout")
_NEW_PATTERNS = (
    (re.compile(r"cannot import name '(\w+)' from '([\w.]+)'"), "import"),
    (re.compile(r"module '([\w.]+)' has no attribute '(\w+)'"), "modattr"),
    (re.compile(r"type object '(\w+)' has no attribute '(\w+)'"), "attr"),
    (re.compile(r"'(\w+)' object has no attribute '(\w+)'"), "attr"),
    (re.compile(r"([\w.]+)\(\) got an unexpected keyword argument '(\w+)'"), "kwarg"),
)
_TEST_BASENAME = re.compile(r"^(test_.*|.*_test)\.py$")
_NEVER_TESTS = ("tests/render.py", "tests/_card_render.py")
_CALL = re.compile(r"[\w.]+\([^()]{4,40}")
_SKIP_SIB = {"pass", "return", "else:", "try:", "finally:", "break", "continue"}


# ----------------------------------------------------------------------------------------------------------------------
# small process + git layer (stdout kept apart from stderr so -z listings parse exactly)

def _git(args, timeout=10, cwd=None, env=None):
    """git (quotepath off) -> (rc | None, stdout bytes, stderr bytes), via the shared runner (new session, killpg,
    tracked for cleanup)."""
    return C.git_run(list(args), timeout=C.real_budget(timeout), env=env, cwd=cwd or C.ws())


def _z(data):
    return [p for p in data.decode("utf-8", "surrogateescape").split("\0") if p]


def _dec(b):
    return b.decode("utf-8", "replace")


def _py(env):
    """The grader runs `python3` from PATH; fall back to this interpreter only when PATH has none."""
    if shutil.which("python3", path=(env or os.environ).get("PATH")):
        return "python3"
    import sys
    return sys.executable or "python3"


def _sh(argv, timeout, cwd, env):
    """Python children go through the shared runner (new session, killpg, capped merged output)."""
    rc, text = C.sh(argv, timeout, cwd=cwd, env=env)
    return rc, text if isinstance(text, str) else _dec(text or b"")


def relpaths(text):
    """Strip the workspace and base-tree prefixes from messages (they only cost tokens)."""
    if not text:
        return text
    for root in sorted({C.ws(), os.path.realpath(C.ws()), os.path.join(C.swe_dir(), "base"),
                        os.path.realpath(os.path.join(C.swe_dir(), "base"))}, key=len, reverse=True):
        text = text.replace(root + os.sep, "")
    return text


def budget(default_s):
    """real_budget(default_s), kept 1.5 s inside the helper watchdog (safe_main arms it at real_budget(HELPER_LIMIT)),
    so a deadline near the end of the task never races the watchdog."""
    rb = C.real_budget(default_s)
    wd = C.real_budget(getattr(C, "HELPER_LIMIT", 110)) - 1.5
    return max(0.5, min(rb, wd))


def end_budget(default_s, end):
    """budget(default_s) clamped so the work is over by task time `end` (C.T_VERIFY_END for verify, C.T_EVAL_END for
    --repro-only and finalize's quick evaluation): real seconds, 0.0 once `end` has passed. This ties every gate run to
    the end-game plan (verify, finalize, restore before T_NO_RESTORE, the submission before CAP_S)."""
    return max(0.0, min(budget(default_s), (float(end) - float(C.clock())) / C.clock_scale()))


def sha1(data):
    if isinstance(data, str):
        data = data.encode("utf-8", "surrogateescape")
    return hashlib.sha1(data or b"").hexdigest()


def _upd(fn):
    def wrap(s):
        fn(s)
        return s
    return C.state_update(wrap)


def _swe():
    d = C.swe_dir()
    os.makedirs(d, exist_ok=True)
    return d


# ----------------------------------------------------------------------------------------------------------------------
# job pool: every child of the gate (claims, pytest sides) shares one semaphore of MAX_PAR slots

def run_jobs(jobs, deadline):
    """jobs: [(key, fn)] or [(key, fn, own_deadline)] with fn(remaining_s) -> result. At most MAX_PAR run at once
    (one semaphore for the whole process); a job that cannot start before its deadline (or raises) yields None."""
    jobs = [j if len(j) == 3 else (j[0], j[1], deadline) for j in jobs]
    results = {}
    if not jobs:
        return results
    lock = threading.Lock()
    it = iter(jobs)

    def worker():
        while True:
            with lock:
                try:
                    k, fn, dl = next(it)
                except StopIteration:
                    return
            dl = min(dl, deadline)
            if dl - time.time() < 0.5:
                results[k] = None
                continue
            with _SEM:
                rem = dl - time.time()
                if rem < 0.5:
                    results[k] = None
                    continue
                try:
                    results[k] = fn(rem)
                except Exception:
                    results[k] = None

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(min(len(jobs), max(1, C.MAX_PAR)))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(max(0.0, deadline - time.time()) + 6.0)
    for j in jobs:
        results.setdefault(j[0], None)
    return results


# ----------------------------------------------------------------------------------------------------------------------
# repository facts

def repo_tops(root):
    """Top-level importable names of a tree: packages (dirs with __init__.py) and modules at the root or under src/."""
    tops = set()
    for base in (root, os.path.join(root, "src")):
        try:
            it = list(os.scandir(base))
        except OSError:
            continue
        for e in it:
            n = e.name
            if n.startswith("."):
                continue
            try:
                if e.is_dir(follow_symlinks=False) and os.path.isfile(os.path.join(e.path, "__init__.py")):
                    tops.add(n)
                elif n.endswith(".py") and e.is_file() and n[:-3].isidentifier():
                    tops.add(n[:-3])
            except OSError:
                pass
    return tops


def module_name(rel, root=None):
    """Dotted module for a repo-relative .py path inside an importable package chain (src/ stripped), else None."""
    root = root or C.ws()
    if not rel.endswith(".py"):
        return None
    parts = rel[:-3].split("/")
    base = root
    if parts[0] == "src" and len(parts) > 1:
        parts, base = parts[1:], os.path.join(root, "src")
    if parts[-1] == "__init__":
        parts = parts[:-1]
        pkg_parts = parts
    else:
        pkg_parts = parts[:-1]
    if not parts or not pkg_parts or parts[-1] == "__main__":
        return None
    if not all(p.isidentifier() for p in parts):
        return None
    d = base
    for p in pkg_parts:
        d = os.path.join(d, p)
        if not os.path.isfile(os.path.join(d, "__init__.py")):
            return None
    return ".".join(parts)


def changes():
    ch = C.changes() or {}
    return {k: list(ch.get(k) or []) for k in ("source", "protected", "untracked", "deleted")}


def nonempty(ch):
    if ch.get("source"):
        return True
    return any(not C.is_protected(p) for p in ch.get("deleted") or [])


# ----------------------------------------------------------------------------------------------------------------------
# 1. base tree

def base_tree():
    """A detached worktree of the baseline under $SWE/base (plus the workspace's ignored build artefacts). Made once per
    task and cached in state.base; None means the ORIGINAL side is UNKNOWN (base copy unavailable)."""
    bl = C.baseline()
    d = os.path.join(_swe(), "base")
    b = (C.state_load() or {}).get("base") or {}
    if b.get("sha") == bl and b.get("dir") == d:
        if b.get("ok") and os.path.isdir(d):
            return d
        if b.get("ok") is False:
            return None
    ok = False
    try:
        ok = _make_base(C.ws(), bl, d)
    except Exception:
        ok = False
    _upd(lambda s: s.__setitem__("base", {"sha": bl, "ok": bool(ok), "dir": d}))
    return d if ok else None


def _make_base(ws, bl, d):
    if os.path.lexists(d):
        _git(["worktree", "remove", "--force", d], 10, cwd=ws)
        shutil.rmtree(d, ignore_errors=True)
    _git(["worktree", "prune"], 5, cwd=ws)
    rc, _, _ = _git(["-c", "core.hooksPath=/dev/null", "worktree", "add", "--detach", "-f", d, bl], 10, cwd=ws)
    ok = rc == 0 and os.path.isdir(d)
    if not ok:
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d, exist_ok=True)
        import shlex
        cmd = "set -o pipefail; git archive %s | tar -x -C %s" % (shlex.quote(bl), shlex.quote(d))
        rc, _ = C.sh(cmd, C.real_budget(20), cwd=ws)
        try:
            ok = rc == 0 and any(True for _ in os.scandir(d))
        except OSError:
            ok = False
    if ok:
        _copy_ignored(ws, d)
    return ok


def _copy_ignored(ws, d):
    # the submit guard's exclude file (v10.1) must not make scratch or new tests look like build artefacts here
    rc, out, _ = _git(C.NO_GUARD + ["ls-files", "--others", "--ignored", "--exclude-standard", "--directory", "-z"], 10,
                      cwd=ws)
    if rc != 0:
        return 0
    cands = [p for p in _z(out) if not p.endswith("/")]
    if not cands:
        return 0
    rc, out, _ = _git(["ls-files", "-z", "--", "*.py"], 10, cwd=ws)
    pydirs = {os.path.dirname(p) for p in _z(out)} if rc == 0 else set()
    n = size = 0
    for p in cands:
        parts = p.split("/")
        base = parts[-1]
        if any(x in ("__pycache__", ".pytest_cache", ".git") or x.endswith(".egg-info") for x in parts):
            continue
        if base.endswith((".pyc", ".pyo")) or base.startswith(".adk_exec_"):
            continue
        if os.path.dirname(p) not in pydirs:
            continue
        src = os.path.join(ws, p)
        try:
            if os.path.islink(src) or not os.path.isfile(src):
                continue
            sz = os.path.getsize(src)
        except OSError:
            continue
        if n >= IGNORED_MAX_FILES or size + sz > IGNORED_MAX_BYTES:
            break
        dst = os.path.join(d, p)
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            n += 1
            size += sz
        except OSError:
            continue
    return n


def untracked_snapshot(tree):
    """(untracked paths, other changed paths) of a tree from porcelain -z, or None."""
    rc, out, _ = _git(["status", "--porcelain", "-z", "--untracked-files=all"], 10, cwd=tree)
    if rc != 0:
        return None
    items = _z(out)
    untracked, modified = set(), set()
    i = 0
    while i < len(items):
        e = items[i]
        code, path = e[:2], e[3:]
        if code == "??":
            untracked.add(path)
        else:
            modified.add(path)
            if code[0] in "RC":
                i += 1
        i += 1
    return untracked, modified


def cleanup_tree(tree, before, is_base):
    """Delete untracked files a run created in `tree`; in the private base tree also restore tracked files it changed."""
    if before is None:
        return
    after = untracked_snapshot(tree)
    if after is None:
        return
    for p in sorted(after[0] - before[0]):
        fp = os.path.join(tree, p)
        try:
            if os.path.isdir(fp) and not os.path.islink(fp):
                shutil.rmtree(fp, ignore_errors=True)
            else:
                os.unlink(fp)
        except OSError:
            pass
    if is_base:
        for p in sorted(after[1] - before[1]):
            _git(["--literal-pathspecs", "checkout", "HEAD", "--", p], 5, cwd=tree)


# ----------------------------------------------------------------------------------------------------------------------
# 2. claims

class Claim(object):
    __slots__ = ("idx", "num", "title", "body", "start", "text")

    def __init__(self, idx, num, title, body, start, text):
        self.idx, self.num, self.title, self.body, self.start, self.text = idx, num, title, body, start, text


def _split_names(s):
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return [x.strip().strip("`'\"") for x in out if x.strip()]


def _parse(text):
    """-> (prelude, [Claim], new_names, messages). No header means one claim; at most MAX_CLAIMS run."""
    text = (text or "").replace("\r\n", "\n")
    ms = list(_HDR.finditer(text))
    claims = []
    if not ms:
        prelude = ""
        claims.append(Claim(1, 1, "", text, 1, text))
    else:
        prelude = text[:ms[0].start()]
        if prelude and not prelude.endswith("\n"):
            prelude += "\n"
        for i, m in enumerate(ms[:MAX_CLAIMS]):
            end = ms[i + 1].start() if i + 1 < len(ms) else len(text)
            body = text[m.start():end]
            start = text.count("\n", 0, m.start()) + 1
            claims.append(Claim(i + 1, int(m.group(1)), m.group(2).strip()[:60], body, start, prelude + body))
    new, msgs = [], []
    for m in _NEW_HDR.finditer(text):
        for n in _split_names(m.group(1)):
            if n and n not in new:
                new.append(n)
    for m in _MSG_HDR.finditer(text):
        v = m.group(1).strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        if v and v not in msgs:
            msgs.append(v)
    return prelude, claims, new, msgs


def parse_tb(out):
    """(frames [(file, line)], exception line) of the last traceback in `out` (or a bare SyntaxError report)."""
    lines = out.splitlines()
    tb = -1
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].startswith("Traceback (most recent call last)"):
            tb = i
            break
    frames, exc = [], ""
    for i in range(tb + 1 if tb >= 0 else 0, len(lines)):
        ln = lines[i]
        m = _FRAME.match(ln)
        if m:
            frames.append((m.group(1), int(m.group(2))))
            continue
        if tb >= 0 and ln and not ln[0].isspace() and not ln.startswith(("During handling", "The above exception")):
            exc = ln.strip()
            break
    if not exc:
        for ln in reversed(lines):
            if not ln or ln[0].isspace():
                continue
            m = _EXC_TYPE.match(ln)
            if m and m.group(1).split(".")[-1].endswith(_EXC_SUFFIX):
                exc = ln.strip()
                break
    return frames, exc


def _sig(rc, out):
    frames, exc = parse_tb(out)
    if exc:
        return exc[:200]
    last = ""
    for ln in reversed(out.splitlines()):
        if ln.strip():
            last = ln.strip()
            break
    return ("exit %s: %s" % (rc, last))[:200] if last else "exit %s" % rc


def _defined_elsewhere(name, claim, claims):
    pat = re.compile(r"(^|\n)\s*(%s\s*(,[^=\n]*)?=(?!=)|def %s\b|class %s\b|(from\s+\S+\s+)?import\b[^\n]*\b%s\b|for %s\b|with\b[^\n]*\bas %s\b)"
                     % ((re.escape(name),) * 6))
    return any(c is not claim and pat.search(c.body) for c in claims)


class _Env(object):
    """Per-evaluation cache of grader envs and importability probes."""

    def __init__(self):
        self.envs = {}
        self.importable = {}

    def env(self, tree, side):
        k = (tree, side)
        if k not in self.envs:
            self.envs[k] = C.grader_env(tree, side)
        return self.envs[k]

    def can_import(self, top):
        if top not in self.importable:
            ws = C.ws()
            env = self.env(ws, "cur")
            rc, out = _sh([_py(env), "-s", "-c", "import importlib.util,sys;"
                           "print('SWE-SPEC', importlib.util.find_spec(sys.argv[1]) is not None)", top],
                          C.real_budget(5), ws, env)
            self.importable[top] = "SWE-SPEC True" in (out or "")
        return self.importable[top]


def claim_file(sha, claim):
    d = os.path.join(_swe(), "claims")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "%s_%d.py" % (sha[:12], claim.idx))
    data = claim.text.encode("utf-8", "surrogateescape")
    try:
        with open(p, "rb") as f:
            if f.read() == data:
                return p
    except OSError:
        pass
    with open(p + ".tmp", "wb") as f:
        f.write(data)
    os.replace(p + ".tmp", p)
    return p


def claim_jobs(side, tree, claims, sha, envs, deadline=None):
    """One job per claim: `python3 -s <claim file>` with cwd=tree under the grader env, CLAIM_TIMEOUT s each; the
    claims of one evaluation share the deadline real_budget(CLAIMS_TOTAL)."""
    env = envs.env(tree, side)
    py = _py(env)
    jobs = []
    for c in claims:
        path = claim_file(sha, c)

        def fn(rem, path=path):
            t = min(float(C.CLAIM_TIMEOUT), rem)
            t0 = time.time()
            rc, out = _sh([py, "-s", path], t, tree, env)
            return {"rc": rc, "out": (out or "")[-8000:], "full": t >= float(C.CLAIM_TIMEOUT) - 0.05,
                    "secs": round(time.time() - t0, 2), "path": path}
        jobs.append((("claim", side, c.idx), fn, deadline or time.time() + C.real_budget(C.CLAIMS_TOTAL)))
    return jobs


def interpret(raw, side, claim, claims, orig_tops, all_tops, envs):
    """Raw job result -> {status PASS|FAIL|HANG|UNKNOWN, sig, broken, hint}."""
    if raw is None:
        return {"status": "UNKNOWN", "sig": "not run (no time)", "broken": None, "hint": None}
    rc, out = raw["rc"], raw["out"]
    if rc is None:
        if raw["full"]:
            return {"status": "HANG", "sig": "no result after %ss" % C.CLAIM_TIMEOUT, "broken": None, "hint": None}
        return {"status": "UNKNOWN", "sig": "stopped early (no time)", "broken": None, "hint": None}
    if rc == 0:
        return {"status": "PASS", "sig": "", "broken": None, "hint": None}
    sig = relpaths(_sig(rc, out))
    res = {"status": "FAIL", "sig": sig, "broken": None, "hint": None}
    if side != "orig":
        return res
    frames, exc = parse_tb(out)
    etype = exc.split(":")[0].strip().split(".")[-1] if exc else ""
    inner = frames[-1] if frames else ("", 0)
    in_claim = os.path.basename(inner[0]) == os.path.basename(raw.get("path") or "")
    if etype in ("SyntaxError", "IndentationError", "TabError") and in_claim:
        res["broken"] = "%s at line %d" % (etype, _repro_line(inner[1], claim, claims))
    elif etype == "NameError" and in_claim:
        m = re.search(r"name '(\w+)' is not defined", exc)
        res["broken"] = exc[:120]
        if m and _defined_elsewhere(m.group(1), claim, claims):
            res["hint"] = "put shared code before the first # CLAIM line"
    elif etype == "ModuleNotFoundError":
        m = re.search(r"No module named '([\w.]+)'", exc)
        if m:
            mod = m.group(1)
            top = mod.split(".")[0]
            if "." not in mod and top in orig_tops:
                return {"status": "UNKNOWN", "sig": "the original copy could not import %s" % top, "broken": None,
                        "hint": None}
            if top not in all_tops and not envs.can_import(top):
                res["broken"] = exc[:120]
    return res


def _repro_line(k, claim, claims=None):
    """Line k of a claim file (prelude + section) -> the line of the saved reproduction."""
    plen = claim.text[:len(claim.text) - len(claim.body)].count("\n")
    return k if k <= plen else claim.start + (k - plen - 1)


def classify(o, c):
    if o.get("broken"):
        return "BROKEN"
    so, sc = o.get("status"), (c or {}).get("status")
    if so == "UNKNOWN" or sc in (None, "UNKNOWN"):
        return "UNKNOWN"
    if so in ("FAIL", "HANG"):
        return {"PASS": "FIXED", "FAIL": "STILL FAILS", "HANG": "STILL HANGS"}.get(sc, "UNKNOWN")
    return "INVALID" if sc == "PASS" else "BROKE"


def new_from_sigs(orig):
    out = []
    for r in (orig or {}).values():
        s = (r or {}).get("sig") or ""
        if (r or {}).get("status") != "FAIL" or (r or {}).get("broken"):
            continue
        for rx, kind in _NEW_PATTERNS:
            m = rx.search(s)
            if not m:
                continue
            if kind == "import":
                n = "%s@%s" % (m.group(1), m.group(2))
            elif kind == "modattr":
                n = "%s@%s" % (m.group(2), m.group(1))
            elif kind == "attr":
                n = "%s.%s" % (m.group(1), m.group(2))
            else:
                n = "%s(%s=)" % (m.group(1).split(".")[-1], m.group(2))
            if n not in out:
                out.append(n)
            break
    return out


def repro_path():
    return os.path.join(_swe(), "repro.py")


def repro_text():
    try:
        with open(repro_path(), "rb") as f:
            return f.read().decode("utf-8", "surrogateescape")
    except OSError:
        return ""


def save_repro(text):
    text = (text or "").replace("\r\n", "\n")
    if text and not text.endswith("\n"):
        text += "\n"
    p = repro_path()
    with open(p + ".tmp", "wb") as f:
        f.write(text.encode("utf-8", "surrogateescape"))
    os.replace(p + ".tmp", p)
    return text


def claims_state(sha):
    r = (C.state_load() or {}).get("repro") or {}
    return r if r.get("sha") == sha else None


def store_orig(sha, orig, new_names, messages):
    keep = {str(k): v for k, v in orig.items() if v and v.get("status") != "UNKNOWN"}

    def fn(s):
        r = s.get("repro") or {}
        if r.get("sha") != sha:
            r = {"sha": sha, "orig": {}, "new_names": [], "messages": []}
        r["orig"] = dict(r.get("orig") or {}, **keep)
        r["new_names"] = list(new_names)
        r["messages"] = list(messages)
        s["repro"] = r
    _upd(fn)


class claims(object):
    """Namespace for the pinned API: claims.parse(text), claims.run(tree, side, sha)."""
    parse = staticmethod(_parse)

    @staticmethod
    def run(tree, side, sha, text=None, deadline=None):
        text = repro_text() if text is None else text
        _, cl, _, _ = _parse(text)
        envs = _Env()
        deadline = deadline or time.time() + C.real_budget(C.CLAIMS_TOTAL)
        before = untracked_snapshot(tree)
        raw = run_jobs(claim_jobs(side, tree, cl, sha, envs), deadline)
        cleanup_tree(tree, before, tree != C.ws())
        tops = repo_tops(tree)
        return {c.idx: interpret(raw.get(("claim", side, c.idx)), side, c, cl, tops, tops | repo_tops(C.ws()), envs)
                for c in cl}


def claim_summary(cl, orig, cur):
    """-> dict(classes {idx: class}, valid, fixed, broke, text 'k/n claims fixed')."""
    classes = {}
    for c in cl:
        o = orig.get(c.idx) or orig.get(str(c.idx)) or {"status": "UNKNOWN"}
        classes[c.idx] = classify(o, (cur or {}).get(c.idx)) if cur is not None else None
    valid = [c.idx for c in cl if (orig.get(c.idx) or orig.get(str(c.idx)) or {}).get("status") in ("FAIL", "HANG")
             and not (orig.get(c.idx) or orig.get(str(c.idx)) or {}).get("broken")]
    fixed = sum(1 for i in valid if classes.get(i) == "FIXED")
    broke = sum(1 for c in cl if classes.get(c.idx) == "BROKE")
    return {"classes": classes, "valid": valid, "fixed": fixed, "broke": broke,
            "text": "%d/%d claims fixed" % (fixed, len(valid))}


# ----------------------------------------------------------------------------------------------------------------------
# 3. import check (plus the origin probe, in the same child)

_IMPORT_SCRIPT = r"""
import importlib, importlib.util, os, sys, traceback
a = sys.argv[1:]
i = a.index("--")
for t in a[:i]:
    try:
        s = importlib.util.find_spec(t)
        o = (s.origin if s and s.origin not in (None, "namespace") else
             (list(s.submodule_search_locations or [""])[0] if s else ""))
    except BaseException:
        o = ""
    sys.stdout.write("SWE-ORIGIN\t%s\t%s\n" % (t, o or ""))
sys.stdout.flush()
for m in a[i + 1:]:
    try:
        importlib.import_module(m)
    except BaseException:
        sys.stdout.write("SWE-IMPORT-FAIL\t%s\n" % m)
        traceback.print_exc(file=sys.stdout)
        sys.stdout.flush()
        os._exit(3)
sys.stdout.write("SWE-IMPORT-OK\n")
sys.stdout.flush()
os._exit(0)
"""


def compile_check(paths, root=None):
    """In-memory compile of each .py path; -> None or (rel, line, msg)."""
    root = root or C.ws()
    for rel in paths:
        if not rel.endswith(".py"):
            continue
        fp = os.path.join(root, rel)
        try:
            with open(fp, "rb") as f:
                src = f.read()
        except OSError:
            continue
        try:
            compile(src, fp, "exec", dont_inherit=True)
        except SyntaxError as e:
            return rel, int(e.lineno or 0), ("%s: %s" % (type(e).__name__, e.msg or e))[:200]
        except (ValueError, TypeError) as e:
            return rel, 0, ("%s: %s" % (type(e).__name__, e))[:200]
    return None


def _import_child(tree, side, tops, mods, envs, timeout):
    env = envs.env(tree, side)
    rc, out = _sh([_py(env), "-s", "-c", _IMPORT_SCRIPT] + list(tops) + ["--"] + list(mods), timeout, tree, env)
    return rc, out or ""


def _import_failure(out, rc, wsr):
    """(failed module or '', 'file:line' in the workspace or '', exception line) of a failed import child."""
    failed = ""
    m = re.search(r"^SWE-IMPORT-FAIL\t(\S+)", out, re.M)
    if m:
        failed = m.group(1)
    tail = out[out.find("SWE-IMPORT-FAIL"):] if failed else out
    frames, exc = parse_tb(tail)
    where = ""
    for f, ln in reversed(frames):
        rf = os.path.realpath(f)
        if rf.startswith(wsr + os.sep):
            where = "%s:%d" % (os.path.relpath(rf, wsr).replace(os.sep, "/"), ln)
            break
    return failed, where, relpaths(exc or _sig(rc, tail))


def import_check(changed_src, envs=None, deadline=None, base=None):
    """-> dict(ok True|False|None, line, where, module, hang, pre, base_checked, origins {top: path},
    outside {top: path}, note). A failing import is compared with the ORIGINAL tree: `base` when given, else
    base_tree() built on demand (cached per task), so the check never depends on the caller having built it. The
    child stops at the first failure, so after a failure the original shares (pre), the modules after it are
    imported again (at most 3 such rounds). base_checked tells whether the reported failure was compared with the
    original."""
    envs = envs or _Env()
    ws = C.ws()
    res = {"ok": True, "line": "", "where": "", "module": "", "hang": False, "pre": False, "origins": {},
           "outside": {}, "note": "", "syntax": False, "base_checked": False}
    bad = compile_check(changed_src, ws)
    if bad:
        res.update(ok=False, syntax=True, module=bad[0], line=bad[2], where="%s:%d" % (bad[0], bad[1]))
        return res
    mods = []
    for p in changed_src:
        if p.endswith(".py") and os.path.isfile(os.path.join(ws, p)):
            m = module_name(p, ws)
            if m and m not in mods:
                mods.append(m)
    tops = sorted({m.split(".")[0] for m in mods})
    if not mods:
        res["note"] = "no changed module inside a package"
        return res
    budget = min(float(C.IMPORT_CHECK), (deadline - time.time()) if deadline else float(C.IMPORT_CHECK))
    budget = min(budget, C.real_budget(C.IMPORT_CHECK))
    if budget < 1.0:
        res.update(ok=None, note="skipped (no time)")
        return res
    rc, out = _import_child(ws, "cur", tops, mods, envs, budget)
    wsr = os.path.realpath(ws)
    for ln in out.splitlines():
        if ln.startswith("SWE-ORIGIN\t"):
            parts = ln.split("\t")
            if len(parts) >= 3 and parts[2]:
                res["origins"][parts[1]] = parts[2]
    origin_map = {}
    for top, o in res["origins"].items():
        ro = os.path.realpath(o)
        if ro == wsr or ro.startswith(wsr + os.sep):
            pkg = os.path.dirname(ro) if os.path.basename(ro).startswith("__init__.") else ro
            rel = os.path.relpath(os.path.dirname(pkg), wsr)
            origin_map[top] = "" if rel == "." else rel.replace(os.sep, "/")
        else:
            res["outside"][top] = o
            origin_map[top] = None
    if origin_map:
        def fn(s):
            o = dict(s.get("origin") or {})
            o.update(origin_map)
            s["origin"] = o
        _upd(fn)
    if rc is None:
        if budget < min(5.0, float(C.IMPORT_CHECK) - 0.05):
            res.update(ok=None, note="import check stopped early (no time)")
        else:
            res.update(ok=False, hang=True, module=mods[0],
                       line="HANG (the import did not finish in %ds)" % int(budget + 0.5))
        return res
    if "SWE-IMPORT-OK" in out and rc == 0:
        return res

    def left():
        rb = min(budget, C.real_budget(C.IMPORT_CHECK))
        return min(rb, deadline - time.time()) if deadline else rb
    todo, pre = list(mods), []
    while True:
        failed, where, line = _import_failure(out, rc, wsr)
        res.update(ok=False, pre=False, module=failed or todo[0], line=line[:200], where=where, base_checked=False,
                   note="")
        if not failed:
            return res
        if base is None and left() >= 1.0:
            base = base_tree()
        bt = left()
        if not base or bt < 1.0:
            return res
        brc, bout = _import_child(base, "orig", [], [failed], envs, bt)
        res["base_checked"] = brc is not None
        if brc is None or "SWE-IMPORT-OK" in bout:
            return res
        _, bexc = parse_tb(bout[bout.find("SWE-IMPORT-FAIL"):] if "SWE-IMPORT-FAIL" in bout else bout)
        bexc = relpaths(bexc)
        if not bexc or bexc.strip() != line.strip():
            return res
        pre.append(failed)
        res.update(ok=True, pre=True, module="", line="", where="",
                   note="%s fails on original too (%s)" % (", ".join(pre), bexc[:120]))
        rest = todo[todo.index(failed) + 1:] if failed in todo else []
        if not rest:
            return res
        bt = left()
        if len(pre) >= 3 or bt < 1.0:
            res["note"] += "; %s not checked (%s)" % (", ".join(rest[:3]), "no time" if bt < 1.0 else "limit")
            return res
        rc, out = _import_child(ws, "cur", [], rest, envs, bt)
        todo = rest
        if rc is None:
            if bt >= min(5.0, float(C.IMPORT_CHECK) - 0.05):
                res.update(ok=False, pre=False, hang=True, module=rest[0],
                           line="HANG (the import did not finish in %ds)" % int(bt + 0.5))
            else:
                res["note"] += "; %s not checked (no time)" % ", ".join(rest[:3])
            return res
        if "SWE-IMPORT-OK" in out and rc == 0:
            return res


# ----------------------------------------------------------------------------------------------------------------------
# 4. discovery

_ESC = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}


def unquote_path(s):
    """A path as git prints it in patch headers: C-quoted ("a/p\\303\\251.py") when it has special bytes."""
    s = s.strip()
    if len(s) < 2 or s[0] != '"' or s[-1] != '"':
        return s
    body, out, i = s[1:-1], bytearray(), 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            nx = body[i + 1]
            if nx in "01234567" and i + 3 < len(body) + 1 and all(c in "01234567" for c in body[i + 1:i + 4]):
                out.append(int(body[i + 1:i + 4], 8) & 0xFF)
                i += 4
                continue
            out.append(_ESC.get(nx, ord(nx) if ord(nx) < 128 else 63))
            i += 2
            continue
        out += ch.encode("utf-8", "surrogateescape")
        i += 1
    return out.decode("utf-8", "surrogateescape")


def _header_path(rest, prefix):
    """'b/x y.py' or '"b/p\\303\\251.py"' -> 'x y.py' / 'pé.py' (None for /dev/null)."""
    p = unquote_path(rest)
    if p == "/dev/null":
        return None
    return p[len(prefix):] if p.startswith(prefix) else p


def _git_header(ln):
    """The b-side path of a 'diff --git' line, quoted or not."""
    rest = ln[len("diff --git "):]
    if rest.endswith('"'):
        j = rest.rfind(' "b/')
        if j >= 0:
            return _header_path(rest[j + 1:], "b/")
    m = re.match(r"(?:a/)?(.*) b/(.*)$", rest)
    return m.group(2) if m else None


def diff_facts(diff):
    """Parse a unified diff (bytes or str) -> {path: {"removed": [...], "added_lines": set(new line numbers),
    "plus": n, "minus": n, "new": bool, "headers": [...], "defs": [...]}}."""
    if isinstance(diff, bytes):
        diff = diff.decode("utf-8", "replace")
    files, cur, new_ln, in_hunk = {}, None, 0, False
    for ln in diff.split("\n"):
        if ln.startswith("diff --git "):
            cur, in_hunk = None, False
            path = _git_header(ln)
            if path:
                cur = {"removed": [], "added_lines": set(), "plus": 0, "minus": 0, "new": False, "headers": [],
                       "defs": [], "deleted": False, "binary": False}
                files[path] = cur
            continue
        if cur is None:
            continue
        if not in_hunk and (ln.startswith("+++ ") or ln.startswith("--- ")):
            continue
        if ln.startswith("new file mode"):
            cur["new"] = True
        elif ln.startswith("deleted file mode"):
            cur["deleted"] = True
        elif ln.startswith("GIT binary patch") or ln.startswith("Binary files"):
            cur["binary"] = True
        elif ln.startswith("@@"):
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@(.*)$", ln)
            in_hunk = True
            if m:
                new_ln = int(m.group(1))
                if m.group(2) == "0":
                    cur["added_lines"].add(max(1, new_ln))
                cur["headers"].append(m.group(3).strip())
        elif ln.startswith("+"):
            cur["plus"] += 1
            cur["added_lines"].add(new_ln)
            dm = re.match(r"\+\s*(?:async\s+)?(?:def|class)\s+(\w+)", ln)
            if dm:
                cur["defs"].append(dm.group(1))
            new_ln += 1
        elif ln.startswith("-"):
            cur["minus"] += 1
            cur["removed"].append(ln[1:])
            cur["added_lines"].add(max(1, new_ln))
            dm = re.match(r"-\s*(?:async\s+)?(?:def|class)\s+(\w+)", ln)
            if dm:
                cur["defs"].append(dm.group(1))
        elif ln.startswith(" "):
            new_ln += 1
    return files


def _load_index(deadline_s):
    try:
        import _swe_index as I
        try:
            return I.build(C.ws(), deadline_s=max(0.5, deadline_s), want_terms=False)
        except TypeError:
            return I.build(C.ws(), deadline_s=max(0.5, deadline_s))
    except Exception:
        return None


def _sym(s):
    return (s[0], s[1], int(s[2]), int(s[3]), s[4] if len(s) > 4 else ()) if s else None


def changed_symbols(facts, idx):
    names = set()
    for path, f in facts.items():
        if not path.endswith(".py") or f.get("binary"):
            continue
        for h in f["headers"]:
            m = re.match(r"(?:async\s+)?(?:def|class)\s+(\w+)", h)
            if m:
                names.add(m.group(1))
        names.update(f["defs"])
        if idx is not None and not f.get("deleted"):
            for ln in sorted(f["added_lines"])[:400]:
                try:
                    s = _sym(idx.enclosing(path, ln))
                except Exception:
                    s = None
                if s and s[1] in ("def", "async def", "class"):
                    names.update(x for x in s[0].split(".") if x.isidentifier())
        elif not f.get("deleted"):
            names.update(_local_enclosing(path, f["added_lines"]))
    return {n for n in names if len(n) >= 4 and not (n.startswith("__") and n.endswith("__"))}


def _local_enclosing(path, lines):
    """Fallback when _swe_index is unavailable: names of the defs/classes enclosing the given lines."""
    import ast
    try:
        with open(os.path.join(C.ws(), path), "rb") as f:
            tree = ast.parse(f.read())
    except Exception:
        return set()
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            end = getattr(node, "end_lineno", node.lineno)
            if any(node.lineno <= ln <= end for ln in lines):
                out.add(node.name)
    return out


def _tracked(ws, pathspecs=()):
    rc, out, _ = _git(["ls-files", "-z", "--"] + list(pathspecs), 10, cwd=ws)
    return _z(out) if rc == 0 else []


def is_candidate(p):
    if p in _NEVER_TESTS or p.startswith("tools/") or os.path.basename(p) == "conftest.py":
        return False
    return bool(_TEST_BASENAME.match(os.path.basename(p)))


def discover(changed, extra=(), facts=None, idx=None, ws=None):
    """Top test files for the change: collectable test_*.py / *_test.py only, scored; --tests entries first."""
    ws = ws or C.ws()
    extra = [e for e in (extra or []) if e]
    ex_files = []
    for e in extra:
        f = e.split("::")[0]
        if os.path.isfile(os.path.join(ws, f)) and e not in ex_files:
            ex_files.append(e)
    cands = []
    for p in _tracked(ws, ["*test_*.py", "*_test.py"]):
        if is_candidate(p):
            try:
                if os.path.getsize(os.path.join(ws, p)) < TEST_MAX_BYTES:
                    cands.append(p)
            except OSError:
                pass
    cset = set(cands)
    src = [p for p in changed if p.endswith(".py") and not C.is_protected(p)]
    stems = set()
    mods = set()
    for p in src:
        b = os.path.basename(p)[:-3]
        if b == "__init__":
            b = os.path.basename(os.path.dirname(p))
        if b and b.isidentifier():
            stems.add(b)
        m = module_name(p, ws)
        if m:
            mods.add(m)
    names = changed_symbols(facts or {}, idx) if facts is not None else set()
    score = {}

    def add(f, v):
        if f in cset:
            score[f] = score.get(f, 0) + v
    for f in cands:
        b = os.path.basename(f)[:-3]
        for s in stems:
            if b == "test_" + s or b == s + "_test":
                add(f, 5)
    words = sorted((names | stems))[:60]
    if words and cands:
        args = ["grep", "-o", "-w", "-F", "-I", "-z"]
        for w in words:
            args += ["-e", w]
        rc, out, _ = _git(args + ["--", "*test_*.py", "*_test.py"], 5, cwd=ws)
        seen = {}
        for ln in _dec(out).split("\n"):
            if "\0" not in ln:
                continue
            f, w = ln.split("\0", 1)
            seen.setdefault(f, set()).add(w)
        for f, ws_ in seen.items():
            for w in ws_:
                add(f, 3 if w in names else 1)
    if mods and cands:
        tops = sorted({m.split(".")[0] for m in mods})
        args = ["grep", "-n", "-I", "-z", "-E"]
        for t in tops:
            args += ["-e", r"^[[:space:]]*(from|import)[[:space:]]+%s([.[:space:],]|$)" % re.escape(t)]
        rc, out, _ = _git(args + ["--", "*test_*.py", "*_test.py"], 5, cwd=ws)
        hits = {}
        for ln in _dec(out).split("\n"):
            parts = ln.split("\0")
            if len(parts) >= 3:
                hits.setdefault(parts[0], []).append(parts[2])
        for f, lines in hits.items():
            if any(_imports_module(l, m) for l in lines for m in mods):
                add(f, 2)
    ex_paths = {e.split("::")[0] for e in ex_files}
    ranked = sorted((f for f in score if score[f] > 0 and f not in ex_paths), key=lambda f: (-score[f], f))
    return (ex_files[:DISCOVER_MAX] + ranked)[:DISCOVER_MAX]


def _imports_module(line, mod):
    s = line.strip()
    parent, _, leaf = mod.rpartition(".")
    if re.match(r"from\s+%s\s+import\b" % re.escape(mod), s):
        return True
    m = re.match(r"import\s+(.+)$", s)
    if m and any(x.strip().split(" ")[0] == mod for x in m.group(1).split(",")):
        return True
    if parent:
        m = re.match(r"from\s+%s\s+import\s+\(?(.+)$" % re.escape(parent), s)
        if m and leaf in [x.strip().split(" ")[0].strip("()") for x in m.group(1).split(",")]:
            return True
    return False


# ----------------------------------------------------------------------------------------------------------------------
# 5. test runs

def pytest_mask(envs=None):
    """-> (state 'ok'|'masked'|'absent', why). Reads pytest/__main__.py for the harness shim text; never imports pytest
    in this process and never bypasses the mask. Cached per task."""
    st = C.state_load() or {}
    cached = st.get("pytest_mask")
    if cached in ("ok", "masked", "absent"):
        return cached, st.get("pytest_mask_why") or ""
    envs = envs or _Env()
    ws = C.ws()
    env = envs.env(ws, "cur")
    rc, out = _sh([_py(env), "-s", "-c", "import importlib.util as u;s=u.find_spec('pytest');"
                   "print('SWE-PYTEST', (s.origin or '') if s else '')"], C.real_budget(C.IMPORT_CHECK), ws, env)
    m = re.search(r"^SWE-PYTEST ?(.*)$", out or "", re.M)
    if rc is None or not m:
        return "absent", "pytest probe failed"
    origin = m.group(1).strip()
    if not origin:
        state, why = "absent", "pytest is not installed"
    else:
        main = os.path.join(os.path.dirname(origin), "__main__.py")
        try:
            with open(main, "rb") as f:
                txt = f.read(20000).decode("utf-8", "replace")
            if DISABLED_TEXT in txt:
                state, why = "masked", DISABLED_TEXT
            else:
                state, why = "ok", ""
        except OSError:
            state, why = "absent", "pytest has no __main__"

    def fn(s):
        s["pytest_mask"] = state
        s["pytest_mask_why"] = why
    _upd(fn)
    return state, why


def pytest_argv(py, files, junit):
    return [py, "-s", "-m", "pytest"] + list(files) + [
        "-q", "-p", "no:cacheprovider", "-p", "no:anyio", "-o", "timeout=0", "-o", "python_classes=Test* *Test",
        "--tb=short", "-rfE", "--continue-on-collection-errors", "--junitxml=" + junit]


def _dotted(f):
    return f.split("::")[0][:-3].replace("/", ".") if f.split("::")[0].endswith(".py") else f


def file_for(dotted, files, memo=None):
    """(file, rest) for a JUnit dotted name, or None: `file` is the workspace-relative test file and `rest` the class
    path after its module ('' for a module-level test). pytest builds classnames from node ids relative to ITS rootdir,
    the directory of the nearest ini file: under tests/pytest.ini (every rich task) tests/test_x.py reports as
    'test_x', not 'tests.test_x'. So every dotted suffix of each file is tried, dropping the fewest leading parts first
    (the most specific match wins); a match needs a dot boundary. memo: an optional dict cache for one parse."""
    if memo is not None and dotted in memo:
        return memo[dotted]
    cands = []
    for f in files:
        fp = f.split("::")[0]
        if fp.endswith(".py"):
            cands.append((fp, fp[:-3].split("/")))
    res = None
    for k in range(max([len(p) for _, p in cands] or [0])):
        for fp, parts in cands:
            if k >= len(parts):
                continue
            s = ".".join(parts[k:])
            if dotted == s:
                res = (fp, "")
            elif dotted.startswith(s + "."):
                res = (fp, dotted[len(s) + 1:])
            if res:
                break
        if res:
            break
    if memo is not None:
        memo[dotted] = res
    return res


def display_id(cls, name, files, memo=None):
    """The runnable node id (path::Class::name) of a JUnit testcase; the raw classname when no file matches."""
    hit = file_for(cls, files, memo) if cls else None
    if hit:
        fp, rest = hit
        return "%s::%s::%s" % (fp, rest.replace(".", "::"), name) if rest else "%s::%s" % (fp, name)
    return "%s::%s" % (cls, name) if cls else name


def parse_junit(path, files):
    """-> (outcomes {id: passed|failed|error|skipped}, msgs {id: first line}, collection errors {file: msg}) or None."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return None
    outcomes, msgs, coll, memo = {}, {}, {}, {}
    for tc in root.iter("testcase"):
        cls, name = tc.get("classname") or "", tc.get("name") or ""
        kind, msg = "passed", ""
        for ch in tc:
            if ch.tag in ("failure", "error"):
                k = "failed" if ch.tag == "failure" else "error"
                if kind in ("passed", "skipped") or k == "failed":
                    kind = k
                    msg = (ch.get("message") or (ch.text or "").strip()).split("\n")[0]
            elif ch.tag == "skipped" and kind == "passed":
                kind = "skipped"
        if not cls and kind == "error":
            hit = file_for(name, files, memo)
            f = hit[0] if hit and not hit[1] else name.replace(".", "/") + ".py"
            coll[f] = relpaths(_coll_msg(tc) or msg or "collection failure")
            continue
        tid = display_id(cls, name, files, memo)
        outcomes[tid] = kind
        if msg:
            msgs[tid] = relpaths(msg[:600])[:300]
    return outcomes, msgs, coll


def _coll_msg(tc):
    """The most useful line of a collection error: the last 'E   ...' line of its report."""
    for ch in tc:
        if ch.tag == "error":
            lines = [ln[1:].strip() for ln in (ch.text or "").split("\n") if ln.startswith("E ")]
            if lines:
                return lines[-1][:300]
    return ""


def test_job(tree, side, files, envs, junit_name, cap_s):
    env = envs.env(tree, side)
    py = _py(env)
    junit = os.path.join(_swe(), junit_name)

    def fn(rem):
        t = min(float(cap_s), rem)
        try:
            os.unlink(junit)
        except OSError:
            pass
        t0 = time.time()
        rc, out = _sh(pytest_argv(py, files, junit), t, tree, env)
        secs = round(time.time() - t0, 2)
        return side_result(rc, out or "", junit, files, secs, t >= float(cap_s) - 0.05)
    return fn


def side_result(rc, out, junit, files, secs, full):
    r = {"status": "ok", "why": "", "outcomes": {}, "msgs": {}, "coll": {}, "secs": secs, "rc": rc}
    if rc is None:
        r.update(status="timeout" if full else "unknown", why="timed out after %ss" % int(secs + 0.5))
        return r
    if DISABLED_TEXT in out:
        r.update(status="unknown", why=DISABLED_TEXT)
        return r
    if not os.path.isfile(junit):
        r.update(status="unknown", why="no JUnit report (pytest exit %s)" % rc)
        return r
    parsed = parse_junit(junit, files)
    if parsed is None:
        r.update(status="unknown", why="unreadable JUnit report")
        return r
    r["outcomes"], r["msgs"], r["coll"] = parsed
    if rc in (2, 3, 4, 5) and not r["coll"]:
        r.update(status="unknown", why="pytest exit %s%s" % (rc, " (no tests collected)" if rc == 5 else ""))
    elif not r["outcomes"] and not r["coll"]:
        r.update(status="unknown", why="0 tests ran")
    return r


def counts(outcomes):
    c = {}
    for v in outcomes.values():
        c[v] = c.get(v, 0) + 1
    parts = ["%d %s" % (c[k], k) for k in ("passed", "failed", "error", "skipped") if c.get(k)]
    return ", ".join(parts) if parts else "0 tests"


def compare_tests(orig, cur):
    """-> dict(status ok|unknown, why, regressions [id], collects 0|1, hang_now, unknown_files)."""
    res = {"status": "ok", "why": "", "regressions": [], "collects": 1, "hang_now": False, "coll_now": {},
           "unknown_files": []}
    if cur is None or orig is None:
        res.update(status="unknown", why="no time to run the tests")
        return res
    if cur["status"] == "timeout" and orig["status"] == "ok":
        res.update(hang_now=True, why="the tests time out now but finished on original")
        return res
    if cur["status"] == "timeout" and orig["status"] == "timeout":
        res.update(status="unknown", why="the tests time out on both sides")
        return res
    if cur["status"] != "ok":
        res.update(status="unknown", why=cur["why"] or "current side unknown")
        return res
    if orig["status"] != "ok":
        res.update(status="unknown", why="original side: " + (orig["why"] or orig["status"]))
        return res
    for f, msg in cur["coll"].items():
        if f in orig["coll"]:
            res["unknown_files"].append(f)
        else:
            res["coll_now"][f] = msg
    if res["coll_now"]:
        res["collects"] = 0
    o = orig["outcomes"]
    res["regressions"] = sorted(t for t, k in cur["outcomes"].items()
                                if k in ("failed", "error") and o.get(t) == "passed")
    if not cur["outcomes"] and res["unknown_files"] and not res["coll_now"]:
        res.update(status="unknown", why="collection error on both sides: " + " ".join(res["unknown_files"][:3]))
    return res


def rerun_ids(ids, envs, deadline):
    """De-flake: re-run regressed ids once, alone, on CURRENT. -> set of ids that still fail (None: could not run)."""
    ws = C.ws()
    ids = ids[:RERUN_MAX]
    rem = min(float(C.PYTEST_SIDE), deadline - time.time())
    if rem < 2.0 or not ids:
        return None
    fn = test_job(ws, "cur", ids, envs, "j_rerun.xml", C.PYTEST_SIDE)
    with _SEM:
        r = fn(rem)
    if r["status"] != "ok":
        return None
    still = set()
    for t in ids:
        k = r["outcomes"].get(t)
        if k is None:
            base_f = t.split("::")[0]
            if base_f in r["coll"]:
                still.add(t)
            continue
        if k in ("failed", "error"):
            still.add(t)
    return still


# ----------------------------------------------------------------------------------------------------------------------
# 6. SIBLINGS (advisory)

_IMPORT_LINE = re.compile(r"^(from\s+\S+\s+)?import\s")


def _sib_line_ok(s):
    if len(s) < 12 or s in _SKIP_SIB or s.startswith("#") or _IMPORT_LINE.match(s):
        return False
    if s.startswith(('"""', "'''", 'r"""', "r'''", 'b"""', 'u"""')) or s in ('"""', "'''"):
        return False
    if not re.search(r"[\w]", s):
        return False
    return True


def siblings(facts, idx, ws=None):
    """Advisory list of the same code elsewhere: removed lines (and the calls inside them) that still occur outside the
    changed hunks, plus same-named defs in other classes or files that the change left alone. At most SIB_MAX lines."""
    ws = ws or C.ws()
    pats, calls = [], []
    for path, f in sorted(facts.items()):
        if not path.endswith(".py") or C.is_protected(path) or f.get("binary"):
            continue
        for ln in f["removed"]:
            s = ln.strip()
            if not _sib_line_ok(s):
                continue
            if s not in pats:
                pats.append(s)
            for c in _CALL.findall(s):
                if len(c) >= 16 and c not in calls and c not in pats:
                    calls.append(c)
    pats = (pats + calls)[:10]
    out, seen = [], set()
    if pats:
        args = ["grep", "-n", "-F", "-I", "-z"]
        for p in pats:
            args += ["-e", p]
        rc, data, _ = _git(args + ["--", "*.py"], 5, cwd=ws)
        for ln in _dec(data).split("\n"):
            parts = ln.split("\0")
            if len(parts) < 3:
                continue
            path, no, code = parts[0], parts[1], parts[2]
            try:
                no = int(no)
            except ValueError:
                continue
            if C.is_protected(path):
                continue
            f = facts.get(path)
            if f and no in f["added_lines"]:
                continue
            if (path, no) in seen:
                continue
            seen.add((path, no))
            out.append("  %s:%d  %s" % (path, no, code.strip()[:100]))
            if len(out) >= SIB_MAX:
                return out
    if idx is None:
        return out
    changed = []
    for path, f in sorted(facts.items()):
        if not path.endswith(".py") or C.is_protected(path) or f.get("deleted") or f.get("binary"):
            continue
        for ln in sorted(f["added_lines"])[:400]:
            try:
                sym = _sym(idx.enclosing(path, ln))
            except Exception:
                sym = None
            if sym and sym[1] in ("def", "async def") and (path, sym[0]) not in changed:
                changed.append((path, sym[0]))
    done = set()
    for path, qn in changed:
        name = qn.rsplit(".", 1)[-1]
        if len(name) < 4 or (name.startswith("__") and name.endswith("__")) or name in done:
            continue
        done.add(name)
        try:
            defs = [(p, _sym(x)) for p, x in idx.defs_named(name)]
        except Exception:
            continue
        others = []
        for p, x in defs:
            if (p, x[0]) in changed or C.is_protected(p) or "def" not in x[1]:
                continue
            ff = facts.get(p)
            if ff and any(x[2] <= ln <= x[3] for ln in ff["added_lines"]):
                continue
            others.append((p, x))
        if not others or len(others) > 4:
            continue
        for p, x in others:
            if (p, x[2]) in seen:
                continue
            seen.add((p, x[2]))
            out.append("  %s:%d  %s %s (same name as your changed %s)" % (p, x[2], x[1], x[0], qn))
            if len(out) >= SIB_MAX:
                return out
    return out


# ----------------------------------------------------------------------------------------------------------------------
# 7. SPEC GAPS (advisory, static)

def _src_grep(words, ws, fixed=True, word=True):
    if not words:
        return []
    args = ["grep", "-n", "-I", "-z"] + (["-F"] if fixed else []) + (["-w"] if word else [])
    for w in words:
        args += ["-e", w]
    rc, data, _ = _git(args + ["--", "*.py"], 5, cwd=ws)
    hits = []
    for ln in _dec(data).split("\n"):
        parts = ln.split("\0")
        if len(parts) >= 3 and not C.is_protected(parts[0]):
            hits.append((parts[0], parts[1], parts[2]))
    return hits


def spec_gaps(new_names, messages, idx, ws=None):
    ws = ws or C.ws()
    out = []
    tops = repo_tops(ws)

    def defs(name, kind=None):
        if idx is None:
            return []
        try:
            r = [(p, _sym(s)) for p, s in idx.defs_named(name)]
        except Exception:
            return []
        return [(p, s) for p, s in r if not C.is_protected(p) and (kind is None or s[1] == kind)]

    for raw in new_names:
        if len(out) >= GAP_MAX:
            break
        n, _, mod = raw.partition("@")
        if mod and mod.split(".")[0] not in tops:
            continue
        m = re.match(r"^([\w.]+)\((\w+)=?\)$", n)
        if m:
            fname, p = m.group(1).split(".")[-1], m.group(2)
            for pp, sym in [(pp, x) for pp, x in defs(fname) if "def" in x[1]]:
                params = [str(x) for x in (sym[4] or ())]
                names = [x.lstrip("*") for x in params]
                if p not in names and not any(x.startswith("**") for x in params):
                    out.append("  new parameter %s= missing in %s %s (L%d)" % (p, pp, sym[0], sym[2]))
                    if len(out) >= GAP_MAX:
                        break
            continue
        if "." in n:
            cls, attr = n.rsplit(".", 1)
            cls = cls.split(".")[-1]
            cds = defs(cls, "class")
            if not cds:
                continue
            found = False
            rx = re.compile(r"^\s*(?:async\s+)?def\s+%s\b|^\s*%s\s*[:=]|self\.%s\s*[:=]|^\s*%s\s*,|\b%s\s*=\s*property\b"
                            % ((re.escape(attr),) * 5), re.M)
            for pp, s in cds:
                try:
                    with open(os.path.join(ws, pp), "rb") as f:
                        lines = f.read().decode("utf-8", "replace").split("\n")
                except OSError:
                    continue
                if rx.search("\n".join(lines[s[2] - 1:s[3]])):
                    found = True
                    break
            if not found:
                pp, s = cds[0]
                out.append("  %s is missing in class %s (%s L%d)" % (attr, cls, pp, s[2]))
            continue
        if not re.match(r"^\w+$", n):
            continue
        if defs(n):
            continue
        hits = _src_grep([n], ws)
        rx = re.compile(r"^\s*%s\s*[:=](?!=)|\bimport\b.*\b%s\b|\bas\s+%s\b|^\s*(?:async\s+)?def\s+%s\b|^\s*class\s+%s\b"
                        % ((re.escape(n),) * 5))
        if not any(rx.search(code) for _, _, code in hits):
            out.append("  new name %s is not defined in the source yet" % n)
    for msg in messages:
        if len(out) >= GAP_MAX:
            break
        frags = [x.strip(" :;,.-") for x in re.split(r"\{[^{}]*\}|%[-#0 +]*\d*(?:\.\d+)?[sdrfxi]|[\"']", msg)]
        frags = [x for x in frags if x]
        probe = [msg] if len(msg) >= 12 else []
        longest = max(frags, key=len) if frags else ""
        if len(longest) >= 12 and longest != msg:
            probe.append(longest)
        if not probe:
            continue
        hits = _src_grep(probe, ws, fixed=True, word=False)
        if not hits:
            out.append('  message "%s" is not in the source yet' % msg[:70])
    return out[:GAP_MAX]


# ----------------------------------------------------------------------------------------------------------------------
# 8. score and key

def make_score(nonempty_, imports_ok, collects, no_hang, fixed, broke, regressions, valid, quick=False):
    fb = (fixed - broke) if valid else 0
    s = [int(bool(nonempty_)), int(bool(imports_ok)), int(bool(collects)), int(bool(no_hang)), int(fb)]
    if not quick:
        s.append(-int(regressions))
    return s


def score_key(repro_sha, files):
    return sha1("%s|%s" % (repro_sha or "", " ".join(sorted(files or []))))


def evidence(imp, summ):
    """What a score rests on, stored with its checkpoint (SPEC 4.10): classes {claim: class}; imp_def, whether an
    import failure is definite (a syntax error, a full-length hang, or compared with the original); incomplete, when
    the score may understate the tree (a claim UNKNOWN, the import check skipped or stopped for time, or an import
    failure never compared with the original). An incomplete score must not decide a restore on its own."""
    imp = imp or {"ok": True}
    classes = {str(i): k for i, k in ((summ or {}).get("classes") or {}).items() if k is not None}
    ok = imp.get("ok")
    imp_def = ok is not False or bool(imp.get("syntax") or imp.get("hang") or imp.get("base_checked"))
    incomplete = ok is None or not imp_def or any(k == "UNKNOWN" for k in classes.values())
    return {"classes": classes, "imp_def": bool(imp_def), "incomplete": bool(incomplete)}


# ----------------------------------------------------------------------------------------------------------------------
# full evaluation (verify's pipeline; finalize's quick evaluation)

def evaluate(quick=False, extra_tests=(), deadline=None, run_tests=True, advice=True, repro_only=False,
             diff=None, ch=None, pytest_cap=None):
    """One pass of the gate: import check, then claims (current, and original unless cached) and tests (discovery plus
    both sides, original cached per file set) sharing MAX_PAR processes, then SIBLINGS/SPEC GAPS and the score.
    Returns a dict the callers format; child failures never raise."""
    t_begin = time.time()
    deadline = deadline or t_begin + budget(C.VERIFY_TOTAL)
    ws = C.ws()
    envs = _Env()
    ch = ch if ch is not None else changes()
    diff = C.diff_bytes() if diff is None else diff
    ne = nonempty(ch)
    R = {"nonempty": ne, "changes": ch, "diff": diff, "diff_sha": sha1(diff), "quick": bool(quick or repro_only),
         "import": None, "repro": None, "tests": None, "siblings": [], "gaps": [], "files": []}
    facts = diff_facts(diff)
    R["facts"] = facts
    src = [p for p in ch["source"] if p.endswith(".py")]
    text = repro_text()
    rsha = sha1(text) if text.strip() else ""
    cl, hnew, hmsg = [], [], []
    if rsha:
        _, cl, hnew, hmsg = _parse(text)
    orig_cached = {}
    if rsha:
        orig_cached = {int(k): v for k, v in (((claims_state(rsha) or {}).get("orig")) or {}).items()}
    todo = [c for c in cl if c.idx not in orig_cached]
    want_tests = bool(run_tests and not quick and not repro_only and ne)
    base = base_tree() if ne and (todo or want_tests) else None
    orig_tree = base if ne else ws
    if ne:
        if deadline - time.time() < PHASE_MIN:
            R["import"] = {"ok": None, "note": "UNKNOWN (no time)", "origins": {}, "outside": {}}
        else:
            R["import"] = import_check(src, envs, deadline, base)
    imp = R["import"] or {"ok": True}
    runnable = imp.get("ok") is not False
    jobs = []
    if rsha and runnable:
        cdl = min(deadline, time.time() + C.real_budget(C.CLAIMS_TOTAL))
        if todo and orig_tree:
            jobs += claim_jobs("orig", orig_tree, todo, rsha, envs, cdl)
        if ne:
            jobs += claim_jobs("cur", ws, cl, rsha, envs, cdl)
    idx = None
    tests = None
    cap_s = float(pytest_cap or C.PYTEST_SIDE)
    if want_tests and runnable and deadline - time.time() < PHASE_MIN:
        tests = {"status": "unknown", "why": "no time", "files": []}
    elif want_tests and runnable:
        mask, why = pytest_mask(envs)
        idx = _load_index(min(5.0, max(0.5, deadline - time.time() - 10)))
        files = discover(ch["source"] + ch["deleted"], extra_tests, facts, idx, ws)
        R["files"] = files
        if mask != "ok":
            tests = {"status": "unavailable", "why": why or mask, "files": files}
        elif not files:
            tests = {"status": "none", "why": "", "files": []}
        else:
            fkey = sha1("\0".join(sorted(files)))
            ocache = ((C.state_load() or {}).get("orig_tests") or {}).get(fkey)
            tests = {"status": "pending", "files": files, "fkey": fkey, "orig_cached": ocache}
            tdl = min(deadline, time.time() + C.real_budget(max(cap_s, C.PYTEST_SIDE)) + 1)
            hang_bug = any((v or {}).get("status") == "HANG" for v in orig_cached.values())
            ocap = min(cap_s, HANG_ORIG_CAP) if hang_bug else cap_s    # a hang bug hangs the original tests too
            if ocache is None and base:
                jobs.append((("test", "orig"), test_job(base, "orig", files, envs, "j_orig.xml", ocap), tdl))
            jobs.append((("test", "cur"), test_job(ws, "cur", files, envs, "j_cur.xml", cap_s), tdl))
    elif ne and run_tests and not repro_only and quick:
        tests = {"status": "skipped", "why": "quick mode", "files": []}
    snaps = {}
    if jobs:
        for tree in {orig_tree, ws}:
            if tree:
                snaps[tree] = untracked_snapshot(tree)
    raw = run_jobs(jobs, deadline - 0.3) if jobs else {}
    for tree, snap in snaps.items():
        cleanup_tree(tree, snap, tree != ws)
    if rsha:
        tops_o = repo_tops(orig_tree) if orig_tree else set()
        tops_all = tops_o | repo_tops(ws)
        orig = dict(orig_cached)
        for c in todo:
            if not orig_tree:
                orig[c.idx] = {"status": "UNKNOWN", "sig": "base copy unavailable", "broken": None, "hint": None}
            elif not runnable:
                orig[c.idx] = {"status": "UNKNOWN", "sig": "not run (import error)", "broken": None, "hint": None}
            else:
                orig[c.idx] = interpret(raw.get(("claim", "orig", c.idx)), "orig", c, cl, tops_o, tops_all, envs)
        new_names = list(hnew)
        for n in new_from_sigs(orig):
            if n not in new_names:
                new_names.append(n)
        store_orig(rsha, orig, new_names, hmsg)
        cur = None
        if ne:
            if runnable:
                cur = {c.idx: interpret(raw.get(("claim", "cur", c.idx)), "cur", c, cl, tops_o, tops_all, envs)
                       for c in cl}
            else:
                cur = {c.idx: {"status": "UNKNOWN", "sig": "not run (import error)", "broken": None, "hint": None}
                       for c in cl}
        R["repro"] = {"sha": rsha, "claims": cl, "orig": orig, "cur": cur, "new_names": new_names, "messages": hmsg,
                      "summary": claim_summary(cl, orig, cur)}
    if tests is not None and tests.get("status") == "pending":
        cur_r = raw.get(("test", "cur"))
        orig_r = tests.get("orig_cached")
        ran_orig = orig_r is None
        if ran_orig:
            orig_r = raw.get(("test", "orig")) if base else {
                "status": "unknown", "why": "base copy unavailable", "outcomes": {}, "msgs": {}, "coll": {}, "secs": 0}
            if orig_r is not None and orig_r.get("status") in ("ok", "timeout") and \
                    len(orig_r.get("outcomes") or {}) <= 4000:
                keep = {"status": orig_r["status"], "why": orig_r.get("why", ""), "outcomes": orig_r["outcomes"],
                        "coll": orig_r.get("coll") or {}, "secs": orig_r.get("secs", 0), "at": time.time()}

                def fn(s, fkey=tests["fkey"], keep=keep):
                    ot = dict(s.get("orig_tests") or {})
                    ot[fkey] = keep
                    for old in sorted(ot, key=lambda k: float((ot[k] or {}).get("at") or 0))[:-ORIG_TESTS_KEEP]:
                        del ot[old]                   # state.json is read by every helper call: keep it small
                    s["orig_tests"] = ot
                _upd(fn)
        cmp_ = compare_tests(orig_r, cur_r)
        if cmp_["regressions"] and not cmp_["hang_now"]:
            head = cmp_["regressions"][:RERUN_MAX]
            still = rerun_ids(head, envs, deadline - 0.3)
            if still is not None:
                cmp_["flaky"] = [t for t in head if t not in still]
                cmp_["regressions"] = [t for t in cmp_["regressions"] if t in still or t not in head]
        tests.update(cmp_)
        tests["orig_res"], tests["cur_res"] = orig_r, cur_r
        tests["secs"] = max([float((cur_r or {}).get("secs") or 0)] +
                            ([float((orig_r or {}).get("secs") or 0)] if ran_orig else []))
    R["tests"] = tests
    if advice and ne and not repro_only and runnable and deadline - time.time() >= PHASE_MIN:
        if idx is None:
            idx = _load_index(min(3.0, max(0.5, deadline - time.time() - 1)))
        try:
            R["siblings"] = siblings(facts, idx, ws)
        except Exception:
            R["siblings"] = []
        rp = R.get("repro") or {}
        try:
            R["gaps"] = spec_gaps(rp.get("new_names") or [], rp.get("messages") or [], idx, ws)
        except Exception:
            R["gaps"] = []
    rp = R.get("repro") or {}
    summ = rp.get("summary") or {"valid": [], "fixed": 0, "broke": 0, "classes": {}}
    t = R["tests"] or {}
    tok = t.get("status") == "ok"
    regs = len(t.get("regressions") or []) if tok else 0
    collects = t.get("collects", 1) if tok else 1
    cur = rp.get("cur") or {}
    hang = bool(t.get("hang_now")) or bool(imp.get("hang")) or any(
        (cur.get(i) or {}).get("status") == "HANG" for i, k in summ["classes"].items() if k in ("STILL HANGS", "BROKE"))
    R["score"] = make_score(ne, imp.get("ok") is not False, collects, not hang, summ["fixed"], summ["broke"], regs,
                            bool(summ["valid"]), quick=R["quick"])
    R.update(evidence(imp, summ))
    R["key"] = score_key(rsha, R["files"])
    R["rkey"] = score_key(rsha, [])
    R["secs"] = round(time.time() - t_begin, 2)
    return R


# v10.1 (R89b): next-step lines name a helper only as its full command.
EDIT_CMD = "python3 /tmp/swe/edit.py"
VERIFY_CMD = "python3 /tmp/swe/verify.py"
READY_NEXT = "NEXT: ready. Fixer: reply with your notes. Verifier: run python3 /tmp/swe/finalize.py."
# Lever A (docs/v10/v10_1_diag_5.md 4.A, make_variant --flip): AMBER without a claim that fails on original is not
# "ready" for the fixer before FINISH (race 2: 23 of 26 AMBER tasks; flipping claims went with 19/36 solved on
# feasible tasks against 6/20). The claim guides the fix and never vetoes it. No new repro from T_FINISH on.
FLIP_NEXT = ('NEXT: no claim fails on original yet, so nothing checks this change. Fixer: write the reproduction '
             "now with python3 /tmp/swe/verify.py --repro-only <<'EOF' ... EOF, a # CLAIM 1: line before each "
             "behaviour's asserts, with the issue's literal inputs, failing on original: one claim per behaviour, "
             'the return value included; for a rule that must hold everywhere, loop over every position and '
             'example input (wide and zero-width characters too). Then run python3 /tmp/swe/verify.py again. A '
             'claim that still fails means change the code, not the claim. Verifier: run '
             'python3 /tmp/swe/finalize.py.')
FLIP_REASONS = ("no reproduction saved", "the reproduction passes on original")


def _before_finish():
    try:
        return float(C.clock()) < C.T_FINISH
    except Exception:
        return False


def verdict(R):
    """-> (line1, next_line, word). The table of SPEC 4.11, first matching row."""
    imp = R.get("import") or {"ok": True}
    rp = R.get("repro") or {}
    summ = rp.get("summary") or {"valid": [], "fixed": 0, "broke": 0, "classes": {}, "text": "0/0 claims fixed"}
    t = R.get("tests") or {"status": "skipped" if R.get("quick") else "none", "why": "quick evaluation"}
    if not R.get("nonempty"):
        return ("VERIFY: NO SOURCE CHANGE - make the plan's change with %s first." % EDIT_CMD,
                "NEXT: make the plan's change with %s, then run %s again." % (EDIT_CMD, VERIFY_CMD), "EMPTY")
    if imp.get("ok") is False:
        where = imp.get("where") or imp.get("module") or "the changed module"
        return ("VERIFY: RED - import error",
                "NEXT: fix the error at %s with %s, then run %s again." % (where, EDIT_CMD, VERIFY_CMD), "RED")
    bad = [i for i in summ["valid"] if summ["classes"].get(i) in ("STILL FAILS", "STILL HANGS")]
    bad += [i for i, k in sorted(summ["classes"].items()) if k == "BROKE"]
    if bad:
        i = bad[0]
        r = (rp.get("cur") or {}).get(i) or {}
        sig = r.get("sig") or ("hangs" if r.get("status") == "HANG" else "fails")
        return ("VERIFY: RED - %s" % summ["text"],
                "NEXT: claim %d still fails (%s). Fix the code, then run %s again." % (i, sig[:110], VERIFY_CMD), "RED")
    if t.get("status") == "ok" and (t.get("regressions") or t.get("collects") == 0) or t.get("hang_now"):
        if t.get("hang_now"):
            nxt = ("NEXT: the tests finished on original but time out now: look for an endless loop in your change, "
                   "then run %s again." % VERIFY_CMD)
        elif t.get("collects") == 0 and not t.get("regressions"):
            f, msg = sorted(t["coll_now"].items())[0]
            nxt = "NEXT: %s no longer collects (%s). Fix the code, then run %s again." % (f, msg[:100], VERIFY_CMD)
        else:
            nxt = REGRESSION_NOTE
        return ("VERIFY: RED - regressions", nxt, "RED")
    tests_ok = t.get("status") in ("ok", "none")
    outside = (imp.get("outside") or {})
    ready = READY_NEXT
    if summ["valid"] and summ["fixed"] == len(summ["valid"]) and tests_ok and not outside and not imp.get("pre"):
        return ("VERIFY: GREEN", ready, "GREEN")
    if outside:
        k, v = sorted(outside.items())[0]
        reason = "%s is imported from outside the workspace (%s)" % (k, v[:80])
    elif imp.get("pre"):
        reason = "import fails on original too"
    elif not rp:
        reason = "no reproduction saved"
    elif not summ["valid"]:
        if any(k == "BROKEN" for k in summ["classes"].values()):
            reason = "the reproduction is broken"
        elif any(k == "INVALID" for k in summ["classes"].values()):
            reason = "the reproduction passes on original"
        else:
            reason = "claims unknown"
    elif summ["fixed"] < len(summ["valid"]):
        reason = "some claims unknown (no time)"
    elif t.get("status") == "skipped":
        reason = "tests skipped (quick mode)"
    elif t.get("status") == "unavailable":
        reason = "tests unavailable"
    else:
        reason = "tests unknown (%s)" % (t.get("why") or "no result")[:80]
    if reason in FLIP_REASONS and _before_finish():
        ready = FLIP_NEXT
    return "VERIFY: AMBER - %s" % reason, ready, "AMBER"


REGRESSION_NOTE = ("If a test asserts the OLD behaviour that the issue asks to change, keep your fix (the graders update "
                   "such tests). Otherwise your change broke it: fix the code.")
