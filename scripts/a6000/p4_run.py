"""P4 runner (docs/v4h/GATE.md, 'P2 addendum 4'): the chosen bundle on the 74 public tasks, sequential, through a pace proxy, via scripts/a6000/run_eval.py
(the kernel's run cell, subprocess sandbox, the bundle's own budgets). The arm comes from ~/g4/runs/autopilot_choice.json {"p4_arm"} (default v5h2, addendum 6),
or from --arm (a control read names its arm: GAPS "sub16 pre-registration", 2026-10-14).

    python scripts/a6000/p4_run.py [--port 8002] [--out ~/g4/runs/p4] [--arm BUNDLE]      resumable"""
import argparse, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CHOICE = Path.home() / "g4" / "runs" / "autopilot_choice.json"


def chosen_arm(path=None):
    try:
        return json.loads(Path(path or CHOICE).read_text()).get("p4_arm") or "v5h2"
    except (FileNotFoundError, ValueError):
        return "v5h2"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", type=int, default=8002); ap.add_argument("--out", default=str(Path.home() / "g4" / "runs" / "p4"))
    ap.add_argument("--arm", default=None, help="run this bundle instead of the choice file's p4_arm")
    a = ap.parse_args(argv)
    arm = a.arm or chosen_arm()
    Path(a.out).mkdir(parents=True, exist_ok=True)
    (Path(a.out) / "ARM").write_text(arm)
    sys.path.insert(0, str(HERE))
    import run_eval
    return run_eval.main([str(ROOT / "submissions" / arm), a.out, "--ids", str(ROOT / "data" / "kaggle_valid_ids.txt"), "--port", str(a.port), "--resume"]) or 0


if __name__ == "__main__":
    sys.exit(main())
