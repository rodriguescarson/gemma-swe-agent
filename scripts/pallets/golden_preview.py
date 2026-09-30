"""Preview of the golden-eval fixture fields that are computable for SWE-Pallets-X today (research/pallets.md section 8).

  .venv/bin/python scripts/pallets/golden_preview.py [--ids data/pallets/valid_ids.txt] [--no-nodes]
      [--out data/pallets/golden_preview.json]

Nothing under eval/golden/, scripts/golden*, tests/test_golden_* is written or edited. The golden builder's PURE
functions are imported read-only from scripts/golden/fixture_lib.py (plan_entries, files_line, gold_functions,
tests_line, title_words), and the hidden nodes come from tests/v10_support/tasks.hidden_claim_nodes, rebound to the
pallets data by scripts/pallets/source.activate() (its workspace cache is ~/.cache/g4/pallets/_ws, not the golden one).
Per task (keys sorted):
  gold_files, gold_new_files, gold_functions, plan_basis ('ast': originals read from the snapshot tar), files_line
  (the FILES line of GOLDEN_EVALS_SPEC 4.1), tests_line (the TESTS line), title_words (from the PR-style statement,
  data/pallets/tasks_prstyle.jsonl), test_files (the grader's targets, tasks.extract_targets), hidden_nodes (4.5),
  split / stratum (data/pallets/split.json; stratum = '<repo>/unrun', no race outcomes exist), plan_words_files.
What is NOT here and why: CAUSE / FIX need a pallets task_catalog (root_cause, one_line_solution); REPRO needs a real
v10 locator trace on the task; V 'wrong' needs a real unresolved patch; gradable = data/pallets/valid_ids.txt.
"""
from __future__ import annotations

import argparse
import json
import sys
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import source  # noqa: E402

T = source.activate()
sys.path.insert(0, str(ROOT / "scripts" / "golden"))
import fixture_lib as FL  # noqa: E402  (read-only use of its pure functions)

PAL = source.PAL


def snapshot_reader(tid: str):
    tf = tarfile.open(PAL / "snapshots" / f"{tid}.tgz", "r:gz")
    members = {}
    for m in tf.getmembers():
        name = m.name[2:] if m.name.startswith("./") else m.name
        if m.isfile():
            members[name] = m

    def read(path: str):
        m = members.get(path)
        if m is None:
            return None
        return tf.extractfile(m).read().decode("utf-8", errors="replace")

    return read, (lambda p: p in members), tf


def preview(tid: str, statement: str, split: dict, nodes: bool) -> dict:
    t = T.load_task(tid)
    read, exists, tf = snapshot_reader(tid)
    try:
        parsed = FL.parse(t["patch"])
        originals = {(fp.old_path or fp.path): read(fp.old_path or fp.path) for fp in parsed if fp.path and not fp.new_file}
        entries, basis = FL.plan_entries(t["patch"], originals)
        gold_files = list(dict.fromkeys(e["file"] for e in entries))
        files = FL.files_line(entries)
        tests = FL.tests_line(t["test_patch"], gold_files, exists)
    finally:
        tf.close()
    s = split.get("tasks", {}).get(tid, {})
    row = {
        "gold_files": gold_files,
        "gold_new_files": [e["file"] for e in entries if e["new_file"]],
        "gold_functions": FL.gold_functions(entries),
        "plan_basis": basis,
        "files_line": files,
        "plan_words_files": len(files.split()),
        "tests_line": "TESTS: " + tests,
        "title_words": FL.title_words(statement),
        "test_files": T.extract_targets(t["test_patch"]),
        "split": s.get("split"),
        "stratum": f"{s.get('repo', t['repo'].split('/')[-1])}/unrun",
        "venv": s.get("venv"),
    }
    if nodes:
        try:
            row["hidden_nodes"] = T.hidden_claim_nodes(tid)
        except BaseException as ex:          # pytest.skip is a BaseException
            row["hidden_nodes"] = None
            row["hidden_nodes_why"] = f"{type(ex).__name__}: {ex}"[:300]
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default=str(PAL / "valid_ids.txt"))
    ap.add_argument("--out", default=str(PAL / "golden_preview.json"))
    ap.add_argument("--no-nodes", action="store_true", help="skip hidden_claim_nodes (it builds a base workspace)")
    a = ap.parse_args()
    ids = [x for x in Path(a.ids).read_text().split() if x]
    prs = {json.loads(ln)["instance_id"]: json.loads(ln)["problem_statement"]
           for ln in open(PAL / "tasks_prstyle.jsonl") if ln.strip()}
    split = json.loads((PAL / "split.json").read_text()) if (PAL / "split.json").is_file() else {}
    out = {}
    for i, tid in enumerate(ids, 1):
        out[tid] = preview(tid, prs.get(tid) or T.load_task(tid)["problem_statement"], split, not a.no_nodes)
        if not a.no_nodes:
            import shutil
            T._BASE_MEMO.clear()
            shutil.rmtree(T.CACHE / tid, ignore_errors=True)
        if i % 25 == 0:
            print(f"golden_preview: {i}/{len(ids)}", flush=True)
    Path(a.out).write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    n = len(out)
    stats = {
        "tasks": n,
        "plan_basis_ast": sum(1 for r in out.values() if r["plan_basis"] == "ast"),
        "with_gold_function": sum(1 for r in out.values() if r["gold_functions"]),
        "files_line_over_6_entries": sum(1 for r in out.values() if " more places in " in r["files_line"]),
        "tests_line_none": sum(1 for r in out.values() if r["tests_line"] == "TESTS: none"),
        "hidden_nodes_nonempty": sum(1 for r in out.values() if r.get("hidden_nodes")),
    }
    print(json.dumps(stats, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
