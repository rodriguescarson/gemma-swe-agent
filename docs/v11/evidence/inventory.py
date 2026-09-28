"""Inventory of model trajectories under eval/**/traces (read-only). Writes inventory_rows.jsonl + prints tables."""
import collections, glob, hashlib, json, os, re, statistics
E = "/Users/carson/Projects/gemma-swe-agent/eval"
SCHEMA = json.load(open(os.path.dirname(os.path.abspath(__file__)) + "/tool_schemas_v10.json"))
EXCLUDE = re.compile(r"/(oracle[^/]*|nopatch_all|rescore_fair)/")
MISSING = re.compile(r"mandatory input parameters are not present|missing .*required|not found in tools|Tool '.*' not found")

def source_of(p):
    if "/race1/" in p: return "race1 (pod H100, July tmpl, no compaction)"
    if "/eval3/" in p: return "eval3 fair (pod H100, July tmpl, no compaction)"
    if "/h100b/" in p: return "h100b (pod H100, July tmpl, no compaction)"
    if "/backups/" in p: return "backup train1 h_* (pod H100, July tmpl, no compaction)"
    if "/kaggle/" in p: return "kaggle (4xL4 TP4, June tmpl, compaction 14336/15)"
    return "runs (pod, early)"

def bundle_of(run):
    m = re.match(r"^(?:r_|c_|p_|h_|canary_|e74_|sw1_|smoke_)?(.*)$", run)
    b = m.group(1)
    if run.startswith("smoke_"): b = "v1"
    if run.startswith("v2_smoke"): b = "v2"
    return b

def load_results(run_dir):
    for c in ("task_results.jsonl", "../results.jsonl"):
        p = os.path.normpath(os.path.join(run_dir, c))
        if os.path.isfile(p):
            out = {}
            for line in open(p):
                if line.strip():
                    r = json.loads(line)
                    out[r.get("instance_id") or r.get("id")] = r
            return out, p
    return {}, None

rows = []
B = "/Users/carson/Projects/gemma-swe-agent/backups/backups/20260926T095858Z-train1/ex/eval/runs"
for tdir in sorted(glob.glob(E + "/**/traces", recursive=True)) + sorted(glob.glob(B + "/h_*/traces")):
    if EXCLUDE.search(tdir + "/"):
        continue
    run_dir = os.path.dirname(tdir)
    run = os.path.basename(run_dir if not run_dir.endswith("/results") else os.path.dirname(run_dir))
    res, rp = load_results(run_dir)
    for f in sorted(glob.glob(tdir + "/trace_*.json")):
        tid = os.path.basename(f)[6:-5]
        r = res.get(tid, {})
        t = json.load(open(f))
        stages, calls, bad, badkinds, quoted, multi, texts_unparsed, nudges = [], 0, 0, collections.Counter(), 0, 0, 0, 0
        pts, cts, models, seq = [], [], set(), []
        prev_pt, prev_author, compactions = None, None, 0
        for s in t["steps"]:
            ex = s.get("extra") or {}
            au = ex.get("author")
            if s.get("source") == "system" and ex.get("event_type") == "continuation_nudge":
                nudges += 1
            if s.get("model_name"):
                models.add(s["model_name"])
            if s.get("source") == "agent":
                if not stages or stages[-1][0] != au:
                    stages.append([au, 0])
                m = s.get("metrics") or {}
                if m.get("prompt_tokens"):
                    pt = m["prompt_tokens"]
                    if prev_pt and au == prev_author and prev_pt > 8000 and pt < 0.7 * prev_pt:
                        compactions += 1
                    prev_pt, prev_author = pt, au
                    pts.append(pt)
                if m.get("completion_tokens"):
                    cts.append(m["completion_tokens"])
                if s.get("tool_calls"):
                    stages[-1][1] += 1
                    if len(s["tool_calls"]) > 1:
                        multi += 1
                    for tc in s["tool_calls"]:
                        calls += 1
                        name, args = tc["function_name"], tc.get("arguments") or {}
                        seq.append((name, json.dumps(args, sort_keys=True)))
                        sch = SCHEMA.get(name)
                        obs = ((s.get("observation") or {}).get("content") or "")
                        kind = None
                        if sch is None:
                            kind = "unknown_tool"
                        elif set(args) - set(sch["props"]):
                            kind = "extra_keys"
                        elif set(sch["required"]) - set(args):
                            kind = "missing_required"
                        elif MISSING.search(obs[:400]):
                            kind = "rejected_by_adk"
                        if kind:
                            bad += 1; badkinds[kind] += 1
                        if any(isinstance(v, str) and len(v) >= 2 and v[0] == v[-1] == '"' for v in args.values()):
                            quoted += 1
                elif (s.get("message") or "") and "<|tool_call>" in (s.get("message") or "") or "call:" in (s.get("message") or "")[:20]:
                    texts_unparsed += 1
        h = hashlib.sha1(json.dumps(seq).encode()).hexdigest()[:12]
        rows.append({"source": source_of(f), "run": run, "bundle": bundle_of(run), "task": tid, "file": f.replace(E + "/", ""),
                     "resolved": bool(r.get("resolved")), "has_result": bool(r), "error": r.get("error") or r.get("err"),
                     "stages": [a for a, _ in stages], "stage_calls": [c for _, c in stages], "calls": calls,
                     "bad_calls": bad, "bad_kinds": dict(badkinds), "quoted_arg_calls": quoted, "multi_call_steps": multi,
                     "unparsed_text_steps": texts_unparsed, "nudges": nudges, "compactions_detected": compactions,
                     "max_prompt": max(pts) if pts else 0, "sum_prompt": sum(pts), "sum_completion": sum(cts),
                     "n_llm_calls": len(pts), "models": sorted(models), "seq_hash": h, "n_steps": len(t["steps"])})
with open(os.path.dirname(os.path.abspath(__file__)) + "/inventory_rows.jsonl", "w") as fo:
    for r in rows:
        fo.write(json.dumps(r) + "\n")
R = [r for r in rows if r["resolved"]]
print("trace files (model runs):", len(rows), " with result:", sum(r["has_result"] for r in rows), " resolved:", len(R),
      " distinct tasks resolved:", len({r["task"] for r in R}), " distinct tasks total:", len({r["task"] for r in rows}))
print("models seen:", collections.Counter(m for r in rows for m in r["models"]))
