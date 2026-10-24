"""G1 / G2 metric: which teacher trajectories are usable as Gemma training data (GAPS 'G1 pre-registration').

A trajectory (one task, one sample) is usable when the task is resolved, every tool call parsed (a name and a JSON-object
argument string), there are at most MAX_TOOL_CALLS tool calls, and the total generated tokens (each reply re-rendered as
Gemma would emit it by train/scorer_render.canonical_completion, reasoning included, counted with Gemma's tokenizer) are
at most TOKEN_BUDGET, the 5-minute L4 budget.

    python scripts/distill/usable.py --capture run/capture.jsonl --results 'run/items/*/*/task_results.jsonl' \
        --ids data/distill/g1_ids.txt --ec2-usd 12.5 --out run/usable.json
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "distill"))
sys.path.insert(0, str(ROOT / "scripts" / "golden"))
from router import classify  # noqa: E402
from train.build_sft import TaskIndex, first_user_text  # noqa: E402
from train.scorer_render import canonical_completion  # noqa: E402

TOKEN_BUDGET, MAX_TOOL_CALLS = 8700, 40
G1_MIN_USABLE, G1_MIN_NEW, G1_MAX_USD_PER_USABLE = 11, 4, 0.60
TASKS = ROOT / "data/heldout1k/harness_all/tasks.jsonl"
TOKENIZER = ROOT / "adapters/v11b/tokenizer.json"


def call_ok(msg: dict) -> bool:
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        if not fn.get("name"):
            return False
        try:
            if not isinstance(json.loads(fn.get("arguments") or "{}"), dict):
                return False
        except (TypeError, ValueError):
            return False
    return True


def is_summariser(body: dict) -> bool:
    """The harness's compaction calls (router.classify's mark), not the agent's; they are not counted."""
    return classify(body)[1] == "summarizer"


def trajectories(capture_rows, index: TaskIndex, count_tokens) -> dict:
    out: dict = {}
    for row in capture_rows:
        body, resp = row.get("body") or {}, row.get("response") or {}
        if is_summariser(body):
            continue
        task = index.lookup(first_user_text(body))
        if task is None:
            continue
        msg = ((resp.get("choices") or [{}])[0] or {}).get("message") or {}
        t = out.setdefault(task, {"calls": 0, "tool_calls": 0, "tokens": 0, "parse_ok": True})
        cont = t["calls"] > 0
        t["calls"] += 1
        t["tool_calls"] += len(msg.get("tool_calls") or [])
        ok = call_ok(msg)
        t["parse_ok"] = t["parse_ok"] and ok
        if ok:
            t["tokens"] += count_tokens(canonical_completion(msg, continuation=cont, thinking=True))
        else:   # unrenderable (bad tool JSON): the trajectory is already unusable; count its raw text
            raw = (msg.get("reasoning_content") or "") + (msg.get("content") or "") + "".join(
                str((c.get("function") or {}).get("arguments") or "") for c in msg.get("tool_calls") or [])
            t["tokens"] += count_tokens(raw)
    return out


def resolved_map(paths) -> dict:
    res: dict = {}
    for p in paths:
        for line in open(p):
            if line.strip():
                r = json.loads(line)
                res[r["instance_id"]] = res.get(r["instance_id"], False) or bool(r.get("resolved"))
    return res


def evaluate(trajs: dict, resolved: dict, ids: list, gemma: dict, ec2_usd: float | None) -> dict:
    per = {}
    for i in ids:
        t = trajs.get(i, {"calls": 0, "tool_calls": 0, "tokens": 0, "parse_ok": False})
        ok = bool(resolved.get(i)) and t["parse_ok"] and t["tool_calls"] <= MAX_TOOL_CALLS and t["tokens"] <= TOKEN_BUDGET
        per[i] = dict(t, resolved=bool(resolved.get(i)), usable=ok, gemma_solved=bool(gemma.get(i)))
    usable = sum(p["usable"] for p in per.values())
    new = sum(p["usable"] and not p["gemma_solved"] for p in per.values())
    usd = None if ec2_usd is None or not usable else round(ec2_usd / usable, 3)
    passed = usable >= G1_MIN_USABLE and new >= G1_MIN_NEW and (usd is not None and usd <= G1_MAX_USD_PER_USABLE)
    return {"n": len(ids), "resolved": sum(p["resolved"] for p in per.values()), "usable": usable,
            "usable_gemma_never_solved": new, "gemma_solved_ref": sum(p["gemma_solved"] for p in per.values()),
            "ec2_usd": ec2_usd, "usd_per_usable": usd, "g1_pass": passed,
            "rule": {"min_usable": G1_MIN_USABLE, "min_new": G1_MIN_NEW, "max_usd_per_usable": G1_MAX_USD_PER_USABLE,
                     "token_budget": TOKEN_BUDGET, "max_tool_calls": MAX_TOOL_CALLS},
            "tasks": per}


def main() -> None:
    from split import gemma_history
    from tokenizers import Tokenizer
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", nargs="+", required=True)
    ap.add_argument("--results", required=True, help="glob of task_results.jsonl files")
    ap.add_argument("--ids", required=True)
    ap.add_argument("--tasks", default=str(TASKS))
    ap.add_argument("--tokenizer", default=str(TOKENIZER))
    ap.add_argument("--ec2-usd", type=float, default=None)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    tok = Tokenizer.from_file(a.tokenizer)
    rows = [json.loads(l) for f in a.capture for l in open(f) if l.strip()]
    trajs = trajectories(rows, TaskIndex(a.tasks), lambda s: len(tok.encode(s, add_special_tokens=False).ids))
    rep = evaluate(trajs, resolved_map(sorted(glob.glob(a.results))), Path(a.ids).read_text().split(), gemma_history(),
                   a.ec2_usd)
    Path(a.out).write_text(json.dumps(rep, indent=1, sort_keys=True) + "\n")
    print({k: rep[k] for k in ("n", "resolved", "usable", "usable_gemma_never_solved", "gemma_solved_ref",
                               "usd_per_usable", "g1_pass")})


if __name__ == "__main__":
    main()
