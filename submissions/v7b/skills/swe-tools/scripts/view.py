"""Show lines of FILE with line numbers (at most 120 per call). An exact repeat of a range already shown in this task,
while the file is unchanged, is refused: re-reading the same lines never helps (v4h6g loop breaker).

v7 takes every range shape the model sends (docs/a6000/FAILURE_FORENSICS.md finding 1: `FILE 30-40` and a bare `FILE`
got the usage line in 63 tasks): FILE START END, FILE START-END, FILE START:END, FILE START (START..START+119) and FILE
(1..120); a reversed range is turned round; several ranges show the first and name the rest. The repeat check compares
the range after parsing, so `30-40` repeats `30 40`. Only non-numeric input gets the usage sentence. Before the task's
first OK edit.py call every view.py call is counted in the ledger (_ws.py) and refused past VIEW_CAP (v7 fix 9).

v7b (docs/GAPS_2026-10-06.md, last section, fix 1): the cap stays, but the 3rd refused read in a row (the ledger's
refused_run) is answered with an outline of the requested file instead of the refusal line, and so is the 6th, the 9th:
every top-level def/class (module-level if/try blocks included) and every method (a def in a class body, nested classes
included) as `START-END kind name(args)`, one per line, at most OUTLINE_MAX; a longer outline shows the OUTLINE_MAX
entries that start OUTLINE_BEFORE entries above the requested line and sums up the rest in "... N more" lines. Then one
line: pick a range and edit it with edit.py --lines. A file that cannot be outlined gets one "outline unavailable (...)"
line instead of the entries. The reply stays far below run_command's 5,000-char cut, so its last line always arrives.
usage: python3 /tmp/swe/view.py FILE [START [END]]"""
import ast, hashlib, json, os, re, sys, tempfile, warnings
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ws import OUTLINE, take_view, ws

MAX = 120
NUM = re.compile(r"^\d+$")
RANGE = re.compile(r"^(\d+)[-:](\d+)$")
OUTLINE_MAX = 60      # v7b: entries in one outline
OUTLINE_BEFORE = 10   # entries shown above the requested line when a file has more than OUTLINE_MAX
OUTLINE_WIDTH = 72    # chars per entry: 60 entries and the last line stay far below the 5,000-char cut
OUTLINE_LAST = "outline only: pick a range and edit it now with `python3 /tmp/swe/edit.py %s --lines A-B`"


def ranges(args):
    """The arguments after FILE -> [(start, end), ...], or None when one of them is not a line number or a range."""
    if not args:
        return [(1, MAX)]
    out, i = [], 0
    while i < len(args):
        m = RANGE.match(args[i])
        if m:
            out.append((int(m.group(1)), int(m.group(2))))
            i += 1
        elif NUM.match(args[i]):
            if i + 1 < len(args) and NUM.match(args[i + 1]):
                out.append((int(args[i]), int(args[i + 1])))
                i += 2
            else:
                out.append((int(args[i]), int(args[i]) + MAX - 1))
                i += 1
        else:
            return None
    return out


def signature(node):
    """(args) of a def, names only: posonly, /, positional, *args or a bare *, keyword-only, **kwargs."""
    a = node.args
    pos = [x.arg for x in getattr(a, "posonlyargs", [])]
    names = pos + (["/"] if pos else []) + [x.arg for x in a.args]
    if a.vararg:
        names.append("*" + a.vararg.arg)
    elif a.kwonlyargs:
        names.append("*")
    names += [x.arg for x in a.kwonlyargs] + (["**" + a.kwarg.arg] if a.kwarg else [])
    return "(%s)" % ", ".join(names)


def bases(node):
    """(Base, metaclass=M) of a class, or nothing."""
    parts = node.bases + node.keywords
    try:
        return "(%s)" % ", ".join(ast.unparse(p) for p in parts) if parts else ""
    except Exception:          # ast.unparse needs Python 3.9; the outline does not need the bases
        return ""


def outline_entries(text):
    """-> [(start, end, 'kind name(args)')] in line order: top-level defs and classes, also inside module-level if/try/with
    blocks, and the defs and classes of every class body; nothing inside a def. Raises SyntaxError on a broken file."""
    out = []

    def walk(node, prefix):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name, end = prefix + ch.name, getattr(ch, "end_lineno", None) or ch.lineno
                if isinstance(ch, ast.ClassDef):
                    out.append((ch.lineno, end, "class " + name + bases(ch)))
                    walk(ch, name + ".")
                else:
                    kind = "async def " if isinstance(ch, ast.AsyncFunctionDef) else "def "
                    out.append((ch.lineno, end, kind + name + signature(ch)))
            elif isinstance(ch, (ast.stmt, ast.excepthandler)) or type(ch).__name__ == "match_case":
                walk(ch, prefix)

    with warnings.catch_warnings():      # Python 3.12 prints SyntaxWarnings (invalid escapes) while parsing: not for the model
        warnings.simplefilter("ignore")
        tree = ast.parse(text)
    walk(tree, "")
    return sorted(out, key=lambda e: e[0])


