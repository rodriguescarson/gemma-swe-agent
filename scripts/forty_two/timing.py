"""Where a box task's 5 minutes go: traces joined with the pace proxy's per-call log, by time.

    python scripts/forty_two/timing.py RUN_DIR PROXY_LOG [--ids FILE] [--json OUT] [--table]

RUN_DIR = eval/a6000/results/<run> (results.jsonl + results/traces/trace_<id>.json); PROXY_LOG = eval/a6000/results/<run>_proxy.jsonl.

Clock: every trace step carries the epoch `timestamp` at which its model call returned (agent steps) or its tool returned
(observation.extra.timestamp). The agent budget starts at the task_prompt step. A model call k returns at E_k; its tools run
E_k -> O_k; the next call starts at O_k. The pace proxy (scripts/a6000/pace_proxy.py) writes one row per model call at the moment it
answers, after holding the reply to the modelled Kaggle-L4 time (scripts/golden/router.py l4_model_s: 0.102 + 0.02815 x completion
+ 0.000921 x uncached prompt). A proxy row with no trace call of the same (prompt, completion) tokens inside the agent window is one
of two things: an ADK compaction summary (google/adk/apps/compaction.py: when the last prompt reached token_threshold 14,336 the
next model call is preceded by an LlmEventSummarizer call; it shows only text parts, never tool results) when it lies before the
last traced call, or a call cut by the 5-minute cap when it lies after the last traced event.

Per task: model seconds (split by the L4 model into fixed / prefill / decode, plus box lateness), compaction calls and seconds,
tool seconds by tool and by shell-command kind, harness gaps, the tail after the last tool result, repeated identical calls
(any earlier / immediately previous) and their seconds, re-reads after a compaction, sandbox command timeouts, and an estimate of
thinking vs visible output tokens (completion tokens split by the characters of the thought vs the visible text + tool arguments
of the same call; ESTIMATE, the proxy does not log the split)."""
from __future__ import annotations

import argparse
import collections
import json
import re
import statistics
from pathlib import Path

L4_A, L4_B, L4_C = 0.102, 0.02815, 0.000921   # scripts/golden/router.py (time_model sect. 2)
CAP_S = 300.0

PYTEST_RE = re.compile(r"\bpytest\b|-m\s+unittest\b")
SEARCH_RE = re.compile(r"^\s*(git\s+grep|grep|rg|egrep|find|ls|tree|fd)\b")
VIEW_RE = re.compile(r"^\s*(cat|sed|head|tail|nl|awk|less|more|wc)\b")
PY_RE = re.compile(r"^\s*(cd\s+\S+\s*&&\s*)?(timeout\s+\d+\S*\s+)?(PYTHONPATH=\S+\s+)?python3?\b")
PIP_RE = re.compile(r"\bpip3?\s+(install|list|show|freeze)\b|-m\s+pip\b")
GIT_RE = re.compile(r"^\s*git\s+(diff|status|log|show|stash|checkout|restore|reset|apply|add)\b")


def command_kind(cmd: str) -> str:
    """Kind of one run_command string. pytest is targeted when it names a test file, a node id or a -k filter."""
    c = cmd.strip()
    if PIP_RE.search(c):
        return "pip"
    if PYTEST_RE.search(c):
        targeted = re.search(r"(\S+\.py\b|::|\s-k\s)", c)
        return "pytest_targeted" if targeted else "pytest_full"
    if PY_RE.search(c):
        return "python_run"
    if SEARCH_RE.search(c) or re.search(r"\|\s*grep\b", c) and re.match(r"^\s*(git\s+grep|grep|find|ls)", c):
        return "search"
    if VIEW_RE.search(c):
        return "view"
    if GIT_RE.search(c):
        return "git"
    return "other"


def tool_kind(name: str, args: dict) -> str:
    if name == "run_command":
        return "run_command:" + command_kind(str((args or {}).get("command") or ""))
    return name


def _usage(steps):
    for s in steps:
        m = s.get("metrics")
        if m and m.get("prompt_tokens") is not None:
            return int(m.get("prompt_tokens") or 0), int(m.get("completion_tokens") or 0)
    for s in steps:
        for c in s.get("tool_calls") or []:
            u = (c.get("extra") or {}).get("usage")
            if u:
                return int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0)
    return None


