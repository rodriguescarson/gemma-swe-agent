"""Render an OpenAI chat-completions request body the way vLLM 0.19.1 does for the scorer's Gemma 4 model
(Kaggle model v2, June chat template): content format 'openai' (detected), string contents wrapped as text parts,
tool-call arguments json.loads'ed (_postprocess_messages), chat_template_kwargs passed through, add_generation_prompt."""
import copy, json, sys
from transformers.utils.chat_template_utils import _compile_jinja_template
TEMPLATE = open(__file__.rsplit("/", 1)[0] + "/chat_template_kaggle_v2_june.jinja").read()
_T = _compile_jinja_template(TEMPLATE)

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
    kw = dict(body.get("chat_template_kwargs") or {})
    return _T.render(messages=to_vllm_conversation(body["messages"]), tools=body.get("tools"),
                     add_generation_prompt=add_generation_prompt, bos_token="<bos>", **kw)

if __name__ == "__main__":
    L = json.load(open(sys.argv[1]))
    idx = int(sys.argv[2])
    print(render(L[idx]["body"]))
