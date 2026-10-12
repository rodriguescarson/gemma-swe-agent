"""The adapter choice of PROMPTS P12 (docs/GAPS_2026-10-06.md, "P12 pre-registration"), applied mechanically after the 50-id pair:
every adapter arm is contrasted against the reference (v12); the arm with the best paired net among those not WORSE becomes
p4_arm (the A6000 screen of the 74 public tasks that the day's submission needs), ties going to the listed order (think1,
think1f, think2); when every arm is WORSE the reference itself is screened (a control read, no submission). Writes
{"p4_arm": ...} into the supervisor's choice file (p4_run.py reads it at its start), the contrasts to --json, one line to the
log. Runs as a post hook of pair_s50 AFTER p2_results_md.py. tests/test_a6000_p12.py.

    python scripts/a6000/p12_choose.py OUT --ids data/heldout1k/s200_valid_ids.txt [--n 50] --arms v12_think1 v12_think1f v12_think2
                                       [--ref v12] [--choice ~/g4/runs/autopilot_choice.json] [--json ~/g4/runs/p12_choice.json] [--log docs/a6000/P2_LOG.md]"""
import argparse, json, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import p2_report as rep  # noqa: E402

CHOICE = Path.home() / "g4" / "runs" / "autopilot_choice.json"


def choose(out, ids, arms, ref, contrast=None):
    """-> (p4_arm, {arm: contrast}): the best net among the arms not WORSE vs ref (ties: listed order); ref when all are WORSE."""
    contrast = contrast or (lambda arm: rep.contrast(str(out), arm, ref, ids=ids))
    cs = {arm: contrast(arm) for arm in arms}
    ok = [arm for arm in arms if cs[arm]["verdict"] != "WORSE"]
    if not ok:
        return ref, cs
    best = max(ok, key=lambda arm: (cs[arm]["wins"] - cs[arm]["losses"], -arms.index(arm)))
    return best, cs


def write_choice(path, arm):
    p = Path(path)
    cur = json.loads(p.read_text()) if p.exists() else {}
    cur["p4_arm"] = arm
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cur))
    return cur


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out"); ap.add_argument("--ids", required=True); ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--arms", nargs="+", required=True); ap.add_argument("--ref", default="v12")
    ap.add_argument("--choice", default=str(CHOICE)); ap.add_argument("--json", default=None); ap.add_argument("--log", default=None)
    a = ap.parse_args(argv)
    ids = [l.strip() for l in open(a.ids) if l.strip()][:a.n]
    arm, cs = choose(a.out, ids, a.arms, a.ref)
    write_choice(a.choice, arm)
    parts = [f"{x} vs {a.ref}: {c['n']} pairs wins {c['wins']} losses {c['losses']} net {c['wins'] - c['losses']:+d} sign p {c['p']:.3f} cap gap {c['cap_gap']:+.2f} -> {c['verdict']}"
             for x, c in cs.items()]
    line = f"P12 adapter choice: p4_arm={arm} ({'; '.join(parts)}; rule: best net among the arms not WORSE, ties in listed order, {a.ref} when all are WORSE)"
    print(line)
    if a.json:
        Path(a.json).write_text(json.dumps({"p4_arm": arm, "ref": a.ref, "contrasts": cs}, indent=1, default=str))
    if a.log:
        with open(a.log, "a") as f:
            f.write(f"- {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} | {line}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