def model_calls(trace: dict) -> tuple[float, list[dict]]:
    """(agent start epoch, calls in order). A call = the agent steps that share one return timestamp."""
    steps = trace.get("steps") or []
    t0 = None
    for s in steps:
        if (s.get("extra") or {}).get("event_type") == "task_prompt":
            t0 = float(s["extra"]["timestamp"])
            break
    if t0 is None:
        t0 = min(float((s.get("extra") or {}).get("timestamp") or 0) for s in steps if (s.get("extra") or {}).get("timestamp"))
    groups: dict = collections.OrderedDict()
    for s in steps:
        ex = s.get("extra") or {}
        if s.get("source") != "agent" or ex.get("timestamp") is None:
            continue
        groups.setdefault(float(ex["timestamp"]), []).append(s)
    calls = []
    for ts, ss in groups.items():
        think = "".join(str(s.get("message") or "") for s in ss if (s.get("extra") or {}).get("event_type") == "thinking")
        text = "".join(str(s.get("message") or "") for s in ss if (s.get("extra") or {}).get("event_type") != "thinking")
        tools = []
        for s in ss:
            for c in s.get("tool_calls") or []:
                ob = s.get("observation") or {}
                oex = ob.get("extra") or {}
                end = float(oex.get("timestamp") or (c.get("extra") or {}).get("timestamp") or ts)
                tools.append({"name": c.get("function_name"), "args": c.get("arguments") or {},
                              "start": float((c.get("extra") or {}).get("timestamp") or ts), "end": end,
                              "obs": str(ob.get("content") or ""), "has_obs": bool(ob)})
        u = _usage(ss)
        args_chars = sum(len(json.dumps(t["args"])) for t in tools)
        calls.append({"ts": ts, "rel": ts - t0, "usage": u, "think_chars": len(think), "text_chars": len(text) + args_chars,
                      "tools": tools})
    return t0, calls


def proxy_window(rows: list[dict], t_from: float, t_to: float) -> list[dict]:
    return [r for r in rows if r.get("status") == 200 and t_from <= float(r["t"]) <= t_to]


def dur(row: dict) -> float:
    return max(float(row.get("latency_s") or 0), float(row.get("l4_target_s") or 0))


def obs_error(obs: str) -> str | None:
    m = re.search(r'"error_type":\s*"(\w+)"', obs or "")
    return m.group(1) if m else None


