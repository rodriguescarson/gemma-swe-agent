"""Show lines START-END of FILE with line numbers (max 120 lines). An exact repeat of a range already shown in this
task, while the file is unchanged, is refused: re-reading the same lines never helps (v4h6g loop breaker).
usage: python3 /tmp/swe/view.py FILE START END"""
import hashlib, json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ws import ws

MAX = 120


def main(argv):
    if len(argv) != 3 or not argv[1].isdigit() or not argv[2].isdigit():
        print("usage: python3 /tmp/swe/view.py FILE START END   (line numbers, at most %d lines)" % MAX); return 0
    root = ws(); rel = argv[0]; path = rel if os.path.isabs(rel) else os.path.join(root, rel)
    if not os.path.isfile(path):
        print("no such file: %s (use git ls-files | grep NAME to find it)" % rel); return 0
    start, end = max(1, int(argv[1])), int(argv[2])
    capped = end - start + 1 > MAX
    if capped: end = start + MAX - 1
    data = open(path, "rb").read(); digest = hashlib.sha1(data).hexdigest()[:12]
    log = os.path.join(os.environ.get("TMPDIR") or tempfile.gettempdir(), "swe", ".views.json")
    os.makedirs(os.path.dirname(log), exist_ok=True)
    try: seen = json.load(open(log))
    except Exception: seen = {}
    key = "%s:%d-%d" % (os.path.realpath(path), start, end)   # v6p: per copy, not per relative path
    if seen.get(key) == digest:
        print("ALREADY SHOWN: %s lines %d-%d, unchanged since. Do not read it again: edit now with "
              "python3 /tmp/swe/edit.py, or view different lines." % (rel, start, end)); return 0
    seen[key] = digest; json.dump(seen, open(log, "w"))
    lines = data.decode("utf-8", "replace").splitlines()
    for i in range(start, min(end, len(lines)) + 1):
        print("%d| %s" % (i, lines[i - 1]))
    if capped: print("(capped at %d lines; view the next range if needed)" % MAX)
    if start > len(lines): print("(file has %d lines)" % len(lines))
    return 0


if __name__ == "__main__":
    import _budget                                  # v6p-b: the per-fixer call ledger (a no-op outside a fixer's copy)
    _refusal, _footer = _budget.enter(ws())
    if _refusal:
        print(_refusal); sys.exit(0)
    if _footer:
        print(_footer)                              # first line: the harness truncates long tool output
    sys.exit(main(sys.argv[1:]))
