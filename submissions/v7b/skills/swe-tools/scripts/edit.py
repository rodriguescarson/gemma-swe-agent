"""edit.py: the edit channel (v4h, v4h2, v5h2; v7 below). Stdlib only; it imports nothing from its siblings except the
optional cap ledger (_ws.py), so it still edits when installed alone.

  python3 /tmp/swe/edit.py FILE <<'EOF'            SEARCH/REPLACE blocks (several blocks are all-or-nothing)
  <<<<<<< SEARCH
  exact current lines
  =======
  new lines
  >>>>>>> REPLACE
  EOF
  python3 /tmp/swe/edit.py FILE --lines A-B <<'EOF'  replace lines A..B (1-based, inclusive); empty input deletes them
  python3 /tmp/swe/edit.py FILE --create <<'EOF'     new file

Why: on the scorer, tool results reach the model JSON-escaped and the gemma4 parser corrupts multi-argument edit_file
calls, so 35% of v4's edit_file calls failed "old_string not found" (152 of 439 on the 2026-09-28 L4 run). A heredoc
through run_command is one plain string. Matching falls back from exact to trailing-whitespace-tolerant, to
indentation-shifted, to JSON-unescaped. Bytes are split on "\\n" only and decoded UTF-8 with surrogateescape so untouched
bytes round-trip. A .py file that no longer compiles after the edit is restored and the error printed.

v7: a --lines body that carries SEARCH/REPLACE markers is applied as a SEARCH/REPLACE block, with one NOTE line, instead
of writing the markers into the file (docs/a6000/FAILURE_FORENSICS.md finding 11: 13 SYNTAX-ERROR reverts); the range
shapes the model sends without the flag (FILE A-B, FILE A B, --lines A B, --create FILE) are taken as meant; every
refusal is one line that names the cause and the next action; the first OK edit is recorded in the task's cap ledger.
"""
import difflib
import os
import py_compile
import re
import sys

HOWTO = ("edit.py edits one file: send python3 /tmp/swe/edit.py FILE <<'EOF' with a SEARCH/REPLACE block (or FILE --lines "
         "A-B with the new lines, or FILE --create with the whole file), the lines, then EOF, next")
PROTECTED = re.compile(r"(^|/)(tests?|testing)/|(^|/)test_[^/]*\.py$|_test\.py$|"
                       r"(^|/)(conftest\.py|pytest\.ini|tox\.ini|setup\.cfg|pyproject\.toml)$")
MS = re.compile(r"^[ \t]*<{5,9} ?(SEARCH|ORIGINAL|FIND|OLD)[ \t]*$", re.I)
MD = re.compile(r"^[ \t]*={5,9}[ \t]*$")
MR = re.compile(r"^[ \t]*>{5,9} ?(REPLACE|UPDATED|NEW)[ \t]*$", re.I)
FENCE = re.compile(r"^[ \t]*```[\w+.-]*[ \t]*$")
NUM = re.compile(r"^\s*\d+[|:] ?")
RANGE_ARG = re.compile(r"^\d+([-:]\d+)?$")
ESC = re.compile(r'\\(["\\nt])')
ESC_TO = {'"': '"', "\\": "\\", "n": "\n", "t": "\t"}
REGION = 30
OUT_MAX = 3500
EARLY_EOF = ("ERROR: the edit ended early (no ======= or no >>>>>>> REPLACE line arrived, often because a line EOF inside "
             "the block ended the heredoc), so nothing changed; put EOF once, as the last line, and send the whole edit again now")
MARKERS_NOTE = ("the --lines input carried SEARCH/REPLACE markers, so it was applied as a SEARCH/REPLACE block and the "
                "range was not used; --lines takes only the new lines")


class Fail(Exception):
    pass


def split(text):
    """-> (lines without their newline, final_nl)."""
    if text == "":
        return [], True
    final_nl = text.endswith("\n")
    body = text[:-1] if final_nl else text
    return body.split("\n"), final_nl


def join(lines, final_nl):
    return "\n".join(lines) + ("\n" if final_nl and lines else "")


def read_text(path):
    with open(path, "rb") as f:
        return f.read().decode("utf-8", "surrogateescape")


