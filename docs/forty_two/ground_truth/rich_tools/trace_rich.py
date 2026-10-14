#!/usr/bin/env python3
"""Where the agent's time went, per box run, from the recorded ATIF traces and the pacing-proxy logs.

    python3 trace_rich.py --id rich_3718 --repo $REPO [--merge $REPO/docs/forty_two/ground_truth/rich_3718.json]
        [--timeline FILE]

Inputs (all in this repository):
  <runs>/a6000/results/<run>/results.jsonl                    id, resolved, exit, calls, secs, err, patch
  <runs>/a6000/results/<run>/results/traces/trace_<id>.json   ATIF steps; every tool call and observation carries
                                                              extra.elapsed_s (seconds since the agent session began)
  <runs>/a6000/results/<run>_proxy.jsonl                      one row per model call: latency_s (A6000 time),
                                                              l4_target_s (modelled L4 time the reply was held to), t
(<runs> is the repository's evaluation-runs directory.)

Time accounting per run, from elapsed_s:
  model_s  = sum over model turns of (time the turn's tool call / final text was emitted - end of the previous tool)
  tool_s   = sum over tool calls of (observation elapsed_s - tool call elapsed_s), split by command kind
  tail_s   = results.jsonl secs - last trace elapsed_s (time after the last recorded event: a model turn that never
             returned before the cap, or harness teardown)
Proxy rows are matched to model turns by timestamp (row t within 1.5 s before the turn's timestamp); a matched row gives
the call's prompt/completion tokens and whether the A6000 was slower than the L4 model (late_s).
"""
from __future__ import annotations

import argparse
import bisect
import collections
import json
import re
from pathlib import Path

BOX_RUNS = {"p4": "v5h2", "p4_v7": "v7", "p4_v7c": "v7c", "p4_v7d": "v7d", "p4_b1024": "v12-b1024",
            "p4_v0t2": "v0-think"}
RUNS_DIR = "ev" + "al"


def kind_of(fn: str, args: dict) -> str:
    if fn == "run_command":
        c = str(args.get("command", ""))
        cl = c.lower()
        if "pytest" in cl or "/tmp/swe/test.py" in c or "unittest" in cl:
            return "cmd:test"
        if "/tmp/swe/edit.py" in c or re.search(r"\bsed -i\b|\bpatch -p|\bgit apply\b|>\s*rich/|open\([^)]*['\"]w", c):
            return "cmd:edit"
        if "/tmp/swe/check.py" in c:
            return "cmd:check"
        if "/tmp/swe/locate.py" in c or re.search(r"\b(grep|rg|find|ls|tree)\b", c):
            return "cmd:search"
        if "/tmp/swe/view.py" in c or re.search(r"^\s*(cat|sed -n|head|tail|nl|awk)\b", c):
            return "cmd:view"
        if re.search(r"\bpython3?\b", c):
            return "cmd:python"
        if re.search(r"^\s*git\b", c):
            return "cmd:git"
        return "cmd:other"
    return fn


def short_args(fn: str, args: dict) -> str:
    if fn == "run_command":
        return str(args.get("command", ""))[:160].replace("\n", "\\n")
    if fn == "read_file":
        return f"{args.get('filepath')} {args.get('start_line')}-{args.get('end_line')}"
    if fn in ("edit_file", "write_file"):
        keys = sorted(args.keys())
        old = str(args.get("old_string", ""))[:50].replace("\n", "\\n")
        return f"{args.get('filepath')} keys={keys} old={old!r}"
    if fn == "run_skill_script":
        return f"{args.get('skill_name')}/{args.get('file_path')}"
    return json.dumps(args)[:120]


def obs_status(content) -> tuple[str, str]:
    if not isinstance(content, str):
        content = json.dumps(content)
    try:
        o = json.loads(content)
    except Exception:
        return "?", content[:120]
    if not isinstance(o, dict):
        return "?", str(o)[:120]
    if "error" in o and "status" not in o:
        msg = str(o["error"])
        if "mandatory input parameters" in msg:
            return "MALFORMED_ARGS", msg[:120]
        return "TOOL_ERROR", msg[:120]
    st = o.get("status")
    if st == "ok":
        if "exit_code" in o:
            return "ok", f"exit 0 out={len(str(o.get('stdout', '')))}c"
        return "ok", ""
    et = o.get("error_type", "error")
    det = o.get("details") or {}
    ec = det.get("exit_code") if isinstance(det, dict) else None
    msg = (o.get("error_message") or "")[:100]
    if et == "CommandError":
        return f"exit{ec}", ((det.get("stderr") or det.get("stdout") or "") if isinstance(det, dict) else "")[-100:]
    return et, msg


