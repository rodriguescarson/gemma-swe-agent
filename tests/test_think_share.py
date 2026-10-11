"""scripts/a6000/think_share.py: the P10 thinking gate (GAPS "P10 pre-registration" (a): non-empty reasoning on >= 80 % of model calls)
measured on pace-proxy captures {t, body, response}; vLLM 0.19 puts the thought under message.reasoning, older stacks under
reasoning_content, and the harness carries earlier thoughts back as reasoning_content in the request. Plus the proxy-log mode
(rows {latency_s, prompt, completion}) for the thinking signature before any capture exists. Written before the script (2026-10-11)."""
import importlib.util, json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("think_share", ROOT / "scripts" / "a6000" / "think_share.py")
ts = importlib.util.module_from_spec(spec); spec.loader.exec_module(ts)


def cap(reason_key=None, reason="", carried=(), completion=50):
    msg = {"role": "assistant", "content": "", "tool_calls": [{"id": "c", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]}
    if reason_key:
        msg[reason_key] = reason
    body_msgs = [{"role": "user", "content": "fix"}] + [{"role": "assistant", "content": "x", "reasoning_content": r} for r in carried]
    return {"t": 1.0, "body": {"messages": body_msgs}, "response": {"choices": [{"message": msg}], "usage": {"completion_tokens": completion}}}


def test_capture_summary_counts_both_keys_and_carried_thoughts():
    rows = [cap("reasoning", "think " * 40, carried=("a", ""), completion=300), cap("reasoning_content", "t2", carried=("b",), completion=120),
            cap(None, completion=20), cap("reasoning", "", completion=30)]
    s = ts.summarize_captures(rows)
    assert s["calls"] == 4 and s["with_reasoning"] == 2 and abs(s["share"] - 0.5) < 1e-9
    assert s["keys"] == {"reasoning": 1, "reasoning_content": 1}                 # an empty reasoning counts as none
    assert s["reasoning_chars"]["median"] > 0 and s["completion_tokens"]["mean"] == 117.5
    assert s["carried"] == {"assistant_msgs": 3, "with_reasoning": 2}


def test_gate_exit_codes_and_proxy_mode(tmp_path):
    good = tmp_path / "capture_s1.jsonl"; good.write_text("".join(json.dumps(cap("reasoning", "r")) + "\n" for _ in range(9)) + json.dumps(cap(None)) + "\n")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "a6000" / "think_share.py"), str(good), "--min-share", "0.8"], capture_output=True, text=True)
    assert r.returncode == 0 and "GATE PASS" in r.stdout and "share 0.90" in r.stdout, r.stdout + r.stderr
    bad = tmp_path / "capture_s2.jsonl"; bad.write_text("".join(json.dumps(cap(None)) + "\n" for _ in range(5)))
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "a6000" / "think_share.py"), str(bad), "--min-share", "0.8"], capture_output=True, text=True)
    assert r.returncode == 3 and "GATE FAIL" in r.stdout
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "a6000" / "think_share.py"), str(tmp_path), "--min-share", "0.8"], capture_output=True, text=True)
    assert "calls 15" in r.stdout and r.returncode == 3                           # a directory = every capture*.jsonl in it
    plog = tmp_path / "proxy.jsonl"
    plog.write_text("".join(json.dumps({"status": 200, "latency_s": 9.1, "prompt": 7000, "completion": c, "t": 1}) + "\n" for c in (260, 300, 90, 400)) +
                    json.dumps({"status": 500, "err": "x", "t": 2}) + "\n")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "a6000" / "think_share.py"), str(plog), "--proxy-log"], capture_output=True, text=True)
    assert r.returncode == 0 and "calls 4" in r.stdout and "ON-like" in r.stdout, r.stdout
    assert ts.proxy_signature({"mean": 50}) == "OFF-like" and ts.proxy_signature({"mean": 120}) == "unclear"


# --- render mode: the thought must land in the TRAINING ROWS, and consecutive rows must chain (2026-10-11, gate (a) extended) ---
SYSF = 'You are fixer. Your internal name is "fixer".'
STMT = "Issue t_ok: " + "words " * 50 + "t_ok"
TOOLS = [{"type": "function", "function": {"name": "read_file", "description": "r", "parameters": {"type": "object", "properties": {"filepath": {"type": "string"}}}}}]
CALL = {"id": "c0", "type": "function", "function": {"name": "read_file", "arguments": json.dumps({"filepath": "a.py"})}}
R1, R2 = "The issue names a.py, so I read it first.", "Line 2 holds the bug; I state the fix."