def write_text(path, text):
    tmp = path + ".swe_edit_tmp"
    with open(tmp, "wb") as f:
        f.write(text.encode("utf-8", "surrogateescape"))
    os.replace(tmp, path)


def strip_fences(lines):
    while lines and FENCE.match(lines[0]):
        lines = lines[1:]
    while lines and FENCE.match(lines[-1]):
        lines = lines[:-1]
    return lines


def strip_nums(lines):
    """Drop a "12| " or "12: " prefix when every non-blank line carries one (copied from a numbered view)."""
    nb = [l for l in lines if l.strip()]
    if nb and all(NUM.match(l) for l in nb):
        return [NUM.sub("", l, 1) if l.strip() else l for l in lines]
    return lines


def parse_blocks(lines):
    blocks, i, n = [], 0, len(lines)
    while i < n:
        if not MS.match(lines[i]):
            i += 1
            continue
        j = i + 1
        while j < n and not MD.match(lines[j]):
            j += 1
        if j >= n:
            raise Fail(EARLY_EOF)
        k = j + 1
        while k < n and not MR.match(lines[k]):
            k += 1
        if k >= n:
            raise Fail(EARLY_EOF)
        search, repl = strip_nums(lines[i + 1:j]), strip_nums(lines[j + 1:k])
        if not [l for l in search if l.strip()]:
            raise Fail("ERROR: the SEARCH part is empty, so copy the exact current lines into it, or replace by number "
                       "with --lines A-B instead")
        blocks.append((search, repl))
        i = k + 1
    if not blocks:
        raise Fail("ERROR: no <<<<<<< SEARCH / ======= / >>>>>>> REPLACE block arrived, so send one next, or replace by "
                   "number with --lines A-B and the plain new lines instead")
    return blocks


def indent(s):
    return s[:len(s) - len(s.lstrip())]


def positions(file_lines, search, key):
    n, out = len(search), []
    ks = [key(l) for l in search]
    for i in range(len(file_lines) - n + 1):
        if all(key(file_lines[i + t]) == ks[t] for t in range(n)):
            out.append(i)
    return out


def find(file_lines, search):
    """-> (start indices, mode) trying exact, rstrip, strip (indentation shift) and JSON-unescaped forms."""
    for name, src in (("exact", search), ("unescaped", [ESC.sub(lambda m: ESC_TO[m.group(1)], l) for l in search])):
        if name == "unescaped" and src == search:
            break
        for mode, key in (("exact", lambda l: l), ("rstrip", lambda l: l.rstrip()), ("strip", lambda l: l.strip())):
            p = positions(file_lines, src, key)
            if p:
                return p, (name if name == "unescaped" else mode), src
    return [], "none", search


def reindent(repl, file_first, search_first):
    f0, s0 = indent(file_first), indent(search_first)
    if f0 == s0:
        return repl
    return [f0 + l[len(s0):] if l.startswith(s0) and l.strip() else l for l in repl]


def numbered(lines, a, b):
    a, b = max(0, a), min(len(lines), b)
    return "\n".join("%d| %s" % (i + 1, lines[i][:150].encode("utf-8", "replace").decode("utf-8", "replace"))
                     for i in range(a, b))


def closest(file_lines, search):
    probe = next((l.strip() for l in search if l.strip()), "")
    best, best_i = 0.0, 0
    for i, l in enumerate(file_lines):
        r = difflib.SequenceMatcher(None, probe, l.strip()).ratio()
        if r > best:
            best, best_i = r, i
    return best_i


def excerpt(line, n=70):
    s = line.strip().encode("utf-8", "replace").decode("utf-8", "replace")
    return s if len(s) <= n else s[:n - 3] + "..."


def apply_blocks(file_lines, blocks, rel):
    cur, regions = list(file_lines), []
    for search, repl in blocks:
        p, mode, src = find(cur, search)
        if len(p) == 0:
            if not cur:
                raise Fail("NO MATCH in %s: the file is empty, so write its whole text with --lines or a new file with "
                           "--create instead" % rel)
            c = closest(cur, search)
            b = min(len(cur), c + len(search))
            raise Fail("NO MATCH in %s: the SEARCH lines are not in the file (the closest is line %d: `%s`), so "
                       "replace by number now with --lines %d-%d, or copy the exact current lines into SEARCH"
                       % (rel, c + 1, excerpt(cur[c]), c + 1, b))
        if len(p) > 1:
            raise Fail("AMBIGUOUS in %s: the SEARCH block matches %d places (lines %s), so add more surrounding lines to "
                       "SEARCH, or replace by number with --lines A-B instead" % (rel, len(p), ", ".join(str(i + 1) for i in p[:6])))
        i = p[0]
        new = reindent(repl, cur[i], src[0]) if indent(cur[i]) != indent(src[0]) else repl
        cur[i:i + len(src)] = new
        regions.append((i, len(src), len(new), mode))
    return cur, regions


