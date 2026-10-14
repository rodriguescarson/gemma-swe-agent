"""Every number in docs/forty_two/TIMING.md, from the box runs' traces + pace-proxy logs (and the two Kaggle L4 runs with traces).

    python scripts/forty_two/timing_report.py [--runs p4 p4_v7 p4_v7c p4_v7d p4_b1024 p4_v0t2] [--main p4_b1024] [--json OUT]

Prints markdown sections; scripts/forty_two/timing.py does the per-task clock (see its docstring for the method)."""
from __future__ import annotations

import argparse
import collections
import glob
import json
import re
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT / "scripts"))
import timing  # noqa: E402
from analyze_failures import patch_files  # noqa: E402

BOX = ROOT / "eval" / "a6000" / "results"
MISSING = "mandatory input parameters are not present"
L4_TRACE_RUNS = ["e74_v2", "e74_v3"]


def never_ids():
    return (ROOT / "data" / "never_solved_box5_ids.txt").read_text().split()


def run_tasks(run):
    return timing.analyse_run(BOX / run, BOX / f"{run}_proxy.jsonl")


def traces(run_dir: Path):
    for f in sorted(glob.glob(str(run_dir / "results" / "traces" / "trace_*.json")) + glob.glob(str(run_dir / "traces" / "trace_*.json"))):
        yield Path(f).stem[len("trace_"):], json.loads(Path(f).read_text())


def groups(tasks, never):
    return [("the 42", [t for t in tasks if t["id"] in never]), ("solved in this run", [t for t in tasks if t["resolved"]]),
            ("other failures", [t for t in tasks if not t["resolved"] and t["id"] not in never])]


def fmt_group_row(run, name, g):
    s = timing.summarise(g)
    if not s["n"]:
        return f"| {run} | {name} | 0 |" + " |" * 14
    n = s["n"]
    return (f"| {run} | {name} | {n} | {s['capped']} | {s['agent_s']['mean']:.0f} | {s['model_s']['mean']:.0f} | "
            f"{s['model_decode'] / n:.0f} | {s['model_prefill'] / n:.0f} | {s['model_late'] / n:.0f} | "
            f"{100 * s['tok_think_est'] / max(1, s['tok_completion']):.0f}% | {s['compaction_s']['mean']:.0f} ({s['with_compaction']}) | "
            f"{s['tool_s']['mean']:.0f} | {s['tail_s']['mean']:.0f} | {s['repeat_any_s']['mean']:.0f} | "
            f"{s['reread_after_compaction_s']['mean']:.0f} | {s['model_calls'] / n:.1f} |")


GROUP_HEAD = ("| run | group | n | capped | agent s | model s | decode s | prefill s | box late s | think share (est) | "
              "compaction s (tasks) | tool s | tail s | repeat s | re-read after compaction s | model calls |\n" + "|" + "---|" * 16)


def by_emitted_tool(g):
    n, s, comp = collections.Counter(), collections.Counter(), collections.Counter()
    for t in g:
        for c in t["calls"]:
            k = (c["tools"][0] if c["tools"] else "text only").replace("run_command:", "run_command ")
            n[k] += 1; s[k] += c["model_s"]; comp[k] += (c["usage"] or [0, 0])[1]
    return n, s, comp


def first_edit(calls):
    """(1-based call index, seconds) of the first successful source write: edit_file/write_file outside tests and /tmp, or a
    run_command that writes a .py file in place."""
    for k, c in enumerate(calls):
        for x in c["tools"]:
            if x["name"] in ("edit_file", "write_file"):
                fp = str(x["args"].get("filepath", ""))
                fp = fp.removeprefix("/workspace/")
                if (fp.startswith("/tmp") or fp.startswith("tests/") or "test" in fp.split("/")[-1] or "/" not in fp
                        or re.search(r"repro|debug|scratch", fp.split("/")[-1])):
                    continue                     # scratch files at the repo root, tests and /tmp are not source edits
                if x["obs"].lstrip().startswith('{"status": "ok"'):
                    return k + 1, c["rel"]
            if x["name"] == "run_command":
                cmd = str(x["args"].get("command", ""))
                if re.search(r"sed -i|write_text\(|patch -p", cmd) and "repro" not in cmd and '"status": "ok"' in x["obs"][:40]:
                    return k + 1, c["rel"]
    return None, None


