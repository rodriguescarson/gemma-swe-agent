"""The forensics counters a bundle run is judged by (docs/GAPS_2026-10-06.md, forensics -> v7; PROMPTS P6): computed from the stored traces of a run.

    python scripts/a6000/v7_counters.py RUN_DIR [--arm v7] [--must-zero view_usage_calls literal_wrapper_commands write_file_path_refusals forced_install_empty_args] [--json OUT.json]

RUN_DIR is either a p2_race output dir (items/<arm>/<task>/traces, task_results.jsonl) or a run_eval.py dir (results.jsonl, results/traces). Counters: view.py usage-line
calls, literal-wrapper commands (prompt call shape echoed into the command), write_file path refusals, forced-install `{}` calls (run_skill_script INVALID_ARGUMENTS),
locate/view cap refusals (SHARE SPENT), loops >= 5, budget-exhausted tasks, helper reachability (tasks with a can't-open), plus tasks and solved. Three examples per non-zero counter."""
import argparse
import glob
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import forensics_lib as fx  # noqa: E402

COUNTERS = ("view_usage_calls", "literal_wrapper_commands", "write_file_path_refusals", "forced_install_empty_args", "cap_refusals", "loops_ge5", "budget_exhausted_tasks", "helper_unreachable_tasks")
RULES = {"view_usage_calls": lambda v, c: v.mechanism.startswith("helper usage/argument error (view)"),
         "literal_wrapper_commands": lambda v, c: v.mechanism == "prompt call-shape echoed into the command",
         "write_file_path_refusals": lambda v, c: v.mechanism == "write_file outside the workspace refused",
         "forced_install_empty_args": lambda v, c: c.fn == "run_skill_script" and v.mechanism.startswith("harness rejection: INVALID_ARGUMENTS"),
         "cap_refusals": lambda v, c: "SHARE SPENT" in (c.content or "")}


def load_run(run, arm, items_dir="items"):
    """-> {task: (trace, resolved)}"""
    out = {}
    run = Path(run)
    if (run / "results.jsonl").exists():
        for line in (run / "results.jsonl").read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                f = run / "results" / "traces" / f"trace_{r['id']}.json"
                if f.exists():
                    out[r["id"]] = (fx.load_trace(f), bool(r.get("resolved")))
        return out
    for f in glob.glob(str(run / items_dir / (arm or "*") / "*" / "task_results.jsonl")):
        r = json.loads(open(f).readline())
        tr = glob.glob(os.path.join(os.path.dirname(f), "traces", "trace_*.json"))
        if tr:
            out[r["instance_id"]] = (fx.load_trace(tr[0]), bool(r.get("resolved")))
    return out


def counters(run, arm=None, items_dir="items"):
    data = load_run(run, arm, items_dir)
    c = {k: 0 for k in COUNTERS}
    c["tasks"], c["solved"] = len(data), sum(1 for _, s in data.values() if s)
    ex = {k: [] for k in COUNTERS}
    for task, (trace, _) in data.items():
        budget = unreachable = False
        for call in fx.iter_calls(trace):
            v = fx.classify(call.fn, call.args, call.payload)
            for k, rule in RULES.items():
                if rule(v, call):
                    c[k] += 1
                    if len(ex[k]) < 3:
                        ex[k].append({"task": task, "call": fx.call_text(call.fn, call.args)[:160], "reply": (call.content or "")[:200]})
            if v.mechanism.startswith("budget exhausted"):
                budget = True
            if v.mechanism.startswith("can't open file"):
                unreachable = True
                if len(ex["helper_unreachable_tasks"]) < 3:
                    ex["helper_unreachable_tasks"].append({"task": task, "call": fx.call_text(call.fn, call.args)[:160], "reply": (call.content or "")[:200]})
        loops = fx.find_loops(trace)
        c["loops_ge5"] += len(loops)
        for l in loops[:1]:
            if len(ex["loops_ge5"]) < 3:
                ex["loops_ge5"].append({"task": task, "call": f"{l.author}: {l.fn} {l.args[:120]} x{l.count}", "reply": l.first_reply[:200]})
        c["budget_exhausted_tasks"] += budget
        c["helper_unreachable_tasks"] += unreachable
        if budget and len(ex["budget_exhausted_tasks"]) < 3:
            ex["budget_exhausted_tasks"].append({"task": task, "call": "", "reply": ""})
    c["examples"] = ex
    return c


def verdict(c, must_zero):
    failing = [k for k in must_zero if c.get(k, 0)]
    return {"pass": not failing, "failing": failing, "must_zero": list(must_zero)}


def markdown(c, v=None):
    lines = [f"| tasks | solved | " + " | ".join(COUNTERS) + " |", "|---|---|" + "---|" * len(COUNTERS), f"| {c['tasks']} | {c['solved']} | " + " | ".join(str(c[k]) for k in COUNTERS) + " |"]
    if v is not None:
        lines.append("")
        lines.append("must-be-zero verdict: **" + ("PASS" if v["pass"] else "FAIL (" + ", ".join(v["failing"]) + ")") + "**")
    for k in COUNTERS:
        if c.get(k) and c["examples"].get(k):
            lines.append(f"- {k}: " + "; ".join(f"{e['task']}: `{e['call'][:80].replace(chr(10), ' ')}` -> `{e['reply'][:90].replace(chr(10), ' ')}`" for e in c["examples"][k] if e["task"]))
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("run"); ap.add_argument("--arm", default=None); ap.add_argument("--must-zero", nargs="*", default=["view_usage_calls", "literal_wrapper_commands", "write_file_path_refusals", "forced_install_empty_args"])
    ap.add_argument("--json", default=None); ap.add_argument("--items-dir", default="items", help="e.g. probe_v7_T2 for a probe")
    a = ap.parse_args(argv)
    c = counters(a.run, a.arm, a.items_dir)
    v = verdict(c, a.must_zero)
    print(markdown(c, v))
    if a.json:
        Path(a.json).write_text(json.dumps({"counters": {k: c[k] for k in c if k != "examples"}, "examples": c["examples"], "verdict": v}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
