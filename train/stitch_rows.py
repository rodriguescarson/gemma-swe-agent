"""Stitch build_sft rows into one training sequence per (trajectory, stage) with weighted supervised spans (plan
~/.claude/plans/nifty-sleeping-liskov.md, "Training step design").

Why: build_sft renders the full history per call, so a 10,884-row set is 70.7M tokens of which 1.3 % are supervised (98 h
per epoch on the A6000). The rows of one (traj, stage) are prefixes of each other; the maximal one plus its completion holds
every model span of the stage: 2,496 sequences and 16.7M tokens for the same supervised tokens.

Chain rule, checked row by row: the next prompt must start with the previous prompt + completion. One known exception is
healed: the model emits the empty thought channel on a continuation call (and on thinking-on calls with no reasoning), but
the harness sends the history back without it, so the next prompt lacks those 25 characters; the stitched text keeps the
MODEL's bytes (the span is then exactly what it produced; the context differs from serving by that empty channel). Any
other break splits the group into two sequences and is counted. With thinking on and reasoning carried back, the chain is
byte-exact (tests/test_thinking_rows.py).

    python train/stitch_rows.py rows.jsonl --out seqs.jsonl --report report.json [--max-seqs-per-task-stage 10]
           [--max-tokens 14336] [--tokenizer-json adapters/v11b/tokenizer.json] [--read-share 0.15] [--seed 1]
           [--holdout-tasks ids.txt --holdout-out holdout.jsonl]
Output rows: {"text", "spans": [[a, b, w], ...], "meta": {task, traj, stage, calls, tokens, breaks}}."""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from train.spans import EMPTY_THOUGHT, TR_OPEN, supervised_char_spans, weight_spans  # noqa: E402

CHARS_PER_TOKEN = 3.6   # measured on the v11b rows (plan); used when no tokenizer is given


COMPACTION_MARK = "For context:[model] said:"   # ADK's events compaction: the history is replaced by a summary user turn


def stitch_group(rows):
    """rows of one (traj, stage) IN FILE ORDER (build_sft writes them in capture order; a length sort would put a compacted,
    shorter prompt before the uncompacted ones) -> [(text, n_calls, n_breaks, n_healed, n_compactions)], one item per
    uninterrupted chain.

    The harness only appends, so each prompt must start with the previous prompt (or the previous prompt minus the empty thought
    channel the thinking-off template put at its end: the harness renders that turn without it); the delta is the harness's
    rendering of the previous reply followed by the tool response. Exact: the delta starts with the model's own completion
    (thinking on with reasoning carried back). Healed: it does not (the harness drops the model's empty thought channel and
    re-serialises tool-call arguments through its own parser), so the model's bytes are kept and the delta is taken from the
    harness's `<|tool_response>` stop token onward. A compaction (the summary user turn) or any other divergence inside the
    shared prefix starts a new sequence: the model's context really changed there."""
    out, text, calls, breaks, healed, compactions = [], None, 0, 0, 0, 0
    prev_prompt = last_completion = prev_text = None
    for r in rows:
        p, c = r["prompt"], r["completion"]
        if text is not None:
            base = prev_prompt
            if not p.startswith(base) and base.endswith(EMPTY_THOUGHT):
                base = base[:-len(EMPTY_THOUGHT)]
            if p.startswith(base):
                delta = p[len(base):]
                k = delta.find(TR_OPEN) if last_completion.endswith(TR_OPEN) else -1
                if delta.startswith(last_completion):
                    text += delta[len(last_completion):] + c
                elif k >= 0:
                    text += delta[k + len(TR_OPEN):] + c              # the model's reply as it produced it, then the harness's continuation
                    healed += 1
                else:
                    text = None
            else:
                text = None
        if text is None:
            if prev_prompt is not None:
                if COMPACTION_MARK in p and COMPACTION_MARK not in prev_prompt:
                    compactions += 1
                else:
                    breaks += 1
                out.append((prev_text, calls, 0, healed, 0))
                calls, healed = 0, 0
            text = p + c
        calls += 1
        prev_prompt, last_completion, prev_text = p, c, text
    out.append((text, calls, breaks, healed, compactions))
    return out


def count_tokens(text, tok):
    return len(tok.encode(text, add_special_tokens=False).ids) if tok is not None else int(len(text) / CHARS_PER_TOKEN)


def auto_holdout(rows, n, seed=1):
    """n tasks chosen by a seeded draw among the tasks present (used when no holdout file names tasks of this collection)."""
    import random
    tasks = sorted({r["meta"]["task"] for r in rows})
    return set(random.Random(seed).sample(tasks, min(n, len(tasks))))


