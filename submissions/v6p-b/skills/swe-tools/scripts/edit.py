"""edit.py: the edit channel for v4h (v4 + this one helper). Stdlib only, standalone (no sibling imports: it is
installed on its own into the sandbox's rewritten tmp, see install.py).

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
"""
import difflib
import os
import py_compile
import re
import sys

USAGE = "usage: python3 /tmp/swe/edit.py FILE [--lines A-B | --create] <<'EOF' ... EOF"
PROTECTED = re.compile(r"(^|/)(tests?|testing)/|(^|/)test_[^/]*\.py$|_test\.py$|"
                       r"(^|/)(conftest\.py|pytest\.ini|tox\.ini|setup\.cfg|pyproject\.toml)$")
MS = re.compile(r"^[ \t]*<{5,9} ?(SEARCH|ORIGINAL|FIND|OLD)[ \t]*$", re.I)
MD = re.compile(r"^[ \t]*={5,9}[ \t]*$")
MR = re.compile(r"^[ \t]*>{5,9} ?(REPLACE|UPDATED|NEW)[ \t]*$", re.I)
FENCE = re.compile(r"^[ \t]*```[\w+.-]*[ \t]*$")
NUM = re.compile(r"^\s*\d+[|:] ?")
ESC = re.compile(r'\\(["\\nt])')
ESC_TO = {'"': '"', "\\": "\\", "n": "\n", "t": "\t"}
REGION = 30
OUT_MAX = 3500
EARLY_EOF = ("ERROR: the edit ended early (no ======= or no >>>>>>> REPLACE line arrived), so nothing changed. A line "
             "EOF inside the block ends the heredoc. Put EOF once, as the last line, and send the whole edit again.")


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
            raise Fail("ERROR: the SEARCH part is empty. Copy the exact current lines to replace, or use --lines A-B.")
        blocks.append((search, repl))
        i = k + 1
    if not blocks:
        raise Fail("ERROR: no <<<<<<< SEARCH / ======= / >>>>>>> REPLACE block found.\n" + USAGE)
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


def apply_blocks(file_lines, blocks, rel):
    cur, regions = list(file_lines), []
    for search, repl in blocks:
        p, mode, src = find(cur, search)
        if len(p) == 0:
            c = closest(cur, search)
            raise Fail("NO MATCH in %s for the SEARCH block (%d lines). Closest current lines:\n%s\n"
                       "Copy them exactly, or replace by number: python3 /tmp/swe/edit.py %s --lines %d-%d <<'EOF' ... EOF"
                       % (rel, len(search), numbered(cur, c - 6, c + 7), rel, c + 1, c + len(search)))
        if len(p) > 1:
            raise Fail("AMBIGUOUS in %s: the SEARCH block matches %d places (lines %s). Include more surrounding lines, "
                       "or use --lines A-B." % (rel, len(p), ", ".join(str(i + 1) for i in p[:6])))
        i = p[0]
        new = reindent(repl, cur[i], src[0]) if indent(cur[i]) != indent(src[0]) else repl
        cur[i:i + len(src)] = new
        regions.append((i, len(src), len(new), mode))
    return cur, regions


def parse_range(s, nlines):
    m = re.match(r"^\s*(\d+)\s*(?:-\s*(\d+))?\s*$", s or "")
    if not m:
        raise Fail("ERROR: --lines needs A-B, for example --lines 120-135.")
    a, b = int(m.group(1)), int(m.group(2) or m.group(1))
    if not (1 <= a <= b <= nlines):
        raise Fail("ERROR: --lines %d-%d is outside the file (%d lines)." % (a, b, nlines))
    return a, b


def main(argv, stdin_text):
    args = [a for a in argv if a != "--"]
    if not args or args[0] in ("-h", "--help"):
        raise Fail(USAGE)
    path, mode, rng = args[0], "blocks", None
    rest = args[1:]
    while rest:
        a = rest.pop(0)
        if a == "--lines" and rest:
            mode, rng = "lines", rest.pop(0)
        elif a.startswith("--lines="):
            mode, rng = "lines", a.split("=", 1)[1]
        elif a == "--create":
            mode = "create"
        else:
            raise Fail("ERROR: unknown argument %r.\n%s" % (a, USAGE))
    rel = path
    full = path if os.path.isabs(path) else os.path.join(os.getcwd(), path)
    if PROTECTED.search(rel.replace(os.sep, "/")):
        raise Fail("REFUSED %s: test and config files are replaced at grading, so edits there are discarded. "
                   "Fix the source code instead." % rel)
    in_lines, _ = split(stdin_text)
    in_lines = strip_fences(in_lines)
    if mode == "create":
        if os.path.exists(full):
            raise Fail("REFUSED --create: %s already exists. Use a SEARCH/REPLACE block or --lines." % rel)
        os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
        text = join(strip_nums(in_lines), True)
        write_text(full, text)
        out = ["OK created %s (%d lines)" % (rel, len(in_lines))]
        return check_compile(full, rel, None, out)
    if not os.path.isfile(full):
        raise Fail("NO SUCH FILE: %s. Find it with: git ls-files | grep %s" % (rel, os.path.basename(rel)))
    original = read_text(full)
    lines, final_nl = split(original)
    if mode == "lines":
        a, b = parse_range(rng, len(lines))
        new = strip_nums(in_lines)
        cur = lines[:a - 1] + new + lines[b:]
        regions = [(a - 1, b - a + 1, len(new), "lines")]
    else:
        cur, regions = apply_blocks(lines, parse_blocks(in_lines), rel)
    if cur == lines:
        raise Fail("NO CHANGE: the replacement equals the current text of %s." % rel)
    write_text(full, join(cur, final_nl or not lines))
    out = []
    for i, n_old, n_new, m in regions:
        out.append("OK %s: lines %d-%d replaced (%d -> %d lines%s)"
                   % (rel, i + 1, i + max(n_old, 1), n_old, n_new, "" if m in ("exact", "lines") else ", matched by " + m))
    i0, _, n0, _ = regions[0]
    out.append("Now:\n" + numbered(cur, i0 - 3, i0 + min(n0, REGION - 6) + 3))
    return check_compile(full, rel, original, out)


def check_compile(full, rel, original, out):
    if full.endswith(".py"):
        try:
            py_compile.compile(full, doraise=True, cfile=full + ".swe_pyc_check")
        except py_compile.PyCompileError as e:
            if original is None:
                os.unlink(full)
            else:
                write_text(full, original)
            raise Fail("SYNTAX ERROR after the edit, so it was REVERTED (%s unchanged):\n%s"
                       % (rel, str(e).strip()[-400:]))
        finally:
            try:
                os.unlink(full + ".swe_pyc_check")
            except OSError:
                pass
    text = "\n".join(out)
    return text if len(text) <= OUT_MAX else text[:OUT_MAX - 20] + "\n... (output cut)"


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import _budget                                  # v6p-b: the per-fixer call ledger (a no-op outside a fixer's copy)
    from _ws import ws
    _refusal, _footer = _budget.enter(ws())
    if _refusal:
        sys.stdout.write(_refusal + "\n"); sys.exit(0)
    try:
        data = sys.stdin.buffer.read().decode("utf-8", "surrogateescape") if not sys.stdin.isatty() else ""
        text = main(sys.argv[1:], data)
    except Fail as e:
        text = str(e)
        sys.exit_code = 1
    sys.stdout.buffer.write(((_footer + "\n" if _footer else "") + text + "\n").encode("utf-8", "replace"))
    sys.stdout.flush()
    sys.exit(getattr(sys, "exit_code", 0))
