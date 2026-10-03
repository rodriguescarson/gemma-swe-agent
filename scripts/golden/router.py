"""Per-case LLM router for single-stage golden runs (docs/eval/GOLDEN_EVALS_SPEC.md v1.1, 5.3, 5.4 step 4, 5.6, 5.7).

One stdlib ThreadingHTTPServer serves every case of a run: case ``key`` has the OpenAI base ``http://127.0.0.1:<port>/r/
<key>/v1`` and each request is answered by ADK agent name (``Your internal name is "<name>"``):

- the LIVE agent is forwarded to the upstream (openrouter / vllm), answered from the oracle script, or answered
  ``done`` (null); only during its FIRST stage-run: after another agent's request arrived, a later live request is
  answered ``done`` and logged ``done_after_end`` (a harness restart must not re-run the live stage, gotcha 9);
- live cap: once ``now - t_live0 >= (300 - t0) / scale`` every further live request is answered ``done`` and logged
  ``cap`` (the helper-clock t=300 stop, gotcha 16); ``now`` comes from an injectable clock;
- every other agent is SCRIPTED (stage_scripts.py); an exhausted script answers ``done`` (``exhausted``);
- summariser requests go upstream on live endpoints and get the mock summary on oracle/null;
- a request with neither an agent name nor the summariser mark marks the case ``infra_error: unknown_request``.

Forwarding keeps the body verbatim except ``model`` (plus ``--upstream-extra``, the OpenRouter ``provider`` pin and an
optional ``seed``); retries only 429/502/503 (5 times by default, G4_GOLDEN_RETRIES; Retry-After else 5/10/20/30/45 s). OpenRouter runs are pinned to one
provider endpoint by default (``OR_PROVIDER_DEFAULT``, bf16 with tools) with fallbacks off, so every arm is served by
the same quantization; ``--or-provider any`` lifts the pin. Cost: OpenRouter's billed ``usage.cost`` when the reply
carries it (``cost_source: billed``), else tokens x prices (reasoning tokens counted as completion; ``estimate``).
vLLM is free per token: its token-price figure is logged as ``est_usd_at_proxy_prices`` and ``cost_usd`` stays 0. A
shared budget refuses before forwarding once ``spent >= cap - 0.01`` (HTTP 500 ``golden budget exhausted``). The API key
lives only in this process: it is never logged, never written, never put in a child environment (gotcha 14).

L4 model clock (docs/v10/SPEC_v10_2.md E1, ``l4_clock="model"``; the default ``wall`` is the behaviour every earlier run
had, byte for byte). After each forwarded live call, and each summariser call while the live stage-run is on, the
router computes the modelled L4 time ``m = 0.102 + 0.02815 c + 0.000921 u`` (time_model sect. 2; ``u`` = prompt tokens
for the stage-run's first live call and for a summariser call, else ``max(0, p - p_prev - c_prev)``, as
research/locator_diag/l4time.py), sets ``excess = latency - m`` (a failed or refused call models to m = 0), moves the
case's ``$SWE/t0`` forward by ``excess`` (atomic replace, ``<sbx>/*/tmp/swe/t0``) and adds it to the route's
``excess_s``. The live cap then fires when ``now - t_live0 - excess_s >= (300 - t0) / scale``, so the helper clock reads
``scale x (tool wall + sum of m)``: 429 back-off and slow proxy calls no longer move it.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(HERE), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from v10_support.mock_llm import (NAME_RE, PROSE_CPT, SUMMARIZER_MARK, Request,  # noqa: E402
                                  estimate_prompt_tokens)

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = "google/gemma-4-31b-it"
VLLM_MODEL = "gemma-4-31b-it-qat-w4a16-ct"
DEFAULT_ENV_FILE = "/Users/carson/Projects/.env"
LABELS = {"openrouter": "PROXY", "vllm": "FAITHFUL", "oracle": "CONTROL", "null": "CONTROL"}
# The default OpenRouter pin: the endpoint tag of one provider's bf16 deployment with tools, tool_choice, reasoning and
# seed (public GET /api/v1/models/google/gemma-4-31b-it/endpoints on 2026-09-30: 15 endpoints across fp4, fp8, bf16 and
# unknown quantizations, $0.08 to $0.75 per M in; crusoe/bf16 and novita/bf16 are the bf16 ones with tools, both
# $0.14/$0.40, Crusoe at 99.97 % 30-minute uptime). Unpinned, one run's calls can land on fp4 and another's on bf16.
OR_PROVIDER_DEFAULT = "crusoe/bf16"
OR_UNPINNED = ("any", "none")
PRICE_IN_DEFAULT = 0.14          # $/M, the pinned endpoint's listed price (the budget estimate; billed cost wins)
PRICE_OUT_DEFAULT = 0.40
REF_PRICE_IN, REF_PRICE_OUT = 0.09, 0.34   # the prices run_suite.EST_COST was computed at (race-2 tokens)
RETRY_STATUS = (429, 502, 503)
BUDGET_MSG = "golden budget exhausted"
SUMMARY_TEXT = "Summary: earlier steps ran helper scripts; continue from status.py."
DONE = {"text": "done"}
L4_CLOCKS = ("wall", "model")
# research/time_model.md sect. 2 (the L4 latency fit): seconds = A + B x completion tokens + C x uncached prompt tokens
L4_A, L4_B, L4_C = 0.102, 0.02815, 0.000921


def l4_model_s(completion: int, uncached: int) -> float:
    """Modelled Kaggle-L4 seconds of one LLM call (time_model sect. 2)."""
    return L4_A + L4_B * max(0, int(completion or 0)) + L4_C * max(0, int(uncached or 0))


def find_t0_files(sbx: Path | None) -> list:
    """The case's helper clock files: <sbx>/*/tmp/swe/t0 (the subprocess sandbox rewrites /tmp), else any deeper one."""
    if sbx is None:
        return []
    sbx = Path(sbx)
    hits = sorted(sbx.glob("*/tmp/swe/t0"))
    return hits or sorted(p for p in sbx.rglob("t0") if p.parent.name == "swe" and p.parent.parent.name == "tmp")


