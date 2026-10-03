"""Synthetic golden dataset cases on the calc task of tests/test_v10_flow.py (component b's own test data).

calc.ops.add subtracts; the hidden test (test_patch) adds tests/test_ops.py::test_add. Cases follow the dataset
schema of docs/eval/GOLDEN_EVALS_SPEC.md 4.6 exactly (component a builds the real ones), with ``repo: "rich"`` so the
exec checks use the rich Kaggle-parity venv (it has pytest).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from test_v10_flow import CLAIM, FILES, STATEMENT, TEST_PATCH, TID  # noqa: E402,F401
from test_v10_flow import GOLD as FLOW_GOLD  # noqa: E402,F401
from test_v10_flow import make_task as _flow_make_task  # noqa: E402

# test_v10_flow.GOLD has no trailing context, so git anchors its hunk at end-of-file and it never applies (the flow
# test only stores it as the task's reference). Real `git diff -U3` output of the same change:
GOLD = ("--- a/calc/ops.py\n+++ b/calc/ops.py\n@@ -1,6 +1,6 @@\n def add(a, b):\n     \"\"\"Add two numbers.\"\"\"\n"
        "-    return a - b\n+    return a + b\n \n \n def mul(a, b):\n")
PLAN = ("FILES: calc/ops.py:3-3 (add)\nCAUSE: add subtracts instead of adding.\nFIX: make add return the sum a + b.\n"
        "REPRO: fails on original\nTESTS: tests/test_ops.py")
WRONG = ("--- a/calc/ops.py\n+++ b/calc/ops.py\n@@ -1,6 +1,6 @@\n def add(a, b):\n     \"\"\"Add two numbers.\"\"\"\n"
         "-    return a - b\n+    return a * b\n \n \n def mul(a, b):\n")
GOLD_STEPS = [{"tool": "run_command", "args": {"command": "python3 /tmp/swe/edit.py calc/ops.py --lines 3-3 <<'EOF'\n"
                                                          "    return a + b\nEOF"}}]
WRONG_STEPS = [{"tool": "run_command", "args": {"command": "python3 /tmp/swe/edit.py calc/ops.py --lines 3-3 <<'EOF'\n"
                                                           "    return a * b\nEOF"}}]
T0 = {"L": 2, "F": 47, "V": 91}
TITLE = "calc.ops.add subtracts instead of adding"


def golden(suite: str, variant: str = "-", *, t0: float | None = None, pre_s: float = 150, task: str = TID,
           repro: str | None = CLAIM, runnable: bool = True, gradable: bool = True) -> dict:
    g = {"schema": "golden-case-v1", "suite": suite, "task": task, "variant": variant, "split": "dev", "repo": "rich",
         "stratum": "rich/none", "runnable": runnable, "runnable_why": "" if runnable else "synthetic: not runnable",
         "gradable": gradable, "gradable_why": "" if gradable else "synthetic: not gradable", "fixture_sha": "",
         "t0": T0[suite] if t0 is None else t0, "pre_s": pre_s, "plan": PLAN if repro else PLAN.replace(
             "REPRO: fails on original", "REPRO: none"),
         "plan_source": "template", "plan_basis": "ast", "title_words": TITLE, "repro": repro,
         "reproducible": bool(repro), "tree_patch": "", "tree_source": "-", "replay": "none", "replay_steps": [],
         "notes_changed": "", "gold_files": ["calc/ops.py"], "gold_new_files": [],
         "gold_functions": [{"file": "calc/ops.py", "qualname": "add", "name": "add"}],
         "test_files": ["tests/test_ops.py"], "hidden_nodes": ["tests/test_ops.py::test_add"],
         "pre_hidden_nodes_pass": None, "known": []}
    if suite == "V":
        tree = {"gold": (GOLD, "gold", "edit", GOLD_STEPS, "CHANGED: calc/ops.py add (3-3)", 1),
                "wrong": (WRONG, "r2_v10_1", "edit", WRONG_STEPS, "CHANGED: calc/ops.py add (3-3)", 0),
                "empty": ("", "empty", "none", [], "CHANGED: nothing", 0)}[variant]
        g.update(tree_patch=tree[0], tree_source=tree[1], replay=tree[2], replay_steps=tree[3], notes_changed=tree[4],
                 pre_hidden_nodes_pass=tree[5])
    return g


def case(suite: str, variant: str = "-", **kw) -> dict:
    g = golden(suite, variant, **kw)
    cid = f"{suite}__{g['task']}" + (f"__{variant}" if suite == "V" else "")
    ref = PLAN if suite == "L" else GOLD
    return {"eval_case_id": cid, "prompt": {"role": "user", "parts": [{"text": STATEMENT}]},
            "reference": {"response": {"role": "model", "parts": [{"text": ref}]}}, "golden": g}


def write_dataset(path: Path, cases: list) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"eval_cases": cases}, indent=1, sort_keys=True) + "\n")
    return path


def make_env(root: Path) -> dict:
    """The calc task (tasks.jsonl + snapshot) under root: {'tasks_jsonl', 'snapshots_dir'}."""
    tasks, snaps = make_task(Path(root) / "task")
    return {"tasks_jsonl": str(tasks), "snapshots_dir": str(snaps)}


def make_task(root: Path, **kw):
    """test_v10_flow.make_task with the applicable GOLD as the task's patch."""
    kw.setdefault("gold", GOLD)
    return _flow_make_task(Path(root), **kw)

