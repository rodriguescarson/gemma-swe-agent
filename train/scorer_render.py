"""Render an OpenAI chat-completions request body byte for byte as the scorer's vLLM 0.19.1 does for the Kaggle Gemma 4
model (model v2, June 2026 chat template). This is docs/v11/evidence/render.py promoted to a library (P0.2).

Verified facts it encodes (docs/v11/facts_internal.md 2.4, 3.3): content format 'openai' (string contents wrapped as
text parts, so the system turn renders as trim(system) + ' '), tool-call arguments json.loads-ed back into dicts, keys
sorted by the template, strings wrapped as <|"|>...<|"|> unescaped, tool results matched by id and rendered inline in
the model turn, add_generation_prompt on. The rendered increment between consecutive calls matched the recorded
prompt_tokens delta in 2,391 of 2,391 pairs on the Kaggle e74_v3 run.

The wheelhouse of 2026-09-30 (adk_submission 0.2.12, google_adk 1.36.1, swegemma 0.2.7) changes none of this: its
patches are the reasoning_content mirror, the seed bridge and an any_of schema flattening (checked by diff 2026-10-02).

    from train.scorer_render import render, canonical_completion
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

from transformers.utils.chat_template_utils import _compile_jinja_template

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "docs" / "v11" / "evidence" / "chat_template_kaggle_v2_june.jinja"
TEMPLATE = TEMPLATE_PATH.read_text()
_T = _compile_jinja_template(TEMPLATE)
TOOL_CALL_OPEN, TOOL_CALL_CLOSE = "<|tool_call>", "<tool_call|>"
TOOL_RESPONSE_OPEN = "<|tool_response>"          # the stop token after a tool call (recon.py: completion = call + 1)
END_OF_TURN = "<turn|>"
EMPTY_THOUGHT = "<|channel>thought\n<channel|>"  # the empty thought channel the model emits itself (facts 3.3)


def to_vllm_conversation(messages):
    conv = []
    for m in messages:
        m = copy.deepcopy(m)
        c = m.get("content")
        if c is None:
            c = []
        elif isinstance(c, str):
            c = [{"type": "text", "text": c}]
        else:
            c = [{"type": "text", "text": p["text"]} if isinstance(p, dict) and p.get("type") == "text" else p for p in c]
        out = {"role": m["role"], "content": c}
        if m["role"] == "assistant" and m.get("tool_calls"):
            tcs = []
            for tc in m["tool_calls"]:
                tc = copy.deepcopy(tc)
                a = tc["function"].get("arguments")
                tc["function"]["arguments"] = json.loads(a) if a and not isinstance(a, (dict, list)) else (a or {})
                tcs.append(tc)
            out["tool_calls"] = tcs
        if m["role"] == "tool" and "tool_call_id" in m:
            out["tool_call_id"] = m["tool_call_id"]
        if isinstance(m.get("name"), str):
            out["name"] = m["name"]
        conv.append(out)
    return conv


def render(body, add_generation_prompt=True):
    """The exact prompt string vLLM builds for this request body (<bos> included)."""
    kw = dict(body.get("chat_template_kwargs") or {})
    return _T.render(messages=to_vllm_conversation(body["messages"]), tools=body.get("tools"),
                     add_generation_prompt=add_generation_prompt, bos_token="<bos>", **kw)


def canonical_tool_calls(tool_calls):
    """The template's own rendering of these tool calls: <|tool_call>call:NAME{k:v,...}<tool_call|> for each."""
    msgs = [{"role": "user", "content": "x"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": f"c{i}", "type": "function", "function": tc["function"]}
                                                                 for i, tc in enumerate(tool_calls)]}]
    a = render({"messages": msgs[:1]}, add_generation_prompt=False)
    b = render({"messages": msgs}, add_generation_prompt=False)
    s = b[len(a):]
    return s[s.index(TOOL_CALL_OPEN):s.rindex(TOOL_CALL_CLOSE) + len(TOOL_CALL_CLOSE)]


def canonical_completion(message, continuation: bool):
    """What the model's raw output is for this reply (facts 3.3): the canonical re-render of its tool calls followed by
    the <|tool_response> stop token, or its text followed by end-of-turn; continuation calls carry the empty thought
    channel in front (94.5% of calls match this exactly on e74_v3)."""
    head = EMPTY_THOUGHT if continuation else ""
    if message.get("tool_calls"):
        return head + canonical_tool_calls(message["tool_calls"]) + TOOL_RESPONSE_OPEN
    return head + (message.get("content") or "") + END_OF_TURN


def template_sha256():
    import hashlib
    return hashlib.sha256(TEMPLATE_PATH.read_bytes()).hexdigest()


if __name__ == "__main__":
    import sys
    L = json.load(open(sys.argv[1]))
    print(render(L[int(sys.argv[2])]["body"]))