def v019_body(messages, thinking=True, budget=4096):
    """What the scorer harness sends (adk_submission bridges thinking_config into extra_body, the SDK merges it top-level)."""
    b = {"model": "m", "messages": messages, "tools": TOOLS, "chat_template_kwargs": {"enable_thinking": thinking}}
    if thinking:
        b["thinking_token_budget"] = budget
    return b


def v019_reply(reasoning, tool_call=None, text=None):
    msg = {"role": "assistant", "content": text, "reasoning": reasoning}            # vLLM 0.19: `reasoning`, no reasoning_content
    if tool_call:
        msg["tool_calls"] = [tool_call]
    return {"choices": [{"message": msg, "finish_reason": "stop"}], "usage": {"prompt_tokens": 10, "completion_tokens": 300}}


def trajectory(carry=True, reason=True, thinking=True):
    base = [{"role": "system", "content": SYSF}, {"role": "user", "content": "Problem Statement:\n" + STMT}]
    carried = {"role": "assistant", "content": "", "tool_calls": [CALL]}
    if carry and reason:
        carried.update(reasoning_content=R1, reasoning=R1)                        # the harness mirrors reasoning_content -> reasoning
    hist = base + [carried, {"role": "tool", "tool_call_id": "c0", "content": json.dumps({"status": "ok", "content": "SECRET_TOOL_OUTPUT"})}]
    return [{"t": 1, "body": v019_body(base, thinking), "response": v019_reply(R1 if reason else "", CALL)},
            {"t": 2, "body": v019_body(hist, thinking), "response": v019_reply(R2 if reason else "", text="Fixed.")}]


def test_render_check_passes_when_thoughts_land_in_rows_and_the_chain_is_exact():
    s = ts.render_check(trajectory())
    assert s["calls"] == 2 and s["thinking_on"] == 2 and s["budgets"] == {"4096": 2}
    assert s["with_thought"] == 2 and s["thought_share"] == 1.0 and s["thought_chars_share"] > 0.3
    assert s["groups"] == 1 and s["sequences"] == 1 and s["pairs"] == 1 and s["exact"] == 1 and s["healed"] == 0 and s["breaks"] == 0
    assert s["model_spans"] == 2 and s["spans_with_thought"] == 2 and s["span_thought_share"] == 1.0
    assert s["completions"][0].startswith("<|channel>thought\n" + R1 + "\n<channel|><|tool_call>call:read_file{")
    assert ts.render_verdict(s, 0.8, 0.02) == "RENDER GATE PASS"


def test_render_check_fails_when_the_harness_strips_the_carried_thoughts_or_the_model_reasons_nothing():
    stripped = ts.render_check(trajectory(carry=False))               # include_thoughts false: the next prompt lacks the thought
    assert stripped["thought_share"] == 1.0 and stripped["exact"] == 0 and stripped["healed"] == 1 and stripped["breaks"] == 0
    assert ts.render_verdict(stripped, 0.8, 0.02) == "RENDER GATE FAIL"   # healed is not exact: the model never saw those thoughts
    silent = ts.render_check(trajectory(reason=False))                 # thinking on, no reasoning: empty channels, exact chain
    assert silent["with_thought"] == 0 and silent["spans_with_thought"] == 0 and silent["healed"] == 1 and silent["exact"] == 0   # the empty channel is dropped by the harness
    assert ts.render_verdict(silent, 0.8, 0.02) == "RENDER GATE FAIL"
    off = ts.render_check(trajectory(thinking=False, reason=False))
    assert off["thinking_on"] == 0 and off["thinking_off"] == 2 and ts.render_verdict(off, 0.8, 0.02) == "RENDER GATE FAIL"


def test_render_mode_cli_prints_both_gate_lines_and_writes_both_summaries(tmp_path):
    cap_f = tmp_path / "capture_s1.jsonl"
    cap_f.write_text("".join(json.dumps(r) + "\n" for r in trajectory()))
    out = tmp_path / "gate.json"
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "a6000" / "think_share.py"), str(tmp_path), "--min-share", "0.8", "--render", "--json", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "GATE PASS: calls 2" in r.stdout and "RENDER GATE PASS" in r.stdout and "exact 1" in r.stdout and "keys {'reasoning': 2}" in r.stdout
    j = json.loads(out.read_text())
    assert j["share"] == 1.0 and j["render"]["exact"] == 1 and "completions" not in j["render"]      # the JSON carries numbers, not texts
    bad = tmp_path / "capture_s2.jsonl"
    bad.write_text("".join(json.dumps(r) + "\n" for r in trajectory(carry=False)))
    r2 = subprocess.run([sys.executable, str(ROOT / "scripts" / "a6000" / "think_share.py"), str(bad), "--render"], capture_output=True, text=True)
    assert r2.returncode == 3 and "GATE PASS" in r2.stdout and "RENDER GATE FAIL" in r2.stdout, r2.stdout + r2.stderr