def shift_t0(path: Path, delta: float) -> bool:
    """Move the epoch in a $SWE/t0 file forward by delta seconds (atomic replace). False when unreadable."""
    path = Path(path)
    try:
        v = float(path.read_text().strip())
    except (OSError, ValueError):
        return False
    tmp = path.with_name(path.name + ".l4tmp")
    try:
        tmp.write_text(repr(v + float(delta)))
        os.replace(tmp, path)
    except OSError:
        return False
    return True


def _text_of(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    return str(content)


def classify(body: dict) -> tuple:
    """(agent, kind): kind is agent | summarizer | unknown (mock_llm's rule)."""
    msgs = body.get("messages") or []
    system = "".join(_text_of(m.get("content")) for m in msgs if m.get("role") == "system")
    m = NAME_RE.search(system)
    if m:
        return m.group(1), "agent"
    if any(SUMMARIZER_MARK in _text_of(x.get("content")) for x in msgs):
        return "_summarizer", "summarizer"
    return "_unknown", "unknown"


def read_env_key(name: str = "OPENROUTER_KEY", env_file: str | None = DEFAULT_ENV_FILE) -> str | None:
    """$name, else the value of a ``name=...`` (or ``export name=...``) line in env_file; quotes stripped."""
    v = (os.environ.get(name) or "").strip()
    if v:
        return v
    if not env_file:
        return None
    try:
        lines = Path(env_file).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        s = line.strip()
        if s.startswith("export "):
            s = s[7:].lstrip()
        k, eq, val = s.partition("=")
        if eq and k.strip() == name:
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            return val or None
    return None


# ------------------------------------------------------------------------------------------------------------ budget
class Budget:
    """Shared USD cap across every case of a run (thread-safe)."""

    def __init__(self, cap_usd: float | None):
        self.cap = cap_usd
        self.spent = 0.0
        self.refused = 0
        self.lock = threading.Lock()

    def allow(self) -> bool:
        with self.lock:
            if self.cap is not None and self.spent >= self.cap - 0.01:
                self.refused += 1
                return False
            return True

    def add(self, usd: float) -> None:
        with self.lock:
            self.spent += float(usd or 0.0)


# ---------------------------------------------------------------------------------------------------------- endpoint
@dataclass
class Endpoint:
    """The router's upstream. ``live`` endpoints forward over HTTP; oracle and null never leave the process."""
    name: str                                   # openrouter | vllm | oracle | null
    base: str | None = None
    model: str | None = None
    key: str | None = field(default=None, repr=False)
    extra: dict = field(default_factory=dict)
    provider: str | None = None
    seed_mode: str = "off"
    price_in: float = PRICE_IN_DEFAULT
    price_out: float = PRICE_OUT_DEFAULT
    timeout: float = 300.0
    # 2026-09-30 smoke: the pinned provider rate-limited 53 of 165 calls (HTTP 429); 2 short retries turned one F case
    # into infra_error. More patience; retried calls are logged (retries, latency) so their clock cost is visible.
    retries: int = int(os.environ.get("G4_GOLDEN_RETRIES", "5"))
    backoff: tuple = (5.0, 10.0, 20.0, 30.0, 45.0)
    sleep: Callable[[float], None] = field(default=time.sleep, repr=False)

    @property
    def live(self) -> bool:
        return self.name in ("openrouter", "vllm")

    @property
    def label(self) -> str:
        return LABELS.get(self.name, "CONTROL")

    @property
    def url(self) -> str | None:
        return (self.base or "").rstrip("/") + "/chat/completions" if self.base else None

    def public(self) -> dict:
        """What run.json records (never the key)."""
        return {"endpoint": self.name, "label": self.label, "upstream_base": self.base, "upstream_model": self.model,
                "or_provider": self.provider, "upstream_extra": self.extra, "seed_mode": self.seed_mode,
                "price_in": self.price_in, "price_out": self.price_out}

    def forward_body(self, body: dict, case_id: str) -> dict:
        out = dict(body)
        out["model"] = self.model
        for k, v in (self.extra or {}).items():
            out[k] = v
        if self.provider:
            out["provider"] = {"order": [self.provider], "allow_fallbacks": False}
        if self.seed_mode == "case":
            out["seed"] = int(hashlib.sha256(case_id.encode()).hexdigest()[:8], 16)
        return out

    def post(self, body: dict) -> tuple:
        """(http status, response dict | None, retries, error text | None). Retries 429/502/503 only."""
        data = json.dumps(body).encode()
        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + (self.key or "EMPTY")}
        retries, last_err, status = 0, None, 0
        for attempt in range(self.retries + 1):
            req = urllib.request.Request(self.url, data=data, headers=headers, method="POST")
            wait = None
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    raw = r.read()
                    status = r.status
                try:
                    return status, json.loads(raw or b"{}"), retries, None
                except ValueError:
                    return 502, None, retries, "upstream returned non-JSON"
            except urllib.error.HTTPError as e:
                status = e.code
                try:
                    raw = e.read()
                except Exception:
                    raw = b""
                last_err = f"HTTP {e.code}: {raw[:300].decode('utf-8', 'replace')}"
                ra = e.headers.get("Retry-After") if e.headers else None
                if ra:
                    try:
                        wait = max(0.0, float(ra))
                    except ValueError:
                        wait = None
                if e.code not in RETRY_STATUS or attempt >= self.retries:
                    return status, _json_or_none(raw), retries, last_err
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                return 599, None, retries, f"{type(e).__name__}: {str(e)[:200]}"
            retries += 1
            self.sleep(wait if wait is not None else self.backoff[min(attempt, len(self.backoff) - 1)])
        return status, None, retries, last_err

    def cost(self, prompt: int, completion: int, reasoning: int) -> float:
        out = completion + reasoning if reasoning > completion else completion   # reasoning counted as completion
        return (prompt * self.price_in + out * self.price_out) / 1e6

    def billed(self, usage: dict) -> float | None:
        """OpenRouter's charged amount for one call (``usage.cost``, USD credits; always included since OpenRouter made
        usage accounting default), else None. Only openrouter replies are billed; a vLLM ``cost`` field is ignored."""
        c = (usage or {}).get("cost") if self.name == "openrouter" else None
        if isinstance(c, bool) or not isinstance(c, (int, float)) or c < 0:
            return None
        return float(c)


