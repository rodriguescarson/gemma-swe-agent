"""scripts/a6000/pace_proxy.py: a pacing reverse proxy in front of the local vLLM, so the harness's 5-minute cap sees at least
the modelled Kaggle-L4 time per call (scripts/golden/router.l4_model_s, the same model scripts/or_proxy.py --l4-pace uses).
Written before the script. A6000 faster than the model -> the reply is held; slower -> never delayed."""
import importlib.util, json, pathlib, sys, threading, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(ROOT / "scripts" / "golden"))
spec = importlib.util.spec_from_file_location("pace_proxy", ROOT / "scripts" / "a6000" / "pace_proxy.py")
pp = importlib.util.module_from_spec(spec); spec.loader.exec_module(pp)
from router import l4_model_s  # noqa: E402

BODY = {"messages": [{"role": "user", "content": "hi"}]}


def _upstream(completion, prompt, status=200):
    return lambda body: (status, {"choices": [{"message": {"content": "x"}}], "usage": {"prompt_tokens": prompt, "completion_tokens": completion}})


def test_faster_than_model_is_held_to_the_model_time():
    slept = []
    clock = iter([100.0, 100.5])          # the upstream answered in 0.5 s
    status, resp, row = pp.handle(_upstream(200, 3000), BODY, pp.Pacer(), sleep=slept.append, now=lambda: next(clock))
    target = l4_model_s(200, 3000)
    assert status == 200 and abs(slept[0] - (target - 0.5)) < 1e-6
    assert row["late_s"] == 0.0 and abs(row["l4_target_s"] - round(target, 3)) < 1e-9


def test_slower_than_model_is_never_delayed_and_logs_lateness():
    slept = []
    clock = iter([0.0, 30.0])
    status, _, row = pp.handle(_upstream(100, 500), BODY, pp.Pacer(), sleep=slept.append, now=lambda: next(clock))
    assert slept == [] and row["late_s"] > 20


def test_errors_pass_through_unpaced():
    slept = []
    clock = iter([0.0, 0.1])
    status, resp, row = pp.handle(_upstream(0, 0, status=500), BODY, pp.Pacer(), sleep=slept.append, now=lambda: next(clock))
    assert status == 500 and slept == [] and "l4_target_s" not in row


def test_streaming_is_refused_like_or_proxy():
    status, resp, _ = pp.handle(_upstream(1, 1), dict(BODY, stream=True), pp.Pacer(), sleep=lambda s: None)
    assert status == 400


def test_second_call_of_a_conversation_only_pays_new_prompt_tokens():
    pacer = pp.Pacer()
    first = pacer.target_s(BODY, 1000, 50)
    second = pacer.target_s(BODY, 1100, 40)           # 1100 - 1000 - 50 = 50 uncached
    assert first == l4_model_s(50, 1000) and abs(second - l4_model_s(40, 50)) < 1e-9


