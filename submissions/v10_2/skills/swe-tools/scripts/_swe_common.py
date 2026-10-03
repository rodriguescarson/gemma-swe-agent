"""swe-tools v10 shared library (v10.2): paths, clock, arguments, stdin, subprocesses, output, git, hygiene and state.

Stdlib only, Python 3.8 syntax. Imported by every helper right after the preamble; never run on its own. Everything
that depends on the environment is computed lazily and cached per process, so importing this module costs little.
"""
import os
import re
import sys
import time
import json

# ---------------------------------------------------------------------------------------------------------- constants
VERSION = "v10.2"
DOCKER_TMP = os.environ.get("SWE_DOCKER_TMP_FOR_TESTS") or "/tmp"
DOCKER_WS = os.environ.get("SWE_DOCKER_WS_FOR_TESTS") or "/workspace"
DISPLAY_SWE = "/tmp/swe"
# The subprocess sandbox rewrites these prefixes in COMMAND TEXT (subprocess.py:432-481); unrewrite() maps them back.
# They are display text for that inverse mapping, never opened as paths.
SANDBOX_REWRITES = (("venv/bin", "/usr/local/bin"), ("workspace", "/workspace"), ("wheels", "/wheels"), ("tmp", "/tmp"))

CAP_S = 300; T_LOCATOR = 75; T_EDIT_NOW = 150; T_FINISH = 210; T_QUICK = 235; T_TIME = 250; T_SAFE = 255
T_VERIFY_END = 262; T_EVAL_END = 272; T_NO_EVAL = 275; T_NO_RESTORE = 285
# End-game plan: every verify.py run ends by T_VERIFY_END; finalize's quick evaluation and verify --repro-only end by
# T_EVAL_END (T_NO_EVAL - 3), so finalize can still restore (< T_NO_RESTORE) and the patch is submitted before CAP_S.
# verify switches to quick mode at T_QUICK, or earlier when clock + 1.2 x last test secs + QUICK_PAD passes
# T_VERIFY_END (QUICK_PAD covers the import check and the claims).
QUICK_PAD = 15
RUN_DEFAULT = 20; RUN_MAX = 90; VIEW_OBJ = 15; LOCATE_PARSE = 15; ORIGIN_PROBE = 5; VERIFY_TOTAL = 60
IMPORT_CHECK = 10; CLAIM_TIMEOUT = 10; CLAIMS_TOTAL = 25; PYTEST_SIDE = 40; FINALIZE_QUICK = 12; MAX_PAR = 2
CAPS = {"install": 400, "locate": 1800, "grep": 1800, "view": 2800, "edit": 1500, "run": 2500,
        "verify": 2000, "finalize": 1400, "status": 2200}   # finalize 1,000 -> 1,400 in v10.1 (EDIT TARGET)
