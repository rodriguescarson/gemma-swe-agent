#!/usr/bin/env python3
"""The P10 thinking gate, by hand (docs/GAPS_2026-10-06.md "P10 pre-registration" (a); no supervisor hook implements it).
Capture mode: python scripts/a6000/think_share.py <capture.jsonl | dir with capture*.jsonl> [--min-share 0.8] [--json OUT]
  rows {t, body, response}: the share of model calls whose reply carries a non-empty thought (message.reasoning on vLLM 0.19,
  reasoning_content on older stacks), the key seen, thought length, completion tokens, and how many assistant messages in the
  requests carry a thought back (include_thoughts). Exit 0 = GATE PASS (share >= --min-share), 3 = GATE FAIL.
Proxy-log mode: python scripts/a6000/think_share.py <proxy.jsonl> --proxy-log
  rows {status, latency_s, prompt, completion}: completion tokens and latency per call; the thinking signature from the sub13
  traces (completion/call 274 on, 50 off; 8.7 s vs 2.7 s per call). Available before any capture exists (pair_s50's proxy log).
Render mode (capture mode + --render; GAPS "gate (a) extended", 2026-10-11): the TRAINING renderer on the same captures. Every
  row -> prompt (train/scorer_render.render) + completion (canonical_completion, the thought in front), grouped by (task text,
  stage) in file order and stitched with train/stitch_rows.stitch_group exactly as `train.sh stitch` will. Reports the requests'
  thinking flag and budget, completions with a non-empty thought, the chain (exact / healed / broken consecutive pairs) and
  the model spans that start with a thought. RENDER GATE PASS needs: thinking flag on >= 99 % of calls, thought share >= --min-share
  on completions AND on model spans, exact pairs >= --min-share, breaks <= --max-break-share. Healed is not exact: a healed
  pair means the next prompt did NOT carry the thought (include_thoughts off, or the empty channel of a reasonless call)."""
import argparse, glob, hashlib, json, os, statistics as st, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


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


def render_check(rows):
    """See the module docstring, render mode. -> counts and shares, plus the completions (dropped from the JSON)."""
    sys.path.insert(0, ROOT)
    from train.scorer_render import canonical_completion, render, thought_of   # noqa: E402  (needs transformers' template compiler)
    from train.build_sft import first_user_text, stage_of                      # noqa: E402
    from train.stitch_rows import stitch_group                                 # noqa: E402
    from train.spans import describe_span, supervised_char_spans               # noqa: E402
    groups, flags, budgets, completions = {}, {"on": 0, "off": 0}, {}, []
    n = skipped = with_thought = thought_chars = comp_chars = 0
    for r in rows:
        body, resp = r.get("body") or {}, r.get("response") or {}
        try:
            msg = resp["choices"][0]["message"]
        except Exception:
            skipped += 1
            continue
        n += 1
        thinking = bool((body.get("chat_template_kwargs") or {}).get("enable_thinking"))
        flags["on" if thinking else "off"] += 1
        if body.get("thinking_token_budget") is not None:
            b = str(body["thinking_token_budget"]); budgets[b] = budgets.get(b, 0) + 1
        continuation = (body.get("messages") or [{}])[-1].get("role") == "tool"
        prompt, completion = render(body), canonical_completion(msg, continuation, thinking)
        reasoning = thought_of(msg)
        with_thought += bool(reasoning); thought_chars += len(reasoning); comp_chars += len(completion)
        completions.append(completion)
        key = (hashlib.sha1(first_user_text(body).encode("utf-8", "replace")).hexdigest(), stage_of(body))
        groups.setdefault(key, []).append({"prompt": prompt, "completion": completion})
    seqs = pairs = breaks = healed = compactions = model_spans = spans_thought = 0
    for rs in groups.values():
        pairs += max(0, len(rs) - 1)
        for text, calls, b, h, c in stitch_group(rs):
            seqs += 1; breaks += b; healed += h; compactions += c
            sp = supervised_char_spans(text)
            model_spans += len(sp); spans_thought += sum(describe_span(text, a, e)["thought"] for a, e in sp)
    exact = pairs - healed - breaks - compactions
    return {"calls": n, "skipped": skipped, "thinking_on": flags["on"], "thinking_off": flags["off"], "budgets": budgets,
            "with_thought": with_thought, "thought_share": round(with_thought / n, 4) if n else 0.0,
            "thought_chars_share": round(thought_chars / comp_chars, 4) if comp_chars else 0.0,
            "groups": len(groups), "sequences": seqs, "pairs": pairs, "exact": exact, "healed": healed, "breaks": breaks, "compactions": compactions,
            "exact_share": round(exact / pairs, 4) if pairs else 1.0, "break_share": round(breaks / pairs, 4) if pairs else 0.0,
            "model_spans": model_spans, "spans_with_thought": spans_thought,
            "span_thought_share": round(spans_thought / model_spans, 4) if model_spans else 0.0, "completions": completions}


def render_verdict(s, min_share, max_break_share):
    ok = (s["calls"] > 0 and s["thinking_on"] >= 0.99 * s["calls"] and s["thought_share"] >= min_share and s["span_thought_share"] >= min_share
          and s["exact_share"] >= min_share and s["break_share"] <= max_break_share)
    return "RENDER GATE PASS" if ok else "RENDER GATE FAIL"


def render_line(s, verdict, min_share, max_break_share):
    return (f"{verdict}: calls {s['calls']} (thinking flag on {s['thinking_on']} off {s['thinking_off']}; budget {s['budgets']}) | "
            f"completions with thought {s['with_thought']} share {s['thought_share']:.2f} (thought chars {s['thought_chars_share']:.2f} of completions) | "
            f"chain: groups {s['groups']} sequences {s['sequences']} pairs {s['pairs']} exact {s['exact']} ({s['exact_share']:.2f}) healed {s['healed']} "
            f"breaks {s['breaks']} ({s['break_share']:.2f}) compactions {s['compactions']} | model spans {s['model_spans']} with thought {s['spans_with_thought']} "
            f"share {s['span_thought_share']:.2f} | gate: shares >= {min_share}, breaks <= {max_break_share}")


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
    ap.add_argument("--render", action="store_true", help="also run the training renderer + stitcher on the captures (RENDER GATE line)")
    ap.add_argument("--max-break-share", type=float, default=0.02)
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
        if a.render:
            r = render_check(rows)
            rv = render_verdict(r, a.min_share, a.max_break_share)
            print(render_line(r, rv, a.min_share, a.max_break_share))
            s["render"] = {k: v for k, v in r.items() if k != "completions"}
            code = code or (0 if rv == "RENDER GATE PASS" else 3)
    if a.json:
        with open(a.json, "w") as f:
            json.dump(s, f, indent=1)
    sys.exit(code)


if __name__ == "__main__":
    main()
