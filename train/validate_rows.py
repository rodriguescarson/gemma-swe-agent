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
STAGES = {"locator", "fixer", "verifier", "setup", "submitter", "swe_single_agent", None}   # swe_single_agent = submissions/v12 (2026-10-11)


def tokenizer():
    try:
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer
        return Tokenizer.from_file(hf_hub_download("google/gemma-4-31b-it-qat-w4a16-ct", "tokenizer.json"))
    except Exception:  # noqa: BLE001
        return None


THOUGHT_RE = re.compile(r"<\|channel>thought\n.*?<channel\|>", re.S)   # the (possibly empty) thought channel in front of a completion


def validate(path, exclude=frozenset(), min_rows=10000, max_tokens=30000, tok=None, require_thought=False, min_thought_share=0.0):
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
    thought_share = round(thought_rows / n, 4) if n else 0.0
    if min_thought_share and thought_share < min_thought_share:
        problems.append((-1, f"thought share {thought_share} < min {min_thought_share} (rows with a non-empty thought channel / rows)"))
    pct = lambda xs, q: sorted(xs)[int(q * (len(xs) - 1))] if xs else None  # noqa: E731
    report = {"rows": n, "tasks": len(tasks), "rows_per_task": round(n / max(1, len(tasks)), 1), "stages": dict(stages),
              "tools": dict(tools.most_common(12)), "continuation_rows": cont, "rows_with_thought": thought_rows, "thought_share": thought_share,
              "prompt_tokens_p50_p90_max": [pct(ptoks, .5), pct(ptoks, .9), max(ptoks) if ptoks else None],
              "completion_tokens_p50_p90_max": [pct(ctoks, .5), pct(ctoks, .9), max(ctoks) if ctoks else None],
              "problems": len(problems), "first_problems": problems[:20], "ok": not problems}
    return report


def validate_stitched(path, exclude=frozenset(), max_tokens=14336, tok=None, require_thought=False, min_seqs=1, min_thought_share=0.0):
    """Stitched sequences (train/stitch_rows.py): {"text", "spans": [[a, b, w]], "meta"}. Checks: <bos> start, the spans are exactly the
    model spans of the text (train/spans.py), at least one span trained, no duplicate text, token cap, excluded tasks absent, and
    with --require-thought at least one NON-EMPTY thought channel per sequence; with --min-thought-share the share of model spans that
    start with a non-empty thought channel (the P11 gate: >= 0.8, the same bar as the capture gate (a))."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from train.spans import describe_span, supervised_char_spans
    problems, seen = [], set()
    n, toks, thought_seqs, trained_chars, masked_chars, stages = 0, [], 0, 0, 0, Counter()
    model_spans = thought_spans = 0
    for i, line in enumerate(open(path)):
        if not line.strip():
            continue
        r = json.loads(line); n += 1
        t, sp, m = r.get("text"), r.get("spans"), r.get("meta") or {}
        if not isinstance(t, str) or not t.startswith("<bos>"):
            problems.append((i, "text does not start with <bos>")); continue
        if not isinstance(sp, list) or not sp or any(len(x) != 3 for x in sp):
            problems.append((i, "spans missing or malformed")); continue
        model_sp = supervised_char_spans(t)
        if [(a, b) for a, b, w in sp] != list(model_sp):
            problems.append((i, "spans are not the model spans of the text"))
        model_spans += len(model_sp); thought_spans += sum(describe_span(t, a, b)["thought"] for a, b in model_sp)
        if not any(w > 0 for a, b, w in sp):
            problems.append((i, "no span with weight > 0"))
        trained_chars += sum(b - a for a, b, w in sp if w > 0); masked_chars += sum(b - a for a, b, w in sp if w == 0)
        has_thought = any(mm.group(0) != "<|channel>thought\n<channel|>" for mm in THOUGHT_RE.finditer(t))
        thought_seqs += has_thought
        if require_thought and not has_thought:
            problems.append((i, "no non-empty thought channel"))
        if m.get("task") in exclude:
            problems.append((i, f"eval-set task {m.get('task')}"))
        h = hashlib.sha1(t.encode("utf-8", "replace")).hexdigest()
        if h in seen:
            problems.append((i, "duplicate sequence"))
        seen.add(h)
        nt = len(tok.encode(t, add_special_tokens=False).ids) if tok is not None else m.get("tokens")
        if nt is not None:
            toks.append(nt)
            if nt > max_tokens:
                problems.append((i, f"{nt} tokens > {max_tokens}"))
        stages[m.get("stage")] += 1
    if n < min_seqs:
        problems.append((-1, f"{n} sequences < min {min_seqs}"))
    thought_share = round(thought_spans / model_spans, 4) if model_spans else 0.0
    if min_thought_share and thought_share < min_thought_share:
        problems.append((-1, f"thought share {thought_share} < min {min_thought_share} (model spans starting with a non-empty thought channel / model spans)"))
    pct = lambda xs, q: sorted(xs)[int(q * (len(xs) - 1))] if xs else None  # noqa: E731
    return {"sequences": n, "stages": dict(stages), "sequences_with_thought": thought_seqs,
            "model_spans": model_spans, "thought_spans": thought_spans, "thought_share": thought_share, "trained_chars": trained_chars, "masked_chars": masked_chars,
            "tokens_p50_p90_max": [pct(toks, .5), pct(toks, .9), max(toks) if toks else None], "tokens_total": sum(toks),
            "problems": len(problems), "first_problems": problems[:20], "ok": not problems}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stitched", action="store_true", help="validate stitched sequences (train/stitch_rows.py output) instead of rows")
    ap.add_argument("rows"); ap.add_argument("--exclude-ids", action="append", default=[])
    ap.add_argument("--min-rows", type=int, default=10000); ap.add_argument("--max-tokens", type=int, default=30000)
    ap.add_argument("--report", default=None); ap.add_argument("--no-tokenizer", action="store_true")
    ap.add_argument("--require-thought", action="store_true", help="every completion must carry a non-empty thought channel (thinking-on data)")
    ap.add_argument("--min-thought-share", type=float, default=0.0, help="gate: rows (or stitched model spans) with a non-empty thought channel / all, >= this (P11: 0.8)")
    a = ap.parse_args()
    excl = set()
    for p in a.exclude_ids:
        excl |= {l.strip() for l in open(p) if l.strip()}
    tok = None if a.no_tokenizer else tokenizer()
    rep = (validate_stitched(a.rows, excl, a.max_tokens, tok, a.require_thought, a.min_rows, a.min_thought_share) if a.stitched
           else validate(a.rows, excl, a.min_rows, a.max_tokens, tok, a.require_thought, a.min_thought_share))
    print(json.dumps(rep, indent=1))
    if a.report:
        Path(a.report).parent.mkdir(parents=True, exist_ok=True); json.dump(rep, open(a.report, "w"), indent=1)
    sys.exit(0 if rep["ok"] else 1)


if __name__ == "__main__":
    main()
