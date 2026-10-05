"""Valid / dropped tasks of a gold pre-flight run by scripts/pallets/pod_probe.sh (PROBE_RUNS=fix).

  .venv/bin/python scripts/heldout/preflight_summary.py PROBE_OUT [--json OUT.json] [--valid-ids OUT.txt]

valid = fix_gold resolved AND fix_empty (test_patch only) did not resolve (research/pallets.md 7.3). Drop reasons come
from the harness's own TaskResult.error strings (swegemma/harness/verification.py) and, for plain test failures, the
pytest output in fix_gold/test_outputs/<tid>.log (import / fixture errors = gold_env_error, as oracle.py's ENV_ERR).
Tasks are only classified, never edited.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

ENV_ERR = re.compile(r"(ModuleNotFoundError|ImportError|cannot import name|No module named|AttributeError: module "
                     r"'[\w.]+' has no attribute|fixture '[\w]+' not found|SyntaxError|unrecognized arguments)")


def classify(tid: str, gold: dict | None, empty: dict | None, gold_out: str = "") -> str:
    if gold is None:
        return "no_result"
    if gold.get("resolved"):
        if empty is None:
            return "empty_no_result"
        return "empty_resolves" if empty.get("resolved") else "valid"
    err = gold.get("error") or ""
    if err.startswith("Failed to apply test_patch"):
        return "test_patch_no_apply"
    if err.startswith("Failed to apply agent patch"):
        return "gold_no_apply"
    if err.startswith(("Evaluation error", "Missing test specification")):
        return "harness_error"
    if "Missing JUnit XML" in err:
        return "gold_no_junit"
    if "No passing tests" in err or "zero or no passing" in err or "Required test node" in err:
        return "gold_junit_reject"
    if "Test failures/errors recorded" in err:
        return "gold_tests_fail"
    if gold.get("test_exit_code") in (124, 137, -9) or "timed out" in gold_out.lower()[-2000:]:
        return "gold_timeout"
    if ENV_ERR.search(gold_out):
        return "gold_env_error"
    return "gold_tests_fail"


def _rows(p: Path) -> dict:
    if not p.is_file():
        return {}
    return {json.loads(ln)["instance_id"]: json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()}


def summarize(d: Path) -> dict:
    d = Path(d)
    gold, empty = _rows(d / "fix_gold" / "task_results.jsonl"), _rows(d / "fix_empty" / "task_results.jsonl")
    ids = (d / "ids.txt").read_text().split() if (d / "ids.txt").is_file() else sorted(set(gold) | set(empty))
    by_task = {}
    for t in ids:
        lp = d / "fix_gold" / "test_outputs" / f"{t}.log"
        out = lp.read_text(errors="replace") if lp.is_file() else ""
        by_task[t] = classify(t, gold.get(t), empty.get(t), out)
    reasons = Counter(by_task.values())
    per_repo: dict = {}
    for t, c in by_task.items():
        repo = (gold.get(t) or empty.get(t) or {}).get("repo") or t.rsplit("_", 1)[0]
        per_repo.setdefault(repo, Counter())[c] += 1
    return {"n": len(ids), "valid": reasons.get("valid", 0), "reasons": dict(reasons.most_common()),
            "valid_ids": [t for t in ids if by_task[t] == "valid"], "by_task": by_task,
            "per_repo": {k: dict(v) for k, v in sorted(per_repo.items())}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("probe_out")
    ap.add_argument("--json")
    ap.add_argument("--valid-ids")
    a = ap.parse_args()
    s = summarize(Path(a.probe_out))
    print(f"preflight: {s['valid']}/{s['n']} valid ({s['valid'] / max(1, s['n']):.1%}); reasons {s['reasons']}")
    for repo, c in s["per_repo"].items():
        bad = {k: v for k, v in c.items() if k != "valid"}
        print(f"  {repo:32s} valid {c.get('valid', 0):3d}/{sum(c.values()):3d}  {bad if bad else ''}")
    if a.json:
        Path(a.json).write_text(json.dumps(s, indent=1, sort_keys=True) + "\n")
    if a.valid_ids:
        Path(a.valid_ids).write_text("".join(t + "\n" for t in s["valid_ids"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
