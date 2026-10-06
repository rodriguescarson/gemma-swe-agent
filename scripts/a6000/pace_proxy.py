"""Pacing reverse proxy for the local vLLM (A6000 -> Kaggle-L4 equivalence for the harness's wall-clock cap).

    python scripts/a6000/pace_proxy.py [--listen 8001] [--upstream http://127.0.0.1:8000] [--log FILE]
    then point scripts/a6000/run_eval.py at it with --port 8001.

Every non-streaming chat reply is held until the modelled Kaggle-L4 time of that call has passed (router.l4_model_s,
research/time_model.md sect. 2, the same model scripts/or_proxy.py --l4-pace uses), so a 5-minute cap buys the same amount of model
work as on 4xL4 even if the A6000 is faster (several parallel tasks, or a short-prompt/cached call). A call the A6000 answers
slower than the model is never delayed; its lateness is logged (late_s). One JSON line per call in --log."""
import argparse, json, sys, threading, time, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent)); sys.path.insert(0, str(HERE.parent / "golden"))
from or_proxy import Pacer  # noqa: E402,F401  (the L4 pacing rule, shared with the OpenRouter path)


def post_upstream(base):
    def go(body):
        req = urllib.request.Request(base.rstrip("/") + "/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "Authorization": "Bearer EMPTY"})
        try:
            with urllib.request.urlopen(req, timeout=1800) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.load(e)
            except Exception:
                return e.code, {"error": {"message": str(e)}}
        except Exception as e:
            return 502, {"error": {"message": repr(e)}}
    return go


def handle(upstream, body, pacer, sleep=time.sleep, now=time.monotonic):
    """(status, response, log row). upstream(body) -> (status, dict)."""
    if body.get("stream"):
        return 400, {"error": {"message": "pace_proxy: streaming not supported"}}, {"status": 400, "err": "stream"}
    t0 = now()
    status, resp = upstream(body)
    usage = (resp or {}).get("usage") or {}
    elapsed = now() - t0
    row = {"status": status, "latency_s": round(elapsed, 3), "prompt": usage.get("prompt_tokens"), "completion": usage.get("completion_tokens")}
    if status == 200:
        target = pacer.target_s(body, int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0))
        row["l4_target_s"], row["late_s"] = round(target, 3), round(max(0.0, elapsed - target), 3)
        if elapsed < target:
            sleep(target - elapsed)
    return status, resp, row


def serve(port, upstream_base, log_path, host="127.0.0.1", sleep=time.sleep):
    pacer, lock, up = Pacer(), threading.Lock(), post_upstream(upstream_base)
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, obj):
            raw = json.dumps(obj).encode()
            self.send_response(code); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)

        def do_GET(self):
            try:
                with urllib.request.urlopen(upstream_base.rstrip("/") + self.path, timeout=60) as r:
                    self._send(r.status, json.load(r))
            except Exception as e:
                self._send(502, {"error": {"message": repr(e)}})

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            try:
                status, resp, row = handle(up, json.loads(self.rfile.read(n) or b"{}"), pacer, sleep)
            except Exception as e:
                status, resp, row = 500, {"error": {"message": f"pace_proxy: {e}"}}, {"status": 500, "err": repr(e)}
            row["t"] = round(time.time(), 3)
            with lock, open(log_path, "a") as f:
                f.write(json.dumps(row) + "\n")
            self._send(status, resp)

    srv = ThreadingHTTPServer((host, port), H)
    srv.daemon_threads = True
    return srv


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--listen", type=int, default=8001)
    ap.add_argument("--upstream", default="http://127.0.0.1:8000")
    ap.add_argument("--log", default=str(Path.home() / "g4" / "runs" / "pace_proxy.jsonl"))
    a = ap.parse_args()
    srv = serve(a.listen, a.upstream, a.log)
    print(f"pace_proxy :{a.listen} -> {a.upstream} log={a.log}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
