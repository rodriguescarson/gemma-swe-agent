"""Patch hygiene and checkpoints. args={"mode": "preflight"|"save"|"restore"}. Stdlib only."""
import os, re, subprocess, sys, py_compile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ws import ws
a = sys.argv[1:]; mode = a[a.index("--mode") + 1] if "--mode" in a else "preflight"
ROOT = ws(); sh = lambda c: subprocess.run(c, cwd=ROOT, shell=True, capture_output=True, text=True).stdout
BEST = "/tmp/_swe_best.diff"
if mode == "save":
    d = sh("git add -N . >/dev/null 2>&1; git diff HEAD"); open(BEST, "w").write(d); print(f"saved checkpoint ({len(d)} bytes)"); sys.exit(0)
if mode == "restore":
    if not os.path.exists(BEST): print("no checkpoint"); sys.exit(0)
    sh("git checkout -- . && git clean -fdq -e '*.pyc'"); r = subprocess.run(f"git apply {BEST}", cwd=ROOT, shell=True, capture_output=True, text=True)
    print("restored checkpoint" if r.returncode == 0 else "restore failed: " + r.stderr[:500]); sys.exit(0)
st = [l for l in sh("git status --porcelain").splitlines() if l.strip()]
bad, notes = [], []
for l in st:
    path = l[3:].strip().split(" -> ")[-1]
    if re.search(r"(^|/)(tests?|testing)/|(^|/)test_[^/]*\.py$|_test\.py$|(^|/)(conftest\.py|pytest\.ini|tox\.ini|setup\.cfg|pyproject\.toml)$", path):
        bad.append(f"{path}  <- test/config file: changes are DISCARDED at grading; revert with `git checkout -- {path}` unless it is a new source file")
    elif l.startswith("??") and not path.endswith(".py"):
        notes.append(f"{path}  <- untracked non-.py file will be in the patch; delete it if scratch")
    elif l.startswith("??") and re.search(r"(repro|scratch|debug|tmp)", path, re.I):
        bad.append(f"{path}  <- looks like a scratch script in /workspace; move it to /tmp or delete")
    if path.endswith(".py") and os.path.exists(os.path.join(ROOT, path)):
        try: py_compile.compile(os.path.join(ROOT, path), doraise=True, cfile="/tmp/_pyc_check")
        except py_compile.PyCompileError as e: bad.append(f"{path}  <- SYNTAX ERROR: {str(e)[-300:]}")
stat = sh("git add -N . >/dev/null 2>&1; git diff HEAD --stat")
print("DIFF:\n" + (stat.strip() or "(empty: nothing changed yet)"))
print("PROBLEMS:\n" + ("\n".join(bad) if bad else "none"))
if notes: print("NOTES:\n" + "\n".join(notes))
print("READY to submit_patch" if stat.strip() and not bad else "NOT READY")
