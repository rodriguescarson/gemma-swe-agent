"""LLM council (karpathy/llm-council pattern) over OpenRouter, stdlib only.

Stage 1: every council model answers the question independently.
Stage 2: every model reviews the anonymised answers (Response A, B, ...) and ranks them.
Stage 3: the chairman synthesises one final answer from all answers and all rankings.

Usage: python scripts/llm_council.py --question-file Q.md --context-file C.md [--context-file ...] --out DIR
       [--models m1,m2,...] [--chairman M] [--max-usd 6]
Writes stage1.json, stage2.json, final.md and cost.json into DIR. Key: OPENROUTER_KEY (never logged).
"""
import argparse, concurrent.futures as cf, json, os, re, string, sys, time, urllib.request

URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODELS = ["anthropic/claude-opus-5.5", "openai/gpt-5.6-terra-pro", "google/gemini-3.1-pro-preview",
                  "x-ai/grok-4.7", "deepseek/deepseek-v4-pro-0813"]
CHAIRMAN = "anthropic/claude-opus-5.5"
SPENT = {"usd": 0.0, "calls": []}


def ask(model, messages, max_usd, max_tokens=6000, retries=4):
    if SPENT["usd"] >= max_usd:
        raise RuntimeError("council budget exhausted")
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "usage": {"include": True}}
    req = urllib.request.Request(URL, json.dumps(body).encode(), {
        "Authorization": "Bearer " + os.environ["OPENROUTER_KEY"], "Content-Type": "application/json"})
    for a in range(retries + 1):
        try:
            r = json.load(urllib.request.urlopen(req, timeout=600))
            cost = float((r.get("usage") or {}).get("cost") or 0)
            SPENT["usd"] += cost
            SPENT["calls"].append({"model": model, "cost": cost, "usage": r.get("usage")})
            return r["choices"][0]["message"]["content"] or ""
        except Exception as e:  # noqa: BLE001 - retry any transport or rate-limit error
            if a == retries:
                return f"[ERROR from {model}: {str(e)[:300]}]"
            time.sleep(10 * (a + 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--question-file", required=True)
    ap.add_argument("--context-file", action="append", default=[])
    ap.add_argument("--out", required=True)
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS))
    ap.add_argument("--chairman", default=CHAIRMAN)
    ap.add_argument("--max-usd", type=float, default=6.0)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    models = [m.strip() for m in a.models.split(",") if m.strip()]
    question = open(a.question_file).read()
    context = "\n\n".join(f"===== {os.path.basename(p)} =====\n{open(p).read()}" for p in a.context_file)
    base = f"CONTEXT:\n{context}\n\nQUESTION:\n{question}"

    # Stage 1
    with cf.ThreadPoolExecutor(len(models)) as ex:
        s1 = dict(zip(models, ex.map(lambda m: ask(m, [{"role": "user", "content": base}], a.max_usd), models)))
    json.dump(s1, open(f"{a.out}/stage1.json", "w"), indent=1)
    print(f"stage 1 done, ${SPENT['usd']:.3f}", file=sys.stderr)

    # Stage 2: anonymised peer review and ranking
    labels = dict(zip(models, string.ascii_uppercase))
    anon = "\n\n".join(f"### Response {labels[m]}\n{s1[m]}" for m in models)
    review_q = (f"{base}\n\nBelow are anonymised responses from several advisers to the QUESTION. Evaluate each one "
                f"critically: correctness against the CONTEXT facts, whether it respects the competition's hard "
                f"constraints, whether its gains are evidenced, and actionability. Then end with a line exactly of the "
                f"form 'FINAL RANKING: X, Y, Z, ...' listing response letters best first.\n\n{anon}")
    with cf.ThreadPoolExecutor(len(models)) as ex:
        s2 = dict(zip(models, ex.map(lambda m: ask(m, [{"role": "user", "content": review_q}], a.max_usd), models)))
    ranks = {}
    for m, txt in s2.items():
        hit = re.findall(r"FINAL RANKING:\s*([A-Z](?:\s*,\s*[A-Z])*)", txt)
        ranks[m] = [x.strip() for x in hit[-1].split(",")] if hit else []
    inv = {v: k for k, v in labels.items()}
    agg = {}
    for order in ranks.values():
        for pos, lab in enumerate(order, 1):
            if lab in inv:
                agg.setdefault(inv[lab], []).append(pos)
    avg = sorted(((sum(v) / len(v), k) for k, v in agg.items()))
    json.dump({"labels": labels, "reviews": s2, "rankings": ranks, "avg_rank": avg}, open(f"{a.out}/stage2.json", "w"), indent=1)
    print(f"stage 2 done, ${SPENT['usd']:.3f}; avg rank: {[(round(r, 2), m) for r, m in avg]}", file=sys.stderr)

    # Stage 3: chairman synthesis
    named = "\n\n".join(f"### Response {labels[m]} ({m})\n{s1[m]}" for m in models)
    reviews = "\n\n".join(f"### Review by {m}\n{s2[m]}" for m in models)
    chair_q = (f"{base}\n\nYou are the chairman of an advisory council. Below are the council's independent answers "
               f"and their anonymised peer reviews with rankings (aggregate average rank, lower is better: "
               f"{[(round(r, 2), m) for r, m in avg]}). Synthesise ONE final recommendation: the ranked plan of what to "
               f"do next to maximise the hidden-set score by the deadline, what to stop doing, where the council agrees "
               f"and disagrees, the key uncertainties, and the cheapest experiments that would resolve them. Stay "
               f"strictly within the competition's hard constraints and the facts in the CONTEXT; flag any council "
               f"claim that contradicts them.\n\nANSWERS:\n{named}\n\nREVIEWS:\n{reviews}")
    final = ask(a.chairman, [{"role": "user", "content": chair_q}], a.max_usd + 3, max_tokens=8000)
    open(f"{a.out}/final.md", "w").write(final)
    json.dump(SPENT, open(f"{a.out}/cost.json", "w"), indent=1)
    print(f"done, total ${SPENT['usd']:.3f}", file=sys.stderr)


if __name__ == "__main__":
    main()