def _json_or_none(raw: bytes):
    try:
        return json.loads(raw or b"{}")
    except ValueError:
        return None


# ------------------------------------------------------------------------------------------------------------- route
@dataclass
class Route:
    key: str
    case_id: str
    live_agent: str
    scripts: dict                      # scripted agents: {agent: [steps]}
    live_script: list                  # oracle steps for the live agent ([] for null / unused for live endpoints)
    cap_s: float                       # (300 - t0) / scale
    log_path: Path | None = None
    bodies_path: Path | None = None
    summary_text: str = SUMMARY_TEXT
    t_start: float = 0.0
    i: int = 0
    counters: dict = field(default_factory=dict)
    live_i: int = 0
    t_first: float | None = None
    t_live0: float | None = None
    other_after_live: bool = False
    last_agent: str | None = None
    stage_runs: dict = field(default_factory=dict)
    tools_seen: set = field(default_factory=set)
    infra: list = field(default_factory=list)
    records: list = field(default_factory=list)
    upstream_failed_last: bool = False
    fail_since: float | None = None
    l4_clock: str = "wall"
    sbx: Path | None = None
    excess_s: float = 0.0
    model_s: float = 0.0
    live_prev: tuple | None = None       # (prompt, completion) of the previous forwarded live call (model clock)
    t0_missing: int = 0
    clock: Callable[[], float] = field(default=time.monotonic, repr=False)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def state(self) -> dict:
        with self.lock:
            out = {"t_first": self.t_first, "t_live0": self.t_live0, "infra": list(dict.fromkeys(self.infra)),
                   "upstream_failed_last": self.upstream_failed_last, "requests": self.i,
                   "fail_streak_s": None if self.fail_since is None else round(self.clock() - self.fail_since, 3),
                   "pre_stage_s": (None if self.t_live0 is None or self.t_first is None
                                   else round(self.t_live0 - self.t_first, 3)),
                   "capped": any(r.get("served") == "cap" for r in self.records)}
            if self.l4_clock == "model":
                out.update(l4_clock="model", excess_s=round(self.excess_s, 3), model_s=round(self.model_s, 3),
                           t0_missing=self.t0_missing)
            return out