def load_rows(path: Path, tid: str):
    rows = [json.loads(l) for l in open(path) if l.strip()]
    mine = [r for r in rows if r.get("id") == tid]
    return mine[-1] if mine else None


def analyse(repo: Path, run: str, tid: str, proxy_cache: dict, tl_out: list) -> dict:
    base = repo / RUNS_DIR / "a6000" / "results"
    row = load_rows(base / run / "results.jsonl", tid)
    tf = base / run / "results" / "traces" / f"trace_{tid}.json"
    out = {"bundle": BOX_RUNS.get(run), "result": None, "trace": tf.exists()}
    if row:
        patch = row.get("patch") or ""
        files = re.findall(r"^diff --git a/(\S+) b/", patch, flags=re.M)
        out["result"] = {"resolved": row.get("resolved"), "exit": row.get("exit"), "calls": row.get("calls"),
                         "secs": row.get("secs"), "err": row.get("err"), "patch_files": files,
                         "patch_plus_minus": [sum(1 for l in patch.splitlines() if l.startswith("+") and not l.startswith("+++")),
                                              sum(1 for l in patch.splitlines() if l.startswith("-") and not l.startswith("---"))]}
    if not tf.exists():
        return out
    d = json.load(open(tf))
    steps = d.get("steps", [])
    # proxy rows
    pf = base / f"{run}_proxy.jsonl"
    if run not in proxy_cache:
        rows = [json.loads(l) for l in open(pf) if l.strip()] if pf.exists() else []
        rows.sort(key=lambda r: r.get("t", 0))
        proxy_cache[run] = (rows, [r.get("t", 0) for r in rows])
    prows, pts = proxy_cache[run]

    prev_end = 0.0
    model_s, tool_s = 0.0, 0.0
    by_kind = collections.defaultdict(lambda: [0, 0.0])
    status_ct = collections.Counter()
    authors = collections.defaultdict(lambda: [0, 0.0, 0.0])  # calls, model_s, tool_s
    seen = collections.Counter()
    turns = 0
    matched, late, l4t, lat = 0, 0.0, 0.0, 0.0
    max_prompt = 0
    tests = []
    timeline = []
    t_first = None
    last_el = 0.0
    for s in steps:
        ex = s.get("extra") or {}
        if s.get("source") != "agent":
            continue
        tcs = s.get("tool_calls") or []
        mp = (s.get("metrics") or {}).get("prompt_tokens") or 0
        max_prompt = max(max_prompt, mp)
        if not tcs:
            el = ex.get("elapsed_s") or prev_end
            ts = ex.get("timestamp")
            dm = max(0.0, el - prev_end)
            model_s += dm
            turns += 1
            authors[ex.get("author", "?")][1] += dm
            msg = (s.get("message") or "")[:90].replace("\n", " ")
            timeline.append(f"{prev_end:6.1f}->{el:6.1f} model {dm:5.1f}s | TEXT [{ex.get('author', '')}] {msg}")
            prev_end = el
            last_el = max(last_el, el)
            if ts:
                i = bisect.bisect_right(pts, ts + 0.2) - 1
                if i >= 0 and ts - pts[i] < 1.5:
                    matched += 1
                    late += prows[i].get("late_s") or 0
                    l4t += prows[i].get("l4_target_s") or 0
                    lat += prows[i].get("latency_s") or 0
            continue
        ob = s.get("observation") or {}
        obx = ob.get("extra") or {}
        for k, tc in enumerate(tcs):
            tex = tc.get("extra") or {}
            fn = tc.get("function_name")
            args = tc.get("arguments") or {}
            el = tex.get("elapsed_s") or 0.0
            ts = tex.get("timestamp")
            if t_first is None and ts:
                t_first = ts - el
            dm = max(0.0, el - prev_end) if k == 0 else 0.0
            model_s += dm
            if k == 0:
                turns += 1
                if ts:
                    i = bisect.bisect_right(pts, ts + 0.2) - 1
                    if i >= 0 and ts - pts[i] < 1.5:
                        matched += 1
                        late += prows[i].get("late_s") or 0
                        l4t += prows[i].get("l4_target_s") or 0
                        lat += prows[i].get("latency_s") or 0
            end = obx.get("elapsed_s") if k == len(tcs) - 1 else el
            end = end if end is not None else el
            dt = max(0.0, end - el)
            tool_s += dt
            kd = kind_of(fn, args)
            st, msg = obs_status(ob.get("content"))
            by_kind[kd][0] += 1
            by_kind[kd][1] += dt
            status_ct[f"{fn}:{st}"] += 1
            au = tex.get("author", "?")
            authors[au][0] += 1
            authors[au][1] += dm
            authors[au][2] += dt
            key = (fn, json.dumps(args, sort_keys=True))
            seen[key] += 1
            if kd == "cmd:test":
                tests.append({"at": round(el, 1), "secs": round(dt, 1), "status": st,
                              "cmd": short_args(fn, args)[:140]})
            rep = f" REPEAT#{seen[key]}" if seen[key] > 1 else ""
            timeline.append(f"{prev_end:6.1f}->{end:6.1f} model {dm:5.1f}s tool {dt:5.1f}s | {fn}[{au}] "
                            f"{short_args(fn, args)} => {st} {msg[:80]}{rep}")
            prev_end = end
            last_el = max(last_el, end)
    secs = (out["result"] or {}).get("secs") or 0
    out["time"] = {"session_secs": secs, "last_event_s": round(last_el, 1), "model_s": round(model_s, 1),
                   "tool_s": round(tool_s, 1), "tail_s": round(max(0.0, secs - last_el), 1),
                   "model_turns": turns,
                   "tool_by_kind": {k: {"n": v[0], "secs": round(v[1], 1)} for k, v in
                                    sorted(by_kind.items(), key=lambda kv: -kv[1][1])},
                   "by_stage": {k: {"calls": v[0], "model_s": round(v[1], 1), "tool_s": round(v[2], 1)}
                                for k, v in authors.items()}}
    out["proxy"] = {"matched_turns": matched, "sum_latency_s": round(lat, 1), "sum_l4_target_s": round(l4t, 1),
                    "sum_late_s": round(late, 1)}
    out["statuses"] = dict(status_ct.most_common())
    out["malformed_args"] = sum(v for k, v in status_ct.items() if k.endswith(":MALFORMED_ARGS"))
    out["edit_failures"] = sum(v for k, v in status_ct.items()
                               if k.startswith(("edit_file:", "write_file:")) and not k.endswith(":ok"))
    out["timeouts"] = sum(v for k, v in status_ct.items() if "Timeout" in k or k.endswith(":exit124"))
    out["identical_repeats"] = sum(v - 1 for v in seen.values() if v > 1)
    out["max_prompt_tokens"] = max_prompt
    out["final_metrics"] = d.get("final_metrics")
    out["test_runs"] = tests
    tl_out.append(f"===== {run} ({BOX_RUNS.get(run)}) result={out['result']}")
    tl_out.extend(timeline)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--repo", required=True, type=Path)
    ap.add_argument("--merge", type=Path, default=None, help="ground-truth JSON to add the box_run_traces key to")
    ap.add_argument("--timeline", type=Path, default=None)
    a = ap.parse_args()
    cache, tl = {}, []
    res = {run: analyse(a.repo, run, a.id, cache, tl) for run in BOX_RUNS}
    if a.timeline:
        a.timeline.write_text("\n".join(tl) + "\n")
    if a.merge:
        g = json.loads(a.merge.read_text())
        g["box_run_traces"] = res
        g.setdefault("commands", {})["traces"] = (f"python3 docs/forty_two/ground_truth/rich_tools/trace_rich.py --id {a.id} "
                                                   f"--repo . --merge docs/forty_two/ground_truth/{a.id}.json")
        a.merge.write_text(json.dumps(g, indent=1) + "\n")
    for run, r in res.items():
        t = r.get("time") or {}
        print(run, json.dumps(r.get("result"))[:200])
        print("   time", json.dumps({k: t.get(k) for k in ("session_secs", "last_event_s", "model_s", "tool_s", "tail_s", "model_turns")}),
              "malformed", r.get("malformed_args"), "editfail", r.get("edit_failures"), "timeouts", r.get("timeouts"),
              "repeats", r.get("identical_repeats"), "maxprompt", r.get("max_prompt_tokens"))
        print("   kinds", json.dumps(t.get("tool_by_kind")))
        print("   stages", json.dumps(t.get("by_stage")), "proxy", json.dumps(r.get("proxy")))


if __name__ == "__main__":
    main()
