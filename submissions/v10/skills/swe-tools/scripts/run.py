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

NAME = "run"
USAGE = 'python3 /tmp/swe/run.py [--timeout N] "COMMAND"'
FLAGS = {"timeout": "int", "cmd": "str"}
DISABLED = "pytest is disabled in this environment"
DISABLED_NOTE = ("Test runners are disabled by the harness here: check behaviour with a reproduction "
                 "(python3 /tmp/swe/verify.py --repro-only) instead.")
_OPS = {"|", "||", "&&", ";", "&", ">", ">>", "<", "2>&1", "2>", "|&", "1>&2", "&>"}


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


def effective_timeout(a):
    """(seconds, notes): --timeout (default 20) clamped to 1..RUN_MAX, then by the remaining task time."""
    notes = []
    want = C.RUN_DEFAULT
    if "timeout" in a["_bad"]:
        notes.append("NOTE: --timeout must be an integer; used %d" % C.RUN_DEFAULT)
    elif a.get("timeout") is not None:
        want = a["timeout"]
    want = max(1, min(C.RUN_MAX, int(want)))
    secs = C.real_budget(want)
    if secs < want - 0.5:
        notes.append("NOTE: timeout cut to %ss by the remaining task time." % fmt_secs(secs))
    return secs, notes


def main():
    C.bootstrap()
    a = C.parse_args(sys.argv[1:], FLAGS, (), usage=USAGE, interspersed=False)
    cmd = a.cmd if a.cmd else join_command(a["_"])
    if not cmd or not cmd.strip():
        C.print_usage(NAME, USAGE)
        return
    secs, tail = effective_timeout(a)
    env = dict(os.environ)
    env.update(PYTHONDONTWRITEBYTECODE="1", NO_COLOR="1", TERM="dumb", COLUMNS="120")
    rc, out = C.sh(cmd, secs, cwd=C.ws(), env=env)
    if rc is None:
        first = ("TIMEOUT after %ss (partial output below). If the issue is about a hang or loop, this may be the bug."
                 % fmt_secs(secs))
    else:
        first = "exit=%d" % rc
    full = C.clean_text(out)
    body = collapse(full) or "(no output)"
    if DISABLED in full:
        tail.append(DISABLED_NOTE)
    note = C.repeat_note(NAME, "%s\0%s" % (cmd, C.sha1_hex(full)))
    if note:
        tail.append(note)
    C.journal({"h": NAME, "msg": "run %s: %s" % (C._short(cmd, 70), first.split(" (")[0])})
    C.emit(NAME, first, body, C.CAPS[NAME], tail=tail, log_text=full)


if __name__ == "__main__":
    C.safe_main(NAME, main)
