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
