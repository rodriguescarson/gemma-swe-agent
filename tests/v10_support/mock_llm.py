"""Scripted OpenAI-compatible chat-completions server for offline ADK / swegemma flow tests (SPEC R113, R114).

Ported from the ephemeral scratchpad/cfgspace/mock_openai.py + probe_runtime.py, with the fixes the config-space probes
needed (config_space.md, C3 artefact): steps are chosen by SERVER-SIDE counters per (route, agent), never by counting
tool messages, because token-threshold compaction removes those messages from the next request.

Routing. One server serves many independent scripted "models": ``url(key)`` returns ``http://127.0.0.1:<port>/r/<key>/v1``
and every request to that base is answered from the script registered under ``key``. Each Evaluator run (or each
scenario) points its model registry / OPENAI_BASE_URL at its own route, so scenarios can run concurrently.

Agent identity. ADK puts ``You are an agent. Your internal name is "<name>".`` in every agent's system instruction
(google/adk/flows/llm_flows/identity.py:37). Requests without it are the compaction summariser
(google/adk/apps/llm_event_summarizer.py: "The following is a conversation history ...") or unknown.

Steps. A script is ``{agent_name: [step, ...]}``. A step is one of
    {"tool": name, "args": {...}}            one tool call
    {"text": "..."}                         a text-only reply (ends a SequentialAgent stage)
    callable(Request) -> step dict          reactive step (look at the last tool result, e.g. "can't open file")
Optional keys on a dict step: "ptok" (forced usage.prompt_tokens, e.g. 15000 to force compaction), "ctok"
(completion tokens), "delay" (seconds to sleep before answering). When an agent's list is exhausted the route's
``default`` step is used (text "done") and the event is recorded as exhausted.

Usage. ``usage.prompt_tokens`` is estimated from the request itself (3.4 chars/token for prose, 3.0 for the
double-encoded tool results, SPEC 6), so ADK's token-threshold compaction fires exactly when a real run would.
Stdlib only; starts in milliseconds.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

NAME_RE = re.compile(r'Your internal name is "([^"]+)"')
SUMMARIZER_MARK = "The following is a conversation history between a user and an AI agent"
PROSE_CPT = 3.4          # chars per token, prose and declarations (SPEC 6)
TOOL_CPT = 3.0           # chars per token, double-encoded tool results (SPEC 6)
COMPACTION_LINE = 14336  # the Kaggle token_threshold


def _text_of(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    return str(content)


def estimate_prompt_tokens(body: dict) -> int:
    """Realistic prompt size of an OpenAI chat request: messages plus tool declarations."""
    prose = tool = 0
    for m in body.get("messages") or []:
        txt = _text_of(m.get("content"))
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            txt += fn.get("name", "") + (fn.get("arguments") or "")
        if m.get("role") == "tool":
            tool += len(txt)
        else:
            prose += len(txt)
    decl = len(json.dumps(body.get("tools") or [], separators=(",", ":")))
    return int((prose + decl) / PROSE_CPT + tool / TOOL_CPT) + 8 * len(body.get("messages") or [])


@dataclass
class Request:
    """What a reactive step sees."""
    key: str
    agent: str
    index: int                 # 0-based step index of this agent on this route
    body: dict

    @property
    def messages(self) -> list:
        return self.body.get("messages") or []

    def system(self) -> str:
        return "".join(_text_of(m.get("content")) for m in self.messages if m.get("role") == "system")

    def tool_results(self) -> list[str]:
        return [_text_of(m.get("content")) for m in self.messages if m.get("role") == "tool"]

    def last_tool_result(self) -> str:
        r = self.tool_results()
        return r[-1] if r else ""

    def user_texts(self) -> list[str]:
        return [_text_of(m.get("content")) for m in self.messages if m.get("role") == "user"]

    def all_text(self) -> str:
        return "\n".join(_text_of(m.get("content")) for m in self.messages)


@dataclass
class Route:
    key: str
    script: dict
    default: dict = field(default_factory=lambda: {"text": "done"})
    summary_text: str = "Summary: earlier steps ran helper scripts; continue from status.py."
    counters: dict = field(default_factory=dict)
    log: list = field(default_factory=list)


def when(cond: Callable[[Request], bool], then: dict, otherwise: dict) -> Callable[[Request], dict]:
    """Reactive step: ``then`` if ``cond(request)`` else ``otherwise``."""
    def step(req: Request) -> dict:
        return then if cond(req) else otherwise
    step.__name__ = "when"
    return step


def last_result_has(*needles: str) -> Callable[[Request], bool]:
    return lambda req: any(n in req.last_tool_result() for n in needles)


class MockLLM:
    """Threaded HTTP server; ``with MockLLM() as m: base = m.add_route("a", script)``."""

    def __init__(self) -> None:
        self.routes: dict[str, Route] = {}
        self.lock = threading.Lock()
        self.t0 = time.perf_counter()
        self.errors: list[str] = []
        self._srv: ThreadingHTTPServer | None = None
        self._th: threading.Thread | None = None

    # -- lifecycle -------------------------------------------------------------------------------------------------
    def start(self) -> "MockLLM":
        mock = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):  # silence
                pass

            def do_GET(self):  # /v1/models probes
                out = json.dumps({"object": "list", "data": [{"id": "gemma-4-31b-it-qat-w4a16-ct", "object": "model"}]}).encode()
                self._send(200, out)

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b"{}"
                try:
                    body = json.loads(raw or b"{}")
                    out = mock._answer(self.path, body)
                    self._send(200, json.dumps(out).encode())
                except Exception as e:  # never hang the client: answer 500 with the reason
                    mock.errors.append(f"{type(e).__name__}: {e}")
                    self._send(500, json.dumps({"error": {"message": str(e)[:300]}}).encode())

            def _send(self, code, out):
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._srv.daemon_threads = True
        self._th = threading.Thread(target=self._srv.serve_forever, name="mock-llm", daemon=True)
        self._th.start()
        return self

    def stop(self) -> None:
        if self._srv is not None:
            self._srv.shutdown()
            self._srv.server_close()
            self._srv = None

    def __enter__(self) -> "MockLLM":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    @property
    def port(self) -> int:
        assert self._srv is not None, "server not started"
        return self._srv.server_address[1]

    # -- scripting -------------------------------------------------------------------------------------------------
    def url(self, key: str) -> str:
        return f"http://127.0.0.1:{self.port}/r/{key}/v1"

    def add_route(self, key: str, script: dict, *, default: dict | None = None, summary_text: str | None = None) -> str:
        r = Route(key=key, script={k: list(v) for k, v in script.items()})
        if default is not None:
            r.default = default
        if summary_text is not None:
            r.summary_text = summary_text
        with self.lock:
            self.routes[key] = r
        return self.url(key)

    def log(self, key: str) -> list[dict]:
        with self.lock:
            return list(self.routes[key].log)

    def agent_requests(self, key: str, agent: str) -> list[dict]:
        return [e for e in self.log(key) if e["agent"] == agent]

    def summarizer_calls(self, key: str) -> int:
        return sum(1 for e in self.log(key) if e["kind"] == "summarizer")

    # -- answering -------------------------------------------------------------------------------------------------
    def _route_for(self, path: str) -> Route:
        m = re.match(r"^/r/([^/]+)/", path)
        key = m.group(1) if m else ""
        with self.lock:
            if key not in self.routes:
                raise KeyError(f"no route {key!r} for path {path}")
            return self.routes[key]

    def _answer(self, path: str, body: dict) -> dict:
        t_in = time.perf_counter() - self.t0
        route = self._route_for(path)
        system = "".join(_text_of(m.get("content")) for m in body.get("messages") or [] if m.get("role") == "system")
        m = NAME_RE.search(system)
        est = estimate_prompt_tokens(body)
        if m:
            agent, kind = m.group(1), "agent"
        elif any(SUMMARIZER_MARK in _text_of(x.get("content")) for x in body.get("messages") or []):
            agent, kind = "_summarizer", "summarizer"
        else:
            agent, kind = "_unknown", "unknown"
        with self.lock:
            idx = route.counters.get(agent, 0)
            route.counters[agent] = idx + 1
        exhausted = False
        if kind == "summarizer":
            step: Any = {"text": route.summary_text}
        else:
            steps = route.script.get(agent) or []
            if idx < len(steps):
                step = steps[idx]
            else:
                step, exhausted = route.default, True
        if callable(step):
            step = step(Request(route.key, agent, idx, body))
        if not isinstance(step, dict) or not ({"tool", "text", "tools"} & set(step)):
            raise ValueError(f"bad step for {agent}#{idx}: {step!r}")
        if step.get("delay"):
            time.sleep(float(step["delay"]))
        ptok = int(step.get("ptok") or est)
        if "tool" in step or "tools" in step:
            calls = step.get("tools") or [{"tool": step["tool"], "args": step.get("args", {})}]
            tool_calls = [{"id": "call_" + uuid.uuid4().hex[:10], "type": "function",
                           "function": {"name": c["tool"], "arguments": json.dumps(c.get("args", {}))}} for c in calls]
            msg = {"role": "assistant", "content": None, "tool_calls": tool_calls}
            finish, out_chars = "tool_calls", sum(len(t["function"]["arguments"]) + 12 for t in tool_calls)
        else:
            msg = {"role": "assistant", "content": step["text"]}
            finish, out_chars = "stop", len(step["text"])
        ctok = int(step.get("ctok") or max(1, out_chars / PROSE_CPT))
        entry = {"t_in": round(t_in, 3), "t_out": round(time.perf_counter() - self.t0, 3), "agent": agent, "kind": kind,
                 "index": idx, "est_prompt_tokens": est, "prompt_tokens": ptok, "exhausted": exhausted,
                 "step": {k: v for k, v in step.items() if k != "delay"}, "body": body}
        with self.lock:
            route.log.append(entry)
        return {"id": "chatcmpl-" + uuid.uuid4().hex[:10], "object": "chat.completion", "created": int(time.time()),
                "model": body.get("model", "mock"),
                "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
                "usage": {"prompt_tokens": ptok, "completion_tokens": ctok, "total_tokens": ptok + ctok}}


# -- convenience step builders (tool names are the harness's; arguments in the template order the prompts teach) -------
def skill(file_path: str, args: dict | list | None = None, positional: list | None = None, **extra) -> dict:
    a: dict = {"file_path": file_path, "skill_name": "swe-tools"}
    if args is not None:
        a["args"] = args
    if positional is not None:
        a["positional_args"] = positional
    return {"tool": "run_skill_script", "args": a, **extra}


def cmd(command: str, **extra) -> dict:
    return {"tool": "run_command", "args": {"command": command}, **extra}


def text(t: str, **extra) -> dict:
    return {"text": t, **extra}


def submit(**extra) -> dict:
    return {"tool": "submit_patch", "args": {}, **extra}


def heredoc(command: str, body: str) -> dict:
    """``command <<'EOF' ... EOF`` as one run_command step (the EDITFORM / repro form the prompts teach)."""
    if not body.endswith("\n"):
        body += "\n"
    return cmd(f"{command} <<'EOF'\n{body}EOF")