def render_step(step: dict, body: dict) -> tuple:
    """(response dict, finish_reason, prompt_tokens, completion_tokens): mock_llm's answer shape for a scripted step."""
    est = estimate_prompt_tokens(body)
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
    resp = {"id": "chatcmpl-" + uuid.uuid4().hex[:10], "object": "chat.completion", "created": int(time.time()),
            "model": body.get("model", "mock"), "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
            "usage": {"prompt_tokens": ptok, "completion_tokens": ctok, "total_tokens": ptok + ctok}}
    return resp, finish, ptok, ctok


# ------------------------------------------------------------------------------------------------------------ router
class StageRouter:
    """``with StageRouter(endpoint, budget) as r: base = r.add_route(...)``; ``r.answer(key, body)`` without HTTP."""

    def __init__(self, endpoint: Endpoint, budget: Budget | None = None, *, clock: Callable[[], float] = time.monotonic,
                 log_bodies: bool = False, l4_clock: str = "wall"):
        if l4_clock not in L4_CLOCKS:
            raise ValueError(f"l4_clock must be one of {L4_CLOCKS}, got {l4_clock!r}")
        self.l4_clock = l4_clock
        self.endpoint = endpoint
        self.budget = budget or Budget(None)
        self.clock = clock
        self.log_bodies = log_bodies
        self.routes: dict[str, Route] = {}
        self.lock = threading.Lock()
        self.errors: list[str] = []
        self._srv: ThreadingHTTPServer | None = None
        self._th: threading.Thread | None = None

    # -- lifecycle ---------------------------------------------------------------------------------------------------
    def start(self) -> "StageRouter":
        router = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_GET(self):
                self._send(200, json.dumps({"object": "list", "data": [{"id": VLLM_MODEL, "object": "model"}]}).encode())

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b"{}"
                m = re.match(r"^/r/([^/]+)/", self.path)
                key = m.group(1) if m else ""
                try:
                    body = json.loads(raw or b"{}")
                    status, out = router.answer(key, body)
                except KeyError as e:
                    status, out = 404, {"error": {"message": f"no route: {e}"}}
                except Exception as e:           # never hang the harness: answer 500 with the reason
                    router.errors.append(f"{type(e).__name__}: {e}")
                    status, out = 500, {"error": {"message": f"router error: {type(e).__name__}: {str(e)[:200]}"}}
                self._send(status, json.dumps(out).encode())

            def _send(self, code, out):
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._srv.daemon_threads = True
        self._th = threading.Thread(target=self._srv.serve_forever, name="golden-router", daemon=True)
        self._th.start()
        return self

    def stop(self) -> None:
        if self._srv is not None:
            self._srv.shutdown()
            self._srv.server_close()
            self._srv = None

    def __enter__(self) -> "StageRouter":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    @property
    def port(self) -> int:
        assert self._srv is not None, "router not started"
        return self._srv.server_address[1]

    def url(self, key: str) -> str:
        return f"http://127.0.0.1:{self.port}/r/{key}/v1"

    def add_route(self, key: str, case_id: str, live_agent: str, scripts: dict, live_script: list, cap_s: float, *,
                  log_path: Path | None = None, bodies_path: Path | None = None, sbx: Path | None = None) -> str | None:
        r = Route(key=key, case_id=case_id, live_agent=live_agent, scripts={k: list(v) for k, v in scripts.items()},
                  live_script=list(live_script or []), cap_s=float(cap_s), log_path=log_path,
                  bodies_path=bodies_path if self.log_bodies else None, t_start=self.clock(), clock=self.clock,
                  l4_clock=self.l4_clock, sbx=Path(sbx) if sbx is not None else None)
        for p in (r.log_path, r.bodies_path):
            if p is not None:
                Path(p).parent.mkdir(parents=True, exist_ok=True)
                Path(p).write_text("")
        with self.lock:
            self.routes[key] = r
        return self.url(key) if self._srv is not None else None

    def route(self, key: str) -> Route:
        with self.lock:
            return self.routes[key]

    def remove_route(self, key: str) -> None:
        with self.lock:
            self.routes.pop(key, None)

    # -- answering ---------------------------------------------------------------------------------------------------
    def answer(self, key: str, body: dict) -> tuple:
        """(http status, response dict) for one chat-completions request on route ``key``."""
        route = self.route(key)
        agent, kind = classify(body)
        now = self.clock()
        rec: dict = {"agent": agent, "kind": kind, "live": kind == "agent" and agent == route.live_agent,
                     "stage_run": None, "served": None, "http_status": 200, "retries": 0, "prompt_tokens": 0,
                     "completion_tokens": 0, "reasoning_tokens": 0, "usage_estimated": False, "finish_reason": None,
                     "latency_s": 0.0, "cost_usd": 0.0, "provider": None, "error": None}
        with route.lock:
            rec["i"] = route.i
            route.i += 1
            rec["t_in"] = round(now - route.t_start, 3)
            if route.t_first is None:
                route.t_first = now
            if kind == "agent":
                if agent != route.last_agent:
                    route.stage_runs[agent] = route.stage_runs.get(agent, -1) + 1
                    route.last_agent = agent
                rec["stage_run"] = route.stage_runs[agent]
                if agent not in route.tools_seen:
                    route.tools_seen.add(agent)
                    rec["tools"] = [((t.get("function") or {}).get("name") or t.get("name")) for t in body.get("tools") or []]
            decision, step, idx = self._decide(route, agent, kind, now)
        status, resp = 200, None
        if decision == "forward":
            status, resp = self._forward(route, body, rec)
            if route.l4_clock == "model" and (rec["live"] or (kind == "summarizer" and self._live_on(route))):
                self._model_clock(route, rec, status, self.clock() - now)
        else:
            if callable(step):
                step = step(Request(route.key, agent, idx, body))
            if not isinstance(step, dict) or not ({"tool", "text", "tools"} & set(step)):
                raise ValueError(f"bad step for {agent}#{idx}: {step!r}")
            if step.get("delay"):
                time.sleep(float(step["delay"]))
            resp, finish, ptok, ctok = render_step(step, body)
            rec.update(served=decision, finish_reason=finish, prompt_tokens=ptok, completion_tokens=ctok)
            if decision == "unknown":
                rec["served"], rec["error"] = "script", "unknown_request"
        t_out = self.clock()
        rec["t_out"] = round(t_out - route.t_start, 3)
        rec["latency_s"] = round(t_out - now, 3)
        self._log(route, rec, body, resp, status)
        return status, resp

    def _decide(self, route: Route, agent: str, kind: str, now: float) -> tuple:
        """(served, step, index) under route.lock. served 'forward' means: go upstream."""
        if kind == "unknown":
            route.infra.append("unknown_request")
            return "unknown", DONE, 0
        if kind == "summarizer":
            if self.endpoint.live:
                return "forward", None, 0
            return "script", {"text": route.summary_text}, 0
        if agent == route.live_agent:
            if route.other_after_live:
                return "done_after_end", DONE, 0
            if route.t_live0 is None:
                route.t_live0 = now
            elif now - route.t_live0 - (route.excess_s if route.l4_clock == "model" else 0.0) >= route.cap_s:
                return "cap", DONE, 0
            if self.endpoint.live:
                return "forward", None, 0
            idx = route.live_i
            route.live_i += 1
            if self.endpoint.name == "null":
                return "null", DONE, idx
            if idx < len(route.live_script):
                return "oracle", route.live_script[idx], idx
            return "exhausted", DONE, idx
        if route.t_live0 is not None:
            route.other_after_live = True
        idx = route.counters.get(agent, 0)
        route.counters[agent] = idx + 1
        steps = route.scripts.get(agent) or []
        if idx < len(steps):
            return "script", steps[idx], idx
        return "exhausted", DONE, idx

    @staticmethod
    def _live_on(route: Route) -> bool:
        """The live agent's first stage-run has started and no other agent has spoken since."""
        with route.lock:
            return route.t_live0 is not None and not route.other_after_live

    def _model_clock(self, route: Route, rec: dict, status: int, latency: float) -> None:
        """E1: charge the modelled L4 time m for this call instead of its proxy latency (see the module doc)."""
        ok = status == 200 and rec.get("served") == "upstream"
        with route.lock:
            if not ok:
                m = 0.0
            else:
                p, c = int(rec.get("prompt_tokens") or 0), int(rec.get("completion_tokens") or 0)
                if rec["live"]:
                    u = p if route.live_prev is None else max(0, p - route.live_prev[0] - route.live_prev[1])
                    route.live_prev = (p, c)
                else:
                    u = p                    # a summariser request is a fresh prompt
                m = l4_model_s(c, u)
                rec["l4_uncached"] = u
            excess = latency - m
            route.excess_s += excess
            route.model_s += m
            rec.update(l4_m=round(m, 4), l4_excess=round(excess, 4), l4_excess_total=round(route.excess_s, 4))
            files = find_t0_files(route.sbx)
            moved = sum(shift_t0(f, excess) for f in files)
            if not moved:
                route.t0_missing += 1
            rec["l4_t0_files"] = moved

    def _forward(self, route: Route, body: dict, rec: dict) -> tuple:
        ep = self.endpoint
        if not self.budget.allow():
            with route.lock:
                route.infra.append("budget")
            rec.update(served="refused", http_status=500, error=BUDGET_MSG)
            return 500, {"error": {"message": BUDGET_MSG, "type": "golden_budget"}}
        fwd = ep.forward_body(body, route.case_id)
        rec["forwarded_model"] = fwd.get("model")
        status, resp, retries, err = ep.post(fwd)
        rec.update(served="upstream", http_status=status, retries=retries, error=err)
        if status != 200 or not isinstance(resp, dict) or not resp.get("choices"):
            with route.lock:
                route.upstream_failed_last = True
                if route.fail_since is None:
                    route.fail_since = self.clock()
            if status == 200:
                rec.update(http_status=502, error=err or "upstream reply without choices")
                status = 502
            return status, resp if isinstance(resp, dict) else {"error": {"message": err or f"upstream HTTP {status}"}}
        with route.lock:
            route.upstream_failed_last = False
            route.fail_since = None
        usage = resp.get("usage") or {}
        choice = (resp.get("choices") or [{}])[0] or {}
        msg = choice.get("message") or {}
        if usage.get("prompt_tokens") is None:
            p = estimate_prompt_tokens(body)
            out = _text_of(msg.get("content")) + "".join(
                ((tc.get("function") or {}).get("arguments") or "") for tc in msg.get("tool_calls") or [])
            c = max(1, int(len(out) / PROSE_CPT))
            resp["usage"] = usage = {"prompt_tokens": p, "completion_tokens": c, "total_tokens": p + c}
            rec["usage_estimated"] = True
        details = usage.get("completion_tokens_details") or {}
        rt = int(details.get("reasoning_tokens") or usage.get("reasoning_tokens") or 0)
        pt, ct = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
        billed = ep.billed(usage)
        cost = billed if billed is not None else ep.cost(pt, ct, rt)
        self.budget.add(cost)            # vllm: only an explicit --max-usd makes this a cap (run_suite)
        if ep.name == "vllm":            # free per token: the figure is what the call would cost on the proxy
            rec.update(cost_usd=0.0, est_usd_at_proxy_prices=round(cost, 8), cost_source="est_usd_at_proxy_prices")
        else:
            rec.update(cost_usd=round(cost, 8), cost_source="billed" if billed is not None else "estimate")
        rec.update(prompt_tokens=pt, completion_tokens=ct, reasoning_tokens=rt,
                   finish_reason=choice.get("finish_reason"), provider=resp.get("provider"))
        return 200, resp

    def _log(self, route: Route, rec: dict, body: dict, resp: dict | None, status: int) -> None:
        with route.lock:
            route.records.append(rec)
            if route.log_path is not None:
                with open(route.log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, sort_keys=True) + "\n")
            if route.bodies_path is not None:
                with open(route.bodies_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"i": rec["i"], "agent": rec["agent"], "served": rec["served"],
                                        "http_status": status, "request": body, "response": resp}) + "\n")