def analyse_task(row: dict, trace: dict, proxy: list[dict]) -> dict:
    t0, calls = model_calls(trace)
    capped = row.get("exit") == -1 or "session timeout" in str(row.get("err") or "").lower()   # exit 124 alone = verification hang
    last_event = max([c["ts"] for c in calls] + [t["end"] for c in calls for t in c["tools"]] + [t0])
    agent_s = CAP_S if capped else max(0.0, last_event - t0)
    untraced_end = False
    rt = row.get("t")
    if not capped and rt and row.get("exit") != 124 and float(rt) - t0 - agent_s > 12.0:
        # the row was written long after the last traced event: the run went on past it (a post-invocation compaction summary
        # or a call cut by the cap); verification takes ~4-6 s on the box
        agent_s = min(CAP_S, float(rt) - t0 - 5.0); untraced_end = True
    t_end = t0 + agent_s
    prox = proxy_window(proxy, t0 - 0.5, t_end + 60.0 if (capped or untraced_end) else last_event + 0.5)
    # match proxy rows to traced calls on (prompt, completion) and time
    used = set()
    for c in calls:
        c["proxy"] = None
        if not c["usage"]:
            continue
        best = None
        for i, r in enumerate(prox):
            if i in used or (r.get("prompt"), r.get("completion")) != c["usage"]:
                continue
            d = abs(float(r["t"]) - c["ts"])
            if d < 3.0 and (best is None or d < best[0]):
                best = (d, i)
        if best:
            used.add(best[1]); c["proxy"] = prox[best[1]]
    last_call_ts = max([c["ts"] for c in calls] + [t0])
    compactions, cut, spill = [], [], []
    for i, r in enumerate(prox):
        if i in used:
            continue
        if float(r["t"]) - dur(r) < t0 - 0.5:
            spill.append(r)          # started before this task: the previous task's call cut by its cap, answered late
        elif float(r["t"]) <= last_call_ts + 0.5:
            compactions.append(r)
        else:
            cut.append(r)
    cut = [r for r in cut if float(r["t"]) - dur(r) < t_end]          # started inside the window
    # time attribution
    comp_s = sum(dur(r) for r in compactions)
    model = dict(fixed=0.0, prefill=0.0, decode=0.0, late=0.0, unpaced=0.0)
    tok = dict(prompt=0, completion=0, uncached=0, think_est=0.0, visible_est=0.0)
    gaps = 0.0
    prev_end, prev_p, prev_c = t0, 0, 0
    tools_s = collections.Counter(); tools_n = collections.Counter(); timeouts = 0
    seen, prev_sig, rep_any_n, rep_any_s, rep_cons_n, rep_cons_s = {}, None, 0, 0.0, 0, 0.0
    reads_before, rereads_after_comp_n, rereads_after_comp_s = set(), 0, 0.0
    errors = collections.Counter()
    open_at_cap = 0
    comp_times = sorted(float(r["t"]) for r in compactions)
    per_call = []
    for c in calls:
        interval = c["ts"] - prev_end
        comp_in = sum(dur(r) for r in compactions if prev_end - 0.5 <= float(r["t"]) <= c["ts"] + 0.5)
        if c["proxy"]:
            d = dur(c["proxy"])
            p, k = c["usage"]
            unc = p if p < prev_p else p - prev_p - prev_c
            unc = max(0, unc)
            model["fixed"] += L4_A; model["prefill"] += L4_C * unc; model["decode"] += L4_B * k
            model["late"] += max(0.0, float(c["proxy"].get("latency_s") or 0) - float(c["proxy"].get("l4_target_s") or 0))
            tok["prompt"] += p; tok["completion"] += k; tok["uncached"] += unc
            share = c["think_chars"] / (c["think_chars"] + c["text_chars"]) if (c["think_chars"] + c["text_chars"]) else 0.0
            tok["think_est"] += k * share; tok["visible_est"] += k * (1 - share)
            prev_p, prev_c = p, k
            gaps += max(0.0, interval - d - comp_in)
            call_model_s = d
        else:
            model["unpaced"] += max(0.0, interval - comp_in)
            call_model_s = max(0.0, interval - comp_in)
        call_tool_s = 0.0
        for t in c["tools"]:
            if capped and c is calls[-1] and not t.get("has_obs", True) and t["name"] not in ("submit_patch", "get_status"):
                t["end"] = t_end; open_at_cap += 1    # still running when the cap fired: the trace never got its observation
            ts = max(0.0, min(t["end"], t_end) - t["start"])
            kind = tool_kind(t["name"], t["args"])
            tools_s[kind] += ts; tools_n[kind] += 1; call_tool_s += ts
            e = obs_error(t["obs"])
            if e:
                errors[e] += 1
            if e == "TimeoutExceeded" or "TimeoutExceeded" in t["obs"][:300] or (capped and not t.get("has_obs", True) and ts > 30):
                timeouts += 1
            sig = json.dumps([t["name"], t["args"]], sort_keys=True)
            cost = call_model_s + ts
            if sig in seen:
                rep_any_n += 1; rep_any_s += cost
            if sig == prev_sig:
                rep_cons_n += 1; rep_cons_s += cost
            seen[sig] = seen.get(sig, 0) + 1; prev_sig = sig
            path = None
            if t["name"] == "read_file":
                path = str(t["args"].get("filepath") or "")
            elif t["name"] == "run_command" and command_kind(str(t["args"].get("command") or "")) == "view":
                m = re.search(r"(\S+\.\w+)\s*$", str(t["args"].get("command") or ""))
                path = m.group(1) if m else None
            if path:
                if path in reads_before and any(ct < t["start"] for ct in comp_times):
                    rereads_after_comp_n += 1; rereads_after_comp_s += cost
                reads_before.add(path)
        per_call.append({"rel": round(c["rel"], 2), "model_s": round(call_model_s, 2), "tool_s": round(call_tool_s, 2),
                         "usage": c["usage"], "tools": [tool_kind(t["name"], t["args"]) for t in c["tools"]]})
        prev_end = max([c["ts"]] + [t["end"] for t in c["tools"]])
    tail = max(0.0, t_end - prev_end)
    cut_s = sum(min(dur(r), max(0.0, t_end - (float(r["t"]) - dur(r)))) for r in cut)
    n_tool = sum(tools_n.values())
    paced_model_s = sum(dur(c["proxy"]) for c in calls if c["proxy"])
    return {
        "id": row["id"], "resolved": bool(row.get("resolved")), "exit": row.get("exit"), "capped": capped,
        "untraced_end": untraced_end,
        "setup_s": round(t0 - (float(rt) - float(row.get("secs") or 0)), 1) if rt else None,
        "post_s": round(float(rt) - t_end, 1) if rt else None,
        "patch_empty": not (row.get("patch") or "").strip(), "agent_s": round(agent_s, 1), "secs": row.get("secs"),
        "model_calls": len(calls), "tool_calls": n_tool,
        "model_s": round(paced_model_s + model["unpaced"], 1),
        "model_split": {k: round(v, 1) for k, v in model.items()},
        "tokens": {k: round(v) for k, v in tok.items()},
        "compactions": len(compactions), "compaction_s": round(comp_s, 1),
        "compaction_tokens": [(r.get("prompt"), r.get("completion")) for r in compactions],
        "cut_calls": len(cut), "cut_s": round(cut_s, 1), "spill_in": len(spill),
        "tool_s": round(sum(tools_s.values()), 1), "tools_s": {k: round(v, 1) for k, v in sorted(tools_s.items())},
        "tools_n": dict(sorted(tools_n.items())), "gaps_s": round(gaps, 1), "tail_s": round(tail, 1),
        "repeat_any": rep_any_n, "repeat_any_s": round(rep_any_s, 1), "repeat_consec": rep_cons_n,
        "repeat_consec_s": round(rep_cons_s, 1), "reread_after_compaction": rereads_after_comp_n,
        "reread_after_compaction_s": round(rereads_after_comp_s, 1), "cmd_timeouts": timeouts, "open_at_cap": open_at_cap, "tool_errors": dict(errors),
        "calls": per_call,
    }