def stitch(rows, max_per_task_stage=10, max_tokens=14336, tok=None, read_share=0.15, seed=1, holdout=frozenset()):
    groups, rep = defaultdict(list), Counter()
    for r in rows:
        m = r["meta"]
        if not m.get("traj"):
            rep["no_traj"] += 1                                # rows from converters without a trajectory id group by task alone
        groups[(m["task"], m.get("traj") or m["task"], m.get("stage"))].append(r)
    seqs, held = [], []
    per_ts = defaultdict(list)
    for (task, traj, stage), rs in groups.items():
        for text, calls, breaks, healed, compactions in stitch_group(rs):
            rep["breaks"] += breaks; rep["healed"] += healed; rep["compactions"] += compactions
            spans = supervised_char_spans(text)
            if not spans:
                rep["no_spans"] += 1
                continue
            weighted, srep = weight_spans(text, spans, read_share=read_share, seed=seed + len(seqs) + len(held))
            n_tok = count_tokens(text, tok)
            item = {"text": text, "spans": [[a, b, w] for a, b, w in weighted],
                    "meta": {"task": task, "traj": traj, "stage": stage, "calls": calls, "tokens": n_tok, "breaks": breaks, "healed": healed, "spans": srep}}
            if n_tok > max_tokens:
                rep["over_max_tokens"] += 1
                continue
            if task in holdout:
                held.append(item)
            else:
                per_ts[(task, stage)].append(item)
    for key, items in per_ts.items():
        items.sort(key=lambda it: (it["meta"]["calls"], it["meta"]["tokens"]))     # fewest calls first
        keep, drop = items[:max_per_task_stage], items[max_per_task_stage:]
        rep["capped_per_task_stage"] += len(drop)
        seqs.extend(keep)
    for s in seqs + held:
        for k, v in s["meta"]["spans"].items():
            rep["span_" + k] += v
        rep["supervised_chars"] += sum(b - a for a, b, w in s["spans"] if w > 0)
        rep["masked_chars"] += sum(b - a for a, b, w in s["spans"] if w == 0)
    rep = dict(rep)                                       # a Counter.update would try to add the strings below
    rep.update({"groups": len(groups), "sequences": len(seqs), "holdout_sequences": len(held),
                "tokens": sum(s["meta"]["tokens"] for s in seqs), "holdout_tokens": sum(s["meta"]["tokens"] for s in held),
                "tasks": len({s["meta"]["task"] for s in seqs}), "tokenizer": "given" if tok is not None else f"estimate {CHARS_PER_TOKEN} chars/token"})
    return seqs, held, rep


def load_tokenizer(path):
    if not path:
        return None
    from tokenizers import Tokenizer
    return Tokenizer.from_file(str(path))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("rows"); ap.add_argument("--out", required=True); ap.add_argument("--report", required=True)
    ap.add_argument("--max-seqs-per-task-stage", type=int, default=10); ap.add_argument("--max-tokens", type=int, default=14336)
    ap.add_argument("--tokenizer-json", default=None); ap.add_argument("--read-share", type=float, default=0.15); ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--holdout-tasks", default=None); ap.add_argument("--holdout-out", default=None)
    ap.add_argument("--holdout-auto", type=int, default=0, help="when the holdout file names no task of these rows, draw this many tasks (seeded) and write them to <out>.holdout_tasks.txt")
    a = ap.parse_args(argv)
    rows = [json.loads(l) for l in open(a.rows) if l.strip()]
    hold = {l.strip() for l in open(a.holdout_tasks) if l.strip()} if a.holdout_tasks else set()
    present = {r["meta"]["task"] for r in rows}
    if a.holdout_auto and not (hold & present):
        hold = auto_holdout(rows, a.holdout_auto, a.seed)
        Path(a.out + ".holdout_tasks.txt").write_text("".join(t + "\n" for t in sorted(hold)))
        print(f"holdout: none of the named tasks are in these rows; drew {sorted(hold)} -> {a.out}.holdout_tasks.txt")
    seqs, held, rep = stitch(rows, a.max_seqs_per_task_stage, a.max_tokens, load_tokenizer(a.tokenizer_json), a.read_share, a.seed, hold)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w") as f:
        for s in seqs:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    if a.holdout_out:
        with open(a.holdout_out, "w") as f:
            for s in held:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
    Path(a.report).parent.mkdir(parents=True, exist_ok=True)
    Path(a.report).write_text(json.dumps(rep, indent=1, sort_keys=True))
    print(json.dumps(rep, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
