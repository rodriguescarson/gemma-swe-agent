"""train/scorer_render.py: the scorer's exact prompt bytes (P0.2). Facts from docs/v11/facts_internal.md 2.4 and 3.3."""
import json, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from train import scorer_render as R  # noqa: E402

BODIES = json.load(open(ROOT / "docs" / "v11" / "evidence" / "bodies_a.json"))


def test_template_is_the_june_scorer_template():
    assert R.template_sha256().startswith("94899c0f") and R.TEMPLATE_PATH.stat().st_size == 16934


def test_system_turn_gets_the_trailing_space_and_prompt_starts_with_bos():
    body = {"messages": [{"role": "system", "content": "SYS"}, {"role": "user", "content": "hi"}],
            "tools": BODIES[0]["body"]["tools"][:1], "chat_template_kwargs": {"enable_thinking": False}}
    s = R.render(body)
    assert s.startswith("<bos>") and "SYS <|tool>" in s, s[:200]       # trim(system) + ' ' before the first <|tool>


def test_every_captured_body_renders_and_is_a_prefix_chain_within_a_stage():
    by_agent = {}
    for e in BODIES:
        s = R.render(e["body"])
        assert s.startswith("<bos>")
        by_agent.setdefault(e["agent"], []).append((int(e["index"]), s))
    for agent, lst in by_agent.items():
        lst.sort()
        for (i, a), (j, b) in zip(lst, lst[1:]):
            if j == i + 1:
                stem = a[:a.rindex("<|turn>")] if "<|turn>" in a else a
                assert b.startswith(stem), (agent, i, j)                 # continuation = previous prompt + increment


def test_canonical_tool_call_and_completion_forms():
    tcs = [{"id": "x", "type": "function", "function": {"name": "read_file", "arguments": json.dumps({"filepath": "a.py", "start_line": 1, "end_line": 5})}}]
    c = R.canonical_tool_calls(tcs)
    assert c.startswith("<|tool_call>call:read_file{") and c.endswith("<tool_call|>")
    assert c.index("end_line") < c.index("filepath") < c.index("start_line")   # dictsort: keys in sorted order
    assert '<|"|>a.py<|"|>' in c                                             # strings wrapped, not escaped
    msg = {"tool_calls": tcs}
    assert R.canonical_completion(msg, continuation=False) == c + "<|tool_response>"
    assert R.canonical_completion(msg, continuation=True) == "<|channel>thought\n<channel|>" + c + "<|tool_response>"
    assert R.canonical_completion({"content": "Done."}, continuation=True) == "<|channel>thought\n<channel|>Done.<turn|>"


def _tokenizer():
    try:
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer
        return Tokenizer.from_file(hf_hub_download("google/gemma-4-31b-it-qat-w4a16-ct", "tokenizer.json"))
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"tokenizer unavailable: {e!r}")


def test_increments_match_recorded_prompt_token_deltas_on_kaggle_l4_traces(tmp_path):
    """facts_internal 2.4: rendered increment == recorded prompt_tokens delta (2,391/2,391 on e74_v3); first calls after
    a compaction are exactly -4 (generation-prompt rule). Re-checked 2026-10-02 on g4-l4-v4: 2,641 exact + 253 at -4 of
    2,940 pairs, the remainder compaction drops. bodies_a.json is a POD capture (July template), so absolute counts
    cannot be compared; only increments can."""
    import tarfile
    tok = _tokenizer()
    tgz = ROOT / "eval" / "kaggle" / "g4-l4-v4" / "traces.tar.gz"
    if not tgz.exists():
        pytest.skip("no L4 traces")
    with tarfile.open(tgz) as t:
        members = [m for m in t.getmembers() if m.name.endswith(".json")][:4]
        t.extractall(tmp_path, members=members)
    exact = minus4 = compaction = other = 0
    for f in tmp_path.rglob("trace_*.json"):
        steps = [s for s in json.load(open(f))["steps"] if s.get("source") == "agent" and s.get("tool_calls") and s.get("observation")]
        prev = None
        for s in steps:
            author = (s.get("extra") or {}).get("author")
            if len(s["tool_calls"]) != 1:
                prev = None; continue
            tc = s["tool_calls"][0]; obs = s["observation"]["content"]
            # the model-visible tool text (recon.py model_visible): swegemma's string tools return a JSON string that ADK
            # wraps as {"result": <string>} (double encoding); everything else is the parsed JSON re-serialised once
            STR_TOOLS = {"run_command", "read_file", "write_file", "edit_file", "submit_patch", "get_status",
                         "get_code_neighbors", "search_similar_code", "get_code_subgraph"}
            try:
                parsed = json.loads(obs)
            except Exception:
                prev = None; continue
            if tc["function_name"] in STR_TOOLS and isinstance(parsed, dict) and "status" in parsed:
                visible = json.dumps({"result": obs}, ensure_ascii=False)
            else:
                visible = json.dumps(parsed, ensure_ascii=False)
            cur = (author, tc, visible, (s.get("metrics") or {}).get("prompt_tokens"))
            if prev and prev[0] == author and prev[3] and cur[3]:
                def conv(items):
                    msgs = [{"role": "user", "content": "x"}]
                    for j, (_, c, v, _) in enumerate(items):
                        msgs.append({"role": "assistant", "content": "", "tool_calls": [{"id": f"c{j}", "type": "function",
                                     "function": {"name": c["function_name"], "arguments": json.dumps(c.get("arguments") or {})}}]})
                        msgs.append({"role": "tool", "tool_call_id": f"c{j}", "content": v})
                    return msgs
                # recon.py: the tokens added between call i and call i+1 are call i's canonical call + its tool response,
                # rendered mid-turn (after a dummy first call so no turn header is counted)
                dummy = ("_", {"function_name": "_", "arguments": {}}, "_", None)
                a = R.render({"messages": conv([dummy])}, add_generation_prompt=False)
                b = R.render({"messages": conv([dummy, prev])}, add_generation_prompt=False)
                assert b.startswith(a)
                inc = len(tok.encode(b[len(a):], add_special_tokens=False).ids)
                d = (cur[3] - prev[3]) - inc
                if d == 0: exact += 1
                elif d == -4: minus4 += 1
                elif d < -1000: compaction += 1
                else: other += 1
            prev = cur
    assert exact >= 60 and other == 0, (exact, minus4, compaction, other)
