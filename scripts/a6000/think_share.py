#!/usr/bin/env python3
"""The P10 thinking gate, by hand (docs/GAPS_2026-10-06.md "P10 pre-registration" (a); no supervisor hook implements it).
Capture mode: python scripts/a6000/think_share.py <capture.jsonl | dir with capture*.jsonl> [--min-share 0.8] [--json OUT]
  rows {t, body, response}: the share of model calls whose reply carries a non-empty thought (message.reasoning on vLLM 0.19,
  reasoning_content on older stacks), the key seen, thought length, completion tokens, and how many assistant messages in the
  requests carry a thought back (include_thoughts). Exit 0 = GATE PASS (share >= --min-share), 3 = GATE FAIL.
Proxy-log mode: python scripts/a6000/think_share.py <proxy.jsonl> --proxy-log
  rows {status, latency_s, prompt, completion}: completion tokens and latency per call; the thinking signature from the sub13
  traces (completion/call 274 on, 50 off; 8.7 s vs 2.7 s per call). Available before any capture exists (pair_s50's proxy log)."""
import argparse, glob, json, os, statistics as st, sys


def _stats(v):
    v = sorted(v)
    return {"n": len(v), "mean": round(st.mean(v), 1) if v else 0, "median": st.median(v) if v else 0, "p90": v[int(0.9 * (len(v) - 1))] if v else 0, "max": v[-1] if v else 0}


def _reason(msg):
    for k in ("reasoning_content", "reasoning"):
        if msg.get(k):
            return k, str(msg[k])
    return None, ""


def summarize_captures(rows):
    keys, chars, comp, with_r = {}, [], [], 0
    carried_n = carried_r = 0
    for r in rows:
        try:
            msg = r["response"]["choices"][0]["message"]
        except Exception:
            continue
        k, text = _reason(msg)
        if k:
            with_r += 1; keys[k] = keys.get(k, 0) + 1; chars.append(len(text))
        u = (r.get("response") or {}).get("usage") or {}
        if u.get("completion_tokens") is not None:
            comp.append(int(u["completion_tokens"]))
        for m in ((r.get("body") or {}).get("messages") or []):
            if m.get("role") == "assistant":
                carried_n += 1; carried_r += bool(_reason(m)[0])
    n = len(rows)
    return {"calls": n, "with_reasoning": with_r, "share": (with_r / n) if n else 0.0, "keys": keys, "reasoning_chars": _stats(chars),
            "completion_tokens": _stats(comp), "carried": {"assistant_msgs": carried_n, "with_reasoning": carried_r}}


def proxy_signature(comp):
    m = comp.get("mean") or 0
    return "ON-like" if m >= 150 else ("OFF-like" if m <= 80 else "unclear")


def summarize_proxy(rows):
    ok = [r for r in rows if r.get("status") == 200 and r.get("completion") is not None]
    comp, lat = _stats([int(r["completion"]) for r in ok]), _stats([float(r.get("latency_s") or 0) for r in ok])
    return {"calls": len(ok), "errors": len(rows) - len(ok), "completion_tokens": comp, "latency_s": lat, "signature": proxy_signature(comp)}


def load(path):
    files = sorted(glob.glob(os.path.join(path, "capture*.jsonl"))) if os.path.isdir(path) else [path]
    rows = []
    for f in files:
        with open(f) as fh:
            rows += [json.loads(l) for l in fh if l.strip()]
    return files, rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("path"); ap.add_argument("--min-share", type=float, default=0.8); ap.add_argument("--json"); ap.add_argument("--proxy-log", action="store_true")
    a = ap.parse_args()
    files, rows = load(a.path)
    if a.proxy_log:
        s = summarize_proxy(rows)
        print(f"proxy log: calls {s['calls']} errors {s['errors']} | completion tok/call mean {s['completion_tokens']['mean']} median {s['completion_tokens']['median']} "
              f"p90 {s['completion_tokens']['p90']} | latency/call mean {s['latency_s']['mean']} s median {s['latency_s']['median']} s | thinking signature: {s['signature']}")
        code = 0
    else:
        s = summarize_captures(rows)
        verdict = "GATE PASS" if s["calls"] and s["share"] >= a.min_share else "GATE FAIL"
        print(f"{verdict}: calls {s['calls']} with reasoning {s['with_reasoning']} share {s['share']:.2f} (min {a.min_share}) | keys {s['keys']} | "
              f"reasoning chars median {s['reasoning_chars']['median']} p90 {s['reasoning_chars']['p90']} | completion tok/call mean {s['completion_tokens']['mean']} | "
              f"carried thoughts {s['carried']['with_reasoning']}/{s['carried']['assistant_msgs']} assistant msgs | files {len(files)}")
        code = 0 if verdict == "GATE PASS" else 3
    if a.json:
        with open(a.json, "w") as f:
            json.dump(s, f, indent=1)
    sys.exit(code)


if __name__ == "__main__":
    main()
