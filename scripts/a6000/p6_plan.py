"""The supervisor steps of the v7 switch (PROMPTS P6): probe (4 items, T = 2) -> v7 on the 50 stage-1a ids -> v7 on the public 74 -> P3 with v7, 4 passes. Writes them into
the open plan (~/g4/runs/autopilot_plan.json) and sets the P4/P3 arm choices to v7. tests/test_a6000_p6_plan.py.

    python scripts/a6000/p6_plan.py [--scale-fallback 1.0] [--plan ~/g4/runs/autopilot_plan.json] [--dry-run]"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
G4 = Path.home() / "g4"
IDS = [l.strip() for l in open(ROOT / "data" / "heldout1k" / "s200_valid_ids.txt") if l.strip()]
P3_IDS = [l.strip() for l in open(ROOT / "data" / "heldout1k" / "p3_ids.txt") if l.strip()]


def v7_steps(runs, py, scale_fallback=1.0):
    runs = str(runs)
    out = f"{runs}/p2"
    probe = {"name": "probe_v7", "total": 4, "docker": True,
             "cmd": [py, "scripts/a6000/p2_probe.py", out, "--harness", "data/heldout1k/harness_s200", "--ids", "data/heldout1k/s200_valid_ids.txt", "--arms", "v7", "--levels", "2"],
             "proxy": None, "stats": {"type": "p2", "out": out, "arms": ["v7"], "ids": []}, "purge": None,
             "post": [[py, "scripts/a6000/p2_probe_gate.py", out, "--arm", "v7"]]}
    s50 = {"name": "v7_s50", "total": 50, "docker": True,
           "cmd": [py, "scripts/a6000/p2_race.py", out, "--harness", "data/heldout1k/harness_s200", "--ids", "data/heldout1k/s200_valid_ids.txt", "--n", "50", "--conc", "2", "--arms", "v7",
                   "--arm-scale-from-probe", f"v7={scale_fallback}", "--port", "8001", "--label", "probe", "--keep"],
           "proxy": {"listen": 8001, "host": "172.18.0.1", "log": f"{out}/proxy_v7_s50.jsonl"}, "speed_log": f"{out}/proxy_v7_s50.jsonl",
           "stats": {"type": "p2", "out": out, "arms": ["v7"], "ids": IDS[:50]},
           "purge": [py, "scripts/a6000/p2_purge.py", out, "items"], "purge_since": [py, "scripts/a6000/p2_purge_since.py", out, "items"],
           "post": [[py, "scripts/a6000/p2_results_md.py", out, "--label", "v7 on the stage-1a ids (vs v4h2 stage 1a)", "--from", "0", "--to", "50", "--arms", "v4h2", "v7"],
                    [py, "scripts/a6000/v7_counters.py", out, "--arm", "v7", "--json", f"{runs}/v7_s50_counters.json"],
                    [py, "scripts/a6000/backup_results.py"]]}
    p4dir = f"{runs}/p4_v7"
    p4 = {"name": "v7_p4", "total": 74, "docker": False,
          "cmd": [py, "scripts/a6000/p4_run.py", "--out", p4dir, "--port", "8002"],
          "proxy": {"listen": 8002, "host": "127.0.0.1", "log": f"{runs}/p4_v7_proxy.jsonl"}, "speed_log": f"{runs}/p4_v7_proxy.jsonl",
          "stats": {"type": "results_jsonl", "file": f"{p4dir}/results.jsonl"},
          "purge": [py, "scripts/a6000/p4_purge.py", f"{p4dir}/results.jsonl"], "purge_since": [py, "scripts/a6000/p4_purge_since.py", f"{p4dir}/results.jsonl"],
          "post": [[py, "scripts/a6000/p4_judge.py", "--out", p4dir, "--proxy-log", f"{runs}/p4_v7_proxy.jsonl"],
                   [py, "scripts/a6000/v7_counters.py", p4dir, "--json", f"{runs}/v7_p4_counters.json"],
                   [py, "scripts/a6000/backup_results.py"]]}
    p3dir = f"{runs}/p3"
    p3 = {"name": "v7_p3", "total": len(P3_IDS) * 4, "docker": True,
          "cmd": [py, "scripts/a6000/p3_run.py", "--out", p3dir, "--port", "8003", "--passes", "4"],
          "proxy": None, "speed_log": f"{p3dir}/proxy.jsonl",
          "stats": {"type": "p2", "out": p3dir, "arms": ["v7"], "ids": P3_IDS},
          "purge": [py, "scripts/a6000/p2_purge.py", p3dir, "items"], "purge_since": [py, "scripts/a6000/p2_purge_since.py", p3dir, "items"],
          "post": [[py, "scripts/a6000/p3_build.py", "--out", p3dir, "--passes", "4"], [py, "scripts/a6000/backup_results.py"]]}
    return [probe, s50, p4, p3]


def set_choices(path, arm):
    p = Path(path)
    cur = json.loads(p.read_text()) if p.exists() else {}
    cur["p4_arm"] = arm; cur["p3_arm"] = arm
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cur))


def finalize_hooks(runs, py):
    return [[py, "scripts/a6000/p3_build.py", "--out", f"{runs}/p3", "--passes", "4"], [py, "scripts/a6000/final_summary.py"], [py, "scripts/a6000/backup_results.py"],
            ["bash", "-c", "kill $(pgrep -f '[b]ackup_results.py --loop') 2>/dev/null; true"]]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--plan", default=str(G4 / "runs" / "autopilot_plan.json")); ap.add_argument("--scale-fallback", type=float, default=1.0); ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    py = str(G4 / "venv" / "bin" / "python")
    plan = json.loads(Path(a.plan).read_text())
    have = {s["name"] for s in plan["steps"]}
    new = [s for s in v7_steps(str(G4 / "runs"), py, a.scale_fallback) if s["name"] not in have]
    plan["steps"] += new
    plan["finalize"] = finalize_hooks(str(G4 / "runs"), py)
    plan["open"] = False
    if a.dry_run:
        print(json.dumps([s["name"] for s in plan["steps"]]))
        return 0
    set_choices(str(G4 / "runs" / "autopilot_choice.json"), "v7")
    Path(a.plan).write_text(json.dumps(plan, indent=1))
    print("plan steps:", [s["name"] for s in plan["steps"]], "| choices -> v7 | open:", plan["open"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
