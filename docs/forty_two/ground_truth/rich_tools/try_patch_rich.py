#!/usr/bin/env python3
"""Re-score any patch for one rich task in the clean environment that gt_rich.py built.

    python3 try_patch_rich.py --id rich_3180 --repo $REPO --work $WORK --patch l4:g4-l4-v4 [--only-src] [--venv kpar221]

--patch  gold:      the task's gold patch
         l4:<run>   the row of <runs>/kaggle/<run>/results.jsonl
         box:<run>  the row of <runs>/a6000/results/<run>/results.jsonl
         file:<path>
--only-src drops test files and newly created files from the patch (the harness resets test files anyway).
The patch is applied like the harness (gt_rich.Tree.apply with harness_like=True, protected files reset), then the task's
test_patch, then the harness pytest command on the test_patch files. Prints the summary and each failing test.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gt_rich as G  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--id", required=True)
ap.add_argument("--repo", required=True, type=Path)
ap.add_argument("--work", required=True, type=Path)
ap.add_argument("--patch", required=True)
ap.add_argument("--only-src", action="store_true")
ap.add_argument("--venv", default="venv_task")
ap.add_argument("--repeat", type=int, default=1, help="rerun the targets N times (flakiness)")
a = ap.parse_args()
G.BOUNDED[:] = [sys.executable, str(a.repo / "scripts" / "forty_two" / "bounded.py")]   # every test command bounded

task = G.Task(a.repo, a.id)
kind, ref = a.patch.split(":", 1)
runs = a.repo / G.RUNS_DIR
if kind == "l4":
    rows = [json.loads(l) for l in open(runs / "kaggle" / ref / "results.jsonl") if l.strip()]
    patch = [r for r in rows if r["id"] == a.id][-1]["patch"]
elif kind == "box":
    rows = [json.loads(l) for l in open(runs / "a6000" / "results" / ref / "results.jsonl") if l.strip()]
    patch = [r for r in rows if r["id"] == a.id][-1]["patch"]
elif kind == "gold":
    patch = task.patch
else:
    patch = open(ref).read()
if a.only_src:
    parts = re.split(r"(?=^diff --git )", patch, flags=re.M)
    patch = "".join(p for p in parts if p.strip() and not G.is_protected(re.match(r"diff --git a/(\S+)", p).group(1))
                    and "new file mode" not in p)
tree = G.Tree(a.work, a.id, task.base_commit)
tree.fresh()
print("apply:", tree.apply(patch, harness_like=True))
tree.reset_protected(patch, task.test_patch)
tree.apply(task.test_patch)
targets = G.test_targets(task.test_patch, tree.path)
py = str(a.work / a.venv / "bin" / "python")
extra = {"PYTHONPATH": str(tree.path)} if a.venv != "venv_task" else None
for i in range(a.repeat - 1):
    r = G.run_tests(tree, py, targets, f"try{i}", 120, extra_env=extra)
    print("repeat", i + 1, r["exit"], r["summary"])
res = G.run_tests(tree, py, targets, "try", 120, extra_env=extra)
print(res["exit"], res["summary"])
for n, v in res["tests"].items():
    if v["status"] not in ("passed", "skipped"):
        print("  FAIL", n, v["msg"][:150].replace("\n", " "))
tree.fresh()
