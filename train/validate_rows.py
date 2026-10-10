"""Validate build_sft rows before they go anywhere (Carson 2026-10-02: every case handled before Adaption).

    python train/validate_rows.py rows.jsonl --exclude-ids data/pallets/dev40_ids.txt --exclude-ids data/pallets/holdout_ids.txt \
        [--min-rows 10000] [--max-tokens 30000] [--report report.json]

Checks (all must hold, exit 1 otherwise): every row has a non-empty prompt starting with <bos> and a completion that ends
with <|tool_response> or <turn|>; no completion is empty text or over max-tokens; no prompt exceeds max-tokens (the scorer's
32k context, with margin); no task id in any exclude list (eval sets); no duplicate (prompt, completion); the row count
meets --min-rows; every stage name is one of the bundle's; tool-call completions name a known tool. The report lists rows,
tasks, rows per task, stages, tools, token percentiles, and the count of continuation rows.
"""
from __future__ import annotations

import argparse
import hashlib
import json, re
import sys
from collections import Counter
from pathlib import Path

KNOWN_TOOLS = {"run_command", "read_file", "write_file", "edit_file", "get_status", "get_code_neighbors", "search_similar_code",
               "get_code_subgraph", "run_skill_script", "load_skill_resource", "submit_patch"}
STAGES = {"locator", "fixer", "verifier", "setup", "submitter", None}


def tokenizer():
    try:
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer
        return Tokenizer.from_file(hf_hub_download("google/gemma-4-31b-it-qat-w4a16-ct", "tokenizer.json"))
    except Exception:  # noqa: BLE001
        return None


THOUGHT_RE = re.compile(r"<\|channel>thought\n.*?<channel\|>", re.S)   # the (possibly empty) thought channel in front of a completion


def validate(path, exclude=frozenset(), min_rows=10000, max_tokens=30000, tok=None, require_thought=False):
    problems, seen = [], set()
    thought_rows = 0
    tasks, stages, tools, ptoks, ctoks, cont = Counter(), Counter(), Counter(), [], [], 0
    n = 0
    for i, line in enumerate(open(path)):
        if not line.strip():
            continue
        r = json.loads(line); n += 1
        p, c, m = r.get("prompt"), r.get("completion"), r.get("meta") or {}
        if not isinstance(p, str) or not p.startswith("<bos>"):
            problems.append((i, "prompt does not start with <bos>"))
        if not isinstance(c, str) or not (c.endswith("<|tool_response>") or c.endswith("<turn|>")):
            problems.append((i, "completion has no terminal token"))
        elif THOUGHT_RE.sub("", c, count=1).strip() in ("<|tool_response>", "<turn|>"):
            problems.append((i, "empty completion"))
        if isinstance(c, str):
            mt = THOUGHT_RE.match(c)
            has_thought = bool(mt) and mt.group(0) != "<|channel>thought\n<channel|>"
            thought_rows += has_thought
            if require_thought and not has_thought:
                problems.append((i, "no thought channel (thinking-on rows must carry reasoning)"))
        if m.get("task") in exclude:
            problems.append((i, f"eval-set task {m.get('task')}"))
        if m.get("stage") not in STAGES:
            problems.append((i, f"unknown stage {m.get('stage')}"))
        if m.get("tool") is not None and m.get("tool") not in KNOWN_TOOLS:
            problems.append((i, f"unknown tool {str(m.get('tool'))[:40]}"))
        h = hashlib.sha1((str(p) + "\x00" + str(c)).encode("utf-8", "replace")).hexdigest()
        if h in seen:
            problems.append((i, "duplicate row"))
        seen.add(h)
        if tok is not None:
            pt = len(tok.encode(p, add_special_tokens=False).ids); ct = len(tok.encode(c, add_special_tokens=False).ids)
            ptoks.append(pt); ctoks.append(ct)
            if pt + ct > max_tokens:
                problems.append((i, f"{pt + ct} tokens > {max_tokens}"))
        tasks[m.get("task")] += 1; stages[m.get("stage")] += 1; tools[m.get("tool")] += 1; cont += bool(m.get("continuation"))
    if n < min_rows:
        problems.append((-1, f"{n} rows < min {min_rows}"))
    pct = lambda xs, q: sorted(xs)[int(q * (len(xs) - 1))] if xs else None  # noqa: E731
    report = {"rows": n, "tasks": len(tasks), "rows_per_task": round(n / max(1, len(tasks)), 1), "stages": dict(stages),
              "tools": dict(tools.most_common(12)), "continuation_rows": cont, "rows_with_thought": thought_rows,
              "prompt_tokens_p50_p90_max": [pct(ptoks, .5), pct(ptoks, .9), max(ptoks) if ptoks else None],
              "completion_tokens_p50_p90_max": [pct(ctoks, .5), pct(ctoks, .9), max(ctoks) if ctoks else None],
              "problems": len(problems), "first_problems": problems[:20], "ok": not problems}
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rows"); ap.add_argument("--exclude-ids", action="append", default=[])
    ap.add_argument("--min-rows", type=int, default=10000); ap.add_argument("--max-tokens", type=int, default=30000)
    ap.add_argument("--report", default=None); ap.add_argument("--no-tokenizer", action="store_true")
    ap.add_argument("--require-thought", action="store_true", help="every completion must carry a non-empty thought channel (thinking-on data)")
    a = ap.parse_args()
    excl = set()
    for p in a.exclude_ids:
        excl |= {l.strip() for l in open(p) if l.strip()}
    rep = validate(a.rows, excl, a.min_rows, a.max_tokens, None if a.no_tokenizer else tokenizer(), a.require_thought)
    print(json.dumps(rep, indent=1))
    if a.report:
        Path(a.report).parent.mkdir(parents=True, exist_ok=True); json.dump(rep, open(a.report, "w"), indent=1)
    sys.exit(0 if rep["ok"] else 1)


if __name__ == "__main__":
    main()
