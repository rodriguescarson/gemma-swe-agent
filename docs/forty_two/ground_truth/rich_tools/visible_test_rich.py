#!/usr/bin/env python3
"""Run test nodes that exist at the base commit (WITHOUT the task's test_patch) on base, gold and box-run patches: does the gold
contradict a test the agent could see? Results go into the ground-truth JSON under "visible_tests". Every run is bounded
(scripts/forty_two/bounded.py, 1500 MB, 60 s).

    python3 visible_test_rich.py --id rich_3470 --repo $REPO --work $WORK --nodes tests/test_console.py::test_capture_and_record \
        --runs p4_b1024 p4 p4_v7d"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gt_rich as G  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--id", required=True)
ap.add_argument("--repo", required=True, type=Path)
ap.add_argument("--work", required=True, type=Path)
ap.add_argument("--nodes", nargs="+", required=True)
ap.add_argument("--runs", nargs="*", default=[])
a = ap.parse_args()
G.BOUNDED[:] = [sys.executable, str(a.repo / "scripts" / "forty_two" / "bounded.py")]
task = G.Task(a.repo, a.id)
tree = G.Tree(a.work, a.id, task.base_commit)
py = str(a.work / "venv_task" / "bin" / "python")
out = {}
for label in ["base", "gold", *a.runs]:
    tree.fresh()
    if label == "gold":
        tree.apply(task.patch)
    elif label != "base":
        rows = [json.loads(l) for l in open(a.repo / G.RUNS_DIR / "a6000" / "results" / label / "results.jsonl") if l.strip()]
        tree.apply([r for r in rows if r["id"] == a.id][-1]["patch"], harness_like=True)
    r = G.run_tests(tree, py, a.nodes, "visible_" + label, 60)
    out[label] = {"exit": r["exit"], "summary": r["summary"]}
    print(label, r["exit"], r["summary"])
tree.fresh()
gt = a.repo / "docs" / "forty_two" / "ground_truth" / f"{a.id}.json"
d = json.loads(gt.read_text())
d["visible_tests"] = {"nodes": a.nodes, "note": "run at base WITHOUT test_patch", "states": out,
                      "command": "python3 docs/forty_two/ground_truth/rich_tools/visible_test_rich.py --id " + a.id + " ..."}
gt.write_text(json.dumps(d, indent=1) + "\n")
