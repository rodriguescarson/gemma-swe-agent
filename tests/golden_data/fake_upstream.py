"""A local OpenAI-compatible upstream for the golden runner tests (no network): it records every request's headers
and body, can fail with given HTTP statuses first, and answers scripted mock_llm steps per agent (reactive steps get a
mock_llm Request, ``delay`` is honoured) with usage that carries reasoning tokens, OpenRouter's billed ``cost`` when
one is given, and a ``provider`` field."""
from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]
ROOT = TESTS.parent
for _p in (str(TESTS), str(ROOT / "scripts" / "golden")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import router as RT  # noqa: E402
from v10_support.mock_llm import Request  # noqa: E402


class FakeUpstream:
    """A local OpenAI-compatible upstream: records headers and bodies, can fail with given statuses first, answers
    scripted steps per agent (reactive steps get a mock_llm Request), and reports usage with reasoning tokens."""

    def __init__(self, script: dict | None = None, fail: list | None = None, reasoning: int = 7,
                 provider: str = "FakeProv", retry_after: str | None = "0", cost: float | None = None):
        self.script = {k: list(v) for k, v in (script or {}).items()}
        self.fail = list(fail or [])
        self.reasoning = reasoning
        self.provider = provider
        self.retry_after = retry_after
        self.cost = cost
        self.seen: list = []
        self.counters: dict = {}
        self.lock = threading.Lock()
        up = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                with up.lock:
                    up.seen.append({"path": self.path, "headers": dict(self.headers), "body": body})
                    status = up.fail.pop(0) if up.fail else 200
                if status != 200:
                    out = json.dumps({"error": {"message": f"fake {status}"}}).encode()
                    self.send_response(status)
                    if up.retry_after is not None:
                        self.send_header("Retry-After", up.retry_after)
                else:
                    agent, kind = RT.classify(body)
                    with up.lock:
                        i = up.counters.get(agent, 0)
                        up.counters[agent] = i + 1
                    steps = up.script.get(agent) or []
                    step = steps[i] if i < len(steps) else {"text": "done"}
                    if kind == "summarizer":
                        step = {"text": "SUMMARY"}
                    if callable(step):
                        step = step(Request("fake", agent, i, body))
                    if step.get("delay"):
                        time.sleep(float(step["delay"]))
                    resp, _, _, _ = RT.render_step(step, body)
                    resp["usage"]["completion_tokens_details"] = {"reasoning_tokens": up.reasoning}
                    if up.cost is not None:
                        resp["usage"]["cost"] = up.cost
                    resp["provider"] = up.provider
                    out = json.dumps(resp).encode()
                    self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.srv.server_address[1]}/v1"

    def close(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()
