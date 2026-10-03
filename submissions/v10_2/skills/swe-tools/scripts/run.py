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

# Run one shell command in the repository with a hard timeout that kills the whole process group, and print compact
# output: line 1 is exit=N or TIMEOUT, repeated lines are collapsed, the pytest summary line is always kept, and the
# full output goes to /tmp/swe/last.log. Skill form: args cmd and timeout.
# v10.2 (SPEC_v10_2 5.5): before anything runs, in this order: the locator gate, the locator's probe limit (3 runs
# before the plan), OFFLINE (network commands), SAME RUN (the same command twice on the same tree with the same
# output), the python3 -c guard (literal \n sequences) and stdin for a bare interpreter (python3 <<'EOF' ... EOF).
import re

NAME = "run"
USAGE = 'python3 /tmp/swe/run.py [--timeout N] "COMMAND"'
FLAGS = {"timeout": "int", "cmd": "str"}
DISABLED = "pytest is disabled in this environment"
DISABLED_NOTE = ("Test runners are disabled by the harness here: check behaviour with a reproduction "
                 "(python3 /tmp/swe/verify.py --repro-only) instead.")
_OPS = {"|", "||", "&&", ";", "&", ">", ">>", "<", "2>&1", "2>", "|&", "1>&2", "&>"}
PROBE_LIMIT = ("PROBE LIMIT: %d runs used before the plan; nothing ran. Locator: reply with your plan; the fixer can run "
               "code after python3 /tmp/swe/status.py." % C.LOC_MAX_RUNS)
OFFLINE = ("OFFLINE: the sandbox has no network; nothing ran. Use the repository and its installed packages "
           "(python3 /tmp/swe/view.py --obj NAME shows a dependency's source).")
SAME_RUN = ("SAME RUN: this command already ran twice on this tree with the same output (t=%ds, t=%ds); nothing ran. "
            "Change the command or the code.")
PY_C = ("PYTHON -c: the code has literal \\n sequences, which Python cannot parse; nothing ran. Pipe multi-line code "
        "instead: python3 /tmp/swe/run.py python3 <<'EOF' ... EOF")
NO_INPUT = ("NO INPUT: %s got no code on stdin; nothing ran. Pipe it: python3 /tmp/swe/run.py %s <<'EOF' ... EOF")
BARE = ("python3", "python", "python3 -", "python -", "python3 -u", "bash", "sh")   # read the heredoc from stdin
RUNS_KEPT = 50             # SAME RUN keys kept in state.runs
_PY = re.compile(r"^python(?:\d+(?:\.\d+)?)?$")
_WRAP = frozenset(("sudo", "env", "nohup", "time", "command", "exec", "nice", "stdbuf", "xargs"))
_NET_GIT = frozenset(("fetch", "pull", "clone", "push", "ls-remote"))
_OFFLINE_RAW = re.compile(r"(?:^|[\s;&|(`])(?:curl|wget)(?=\s|$)|\bpip\d*(?:\.\d+)?\s+(?:install|download)\b|"
                          r"\b(?:apt|apt-get|conda|mamba|npm)\s+(?:-\S+\s+)*install\b|"
                          r"\bgit\s+(?:-\S+\s+)*(?:fetch|pull|clone|push|ls-remote)\b")


def join_command(words):
    """One word is the command itself; several words (split by the calling shell) are re-quoted so the command keeps
    its argument boundaries, except bare shell operators."""
    if len(words) == 1:
        return words[0]
    import shlex
    return " ".join(w if w in _OPS else shlex.quote(w) for w in words)


def collapse(text):
    """Runs of identical lines become 'line (xN)'; runs of blank lines become one blank line; trailing blanks dropped."""
    out, prev, n = [], None, 0

    def flush():
        if prev is None:
            return
        if n > 1 and prev.strip():
            out.append("%s (x%d)" % (prev, n))
        else:
            out.append(prev)
    for line in text.split("\n"):
        if line == prev:
            n += 1
            continue
        flush()
        prev, n = line, 1
    flush()
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out)


def fmt_secs(s):
    return ("%d" % s) if abs(s - round(s)) < 0.05 else ("%.1f" % s)


def segments(cmd):
    """The simple commands of a shell command line as word lists (split at | || && ; & ( ) and redirections, quotes
    respected), or None when it does not tokenise (unbalanced quotes)."""
    import shlex
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        toks = list(lex)
    except ValueError:
        return None
    segs, cur = [], []
    for t in toks:
        if t and all(c in "();<>|&" for c in t):
            if cur:
                segs.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur:
        segs.append(cur)
    return segs


