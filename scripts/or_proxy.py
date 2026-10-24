"""OpenAI-compatible proxy: the full harness talks to it as if it were the pod's vLLM, it forwards to OpenRouter.

Replaces the rented H100 pods for A/B races (2026-09-30: pods cost ~$155 in a week and ranked bundles no better than the
proxy). Reuses the golden router's tested pieces: ``Endpoint`` (provider pin, fallbacks off, 429/502/503 retries with
back-off) and ``Budget`` (hard USD cap; once hit, every call gets HTTP 500 so the run fails loudly instead of skewing).

    python scripts/or_proxy.py --port 8790 --max-usd 4 --log eval/runs/<run>/proxy.jsonl [--or-provider crusoe/bf16]

One JSON line per call: t, status, latency_s, retries, prompt/completion tokens, cost_usd, spent_usd, err. The key is
read from OPENROUTER_KEY or ~/Projects/.env and never logged. Non-streaming only (the harness never streams).

``--upstream bedrock --model <bedrock id> [--region us-west-2]`` serves a teacher on Amazon Bedrock instead (router.
BedrockEndpoint: OpenAI <-> converse translation, list-price costing for the cap, AWS keys read in-process only).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "golden"))
from router import VLLM_MODEL, Budget, l4_model_s, make_bedrock_endpoint, make_endpoint  # noqa: E402


class Pacer:
    """Hold each reply until the modelled Kaggle-L4 time of that call has passed (router.l4_model_s), so the harness's
    wall-clock cap sees L4 speed whatever the provider's speed. Uncached tokens per conversation (keyed by its first two
    messages) = prompt - previous prompt - previous completion, as vLLM prefix caching would give; a new conversation
    pays its whole prompt. A provider slower than the model is not compensated (logged as late_s)."""

    def __init__(self):
        self.prev, self.lock = {}, threading.Lock()

    def target_s(self, body: dict, prompt: int, completion: int) -> float:
        key = hashlib.sha256(json.dumps((body.get("messages") or [])[:2], sort_keys=True, default=str).encode()).hexdigest()
        with self.lock:
            pp, pc = self.prev.get(key, (0, 0))
            self.prev[key] = (prompt, completion)
        uncached = prompt if prompt < pp else prompt - pp - pc
        return l4_model_s(completion, max(0, uncached))



def handle(ep, budget: Budget, body: dict, pacer: "Pacer | None" = None, sleep=time.sleep) -> tuple:
    """(status, response dict, log row) for one chat-completions body. Pure except for ep.post."""
    if body.get("stream"):
        return 400, {"error": {"message": "or_proxy: streaming not supported"}}, {"status": 400, "err": "stream"}
    if not budget.allow():
        return 500, {"error": {"message": "or_proxy budget exhausted"}}, {"status": 500, "err": "budget"}
    t0 = time.monotonic()
    status, resp, retries, err = ep.post(ep.forward_body(body, ""))
    usage = (resp or {}).get("usage") or {}
    cost = ep.billed(usage)
    if cost is None:
        cost = ep.cost(int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0), 0)
    budget.add(cost)
    row = {"status": status, "latency_s": round(time.monotonic() - t0, 3), "retries": retries,
           "prompt": usage.get("prompt_tokens"), "completion": usage.get("completion_tokens"),
           "cost_usd": round(cost, 6), "spent_usd": round(budget.spent, 4), "err": err}
    if pacer is not None and status == 200:
        target = pacer.target_s(body, int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0))
        elapsed = time.monotonic() - t0
        row["l4_target_s"], row["late_s"] = round(target, 3), round(max(0.0, elapsed - target), 3)
        if elapsed < target:
            sleep(target - elapsed)
    if resp is None:
        resp = {"error": {"message": err or f"upstream status {status}"}}
    elif isinstance(resp.get("model"), str):
        resp["model"] = body.get("model") or resp["model"]   # echo the harness's own model name back
    return status, resp, row


def probe(ep) -> tuple:
    """One tiny upstream call: (ok, status, message). E1 (docs/PLAN_TO_FINISH.txt): a pass never starts on a key that is
    over its limit (OpenRouter answers 403 'Key limit exceeded' to every call; the 2026-10-03 sample 3 was 159 of them)."""
    status, resp, _ = handle(ep, Budget(0.05), {"messages": [{"role": "user", "content": "Reply with the single word ok."}],
                                                "max_tokens": 4, "temperature": 0})
    msg = ((resp or {}).get("error") or {}).get("message") if status != 200 else "ok"
    return status == 200, status, str(msg)


def serve(port: int, ep, budget: Budget, log_path: Path, host: str = "0.0.0.0", pacer=None,
          capture_path: "Path | None" = None) -> ThreadingHTTPServer:
    """capture_path: append one JSON line per successful call {t, body, response} (the exact OpenAI request the harness
    sent and the exact reply), the raw material for SFT rows (train/build_sft.py). Nothing is reconstructed later."""
    lock = threading.Lock()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if capture_path is not None:
        capture_path.parent.mkdir(parents=True, exist_ok=True)

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code: int, obj: dict):
            raw = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            self._send(200, {"object": "list", "data": [{"id": VLLM_MODEL, "object": "model"}]})

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
                status, resp, row = handle(ep, budget, body, pacer)
            except Exception as e:              # never hang the harness
                status, resp, row = 500, {"error": {"message": f"or_proxy: {e}"}}, {"status": 500, "err": repr(e)}
            row["t"] = round(time.time(), 3)
            with lock, open(log_path, "a") as f:
                f.write(json.dumps(row) + "\n")
            if capture_path is not None and status == 200:
                with lock, open(capture_path, "a") as f:
                    f.write(json.dumps({"t": row["t"], "body": body, "response": resp}) + "\n")
            self._send(status, resp)

    srv = ThreadingHTTPServer((host, port), H)
    srv.daemon_threads = True
    return srv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--max-usd", type=float, default=None)
    ap.add_argument("--log", default=None)
    ap.add_argument("--probe", action="store_true", help="one upstream call, exit 0 on 200 / 3 otherwise; no server")
    ap.add_argument("--or-provider", default=None)
    ap.add_argument("--l4-pace", action="store_true", help="hold replies to the modelled L4 time per call")
    ap.add_argument("--capture", default=None, help="JSONL of {t, body, response} for every successful call (SFT raw data)")
    ap.add_argument("--model", default=None, help="upstream model id (default google/gemma-4-31b-it); e.g. a teacher")
    ap.add_argument("--upstream", choices=("openrouter", "bedrock", "vllm"), default="openrouter",
                    help="bedrock: a teacher on Amazon Bedrock via boto3 converse (--model is the Bedrock model id); "
                         "vllm: a self-hosted OpenAI-compatible server at --base (e.g. a teacher on EC2)")
    ap.add_argument("--base", default=None, help="upstream base URL for --upstream vllm, e.g. http://127.0.0.1:8000/v1")
    ap.add_argument("--region", default="us-east-1", help="Bedrock region (--upstream bedrock)")
    ap.add_argument("--price-in", type=float, default=None, help="$ per M input tokens (Bedrock models not in the table)")
    ap.add_argument("--price-out", type=float, default=None, help="$ per M output tokens")
    a = ap.parse_args()
    if a.upstream == "bedrock":
        ep = make_bedrock_endpoint(a.model, region=a.region, price_in=a.price_in, price_out=a.price_out)
    elif a.upstream == "vllm":
        ep = make_endpoint("vllm", upstream_base=a.base, upstream_model=a.model, price_in=0.0, price_out=0.0)
    else:
        ep = make_endpoint("openrouter", or_provider=a.or_provider, upstream_model=a.model)
    if a.probe:
        ok, status, msg = probe(ep)
        print(f"or_proxy probe {getattr(ep, 'model', a.model)}: {'OK' if ok else 'FAILED'} status={status} {msg[:160]}", flush=True)
        sys.exit(0 if ok else 3)
    if a.port is None or a.max_usd is None or a.log is None:
        ap.error("--port, --max-usd and --log are required unless --probe")
    srv = serve(a.port, ep, Budget(a.max_usd), Path(a.log), pacer=Pacer() if a.l4_pace else None,
                capture_path=Path(a.capture) if a.capture else None)
    where = {"bedrock": f"bedrock:{a.region}", "vllm": f"vllm:{a.base}"}.get(a.upstream, f"pin={ep.provider}")
    print(f"or_proxy :{a.port} -> {ep.model} {where} cap=${a.max_usd} l4_pace={a.l4_pace}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