def malformed_census(run):
    per_tool, calls, tasks = collections.Counter(), collections.Counter(), collections.Counter()
    for i, t in traces(BOX / run):
        for s in t["steps"]:
            for c in s.get("tool_calls") or []:
                calls[c["function_name"]] += 1
                if MISSING in str((s.get("observation") or {}).get("content")):
                    per_tool[c["function_name"]] += 1; tasks[i] += 1
    return per_tool, calls, tasks


def malformed_seconds(run):
    out = collections.defaultdict(lambda: [0, 0.0])
    for i, t in traces(BOX / run):
        t0, calls = timing.model_calls(t)
        prev = t0
        for c in calls:
            for x in c["tools"]:
                if x["name"] in ("edit_file", "write_file") and MISSING in x["obs"]:
                    out[i][0] += 1; out[i][1] += (c["ts"] - prev) + (x["end"] - x["start"])
            prev = max([c["ts"]] + [x["end"] for x in c["tools"]])
    return out


def command_census(runs):
    durs = []
    dirs = [BOX / r for r in runs] + [ROOT / "eval" / "kaggle" / r for r in L4_TRACE_RUNS]
    n_traces = 0
    for d in dirs:
        for _, t in traces(d):
            try:
                _, calls = timing.model_calls(t)
            except ValueError:
                continue
            n_traces += 1
            for c in calls:
                for x in c["tools"]:
                    if x["name"] == "run_command":
                        durs.append((x["end"] - x["start"], "TimeoutExceeded" in x["obs"][:400], d.name, str(x["args"].get("command"))))
    return n_traces, durs


