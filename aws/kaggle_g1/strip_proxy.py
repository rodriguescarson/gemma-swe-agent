"""Forward OpenAI chat requests to the teacher's vLLM without the fields its Mistral tokenizer path refuses.

    python strip_proxy.py --listen 8102 --upstream http://127.0.0.1:8101 --log /kaggle/working/strip_proxy.jsonl

vLLM 0.19.1 rejects every request that carries `chat_template_kwargs` or `chat_template` when it serves a model with the
Mistral tokenizer (vllm/tokenizers/mistral.py validate_request_params: "chat_template is not supported for Mistral
tokenizers"; offline G1 run 4, 2026-10-26). The v12b harness sends `chat_template_kwargs: {"enable_thinking": ...}`, a
variable of Gemma's chat template that means nothing to Devstral. This proxy sits between scripts/or_proxy.py (which still
captures the request exactly as the harness sent it) and vLLM, drops those two keys, and passes everything else, the reply
and the status code through unchanged. One JSON line per request: t, path, stripped keys, upstream status, latency_s.
"""
import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STRIP = ("chat_template_kwargs", "chat_template")


def strip(body):
    """-> (body without the refused keys, the keys removed)."""
    removed = [k for k in STRIP if k in body]
    return {k: v for k, v in body.items() if k not in STRIP}, removed


def serve(port, upstream, log_path, host="127.0.0.1", timeout=1800):
    lock = threading.Lock()

    def record(row):
        if log_path:
            with lock, open(log_path, "a") as f:
                f.write(json.dumps(row) + "\n")

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _relay(self, method, data=None):
            t0, removed = time.time(), []
            if data is not None:
                try:
                    body, removed = strip(json.loads(data or b"{}"))
                    data = json.dumps(body).encode()
                except ValueError:
                    pass   # not JSON: pass it through untouched and let vLLM answer
            req = urllib.request.Request(upstream.rstrip("/") + self.path, data=data, method=method,
                                         headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    status, payload = r.status, r.read()
            except urllib.error.HTTPError as e:
                status, payload = e.code, e.read()
            except Exception as e:   # upstream down or timed out: a 502 the harness sees as a failed call
                status, payload = 502, json.dumps({"error": {"message": f"strip_proxy: {e!r}"[:500]}}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            record({"t": round(t0, 3), "path": self.path, "stripped": removed, "status": status, "latency_s": round(time.time() - t0, 3)})

        def do_GET(self):
            self._relay("GET")

        def do_POST(self):
            self._relay("POST", self.rfile.read(int(self.headers.get("Content-Length") or 0)))

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 128   # 8 concurrent harness tasks; the default backlog of 5 resets connections under bursts

    return Server((host, port), H)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--listen", type=int, required=True); ap.add_argument("--upstream", required=True); ap.add_argument("--log")
    a = ap.parse_args(argv)
    srv = serve(a.listen, a.upstream, a.log)
    print(f"strip_proxy :{a.listen} -> {a.upstream} (drops {', '.join(STRIP)})", flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
