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
