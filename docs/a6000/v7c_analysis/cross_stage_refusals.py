"""Cross-stage re-read replies per run (docs/a6000/V7C_FAILURE_ANALYSIS.md, cause 1; the re-measure for step 1 = v7d).

    python3 -I cross_stage_refusals.py [LABEL=GLOB ...]

Each argument is a label and a glob of trace files (items/<arm>/*/traces/trace_*.json next to task_results.jsonl).
Without arguments the box's own runs are read (~/g4/runs/p2/...). Counted per run: every view.py reply that is a re-read
of a range already shown in the task, split into bare refusals (v4h6g..v7c: "ALREADY SHOWN", one line, no lines) and
shown-again replies (v7d: "SHOWN AGAIN", then the lines); the items whose FIRST fixer view was such a re-read, with how
many solved against the rest; and the fixer re-reads whose call is identical to a locator call (the stage crossing).
v7d's target: bare refusals 0 of N; the first-fixer-view re-reads then come back with lines, so what matters is the
solve rate of those items against the rest, and the share of identical consecutive repeats (aggregate_failures.py)."""
import collections, glob, json, os, sys

HOME = os.path.expanduser("~")
DEFAULT = [("v7c s50+probe", HOME + "/g4/runs/p2/items/v7c/*/traces/trace_*.json"),
           ("v7c probe", HOME + "/g4/runs/p2/probe_v7c_T2/v7c/*/traces/trace_*.json"),
           ("v7  s50", HOME + "/g4/runs/p2/items/v7/*/traces/trace_*.json"),
           ("v7  P4 (public 74)", HOME + "/g4/runs/p4_v7/results/traces/trace_*.json"),
           ("v5h2 P4", HOME + "/g4/runs/p4/results/traces/trace_*.json")]
MARKS = ("ALREADY SHOWN", "SHOWN AGAIN")


def reread(content):
    return next((m for m in MARKS if m in content), None)


def analyze(label, pattern):
    rows = []
    for tf in sorted(glob.glob(pattern)):
        d = os.path.dirname(os.path.dirname(tf))
        rf = glob.glob(d + "/task_results.jsonl")
        if not rf:
            continue
        res = json.loads(open(rf[0]).readline())
        steps = json.load(open(tf))["steps"]
        seq = []
        for s in steps:
            for c in s.get("tool_calls") or []:
                seq.append(((c.get("extra") or {}).get("author"), c["function_name"], json.dumps(c.get("arguments")),
                            (s.get("observation") or {}).get("content", "")))
        by = collections.Counter((a[0], reread(a[3])) for a in seq if reread(a[3]))
        fixer = [x for x in seq if x[0] == "fixer"]
        first_view = next((x for x in fixer if "view.py" in x[2]), None)
        cross = reread(first_view[3]) if first_view is not None else None
        loc_calls = {x[2] for x in seq if x[0] == "locator"}
        cross_n = sum(1 for x in fixer if reread(x[3]) and x[2] in loc_calls)
        rows.append((os.path.basename(d), bool(res["resolved"]), by, cross, cross_n))
    n = len(rows)
    if not n:
        print(label, "no items")
        return
    tot = {m: sum(v for r in rows for (a, mk), v in r[2].items() if mk == m) for m in MARKS}
    stage = {m: {st: sum(r[2].get((st, m), 0) for r in rows) for st in ("locator", "fixer", "verifier")} for m in MARKS}
    first = [r for r in rows if r[3]]
    print(f"{label}: items {n} solved {sum(r[1] for r in rows)} | re-read replies: bare refusals (ALREADY SHOWN) {tot['ALREADY SHOWN']} "
          f"{stage['ALREADY SHOWN']}, shown again (SHOWN AGAIN) {tot['SHOWN AGAIN']} {stage['SHOWN AGAIN']}")
    print(f"   items whose FIRST fixer view was a re-read (stage-crossing): {len(first)} -> solved {sum(r[1] for r in first)}; "
          f"others {n - len(first)} -> solved {sum(r[1] for r in rows if not r[3])}"
          + (f" | of the {len(first)}: " + ", ".join(f"{m} {sum(1 for r in first if r[3] == m)}" for m in MARKS) if first else ""))
    print(f"   fixer re-reads on a call identical to a locator call: {sum(r[4] for r in rows)}")


if __name__ == "__main__":
    args = [a.split("=", 1) for a in sys.argv[1:]]
    for label, pattern in (args or DEFAULT):
        analyze(label, pattern)
