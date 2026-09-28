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

# Bounded git grep over the repository: source files first, tests excluded unless --tests, each hit grouped under
# its enclosing def/class from the AST index. Output 1,800 chars or fewer.
import re

USAGE = 'python3 /tmp/swe/grep.py "REGEX" [--tests] [--path DIR] [--max N]'
FLAGS = {"regex": "str", "tests": "bool", "path": "str", "max": "int"}
NAME = "grep"
MAX_DEFAULT, MAX_LO, MAX_HI = 40, 1, 80
PER_FILE = 5
LINE_CUT = 160
DEADLINE = 5
FOOTER_RESERVE = 300
DOC_DIRS = frozenset(("docs", "docs_src", "examples", "benchmarks"))
TEST_EXCLUDES = [":(exclude,glob)%s" % g for g in ("tests/**", "test/**", "testing/**", "**/tests/**", "**/test/**",
                                                     "**/test_*.py", "**/*_test.py", "**/conftest.py")]
_NO_PCRE = ("perl-compatible", "use_libpcre", "not compiled", "pcre")


def is_test_path(rel):
    """The test rules of is_protected: test_*.py, *_test.py, conftest.py, a tests/test/testing root dir, or a
    nested tests/ or test/ dir (a nested testing/ package is source)."""
    parts = rel.split("/")
    b = parts[-1]
    if b == "conftest.py" or (b.endswith(".py") and (b.startswith("test_") or b.endswith("_test.py"))):
        return True
    if len(parts) > 1 and parts[0] in ("tests", "test", "testing"):
        return True
    return any(p in ("tests", "test") for p in parts[1:-1])


def to_ere(rx):
    """Python-style regex -> POSIX ERE for git grep -E (used only when git has no PCRE)."""
    out, i, inb = [], 0, False
    simple = {"d": "[0-9]", "D": "[^0-9]", "s": "[[:space:]]", "S": "[^[:space:]]", "w": "[[:alnum:]_]",
              "W": "[^[:alnum:]_]"}
    inner = {"d": "0-9", "s": "[:space:]", "w": "[:alnum:]_"}
    while i < len(rx):
        ch = rx[i]
        if ch == "\\" and i + 1 < len(rx):
            nx = rx[i + 1]
            if inb and nx in inner:
                out.append(inner[nx])
            elif not inb and nx in simple:
                out.append(simple[nx])
            elif inb:
                out.append(nx if nx not in "]^-\\" else "\\" + nx)
            else:
                out.append(ch + nx)
            i += 2
            continue
        if not inb and rx.startswith("(?:", i):
            out.append("(")
            i += 3
            continue
        if not inb and rx.startswith("(?P<", i):
            j = rx.find(">", i)
            out.append("(")
            i = j + 1 if j > 0 else i + 4
            continue
        if not inb and ch in "*+?" and i + 1 < len(rx) and rx[i + 1] == "?":
            out.append(ch)
            i += 2
            continue
        if ch == "[" and not inb:
            inb = True
            out.append(ch)
            if rx.startswith("^", i + 1):
                out.append("^")
                i += 1
            if rx.startswith("]", i + 1):
                out.append("]")
                i += 1
            i += 1
            continue
        if ch == "]" and inb:
            inb = False
        out.append(ch)
        i += 1
    return "".join(out)


def _no_pcre(s):
    s["grep_pcre"] = False
    return s


def run_grep(ws, rx, pathspec, tests, deadline, no_index_dir=None):
    """(rc, text, mode). Prefers PCRE (Python regex syntax); falls back to ERE when git lacks PCRE."""
    st = C.state_load()
    modes = ["-E"] if st.get("grep_pcre") is False else ["-P", "-E"]
    rc, out, mode = None, "", modes[0]
    for mode in modes:
        pat = rx if mode == "-P" else to_ere(rx)
        argv = ["git", "-c", "core.quotepath=off", "grep", "-n", "-z", "-I", "--no-color"]
        if no_index_dir:
            argv.append("--no-index")
        argv += [mode, "-e", pat, "--"] + pathspec
        if not tests and not no_index_dir:
            argv += TEST_EXCLUDES
        rc, out = C.sh(argv, deadline, cwd=no_index_dir or ws)
        low = (out or "").lower()
        if mode == "-P" and rc not in (0, 1, None) and any(k in low for k in _NO_PCRE) and "fatal" in low:
            C.state_update(_no_pcre)
            continue
        break
    return rc, out or "", mode


def parse_hits(out):
    hits = []
    for ln in out.split("\n"):
        if ln.count("\0") < 2:
            continue
        path, num, text = ln.split("\0", 2)
        if num.isdigit():
            hits.append((path, int(num), text))
    return hits


def _prio(path, tests_first=False):
    if tests_first and is_test_path(path):
        return -1
    if path.endswith(".py"):
        return 1 if DOC_DIRS.intersection(path.split("/")[:-1]) else 0
    return 2


def _cut(s):
    s = s.rstrip("\r")
    return s if len(s) <= LINE_CUT else s[:LINE_CUT - 4] + " ..."


