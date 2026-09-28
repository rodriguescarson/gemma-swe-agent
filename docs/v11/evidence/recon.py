"""Check whether training conversations can be reconstructed byte-exactly from SessionTrace (ATIF) files.
For consecutive tool-call steps of the same stage, render the increment (canonical tool call + tool response block)
with the scorer's June template, tokenize with the Gemma 4 tokenizer, and compare with the recorded
delta of usage.prompt_tokens. Also compare tokens(canonical call)+1 (stop token <|tool_response>) with
usage.completion_tokens. Usage: python recon.py OUT.json TRACE_DIR [TRACE_DIR ...]"""
import glob, json, sys
from tokenizers import Tokenizer
from transformers.utils.chat_template_utils import _compile_jinja_template
T = _compile_jinja_template(open(__file__.rsplit("/", 1)[0] + "/chat_template_kaggle_v2_june.jinja").read())
TOK = Tokenizer.from_file(__import__("os").environ.get("GEMMA4_TOKENIZER", "tokenizer.json"))
STR_TOOLS = {"run_command", "read_file", "write_file", "edit_file", "submit_patch", "get_status",
             "get_code_neighbors", "search_similar_code", "get_code_subgraph"}

def ntok(s):
    return len(TOK.encode(s, add_special_tokens=False).ids)

def model_visible(tool, obs):
    try:
        parsed = json.loads(obs)
    except Exception:
        return None
    if tool in STR_TOOLS and isinstance(parsed, dict) and "status" in parsed:
        return json.dumps({"result": obs}, ensure_ascii=False)
    return json.dumps(parsed, ensure_ascii=False)

def conv(calls_and_obs):
    msgs = [{"role": "user", "content": [{"type": "text", "text": "x"}]}]
    for j, (calls, obs_list) in enumerate(calls_and_obs):
        tcs = [{"id": f"c{j}_{i}", "type": "function", "function": {"name": n, "arguments": a}} for i, (n, a) in enumerate(calls)]
        msgs.append({"role": "assistant", "content": [], "tool_calls": tcs})
        for i, o in enumerate(obs_list):
            msgs.append({"role": "tool", "tool_call_id": f"c{j}_{i}", "content": [{"type": "text", "text": o}]})
    return msgs

def render(msgs):
    return T.render(messages=msgs, tools=None, add_generation_prompt=False, bos_token="<bos>", enable_thinking=False)

def increment(prev, cur):
    a = render(conv([prev]))
    b = render(conv([prev, cur]))
    assert b.startswith(a)
    return b[len(a):]

def call_text(calls):
    a = render(conv([]))
    b = render(conv([(calls, [])]))
    s = b[len(a):]
    return s[s.index("<|tool_call>"):s.rindex("<tool_call|>") + len("<tool_call|>")]

def steps_of(trace):
    out = []
    for s in trace["steps"]:
        ex = s.get("extra") or {}
        if s.get("source") == "agent" and s.get("tool_calls"):
            obs = s.get("observation")
            out.append({"kind": "call", "author": ex.get("author"), "calls": [(tc["function_name"], tc.get("arguments") or {}) for tc in s["tool_calls"]],
                        "obs": obs["content"] if obs else None, "obs_tool": (obs or {}).get("extra", {}).get("tool_name"),
                        "pt": (s.get("metrics") or {}).get("prompt_tokens"), "ct": (s.get("metrics") or {}).get("completion_tokens")})
        else:
            out.append({"kind": ex.get("event_type") or s.get("source"), "author": ex.get("author")})
    return out

res = {"pairs": 0, "delta_exact": 0, "delta_absdiff": [], "calls": 0, "ct_exact": 0, "ct_diff": [], "skipped_obs": 0, "multi": 0}
examples = []
for d in sys.argv[2:]:
    for f in sorted(glob.glob(d + "/trace_*.json")):
        st = steps_of(json.load(open(f)))
        for i, s in enumerate(st):
            if s["kind"] != "call" or s["obs"] is None:
                continue
            if len(s["calls"]) > 1:
                res["multi"] += 1
                continue
            res["calls"] += 1
            ct = s["ct"]
            if ct is not None:
                c = ntok(call_text(s["calls"])) + 1
                res["ct_diff"].append(ct - c)
                res["ct_exact"] += int(ct == c)
            if i + 1 < len(st):
                n = st[i + 1]
                if n["kind"] == "call" and n["author"] == s["author"] and n["pt"] and s["pt"]:
                    mv = model_visible(s["obs_tool"] or s["calls"][0][0], s["obs"])
                    if mv is None:
                        res["skipped_obs"] += 1
                        continue
                    inc = increment(([("_", {})], ["_"]), (s["calls"], [mv]))
                    got = ntok(inc)
                    dl = n["pt"] - s["pt"]
                    res["pairs"] += 1
                    res["delta_exact"] += int(dl == got)
                    res["delta_absdiff"].append(dl - got)
                    if dl != got and len(examples) < 12:
                        examples.append({"file": f, "step": i, "tool": s["calls"][0][0], "delta": dl, "rendered": got})
import collections
out = {k: v for k, v in res.items() if not isinstance(v, list)}
out["delta_diff_hist"] = collections.Counter(res["delta_absdiff"]).most_common(12)
out["ct_diff_hist"] = collections.Counter(res["ct_diff"]).most_common(12)
out["examples"] = examples
json.dump(out, open(sys.argv[1], "w"), indent=1)
print(json.dumps(out, indent=1)[:3000])
