#!/usr/bin/env python3
"""Aggregate time sinks over the batch's trace-timing files (box runs only: they carry proxy latencies).

    python3 docs/forty_two/ground_truth/fastapi_tools/sinks_fastapi.py [--per-run]

Categories (a step can count in more than one; seconds are model latency unless noted):
  repeat_identical   steps whose call string (tool + first 150 chars of arguments) AND reply summary equal an earlier step's;
                     model s + tool s of the repeats
  dropped_args       tool replies "mandatory input parameters are not present" (the parser lost an argument); model s
  long_call_30s      model calls of 30 s or more (stepped and unmatched); their full latency
  compaction         unmatched model calls flagged compaction_like (the next prompt is < 60% of the largest so far)
  cmd_timeout        tool runtimes of 170 s or more (the 180 s per-command limit), tool s
  cap_tail           time after the last logged step when the session cap cut a call or command off (tail_s)
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
IDS = ["requests_6644", "fastapi_14616", "fastapi_9753", "fastapi_14419", "fastapi_13920", "fastapi_14258",
       "fastapi_14306", "fastapi_14448", "fastapi_14479", "fastapi_14487", "fastapi_14986", "fastapi_15280",
       "fastapi_15588", "fastapi_15661", "fastapi_15800"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-run", action="store_true")
    a = ap.parse_args()
    tot = defaultdict(float)
    cnt = defaultdict(int)
    runs_with = defaultdict(set)
    by_bundle = defaultdict(lambda: defaultdict(float))
    agent_s = model_s = tools_s = 0.0
    n = 0
    for tid in IDS:
        d = json.load(open(HERE / "trace_timing" / f"{tid}.json"))
        for run, x in d["runs"].items():
            if run.startswith("l4:"):
                continue
            n += 1
            agent_s += x["secs"]
            model_s += x["model_s"] or 0
            tools_s += x["tools_s"] or 0
            seen = set()
            row = defaultdict(float)
            for s in x["steps"]:
                c = s.get("call")
                if c:
                    key = (c, s.get("result"))   # same call AND same reply: no new information
                    if key in seen:
                        row["repeat_identical"] += (s["model_s"] or 0) + (s["tool_s"] or 0)
                        cnt["repeat_identical"] += 1
                    seen.add(key)
                    if "mandatory input parameters are not present" in (s.get("result") or ""):
                        row["dropped_args"] += s["model_s"] or 0
                        cnt["dropped_args"] += 1
                    if (s["tool_s"] or 0) >= 170:
                        row["cmd_timeout"] += s["tool_s"]
                        cnt["cmd_timeout"] += 1
                if (s["model_s"] or 0) >= 30:
                    row["long_call_30s"] += s["model_s"]
                    cnt["long_call_30s"] += 1
            for u in x.get("unmatched_model_calls") or []:
                if u["latency_s"] >= 30:
                    row["long_call_30s"] += u["latency_s"]
                    cnt["long_call_30s"] += 1
                if u["compaction_like"]:
                    row["compaction"] += u["latency_s"]
                    cnt["compaction"] += 1
            if x.get("tail_s"):
                row["cap_tail"] += x["tail_s"]
                cnt["cap_tail"] += 1
            for k, v in row.items():
                tot[k] += v
                by_bundle[x["bundle"]][k] += v
                if v > 0:
                    runs_with[k].add(f"{tid}:{run}")
            if a.per_run:
                print(tid, run, {k: round(v, 1) for k, v in row.items()})
    print(f"box runs: {n}, agent seconds {agent_s:.1f}, model seconds {model_s:.1f} ({100 * model_s / agent_s:.1f}%), "
          f"tool seconds {tools_s:.1f} ({100 * tools_s / agent_s:.1f}%)")
    for k in sorted(tot, key=lambda k: -tot[k]):
        print(f"  {k:18s} {tot[k]:8.1f} s  ({100 * tot[k] / agent_s:4.1f}% of agent time)  events {cnt[k]:4d}  runs {len(runs_with[k]):3d}")
    print("by bundle:")
    for b, row in sorted(by_bundle.items()):
        print("  ", b, {k: round(v, 1) for k, v in sorted(row.items(), key=lambda kv: -kv[1])})


if __name__ == "__main__":
    main()