# Output is also capped by ESTIMATED tokens (est_tokens: ASCII chars / 3 + non-ASCII chars x 2.7), so rendered tables
# and box drawing (0.36-0.63 chars/token measured) cannot spend 3x a helper's budget. ASCII output never hits these.
CAP_TOKENS = {k: v // 3 for k, v in CAPS.items()}
# Context meter (state["ctx"]): estimated tokens that the current stage's tool calls added to its prompt (output,
# model-written input, CTX_CALL per call). At CONTEXT_TOKENS the footer shows CONTEXT_HINT. tests/test_v10_prompts.py
# (R95) derives the value: with a p95 statement, the measured p90 handoff and CONTEXT_TOKENS at 2.3 chars/token, the
# fixer stays 1,000 tokens under the 14,336 compaction line (review round 2: 5,500 left 144 tokens at a 120-word plan
# and crossed it at the measured median plan), and a first fixer round at measured sizes (3 views, 3 edits of 256
# model-written tokens, the race-1 p90, 1 verify: about 4,600) stays below it.
CONTEXT_TOKENS = 4600         # v10.2 (F3): 4,700 -> 4,600; the fixer's first round now starts with status.py
CTX_CALL = 30
GIT_TIMEOUT = 10
HELPER_LIMIT = 110          # whole-helper watchdog (s), always clamped by real_budget; timeout_seconds is 180 (was 120)
# v10.2 (docs/v10/SPEC_v10_2.md 5.0): the locator budget, enforced by the helpers. The locator phase is open while the
# context meter's phase is "locator"; it ends at the first status.py or edit.py call (5.1).
LOC_MAX_CALLS = 14          # gated helper calls the locator phase may run (the 15th is refused)
T_LOC_CLOSE = 90            # helper t at which the locator phase closes (reply by t=90s in the prompt)
LOC_MAX_RUNS = 3            # run.py commands executed in the locator phase
LOC_MAX_REPROS = 2          # new reproductions (--repro-only with text) in the locator phase
STATUS_START_CAP = 800      # chars of the phase-start status output (LOCATOR DIGEST)
REFUSAL_CAP = 600           # LOCATOR CLOSED, PROBE LIMIT, REPRO LIMIT, SAME RUN, OFFLINE, PYTHON -c, NO INPUT (5.9)
BUDGET_SCALE = 1.0          # 300/330 only in the make_variant --cap 5.5 variant (R6): helper time = real time x this
BASE_MAX_MB = 300           # tracked baseline size above which no base worktree is made (R4)
GATED = ("locate", "grep", "view", "run", "repro")

_SH_MAX = 4 << 20           # merged child output kept by sh(), bytes
_STDIN_MAX = 32 << 20       # read_stdin() safety cap, bytes
_TAG = "_swegemma_baseline"
_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
_HEX = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
_HERE = os.path.dirname(os.path.abspath(__file__))
_GIT_OPTS = ["-c", "safe.directory=*", "-c", "gc.auto=0"]
_CACHE = {}
_LIVE = set()               # process groups of running children, killed by safe_main on any exit
_LOG_PARTS = []             # full texts of sections cut by cap(), written to last.log

# Hint and next-step lines name a helper only as its full command, python3 /tmp/swe/NAME.py (v10.1, SPEC 4.0.10 and
# R89b): race 2 showed the model turning bare helper names into tool names (call:view.py, a parsed crash).
FINAL_HINT = ("FINAL: the patch was finalized at t=%ds; nothing more to change. The stage that can submit should "
              "submit now; any other stage should reply done.")
TIME_HINT = ("TIME: t>=250s. End your stage now; reply in one line, under 30 words (verifier: run "
             "python3 /tmp/swe/finalize.py next).")
FINISH_HINT = "FINISH: t>=210s. Stop exploring; keep the edit you have and end your stage with a short reply."
# v10.1: shown whenever the tree has no source change once t >= T_EDIT_NOW or the locator stage is over, above TIME,
# FINISH and CONTEXT: an empty tree never hears "end your stage" (race 2: fastapi_14851, 14306, 15280).
EDIT_NOW_HINT = ("EDIT NOW: no source file changed at t=%ds; an empty patch always fails. Locator: reply with your plan "
                 "now. Other stages: make the smallest plausible version of the plan's change now.")
EDIT_NOW_LATE = " Then run python3 /tmp/swe/finalize.py once."
LOCATOR_HINT = "LOCATOR: 75s used. Locator: stop and reply with your plan now. Other stages: ignore this line."
CONTEXT_HINT = ("CONTEXT: this stage's context is nearly full. Locator: reply with your plan now. Fixer: make any "
                "missing edit, then reply with your notes. Verifier: run python3 /tmp/swe/finalize.py next.")
REPEAT_NOTES = {
    "run": "NOTE: same command, same output 3 times; change something.",
    "verify": "STOP re-running verify; decide now.",
    "locate": "NOTE: 3rd locate call; stop searching and use what you have.",
    "grep": "NOTE: same search 3 times; use what you found.",
    "view": "NOTE: same view 3 times; you already have these lines.",
}


def _reset():
    """Test hook: forget every per-process cache."""
    _CACHE.clear()
    del _LOG_PARTS[:]


def _under(path, root):
    root = root.rstrip(os.sep) or os.sep
    return path == root or path.startswith(root + os.sep)


def _real(p):
    try:
        return os.path.realpath(p)
    except (OSError, ValueError):
        return os.path.abspath(p)


def sha1_hex(data):
    """sha1 hex digest of bytes or str (str encoded UTF-8, surrogates kept)."""
    if isinstance(data, str):
        data = data.encode("utf-8", "surrogateescape")
    try:
        from _sha1 import sha1          # the C builtin; avoids the ~10 ms OpenSSL import of hashlib
    except ImportError:
        from hashlib import sha1
    return sha1(data or b"").hexdigest()


def _atomic_write(path, data, mode=0o644):
    """Write bytes or str to path via a temp file and os.replace (readers never see a partial file)."""
    if isinstance(data, str):
        data = data.encode("utf-8", "surrogateescape")
    tmp = "%s.tmp.%d" % (path, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        _write_all(fd, data)
    finally:
        os.close(fd)
    try:
        os.chmod(tmp, mode)
    except OSError:
        pass
    os.replace(tmp, path)


def _write_all(fd, data):
    view = memoryview(data)
    while view:
        n = os.write(fd, view)
        view = view[n:]


# -------------------------------------------------------------------------------------------------------------- paths
def in_rewriting_sandbox():
    """True inside the harness subprocess sandbox, whose TMPDIR/TEST_TMPDIR is <root>/tmp with a swegemma_sandbox_* root."""
    return _sandbox_root() is not None


def _sandbox_root():
    for k in ("TEST_TMPDIR", "TMPDIR"):
        v = (os.environ.get(k) or "").rstrip(os.sep)
        if v and os.path.basename(v) == "tmp" and os.path.basename(os.path.dirname(v)).startswith("swegemma_sandbox_"):
            return os.path.dirname(v)
    return None


def _primary_swe():
    e = os.environ
    if e.get("SWE_DIR"):
        return os.path.abspath(e["SWE_DIR"])
    for k in ("TEST_TMPDIR", "TMPDIR"):
        if e.get(k):
            return os.path.join(os.path.abspath(e[k]), "swe")
    import tempfile
    return os.path.join(tempfile.gettempdir(), "swe")


def swe_dir():
    """The per-task helper dir: this file's dir once installed (it holds VERSION), else $SWE_DIR, $TEST_TMPDIR/swe,
    $TMPDIR/swe, then tempfile.gettempdir()/swe. Created on first use."""
    d = _CACHE.get("swe")
    if d:
        return d
    d = _HERE if os.path.isfile(os.path.join(_HERE, "VERSION")) else _primary_swe()
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    _CACHE["swe"] = d
    return d


def install_targets():
    """The primary install dir, plus DOCKER_TMP/swe when the command text is not rewritten (TEST_TMPDIR unset, not the
    rewriting sandbox, SWE_DUAL not 0, SWE_DIR unset), the path differs and DOCKER_TMP is writable."""
    prim = _primary_swe()
    out = [prim]
    e = os.environ
    if e.get("TEST_TMPDIR") or e.get("SWE_DIR") or in_rewriting_sandbox() or e.get("SWE_DUAL", "1") == "0":
        return out
    dual = os.path.join(DOCKER_TMP, "swe")
    if _real(dual) != _real(prim) and os.path.isdir(DOCKER_TMP) and os.access(DOCKER_TMP, os.W_OK):
        out.append(dual)
    return out


def _git_root(cand, sd, bounds):
    d = os.path.abspath(cand)
    rd = _real(d)
    if _under(rd, sd):
        return None
    stop = None
    for b in bounds:                    # never walk up out of TMPDIR (the skill wrapper's temp dir lives there)
        if _under(rd, b) and (stop is None or len(b) > len(stop)):
            stop = b
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            r = _real(d)
            return None if _under(r, sd) else r
        if stop is not None and _real(d) == stop:
            return None
        p = os.path.dirname(d)
        if p == d:
            return None
        d = p


def ws():
    """The repository root: $SWE_WS, else the first git root above cwd, $PWD, $SWE_PATH0, then /workspace (only when it
    has .git); paths under swe_dir() are skipped. Falls back to the cwd. Cached per process."""
    w = _CACHE.get("ws")
    if w:
        return w
    e = os.environ
    if e.get("SWE_WS") and os.path.isdir(e["SWE_WS"]):
        w = _real(e["SWE_WS"])
    else:
        sd = _real(swe_dir())
        bounds = [_real(e[k]) for k in ("TMPDIR", "TEST_TMPDIR") if e.get(k)]
        try:
            cwd = os.getcwd()
        except OSError:
            cwd = ""
        for c in (cwd, e.get("PWD"), e.get("SWE_PATH0")):
            if c:
                w = _git_root(c, sd, bounds)
                if w:
                    break
        if not w and os.path.exists(os.path.join(DOCKER_WS, ".git")) and not _under(_real(DOCKER_WS), sd):
            w = _real(DOCKER_WS)
        if not w:
            w = _real(cwd or ".")
    _CACHE["ws"] = w
    return w


def rel(path):
    """Path relative to ws() with / separators ('' when outside)."""
    r = _real(path if os.path.isabs(path) else os.path.join(ws(), path))
    w = ws()
    if not _under(r, w):
        return ""
    return os.path.relpath(r, w).replace(os.sep, "/")


def git_dir():
    g = _CACHE.get("gitdir", 0)
    if g == 0:
        p = os.path.join(ws(), ".git")
        g = p if os.path.isdir(p) else None
        _CACHE["gitdir"] = g
    return g


# ---------------------------------------------------------------------------------------------------------------- git
def _clamp(timeout):
    """timeout, cut to real_budget() once the task clock is known (never earlier: the clock itself needs git)."""
    t = max(0.1, float(timeout))
    if os.environ.get("SWE_FAKE_CLOCK") or "t0" in _CACHE:
        try:
            return min(t, real_budget(t))
        except Exception:
            pass
    return t


def git_run(args, timeout=GIT_TIMEOUT, env=None, cwd=None, input=None, quotepath_off=True):
    """Run git in ws() -> (rc | None on timeout, stdout bytes, stderr bytes). New session, killpg on timeout, no
    optional index writes (GIT_OPTIONAL_LOCKS=0)."""
    import subprocess
    argv = ["git"] + (["-c", "core.quotepath=off"] if quotepath_off else []) + _GIT_OPTS + [str(a) for a in args]
    e = dict(os.environ if env is None else env)
    e["GIT_OPTIONAL_LOCKS"] = "0"
    e["GIT_TERMINAL_PROMPT"] = "0"
    try:
        p = subprocess.Popen(argv, cwd=cwd or ws(), env=e, stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    except OSError as ex:
        return 127, b"", str(ex).encode()
    _LIVE.add(p.pid)
    try:
        try:
            out, err = p.communicate(input, timeout=_clamp(timeout))
            rc = p.returncode
        except subprocess.TimeoutExpired:
            _killpg(p.pid)
            try:
                out, err = p.communicate(timeout=2)
            except Exception:
                out, err = b"", b""
            rc = None
    finally:
        _killpg(p.pid)
        _LIVE.discard(p.pid)
    return rc, out or b"", err or b""


def git(args, timeout=GIT_TIMEOUT, env=None, cwd=None):
    """git -c core.quotepath=off <args> in ws() -> (rc | None, text). The text is stdout; on failure stderr is appended."""
    rc, out, err = git_run(args, timeout, env=env, cwd=cwd)
    text = out.decode("utf-8", "surrogateescape")
    if rc != 0:
        text += err.decode("utf-8", "replace")
    return rc, text


def _tag_sha():
    if "tag" in _CACHE:
        return _CACHE["tag"]
    sha = None
    gd = git_dir()
    if gd:
        try:
            with open(os.path.join(gd, "refs", "tags", _TAG)) as f:
                s = f.read().strip()
            if _HEX.match(s) and _loose_type(s) in (None, "commit"):
                sha = s
        except OSError:
            pass
    if sha is None:
        rc, out = git(["rev-parse", "-q", "--verify", "refs/tags/%s^{commit}" % _TAG])
        s = out.strip() if rc == 0 else ""
        sha = s if _HEX.match(s) else None
    _CACHE["tag"] = sha
    return sha


def _loose(sha):
    """(type, body) of a loose object, or None when it is packed/unreadable."""
    gd = git_dir()
    if not gd or not sha:
        return None
    try:
        import zlib
        with open(os.path.join(gd, "objects", sha[:2], sha[2:]), "rb") as f:
            raw = zlib.decompress(f.read())
        head, _, body = raw.partition(b"\0")
        return head.split(b" ")[0].decode("ascii", "replace"), body
    except Exception:
        return None


def _loose_type(sha):
    o = _loose(sha)
    return o[0] if o else None


def baseline():
    """The _swegemma_baseline commit (what the patch is diffed against); without the tag, HEAD recorded at the first
    call (kept in state.json). Cached per process."""
    b = _CACHE.get("base")
    if b:
        return b
    b = _tag_sha()
    if not b:
        st = _read_state_raw()
        if st.get("baseline") and st.get("ws") == ws():
            b = st["baseline"]
        else:
            rc, out = git(["rev-parse", "-q", "--verify", "HEAD^{commit}"])
            b = out.strip() if rc == 0 and _HEX.match(out.strip()) else _EMPTY_TREE
            _CACHE["base"] = b
            if not _CACHE.get("locked"):        # inside state_update, _fill() records it (flock is not re-entrant)
                try:
                    state_update(lambda s: None)
                except Exception:
                    pass
    _CACHE["base"] = b
    return b


def _commit_time(sha):
    o = _loose(sha)
    if o and o[0] == "commit":
        m = re.search(rb"^committer .* (\d+) [+-]\d{4}\s*$", o[1], re.M)
        if m:
            return int(m.group(1))
    if not sha or sha == _EMPTY_TREE:
        return None
    rc, out = git(["log", "-1", "--format=%ct", sha])
    try:
        return int(out.strip()) if rc == 0 else None
    except ValueError:
        return None


# -------------------------------------------------------------------------------------------------------------- clock
def clock_scale():
    """pod scale x BUDGET_SCALE, clamped to 0.2..5. The pod scale is float($SWE/clock_scale) (the pod L4 hook; never
    present on Kaggle), else 1.0. BUDGET_SCALE (v10.2, R6) is 1.0 here and 300/330 in the --cap 5.5 variant, so every
    threshold keeps its meaning in helper time while the real cap is 330 s."""
    s = _CACHE.get("scale")
    if s is None:
        pod = 1.0
        try:
            with open(os.path.join(swe_dir(), "clock_scale")) as f:
                v = float(f.read().strip())
            if v == v:                   # not NaN
                pod = v
        except (OSError, ValueError):
            pass
        s = min(5.0, max(0.2, pod * BUDGET_SCALE))
        _CACHE["scale"] = s
    return s


def _t0_file():
    """$SWE/t0, written once (by the first helper or install) and read afterwards."""
    path = os.path.join(swe_dir(), "t0")
    try:
        with open(path) as f:
            return float(f.read().strip())
    except (OSError, ValueError):
        pass
    now = time.time()
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        try:
            os.write(fd, repr(now).encode())
        finally:
            os.close(fd)
    except FileExistsError:
        try:
            with open(path) as f:
                return float(f.read().strip())
        except (OSError, ValueError):
            pass
    except OSError:
        pass
    return now


def t0():
    """Task start (epoch s): the baseline's committer time, else the tag file mtime, each only when 0-900 s ago, else
    $SWE/t0."""
    v = _CACHE.get("t0")
    if v is not None:
        return v
    now = time.time()
    tf = _t0_file()
    ct = _commit_time(baseline())
    if ct is not None and -5 <= now - ct <= 900:
        v = float(ct)
    else:
        v = None
        gd = git_dir()
        if gd:
            try:
                m = os.stat(os.path.join(gd, "refs", "tags", _TAG)).st_mtime
                if -5 <= now - m <= 900:
                    v = m
            except OSError:
                pass
        if v is None:
            v = tf
    _CACHE["t0"] = v
    return v


def clock():
    """Seconds of task time used: $SWE_FAKE_CLOCK when set, else (now - t0) * clock_scale."""
    f = os.environ.get("SWE_FAKE_CLOCK")
    if f:
        try:
            return float(f)
        except ValueError:
            pass
    return max(0.0, (time.time() - t0()) * clock_scale())


def real_budget(default_s):
    """Real seconds a helper may spend: min(default, max(1, (300 - clock)/scale - 4))."""
    return min(float(default_s), max(1.0, (CAP_S - clock()) / clock_scale() - 4.0))


# -------------------------------------------------------------------------------------------------------------- state
_HELD = set()


class _Flock(object):
    """Exclusive flock on $SWE/<name>, re-entrant within a process (flock itself is not: a second fd would block);
    a no-op where fcntl is missing."""

    def __init__(self, name="state.lock"):
        self.name, self.fd, self.outer = name, None, False

    def __enter__(self):
        if self.name in _HELD:
            return self
        self.outer = True
        _HELD.add(self.name)
        try:
            import fcntl
            self.fd = os.open(os.path.join(swe_dir(), self.name), os.O_RDWR | os.O_CREAT, 0o644)
            fcntl.flock(self.fd, fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass
        return self

    def __exit__(self, *exc):
        if not self.outer:
            return False
        _HELD.discard(self.name)
        self.outer = False
        if self.fd is not None:
            try:
                import fcntl
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            except (ImportError, OSError):
                pass
            os.close(self.fd)
            self.fd = None
        return False


def _loc_defaults():
    return {"calls": 0, "runs": 0, "repros": 0, "refused": 0, "close_t": None, "close_why": None}


def _defaults():
    # v10.2 (SPEC_v10_2 5.12): loc (the locator budget), locate_top (the digest's ranking), vsince (full verify calls
    # since the last status.py), t_import / t_import_mods (R1 calibration) and runs (SAME RUN keys).
    return {"version": VERSION, "ws": None, "baseline": None, "t0": None, "final_done": False, "final_sha": None,
            "final_t": None, "origin": {}, "base": {}, "memo": {}, "repeats": {}, "repro": {}, "orig_tests": {},
            "last_test_secs": None, "pytest_mask": None, "ckpts": [], "edits": [], "views": {}, "locate_calls": 0,
            "loc": _loc_defaults(), "locate_top": [], "vsince": 0, "t_import": None, "t_import_mods": [], "runs": {}}


def _with_defaults(st):
    d = _defaults()
    for k, v in d.items():
        if k not in st or (isinstance(v, (dict, list)) and not isinstance(st.get(k), type(v))):
            st[k] = v
    loc = st["loc"]
    for k, v in _loc_defaults().items():             # a partial or hand-edited loc dict loads too
        if k not in loc or (k in ("calls", "runs", "repros", "refused") and not isinstance(loc.get(k), int)):
            loc[k] = v
    if not isinstance(st.get("vsince"), int) or isinstance(st.get("vsince"), bool):
        st["vsince"] = 0
    return st


def _read_state_raw():
    try:
        with open(os.path.join(swe_dir(), "state.json"), "rb") as f:
            st = json.loads(f.read().decode("utf-8", "replace"))
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


def _mismatch(st):
    if st.get("ws") and st["ws"] != ws():
        return True
    tag = _tag_sha()
    return bool(tag and st.get("baseline") and st["baseline"] != tag)


def _reset_task_files():
    """A different task (ws or baseline changed): drop state, journal, caches, repro and checkpoints."""
    import shutil
    sd = swe_dir()
    try:
        names = os.listdir(sd)
    except OSError:
        return
    drop = {"state.json", "journal.jsonl", "repro.py", "idx", "j_orig.xml", "j_cur.xml", "t0", GUARD_STAT}
    for n in names:
        p = os.path.join(sd, n)
        if n in drop or n.startswith("index_") and n.endswith(".marshal"):
            try:
                os.remove(p)
            except OSError:
                pass
        elif n in ("claims", "ckpt", "base", "rt_orig", "rt_cur"):
            shutil.rmtree(p, ignore_errors=True)
    for k in ("t0", "scale"):
        _CACHE.pop(k, None)


def _fill(st):
    if not st.get("ws"):
        st["ws"] = ws()
    if not st.get("baseline"):
        st["baseline"] = baseline()
    if st.get("t0") is None and not os.environ.get("SWE_FAKE_CLOCK"):
        try:
            st["t0"] = round(t0(), 3)
        except Exception:
            pass
    return st


def state_load():
    """The task state (section 4.16 schema, defaults filled). A state from another ws/baseline is reset first."""
    st = _read_state_raw()
    if st and _mismatch(st):
        return state_update(lambda s: None)
    return _with_defaults(st)


def state_update(fn):
    """Load, fn(state) (mutate in place or return a new dict), write atomically, all under flock. Returns the state."""
    with _Flock():
        _CACHE["locked"] = True
        try:
            st = _read_state_raw()
            if st and _mismatch(st):
                _reset_task_files()
                st = {}
            st = _with_defaults(st)
            r = fn(st)
            if isinstance(r, dict):
                st = _with_defaults(r)
            _fill(st)
            _atomic_write(os.path.join(swe_dir(), "state.json"), json.dumps(st, default=str, sort_keys=True))
        finally:
            _CACHE["locked"] = False
    return st


VIEWS_KEPT = 60                      # per file, as view.py keeps them


def record_views(items, derived=True):
    """Record line ranges this helper just PRINTED with their current numbers (grep hits, locate symbol spans, verify
    SIBLINGS and IMPORT file:line) as views in state["views"], one state update for all: edit.py's STALE guard then
    sees that numbers taken from this output are current. items: (rel path, a, b). Derived views carry a 4th field "d"
    (a line seen in a search result rather than a view.py range); edit.py treats them as weaker evidence."""
    rows = {}
    for rel, a, b in items or ():
        try:
            a, b = int(a), int(b)
        except (TypeError, ValueError):
            continue
        if rel and 0 < a <= b:
            rows.setdefault(str(rel), []).append((a, b))
    if not rows:
        return
    t = round(float(clock()), 1)

    def fn(s):
        vv = s.get("views")
        if not isinstance(vv, dict):
            vv = s["views"] = {}
        for rel, spans in rows.items():
            lst = vv.get(rel)
            if not isinstance(lst, list):
                lst = vv[rel] = []
            seen = set()
            for a, b in spans:
                if (a, b) not in seen:
                    seen.add((a, b))
                    lst.append([a, b, t, "d"] if derived else [a, b, t])
            del lst[:-VIEWS_KEPT]
        return s
    try:
        state_update(fn)
    except Exception:
        pass


# ------------------------------------------------------------------------------------------------------------ journal
def journal(event):
    """Append one JSON line to $SWE/journal.jsonl (t = task seconds added when absent)."""
    ev = dict(event or {})
    if "t" not in ev:
        try:
            ev["t"] = round(clock(), 1)
        except Exception:
            ev["t"] = None
    line = (json.dumps(ev, ensure_ascii=False, default=str) + "\n").encode("utf-8", "replace")
    try:
        fd = os.open(os.path.join(swe_dir(), "journal.jsonl"), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
    except OSError:
        pass


def journal_entries(max_bytes=262144):
    """Parsed journal entries from the last max_bytes of the file (oldest first)."""
    try:
        with open(os.path.join(swe_dir(), "journal.jsonl"), "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            data = f.read().decode("utf-8", "replace")
    except OSError:
        return []
    lines = data.split("\n")
    if size > max_bytes:
        lines = lines[1:]
    out = []
    for ln in lines:
        if ln.strip():
            try:
                e = json.loads(ln)
            except ValueError:
                continue
            if isinstance(e, dict):
                out.append(e)
    return out


def _short(s, n):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n - 3] + "..."


def render_event(e):
    """One short line for a journal entry (prefers its 'msg')."""
    h = str(e.get("h") or "?")
    t = e.get("t")
    ts = "t=%ds " % int(t) if isinstance(t, (int, float)) else ""
    if e.get("msg"):
        body = str(e["msg"])
        if not body.startswith(h):
            body = "%s: %s" % (h, body)
    elif h == "edit":
        body = "edit %s %s" % (e.get("file", "?"), "OK" if e.get("ok") else "FAILED")
        if e.get("tier"):
            body += " (%s)" % e["tier"]
        if e.get("start") is not None and e.get("end") is not None:
            body += " lines %s-%s" % (e["start"], e["end"])
        if isinstance(e.get("delta"), int) and e["delta"]:
            body += " (%+d)" % e["delta"]
        if not e.get("ok") and e.get("why"):
            body += " %s" % e["why"]
    elif h == "locate" and e.get("files") is not None:
        body = "locate: %s files%s" % (e["files"], " (top %s)" % e["top"] if e.get("top") else "")
    elif e.get("first"):
        body = "%s: %s" % (h, e["first"])
    elif e.get("verdict"):
        body = "%s: %s" % (h, e["verdict"])
    else:
        kv = ["%s=%s" % (k, v) for k, v in sorted(e.items()) if k not in ("h", "t", "ts") and isinstance(v, (str, int, float, bool))]
        body = "%s: %s" % (h, " ".join(kv)) if kv else h
    return _short(ts + body, 140)


def jtail(n=8):
    """Rendered last n journal entries (list of str)."""
    return [render_event(e) for e in journal_entries()[-n:]] if n > 0 else []


def repeat_note(helper, key):
    """Count sha1(helper, key) in state.repeats; from the third time on return the helper's repeat note, else ''."""
    k = sha1_hex("%s\0%s" % (helper, key))[:16]
    box = {}

    def bump(s):
        s["repeats"][k] = int(s["repeats"].get(k) or 0) + 1
        box["n"] = s["repeats"][k]
    try:
        state_update(bump)
    except Exception:
        return ""
    if box.get("n", 0) >= 3:
        return REPEAT_NOTES.get(helper, "NOTE: same %s call, same result 3 times; change something." % helper)
    return ""


# ---------------------------------------------------------------------------------------------------------- arguments
class UsageError(Exception):
    """Bad command line; safe_main prints the message (one line) and the script exits 0."""


class Span(tuple):
    """An inclusive line range (A, B) parsed from 'A-B'; str() gives 'A-B'."""

    def __new__(cls, a, b):
        return tuple.__new__(cls, (a, b))

    def __str__(self):
        return "%d-%d" % (self[0], self[1])

    def split(self, *a, **k):
        return str(self).split(*a, **k)


class Args(dict):
    """parse_args result: a dict keyed by flag name (dash form) that also answers to the underscore form and to
    attribute access. Extra keys: '_' (unassigned positionals), '_given' (names set on the command line), '_notes',
    '_bad' (raw values that did not convert), '_unknown' (ignored unknown flags when strict=False)."""

    @staticmethod
    def _k(k):
        return k.replace("_", "-") if isinstance(k, str) and not k.startswith("_") else k

    def __getitem__(self, k):
        return dict.__getitem__(self, self._k(k))

    def __setitem__(self, k, v):
        dict.__setitem__(self, self._k(k), v)

    def __contains__(self, k):
        return dict.__contains__(self, self._k(k))

    def get(self, k, d=None):
        return dict.get(self, self._k(k), d)

    def pop(self, k, *d):
        return dict.pop(self, self._k(k), *d)

    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError:
            raise AttributeError(k)


_FLAG = re.compile(r"^--([A-Za-z][A-Za-z0-9_-]*)(?:=(.*))?$", re.S)
_BOOLS = {"1": True, "true": True, "yes": True, "on": True, "0": False, "false": False, "no": False, "off": False}
_INT = re.compile(r"^\s*([+-]?\d+)(?:\.0*)?\s*s?\s*$")
_RANGE = re.compile(r"^\s*L?(\d+)\s*(?:(?:-|:|,|\.\.|\s+|to)\s*L?(\d+))?\s*$", re.I)


def _norm_flag(name):
    return name.lower().replace("_", "-")


def _main_usage():
    return str(getattr(sys.modules.get("__main__"), "USAGE", "") or "")


def _split_list(vals):
    out = []
    for v in vals:
        s = str(v).strip()
        if len(s) > 1 and s[0] == "[" and s[-1] == "]":          # the skill wrapper passes str(list)
            try:
                import ast
                lit = ast.literal_eval(s)
                if isinstance(lit, (list, tuple)):
                    out.extend(str(x) for x in lit)
                    continue
            except (ValueError, SyntaxError):
                pass
        cur, depth = [], 0
        for ch in s:
            if ch in "[({":
                depth += 1
            elif ch in "])}" and depth:
                depth -= 1
            if depth == 0 and (ch == "," or ch.isspace()):
                if cur:
                    out.append("".join(cur))
                cur = []
                continue
            cur.append(ch)
        if cur:
            out.append("".join(cur))
    return [x for x in out if x]


def _coerce(name, kind, raw, res, is_flag):
    """Typed value, or: int/float -> None (flag) / raw str (positional); range -> raw str. Failures noted in _bad."""
    s = str(raw)
    if kind == "int":
        m = _INT.match(s)
        if m:
            return int(m.group(1))
    elif kind == "float":
        try:
            return float(s.strip().rstrip("s"))
        except ValueError:
            pass
    elif kind == "range":
        m = _RANGE.match(s)
        if m:
            a = int(m.group(1))
            return Span(a, int(m.group(2)) if m.group(2) else a)
    elif kind == "bool":
        v = _BOOLS.get(s.strip().lower())
        return True if v is None else v
    else:
        return s
    res["_bad"][name] = s
    what = {"int": "an integer", "float": "a number", "range": "a line range like 120-135"}.get(kind, kind)
    res["_notes"].append("--%s must be %s" % (name, what))
    if kind == "range" or not is_flag:
        return s
    return None


def parse_args(argv, flags, positionals=(), usage=None, strict=True, interspersed=True):
    """Parse helper arguments -> Args.

    flags: {name: kind}, kind in str/int/float/bool/range/list. Accepted: --k v, --k=v, bare booleans or booleans
    followed by 1/0/true/false/yes/no/on/off (any case), list flags taking values until the next --x (a string with
    spaces/commas or a str(list) is split). A bare -- is ignored. positionals: names given to the positional words in
    order, skipping names already set by a flag; a name ending in * takes all remaining words joined by spaces.
    Unknown flags raise UsageError (strict) or land in _unknown. interspersed=False: the first positional word ends
    flag parsing (run.py commands)."""
    flags = dict((_norm_flag(k), v) for k, v in (flags or {}).items())
    usage = usage if usage is not None else _main_usage()
    res = Args()
    for k, kind in flags.items():
        res[k] = False if kind == "bool" else [] if kind == "list" else None
    for k in ("_", "_notes", "_unknown"):
        dict.__setitem__(res, k, [])
    dict.__setitem__(res, "_given", set())
    dict.__setitem__(res, "_bad", {})
    toks = [str(t) for t in (argv or [])]
    pos, i, done = [], 0, False

    def is_known_flag(tok):
        m = _FLAG.match(tok)
        return bool(m) and _norm_flag(m.group(1)) in flags

    while i < len(toks):
        t = toks[i]
        i += 1
        if t == "--":
            continue
        m = None if done else _FLAG.match(t)
        if not m:
            pos.append(t)
            if not interspersed:
                done = True
            continue
        name, inline = _norm_flag(m.group(1)), m.group(2)
        kind = flags.get(name)
        if kind is None:
            if strict:
                raise UsageError("USAGE ERROR: unknown option --%s. Usage: %s" % (m.group(1), usage))
            res["_unknown"].append(t)
            continue
        res["_given"].add(name)
        if kind == "bool":
            if inline is not None:
                res[name] = _coerce(name, kind, inline, res, True)
            elif i < len(toks) and toks[i].strip().lower() in _BOOLS:
                res[name] = _BOOLS[toks[i].strip().lower()]
                i += 1
            else:
                res[name] = True
        elif kind == "list":
            vals = [inline] if inline is not None else []
            if inline is None:
                while i < len(toks) and toks[i] != "--" and not _FLAG.match(toks[i]):
                    vals.append(toks[i])
                    i += 1
            res[name] = list(res.get(name) or []) + _split_list(vals)
        else:
            if inline is None:
                if i < len(toks) and not is_known_flag(toks[i]) and toks[i] != "--":
                    inline = toks[i]
                    i += 1
                else:
                    raise UsageError("USAGE ERROR: --%s needs a value. Usage: %s" % (name, usage))
            res[name] = _coerce(name, kind, inline, res, True)
    names = list(positionals or ())
    rest, pi = [], 0
    for j, v in enumerate(pos):
        while pi < len(names) and _norm_flag(names[pi].rstrip("*")) in res["_given"]:
            pi += 1
        if pi >= len(names):
            rest.append(v)
            continue
        raw = names[pi]
        n = _norm_flag(raw.rstrip("*"))
        kind = flags.get(n, "str")
        if raw.endswith("*"):
            words = pos[j:]
            res[n] = _split_list(words) if kind == "list" else " ".join(words)
            res["_given"].add(n)
            break
        res[n] = _coerce(n, kind, v, res, False) if kind not in ("str", "list") else ([v] if kind == "list" else v)
        res["_given"].add(n)
        pi += 1
    dict.__setitem__(res, "_", rest)
    return res


def input_text(opts):
    """The text a helper works on: --text when given (normalised like stdin), else read_stdin()."""
    v = opts.get("text") if opts is not None else None
    if v is not None and v is not False:
        return _normalize_text(str(v))     # --text is part of argv, which the context meter already counts
    return read_stdin()


# -------------------------------------------------------------------------------------------------------------- stdin
_JUNK = re.compile(r"^\s*(?:(?:SWE_)?EOF\W*|`+)\s*$")


def _normalize_text(text):
    """CRLF -> LF; strip trailing heredoc junk lines (EOF, SWE_EOF, EOF., lone backticks)."""
    text = text.replace("\r\n", "\n")
    lines = text.split("\n")
    for _ in range(4):
        j = len(lines) - 1
        while j >= 0 and not lines[j].strip():
            j -= 1
        if j < 0 or not _JUNK.match(lines[j]):
            break
        lines = lines[:j] + [""]
    return "\n".join(lines)


def read_stdin(idle=1.0):
    """stdin text, never blocking: '' for a TTY, a closed stdin, /dev/null or any char device, and when nothing is
    readable within idle seconds; otherwise everything up to EOF (normalised by _normalize_text)."""
    try:
        fd = sys.stdin.fileno() if sys.stdin is not None else 0
    except (AttributeError, ValueError, OSError):
        fd = 0
    try:
        st = os.fstat(fd)
    except OSError:
        return ""
    try:
        if os.isatty(fd):
            return ""
    except OSError:
        return ""
    import stat as _stat
    if _stat.S_ISCHR(st.st_mode):
        return ""
    import select
    chunks, total = [], 0
    end = time.monotonic() + 20.0
    while True:
        try:
            r = select.select([fd], [], [], idle)[0]
        except (OSError, ValueError):
            break
        if not r:
            break
        try:
            b = os.read(fd, 1 << 16)
        except OSError:
            break
        if not b:
            break
        chunks.append(b)
        total += len(b)
        if total >= _STDIN_MAX or time.monotonic() > end:
            break
    if not chunks:
        return ""
    text = _normalize_text(b"".join(chunks).decode("utf-8", "surrogateescape"))
    _CACHE["in_stdin"] = est_tokens(text)          # the heredoc the model wrote: part of the stage's prompt
    return text


# ------------------------------------------------------------------------------------------------------- subprocesses
def _killpg(pgid):
    try:
        import signal
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError, AttributeError):
        pass


def _shell():
    b = _CACHE.get("bash")
    if b is None:
        b = "/bin/bash" if os.path.exists("/bin/bash") else "sh"
        _CACHE["bash"] = b
    return b


def _feed(pipe, data):
    """Write data to a child's stdin and close it (a writer thread: a child that never reads cannot block sh())."""
    try:
        pipe.write(data)
    except (OSError, ValueError):
        pass
    try:
        pipe.close()
    except (OSError, ValueError):
        pass


def sh(cmd, timeout, cwd=None, env=None, input=None):
    """Run argv (list) or a bash command string -> (rc | None on timeout, merged output text).

    New session, stdin /dev/null (v10.2: or `input`, str or bytes, fed by a writer thread and then closed), output
    capped at 4 MB (decoded UTF-8, errors replaced). On the deadline the whole process group is SIGKILLed and the
    partial output returned; on a normal exit the group is killed too, so background children never outlive the call
    (a child that exited but left a background process holding the pipe returns within ~0.3 s)."""
    import subprocess
    import select
    argv = [_shell(), "-c", cmd] if isinstance(cmd, str) else [str(a) for a in cmd]
    try:
        p = subprocess.Popen(argv, cwd=cwd or ws(), env=env,
                             stdin=subprocess.DEVNULL if input is None else subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, start_new_session=True)
    except OSError as ex:
        return 127, "cannot run %s: %s" % (argv[0], ex)
    _LIVE.add(p.pid)
    if input is not None:
        import threading
        data = input.encode("utf-8", "surrogateescape") if isinstance(input, str) else bytes(input)
        th = threading.Thread(target=_feed, args=(p.stdin, data))
        th.daemon = True
        th.start()
    fd = p.stdout.fileno()
    buf, n, over, timed_out, exited = [], 0, False, False, None
    end = time.monotonic() + _clamp(timeout)
    try:
        while True:
            now = time.monotonic()
            if now >= end:
                timed_out = True
                break
            if exited is None and p.poll() is not None:
                exited = now
            if exited is not None and now - exited > 0.3:
                break
            r = select.select([fd], [], [], min(end - now, 0.05 if exited is not None else 0.1))[0]
            if not r:
                continue
            b = os.read(fd, 65536)
            if not b:
                break
            if n < _SH_MAX:
                b = b[:_SH_MAX - n]
                buf.append(b)
                n += len(b)
            else:
                over = True
    finally:
        _killpg(p.pid)
        if timed_out:
            stop = time.monotonic() + 0.5
            try:
                while time.monotonic() < stop:
                    r = select.select([fd], [], [], 0.05)[0]
                    if not r:
                        continue
                    b = os.read(fd, 65536)
                    if not b:
                        break
                    if n < _SH_MAX:
                        buf.append(b[:_SH_MAX - n])
                        n += len(buf[-1])
            except (OSError, ValueError):
                pass
        try:
            p.wait(timeout=2)
        except Exception:
            pass
        try:
            p.stdout.close()
        except Exception:
            pass
        _LIVE.discard(p.pid)
    text = b"".join(buf).decode("utf-8", "replace")
    if over:
        text += "\n... [output cut at 4 MB]"
    return (None if timed_out else p.returncode), text


def sh_many(jobs, deadline, par=None):
    """Run jobs with at most MAX_PAR (or par, if smaller) at once, all within `deadline` seconds from now.
    A job is a command (str or argv list), a tuple (cmd, timeout[, cwd[, env]]) or a dict(cmd=, timeout=, cwd=, env=).
    Returns [(rc | None, text)] in job order; a job that cannot start in time gives (None, 'not run: no time left')."""
    import threading
    end = time.monotonic() + float(deadline)
    jobs = list(jobs)
    res = [None] * len(jobs)
    nxt = [0]
    lock = threading.Lock()

    def unpack(j):
        if isinstance(j, dict):
            return j.get("cmd") or j.get("argv"), j.get("timeout"), j.get("cwd"), j.get("env")
        if isinstance(j, tuple):
            j = list(j) + [None] * 3
            return j[0], j[1], j[2], j[3]
        return j, None, None, None

    def worker():
        while True:
            with lock:
                i = nxt[0]
                nxt[0] += 1
            if i >= len(jobs):
                return
            cmd, t, cwd, env = unpack(jobs[i])
            rem = end - time.monotonic()
            if rem <= 0.05:
                res[i] = (None, "not run: no time left")
                continue
            res[i] = sh(cmd, min(float(t), rem) if t else rem, cwd=cwd, env=env)

    k = max(1, min(MAX_PAR, par or MAX_PAR, len(jobs)))
    threads = [threading.Thread(target=worker) for _ in range(k)]
    for th in threads:
        th.daemon = True
        th.start()
    for th in threads:
        th.join()
    return res


# ------------------------------------------------------------------------------------------------------ git: the tree
# v10.2 (R2, hidden.md T2): a scratch prefix needs a separator (or the end of the name) after it: repro.py,
# reproduce_issue.py, tmp_check.py, scratch.py, debug_out.log, demo2.py are scratch; template.py, templates_engine.py,
# tmpl.py, temperature.py, debugger.py, trying.py, reproducible.py are not (v10.1 deleted them from real patches).
SCRATCH_PREFIXES = ("repro", "reproduce", "scratch", "debug", "tmp", "temp", "try", "demo")
_SCRATCH_ROOT = re.compile(r"^(?:%s)(?=$|[-_.0-9])" % "|".join(SCRATCH_PREFIXES), re.I)


def scratch_name(name):
    """True when a root-level file or directory name looks like scratch (the R2 separator rule)."""
    return bool(_SCRATCH_ROOT.match(name or ""))


def _skip_path(p):
    b = p.rsplit("/", 1)[-1]
    return not p or b.startswith(".adk_exec_") or "/__pycache__/" in "/" + p or p.endswith(".pyc")


# Tracked root-level scripts that do not make the repository a root-module layout.
_ROOT_SCRIPTS = frozenset(("setup.py", "conftest.py", "noxfile.py", "fabfile.py", "tasks.py", "manage.py",
                           "runtests.py", "versioneer.py"))


def _root_entries():
    """(names, modules) of the baseline's root tree: every root entry, and the root-level .py modules other than
    _ROOT_SCRIPTS and protected files. Cached per process (the baseline cannot change within a task)."""
    v = _CACHE.get("root_entries")
    if v is None:
        rc, out = git(["ls-tree", "-z", "--name-only", baseline()])
        names = frozenset(p for p in out.split("\0") if p) if rc == 0 else frozenset()
        mods = frozenset(p for p in names if p.endswith(".py") and p not in _ROOT_SCRIPTS and not _protected_git(p))
        v = _CACHE["root_entries"] = (names, mods)
    return v


def is_stdlib_name(stem):
    """True for a top-level stdlib module name (a same-named root file would shadow it)."""
    names = getattr(sys, "stdlib_module_names", None)
    if names is not None:
        return stem in names
    if stem in sys.builtin_module_names:
        return True
    lib = os.path.dirname(os.__file__)
    return os.path.isfile(os.path.join(lib, stem + ".py")) or os.path.isdir(os.path.join(lib, stem))


def imports_module(stem, paths):
    """True when one of these repo files (relative paths) imports the top-level module `stem`."""
    rx = _CACHE.get(("imp_rx", stem))
    if rx is None:
        s = re.escape(stem)
        rx = _CACHE[("imp_rx", stem)] = re.compile(
            r"^[ \t]*(?:from[ \t]+%s(?:[ \t]|\.)|import[ \t]+(?:[\w.]+(?:[ \t]+as[ \t]+\w+)?[ \t]*,[ \t]*)*%s\b)" % (s, s),
            re.M)
    w = ws()
    for p in paths:
        try:
            with open(os.path.join(w, p), "rb") as f:
                text = f.read(4 << 20).decode("utf-8", "replace")
        except OSError:
            continue
        if rx.search(text):
            return True
    return False


def root_module_kept(p, tracked_changed=()):
    """Whether an untracked .py file is a new module (part of the patch) rather than scratch. Inside a directory it
    is; at the root it is only when its name is no stdlib module and no baseline root entry, and either a changed
    tracked file (tracked_changed) imports it (v10.2, R2: whatever its prefix, so demo_data.py imported by app.py
    ships), or it does not look like scratch and the baseline already has root-level modules. Root-level
    check/verify/repro scripts are therefore scratch: they would ship in the patch and, under the grader's
    PYTHONPATH=<workspace>, could shadow installed modules."""
    if not p.endswith(".py"):
        return False
    if "/" in p:
        return True
    stem = p[:-3]
    if not stem.isidentifier() or is_stdlib_name(stem):
        return False
    names, mods = _root_entries()
    if stem in names:                      # a tracked package or data dir of that name: the file only shadows it
        return False
    if mods and not _SCRATCH_ROOT.match(p):
        return True
    return bool(tracked_changed) and imports_module(stem, tracked_changed)


def references_name(name, paths):
    """True when one of these repo files (relative paths) names `name` as a whole word (an import, or a string such
    as a data directory the code loads): the v10.2 test for a new root directory that tracked code references."""
    rx = re.compile(r"(?<![\w.-])%s(?![\w-])" % re.escape(name))
    w = ws()
    for p in paths:
        try:
            with open(os.path.join(w, p), "rb") as f:
                text = f.read(4 << 20).decode("utf-8", "replace")
        except OSError:
            continue
        if rx.search(text):
            return True
    return False


def _new_module(p, tracked_changed=()):
    """An untracked .py that looks like a new module rather than scratch (see root_module_kept)."""
    return root_module_kept(p, tracked_changed)


def changes(hidden=True):
    """Changes since baseline() -> dict(source, protected, untracked, deleted, status). source: changed tracked
    non-protected files plus untracked new modules; deleted: deleted tracked non-protected files; protected: every
    changed/new protected path (a new one also by the graders' rule, harness_protected: see write_protected);
    untracked: every untracked non-protected file; status: path -> M/A/D/T/?. Reads only (no write to the real index). The helpers keep their own view under the submit guard (v10.1): untracked files are
    listed without the guard's exclude file, and with hidden=True the protected files the guard marked
    assume-unchanged are compared too (on a temp copy of the index), so hygiene still sees and reverts them."""
    b = baseline()
    res = {"source": [], "protected": [], "untracked": [], "deleted": [], "status": {}}
    args = ["diff", "--name-status", "-z", "--no-renames", "--no-ext-diff", "--ignore-submodules", b]
    flagged = []
    env = _unguarded_index_env(flagged) if hidden and not _hidden_clean() else None
    try:
        rc, out = git(args, env=env)
    finally:
        if env is not None:
            _drop_index(env)
    if env is not None and rc == 0:
        _note_hidden_clean(flagged, set(out.split("\0")[1::2]))
    if rc == 0:
        parts = out.split("\0")
        i = 0
        while i + 1 < len(parts):
            code, p = parts[i][:1], parts[i + 1]
            i += 2
            if not code or _skip_path(p):
                continue
            res["status"][p] = code
            if _protected_git(p) or (code == "A" and harness_protected(p)):   # A: new, the graders delete it
                res["protected"].append(p)
            elif code == "D":
                res["deleted"].append(p)
            else:
                res["source"].append(p)
    rc, out = git(NO_GUARD + ["ls-files", "--others", "--exclude-standard", "-z"])
    if rc == 0:
        root_py = []
        for p in out.split("\0"):
            if not p or _skip_path(p) or p in res["status"]:
                continue
            res["status"][p] = "?"
            if _protected_git(p) or harness_protected(p):
                res["protected"].append(p)
            else:
                res["untracked"].append(p)
                if p.endswith(".py"):
                    if "/" in p:
                        res["source"].append(p)
                    else:
                        root_py.append(p)
        if root_py:                        # rare: decided against the tracked changes found above
            tracked = [q for q in res["source"] if q.endswith(".py") and res["status"].get(q) != "?"]
            res["source"] += [p for p in root_py if root_module_kept(p, tracked)]
    for k in ("source", "protected", "untracked", "deleted"):
        res[k].sort()
    return res


def source_changed():
    """True when the tree has a source change (or when that cannot be determined)."""
    try:
        ch = changes(hidden=False)          # the guard hides only protected files, never source
        return bool(ch["source"] or ch["deleted"])
    except Exception:
        return True


def _index_path():
    gd = git_dir()
    if gd:
        return os.path.join(gd, "index")
    rc, out = git(["rev-parse", "--git-path", "index"])
    p = out.strip() if rc == 0 else ""
    return os.path.join(ws(), p) if p and not os.path.isabs(p) else p


def _tmp_index_env():
    """Env with GIT_INDEX_FILE=$SWE/idx: a copy of the real index plus intent-to-add entries for untracked files
    (what the harness's `git add -N .` adds before diffing). The real index is never written."""
    idx = os.path.join(swe_dir(), "idx")
    src = _index_path()
    try:
        with open(src, "rb") as f:
            st = os.fstat(f.fileno())
            data = f.read()
        tmp = idx + ".tmp.%d" % os.getpid()
        _atomic_write(tmp, data)
        # keep the index's own timestamps: git judges "racily clean" entries (a file rewritten in the same second
        # with the same size) against the index file's mtime; a fresh mtime would make such an edit look unchanged
        os.utime(tmp, ns=(st.st_atime_ns, st.st_mtime_ns))
        os.replace(tmp, idx)
    except OSError:
        try:
            os.remove(idx)
        except OSError:
            pass
    env = dict(os.environ)
    env["GIT_INDEX_FILE"] = idx
    git_run(["add", "-N", "--", "."], timeout=30, env=env)
    return env


class tmp_index(object):
    """`with C.tmp_index() as env:` git calls made with env see the tree as the submitted patch will (new files in);
    built once for the block, under a lock, without writing the real index."""

    def __enter__(self):
        self.lock = _Flock("idx.lock.flock")
        self.lock.__enter__()
        try:
            return _tmp_index_env()
        except BaseException:
            self.lock.__exit__(None, None, None)
            raise

    def __exit__(self, *exc):
        return self.lock.__exit__(*exc)


def diff_bytes():
    """Bytes equal to the patch the harness submits (`git add -N . && git diff --binary <baseline>`), built on a temp
    copy of the index so the real one is untouched. Paths are quoted the way the harness sees them."""
    with tmp_index() as env:
        rc, out, err = git_run(["diff", "--binary", baseline()], timeout=60, env=env, quotepath_off=False)
    return out if rc == 0 else b""


def diff_sha():
    return sha1_hex(diff_bytes())


def git_tmpindex(args, timeout=30, env=None):
    """git <args> against the temp index (new files visible, as in the submitted patch) -> (rc, text). Pass the env
    of an open tmp_index() block to reuse it."""
    if env is not None:
        rc, out, err = git_run(args, timeout=timeout, env=env)
    else:
        with tmp_index() as e:
            rc, out, err = git_run(args, timeout=timeout, env=e)
    text = out.decode("utf-8", "surrogateescape")
    return rc, text if rc == 0 else text + err.decode("utf-8", "replace")


def numstat(paths=None, env=None):
    """[(path, added, deleted)] since baseline over the submitted-patch view (None counts for binary files)."""
    args = ["--literal-pathspecs", "diff", "--numstat", "-z", "--no-renames", "--no-ext-diff", baseline()]
    if paths is not None:
        if not paths:
            return []
        args += ["--"] + list(paths)
    rc, out = git_tmpindex(args, env=env)
    res = []
    if rc != 0:
        return res
    for rec in out.split("\0"):
        f = rec.split("\t", 2)
        if len(f) == 3 and f[2]:
            a = int(f[0]) if f[0].isdigit() else None
            d = int(f[1]) if f[1].isdigit() else None
            res.append((f[2], a, d))
    return res


# -------------------------------------------------------------------------------------------------------- protection
_PROT_NAMES = {"conftest.py": "test configuration file", "pytest.ini": "test configuration file",
               ".pytest.ini": "test configuration file", "tox.ini": "test configuration file",
               "setup.cfg": "packaging/test configuration file", "pyproject.toml": "packaging/test configuration file",
               "sitecustomize.py": "interpreter startup file", "usercustomize.py": "interpreter startup file",
               "_swegemma_stubs.py": "harness file"}


def _protected_parts(parts):
    if not parts or ".." in parts:
        return "outside the repository"
    if ".git" in parts:
        return "git internals"
    base = parts[-1]
    if (base.startswith("test_") and base.endswith(".py")) or base.endswith("_test.py"):
        return "test file"
    if base in _PROT_NAMES:
        return _PROT_NAMES[base]
    if base.endswith(".pth"):
        return "interpreter startup file"
    if len(parts) > 1 and (parts[0] in ("tests", "test", "testing") or any(x in ("tests", "test") for x in parts[1:-1])):
        return "test directory"
    return None


def _protected_git(p):
    """is_protected for a repo-relative path listed by git (no symlink/realpath checks needed)."""
    return _protected_parts([x for x in p.split("/") if x not in ("", ".")])


def is_protected(path):
    """Why the grader-side reset owns this path (a short reason), or None when the agent may change it."""
    if path is None:
        return "outside the repository"
    p = str(path).replace("\\", "/").strip()
    if not p or p in (".", "./"):
        return "outside the repository"
    w = ws()
    if os.path.isabs(p):
        rp = _real(p)
        if not _under(rp, w) or rp == w:
            return "outside the repository"
        p = os.path.relpath(rp, w).replace(os.sep, "/")
    parts = [x for x in p.split("/") if x not in ("", ".")]
    why = _protected_parts(parts)
    if why:
        return why
    if not _under(_real(os.path.join(w, *parts)), w):
        return "outside the repository"
    return None


def hygiene_revert():
    """Undo agent changes to protected paths: tracked ones (modified, deleted, type-changed) are checked out from the
    baseline one path per call; new ones are removed. Source files are never touched. Returns the paths."""
    ch = changes()
    b = baseline()
    done = []
    w = ws()
    for p in ch["protected"]:
        code = ch["status"].get(p)
        if code in ("?", "A"):
            if code == "A":
                git(["--literal-pathspecs", "rm", "-q", "--cached", "--ignore-unmatch", "--", p])
            fp = os.path.join(w, p)
            try:
                if os.path.islink(fp) or os.path.isfile(fp):
                    os.remove(fp)
                    done.append(p)
            except OSError:
                pass
        else:
            rc, _ = git(["--literal-pathspecs", "checkout", b, "--", p])
            if rc == 0:
                done.append(p)
    return done


def hygiene_note(paths):
    """The one line helpers print after hygiene_revert() did something ('' when nothing was done)."""
    if not paths:
        return ""
    shown = ", ".join(paths[:6]) + (" (+%d more)" % (len(paths) - 6) if len(paths) > 6 else "")
    return "reverted test/config edits: " + shown + HYGIENE_WHY


# v10.1 (race 2, fastapi_14077): a bare "reverted pyproject.toml" read like a lost edit, and the model made it again.
HYGIENE_WHY = " (graders replace test and config files, so a patch never carries them; do not redo this)"


# ----------------------------------------------------------------------------------------------------- the submit guard
# v10.1 (race 2, diagnosis 3). Every hygiene step above runs only inside a helper call, but the harness snapshots the
# patch whenever it likes: submit_patch after a native edit_file (fastapi_14077 re-edited pyproject.toml after
# finalize), and the fallback diff `git add -N . && git diff --binary _swegemma_baseline` at a timeout, a tool-budget
# end or a nudge end (fastapi_14258 shipped a root repro.py; finalize never ran). arm_submit_guard() makes that diff
# blind to those paths from the first tool call on, passively: protected tracked files are marked assume-unchanged in
# the real index (git diff <tag> and git add then treat the worktree copy as unchanged), and an exclude file named by
# core.excludesFile keeps untracked scratch, vendored trees and new test/config files out of `git add -N .`. The
# helpers keep their own view (NO_GUARD, changes(hidden=True)), so HYGIENE and CLEANED still see and undo them.
GUARD_FILE = "swe_exclude"                    # <gitdir>/swe_exclude: inside .git, so it can never enter a patch
GUARD_STAT = "guard_stat.json"                # $SWE: stat of the guarded files last found clean (_hidden_clean)
NO_GUARD = ["-c", "core.excludesFile=" + os.devnull]   # untracked listings of the helpers' own view
GUARD_ROOT_PREFIXES = SCRATCH_PREFIXES      # v10.2 (R2): each as /<prefix> and /<prefix>[-_.0-9]* (a separator)
GUARD_KEEP_MARK = "# swe-tools v10.2: kept new root entries (imported or referenced by changed tracked code)"
GUARD_ANY = ("*.log", "*.orig", "*.rej", "*.bak", "*.swp", ".coverage")
GUARD_VENDOR = ("site-packages/", "_pytest/", "*.dist-info/")
GUARD_PROTECTED = ("test_*.py", "*_test.py", "*.pth", "tests/", "test/", "/testing/")
GUARD_TEST_DIRS = ("tests", "test", "testing")   # new .py below one, any depth and case: the graders' git clean deletes it


def _ci(word):
    """A gitignore glob matching `word` in any letter case: repro -> [Rr][Ee][Pp][Rr][Oo]."""
    return "".join("[%s%s]" % (c.upper(), c.lower()) if c.isalpha() else c for c in word)


def _gi_escape(name):
    """A literal path for a gitignore line (leading ! or #, glob characters, trailing spaces escaped)."""
    out = re.sub(r"([\\*?\[\]])", r"\\\1", name)
    if out[:1] in ("!", "#"):
        out = "\\" + out
    return re.sub(r" +$", lambda m: "\\ " * len(m.group(0)), out)


def _guard_vendor_dir(base):
    return base in ("site-packages", "_pytest") or base.endswith(".dist-info")


def guard_exclude_text(root_names, tracked_dirs, kept=()):
    """The exclude file: root scratch prefixes (any case, v10.2: the name itself or the prefix plus a separator),
    scratch anywhere, vendored trees, new protected files (the is_protected rules, and write_protected's new .py under
    a tests/test/testing dir of any depth and case), then re-includes for baseline root entries and tracked directories
    that a pattern would otherwise hide, so a real new file under a tracked templates/ or src/_pytest/ still ships.
    kept (v10.2, R2): new root modules and directories that changed tracked code imports or references, re-included
    after GUARD_KEEP_MARK so `git add -N . && git diff _swegemma_baseline` carries them."""
    lines = ["# swe-tools %s submit guard: git add -N . never adds these untracked paths" % VERSION]
    for p in GUARD_ROOT_PREFIXES:
        lines += ["/%s" % _ci(p), "/%s[-_.0-9]*" % _ci(p)]
    lines += list(GUARD_ANY) + list(GUARD_VENDOR) + sorted(_PROT_NAMES) + list(GUARD_PROTECTED)
    lines += ["**/%s/**/*.py" % _ci(d) for d in GUARD_TEST_DIRS]       # harness_protected's new files (write_protected)
    keep = set()
    for n in root_names:
        if scratch_name(n):
            keep.add("!/" + _gi_escape(n))
    for d in tracked_dirs:
        if _guard_vendor_dir(d.rsplit("/", 1)[-1]):
            keep.add("!/" + _gi_escape(d) + "/")
    return "\n".join(lines + sorted(keep) + [GUARD_KEEP_MARK] + ["!/" + _gi_escape(n) for n in sorted(set(kept))]) + "\n"


def guard_kept_entries():
    """v10.2 (R2): the untracked root entries the guard's scratch patterns hide although they belong to the patch: a
    new root .py module that root_module_kept() keeps (a changed tracked file imports it), and a new root directory
    whose name changed tracked code references. Two git calls, and only when such an entry exists: every kept entry is
    a root-level name matching the scratch rule, so a workspace root without one returns [] after a listdir (edit.py
    calls this on every edit, and the git call cost 11 ms of its 150 ms p95 budget)."""
    try:
        if not any(scratch_name(n) for n in os.listdir(ws())):
            return []
    except OSError:
        pass
    rc, out = git(NO_GUARD + ["ls-files", "--others", "--exclude-standard", "--directory", "--no-empty-directory",
                              "-z"])
    if rc != 0:
        return []
    roots = set()
    for p in out.split("\0"):
        if p and not _skip_path(p):
            top = p.split("/", 1)[0]
            if scratch_name(top) and not _protected_git(top):
                roots.add((top, "/" in p))
    if not roots:
        return []
    rc, out = git(["diff", "--name-only", "-z", "--no-renames", baseline()])
    tracked = [q for q in out.split("\0") if q and not _skip_path(q)] if rc == 0 else []
    if not tracked:
        return []
    kept = []
    for top, is_dir in sorted(roots):
        if is_dir:
            if references_name(top, tracked):
                kept.append(top)
        elif top.endswith(".py") and root_module_kept(top, [q for q in tracked if q.endswith(".py")]):
            kept.append(top)
    return kept


def refresh_guard_keep():
    """Rewrite only the kept-entries section of an armed guard file (edit.py's save_edited and status.py call it, and
    finalize re-arms fully). No-op when the guard is not armed or the section is already right."""
    path = _guard_path()
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            text = f.read()
    except OSError:
        return None
    kept = guard_kept_entries()
    head = text.split(GUARD_KEEP_MARK + "\n", 1)[0] if GUARD_KEEP_MARK in text else text
    new = head + GUARD_KEEP_MARK + "\n" + "".join("!/%s\n" % _gi_escape(n) for n in kept)
    if new != text:
        _atomic_write(path, new)
    return kept


def _guard_path():
    """<gitdir>/swe_exclude, or '' when the workspace has no git dir."""
    v = _CACHE.get("guard_path")
    if v is None:
        gd = git_dir()
        if not gd:
            rc, out = git(["rev-parse", "--absolute-git-dir"])
            gd = out.strip() if rc == 0 and out.strip() else ""
        v = _CACHE["guard_path"] = os.path.join(gd, GUARD_FILE) if gd else ""
    return v


def guard_armed():
    p = _guard_path()
    return bool(p) and os.path.isfile(p)


def arm_submit_guard():
    """Arm (or re-arm) the submit guard; idempotent, a few git calls, never touches the worktree. -> (flagged paths
    newly marked, total flagged) or None when the workspace is no git repository. Called by install.py (the first tool
    call, before any agent write) and at the top of finalize.py (after a failed install, or a read-tree/reset that
    dropped the flags)."""
    path = _guard_path()
    if not path or not _tag_sha():           # only a harness workspace (it has the baseline tag) is ever armed
        return None
    rc, out = git(["ls-files", "-v", "-z"], timeout=20)
    if rc != 0:
        return None
    todo, total, dirs = [], 0, set()
    for rec in out.split("\0"):
        if len(rec) < 3:
            continue
        tag, p = rec[0], rec[2:]
        d = os.path.dirname(p)
        while d and d not in dirs:
            dirs.add(d)
            d = os.path.dirname(d)
        if _protected_git(p):
            total += 1
            if not tag.islower():
                todo.append(p)
    try:
        kept = guard_kept_entries()
    except Exception:
        kept = []
    text = guard_exclude_text(_root_entries()[0], dirs, kept)
    try:
        with open(path) as f:
            same = f.read() == text
    except OSError:
        same = False
    if not same:
        _atomic_write(path, text)
    rc, cur = git(["config", "--local", "--get", "core.excludesFile"])
    if cur.strip() != path:
        git(["config", "--local", "core.excludesFile", path])
    if todo:
        git_run(["update-index", "-z", "--assume-unchanged", "--stdin"], timeout=20,
                input="\0".join(todo).encode("utf-8", "surrogateescape"))
        try:                                 # newly guarded files are not in the clean snapshot: check them fully
            os.remove(os.path.join(swe_dir(), GUARD_STAT))
        except OSError:
            pass
    return len(todo), total


def _drop_index(env):
    try:
        os.remove(env["GIT_INDEX_FILE"])
    except (OSError, KeyError, TypeError):
        pass


def _stat_sig(rel):
    try:
        st = os.lstat(os.path.join(ws(), rel))
    except OSError:
        return None
    return [st.st_size, st.st_mtime_ns]


def _hidden_clean():
    """True when the last full check found every guarded file equal to the baseline and none of them has changed size
    or mtime since (the stat test git itself makes): changes() then skips the index copy and its three git calls, which
    cost about 20 ms per call (v10.1, speed)."""
    try:
        with open(os.path.join(swe_dir(), GUARD_STAT)) as f:
            snap = json.load(f)
    except (OSError, ValueError):
        return False
    return isinstance(snap, dict) and bool(snap) and all(_stat_sig(p) == v for p, v in snap.items())


def _note_hidden_clean(flagged, changed):
    """Remember the stat of every guarded file the full check found unchanged; a changed one is recorded as "dirty",
    which never matches, so every later call checks fully until a check finds it clean again."""
    snap = {p: ("dirty" if p in changed else _stat_sig(p)) for p in flagged}
    try:
        _atomic_write(os.path.join(swe_dir(), GUARD_STAT), json.dumps(snap))
    except OSError:
        pass


def _unguarded_index_env(flagged_out=None):
    """None when no path is marked assume-unchanged; else an env whose GIT_INDEX_FILE is a private copy of the real
    index with those marks cleared (the index's own timestamps kept, as in _tmp_index_env), so git diff compares the
    protected files the guard hides from the patch. The caller removes the copy (_drop_index). flagged_out, a list,
    receives the marked paths."""
    if not guard_armed():
        return None
    rc, out = git(["ls-files", "-v", "-z"], timeout=20)
    flagged = [r[2:] for r in out.split("\0") if len(r) > 2 and r[0].islower()] if rc == 0 else []
    if flagged_out is not None:
        flagged_out.extend(flagged)
    if not flagged:
        return None
    src = _index_path()
    idx = os.path.join(swe_dir(), "gidx.%d" % os.getpid())
    try:
        with open(src, "rb") as f:
            st = os.fstat(f.fileno())
            data = f.read()
        _atomic_write(idx, data)
        os.utime(idx, ns=(st.st_atime_ns, st.st_mtime_ns))
    except OSError:
        return None
    env = dict(os.environ)
    env["GIT_INDEX_FILE"] = idx
    rc, _, _ = git_run(["update-index", "-z", "--no-assume-unchanged", "--stdin"], timeout=20, env=env,
                       input="\0".join(flagged).encode("utf-8", "surrogateescape"))
    if rc != 0:
        _drop_index(env)
        return None
    return env


# The graders' view of a patch (replay_l4 KPI 7 and 8; tests keep the two in sync): the harness rule
# swegemma.harness.verification._is_protected_test_or_config_path, and NEW scratch or vendored files.
_H_PROT_NAMES = frozenset(("conftest.py", "pytest.ini", "pyproject.toml", "tox.ini", "setup.cfg", ".pytest.ini",
                           "sitecustomize.py", "usercustomize.py", "_swegemma_stubs.py"))
_KPI_SCRATCH_ROOT = re.compile(r"^(?:repro|reproduce|scratch|debug|tmp|temp|try|demo)(?:[-_.0-9][^/]*)?$|"
                               r"^test_[^/]*\.py$|^[^/]*_test\.py$", re.I)       # v10.2 (R2): the separator rule
_KPI_SCRATCH_ANY = re.compile(r"\.(log|orig|rej|bak|swp)$|(^|/)\.coverage$")
_KPI_VENDORED = re.compile(r"(^|/)(site-packages|_pytest|[^/]+\.dist-info)(/|$)")


def harness_protected(rel):
    """The graders' reset rule (verification.py:60-83): test/config names anywhere, *.pth, and .py files under a
    tests/test/testing directory at any depth, in any case."""
    parts = rel.split("/")
    name = parts[-1]
    if name in _H_PROT_NAMES or name.endswith(".pth"):
        return True
    if (name.startswith("test_") and name.endswith(".py")) or name.endswith("_test.py"):
        return True
    return bool({"tests", "test", "testing"} & {p.lower() for p in parts[:-1]} and name.endswith(".py"))


# One rule for every helper (review 2026-09-29): what edit.py refuses is exactly what finalize undoes. The graders'
# reset (verification.py:392-415) runs `git checkout HEAD -- <files> sitecustomize.py ...`, which aborts on the missing
# pathspec and restores nothing, then `git clean -f -- <files>`, which does delete NEW files. So a tracked file their rule
# alone covers (pkg/testing/util.py, pkg/Tests/x.py) keeps the agent's edit and may ship (is_protected allows it, R20),
# while a new .py there is deleted before the tests run and is refused like a test file.
NEW_IN_TEST_DIR = "new file in a test directory"


def in_baseline(rel):
    """True when the baseline tree has this repo-relative path (a file edit.py changes rather than creates)."""
    rc, _ = git(["cat-file", "-e", "%s:%s" % (baseline(), rel)])
    return rc == 0


def write_protected(rel):
    """Why no helper may write this path, or None: is_protected, or a path the graders' rule alone covers that the
    baseline does not have (their git clean deletes it). The git call runs only for that rare second kind."""
    why = is_protected(rel)
    if why:
        return why
    p = str(rel).replace("\\", "/").strip()
    if os.path.isabs(p):                      # is_protected already refused one outside ws()
        p = os.path.relpath(_real(p), ws()).replace(os.sep, "/")
    p = "/".join(x for x in p.split("/") if x not in ("", "."))
    if p and harness_protected(p) and not in_baseline(p):
        return NEW_IN_TEST_DIR
    return None


def patch_violations(files, kept=()):
    """[(path, why)] for the paths a patch must never carry: files = [(path, is_new)] as in the patch. Tracked paths
    follow the helpers' rule (_protected_git; the graders' checkout keeps tracked edits), new ones the graders' rule
    as well (their git clean deletes them), plus new scratch or vendored files. kept (v10.2, R2): new root modules that
    changed tracked code imports (kept_root_modules), never scratch whatever their prefix."""
    out = []
    kept = set(kept or ())
    for p, new in files:
        if _protected_git(p) or (new and harness_protected(p)):
            out.append((p, "test/config file"))
        elif new and p not in kept and (("/" not in p and _KPI_SCRATCH_ROOT.search(p)) or _KPI_SCRATCH_ANY.search(p)
                                        or _KPI_VENDORED.search(p)):
            out.append((p, "scratch or vendored file"))
    return out


def kept_root_modules(files):
    """v10.2 (R2): the new root .py files of a patch file list ([(path, is_new)]) that a changed tracked .py file of
    the same patch imports (root_module_kept), so the patch rules keep them whatever their prefix."""
    tracked = [p for p, new in files if not new and p.endswith(".py")]
    if not tracked:
        return set()
    return {p for p, new in files if new and "/" not in p and p.endswith(".py") and _KPI_SCRATCH_ROOT.search(p)
            and root_module_kept(p, tracked)}


def patch_file_list(diff):
    """[(path, is_new)] of a `git diff --binary` (bytes or str), paths unquoted the way git quotes them."""
    text = diff.decode("utf-8", "surrogateescape") if isinstance(diff, bytes) else str(diff or "")
    out, cur = [], None
    for line in text.split("\n"):
        if line.startswith("diff --git "):
            rest = line[len("diff --git "):]
            if rest.endswith('"'):
                j = rest.rfind(' "b/')
                p = _unquote_git(rest[j + 1:])[2:] if j >= 0 else rest
            else:
                j = rest.rfind(" b/")
                p = rest[j + 3:] if j >= 0 else rest
            cur = [p, False]
            out.append(cur)
        elif cur is not None and line.startswith("new file mode"):
            cur[1] = True
    return [(p, n) for p, n in out]


def _unquote_git(s):
    """A C-quoted git path ("a\\303\\251.py") -> str."""
    if not (len(s) >= 2 and s[0] == '"' and s[-1] == '"'):
        return s
    body, out, i = s[1:-1], bytearray(), 0
    esc = {"n": 10, "t": 9, '"': 34, "\\": 92, "a": 7, "b": 8, "f": 12, "r": 13, "v": 11}
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            nx = body[i + 1]
            if re.match(r"[0-7]{3}", body[i + 1:i + 4]):
                out.append(int(body[i + 1:i + 4], 8))
                i += 4
                continue
            out.append(esc.get(nx, ord(nx)))
            i += 2
            continue
        out += c.encode("utf-8", "surrogateescape")
        i += 1
    return out.decode("utf-8", "surrogateescape")


def enforce_patch_rules(diff=None):
    """Undo whatever the harness-view patch still carries against patch_violations: a tracked path is checked out
    from the baseline, a new one is unstaged (if the model staged it) and deleted. -> [(path, why)] undone."""
    if diff is None:
        diff = diff_bytes()
    files = patch_file_list(diff)
    is_new = dict(files)
    b, w, done = baseline(), ws(), []
    for p, why in patch_violations(files, kept_root_modules(files)):
        if is_new.get(p):
            git(["--literal-pathspecs", "rm", "-q", "--cached", "--ignore-unmatch", "--", p])
            fp = os.path.join(w, p)
            try:
                if os.path.islink(fp) or os.path.isfile(fp):
                    os.remove(fp)
            except OSError:
                continue
        else:
            rc, _ = git(["--literal-pathspecs", "checkout", b, "--", p])
            if rc != 0:
                continue
        done.append((p, why))
    return done


def unrewrite(text):
    """Undo the subprocess sandbox's rewrite of /tmp, /workspace, /usr/local/bin and /wheels in command text (heredoc
    bodies included), so code written through a heredoc keeps its literal paths. Identity outside that sandbox."""
    root = _sandbox_root()
    if not root or not text:
        return text
    for sub, lit in SANDBOX_REWRITES:
        pre = os.path.join(root, *sub.split("/"))
        if pre in text:
            text = re.sub(re.escape(pre) + r"(?![\w.-])", lambda m, lit=lit: lit, text)
    return text


def grader_env(tree, side):
    """Env for a child that imports repository code from `tree` the way the grader does (side: orig or cur)."""
    e = dict(os.environ)
    e.update(PYTHONSAFEPATH="1", PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1", NO_COLOR="1")
    side = re.sub(r"[^A-Za-z0-9_]", "_", str(side)) or "cur"
    rt = os.path.join(swe_dir(), "rt_" + side)
    try:
        os.makedirs(rt, exist_ok=True)
    except OSError:
        pass
    e["TMPDIR"] = rt
    w = ws()
    tree = os.path.abspath(str(tree))
    out, rerooted = [], False
    for x in (e.get("PYTHONPATH") or "").split(os.pathsep):
        if not x:
            continue
        rx = _real(x)
        if rx == w:
            out.append(tree)
            rerooted = True
        elif _under(rx, w):
            out.append(os.path.join(tree, os.path.relpath(rx, w)))
            rerooted = True
        else:
            out.append(x)
    if not rerooted:
        out.insert(0, tree)
    pre = []
    try:
        origin = state_load().get("origin") or {}
    except Exception:
        origin = {}
    for d in origin.values() if isinstance(origin, dict) else ():
        if isinstance(d, str) and d and not os.path.isabs(d) and ".." not in d.split("/"):
            c = os.path.join(tree, d)
            if c not in pre and os.path.isdir(c):
                pre.append(c)
    seen, final = set(), []
    for x in pre + out:
        if x not in seen:
            seen.add(x)
            final.append(x)
    e["PYTHONPATH"] = os.pathsep.join(final)
    return e


# ------------------------------------------------------------------------------------------------------------- output
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?|\x1b[@-Z\\-_]")
SUMMARY_RE = re.compile(r"(?:\b\d+ (?:passed|failed|errors?|skipped|xfailed|xpassed|deselected|warnings?)\b.*\bin "
                        r"[\d.]+s\b)|\bno tests ran\b")
_CUT = "... [%d lines cut; full output: /tmp/swe/last.log] ..."


def clean_text(text):
    """ANSI/OSC escapes removed; CRLF -> LF; a line redrawn with bare CRs keeps its last non-empty segment."""
    if not text:
        return ""
    if "\x1b" in text:
        text = _ANSI.sub("", text)
    text = text.replace("\r\n", "\n").replace("\x00", "")
    if "\r" in text:
        lines = []
        for ln in text.split("\n"):
            if "\r" in ln:
                segs = [s for s in ln.split("\r") if s.strip()]
                ln = segs[-1] if segs else ""
            lines.append(ln)
        text = "\n".join(lines)
    return text


def _long(line):
    return line if len(line) <= 400 else line[:200] + " ... " + line[-100:]


def _last_log():
    return os.path.join(swe_dir(), "last.log")


def _write_last_log(text):
    try:
        _atomic_write(_last_log(), text)
    except OSError:
        pass


def cap(text, limit, log=True, keep=SUMMARY_RE, head_share=0.34):
    """Fit text into `limit` chars: escapes stripped, CRs normalised, lines over 400 chars cut to 200 + ' ... ' + 100;
    when still too long keep head and tail lines around the marker '... [N lines cut; full output: /tmp/swe/last.log] ...'
    and always keep the last line matching `keep` (the pytest summary). With log=True the full text goes to last.log."""
    t = clean_text(text if isinstance(text, str) else str(text or ""))
    lines = [_long(x) for x in t.split("\n")]
    out = "\n".join(lines)
    limit = int(limit)
    if len(out) <= limit:
        return out
    if log:
        _LOG_PARTS.append(t)
        _write_last_log("\n\n".join(_LOG_PARTS))
    ki = None
    if keep is not None:
        for i in range(len(lines) - 1, -1, -1):
            if keep.search(lines[i]):
                ki = i
                break
    marker_len = len(_CUT % len(lines)) + 1
    budget = limit - marker_len - (len(lines[ki]) + 1 if ki is not None else 0)
    head_b = int(max(0, budget) * head_share)
    head, used = [], 0
    for i, ln in enumerate(lines):
        if used + len(ln) + 1 > head_b:
            break
        head.append(i)
        used += len(ln) + 1
    tail_b = max(0, budget) - used
    tail, used2 = [], 0
    lo = head[-1] + 1 if head else 0
    for i in range(len(lines) - 1, lo - 1, -1):
        if used2 + len(lines[i]) + 1 > tail_b:
            break
        tail.append(i)
        used2 += len(lines[i]) + 1
    tail.reverse()
    keep_sep = ki is not None and ki not in head and ki not in tail
    cut = len(lines) - len(head) - len(tail) - (1 if keep_sep else 0)
    parts = [lines[i] for i in head] + [_CUT % cut]
    if keep_sep:
        parts.append(lines[ki])
    parts += [lines[i] for i in tail]
    res = "\n".join(parts)
    return res if len(res) <= limit else res[:max(0, limit)]


def _ckpt_nonempty():
    try:
        for e in os.scandir(os.path.join(swe_dir(), "ckpt")):
            if e.name.endswith(".diff") and e.is_file() and e.stat().st_size > 0:
                return True
    except OSError:
        pass
    return False


def _restored_line(res, t):
    ok, msg, k = False, "", None
    if isinstance(res, bool):
        ok = res
    elif isinstance(res, tuple):
        ok = bool(res[0]) if res else False
        msg = res[1] if len(res) > 1 and isinstance(res[1], str) else ""
    elif isinstance(res, dict):
        ok, k, msg = bool(res.get("ok", True)), res.get("id"), str(res.get("msg") or "")
    elif isinstance(res, str):
        ok, msg = res.startswith("RESTORED"), res
    elif isinstance(res, int):
        ok, k = True, res
    if not ok:
        return msg if msg.startswith("RESTORE FAILED") else ""
    if msg.startswith("RESTORED checkpoint"):
        return msg.split("\n")[0]
    if k is None:
        m = re.search(r"#(\d+)", msg or "")
        k = m.group(1) if m else "?"
    return "RESTORED checkpoint #%s: the tree had no source change at t=%ds." % (k, int(t))


def late_guard(t=None, src=None):
    """At t >= 255 s with no source change, not finalized and a stored non-empty checkpoint: restore the best
    checkpoint (lazy _swe_ckpt import; skipped when missing). Returns the line to prefix the output with, or ''."""
    if _CACHE.get("in_guard"):
        return ""
    t = clock() if t is None else t
    if t < T_SAFE or not _ckpt_nonempty():
        return ""
    if state_load().get("final_done"):
        return ""
    if src is None:
        src = source_changed()
    if src:
        return ""
    try:
        import _swe_ckpt as K
    except ImportError:
        return ""
    fn = getattr(K, "auto_restore_if_empty", None)
    if fn is None:
        return ""
    _CACHE["in_guard"] = True
    try:
        res = fn()
    except Exception:
        return ""
    finally:
        _CACHE["in_guard"] = False
    return _restored_line(res, t)


def locator_over(st=None):
    """True once a later stage has worked (v10.1): the journal holds an edit, a finalize, a restore or a full verify,
    or the context meter has left the locator phase or seen status.py. Then LOCATOR ("Other stages: ignore this
    line") gives way to EDIT NOW on an empty tree (race 2: fastapi_15280's verifier and fastapi_14873's submitter
    read LOCATOR on an empty tree)."""
    st = state_load() if st is None else st
    ctx = st.get("ctx") if isinstance(st.get("ctx"), dict) else {}
    if (ctx.get("phase") or "locator") != "locator":
        return True
    if any(isinstance(x, list) and x[:1] == ["status"] for x in (ctx.get("tail") or [])):
        return True
    for e in reversed(journal_entries()):
        h = e.get("h")
        if h in ("edit", "finalize", "restore") or (h == "verify" and e.get("mode") != "repro-only"):
            return True
    return False


def hint(t=None, src=None, sha=None, ctx=None):
    """The single footer hint that applies (FINAL > EDIT NOW > TIME > FINISH > CONTEXT > LOCATOR), or ''. ctx: the
    context meter after this call (estimated tokens); CONTEXT shows at CONTEXT_TOKENS or more. EDIT NOW (v10.1):
    no source change at t >= T_EDIT_NOW, or at t >= T_LOCATOR once the locator stage is over; from T_TIME on it adds
    the finalize command. An empty tree is never told to end its stage."""
    t = clock() if t is None else t
    st = state_load()
    if st.get("final_done") and st.get("final_sha"):
        cur = sha if sha is not None else diff_sha()
        if cur == st.get("final_sha"):
            ft = st.get("final_t")
            return FINAL_HINT % int(ft if isinstance(ft, (int, float)) else t)
    if t >= T_LOCATOR:
        if src is None:
            src = source_changed()
        if not src and (t >= T_EDIT_NOW or locator_over(st)):
            return EDIT_NOW_HINT % int(t) + (EDIT_NOW_LATE if t >= T_TIME else "")
    if t >= T_TIME:
        return TIME_HINT
    if t >= T_FINISH:
        return FINISH_HINT
    if ctx is not None and ctx >= CONTEXT_TOKENS:
        return CONTEXT_HINT
    if t >= T_LOCATOR and not src:
        return LOCATOR_HINT
    return ""


def footer(t=None, src=None, sha=None, ctx=None):
    """'[t=Ns]', preceded by at most one hint line."""
    t = clock() if t is None else t
    try:
        h = hint(t, src, sha, ctx)
    except Exception:
        h = ""
    return (h + "\n" if h else "") + "[t=%ds]" % int(t)


# --------------------------------------------------------------------------------------------- token caps, context meter
def est_tokens(s):
    """Estimated prompt tokens of text: ASCII chars / 3 plus non-ASCII chars x 2.7. Race-1 and e74 traces: tool output
    is about 3.06 chars/token (p10 2.2-2.4); rendered tables that are 24-35% non-ASCII measured 0.36-0.63 chars/token."""
    if not s:
        return 0.0
    a = len(s.encode("ascii", "ignore"))
    return a / 3.0 + (len(s) - a) * 2.7


def _token_prefix(s, tokens):
    """The longest prefix of s whose est_tokens is at most `tokens`."""
    if est_tokens(s) <= tokens:
        return s
    used, i = 0.0, 0
    for i, ch in enumerate(s):
        used += (1 / 3.0) if ord(ch) < 128 else 2.7
        if used > tokens:
            return s[:i]
    return s


def ctx_next(ctx, name, est):
    """The context meter (state["ctx"]) after a `name` call that added `est` tokens to the stage's prompt. Stages are
    inferred from the prompts' fixed first steps: status.py starts a count (verifier step 1, and any stage recovering
    after compaction, which the prompts send to status.py); the first edit.py call after the locator starts the fixer's
    count with the views it made just before editing (the trailing view/grep calls, at most 3); the setup stage's
    install.py is not counted."""
    ctx = ctx if isinstance(ctx, dict) else {}
    try:
        n = float(ctx.get("n") or 0)
    except (TypeError, ValueError):
        n = 0.0
    phase = ctx.get("phase") or "locator"
    tail = [x for x in (ctx.get("tail") or []) if isinstance(x, list) and len(x) == 2]
    if name == "install" and all(h == "install" for h, _ in tail):
        n, est = 0.0, 0.0
    elif name == "status":
        n = 0.0
        # v10.2 (5.1): the first status.py ends the locator phase (the fixer's first step), the next one starts the
        # verifier's count (v10.1 kept "locator" at a status call)
        phase = {"locator": "fixer", "fixer": "verifier"}.get(phase, phase)
    elif name == "edit" and phase == "locator":
        carry, k = 0.0, 0
        for h, e in reversed(tail):
            if h not in ("view", "grep") or k >= 3:
                break
            carry += float(e or 0)
            k += 1
        n, phase = carry, "fixer"
    n += float(est)
    return {"n": round(n, 1), "phase": phase, "tail": (tail + [[name, round(float(est), 1)]])[-8:]}


def _ctx_record(name, est):
    def fn(s):
        s["ctx"] = ctx_next(s.get("ctx"), name, est)
        return s
    try:
        state_update(fn)
    except Exception:
        pass


def _in_est():
    """Estimated tokens the model wrote for this call: the command's arguments, a heredoc body, the call overhead."""
    try:
        args = " ".join(str(a) for a in sys.argv[1:])
    except Exception:
        args = ""
    return est_tokens(args) + float(_CACHE.get("in_stdin") or 0) + CTX_CALL


def _write_out(s):
    try:
        sys.stdout.flush()
    except Exception:
        pass
    try:
        buf = sys.stdout.buffer
        buf.write(s.encode("utf-8", "replace"))
        buf.flush()
    except (AttributeError, ValueError):
        try:
            sys.stdout.write(s)
            sys.stdout.flush()
        except Exception:
            pass
    except (BrokenPipeError, OSError):
        pass


def _compose(limit, tok_cap, head, body_t, tail_t, foot):
    """(output, head, tail) within `limit` chars and about `tok_cap` estimated tokens: the body is cut first (by chars,
    then shrunk until the token estimate fits), then the head and tail; the footer is always kept whole."""
    room = limit - 1 - len(foot) - 1                          # final newline; newline before the footer
    if tail_t and len(tail_t) > room // 2:
        tail_t = tail_t[:max(0, room // 2)]
    fixed = len(head) + (len(tail_t) + 1 if tail_t else 0)
    if fixed > room:
        head = head[:max(0, room - (len(tail_t) + 1 if tail_t else 0))]
    body_room = room - len(head) - (len(tail_t) + 1 if tail_t else 0) - 1

    def build(br):
        parts = [head]
        if body_t.strip():
            if br >= 40:
                parts.append(cap_text(body_t, br))
            elif br >= len(_CUT % 0):
                parts.append((_CUT % (body_t.count("\n") + 1))[:br])
        if tail_t:
            parts.append(tail_t)
        parts.append(foot)
        o = "\n".join(parts)
        return o[:limit - 1] if len(o) > limit - 1 else o
    out = build(body_room)
    for _ in range(8):                  # box drawing and other non-ASCII text: fit the token cap by shrinking the body
        over = est_tokens(out) - tok_cap
        if over <= 0 or body_room < 40 or not body_t.strip():
            break
        be = est_tokens(cap_text(body_t, body_room))
        body_room = max(0, min(body_room - 1, int(body_room * max(0.0, be - over) / be * 0.95))) if be else 0
        out = build(body_room)
    if est_tokens(out) > tok_cap:       # still over (non-ASCII head or tail): cut the text before the footer
        keep = _token_prefix(out[:len(out) - len(foot)].rstrip("\n"), max(0.0, tok_cap - est_tokens(foot) - 1))
        out = (keep + "\n" + foot) if keep else foot
    return out, head, tail_t


def emit(name, first_line, body="", cap=None, tail=None, log_text=None, src=None, sha=None, plain=False):
    """Print a helper's whole output and return it: [RESTORED line], the status/verdict line, the body capped to fit,
    `tail` lines (kept whole), then the footer. Total length stays within cap (default CAPS[name]) and the estimated
    tokens within CAP_TOKENS[name] (and cap / 3); the full text goes to $SWE/last.log (log_text replaces the body
    there when given). The call is added to the context meter; at CONTEXT_TOKENS the footer carries CONTEXT_HINT.
    plain (v10.2, the refusals of 5.9): the footer is only [t=Ns], without a hint line, and no git call is made."""
    limit = int(cap or CAPS.get(name, 2000))
    tok_cap = min(float(CAP_TOKENS.get(name, limit // 3)), limit / 3.0)
    try:
        t = clock()
    except Exception:
        t = 0.0
    pre = ""
    if plain:
        src = True if src is None else src
    if src is None and t >= T_LOCATOR:       # v10.1: EDIT NOW outranks FINISH and TIME, so it is needed late too
        src = source_changed()
    if t >= T_SAFE and not plain:
        try:
            pre = late_guard(t, src)
        except Exception:
            pre = ""
        if pre.startswith("RESTORED"):
            src, sha = True, None
    try:
        foot = "[t=%ds]" % int(t) if plain else footer(t, src, sha)
    except Exception:
        foot = "[t=%ds]" % int(t)
    head = clean_text(first_line if isinstance(first_line, str) else str(first_line)).strip("\n")
    if pre:
        head = pre + "\n" + head
    body_t = "\n".join(str(x) for x in body) if isinstance(body, (list, tuple)) else str(body or "")
    tail_t = "\n".join(str(x) for x in tail if x) if isinstance(tail, (list, tuple)) else str(tail or "")
    out, head_c, tail_c = _compose(limit, tok_cap, head, body_t, tail_t, foot)
    in_est = _in_est()
    try:
        proj = ctx_next(state_load().get("ctx"), name, in_est + est_tokens(out))["n"]
    except Exception:
        proj = 0.0
    if proj >= CONTEXT_TOKENS and not plain:
        try:
            foot2 = footer(t, src, sha, proj)
        except Exception:
            foot2 = foot
        if foot2 != foot:
            foot = foot2
            out, head_c, tail_c = _compose(limit, tok_cap, head, body_t, tail_t, foot)
    head, tail_t = head_c, tail_c
    _ctx_record(name, in_est + est_tokens(out))
    full = [head, clean_text(log_text if log_text is not None else body_t)]
    if tail_t:
        full.append(tail_t)
    full.append(foot)
    if _LOG_PARTS:
        full.append("\n--- sections cut above, in full ---\n" + "\n\n".join(_LOG_PARTS))
    _write_last_log("\n".join(full) + "\n")
    _write_out(out + "\n")
    return out


def cap_text(text, limit):
    """cap() without writing last.log (emit writes the whole output there itself)."""
    return cap(text, limit, log=False)


def print_usage(name, usage=None):
    """Print 'USAGE: <usage>' plus the footer (a helper called without its required argument)."""
    return emit(name, "USAGE: " + (usage or _main_usage()))


# ------------------------------------------------------------------------------------- v10.2 locator budget and digest
# docs/v10/SPEC_v10_2.md 5.1-5.3: the locator phase is open while the context meter's phase is "locator" (status.py or
# edit.py ends it). While it is open, the gated helpers (locate, grep, view, run, verify --repro-only) count their
# calls and refuse from the 15th call or from t=90s, with a draft plan built from what the locator's calls showed.
LOC_CLOSED_HEAD = ("LOCATOR CLOSED at t=%ds after %d calls: nothing ran. Locator: reply now with your plan; a draft "
                   "from your calls:")
LOC_CLOSED_LATER = "Any later stage: run python3 /tmp/swe/status.py first, then repeat this call."
LOC_CLOSED_SHORT = ("LOCATOR CLOSED: nothing ran. Reply with your plan now (the draft is above); a later stage runs "
                    "python3 /tmp/swe/status.py first.")
DEF_BUDGET = 0.15           # s: enclosing defs for the digest and the draft plan come from the marshal cache only


def ctx_phase(st):
    ctx = st.get("ctx") if isinstance(st.get("ctx"), dict) else {}
    return ctx.get("phase") or "locator"


def loc_open(st=None):
    """True while the locator phase is open (the context meter's phase is still 'locator')."""
    return ctx_phase(state_load() if st is None else st) == "locator"


def loc_state(st):
    loc = st.get("loc") if isinstance(st.get("loc"), dict) else {}
    d = _loc_defaults()
    d.update((k, v) for k, v in loc.items() if k in d)
    return d


def real_views(st):
    """[(t, rel, a, b)] of the view.py ranges recorded in the state (never the derived rows of grep, locate or verify),
    newest first; test and config files (the protected paths) are left out."""
    out = []
    for f, lst in (st.get("views") or {}).items():
        if not isinstance(f, str) or not f or _protected_git(f):
            continue
        for v in lst if isinstance(lst, list) else []:
            if isinstance(v, list) and len(v) == 3 and all(isinstance(x, (int, float)) for x in v):
                out.append((float(v[2]), f, int(v[0]), int(v[1])))
    out.sort(key=lambda x: (-x[0], x[1], x[2]))
    return out


def cached_defs(items, budget=DEF_BUDGET):
    """{(rel, line): qualified name of the innermost def or class holding that line}, read from the marshal index
    cache only (never a parse; an entry whose file changed since it was cached is skipped); {} without a cache."""
    out = {}
    if not items:
        return out
    end = time.monotonic() + budget
    try:
        import marshal
        import _swe_index as I
        path = I.default_cache_path()
        if not path or not os.path.isfile(path) or os.path.getsize(path) > (64 << 20):
            return out
        cache = I._load_marshal(path)
    except Exception:
        return out
    files = (cache or {}).get("files") or {}
    for rel, line in items:
        if time.monotonic() > end:
            break
        rec = files.get(rel)
        if not rec or not rec[4]:
            continue
        try:
            key = I._stat_key(os.path.join(ws(), rel))
            if key is None or (rec[0], rec[1]) != tuple(key):
                continue
            syms = marshal.loads(rec[4])[0]
        except Exception:
            continue
        best = None
        for s in syms:
            if s[1] != "module" and s[2] <= line <= s[3] and (best is None or (s[2], -s[3]) > (best[2], -best[3])):
                best = s
        if best is not None:
            out[(rel, line)] = best[0]
    return out


def repro_fails(st):
    """True when the saved reproduction has a valid claim that failed or hung on original."""
    r = st.get("repro") if isinstance(st.get("repro"), dict) else {}
    orig = r.get("orig") if isinstance(r.get("orig"), dict) else {}
    return any(isinstance(v, dict) and v.get("status") in ("FAIL", "HANG") and not v.get("broken")
               for v in orig.values())


def locate_top_entries(st):
    """[(rel, symbol, start, end)] of the last locate.py ranking (state.locate_top)."""
    out = []
    for e in st.get("locate_top") or []:
        if isinstance(e, (list, tuple)) and len(e) == 4 and isinstance(e[0], str) and e[0]:
            try:
                out.append((e[0], str(e[1] or ""), int(e[2] or 0), int(e[3] or 0)))
            except (TypeError, ValueError):
                continue
    return out


def draft_plan(st):
    """(FILES line, REPRO word) for a closed locator (5.3): up to 2 files ranked by their number of real views (ties:
    the latest), each with its latest real view range and enclosing def; else the first locate_top entry with its
    symbol span; else FILES: none seen. REPRO is 'fails on original' when a valid claim failed or hung on original."""
    per = {}
    for t, f, a, b in real_views(st):
        c = per.setdefault(f, [0, t, a, b])
        c[0] += 1
    ranked = sorted(per.items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0]))[:2]
    parts = []
    if ranked:
        defs = cached_defs([(f, (c[2] + c[3]) // 2) for f, c in ranked])
        for f, c in ranked:
            d = defs.get((f, (c[2] + c[3]) // 2))
            parts.append("%s:%d-%d%s" % (f, c[2], c[3], " (%s)" % d if d else ""))
    else:
        top = locate_top_entries(st)
        if top:
            f, sym, a, b = top[0]
            parts.append(("%s:%d-%d" % (f, a, b) if a > 0 and b >= a else f) + (" (%s)" % sym if sym else ""))
    files = "FILES: " + ("; ".join(parts) if parts else "none seen")
    return _short(files, 320), ("fails on original" if repro_fails(st) else "none")


def loc_gate(kind):
    """None when this gated call may run (counted in state.loc.calls while the locator phase is open), else the text
    of its refusal. A single state read, plus one state_update while the locator phase is open. Refused while the phase
    is open and 14 calls ran or t >= 90 s; the 3rd and later consecutive refusals are the short form (the loop guard)."""
    try:
        st = state_load()
    except Exception:
        return None
    if not loc_open(st):
        return None
    t = float(clock())
    box = {}

    def fn(s):
        if not loc_open(s):
            box["pass"] = True
            return s
        loc = loc_state(s)
        why = "calls" if loc["calls"] >= LOC_MAX_CALLS else ("time" if t >= T_LOC_CLOSE else None)
        if why is None:
            loc["calls"] += 1
            loc["refused"] = 0
            box["pass"] = True
        else:
            loc["refused"] += 1
            if loc.get("close_t") is None:
                loc["close_t"], loc["close_why"] = round(t, 1), why
            box.update(why=why, n=loc["refused"], calls=loc["calls"])
        s["loc"] = loc
        return s
    try:
        st = state_update(fn)
    except Exception:
        return None
    if box.get("pass"):
        return None
    journal({"h": "gate", "kind": kind, "why": box["why"],
             "msg": "gate: %s refused (locator closed: %s)" % (kind, "14 calls" if box["why"] == "calls" else "t>=90s")})
    if box["n"] >= 3:
        return LOC_CLOSED_SHORT
    files, repro = draft_plan(st)
    return "\n".join([LOC_CLOSED_HEAD % (int(t), box["calls"]), files, "REPRO: " + repro, LOC_CLOSED_LATER])


def refuse(name, text):
    """Print a v10.2 refusal (nothing ran): within REFUSAL_CAP chars, the footer only [t=Ns]."""
    return emit(name, text, "", REFUSAL_CAP, plain=True)


def gate(name, kind=None):
    """loc_gate for the helper `name`: prints the refusal and returns True when the call must not run."""
    msg = loc_gate(kind or name)
    if msg is None:
        return False
    refuse(name, msg)
    return True


def loc_count(field):
    """Count an executed run (runs) or a new reproduction (repros) while the locator phase is open."""
    def fn(s):
        if loc_open(s):
            loc = loc_state(s)
            loc[field] = int(loc.get(field) or 0) + 1
            s["loc"] = loc
        return s
    try:
        state_update(fn)
    except Exception:
        pass


# ----------------------------------------------------------------------------------------------------------- lifecycle
class HelperTimeout(Exception):
    pass


def _arm_watchdog():
    try:
        import signal
        if not hasattr(signal, "setitimer"):
            return None
        secs = max(4.0, real_budget(HELPER_LIMIT))

        def fire(signum, frame):
            raise HelperTimeout("stopped after %ds (helper time limit)" % int(secs))
        signal.signal(signal.SIGALRM, fire)
        signal.setitimer(signal.ITIMER_REAL, secs)
        return signal
    except Exception:
        return None


def _where(tb):
    last = None
    while tb is not None:
        fn = tb.tb_frame.f_code.co_filename
        if _under(_real(fn), _real(_HERE)) or os.path.basename(fn).startswith("_swe_"):
            last = "%s:%d" % (os.path.basename(fn), tb.tb_lineno)
        tb = tb.tb_next
    return last


def safe_main(name, main):
    """Run main(); never raise and never exit non-zero. UsageError prints its message; any other exception prints
    'HELPER ERROR <name>: <Type>: <msg>' (300 chars or fewer). stderr goes to stdout; children are killed on exit."""
    try:
        sys.stderr = sys.stdout
    except Exception:
        pass
    try:
        import warnings
        warnings.simplefilter("ignore")
    except Exception:
        pass
    sig = _arm_watchdog()
    try:
        main()
    except UsageError as e:
        try:
            emit(name, str(e))
        except Exception:
            _write_out(str(e)[:300] + "\n")
    except SystemExit as e:
        if e.code not in (None, 0) and not isinstance(e.code, int):
            _write_out(_short("HELPER ERROR %s: exit: %s" % (name, e.code), 300) + "\n")
    except BaseException as e:
        where = _where(sys.exc_info()[2])
        msg = "HELPER ERROR %s: %s: %s" % (name, type(e).__name__, " ".join(str(e).split()) or "-")
        if where:
            loc = " (%s)" % where
            msg = (msg[:300 - len(loc) - 3] + "..." if len(msg) + len(loc) > 300 else msg) + loc
        _write_out(msg[:300] + "\n")
        try:
            journal({"h": name, "msg": msg[:200]})
        except Exception:
            pass
    finally:
        if sig is not None:
            try:
                sig.setitimer(sig.ITIMER_REAL, 0)
            except Exception:
                pass
        for pg in list(_LIVE):
            _killpg(pg)
        try:
            sys.stdout.flush()
        except Exception:
            pass


def _precompile(d, names, fresh):
    """Write checked-hash .pyc files for the libraries in an install dir: main scripts are always compiled from source,
    but `import _swe_common` (and the gate/index libraries) then skip ~10-40 ms of compiling per helper call. Python
    re-validates each pyc against the source hash, so a stale one is never used."""
    try:
        import importlib.util
        todo = []
        for n in names:
            path = os.path.join(d, n)
            pyc = importlib.util.cache_from_source(path)
            if n in fresh or not os.path.exists(pyc):
                todo.append((path, pyc))
        if todo:
            import py_compile
            for path, pyc in todo:
                py_compile.compile(path, cfile=pyc, doraise=True,
                                   invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH)
    except Exception:
        pass


def install_all(src=None):
    """Copy every *.py next to this file into each install_targets() dir (atomic, 0644, skipped when identical), write
    VERSION when it differs and t0 when absent. -> [(target, copied, skipped, error | None)]."""
    src = src or _HERE
    names = sorted(f for f in os.listdir(src) if f.endswith(".py") and not f.startswith("."))
    out = []
    for tgt in install_targets():
        copied = skipped = 0
        err = None
        fresh = set()
        try:
            os.makedirs(tgt, exist_ok=True)
            same_dir = _real(tgt) == _real(src)
            for n in names:
                if same_dir:
                    skipped += 1
                    continue
                with open(os.path.join(src, n), "rb") as f:
                    data = f.read()
                d = os.path.join(tgt, n)
                try:
                    with open(d, "rb") as f:
                        if f.read() == data:
                            skipped += 1
                            continue
                except OSError:
                    pass
                _atomic_write(d, data)
                fresh.add(n)
                copied += 1
            vpath = os.path.join(tgt, "VERSION")
            try:
                with open(vpath) as f:
                    vok = f.read().strip() == VERSION
            except OSError:
                vok = False
            if not vok:
                _atomic_write(vpath, VERSION + "\n")
            tp = os.path.join(tgt, "t0")
            if not os.path.exists(tp):
                try:
                    fd = os.open(tp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
                    try:
                        os.write(fd, repr(time.time()).encode())
                    finally:
                        os.close(fd)
                except FileExistsError:
                    pass
            if not same_dir:
                _precompile(tgt, [n for n in names if n.startswith("_")], fresh)
        except OSError as e:
            err = "%s: %s" % (type(e).__name__, e)
        out.append((tgt, copied, skipped, err))
    return out


def installed():
    """True when this file runs from an installed helper dir (VERSION starting with v10 next to it)."""
    try:
        with open(os.path.join(_HERE, "VERSION")) as f:
            return f.read(16).startswith("v10")
    except OSError:
        return False


def bootstrap():
    """First call of every helper's main: when running from a non-installed dir (the skill wrapper's temp copy),
    silently install all helpers; then make sure a stale state from another task is reset."""
    if not installed():
        try:
            install_all()
        except Exception:
            pass
    try:
        state_load()
    except Exception:
        pass
