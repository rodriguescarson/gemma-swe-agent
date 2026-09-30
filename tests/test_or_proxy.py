"""or_proxy: the pin and model rewrite reach upstream, the budget refuses loudly, streaming is refused, cost is billed."""
import json, sys, threading, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "golden"))
import or_proxy  # noqa: E402
from router import Budget, make_endpoint  # noqa: E402


def fake_ep(reply=None, status=200):
    ep = make_endpoint("openrouter", key="k")
    sent = []
    def post(body):
        sent.append(body)
        return status, (json.loads(json.dumps(reply)) if reply is not None else None), 0, None if reply else "boom"
    ep.post = post
    return ep, sent


REPLY = {"model": "google/gemma-4-31b-it", "choices": [{"message": {"content": "hi"}}],
         "usage": {"prompt_tokens": 1000, "completion_tokens": 100, "cost": 0.0123}}


def test_forwards_with_pin_and_rewritten_model_and_echoes_harness_model():
    ep, sent = fake_ep(REPLY)
    status, resp, row = or_proxy.handle(ep, Budget(1.0), {"model": "gemma-4-31b-it-qat-w4a16-ct", "messages": []})
    assert status == 200 and sent[0]["model"] == "google/gemma-4-31b-it"
    assert sent[0]["provider"] == {"order": ["crusoe/bf16"], "allow_fallbacks": False}
    assert resp["model"] == "gemma-4-31b-it-qat-w4a16-ct"
    assert row["cost_usd"] == 0.0123 and row["spent_usd"] == 0.0123


def test_budget_exhausted_refuses_without_calling_upstream():
    ep, sent = fake_ep(REPLY)
    b = Budget(0.02); b.add(0.02)
    status, resp, row = or_proxy.handle(ep, b, {"messages": []})
    assert status == 500 and "budget" in resp["error"]["message"] and not sent


def test_stream_refused_and_upstream_failure_is_an_error_body():
    ep, sent = fake_ep(REPLY)
    assert or_proxy.handle(ep, Budget(1.0), {"stream": True})[0] == 400 and not sent
    ep2, _ = fake_ep(None, status=599)
    status, resp, row = or_proxy.handle(ep2, Budget(1.0), {"messages": []})
    assert status == 599 and "error" in resp and row["cost_usd"] == 0


def test_http_round_trip_logs_one_row(tmp_path):
    ep, _ = fake_ep(REPLY)
    log = tmp_path / "p.jsonl"
    srv = or_proxy.serve(0, ep, Budget(1.0), log, host="127.0.0.1")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", data=json.dumps({"messages": []}).encode(),
                                 headers={"Content-Type": "application/json"})
    out = json.load(urllib.request.urlopen(req))
    srv.shutdown()
    assert out["choices"][0]["message"]["content"] == "hi"
    rows = [json.loads(l) for l in log.read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["status"] == 200


def test_l4_pacing_sleeps_to_modelled_time_and_uses_prefix_cache():
    from router import l4_model_s
    ep, _ = fake_ep(REPLY)          # prompt 1000, completion 100
    slept = []
    pacer = or_proxy.Pacer()
    body = {"messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]}
    _, _, row = or_proxy.handle(ep, Budget(1.0), body, pacer, sleep=slept.append)
    assert abs(row["l4_target_s"] - round(l4_model_s(100, 1000), 3)) < 1e-9 and slept and slept[0] > 0
    # the same conversation again at the same prompt size: uncached = max(0, 1000 - 1000 - 100) = 0
    _, _, row2 = or_proxy.handle(ep, Budget(1.0), body, pacer, sleep=slept.append)
    assert abs(row2["l4_target_s"] - round(l4_model_s(100, 0), 3)) < 1e-9


def test_no_pacing_on_error_or_when_disabled():
    ep, _ = fake_ep(None, status=429)
    slept = []
    _, _, row = or_proxy.handle(ep, Budget(1.0), {"messages": []}, or_proxy.Pacer(), sleep=slept.append)
    assert not slept and "l4_target_s" not in row
