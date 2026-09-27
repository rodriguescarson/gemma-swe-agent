"""Replace a line range of a file with new text, then syntax-check; auto-revert on a syntax error. Stdlib only.
Usage (new text on stdin, raw, no escaping needed):
  python3 /tmp/swe/replace.py --file pkg/mod.py --start 40 --end 52 <<'EOF'
  <new lines>
  EOF
--end may equal --start - 1 to INSERT before --start. Prints the edited region with line numbers."""
import os, sys, py_compile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ws import ws
a = sys.argv[1:]; opt = {}
i = 0
while i < len(a):
    if a[i].startswith("--") and i + 1 < len(a): opt[a[i][2:]] = a[i + 1]; i += 2
    else: i += 1
if not {"file", "start", "end"} <= opt.keys(): print(__doc__); sys.exit(0)
ROOT = ws(); path = opt["file"] if os.path.isabs(opt["file"]) else os.path.join(ROOT, opt["file"])
if not os.path.isfile(path): print(f"ERROR: no such file {opt['file']}"); sys.exit(0)
try: start, end = int(opt["start"]), int(opt["end"])
except ValueError: print("ERROR: --start/--end must be integers"); sys.exit(0)
old = open(path, encoding="utf-8").read(); lines = old.splitlines(keepends=True)
if not (1 <= start <= len(lines) + 1) or not (start - 1 <= end <= len(lines)):
    print(f"ERROR: range {start}-{end} outside file (1-{len(lines)} lines)"); sys.exit(0)
new = sys.stdin.read()
if new and not new.endswith("\n"): new += "\n"
text = "".join(lines[:start - 1]) + new + "".join(lines[end:])
open(path, "w", encoding="utf-8").write(text)
if path.endswith(".py"):
    try: py_compile.compile(path, doraise=True, cfile="/tmp/_pyc_replace")
    except py_compile.PyCompileError as e:
        open(path, "w", encoding="utf-8").write(old)
        print("REVERTED (file unchanged): the new text has a syntax error:\n" + str(e)[-600:]); sys.exit(0)
n_new = new.count("\n"); lo = max(1, start - 3); hi = min(len(text.splitlines()), start + n_new + 2)
print(f"OK: replaced lines {start}-{end} ({end - start + 1} old) with {n_new} new lines. Now lines {lo}-{hi}:")
for k, l in enumerate(text.splitlines()[lo - 1:hi], lo): print(f"{k:5d}  {l}")
