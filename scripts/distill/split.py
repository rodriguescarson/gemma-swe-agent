"""Repo-disjoint EVAL / TRAIN split for the teacher-distillation track (plan 2026-10-24, step 2).

The hidden set is private repositories, so configurations are chosen on whole repos that no training row came from.
Rule (fixed before any teacher or adapter run, deterministic, no randomness):

  1. pool = data/heldout1k valid tasks (all packed in harness_all), minus every public-74 id (data/kaggle_valid_ids.txt);
  2. candidate EVAL repos: REPO_MIN..REPO_MAX tasks and a Gemma history (P10/P3 runs) on at least half of them;
  3. order candidates by Gemma's per-task solve rate (any sample solved), ties by name, and take every other one from the
     hardest (indices 0, 2, 4, ...), then the skipped ones in the same order, until EVAL holds >= TARGET tasks;
  4. TRAIN = every other pool task. Gemma's own solved runs count toward the training mix only on TRAIN repos.

    python scripts/distill/split.py            # writes data/distill/{eval,train}_ids.txt and split_report.json
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / "data/heldout1k/harness_all/tasks.jsonl"
VALID = ROOT / "data/heldout1k/all_valid_ids.txt"
PUBLIC = ROOT / "data/kaggle_valid_ids.txt"
HISTORY = ("eval/a6000/results/p3*/items/*/*/task_results.jsonl", "eval/a6000/results/p3/s*/task_results.jsonl")
OUT = ROOT / "data/distill"
REPO_MIN, REPO_MAX, TARGET = 20, 60, 200


def gemma_history(root: Path = ROOT) -> dict:
    """{instance_id: solved in any recorded Gemma sample}."""
    seen: dict = {}
    for pat in HISTORY:
        for f in sorted(glob.glob(str(root / pat))):
            for line in open(f):
                if line.strip():
                    r = json.loads(line)
                    seen[r["instance_id"]] = seen.get(r["instance_id"], False) or bool(r.get("resolved"))
    return seen


def split(repo_of: dict, pool: set, history: dict, *, repo_min: int = REPO_MIN, repo_max: int = REPO_MAX,
          target: int = TARGET) -> dict:
    by_repo = collections.defaultdict(list)
    for i in sorted(pool):
        by_repo[repo_of[i]].append(i)
    rate = {}
    for repo, ids in by_repo.items():
        tried = [i for i in ids if i in history]
        if repo_min <= len(ids) <= repo_max and len(tried) * 2 >= len(ids):
            rate[repo] = sum(history[i] for i in tried) / len(tried)
    order = sorted(rate, key=lambda r: (rate[r], r))
    picks = order[0::2] + order[1::2]
    eval_repos, n = [], 0
    for repo in picks:
        if n >= target:
            break
        eval_repos.append(repo)
        n += len(by_repo[repo])
    if n < target:
        raise ValueError(f"only {n} EVAL tasks from {len(order)} candidate repos; loosen REPO_MIN/REPO_MAX")
    eval_ids = sorted(i for r in eval_repos for i in by_repo[r])
    train_ids = sorted(i for i in pool if repo_of[i] not in set(eval_repos))
    per_repo = {r: {"tasks": len(ids), "set": "EVAL" if r in eval_repos else "TRAIN",
                    "gemma_tried": sum(i in history for i in ids), "gemma_solved": sum(history.get(i, False) for i in ids)}
                for r, ids in sorted(by_repo.items())}
    return {"rule": {"repo_min": repo_min, "repo_max": repo_max, "target": target, "order": "solve rate asc, alternate"},
            "eval_repos": eval_repos, "eval_n": len(eval_ids), "train_n": len(train_ids),
            "eval_gemma_solve_rate": round(sum(history.get(i, False) for i in eval_ids)
                                           / max(1, sum(i in history for i in eval_ids)), 4),
            "train_gemma_solved_tasks": sum(history.get(i, False) for i in train_ids),
            "per_repo": per_repo, "repo_of": {i: repo_of[i] for i in eval_ids + train_ids},
            "eval_ids": eval_ids, "train_ids": train_ids}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    repo_of = {}
    for line in open(TASKS):
        r = json.loads(line)
        repo_of[r["instance_id"]] = r["repo"]
    public = set(PUBLIC.read_text().split())
    pool = set(VALID.read_text().split()) - public
    rep = split(repo_of, pool, gemma_history())
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "eval_ids.txt").write_text("\n".join(rep["eval_ids"]) + "\n")
    (out / "train_ids.txt").write_text("\n".join(rep["train_ids"]) + "\n")
    slim = {k: v for k, v in rep.items() if k not in ("eval_ids", "train_ids")}
    (out / "split_report.json").write_text(json.dumps(slim, indent=1, sort_keys=True) + "\n")
    print(f"EVAL {rep['eval_n']} tasks from {rep['eval_repos']} (Gemma solve rate {rep['eval_gemma_solve_rate']}); "
          f"TRAIN {rep['train_n']} tasks; Gemma-solved TRAIN tasks {rep['train_gemma_solved_tasks']}")


if __name__ == "__main__":
    main()
