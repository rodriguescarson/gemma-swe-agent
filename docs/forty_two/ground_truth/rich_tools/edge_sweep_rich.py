#!/usr/bin/env python3
"""Call one function of a rich task on a list of edge inputs, each in its own process under scripts/forty_two/bounded.py
(--mb 1500 --secs 10), at base, under the gold patch and under each named box run's final patch. Stores the outcomes in the
task's ground-truth JSON under "edge_sweep".

    python3 edge_sweep_rich.py --id rich_4006 --repo $REPO --work $WORK --call "from rich.cells import split_graphemes as f" \
        --inputs '["", "a", "\\u001b"]' --runs p4 p4_v7c p4_v7d

$WORK is the directory gt_rich.py used (the task's worktree and venv_task must still exist)."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gt_rich as G  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--id", required=True)
ap.add_argument("--repo", required=True, type=Path)
ap.add_argument("--work", required=True, type=Path)
ap.add_argument("--call", required=True, help="python that binds the function under test to the name f")
ap.add_argument("--inputs", required=True, help="JSON list of string inputs")
ap.add_argument("--runs", nargs="*", default=[])
ap.add_argument("--secs", type=int, default=10)
a = ap.parse_args()

task = G.Task(a.repo, a.id)
tree = G.Tree(a.work, a.id, task.base_commit)
py = str(a.work / "venv_task" / "bin" / "python")
inputs = json.loads(a.inputs)
states = {}
for label in ["base", "gold", *a.runs]:
    tree.fresh()
    if label == "gold":
        tree.apply(task.patch)
    elif label != "base":
        rows = [json.loads(l) for l in open(a.repo / G.RUNS_DIR / "a6000" / "results" / label / "results.jsonl") if l.strip()]
        tree.apply([r for r in rows if r["id"] == a.id][-1]["patch"], harness_like=True)
    out = {}
    for s in inputs:
        code = f"{a.call}\nprint(repr(f({s!r})))"
        r = subprocess.run([sys.executable, str(a.repo / "scripts" / "forty_two" / "bounded.py"), "--mb", "1500", "--secs",
                            str(a.secs), "--", py, "-c", code], cwd=tree.path, capture_output=True, text=True, timeout=a.secs + 50)
        if r.returncode in (124, 137):
            out[repr(s)] = f"KILLED({r.returncode})"
        else:
            out[repr(s)] = r.stdout.strip() if r.returncode == 0 else f"exit {r.returncode}: {r.stderr.strip()[-120:]}"
    states[label] = out
    print(label, sum(v.startswith("KILLED") for v in out.values()), "killed of", len(out))
tree.fresh()
gt = a.repo / "docs" / "forty_two" / "ground_truth" / f"{a.id}.json"
d = json.loads(gt.read_text())
d["edge_sweep"] = {"call": a.call, "inputs": inputs, "secs_each": a.secs, "states": states,
                   "command": "python3 docs/forty_two/ground_truth/rich_tools/edge_sweep_rich.py --id " + a.id + " ..."}
gt.write_text(json.dumps(d, indent=1) + "\n")
