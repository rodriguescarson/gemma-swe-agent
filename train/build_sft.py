"""Turn or_proxy --capture JSONL (the exact requests the harness sent and the exact replies) into SFT rows for
Adaption / Together `instruction` format: {"prompt": <scorer-rendered prefix>, "completion": <canonical reply>} (P0.3).

    python train/build_sft.py --capture CAP.jsonl [--capture ...] --tasks data/pallets/harness/tasks.jsonl \
        --results eval/runs/<run>/pl_<bundle>/task_results.jsonl [--results ...] --out data/v11/rows.jsonl \
        [--exclude-ids data/pallets/dev40_ids.txt ...] [--all-outcomes] [--max-prompt-chars 160000]

Rules (docs/v11/PLAN.md 4, council): success-only by default (the task's result row says resolved); tasks in any
--exclude-ids file are refused (eval sets never enter training: a planted id makes the builder exit 2); a row is one
model call: prompt = train.scorer_render.render(body) (the generation prompt included), completion =
canonical_completion(reply, continuation = last message is a tool result); replies with neither tool calls nor text,
or cut off (finish_reason length), are dropped; exact duplicate rows are dropped. A call is attributed to its task by
matching the task's problem statement inside the first user message (captures of concurrent tasks interleave).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from train.scorer_render import canonical_completion, render  # noqa: E402

STAGE_MARK = 'Your internal name is "'


def stage_of(body):
    for m in body.get("messages", []):
        if m.get("role") == "system":
            t = m.get("content") if isinstance(m.get("content"), str) else " ".join(p.get("text", "") for p in (m.get("content") or []) if isinstance(p, dict))
            i = t.find(STAGE_MARK)
            if i >= 0:
                return t[i + len(STAGE_MARK):].split('"', 1)[0]
    return None


def first_user_text(body):
    """The text to match a task against: the system prompt (fixer/verifier carry the issue there, via
    {problem_description}) plus the first user message (the locator's task prompt)."""
    out = []
    for m in body.get("messages", []):
        if m.get("role") in ("system", "user"):
            c = m.get("content")
            out.append(c if isinstance(c, str) else " ".join(p.get("text", "") for p in (c or []) if isinstance(p, dict)))
            if m.get("role") == "user":
                break
    return "\n".join(out)


class TaskIndex:
    """problem statement -> instance_id, longest statements first so a statement that contains another wins."""

    def __init__(self, tasks_path):
        rows = [json.loads(l) for l in open(tasks_path) if l.strip()]
        self.items = sorted(((r["problem_statement"].strip(), r["instance_id"]) for r in rows if r.get("problem_statement")),
                            key=lambda x: -len(x[0]))
        self.cache = {}

    def lookup(self, user_text):
        key = hashlib.sha1(user_text.encode("utf-8", "replace")).hexdigest()
        if key in self.cache:
            return self.cache[key]
        hit = next((tid for stmt, tid in self.items if stmt[:400] in user_text), None)
        self.cache[key] = hit
        return hit


def load_results(paths):
    out = {}
    for p in paths:
        for l in open(p):
            if l.strip():
                r = json.loads(l)
                out[r.get("instance_id") or r.get("id")] = str(r.get("resolved")) == "True"
    return out


def build(captures, tasks_path, results_paths, exclude_ids=frozenset(), success_only=True, max_prompt_chars=160000, pairs=()):
    """captures share the results in results_paths; pairs = [(capture, [results...])] bind a capture to its own sample's
    results, so a solved and an unsolved sample of the same task never share a verdict."""
    idx = TaskIndex(tasks_path)
    pool = load_results(results_paths)
    stats, seen, rows = Counter(), set(), []
    work = [(c, pool) for c in captures] + [(c, load_results(r)) for c, r in pairs]
    for cap, resolved in work:
        for line in open(cap):
            if not line.strip():
                continue
            e = json.loads(line)
            body, resp = e["body"], e["response"]
            stats["calls"] += 1
            tid = idx.lookup(first_user_text(body))
            if tid is None:
                stats["no_task"] += 1
                continue
            if tid in exclude_ids:
                print(f"LEAK GUARD: capture contains excluded task {tid}; refusing to build (exit 2)", file=sys.stderr)
                raise SystemExit(2)
            if success_only and not resolved.get(tid, False):
                stats["unsolved_or_unknown"] += 1
                continue
            ch = (resp.get("choices") or [{}])[0]
            msg = ch.get("message") or {}
            if ch.get("finish_reason") == "length":
                stats["cut_off"] += 1
                continue
            if not msg.get("tool_calls") and not (msg.get("content") or "").strip():
                stats["empty_reply"] += 1
                continue
            prompt = render(body)
            if len(prompt) > max_prompt_chars:
                stats["too_long"] += 1
                continue
            continuation = body["messages"][-1].get("role") == "tool"
            completion = canonical_completion(msg, continuation)
            h = hashlib.sha1((prompt + "\x00" + completion).encode("utf-8", "replace")).hexdigest()
            if h in seen:
                stats["duplicate"] += 1
                continue
            seen.add(h)
            rows.append({"prompt": prompt, "completion": completion,
                         "meta": {"task": tid, "traj": f"{os.path.basename(cap)}|{tid}", "stage": stage_of(body), "continuation": continuation,
                                  "tool": (msg.get("tool_calls") or [{}])[0].get("function", {}).get("name") if msg.get("tool_calls") else None}})
            stats["rows"] += 1
    return rows, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", action="append", default=[], help="capture(s) judged by the shared --results pool")
    ap.add_argument("--pair", action="append", default=[], help="CAPTURE=RESULTS: a capture judged by its own sample's results")
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--results", action="append", default=[])
    ap.add_argument("--out", required=True)
    ap.add_argument("--exclude-ids", action="append", default=[])
    ap.add_argument("--all-outcomes", action="store_true", help="keep calls from unsolved tasks too")
    ap.add_argument("--max-prompt-chars", type=int, default=160000)
    a = ap.parse_args()
    excl = set()
    for p in a.exclude_ids:
        excl |= {l.strip() for l in open(p) if l.strip()}
    pairs = [(c.split("=", 1)[0], [c.split("=", 1)[1]]) for c in a.pair]
    if not a.capture and not pairs:
        ap.error("give --capture (with --results) or --pair CAPTURE=RESULTS")
    if a.capture and not a.results:
        ap.error("--capture needs --results")
    rows, stats = build(a.capture, a.tasks, a.results, excl, not a.all_outcomes, a.max_prompt_chars, pairs)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tasks = Counter(r["meta"]["task"] for r in rows)
    stages = Counter(r["meta"]["stage"] for r in rows)
    print(json.dumps({"stats": dict(stats), "tasks": len(tasks), "rows_per_task": round(len(rows) / max(1, len(tasks)), 1),
                      "stages": dict(stages)}, indent=1))


if __name__ == "__main__":
    main()