def load_rows(run_dir: Path) -> dict:
    rows = {}
    for line in (run_dir / "results.jsonl").read_text().splitlines():
        if line.strip():
            r = json.loads(line); rows[r["id"]] = r
    return rows


def analyse_run(run_dir, proxy_log, ids=None) -> list[dict]:
    run_dir = Path(run_dir)
    rows = load_rows(run_dir)
    proxy = [json.loads(l) for l in Path(proxy_log).read_text().splitlines() if l.strip()]
    out = []
    for i in (ids or sorted(rows)):
        if i not in rows:
            continue
        tp = run_dir / "results" / "traces" / f"trace_{i}.json"
        if not tp.exists():
            continue
        out.append(analyse_task(rows[i], json.loads(tp.read_text()), proxy))
    return out


def summarise(tasks: list[dict]) -> dict:
    if not tasks:
        return {"n": 0}
    keys = ["agent_s", "model_s", "compaction_s", "cut_s", "tool_s", "gaps_s", "tail_s", "repeat_any_s", "repeat_consec_s",
            "reread_after_compaction_s"]
    s = {"n": len(tasks), "capped": sum(t["capped"] for t in tasks), "resolved": sum(t["resolved"] for t in tasks),
         "with_compaction": sum(t["compactions"] > 0 for t in tasks), "compactions": sum(t["compactions"] for t in tasks)}
    for k in keys:
        v = [t[k] for t in tasks]
        s[k] = {"sum": round(sum(v), 1), "mean": round(statistics.mean(v), 1), "median": round(statistics.median(v), 1)}
    for k in ["fixed", "prefill", "decode", "late", "unpaced"]:
        s["model_" + k] = round(sum(t["model_split"][k] for t in tasks), 1)
    for k in ["completion", "think_est", "visible_est", "uncached", "prompt"]:
        s["tok_" + k] = round(sum(t["tokens"][k] for t in tasks))
    tk = collections.Counter()
    for t in tasks:
        tk.update(t["tools_s"])
    s["tools_s"] = {k: round(v, 1) for k, v in tk.most_common()}
    s["model_calls"] = sum(t["model_calls"] for t in tasks)
    s["cmd_timeouts"] = sum(t["cmd_timeouts"] for t in tasks)
    return s


def table(tasks: list[dict]) -> str:
    h = ("| id | res | cap | agent s | calls | model s (decode/prefill/fixed/late) | think tok est / visible | compactions (s) | "
         "cut s | tool s | top tool kinds (s) | gaps s | tail s | repeats any/consec (s) | re-read after comp (s) | cmd timeouts |")
    lines = [h, "|" + "---|" * 16]
    for t in tasks:
        m = t["model_split"]
        top = ", ".join(f"{k.replace('run_command:', 'rc:')} {v:.0f}" for k, v in sorted(t["tools_s"].items(), key=lambda x: -x[1])[:3])
        lines.append(f"| {t['id']} | {'Y' if t['resolved'] else 'n'} | {'Y' if t['capped'] else 'n'} | {t['agent_s']:.0f} | "
                     f"{t['model_calls']} | {t['model_s']:.0f} ({m['decode']:.0f}/{m['prefill']:.0f}/{m['fixed']:.0f}/{m['late']:.0f}) | "
                     f"{t['tokens']['think_est']} / {t['tokens']['visible_est']} | {t['compactions']} ({t['compaction_s']:.0f}) | "
                     f"{t['cut_s']:.0f} | {t['tool_s']:.0f} | {top} | {t['gaps_s']:.0f} | {t['tail_s']:.0f} | "
                     f"{t['repeat_any']}/{t['repeat_consec']} ({t['repeat_any_s']:.0f}) | {t['reread_after_compaction']} "
                     f"({t['reread_after_compaction_s']:.0f}) | {t['cmd_timeouts']} |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir"); ap.add_argument("proxy_log")
    ap.add_argument("--ids"); ap.add_argument("--json"); ap.add_argument("--table", action="store_true")
    a = ap.parse_args()
    ids = Path(a.ids).read_text().split() if a.ids else None
    tasks = analyse_run(a.run_dir, a.proxy_log, ids)
    if a.json:
        Path(a.json).write_text(json.dumps(tasks, indent=1))
    if a.table:
        print(table(tasks))
    print(json.dumps(summarise(tasks), indent=1))


if __name__ == "__main__":
    main()
