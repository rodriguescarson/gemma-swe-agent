"""Sanity gate for a bundle that has never run on a model (docs/v4h/GATE.md, P2 addendum 7): after its arm-pure probe (T = 2, 4 items), the bundle is BROKEN, and is
dropped from the race, when 3 or more of the items ended with an empty patch, or 2 or more with the tool-call budget error, or any item with an infrastructure or
harness error; or when the probe did not run. Writes OUT/probe_gate.json {arm: {ok, n, empty, budget, infra, reasons}}.

    python scripts/a6000/p2_probe_gate.py OUT --arm v6p-b"""
import argparse, glob, json, os, re, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import p2_report as rep  # noqa: E402

FOOTER = re.compile(r"\[fixer ([abc]): helper call (\d+)/(\d+)")
LOCATOR = re.compile(r"\[locator: helper call (\d+)/(\d+)")
REFUSAL = re.compile(r"(SHARE SPENT|STOP: candidate [abc])")
FINAL = re.compile(r"/tmp/w([abc])")


def _ledger_from_dir(d):
    c = {"a": 0, "b": 0, "c": 0}
    for f in os.listdir(d):
        if ".call." in f and f[0] in c:
            c[f[0]] += 1
    return c


def _locator_from_dir(d):
    return sum(1 for f in os.listdir(d) if f.startswith("L.call."))


def ledger_counts(item_dir, task):
    """Counted helper calls per fixer for one probe item and the refusals seen: from the copied ledger directory when it survived, else from the
    footers the helpers print into the stored tool results (the largest n printed for a fixer is its count)."""
    led = item_dir.rstrip("/") + ".ledger"
    if os.path.isdir(led):
        return dict(_ledger_from_dir(led), refused=0, source="ledger", locator=_locator_from_dir(led))
    c, refused, loc = {"a": 0, "b": 0, "c": 0}, 0, 0
    for f in glob.glob(os.path.join(item_dir, "traces", "trace_*.json")):
        for st in json.load(open(f)).get("steps", []):
            obs = st.get("observation")
            text = obs if isinstance(obs, str) else json.dumps(obs)
            for k, n, _h in FOOTER.findall(text):
                c[k] = max(c[k], int(n))
            for n, _h in LOCATOR.findall(text):
                loc = max(loc, int(n))
            refused += len(REFUSAL.findall(text))
    return dict(c, refused=refused, source="traces", locator=loc)


def helper_fail_tasks(out, arm, T):
    """scripts/analyze_helper_reachability.py on the probe items: how many items show \"can't open file\" on a /tmp/swe helper."""
    root = Path(out) / "report_links" / f"probe_{arm}_T{T}" / "results" / "traces"
    root.mkdir(parents=True, exist_ok=True)
    for f in glob.glob(os.path.join(out, f"probe_{arm}_T{T}", arm, "*", "traces", "trace_*.json")):
        dst = root / os.path.basename(f)
        if not dst.exists():
            os.symlink(f, dst)
    sys.path.insert(0, str(HERE.parent))
    import analyze_helper_reachability as ahr
    return ahr.analyse(str(Path(out) / "report_links" / f"probe_{arm}_T{T}"))["tasks_with_failure"]


def gate(out, arm, T=2):
    rows = []
    for f in glob.glob(os.path.join(out, f"probe_{arm}_T{T}", arm, "*", "task_results.jsonl")):
        rows += [json.loads(l) for l in open(f) if l.strip()]
    n = len(rows)
    tags = [rep.classify(r) for r in rows]
    empty = sum("empty" in t for t in tags)
    budget = sum("budget" in t and "tool call" in (r.get("error") or "") for t, r in zip(tags, rows))
    infra = sum("infra" in t for t in tags)
    ledger = {}
    for f in glob.glob(os.path.join(out, f"probe_{arm}_T{T}", arm, "*", "task_results.jsonl")):
        task = os.path.basename(os.path.dirname(f))
        ledger[task] = ledger_counts(os.path.dirname(f), task)
    ledger_total = sum(v["a"] + v["b"] + v["c"] for v in ledger.values())
    hf = helper_fail_tasks(out, arm, T) if n else 0
    reasons = []
    if n == 0:
        reasons.append("the probe produced no result rows")
    if empty >= 3:
        reasons.append(f"{empty}/{n} empty patches")
    if budget >= 2:
        reasons.append(f"{budget}/{n} hit the tool-call budget")
    if infra:
        reasons.append(f"{infra} infrastructure/harness errors")
    if hf > 1:
        reasons.append(f"{hf} items with a can't open file on a helper")
    if n and ledger_total == 0:
        reasons.append("the per-fixer caps never engaged (no counted helper call on any item)")
    return {"ok": not reasons, "n": n, "empty": empty, "budget": budget, "infra": infra, "helper_fail_tasks": hf, "ledger": ledger, "ledger_total": ledger_total,
            "reasons": reasons}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out"); ap.add_argument("--arm", required=True)
    ap.add_argument("--log", default=str(HERE.parents[1] / "docs" / "a6000" / "P2_LOG.md"), help="the report is appended here (the supervisor pushes it)")
    a = ap.parse_args(argv)
    r = gate(a.out, a.arm)
    f = Path(a.out) / "probe_gate.json"
    cur = json.loads(f.read_text()) if f.exists() else {}
    cur[a.arm] = r
    f.write_text(json.dumps(cur, indent=1))
    lines = [f"- {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} | probe gate {a.arm}: GATE {'PASS' if r['ok'] else 'FAIL'} | items {r['n']}, empty patches {r['empty']}, "
             f"tool-call-budget errors {r['budget']}, infrastructure errors {r['infra']}, items with a can't open file {r['helper_fail_tasks']}, counted helper calls {r['ledger_total']}"
             + (f" | reasons: {'; '.join(r['reasons'])}" if r["reasons"] else "")]
    for task, v in sorted(r["ledger"].items()):
        lines.append(f"  - ledger {task}: locator {v.get('locator', 0)}, fixer a {v['a']}, b {v['b']}, c {v['c']} counted helper calls, {v['refused']} refusals (from {v['source']})")
    print("\n".join(lines))
    with open(a.log, "a") as fh:
        fh.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
