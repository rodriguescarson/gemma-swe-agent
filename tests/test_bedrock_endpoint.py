"""BedrockEndpoint (scripts/golden/router.py): the OpenAI <-> Bedrock converse translation behind or_proxy --upstream
bedrock, its retry and error paths, pricing for the budget cap, and that AWS keys never reach public()/repr/logs.
No network: a stub client stands in for boto3's bedrock-runtime."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "golden"))
import or_proxy  # noqa: E402
from router import (BEDROCK_PRICES, Budget, BedrockEndpoint, converse_to_openai, make_bedrock_endpoint,  # noqa: E402
                    openai_to_converse, sanitize_schema)


class ClientError(Exception):
    """botocore.exceptions.ClientError's shape: .response['Error']['Code']."""

    def __init__(self, code: str, msg: str = "boom"):
        super().__init__(f"An error occurred ({code}): {msg}")
        self.response = {"Error": {"Code": code, "Message": msg}}


class StubClient:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def converse(self, **kw):
        self.calls.append(kw)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def reply(blocks, stop="end_turn", p=100, c=20):
    return {"output": {"message": {"role": "assistant", "content": blocks}}, "stopReason": stop,
            "usage": {"inputTokens": p, "outputTokens": c, "totalTokens": p + c}}


HARNESS_BODY = {   # the shape a captured harness request has (eval/collect/*/capture_s*.jsonl)
    "model": "gemma-4-31b-it-qat-w4a16-ct", "max_completion_tokens": 4096, "temperature": 1.0, "top_p": 0.95,
    "top_k": 64.0, "chat_template_kwargs": {"enable_thinking": True}, "thinking_token_budget": 4096,
    "messages": [
        {"role": "system", "content": "You fix bugs."},
        {"role": "user", "content": "Issue: x breaks."},
        {"role": "assistant", "content": None, "reasoning_content": "look first",
         "tool_calls": [{"type": "function", "id": "call_a", "function": {"name": "run_command",
                                                                         "arguments": "{\"command\": \"ls\"}"}},
                        {"type": "function", "id": "call_b", "function": {"name": "read_file",
                                                                         "arguments": "{\"path\": \"a.py\"}"}}]},
        {"role": "tool", "tool_call_id": "call_a", "content": "a.py"},
        {"role": "tool", "tool_call_id": "call_b", "content": ""},
        {"role": "user", "content": [{"type": "text", "text": "Continue."}]},
    ],
    "tools": [{"type": "function", "function": {"name": "run_command", "description": "run",
                                                "parameters": {"type": "object", "properties": {
                                                    "command": {"type": "string"},
                                                    "timeout": {"type": "integer", "nullable": True, "default": 60},
                                                    "mode": {"any_of": [{"type": "string"}, {"type": "null"}]}},
                                                    "required": ["command"]}}}],
}


def test_request_translation_keeps_the_conversation_and_drops_vllm_fields():
    kw = openai_to_converse(HARNESS_BODY)
    assert kw["system"] == [{"text": "You fix bugs."}]
    roles = [m["role"] for m in kw["messages"]]
    assert roles == ["user", "assistant", "user"]                       # alternation, user first
    uses = [b["toolUse"] for b in kw["messages"][1]["content"]]
    assert [u["toolUseId"] for u in uses] == ["call_a", "call_b"] and uses[0]["input"] == {"command": "ls"}
    last = kw["messages"][2]["content"]                                  # both tool results + the user text, merged
    assert [list(b)[0] for b in last] == ["toolResult", "toolResult", "text"]
    assert last[1]["toolResult"]["content"] == [{"text": "(empty)"}]     # Converse rejects empty text
    assert kw["inferenceConfig"] == {"maxTokens": 4096, "temperature": 1.0, "topP": 0.95}
    flat = json.dumps(kw)
    for gone in ("chat_template_kwargs", "thinking_token_budget", "top_k", "reasoning_content", "look first"):
        assert gone not in flat