def outline_reply(argv):
    """The reply on an outline turn: the entries of the requested file (or one 'outline unavailable' line), then the
    outline-only line."""
    rel = argv[0] if argv else ""
    last = OUTLINE_LAST % (rel or "FILE")
    if not rel:
        return "outline unavailable (no file named)\n" + last
    path = rel if os.path.isabs(rel) else os.path.join(ws(), rel)
    if not os.path.isfile(path):
        return "outline unavailable (no such file: %s)\n%s" % (rel, last)
    try:
        text = open(path, "rb").read().decode("utf-8-sig", "replace")
    except OSError as e:
        return "outline unavailable (cannot read %s: %s)\n%s" % (rel, e.strerror or e, last)
    n = len(text.splitlines())
    if not path.endswith((".py", ".pyi")):
        return "outline unavailable (not a Python file; it has %d lines)\n%s" % (n, last)
    try:
        ents = outline_entries(text)
    except SyntaxError as e:
        return "outline unavailable (syntax error at line %s)\n%s" % (e.lineno or "?", last)
    except (ValueError, RecursionError, MemoryError):
        return "outline unavailable (cannot parse %s)\n%s" % (rel, last)
    if not ents:
        return "outline unavailable (no def or class; it has %d lines)\n%s" % (n, last)
    rs = ranges(argv[1:])
    want = max(1, min(rs[0])) if rs else 1
    at = max([i for i, e in enumerate(ents) if e[0] <= want] or [0])
    k = len(ents)
    lo = max(0, min(at - OUTLINE_BEFORE, k - OUTLINE_MAX))
    hi = min(k, lo + OUTLINE_MAX)
    clip = lambda s: s if len(s) <= OUTLINE_WIDTH else s[:OUTLINE_WIDTH - 3] + "..."
    lines = ["... %d more" % lo] if lo else []
    lines += [clip("%d-%d %s" % e) for e in ents[lo:hi]]
    lines += ["... %d more" % (k - hi)] if hi < k else []
    return "\n".join(lines + [last])


def main(argv):
    refusal = take_view()
    if refusal == OUTLINE:     # v7b: the 3rd refused read in a row gets new content, not the same line again
        print(outline_reply(argv)); return 0
    if refusal:
        print(refusal); return 0
    rs = ranges(argv[1:]) if argv else None
    if rs is None:
        print("usage: view.py takes FILE then line numbers (START END, START-END or START), not %r, so send it again next, "
              "for example python3 /tmp/swe/view.py %s 30 60" % (" ".join(argv), argv[0] if argv else "path/to/file.py")); return 0
    root = ws(); rel = argv[0]; path = rel if os.path.isabs(rel) else os.path.join(root, rel)
    if not os.path.isfile(path):
        print("no such file: %s, so find the path with git ls-files | grep %s and view it next" % (rel, os.path.basename(rel))); return 0
    (a, b), rest = rs[0], rs[1:]
    start, end = max(1, min(a, b)), max(a, b)
    end = max(end, start)
    capped = end - start + 1 > MAX
    if capped: end = start + MAX - 1
    data = open(path, "rb").read(); digest = hashlib.sha1(data).hexdigest()[:12]
    log = os.path.join(os.environ.get("TMPDIR") or tempfile.gettempdir(), "swe", ".views.json")
    os.makedirs(os.path.dirname(log), exist_ok=True)
    try: seen = json.load(open(log))
    except Exception: seen = {}
    key = "%s:%d-%d" % (os.path.relpath(path, root), start, end)
    if seen.get(key) == digest:
        print("ALREADY SHOWN: %s lines %d-%d are unchanged since you saw them, so edit now with python3 /tmp/swe/edit.py "
              "or view different lines instead" % (rel, start, end)); return 0
    seen[key] = digest; json.dump(seen, open(log, "w"))
    lines = data.decode("utf-8", "replace").splitlines()
    if not lines:
        print("EMPTY FILE: %s has no lines, so read another file next" % rel); return 0
    if start > len(lines):
        print("PAST END: %s has %d lines, so view a range inside 1-%d next" % (rel, len(lines), len(lines))); return 0
    for i in range(start, min(end, len(lines)) + 1):
        print("%d| %s" % (i, lines[i - 1]))
    if capped: print("(capped at %d lines; view the next range if needed)" % MAX)
    if rest: print("(one range per call: view %s next)" % ", ".join("%d-%d" % r for r in rest))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
