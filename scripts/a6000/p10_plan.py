"""The supervisor steps of PROMPTS P10 (docs/GAPS_2026-10-06.md, "P10 pre-registration"): the thinking-on collector pair and the
collection pass. probe_pair (both arms, 4 items, T = 2) -> pair_s50 (both arms on the 50 stage-1a ids, paired; its post hooks
write the table, apply the P10 collector rule to the choice file, run the counters) -> p3_think (ONE pass of the chosen arm over
the 844 training ids, captures on; output runs/p3_think, next to the earlier passes). Same shape as p8_plan.py.
tests/test_a6000_p10.py.

    python scripts/a6000/p10_plan.py [--plan ~/g4/runs/autopilot_plan.json] [--scale-fallback 1.0] [--dry-run]
The plan REPLACES the steps of the file and is closed; the choice file is set to the reference arm until the pair decides."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
G4 = Path.home() / "g4"
IDS = [l.strip() for l in open(ROOT / "data" / "heldout1k" / "s200_valid_ids.txt") if l.strip()]
P3_IDS = [l.strip() for l in open(ROOT / "data" / "heldout1k" / "p3_ids.txt") if l.strip()]
CAND, REF = "v12", "v5h2-think"
ARMS = [REF, CAND]
COMPARATORS = ("v4h2", "v7c", "v7d")   # the thinking-off rows on the same 50 ids (v7d's exist on the box only)


def p10_steps(runs, py, scale_fallback=1.0, p3_scale=None):
    runs = str(runs)
    out = f"{runs}/p2"
    probe = {"name": "probe_pair", "total": 8, "docker": True,
             "cmd": [py, "scripts/a6000/p2_probe.py", out, "--harness", "data/heldout1k/harness_s200", "--ids", "data/heldout1k/s200_valid_ids.txt", "--arms", *ARMS, "--levels", "2"],
             "proxy": None, "stats": {"type": "p2", "out": out, "arms": ARMS, "ids": []}, "purge": None,
             "post": [[py, "scripts/a6000/v7_counters.py", out, "--arm", arm, "--items-dir", f"probe_{arm}_T2", "--json", f"{runs}/{arm}_probe_counters.json"] for arm in ARMS]}
    s50 = {"name": "pair_s50", "total": 100, "docker": True,
           "cmd": [py, "scripts/a6000/p2_race.py", out, "--harness", "data/heldout1k/harness_s200", "--ids", "data/heldout1k/s200_valid_ids.txt", "--n", "50", "--conc", "2", "--arms", *ARMS,
                   "--arm-scale-from-probe", *[f"{arm}={scale_fallback}" for arm in ARMS], "--port", "8001", "--label", "probe", "--keep"],
           "proxy": {"listen": 8001, "host": "172.18.0.1", "log": f"{out}/proxy_pair_s50.jsonl"}, "speed_log": f"{out}/proxy_pair_s50.jsonl",
           "stats": {"type": "p2", "out": out, "arms": ARMS, "ids": IDS[:50]},
           "purge": [py, "scripts/a6000/p2_purge.py", out, "items"], "purge_since": [py, "scripts/a6000/p2_purge_since.py", out, "items"],
           "post": [[py, "scripts/a6000/p2_results_md.py", out, "--label", f"{CAND} vs {REF} on the stage-1a ids (thinking on; vs {', '.join(COMPARATORS)} thinking off)",
                     "--from", "0", "--to", "50", "--arms", *COMPARATORS, *ARMS],
                    [py, "scripts/a6000/p10_choose.py", out, "--ids", "data/heldout1k/s200_valid_ids.txt", "--n", "50", "--cand", CAND, "--ref", REF, "--log", "docs/a6000/P2_LOG.md"],
                    *[[py, "scripts/a6000/v7_counters.py", out, "--arm", arm, "--json", f"{runs}/{arm}_s50_counters.json"] for arm in ARMS],
                    [py, "scripts/a6000/backup_results.py"]]}
    p3dir = f"{runs}/p3_think"
    p3cmd = [py, "scripts/a6000/p3_run.py", "--out", p3dir, "--port", "8003", "--passes", "1"]
    if p3_scale is not None:
        p3cmd += ["--scale", str(p3_scale)]
    p3 = {"name": "p3_think", "total": len(P3_IDS), "docker": True, "cmd": p3cmd,
          "proxy": None, "speed_log": f"{p3dir}/proxy.jsonl",
          "stats": {"type": "p2", "out": p3dir, "arms": ARMS, "ids": P3_IDS},
          "purge": [py, "scripts/a6000/p2_purge.py", p3dir, "items"], "purge_since": [py, "scripts/a6000/p2_purge_since.py", p3dir, "items"],
          "post": [[py, "scripts/a6000/p3_build.py", "--out", p3dir, "--passes", "1"], [py, "scripts/a6000/backup_results.py"]]}
    return [probe, s50, p3]


def set_choices(path, arm):
    p = Path(path)
    cur = json.loads(p.read_text()) if p.exists() else {}
    cur["p4_arm"] = arm; cur["p3_arm"] = arm
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cur))


def finalize_hooks(runs, py):
    return [[py, "scripts/a6000/p3_build.py", "--out", f"{runs}/p3_think", "--passes", "1"], [py, "scripts/a6000/final_summary.py"], [py, "scripts/a6000/backup_results.py"],
            ["bash", "-c", "kill $(pgrep -f '[b]ackup_results.py --loop') 2>/dev/null; true"]]


def write_plan(path, runs, py, scale_fallback=1.0):
    plan = {"steps": p10_steps(runs, py, scale_fallback), "finalize": finalize_hooks(runs, py), "open": False}
    Path(path).write_text(json.dumps(plan, indent=1))
    return plan


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--plan", default=str(G4 / "runs" / "autopilot_plan.json")); ap.add_argument("--scale-fallback", type=float, default=1.0); ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    py = str(G4 / "venv" / "bin" / "python")
    if a.dry_run:
        print(json.dumps([s["name"] for s in p10_steps(str(G4 / "runs"), py, a.scale_fallback)]))
        return 0
    set_choices(str(G4 / "runs" / "autopilot_choice.json"), REF)     # the pair's post hook replaces p3_arm by the P10 rule
    plan = write_plan(a.plan, str(G4 / "runs"), py, a.scale_fallback)
    print("plan steps:", [s["name"] for s in plan["steps"]], "| choices ->", REF, "until pair_s50 decides | open:", plan["open"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
