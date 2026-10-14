#!/usr/bin/env python3
"""Where a recorded run's 300 s went, from its ATIF trace and (box runs) the per-model-call proxy log.

    python3 docs/forty_two/ground_truth/fastapi_tools/tr_fastapi.py TASK_ID [--json OUT] [--steps]

Sources, per run:
  box   eval/a6000/results/<run>/results.jsonl (t = end time, secs = agent seconds), .../results/traces/trace_<id>.json,
        eval/a6000/results/<run>_proxy.jsonl (latency_s and completion time t of every model call; no task id, so a call
        belongs to the task whose window [t_end - secs - 1, t_end + 1] holds its completion time).
  L4    eval/kaggle/<run>/results/traces/trace_<id>.json where present (e74_v2, e74_v3); no proxy log there, so only
        step-to-step gaps (model + tool together) are available.

Method (MEASURED from those files): model seconds = sum of proxy latency_s in the window. A step's tool runtime = start
of the next model call (proxy t - latency_s) minus the step's timestamp (the trace stamps a tool call when the model's
reply arrives). "other" = window - model - tools (harness turn overhead, gaps before the first call, compaction).
Command kinds are a regex classification of run_command strings (see kind()).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BOX_RUNS = ["p4", "p4_v7", "p4_v7c", "p4_v7d", "p4_b1024", "p4_v0t2"]
BUNDLE = {"p4": "v5h2", "p4_v7": "v7", "p4_v7c": "v7c", "p4_v7d": "v7d", "p4_b1024": "v12-b1024", "p4_v0t2": "v0-think"}
L4_TRACE_RUNS = ["e74_v2", "e74_v3"]


def kind(fn, args):
    if fn == "run_command":
        c = (args.get("command") or "").strip()
        lc = c.lower()
        if "/tmp/swe/" in c or re.search(r"\b(locate|view|check|repro|verify)\.py\b", c) and "/tmp/" in c:
            return "helper"
        if re.search(r"(^|[\n;&|(]\s*)(timeout\s+\d+\s+)?(\S+=\S+\s+)*(python3?\s+-m\s+)?(pytest|unittest|tox)\b", lc):
            return "test"
        if re.match(r"(cat|tee)\s*>+\s*/tmp/", c) and re.search(r"\bpython3?\b", c):
            return "python"     # scratch script written to /tmp and run in the same command
        if re.search(r"(^|\s)sed\s+-i|perl\s+-[a-z]*i|\bcat\s*>|>\s*\S+\.py\b|\btee\b|\bpatch\s+-p", c):
            return "edit_shell"
        if re.match(r"^(timeout\s+\d+\s+)?(\S+=\S+\s+)*(cd \S+ && )?(timeout\s+\d+\s+)?python3?\b", c):
            return "python"
        if re.search(r"^(cd \S+ && )?(git\s+grep|grep|rg|find|ls|tree|git\s+ls-files|ack)\b", c):
            return "search"
        if re.search(r"^(cd \S+ && )?(cat|sed\s+-n|head|tail|nl|awk|wc|less)\b", c):
            return "read"
        if re.search(r"^(cd \S+ && )?git\b", c):
            return "git"
        return "other_shell"
    return {"read_file": "read", "edit_file": "edit", "write_file": "edit", "get_status": "meta", "submit_patch": "meta",
            "run_skill_script": "helper", "transfer_to_agent": "meta", "get_code_neighbors": "graph",
            "search_similar_code": "graph", "get_code_subgraph": "graph"}.get(fn, "subagent" if "agent" in fn or "analyzer" in fn else fn)


def short(x, n=110):
    s = x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)
    s = s.replace("\n", "\\n")
    return s if len(s) <= n else s[:n] + "..."


def obs_summary(obs):
    content = (obs or {}).get("content")
    try:
        o = json.loads(content) if isinstance(content, str) else (content or {})
    except Exception:
        return "raw", short(content or "", 120)
    if not isinstance(o, dict):
        return "raw", short(o, 120)
    st = o.get("status") or ("error" if o.get("error") else "ok")
    if st == "error":
        d = o.get("details") or {}
        msg = o.get("error_type", "") + ":" + str(d.get("exit_code", "")) + " " + (o.get("error_message") or o.get("error") or "")
        tail = (d.get("stderr") or d.get("stdout") or "")
        return "error", short(msg + " | " + tail[-160:], 200)
    if "exit_code" in o:
        out = (o.get("stdout") or "") + (o.get("stderr") or "")
        return "ok", short(f"exit={o.get('exit_code')} " + out[-160:], 200)
    if "occurrences" in o:
        return "ok", f"edit ok ({o.get('strategy')})"
    if "content" in o and "filepath" in o:
        return "ok", f"read {o.get('filepath')} {o.get('start_line')}-{o.get('end_line')}/{o.get('total_lines')}"
    return "ok", short(o, 160)


def load_row(path, tid):
    for line in open(path):
        if line.strip():
            x = json.loads(line)
            if (x.get("id") or x.get("instance_id")) == tid:
                return x
    return None


def analyse(tid, run, box=True):
    base = ROOT / "eval" / ("a6000/results" if box else "kaggle") / run
    row = load_row(base / "results.jsonl", tid)
    tp = base / "results" / "traces" / f"trace_{tid}.json"
    if row is None or not tp.exists():
        return None
    trace = json.load(open(tp))
    end, secs = row["t"] if "t" in row else None, row["secs"]
    start = end - secs if end else None
    proxy, overlap_prev, matched = [], [], set()
    if box:
        pp = ROOT / "eval" / "a6000" / "results" / f"{run}_proxy.jsonl"
        for line in open(pp):
            p = json.loads(line)
            if start - 1 <= p["t"] - p["latency_s"] and p["t"] <= end + 1:
                proxy.append(p)
            elif p["t"] - p["latency_s"] < start - 1 and p["t"] > start:   # the previous task's call still in flight
                overlap_prev.append(round(p["t"] - start, 1))
        proxy.sort(key=lambda p: p["t"])
    pstarts = [p["t"] - p["latency_s"] for p in proxy]
    steps = []
    for s in trace["steps"]:
        if s.get("source") != "agent":
            continue
        ex = s.get("extra") or {}
        tcs = s.get("tool_calls") or []
        ts = None
        if tcs:
            ts = (tcs[0].get("extra") or {}).get("timestamp")
        ts = ts or ex.get("timestamp")
        if ts is None:
            continue
        steps.append((ts, s, tcs, ex))
    if start is None and steps:
        start = steps[0][0]
    out_steps = []
    tool_by_kind = defaultdict(float)
    n_by_kind = Counter()
    err_by_tool = Counter()
    calls = Counter()
    pytest_runs, edits, edit_fail = [], [], 0
    prev_ts = start
    for ts, s, tcs, ex in steps:
        # model call that produced this step: the latest proxy completion at or before ts (+0.5 s)
        lat = None
        if proxy:
            cands = [(i, p) for i, p in enumerate(proxy) if ts - 4 <= p["t"] <= ts + 0.5 and i not in matched]
            if cands:
                i, best = min(cands, key=lambda ip: abs(ip[1]["t"] - ts))
                matched.add(i)
                lat = round(best["latency_s"], 2)
        tool_s = None
        if tcs and proxy:
            nxt = [ps for ps in pstarts if ps >= ts - 0.05]
            tool_s = round((min(nxt) if nxt else end) - ts, 2)
        elif tcs and not box:
            tool_s = None
        rec = {"t": round(ts - start, 1), "author": ex.get("author") or (tcs[0].get("extra") or {}).get("author") if tcs else ex.get("author"),
               "model_s": lat, "gap_s": round(ts - prev_ts, 1), "tool_s": tool_s,
               "completion_tokens": (s.get("metrics") or {}).get("completion_tokens")}
        prev_ts = ts
        if not tcs:
            rec["text"] = short(s.get("message") or "", 140)
            out_steps.append(rec)
            continue
        obs = s.get("observation") or {}
        st, summ = obs_summary(obs)
        names = []
        for tc in tcs:
            fn, args = tc["function_name"], tc.get("arguments") or {}
            k = kind(fn, args)
            names.append(f"{fn}[{k}] {short(args.get('command') if fn == 'run_command' else args, 150)}")
            calls[(fn, json.dumps(args, sort_keys=True))] += 1
            n_by_kind[k] += 1
            if tool_s is not None:
                tool_by_kind[k] += tool_s / len(tcs)
            if st == "error":
                err_by_tool[fn] += 1
            if fn == "edit_file" or fn == "write_file":
                if st == "error":
                    edit_fail += 1
                else:
                    edits.append(args.get("filepath"))
            if k == "test":
                pytest_runs.append({"t": rec["t"], "cmd": short(args.get("command"), 160), "tool_s": tool_s, "result": summ})
        rec["call"] = " || ".join(names)
        rec["status"] = st
        rec["result"] = summ
        out_steps.append(rec)
    model_s = round(sum(p["latency_s"] for p in proxy), 1) if proxy else None
    # model calls with no step of their own: ADK events compaction (a summariser call; the next prompt is much smaller)
    # or a reply the harness dropped. Listed with their start time, latency and token counts.
    unmatched = []
    for i, p in enumerate(proxy):
        if i in matched:
            continue
        nxt = proxy[i + 1]["prompt"] if i + 1 < len(proxy) else None
        prv = max((q["prompt"] for q in proxy[:i]), default=0)
        unmatched.append({"start": round(p["t"] - p["latency_s"] - start, 1), "latency_s": round(p["latency_s"], 1),
                          "prompt": p["prompt"], "completion": p["completion"],
                          "compaction_like": bool(nxt is not None and prv and nxt < 0.6 * prv)})
    tools_s = round(sum(tool_by_kind.values()), 1) if proxy else None
    repeats = {k[0] + " " + short(k[1], 100): v for k, v in calls.items() if v >= 2}
    patch = row.get("patch") or ""
    pfiles = re.findall(r"^\+\+\+ b/(\S+)", patch, re.M)
    return {
        "run": run, "bundle": BUNDLE.get(run, run), "resolved": row.get("resolved"), "exit": row.get("exit"),
        "calls": row.get("calls"), "secs": secs, "err": row.get("err"), "patch_chars": len(patch), "patch_files": pfiles,
        "model_calls": len(proxy) if proxy else None, "model_s": model_s, "tools_s": tools_s,
        "other_s": round(secs - model_s - tools_s, 1) if proxy else None,
        "tool_s_by_kind": {k: round(v, 1) for k, v in sorted(tool_by_kind.items(), key=lambda kv: -kv[1])},
        "n_by_kind": dict(n_by_kind.most_common()),
        "unmatched_model_calls": unmatched if proxy else None,
        "unmatched_model_s": round(sum(u["latency_s"] for u in unmatched), 1) if proxy else None,
        "prev_task_call_in_flight_until_s": overlap_prev,
        "prompt_tokens_max":max((p["prompt"] for p in proxy), default=None) if proxy else None,
        "completion_tokens_sum": sum(p["completion"] for p in proxy) if proxy else None,
        "slowest_model_calls_s": sorted((round(p["latency_s"], 1) for p in proxy), reverse=True)[:5] if proxy else None,
        "errors_by_tool": dict(err_by_tool), "edit_failures": edit_fail, "files_edited_ok": sorted(set(e for e in edits if e)),
        "repeated_identical_calls": repeats, "test_runs": pytest_runs, "steps": out_steps,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tid")
    ap.add_argument("--json")
    ap.add_argument("--steps", action="store_true")
    a = ap.parse_args()
    res = {}
    for r in BOX_RUNS:
        x = analyse(a.tid, r, box=True)
        if x:
            res[r] = x
    for r in L4_TRACE_RUNS:
        x = analyse(a.tid, r, box=False)
        if x:
            res["l4:" + r] = x
    if a.json:
        Path(a.json).write_text(json.dumps({"id": a.tid, "generator": "docs/forty_two/ground_truth/fastapi_tools/tr_fastapi.py",
                                            "runs": res}, indent=1) + "\n")
    for r, x in res.items():
        print(f"=== {r} ({x['bundle']}) resolved={x['resolved']} exit={x['exit']} calls={x['calls']} secs={x['secs']} err={x['err']}")
        print(f"    model {x['model_s']}s in {x['model_calls']} calls | tools {x['tools_s']}s {x['tool_s_by_kind']} | other {x['other_s']}s"
              f" | max prompt {x['prompt_tokens_max']} | completion sum {x['completion_tokens_sum']} | slowest {x['slowest_model_calls_s']}")
        print(f"    kinds {x['n_by_kind']} | errors {x['errors_by_tool']} | edit fails {x['edit_failures']} | edited {x['files_edited_ok']}"
              f" | patch {x['patch_chars']} chars {x['patch_files']}")
        if x.get("unmatched_model_calls"):
            print(f"    unmatched model calls {x['unmatched_model_s']}s {x['unmatched_model_calls']}")
        if x.get("prev_task_call_in_flight_until_s"):
            print(f"    previous task's model call still running until t={x['prev_task_call_in_flight_until_s']}")
        if x["repeated_identical_calls"]:
            print(f"    repeats {x['repeated_identical_calls']}")
        for tr in x["test_runs"]:
            print(f"    TEST t={tr['t']} {tr['tool_s']}s {tr['cmd']} -> {tr['result']}")
        if a.steps:
            for s in x["steps"]:
                if "call" in s:
                    print(f"      t={s['t']:>6} m={s['model_s']} tool={s['tool_s']} [{s['author']}] {s['call']}\n               -> {s['status']}: {s['result']}")
                else:
                    print(f"      t={s['t']:>6} m={s['model_s']} [{s['author']}] TEXT {s['text']}")


if __name__ == "__main__":
    main()
