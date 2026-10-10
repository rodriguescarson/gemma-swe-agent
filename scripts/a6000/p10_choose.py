"""The collector choice of PROMPTS P10 (docs/GAPS_2026-10-06.md, "P10 pre-registration"), applied mechanically after the 50-id pair:
the candidate (v12, the single thinking-on agent) is the P3 collector unless its paired verdict against the reference (v5h2-think)
is WORSE; simpler wins ties and NO EVIDENCE. Writes {"p3_arm": ...} into the supervisor's choice file (p3_run.py reads it at its
start) and prints the contrast it decided on. Runs as a post hook of the pair step, AFTER p2_results_md.py (which writes its own
p3_arm by an older rule) so this rule is the one that stands.

    python scripts/a6000/p10_choose.py OUT --ids data/heldout1k/s200_valid_ids.txt [--n 50] [--cand v12] [--ref v5h2-think]
                                       [--choice ~/g4/runs/autopilot_choice.json] [--log docs/a6000/P2_LOG.md]"""
import argparse, json, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import p2_report as rep  # noqa: E402

CHOICE = Path.home() / "g4" / "runs" / "autopilot_choice.json"


def choose(out, ids, cand, ref):
    """-> (arm, contrast dict): the candidate unless its verdict vs the reference is WORSE."""
    c = rep.contrast(str(out), cand, ref, ids=ids)
    return (ref if c["verdict"] == "WORSE" else cand), c


def write_choice(path, arm):
    p = Path(path)
    cur = json.loads(p.read_text()) if p.exists() else {}
    cur["p3_arm"] = arm
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cur))
    return cur


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out"); ap.add_argument("--ids", required=True); ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--cand", default="v12"); ap.add_argument("--ref", default="v5h2-think")
    ap.add_argument("--choice", default=str(CHOICE)); ap.add_argument("--log", default=None)
    a = ap.parse_args(argv)
    ids = [l.strip() for l in open(a.ids) if l.strip()][:a.n]
    arm, c = choose(a.out, ids, a.cand, a.ref)
    write_choice(a.choice, arm)
    line = (f"P10 collector choice: p3_arm={arm} ({a.cand} vs {a.ref} on {c['n']} valid pairs: wins {c['wins']} losses {c['losses']} "
            f"net {c['wins'] - c['losses']:+d} sign p {c['p']:.3f} cap gap {c['cap_gap']:+.2f} -> {c['verdict']}; rule: {a.cand} unless WORSE)")
    print(line)
    if a.log:
        with open(a.log, "a") as f:
            f.write(f"- {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} | {line}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