def parse_range(s, nlines, rel):
    m = re.match(r"^\s*(\d+)\s*(?:[-:]\s*(\d+))?\s*$", s or "")
    if not m:
        raise Fail("ERROR: --lines needs A-B (for example --lines 120-135), not %r, so send the edit again with the range "
                   "next" % (s or ""))
    a, b = int(m.group(1)), int(m.group(2) or m.group(1))
    if not (1 <= a <= b <= nlines):
        raise Fail("ERROR: --lines %d-%d is outside %s (%d lines), so pick a range inside 1-%d next"
                   % (a, b, rel, nlines, nlines))
    return a, b


def parse_args(argv):
    """-> (path, mode, range text). FILE [--lines A-B | --lines A B | --lines=A-B | --create]; also FILE A-B, FILE A B,
    FILE A (meaning --lines) and --create FILE, the shapes the model sends."""
    args = [a for a in argv if a != "--"]
    if not args or args[0] in ("-h", "--help"):
        raise Fail(HOWTO)
    path, mode, rng, nums, i = None, "blocks", None, [], 0
    while i < len(args):
        a = args[i]
        if a == "--create":
            mode = "create"
        elif a == "--lines" and i + 1 < len(args):
            rng, i = args[i + 1], i + 1
            if re.fullmatch(r"\d+", rng) and i + 1 < len(args) and re.fullmatch(r"\d+", args[i + 1]):
                rng, i = rng + "-" + args[i + 1], i + 1
            mode = "lines" if mode == "blocks" else mode
        elif a.startswith("--lines="):
            rng = a.split("=", 1)[1]
            mode = "lines" if mode == "blocks" else mode
        elif path is None and not a.startswith("-"):
            path = a
        elif path is not None and RANGE_ARG.match(a):
            nums.append(a)
        else:
            raise Fail("ERROR: unknown argument %r, so send the edit again next with only FILE and, if needed, --lines A-B "
                       "or --create" % a)
        i += 1
    if path is None:
        raise Fail(HOWTO)
    if nums:
        if len(nums) == 2 and all(re.fullmatch(r"\d+", x) for x in nums):
            nums = [nums[0] + "-" + nums[1]]
        if len(nums) != 1 or rng is not None or mode == "create":
            raise Fail("ERROR: unknown argument %r, so send the edit again next with only FILE and, if needed, --lines A-B "
                       "or --create" % nums[-1])
        rng, mode = nums[0], "lines"
    return path, mode, rng


def source_hint():
    """' under pkg/' for the workspace's top-level package(s), so a refused test edit points at the source."""
    root = os.getcwd()
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return ""
    skip = {"tests", "test", "testing", "docs", "doc", "examples", "scripts", "benchmarks", "build", "dist"}
    pk = [n for n in names if n not in skip and not n.startswith((".", "_")) and os.path.isfile(os.path.join(root, n, "__init__.py"))]
    src = os.path.join(root, "src")
    if not pk and os.path.isdir(src):
        pk = ["src/" + n for n in sorted(os.listdir(src)) if os.path.isfile(os.path.join(src, n, "__init__.py"))]
    return (" under " + " or ".join(p + "/" for p in pk[:2])) if pk else ""


