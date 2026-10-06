"""S1 keep rule (docs/GAPS_2026-10-06.md, Carson 2026-10-06): judge one faithful L4 run of the public 74 mechanically.

KEEP when the run solves >= 37 AND, paired task by task against v4h2g's L4 run, wins - losses >= +3.
INVALID when the run does not cover every baseline task (not a faithful run). Exit 0 KEEP, 1 DROP, 2 INVALID.

usage: python scripts/keep_rule.py <results.jsonl> [--base eval/kaggle/g4-l4-v4h2g-p312/results.jsonl]
                                   [--min-solved 37] [--min-net 3]
A task counts as solved if any of its rows is resolved (a re-run row never un-solves it)."""
import argparse, json, sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent / "eval" / "kaggle" / "g4-l4-v4h2g-p312" / "results.jsonl"


def load(path):
    solved = {}
    for line in Path(path).read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            solved[r["id"]] = solved.get(r["id"], False) or bool(r.get("resolved"))
    return solved


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("results")
    ap.add_argument("--base", default=str(BASE))
    ap.add_argument("--min-solved", type=int, default=37)
    ap.add_argument("--min-net", type=int, default=3)
    a = ap.parse_args(argv)
    new, base = load(a.results), load(a.base)
    missing = sorted(set(base) - set(new))
    n_new = sum(new.get(t, False) for t in base)
    wins = sorted(t for t in base if new.get(t) and not base[t])
    losses = sorted(t for t in base if base[t] and not new.get(t))
    net = len(wins) - len(losses)
    print(f"solved {n_new}/{len(base)} (base {sum(base.values())}/{len(base)}) | wins {len(wins)} losses {len(losses)} "
          f"net {net:+d} | rule: solved >= {a.min_solved} and net >= {a.min_net:+d}")
    if wins: print("won: " + " ".join(wins))
    if losses: print("lost: " + " ".join(losses))
    if missing:
        print(f"INVALID: missing {len(missing)} of {len(base)} baseline tasks ({' '.join(missing[:10])}"
              f"{' ...' if len(missing) > 10 else ''}); not a faithful run")
        return 2
    if n_new >= a.min_solved and net >= a.min_net:
        print("KEEP"); return 0
    why = [w for w, bad in ((f"solved {n_new} < {a.min_solved}", n_new < a.min_solved),
                            (f"net {net:+d} < {a.min_net:+d}", net < a.min_net)) if bad]
    print("DROP: " + "; ".join(why)); return 1


if __name__ == "__main__":
    sys.exit(main())
