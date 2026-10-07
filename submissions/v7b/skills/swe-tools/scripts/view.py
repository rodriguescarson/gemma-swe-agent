"""Show lines of FILE with line numbers (at most 120 per call). An exact repeat of a range already shown in this task,
while the file is unchanged, is refused: re-reading the same lines never helps (v4h6g loop breaker).

v7 takes every range shape the model sends (docs/a6000/FAILURE_FORENSICS.md finding 1: `FILE 30-40` and a bare `FILE`
got the usage line in 63 tasks): FILE START END, FILE START-END, FILE START:END, FILE START (START..START+119) and FILE
(1..120); a reversed range is turned round; several ranges show the first and name the rest. The repeat check compares
the range after parsing, so `30-40` repeats `30 40`. Only non-numeric input gets the usage sentence. Before the task's
first OK edit.py call every view.py call is counted in the ledger (_ws.py) and refused past VIEW_CAP (v7 fix 9).
usage: python3 /tmp/swe/view.py FILE [START [END]]"""
import hashlib, json, os, re, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ws import take_view, ws

MAX = 120
NUM = re.compile(r"^\d+$")
RANGE = re.compile(r"^(\d+)[-:](\d+)$")


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


def main(argv):
    refusal = take_view()
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