def main(argv, stdin_text):
    path, mode, rng = parse_args(argv)
    rel = path
    full = path if os.path.isabs(path) else os.path.join(os.getcwd(), path)
    if PROTECTED.search(rel.replace(os.sep, "/")):
        raise Fail("REFUSED %s: test and config files are reset by the grader, so edit the source file%s instead"
                   % (rel, source_hint()))
    in_lines, _ = split(stdin_text)
    in_lines = strip_fences(in_lines)
    if mode == "create":
        if os.path.exists(full):
            raise Fail("REFUSED --create: %s already exists, so change it with a SEARCH/REPLACE block or --lines A-B instead" % rel)
        os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
        text = join(strip_nums(in_lines), True)
        write_text(full, text)
        out = ["OK created %s (%d lines)" % (rel, len(in_lines))]
        return check_compile(full, rel, None, out)
    if not os.path.isfile(full):
        raise Fail("NO SUCH FILE: %s, so find the path with git ls-files | grep %s and send the edit again next"
                   % (rel, os.path.basename(rel)))
    original = read_text(full)
    lines, final_nl = split(original)
    note = None
    if mode == "lines" and any(MS.match(l) for l in in_lines):
        mode, note = "blocks", "NOTE: " + MARKERS_NOTE.replace("--lines input", "--lines %s input" % rng, 1)
    try:
        if mode == "lines":
            a, b = parse_range(rng, len(lines), rel)
            new = strip_nums(in_lines)
            cur = lines[:a - 1] + new + lines[b:]
            regions = [(a - 1, b - a + 1, len(new), "lines")]
        else:
            cur, regions = apply_blocks(lines, parse_blocks(in_lines), rel)
        if cur == lines:
            raise Fail("NO CHANGE: %s already contains the REPLACE text, so do not resend this edit; move to the next "
                       "change or run the test now" % rel)
        write_text(full, join(cur, final_nl or not lines))
        out = []
        for i, n_old, n_new, m in regions:
            out.append("OK %s: lines %d-%d replaced (%d -> %d lines%s)"
                       % (rel, i + 1, i + max(n_old, 1), n_old, n_new, "" if m in ("exact", "lines") else ", matched by " + m))
        i0, _, n0, _ = regions[0]
        out.append("Now:\n" + numbered(cur, i0 - 3, i0 + min(n0, REGION - 6) + 3))
        text = check_compile(full, rel, original, out)
    except Fail as e:
        if note:
            raise Fail("%s (%s)" % (e, MARKERS_NOTE))
        raise
    return text + ("\n" + note if note else "")


def compile_error(e):
    v = getattr(e, "exc_value", None)
    line, msg, src = getattr(v, "lineno", None), getattr(v, "msg", None), (getattr(v, "text", None) or "").strip()
    if not msg:
        msg = (str(v) if v is not None else str(e)).strip().splitlines()[-1:] or ["does not compile"]
        msg = msg[0]
    d = ("line %d: %s" % (line, msg)) if line else str(msg)
    if src:
        d += ", `%s`" % excerpt(src, 60)
    return " ".join(d.split())


def check_compile(full, rel, original, out):
    if full.endswith(".py"):
        try:
            py_compile.compile(full, doraise=True, cfile=full + ".swe_pyc_check")
        except py_compile.PyCompileError as e:
            if original is None:
                os.unlink(full)
                raise Fail("SYNTAX ERROR in the new file (%s), so it was REVERTED and %s was not created; fix those lines "
                           "and send the --create again now" % (compile_error(e), rel))
            write_text(full, original)
            raise Fail("SYNTAX ERROR after the edit (%s), so it was REVERTED and %s is unchanged; fix the new lines and "
                       "send the edit again now" % (compile_error(e), rel))
        finally:
            try:
                os.unlink(full + ".swe_pyc_check")
            except OSError:
                pass
    _mark_edited()
    text = "\n".join(out)
    return text if len(text) <= OUT_MAX else text[:OUT_MAX - 20] + "\n... (output cut)"


def _mark_edited():
    """The task's first OK edit ends view.py's pre-edit read cap (_ws.py); an edit never fails over the ledger."""
    try:
        sys.dont_write_bytecode = True                  # never leave a __pycache__ next to the helpers
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _ws import mark_edited
        mark_edited()
    except Exception:
        pass


if __name__ == "__main__":
    try:
        data = sys.stdin.buffer.read().decode("utf-8", "surrogateescape") if not sys.stdin.isatty() else ""
        text = main(sys.argv[1:], data)
    except Fail as e:
        text = str(e)
        sys.exit_code = 1
    sys.stdout.buffer.write((text + "\n").encode("utf-8", "replace"))
    sys.stdout.flush()
    sys.exit(getattr(sys, "exit_code", 0))