def test_end_to_end_through_a_real_socket():
    class Up(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            raw = json.dumps({"data": [{"id": "m"}]}).encode(); self.send_response(200); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            raw = json.dumps({"usage": {"prompt_tokens": 10, "completion_tokens": 1}, "choices": []}).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    up = ThreadingHTTPServer(("127.0.0.1", 0), Up); threading.Thread(target=up.serve_forever, daemon=True).start()
    log = ROOT / "eval" / "runs" / "pace_proxy_test.jsonl"
    px = pp.serve(0, f"http://127.0.0.1:{up.server_address[1]}", log, host="127.0.0.1", sleep=lambda s: None)
    threading.Thread(target=px.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{px.server_address[1]}"
    assert json.load(urllib.request.urlopen(base + "/v1/models"))["data"][0]["id"] == "m"
    req = urllib.request.Request(base + "/v1/chat/completions", data=json.dumps(BODY).encode(), headers={"Content-Type": "application/json"})
    assert json.load(urllib.request.urlopen(req))["usage"]["completion_tokens"] == 1
    assert json.loads(log.read_text().splitlines()[-1])["status"] == 200
    px.shutdown(); up.shutdown(); log.unlink()


def test_model_name_is_rewritten_upstream_and_echoed_back():
    seen = {}

    def up(body):
        seen["model"] = body["model"]
        return 200, {"model": "/home/jc/g4/model", "usage": {"prompt_tokens": 10, "completion_tokens": 1}, "choices": []}
    clock = iter([0.0, 99.0])
    status, resp, _ = pp.handle(up, dict(BODY, model="gemma-4-31b-it-qat-w4a16-ct"), pp.Pacer(), sleep=lambda s: None,
                                now=lambda: next(clock), upstream_model="/home/jc/g4/model")
    assert seen["model"] == "/home/jc/g4/model" and resp["model"] == "gemma-4-31b-it-qat-w4a16-ct"


def test_serve_takes_a_bind_host_and_a_model_rewrite():
    import inspect
    sig = inspect.signature(pp.serve)
    assert "host" in sig.parameters and "upstream_model" in sig.parameters


def test_capture_file_gets_the_exact_request_and_reply(tmp_path):
    class Up(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            raw = json.dumps({"model": "/m", "usage": {"prompt_tokens": 10, "completion_tokens": 1}, "choices": [{"message": {"content": "hi"}}]}).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    up = ThreadingHTTPServer(("127.0.0.1", 0), Up); threading.Thread(target=up.serve_forever, daemon=True).start()
    cap = tmp_path / "cap.jsonl"
    px = pp.serve(0, f"http://127.0.0.1:{up.server_address[1]}", tmp_path / "log.jsonl", host="127.0.0.1", sleep=lambda s: None,
                  upstream_model="/m", capture_path=cap)
    threading.Thread(target=px.serve_forever, daemon=True).start()
    body = {"model": "gemma-4-31b-it-qat-w4a16-ct", "messages": [{"role": "user", "content": "hello"}]}
    req = urllib.request.Request(f"http://127.0.0.1:{px.server_address[1]}/v1/chat/completions", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req).read()
    row = json.loads(cap.read_text().splitlines()[0])
    assert row["body"] == body and row["response"]["choices"][0]["message"]["content"] == "hi" and row["response"]["model"] == body["model"] and "t" in row
    px.shutdown(); up.shutdown()


def test_seed_override_replaces_the_requests_seed_upstream_only():
    seen = {}

    def up(body):
        seen.update(body)
        return 200, {"usage": {"prompt_tokens": 1, "completion_tokens": 1}, "choices": []}
    clock = iter([0.0, 99.0])
    body = dict(BODY, seed=42, temperature=0.2)
    pp.handle(up, body, pp.Pacer(), sleep=lambda s: None, now=lambda: next(clock), seed_override=45)
    assert seen["seed"] == 45 and seen["temperature"] == 0.2 and body["seed"] == 42          # the caller's body is not mutated
    clock = iter([0.0, 99.0])
    pp.handle(up, dict(BODY), pp.Pacer(), sleep=lambda s: None, now=lambda: next(clock), seed_override=None)
    assert "seed" not in seen or seen["seed"] == 45                                           # no override: untouched (seen still holds the old value)


def test_a_served_adapter_name_is_kept_and_only_the_base_alias_is_rewritten():
    """2026-10-13: adapter arms on the box. swegemma's agent_runner requests `openai/<adapter>` (the model field is the adapter name);
    --rewrite-model used to send every call to the base id, so an adapter arm would have raced as the base model."""
    served = {"/home/jc/g4/model", "think1", "think1f", "think2"}
    assert pp.route_model("gemma-4-31b-alias", "/home/jc/g4/model", served) == "/home/jc/g4/model"
    assert pp.route_model("think1", "/home/jc/g4/model", served) == "think1"
    assert pp.route_model("openai/gemma:think2", "/home/jc/g4/model", served) == "think2"      # the resolver's fallback form
    assert pp.route_model("think9", "/home/jc/g4/model", served) == "/home/jc/g4/model"        # unknown adapter: the base (vLLM would 404)
    assert pp.route_model("anything", "/home/jc/g4/model", None) == "/home/jc/g4/model"        # no served list: the old behaviour
    assert pp.route_model("anything", None, served) == "anything"
    seen = []

    def up(body):
        seen.append(body["model"]); return 200, {"model": body["model"], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
    clock = iter([0.0, 0.1, 0.0, 0.1])
    st, resp, row = pp.handle(up, {"model": "think1", "messages": []}, pp.Pacer(), sleep=lambda s: None, now=lambda: next(clock),
                              upstream_model="/home/jc/g4/model", served=served)
    assert seen == ["think1"] and resp["model"] == "think1" and row["lora"] == "think1"
    st, resp, row = pp.handle(up, {"model": "alias", "messages": []}, pp.Pacer(), sleep=lambda s: None, now=lambda: next(clock),
                              upstream_model="/home/jc/g4/model", served=served)
    assert seen[-1] == "/home/jc/g4/model" and resp["model"] == "alias" and "lora" not in row