def crosscheck(R, never):
    """TIMING.md sect. 12: the fastapi/requests 15 of the 42 over the given runs, and the long-call / 512-budget numbers."""
    fast = {i for i in never if not i.startswith("rich")}
    for name, sel in [("fastapi 15", fast), ("rich 27", never - fast)]:
        agent = model = tool = comp = rep = big_proxy = big_iv = 0.0; nrep = nbig = nbig_iv = 0; secs = 0.0
        for r, T in R.items():
            rows = timing.load_rows(BOX / r)
            for t in T:
                if t["id"] not in sel:
                    continue
                agent += t["agent_s"]; model += t["model_s"]; tool += t["tool_s"]; comp += t["compaction_s"]
                rep += t["repeat_any_s"]; nrep += t["repeat_any"]; secs += float(rows[t["id"]]["secs"] or 0)
                big = [c["model_s"] for c in t["calls"] if c["model_s"] >= 30]; big_proxy += sum(big); nbig += len(big)
                tr = json.loads((BOX / r / "results" / "traces" / f"trace_{t['id']}.json").read_text())
                t0, calls = timing.model_calls(tr); prev = t0
                for c in calls:
                    if c["ts"] - prev >= 30:
                        big_iv += c["ts"] - prev; nbig_iv += 1
                    prev = max([c["ts"]] + [x["end"] for x in c["tools"]])
        print(f"- {name} over {len(R)} runs: row secs {secs:.0f}, agent {agent:.0f}, model {100 * model / agent:.1f} %, tools "
              f"{100 * tool / agent:.1f} %, compaction {comp:.0f} s, calls >= 30 s {big_proxy:.0f} s ({nbig}) by proxy duration / "
              f"{big_iv:.0f} s ({nbig_iv}) by trace interval, identical repeats {rep:.0f} s ({nrep})")
    for r in R:
        if r != "p4_b1024":
            continue
        rows = timing.load_rows(BOX / r)
        for name, sel in [("the 42", lambda i: i in never), ("solved", lambda i: rows[i]["resolved"])]:
            above = 0.0; n = 0; big = 0.0; agent = 0.0
            for t in R[r]:
                if not sel(t["id"]):
                    continue
                n += 1; agent += t["agent_s"]; big += sum(c["model_s"] for c in t["calls"] if c["model_s"] >= 30)
                tr = json.loads((BOX / r / "results" / "traces" / f"trace_{t['id']}.json").read_text())
                for c in timing.model_calls(tr)[1]:
                    if c["usage"] and (c["think_chars"] + c["text_chars"]):
                        above += max(0.0, c["usage"][1] * c["think_chars"] / (c["think_chars"] + c["text_chars"]) - 512)
            print(f"- {r} {name}: calls >= 30 s {big:.0f} s of {agent:.0f} agent s; thinking tokens above 512 (est) {above:.0f} = "
                  f"{above * timing.L4_B:.0f} L4 s, {above * timing.L4_B / n:.1f} s per task")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", default=["p4", "p4_v7", "p4_v7c", "p4_v7d", "p4_b1024", "p4_v0t2"])
    ap.add_argument("--main", default="p4_b1024")
    ap.add_argument("--json")
    ap.add_argument("--crosscheck", action="store_true", help="only TIMING.md sect. 12")
    a = ap.parse_args()
    never = set(never_ids())
    R = {r: run_tasks(r) for r in a.runs}
    if a.crosscheck:
        crosscheck(R, never)
        return
    rows = {r: timing.load_rows(BOX / r) for r in a.runs}
    tasks_jsonl = {json.loads(l)["instance_id"]: json.loads(l) for l in (ROOT / "data" / "tasks.jsonl").read_text().splitlines() if l.strip()}

    print("## 1. Check: the clock partitions every agent window")
    for r, T in R.items():
        bad = [t["id"] for t in T if abs(t["agent_s"] - (t["model_s"] + t["compaction_s"] + t["tool_s"] + t["gaps_s"] + t["tail_s"])) > 3]
        post = [t["post_s"] for t in T if t["post_s"] is not None]
        print(f"- {r}: {len(T)} tasks, model + compaction + tools + gaps + tail within 3 s of the agent window in {len(T) - len(bad)}; "
              f"capped {sum(t['capped'] for t in T)}; verification+teardown after the agent: median {statistics.median(post):.1f} s, "
              f"non-hanging max {max([p for p in post if p < 100] or [0]):.1f} s, hangs (>=100 s) {sum(p >= 100 for p in post)}")

    print("\n## 2. Where the agent time goes, per group (means per task)\n")
    print(GROUP_HEAD)
    for r, T in R.items():
        for name, g in groups(T, never):
            print(fmt_group_row(r, name, g))

    main_T = {t["id"]: t for t in R[a.main]}
    print(f"\n## 3. The 42 on {a.main}, task by task\n")
    print(timing.table([main_T[i] for i in never_ids() if i in main_T]))

    print(f"\n## 4. Model seconds by the tool the call emitted ({a.main} and p4_v0t2)\n")
    for r in [a.main, "p4_v0t2"]:
        if r not in R:
            continue
        for name, g in groups(R[r], never)[:2]:
            n, s, comp = by_emitted_tool(g)
            tot = sum(s.values())
            print(f"\n{r}, {name} ({len(g)} tasks, {tot / max(1, len(g)):.0f} model s per task)\n")
            print("| emitted tool | calls per task | model s per task | share | mean completion tokens | s per call |\n|---|---|---|---|---|---|")
            for k, v in s.most_common(8):
                print(f"| {k} | {n[k] / len(g):.1f} | {v / len(g):.1f} | {100 * v / tot:.0f}% | {comp[k] / n[k]:.0f} | {v / n[k]:.1f} |")

    print(f"\n## 5. When the first source edit happens ({a.main})\n")
    for name, sel in [("solved", lambda i: rows[a.main][i]["resolved"]), ("the 42", lambda i: i in never)]:
        got, none = [], 0
        for i, t in traces(BOX / a.main):
            if not sel(i):
                continue
            _, calls = timing.model_calls(t)
            k, rel = first_edit(calls)
            if k is None:
                none += 1
            else:
                got.append((k, rel))
        ks = sorted(k for k, _ in got); ts = sorted(x for _, x in got)
        print(f"- {name}: {len(got)} tasks edit, {none} never edit; first edit at call median {statistics.median(ks):.0f} "
              f"(max {max(ks)}), at {statistics.median(ts):.0f} s median (p75 {ts[int(.75 * (len(ts) - 1))]:.0f}, max {max(ts):.0f})")

    print("\n## 6. Malformed tool calls (reply: 'mandatory input parameters are not present')\n")
    print("| run | malformed / calls by tool | tasks |\n|---|---|---|")
    for r in a.runs:
        per, calls, tasks = malformed_census(r)
        cells = "; ".join(f"{k} {per[k]}/{calls[k]}" for k in sorted(per)) or "0"
        rc = calls.get("run_command", 0)
        print(f"| {r} | {cells}; run_command 0/{rc} | {len(tasks)} |")
    for r in [a.main, "p4_v0t2"]:
        if r not in R:
            continue
        ms = malformed_seconds(r)
        print(f"\n{r}: {sum(v[1] for v in ms.values()):.0f} s in malformed edit/write calls, {len(ms)} tasks: " +
              ", ".join(f"{i} {v[0]} calls {v[1]:.0f} s{' (42)' if i in never else ''}{' solved' if rows[r][i]['resolved'] else ''}"
                        for i, v in sorted(ms.items(), key=lambda x: -x[1][1])))

    n_tr, durs = command_census(a.runs)
    print(f"\n## 7. run_command durations ({len(durs)} commands in {n_tr} traces: {', '.join(a.runs)} + Kaggle L4 {', '.join(L4_TRACE_RUNS)})\n")
    b = collections.Counter()
    for d, to, _, _ in durs:
        k = ">=170" if d >= 170 else "60-170" if d >= 60 else "30-60" if d >= 30 else "15-30" if d >= 15 else "5-15" if d >= 5 else "<5"
        b[(k, "timeout" if to else "finished")] += 1
    for k in ["<5", "5-15", "15-30", "30-60", "60-170", ">=170"]:
        print(f"- {k} s: finished {b[(k, 'finished')]}, hit the timeout {b[(k, 'timeout')]}")
    fin = sorted((d, run, c) for d, to, run, c in durs if not to)[-3:]
    print("- longest commands that finished: " + "; ".join(f"{d:.1f} s {run} `{c[:50]}`" for d, run, c in reversed(fin)))
    main_hangs = [(t["id"], t["cmd_timeouts"], t["tool_s"]) for t in R[a.main] if t["cmd_timeouts"]]
    print(f"- {a.main}: tasks with a command timeout: " + ", ".join(f"{i} ({n} timeouts, {s:.0f} tool s)" for i, n, s in main_hangs))

    print(f"\n## 8. Completion tokens per model call ({a.main})\n")
    for name, g in groups(R[a.main], never)[:2]:
        comps = sorted(c["usage"][1] for t in g for c in t["calls"] if c["usage"])
        above = sum(max(0, c - 512) for c in comps)
        print(f"- {name}: {len(comps)} calls, median {statistics.median(comps):.0f}, p90 {comps[int(.9 * (len(comps) - 1))]}, "
              f">= 1000: {sum(c >= 1000 for c in comps)}; tokens above 512 per call: {above} = {above * timing.L4_B:.0f} L4 s "
              f"({above * timing.L4_B / len(g):.0f} s per task)")

    print(f"\n## 9. Compaction ({a.main})\n")
    for name, g in groups(R[a.main], never)[:2]:
        comp = [x for t in g for x in t["compaction_tokens"]]
        print(f"- {name}: {sum(t['compactions'] > 0 for t in g)} of {len(g)} tasks compacted, {len(comp)} summaries, "
              f"{sum(t['compaction_s'] for t in g):.0f} s ({sum(t['compaction_s'] for t in g) / max(1, len(comp)):.0f} s each); "
              f"summary completion tokens median {statistics.median([c for _, c in comp]) if comp else 0:.0f}; "
              f"re-reads of an already-read file after a compaction {sum(t['reread_after_compaction'] for t in g)} calls, "
              f"{sum(t['reread_after_compaction_s'] for t in g):.0f} s")

    print(f"\n## 10. Final state of the 42 across the box runs (E empty patch, G touches a gold file, W wrong files; c capped, "
          f"digit = compactions, h = command timeout)\n")
    print("| id | " + " | ".join(a.runs) + " |\n|" + "---|" * (len(a.runs) + 1))
    for i in never_ids():
        gold = patch_files(tasks_jsonl[i]["patch"])
        cells = []
        for r in a.runs:
            t = {x["id"]: x for x in R[r]}[i]
            pf = patch_files(rows[r][i].get("patch") or "")
            st = "E" if not pf else ("G" if any(f in gold for f in pf) else "W")
            cells.append(f"{st}{'c' if t['capped'] else ''}{t['compactions'] or ''}{'h' if t['cmd_timeouts'] else ''}")
        print(f"| {i} | " + " | ".join(cells) + " |")
    if a.json:
        Path(a.json).write_text(json.dumps({r: [{k: v for k, v in t.items() if k != "calls"} for t in T] for r, T in R.items()}, indent=0))


if __name__ == "__main__":
    main()