def _strip_prefix(words):
    """Words of a simple command without leading VAR=value assignments and wrappers (sudo, env, timeout N, ...)."""
    i = 0
    while i < len(words):
        w = words[i]
        if re.match(r"^[A-Za-z_]\w*=", w):
            i += 1
        elif w in _WRAP:
            i += 1
            while i < len(words) and words[i].startswith("-"):
                i += 1
        elif w == "timeout":
            i += 1
            while i < len(words) and (words[i].startswith("-") or re.match(r"^\d+(\.\d+)?[smhd]?$", words[i])):
                i += 1
        else:
            break
    return words[i:]


def is_network(words):
    """True for a simple command that needs the network (5.5 OFFLINE): curl, wget, pip/pip3 install or download
    (also python -m pip and uv pip), apt/apt-get/conda/npm install, git fetch/pull/clone/push/ls-remote."""
    w = _strip_prefix(words)
    if not w:
        return False
    head, rest = w[0].rsplit("/", 1)[-1], w[1:]
    if head in ("curl", "wget"):
        return True
    if re.match(r"^pip\d*(\.\d+)?$", head):
        return bool(rest) and rest[0] in ("install", "download")
    if _PY.match(head):
        j = rest.index("-m") if "-m" in rest else -1
        return j >= 0 and rest[j + 1:j + 3] in (["pip", "install"], ["pip", "download"])
    if head == "uv":
        return rest[:2] in (["pip", "install"], ["pip", "download"])
    if head in ("apt", "apt-get", "conda", "mamba", "micromamba", "npm"):
        return "install" in [x for x in rest if not x.startswith("-")][:1]
    if head == "git":
        i = 0
        while i < len(rest) and rest[i].startswith("-"):
            i += 2 if rest[i] in ("-C", "-c") else 1
        return i < len(rest) and rest[i] in _NET_GIT
    return False


def offline(cmd):
    """True when a command (or a bash script piped to bash/sh) contains a simple command that needs the network."""
    segs = segments(cmd)
    if segs is None:
        return bool(_OFFLINE_RAW.search(cmd))
    return any(is_network(sg) for sg in segs)


def py_c_broken(cmd):
    """True when the command is python/python3 -c CODE whose CODE has a literal backslash-n and does not compile
    (the model wrote \\n for newlines: 30 SyntaxError calls in 10 golden cases, 13 in a row in one)."""
    segs = segments(cmd)
    if not segs:
        return False
    for sg in segs:
        w = _strip_prefix(sg)
        if not w or not _PY.match(w[0].rsplit("/", 1)[-1]):
            continue
        i = 1
        while i < len(w) and w[i].startswith("-") and w[i] != "-c":
            i += 1
        if i + 1 < len(w) and w[i] == "-c":
            code = w[i + 1]
            if "\\n" not in code or "\n" in code:
                return False
            try:
                compile(code, "<string>", "exec", dont_inherit=True)
            except SyntaxError:
                return True
            except (ValueError, TypeError):
                return False
        return False
    return False


def effective_timeout(a, t_import=None):
    """(seconds, notes): --timeout (default 20; v10.2: max(20, t_import + 15) once the package import time has been
    measured) clamped to 1..RUN_MAX, then by the remaining task time."""
    notes = []
    want = C.RUN_DEFAULT
    if t_import is not None and "timeout" not in a["_given"]:
        want = max(C.RUN_DEFAULT, int(float(t_import) + 15.5))
    if "timeout" in a["_bad"]:
        notes.append("NOTE: --timeout must be an integer; used %d" % want)
    elif a.get("timeout") is not None:
        want = a["timeout"]
    want = max(1, min(C.RUN_MAX, int(want)))
    secs = C.real_budget(want)
    if secs < want - 0.5:
        notes.append("NOTE: timeout cut to %ss by the remaining task time." % fmt_secs(secs))
    return secs, notes


def tree_key():
    """The tree SAME RUN compares: git status (changed tracked and untracked paths, the submit guard's excludes
    ignored) plus the size and mtime of each listed path. One git call: diff_sha() costs three (36 ms measured) and put
    run.py's overhead past its 100 ms budget. An edit between two runs changes it, so the third run is allowed.
    Computed only for a command that already ran (a repeat): the git call cost 25-30 ms of every run.py call (v10.2
    min 75 ms against v10.1's 44 ms at load 20), and a first run can never be refused."""
    rc, out = C.git(C.NO_GUARD + ["status", "--porcelain", "-z", "--untracked-files=all"])
    if rc != 0:
        return "status failed"
    parts = [out]
    for rec in out.split("\0"):
        p = rec[3:] if len(rec) > 3 else ""
        if p:
            parts.append("%s %s" % (p, C._stat_sig(p)))
    return C.sha1_hex("\0".join(parts))


