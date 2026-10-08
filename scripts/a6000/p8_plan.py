"""The supervisor steps of PROMPTS P8 (v7c screen + one data pass): probe (4 items, T = 2) -> v7c on the 50 stage-1a ids -> v7c on the public 74 -> P3 with v7c, ONE pass over
the 844 training ids. Same shape as p6_plan.py (v7); the P3 output goes to p3_v7c so the v7 pass in p3 stays untouched. tests/test_a6000_p8_plan.py.

    python scripts/a6000/p8_plan.py [--plan ~/g4/runs/autopilot_plan.json] [--scale-fallback 1.0] [--dry-run]
The plan REPLACES the steps of the file (the old plan is kept by the caller) and is closed; the choice file points P4 and P3 at v7c."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
G4 = Path.home() / "g4"
IDS = [l.strip() for l in open(ROOT / "data" / "heldout1k" / "s200_valid_ids.txt") if l.strip()]
P3_IDS = [l.strip() for l in open(ROOT / "data" / "heldout1k" / "p3_ids.txt") if l.strip()]
ARM = "v7c"


def v7c_steps(runs, py, scale_fallback=1.0, p3_scale=None):
    runs = str(runs)
    out = f"{runs}/p2"
    probe = {"name": f"probe_{ARM}", "total": 4, "docker": True,
             "cmd": [py, "scripts/a6000/p2_probe.py", out, "--harness", "data/heldout1k/harness_s200", "--ids", "data/heldout1k/s200_valid_ids.txt", "--arms", ARM, "--levels", "2"],
             "proxy": None, "stats": {"type": "p2", "out": out, "arms": [ARM], "ids": []}, "purge": None,
             "post": [[py, "scripts/a6000/v7_counters.py", out, "--arm", ARM, "--items-dir", f"probe_{ARM}_T2", "--json", f"{runs}/{ARM}_probe_counters.json"]]}
    s50 = {"name": f"{ARM}_s50", "total": 50, "docker": True,
           "cmd": [py, "scripts/a6000/p2_race.py", out, "--harness", "data/heldout1k/harness_s200", "--ids", "data/heldout1k/s200_valid_ids.txt", "--n", "50", "--conc", "2", "--arms", ARM,
                   "--arm-scale-from-probe", f"{ARM}={scale_fallback}", "--port", "8001", "--label", "probe", "--keep"],
           "proxy": {"listen": 8001, "host": "172.18.0.1", "log": f"{out}/proxy_{ARM}_s50.jsonl"}, "speed_log": f"{out}/proxy_{ARM}_s50.jsonl",
           "stats": {"type": "p2", "out": out, "arms": [ARM], "ids": IDS[:50]},
           "purge": [py, "scripts/a6000/p2_purge.py", out, "items"], "purge_since": [py, "scripts/a6000/p2_purge_since.py", out, "items"],
           "post": [[py, "scripts/a6000/p2_results_md.py", out, "--label", f"{ARM} on the stage-1a ids (vs v4h2 and v7 stage 1a)", "--from", "0", "--to", "50", "--arms", "v4h2", "v7", ARM],
                    [py, "scripts/a6000/v7_counters.py", out, "--arm", ARM, "--json", f"{runs}/{ARM}_s50_counters.json"],
                    [py, "scripts/a6000/backup_results.py"]]}
    p4dir = f"{runs}/p4_{ARM}"
    p4 = {"name": f"{ARM}_p4", "total": 74, "docker": False,
          "cmd": [py, "scripts/a6000/p4_run.py", "--out", p4dir, "--port", "8002"],
          "proxy": {"listen": 8002, "host": "127.0.0.1", "log": f"{runs}/p4_{ARM}_proxy.jsonl"}, "speed_log": f"{runs}/p4_{ARM}_proxy.jsonl",
          "stats": {"type": "results_jsonl", "file": f"{p4dir}/results.jsonl"},
          "purge": [py, "scripts/a6000/p4_purge.py", f"{p4dir}/results.jsonl"], "purge_since": [py, "scripts/a6000/p4_purge_since.py", f"{p4dir}/results.jsonl"],
          "post": [[py, "scripts/a6000/p4_judge.py", "--out", p4dir, "--proxy-log", f"{runs}/p4_{ARM}_proxy.jsonl"],
                   [py, "scripts/a6000/v7_counters.py", p4dir, "--json", f"{runs}/{ARM}_p4_counters.json"],
                   [py, "scripts/a6000/backup_results.py"]]}
    p3dir = f"{runs}/p3_{ARM}"
    p3cmd = [py, "scripts/a6000/p3_run.py", "--out", p3dir, "--port", "8003", "--passes", "1"]
    if p3_scale is not None:
        p3cmd += ["--scale", str(p3_scale)]
    p3 = {"name": f"{ARM}_p3", "total": len(P3_IDS), "docker": True, "cmd": p3cmd,
          "proxy": None, "speed_log": f"{p3dir}/proxy.jsonl",
          "stats": {"type": "p2", "out": p3dir, "arms": [ARM], "ids": P3_IDS},
          "purge": [py, "scripts/a6000/p2_purge.py", p3dir, "items"], "purge_since": [py, "scripts/a6000/p2_purge_since.py", p3dir, "items"],
          "post": [[py, "scripts/a6000/p3_build.py", "--out", p3dir, "--passes", "1"], [py, "scripts/a6000/backup_results.py"]]}
    return [probe, s50, p4, p3]


def set_choices(path, arm):
    p = Path(path)
    cur = json.loads(p.read_text()) if p.exists() else {}
    cur["p4_arm"] = arm; cur["p3_arm"] = arm
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cur))


def finalize_hooks(runs, py):
    return [[py, "scripts/a6000/p3_build.py", "--out", f"{runs}/p3_{ARM}", "--passes", "1"], [py, "scripts/a6000/final_summary.py"], [py, "scripts/a6000/backup_results.py"],
            ["bash", "-c", "kill $(pgrep -f '[b]ackup_results.py --loop') 2>/dev/null; true"]]


def write_plan(path, runs, py, scale_fallback=1.0):
    plan = {"steps": v7c_steps(runs, py, scale_fallback), "finalize": finalize_hooks(runs, py), "open": False}
    Path(path).write_text(json.dumps(plan, indent=1))
    return plan


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--plan", default=str(G4 / "runs" / "autopilot_plan.json")); ap.add_argument("--scale-fallback", type=float, default=1.0); ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    py = str(G4 / "venv" / "bin" / "python")
    if a.dry_run:
        print(json.dumps([s["name"] for s in v7c_steps(str(G4 / "runs"), py, a.scale_fallback)]))
        return 0
    set_choices(str(G4 / "runs" / "autopilot_choice.json"), ARM)
    plan = write_plan(a.plan, str(G4 / "runs"), py, a.scale_fallback)
    print("plan steps:", [s["name"] for s in plan["steps"]], "| choices ->", ARM, "| open:", plan["open"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