def main():
    C.bootstrap()
    opts = C.parse_args(sys.argv[1:], FLAGS, ["regex*"])
    rx = str(opts.get("regex") or " ".join(opts.get("_") or []))
    cap = C.CAPS["grep"]
    if not rx:
        C.print_usage(NAME, USAGE)
        return
    try:
        mx = int(opts.get("max") if opts.get("max") not in (None, "") else MAX_DEFAULT)
    except (TypeError, ValueError):
        mx = MAX_DEFAULT
    mx = max(MAX_LO, min(MAX_HI, mx))
    tests = bool(opts.get("tests"))
    ws = C.ws()
    path = (opts.get("path") or "").strip()
    no_index_dir, pathspec = None, ["."]
    if path:
        ap = path if os.path.isabs(path) else os.path.join(ws, path)
        rp, rw = os.path.realpath(ap), os.path.realpath(ws)
        if not os.path.exists(ap):
            C.emit(NAME, "GREP: 0 hits in 0 files (shown 0)", "NOTE: --path %s does not exist" % path, cap)
            return
        if rp == rw or rp.startswith(rw + os.sep):
            pathspec = [os.path.relpath(rp, rw)]
        else:
            no_index_dir = rp if os.path.isdir(rp) else os.path.dirname(rp)
            pathspec = ["." if os.path.isdir(rp) else os.path.basename(rp)]
    rc, out, mode = run_grep(ws, rx, pathspec, tests, C.real_budget(DEADLINE), no_index_dir)
    if rc not in (0, 1, None) and not no_index_dir and "not a git repository" in out.lower():
        no_index_dir = os.path.realpath(ws)                   # a workspace without git: search the tree itself
        rc, out, mode = run_grep(ws, rx, pathspec, tests, C.real_budget(DEADLINE), no_index_dir)
        if not tests:
            out = "\n".join(l for l in out.split("\n") if not is_test_path(l.split("\0", 1)[0]))
    if rc not in (0, 1, None) or (rc != 0 and out.lstrip().lower().startswith(("fatal:", "error:"))):
        msg = " ".join(l.strip() for l in out.splitlines() if l.strip())[:220] or ("git grep exit %s" % rc)
        msg = re.sub(r"^(fatal|error):\s*", "", msg)
        C.emit(NAME, "GREP: invalid regex: %s (escape ( ) [ ] . * + ? with a backslash for literal text)" % msg,
               "", cap)
        return
    hits = parse_hits(out)
    if not tests and not no_index_dir:
        hits = [h for h in hits if not is_test_path(h[0])]
    groups = {}
    for h in hits:
        groups.setdefault(h[0], []).append(h)
    order = sorted(groups, key=lambda p: (_prio(p, tests), p))
    total, nfiles = len(hits), len(groups)
    # enclosing defs for the .py files that will be shown
    shown_files = []
    k = 0
    for p in order:
        if k >= mx:
            break
        shown_files.append(p)
        k += min(PER_FILE, len(groups[p]), mx - k)
    idx = None
    pys = [p for p in shown_files if p.endswith(".py")]
    if pys:
        try:
            import _swe_index as I
            base = no_index_dir or ws
            idx = I.build(base, deadline_s=C.real_budget(2), only=pys, want_terms=False,
                          use_cache=not no_index_dir)
        except Exception:
            idx = None
    body_budget = cap - FOOTER_RESERVE - 60
    body, used, shown = [], 0, 0
    trunc = False
    in_ws = not no_index_dir or no_index_dir == os.path.realpath(ws)
    seen = []                       # (path, line) of every hit printed: recorded as views for edit.py's STALE guard
    for p in shown_files:
        disp = p if in_ws else os.path.join(no_index_dir, p)
        block = [disp]
        last = ()
        n_here = 0
        nums = []
        for (_p, num, text) in groups[p][:PER_FILE]:
            if shown + n_here >= mx:
                break
            nums.append(num)
            if idx is not None and p.endswith(".py"):
                try:
                    s = idx.enclosing(p, num)
                except Exception:
                    s = None
                key = (s[0], s[2]) if s else None
                if key != last:
                    block.append("  (in %s %s L%d-%d)" % (s[1], s[0][:80], s[2], s[3]) if s else "  (module level)")
                    last = key
            block.append("%5d| %s" % (num, _cut(text)))
            n_here += 1
        size = sum(len(x) + 1 for x in block)
        if used + size > body_budget:
            trunc = True
            break
        body += block
        used += size
        shown += n_here
        if in_ws:
            seen += [(p, n, n) for n in nums]
    if total > shown or trunc:
        body.append("... %d more hits not shown; narrow it with --path DIR or a more specific regex" % (total - shown))
    if total == 0:
        body.append("NOTE: no match%s. Try a shorter regex%s." % (
            "" if tests else " in source files", "" if tests else ", or add --tests to search the tests"))
    if rc is None:
        body.insert(0, "NOTE: git grep hit the %ds deadline; results are partial." % DEADLINE)
    first = "GREP: %d hits in %d files (shown %d)" % (total, nfiles, shown)
    C.record_views(seen)
    C.emit(NAME, first, "\n".join(body), cap)


if __name__ == "__main__":
    C.safe_main(NAME, main)