def run_entries(st, key):
    """[[t, output sha, tree key or None]] of this command's earlier runs, oldest first (state.runs[key])."""
    return [x for x in ((st.get("runs") or {}).get(key) or [])
            if isinstance(x, list) and len(x) in (2, 3)]


def _record_run(key, out_sha, tkey):
    t = round(float(C.clock()), 1)

    def fn(s):
        runs = s.get("runs") if isinstance(s.get("runs"), dict) else {}
        lst = [x for x in (runs.pop(key, None) or []) if isinstance(x, list) and len(x) in (2, 3)][-2:]
        runs[key] = lst + [[t, out_sha, tkey]]
        while len(runs) > RUNS_KEPT:
            runs.pop(next(iter(runs)))
        s["runs"] = runs
        return s
    try:
        C.state_update(fn)
    except Exception:
        pass


def same_run(prev, tkey):
    """(t1, t2) when the command's last two runs gave the same output, the last on this tree (tkey) and the one before
    on this tree too, or of unknown tree (a first run records none); else None."""
    if len(prev) >= 2 and prev[-1][1] == prev[-2][1] and len(prev[-1]) == 3 and prev[-1][2] == tkey and \
            (len(prev[-2]) < 3 or prev[-2][2] in (None, tkey)):
        return prev[-2][0], prev[-1][0]
    return None


def main():
    C.bootstrap()
    a = C.parse_args(sys.argv[1:], FLAGS, (), usage=USAGE, interspersed=False)
    cmd = a.cmd if a.cmd else join_command(a["_"])
    if not cmd or not cmd.strip():
        C.print_usage(NAME, USAGE)
        return
    if C.gate(NAME):
        return
    st = C.state_load()
    in_loc = C.loc_open(st)
    if in_loc and int(C.loc_state(st).get("runs") or 0) >= C.LOC_MAX_RUNS:
        C.refuse(NAME, PROBE_LIMIT)
        return
    bare = " ".join(cmd.split()) in BARE
    text = C.read_stdin() if bare else None
    if offline(cmd) or (bare and text and cmd.split()[0] in ("bash", "sh") and offline(text)):
        C.refuse(NAME, OFFLINE)
        return
    key = C.sha1_hex("%s\0%s" % (cmd, C.sha1_hex(text) if text else ""))[:16]
    prev = run_entries(st, key)
    tkey = tree_key() if prev else None               # a repeat: the tree it runs on (a first run never pays for it)
    hit = same_run(prev, tkey) if prev else None
    if hit:
        C.refuse(NAME, SAME_RUN % (int(hit[0]), int(hit[1])))
        return
    if py_c_broken(cmd):
        C.refuse(NAME, PY_C)
        return
    if bare and not (text or "").strip():
        word = cmd.split()[0]
        C.refuse(NAME, NO_INPUT % (word, word))
        return
    t_import = st.get("t_import") if isinstance(st.get("t_import"), (int, float)) else None
    secs, tail = effective_timeout(a, t_import)
    env = dict(os.environ)
    env.update(PYTHONDONTWRITEBYTECODE="1", NO_COLOR="1", TERM="dumb", COLUMNS="120")
    rc, out = C.sh(cmd, secs, cwd=C.ws(), env=env, input=text if bare else None)
    if in_loc:
        C.loc_count("runs")
    if rc is None:
        slow = ("; the package import alone takes %ds here" % int(t_import + 0.5)) if t_import and t_import >= 5 else ""
        first = ("TIMEOUT after %ss (partial output below)%s. If the issue is about a hang or loop, this may be the bug."
                 % (fmt_secs(secs), slow))
    else:
        first = "exit=%d" % rc
    full = C.clean_text(out)
    body = collapse(full) or "(no output)"
    if DISABLED in full:
        tail.append(DISABLED_NOTE)
    note = C.repeat_note(NAME, "%s\0%s" % (cmd, C.sha1_hex(full)))
    if note:
        tail.append(note)
    _record_run(key, C.sha1_hex(full), tkey)
    C.journal({"h": NAME, "msg": "run %s: %s" % (C._short(cmd, 70), first.split(" (")[0])})
    C.emit(NAME, first, body, C.CAPS[NAME], tail=tail, log_text=full)


if __name__ == "__main__":
    C.safe_main(NAME, main)
