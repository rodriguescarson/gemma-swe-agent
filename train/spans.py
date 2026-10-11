"""Supervised spans of a rendered Gemma 4 chat text, and their weights for training (plan ~/.claude/plans/nifty-sleeping-liskov.md,
"Training step design"). Shared by train/sft.py (unchanged behaviour) and train/stitch_rows.py / train/qlora_train.py.

A span is a char range [a, b) of text the model itself produced: inside each `<|turn>model\\n ... <turn|>` turn, minus the inline
`<|tool_response> ... <tool_response|>` blocks, keeping the `<|tool_response>` stop token the model emits to hand over and the
closing `<turn|>` (the model must learn to stop). Gemma 4 merges consecutive assistant messages into one model turn, so
prefix-diff masking fails and span masking on the final text is the way (tests/test_sft_masking.py).

Span kinds and the weight rules (the row-level lessons of v11a/v11b, now per span inside one stitched sequence):
  text spans (a reply with no tool call)            weight 1, never masked: the final plan / notes / answer carry the decision to stop
  a tool-call span identical to an earlier one      weight 0 (the v11a read loop: 50 exact repeats in one trajectory)
  a tool-call span whose tool response is an error  weight 0 (do not learn calls the harness rejected)
  read_file calls over READ_SHARE of the tool spans weight 0, chosen with a seeded RNG (v11b: 24 % read_file -> a reader)
  everything else                                   weight 1
The thought channel (`<|channel>thought ... <channel|>`) sits inside the span and is trained with it: that is the signal the
thinking-on trajectories add."""
import json
import random
import re

MODEL_OPEN, TURN_CLOSE = "<|turn>model\n", "<turn|>"
TR_OPEN, TR_CLOSE = "<|tool_response>", "<tool_response|>"
TC_OPEN, TC_CLOSE = "<|tool_call>", "<tool_call|>"
EMPTY_THOUGHT = "<|channel>thought\n<channel|>"
READ_SHARE = 0.15
CALL_RE = re.compile(r"<\|tool_call>call:([A-Za-z_][\w.-]*)\{")
ERROR_RE = re.compile(r'"status"\s*:\s*"error"|"error_type"\s*:|"error"\s*:\s*"[^"]|\bError\b.*not found|Traceback \(most recent', re.S)


def supervised_char_spans(text):
    """Char spans the model itself produced: inside each model turn, minus inline tool-response blocks."""
    spans, pos = [], 0
    while True:
        s = text.find(MODEL_OPEN, pos)
        if s < 0:
            break
        s += len(MODEL_OPEN)
        e = text.find(TURN_CLOSE, s)
        e = len(text) if e < 0 else e + len(TURN_CLOSE)       # train on the turn-close token too (the model must stop)
        cur = s
        while True:
            t = text.find(TR_OPEN, cur, e)
            if t < 0:
                spans.append((cur, e))
                break
            spans.append((cur, t + len(TR_OPEN)))              # the model emits <|tool_response> to hand over, then waits
            c = text.find(TR_CLOSE, t, e)
            if c < 0:
                break
            cur = c + len(TR_CLOSE)
        pos = e
    return [(a, b) for a, b in spans if b > a]


def describe_span(text, a, b):
    """-> {"kind": "text"|"tool", "tool": name|None, "call": the call text or None, "error": bool, "thought": bool}."""
    seg = text[a:b]
    m = CALL_RE.search(seg)
    thought = seg.lstrip().startswith("<|channel>thought\n") and not seg.lstrip().startswith(EMPTY_THOUGHT)
    if not m:
        return {"kind": "text", "tool": None, "call": None, "error": False, "thought": thought}
    call = seg[m.start():seg.rfind(TC_CLOSE) + len(TC_CLOSE)] if TC_CLOSE in seg else seg[m.start():]
    resp_end = text.find(TR_CLOSE, b)
    resp = text[b:resp_end] if resp_end >= 0 else text[b:b + 2000]
    return {"kind": "tool", "tool": m.group(1), "call": call, "error": bool(ERROR_RE.search(resp[:4000])), "thought": thought}


def weight_spans(text, spans, read_share=READ_SHARE, seed=1, read_tool="read_file"):
    """-> ([(a, b, w), ...], report) applying the rules above to the spans of one sequence."""
    info = [describe_span(text, a, b) for a, b in spans]
    seen, w, rep = set(), [], {"text": 0, "tool": 0, "repeat": 0, "error": 0, "read_over_share": 0, "thought": 0, "thought_masked": 0}
    for d in info:
        rep[d["kind"]] += 1
        rep["thought"] += d["thought"]
        if d["kind"] == "text":
            w.append(1.0)
            continue
        if d["call"] in seen:
            rep["repeat"] += 1
            w.append(0.0)
            continue
        seen.add(d["call"])
        if d["error"]:
            rep["error"] += 1
            w.append(0.0)
            continue
        w.append(1.0)
    live_tools = [i for i, d in enumerate(info) if d["kind"] == "tool" and w[i] > 0]
    reads = [i for i in live_tools if info[i]["tool"] == read_tool]
    allowed = int(read_share * len(live_tools))
    if len(reads) > allowed:
        drop = random.Random(seed).sample(reads, len(reads) - allowed)
        for i in drop:
            w[i] = 0.0
        rep["read_over_share"] = len(drop)
    rep["thought_masked"] = sum(1 for i, d in enumerate(info) if d["thought"] and w[i] == 0)   # a masked call span masks its thought too (reported)
    return [(a, b, w[i]) for i, (a, b) in enumerate(spans)], rep


def span_report_json(rep):
    return json.dumps(rep, sort_keys=True)