def test_tool_schema_is_sanitized_for_converse():
    spec = openai_to_converse(HARNESS_BODY)["toolConfig"]["tools"][0]["toolSpec"]
    schema = spec["inputSchema"]["json"]
    assert "nullable" not in json.dumps(schema) and "any_of" not in json.dumps(schema)
    assert schema["properties"]["mode"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
    assert schema["properties"]["timeout"]["default"] == 60 and spec["description"] == "run"
    assert sanitize_schema([{"nullable": False, "x": 1}]) == [{"x": 1}]


def test_tool_choice_mapping():
    body = dict(HARNESS_BODY, tool_choice="required")
    assert openai_to_converse(body)["toolConfig"]["toolChoice"] == {"any": {}}
    assert "toolConfig" not in openai_to_converse(dict(HARNESS_BODY, tool_choice="none"))


def test_assistant_first_or_empty_turns_stay_valid():
    kw = openai_to_converse({"messages": [{"role": "assistant", "content": ""}]})
    assert kw["messages"][0] == {"role": "user", "content": [{"text": "(start)"}]}
    assert kw["messages"][1]["content"] == [{"text": "(empty)"}]


def test_bad_tool_arguments_do_not_crash():
    body = {"messages": [{"role": "user", "content": "x"},
                         {"role": "assistant", "tool_calls": [{"id": "c", "function": {"name": "f", "arguments": "{bad"}}]}]}
    assert openai_to_converse(body)["messages"][1]["content"][0]["toolUse"]["input"] == {"_raw": "{bad"}


def test_reply_translation_text_tools_and_reasoning():
    r = reply([{"reasoningContent": {"reasoningText": {"text": "think"}}}, {"text": "I will list."},
               {"toolUse": {"toolUseId": "t1", "name": "run_command", "input": {"command": "ls"}}}], stop="tool_use")
    out = converse_to_openai(r, "qwen.x")
    msg, ch = out["choices"][0]["message"], out["choices"][0]
    assert ch["finish_reason"] == "tool_calls" and msg["content"] == "I will list."
    assert msg["reasoning_content"] == "think"
    assert msg["tool_calls"][0]["function"] == {"name": "run_command", "arguments": json.dumps({"command": "ls"})}
    assert out["usage"] == {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}


def test_inline_think_tags_are_split_out():
    out = converse_to_openai(reply([{"text": "<think>plan it</think>\nDone."}]), "minimax.x")
    msg = out["choices"][0]["message"]
    assert msg["content"] == "Done." and msg["reasoning_content"] == "plan it"


def test_finish_reasons():
    assert converse_to_openai(reply([{"text": "x"}], stop="max_tokens"), "m")["choices"][0]["finish_reason"] == "length"
    assert converse_to_openai(reply([{"text": "x"}]), "m")["choices"][0]["finish_reason"] == "stop"


def ep_with(replies, **kw):
    sleeps = []
    ep = BedrockEndpoint("bedrock", model="qwen.qwen3-coder-480b-a35b-v1:0", client=StubClient(replies),
                         price_in=0.45, price_out=1.80, **kw)
    ep.sleep = sleeps.append
    return ep, sleeps


def test_post_retries_throttling_then_succeeds():
    ep, sleeps = ep_with([ClientError("ThrottlingException"), reply([{"text": "ok"}])])
    status, resp, retries, err = ep.post(HARNESS_BODY)
    assert status == 200 and retries == 1 and err is None and sleeps == [5.0]
    assert resp["choices"][0]["message"]["content"] == "ok"
    assert ep.client.calls[-1]["modelId"] == "qwen.qwen3-coder-480b-a35b-v1:0"


def test_post_validation_error_is_not_retried():
    ep, sleeps = ep_with([ClientError("ValidationException", "bad schema")])
    status, resp, retries, err = ep.post(HARNESS_BODY)
    assert status == 400 and retries == 0 and sleeps == [] and "ValidationException" in err
    assert resp["error"]["type"] == "ValidationException"


def test_post_gives_up_after_retries():
    ep, sleeps = ep_with([ClientError("ThrottlingException")] * 3)
    ep.retries = 2
    status, _, retries, err = ep.post(HARNESS_BODY)
    assert status == 429 and retries == 2 and len(sleeps) == 2


def test_cost_and_budget_through_or_proxy_handle():
    ep, _ = ep_with([reply([{"text": "ok"}], p=1_000_000, c=100_000)])
    budget = Budget(5.0)
    status, resp, row = or_proxy.handle(ep, budget, dict(HARNESS_BODY))
    assert status == 200 and resp["model"] == "gemma-4-31b-it-qat-w4a16-ct"     # the harness's own name echoed back
    assert row["cost_usd"] == pytest.approx(0.45 + 0.18) and budget.spent == pytest.approx(0.63)
    assert ep.billed({"cost": 9.9}) is None


def test_budget_exhausted_refuses_before_calling():
    ep, _ = ep_with([])
    budget = Budget(1.0)
    budget.add(1.0)
    status, _, row = or_proxy.handle(ep, budget, dict(HARNESS_BODY))
    assert status == 500 and row["err"] == "budget" and ep.client.calls == []


def test_make_bedrock_endpoint_prices_and_keys(tmp_path, monkeypatch):
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_ACCESS_KEY", "AWS_SECRET_KEY"):
        monkeypatch.delenv(k, raising=False)
    env = tmp_path / ".env"
    env.write_text("AWS_ACCESS_KEY=AKIATESTKEY000000000\nAWS_SECRET_KEY='s3cr3t/value'\n")
    ep = make_bedrock_endpoint("moonshotai.kimi-k2.5", region="us-west-2", env_file=str(env))
    assert (ep.price_in, ep.price_out) == BEDROCK_PRICES["moonshotai.kimi-k2.5"] and ep.region == "us-west-2"
    shown = json.dumps(ep.public()) + repr(ep)
    assert "AKIATESTKEY" not in shown and "s3cr3t" not in shown and ep.public()["endpoint"] == "bedrock"
    with pytest.raises(ValueError, match="no list price"):
        make_bedrock_endpoint("zai.glm-5.3", env_file=str(env))
    assert make_bedrock_endpoint("zai.glm-5.3", env_file=str(env), price_in=1, price_out=2).price_out == 2.0
    with pytest.raises(ValueError, match="AWS_ACCESS_KEY"):
        make_bedrock_endpoint("moonshotai.kimi-k2.5", env_file=str(tmp_path / "missing.env"))