def or_pin(or_provider: str | None) -> str | None:
    """The OpenRouter provider pin: None -> OR_PROVIDER_DEFAULT; 'any' or 'none' -> no pin; else the given slug/tag."""
    if or_provider is None:
        return OR_PROVIDER_DEFAULT
    v = or_provider.strip()
    return None if v.lower() in OR_UNPINNED or not v else v


def make_endpoint(name: str, *, upstream_base: str | None = None, upstream_model: str | None = None,
                  env_file: str | None = DEFAULT_ENV_FILE, or_provider: str | None = None,
                  upstream_extra: dict | None = None, seed_mode: str = "off", price_in: float = PRICE_IN_DEFAULT,
                  price_out: float = PRICE_OUT_DEFAULT, key: str | None = None) -> Endpoint:
    """The --endpoint choices of 5.6. Raises ValueError when a live endpoint lacks its base or key. openrouter is pinned
    to OR_PROVIDER_DEFAULT unless or_provider names another pin or 'any'."""
    extra = dict(upstream_extra or {})
    if "provider" in extra:
        raise ValueError("--upstream-extra must not carry 'provider': pin it with --or-provider (recorded in run.json)")
    if name == "openrouter":
        k = key or read_env_key("OPENROUTER_KEY", env_file)
        if not k:
            raise ValueError(f"OPENROUTER_KEY not in the environment or {env_file}")
        return Endpoint("openrouter", base=upstream_base or OPENROUTER_BASE, model=upstream_model or OPENROUTER_MODEL,
                        key=k, extra=extra, provider=or_pin(or_provider), seed_mode=seed_mode, price_in=price_in,
                        price_out=price_out)
    if name == "vllm":
        if not upstream_base:
            raise ValueError("--endpoint vllm needs --upstream-base URL")
        return Endpoint("vllm", base=upstream_base, model=upstream_model or VLLM_MODEL, key="EMPTY", extra=extra,
                        seed_mode=seed_mode, price_in=price_in, price_out=price_out)
    if name in ("oracle", "null"):
        return Endpoint(name, seed_mode=seed_mode, price_in=price_in, price_out=price_out)
    raise ValueError(f"unknown endpoint {name!r}")
