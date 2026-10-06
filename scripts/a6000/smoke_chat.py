"""One tool-call chat request and a ~1k-token tokens/s measurement against the local vLLM (scripts/a6000/serve.sh)."""
import json, sys, time, urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/v1"


def post(body, timeout=900):
    req = urllib.request.Request(BASE + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer EMPTY"})
    t = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r), time.time() - t


model = json.load(urllib.request.urlopen(BASE + "/models"))["data"][0]["id"]
tool = {"type": "function", "function": {"name": "get_weather", "description": "Weather for a city",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}
out, _ = post({"model": model, "messages": [{"role": "user", "content": "What is the weather in Lisbon? Use the tool."}],
               "tools": [tool], "max_tokens": 512, "temperature": 0})
calls = out["choices"][0]["message"].get("tool_calls") or []
print("TOOL_CALL", json.dumps([c["function"] for c in calls]))
out, dt = post({"model": model, "messages": [{"role": "user", "content": "Write a long detailed essay about the history of the compiler, at least 1500 words."}],
                "max_tokens": 1000, "min_tokens": 1000, "temperature": 0.7})
n = out["usage"]["completion_tokens"]
print("MODEL", model, "completion_tokens", n, "seconds", round(dt, 1), "tokens_per_s", round(n / dt, 1))
sys.exit(0 if calls else 1)
