"""Sanity gate for a bundle that has never run on a model (docs/v4h/GATE.md, P2 addendum 7): after its arm-pure probe (T = 2, 4 items), the bundle is BROKEN, and is
dropped from the race, when 3 or more of the items ended with an empty patch, or 2 or more with the tool-call budget error, or any item with an infrastructure or
harness error; or when the probe did not run. Writes OUT/probe_gate.json {arm: {ok, n, empty, budget, infra, reasons}}.

    python scripts/a6000/p2_probe_gate.py OUT --arm v6p-b"""
import argparse, glob, json, os, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import p2_report as rep  # noqa: E402


def gate(out, arm, T=2):
    rows = []
    for f in glob.glob(os.path.join(out, f"probe_{arm}_T{T}", arm, "*", "task_results.jsonl")):
        rows += [json.loads(l) for l in open(f) if l.strip()]
    n = len(rows)
    tags = [rep.classify(r) for r in rows]
    empty = sum("empty" in t for t in tags)
    budget = sum("budget" in t and "tool call" in (r.get("error") or "") for t, r in zip(tags, rows))
    infra = sum("infra" in t for t in tags)
    reasons = []
    if n == 0:
        reasons.append("the probe produced no result rows")
    if empty >= 3:
        reasons.append(f"{empty}/{n} empty patches")
    if budget >= 2:
        reasons.append(f"{budget}/{n} hit the tool-call budget")
    if infra:
        reasons.append(f"{infra} infrastructure/harness errors")
    return {"ok": not reasons, "n": n, "empty": empty, "budget": budget, "infra": infra, "reasons": reasons}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out"); ap.add_argument("--arm", required=True)
    a = ap.parse_args(argv)
    r = gate(a.out, a.arm)
    f = Path(a.out) / "probe_gate.json"
    cur = json.loads(f.read_text()) if f.exists() else {}
    cur[a.arm] = r
    f.write_text(json.dumps(cur, indent=1))
    print(a.arm, "GATE", "PASS" if r["ok"] else "FAIL", json.dumps(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
