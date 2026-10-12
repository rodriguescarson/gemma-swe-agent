"""The supervisor steps of PROMPTS P12 (docs/GAPS_2026-10-06.md, "P12 pre-registration", 2026-10-13): the A6000 screen of the
think adapters while Kaggle's weekly GPU quota is out. probe_pair (the adapter arms, 4 items, T = 2: the adapter must apply and
answer) -> pair_s50 (the adapter arms on the 50 stage-1a ids, paired against v12's rows of the P10 pair in the same p2 dir:
p2_race skips items that already have a task_results.jsonl, so v12 is not re-run; its post hooks write the table and the
counters). vLLM serves the union bundle's adapters: plan["serve_bundle"] -> autopilot serve_env -> serve.sh BUNDLE. Same
shape as p10_plan.py. tests/test_a6000_p12.py.

    python scripts/a6000/p12_plan.py --serve-bundle ~/g4/serve_bundle [--arms v12_think1 v12_think1f v12_think2]
        [--ref v12] [--plan ~/g4/runs/autopilot_plan.json] [--scale-fallback 1.0] [--dry-run]
The plan REPLACES the steps of the file and is closed (no step is added while it runs)."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
G4 = Path.home() / "g4"
IDS = [l.strip() for l in open(ROOT / "data" / "heldout1k" / "s200_valid_ids.txt") if l.strip()]
REF = "v12"
DEFAULT_ARMS = ["v12_think1", "v12_think1f", "v12_think2"]
COMPARATORS = ("v4h2", "v7c", "v7d", "v5h2-think")   # thinking-off rows and the P10 reference on the same 50 ids (box only)


def p12_steps(runs, py, arms, ref=REF, scale_fallback=1.0):
    runs = str(runs)
    out = f"{runs}/p2"
    all_arms = [ref, *arms]
    probe = {"name": "probe_pair", "total": 4 * len(arms), "docker": True,
             "cmd": [py, "scripts/a6000/p2_probe.py", out, "--harness", "data/heldout1k/harness_s200", "--ids", "data/heldout1k/s200_valid_ids.txt", "--arms", *arms, "--levels", "2"],
             "proxy": None, "stats": {"type": "p2", "out": out, "arms": arms, "ids": []}, "purge": None,
             "post": [[py, "scripts/a6000/v7_counters.py", out, "--arm", arm, "--items-dir", f"probe_{arm}_T2", "--json", f"{runs}/{arm}_probe_counters.json"] for arm in arms]}
    s50 = {"name": "pair_s50", "total": 50 * len(arms), "docker": True,
           "cmd": [py, "scripts/a6000/p2_race.py", out, "--harness", "data/heldout1k/harness_s200", "--ids", "data/heldout1k/s200_valid_ids.txt", "--n", "50", "--conc", "2", "--arms", *all_arms,
                   "--arm-scale-from-probe", *[f"{arm}={scale_fallback}" for arm in all_arms], "--port", "8001", "--label", "probe", "--keep"],
           "proxy": {"listen": 8001, "host": "172.18.0.1", "log": f"{out}/proxy_pair_s50_think.jsonl"}, "speed_log": f"{out}/proxy_pair_s50_think.jsonl",
           "stats": {"type": "p2", "out": out, "arms": all_arms, "ids": IDS[:50]},
           "purge": [py, "scripts/a6000/p2_purge.py", out, "items"], "purge_since": [py, "scripts/a6000/p2_purge_since.py", out, "items"],
           "post": [[py, "scripts/a6000/p2_results_md.py", out, "--label", f"think adapters vs {ref} on the stage-1a ids (A6000 screen; {ref} rows from the P10 pair; vs {', '.join(COMPARATORS)})",
                     "--from", "0", "--to", "50", "--base", ref, "--arms", ref, *arms, *COMPARATORS],
                    [py, "scripts/a6000/p12_choose.py", out, "--ids", "data/heldout1k/s200_valid_ids.txt", "--n", "50", "--arms", *arms, "--ref", ref,
                     "--json", f"{runs}/p12_choice.json", "--log", "docs/a6000/P2_LOG.md"],
                    *[[py, "scripts/a6000/v7_counters.py", out, "--arm", arm, "--json", f"{runs}/{arm}_s50_counters.json"] for arm in arms],
                    [py, "scripts/a6000/backup_results.py"]]}
    # the chosen adapter (p12_choose -> autopilot_choice.json p4_arm) on the 74 public tasks: the day's submission needs the full
    # population run clean (0 crash rows) before any slot (the standing rule); sequential, the bundle's own budgets, as P4
    p4dir = f"{runs}/p4_adapter"
    p4 = {"name": "p4_adapter", "total": 74, "docker": False,
          "cmd": [py, "scripts/a6000/p4_run.py", "--out", p4dir, "--port", "8002"],
          "proxy": {"listen": 8002, "host": "127.0.0.1", "log": f"{runs}/p4_adapter_proxy.jsonl"}, "speed_log": f"{runs}/p4_adapter_proxy.jsonl",
          "stats": {"type": "results_jsonl", "file": f"{p4dir}/results.jsonl"},
          "purge": [py, "scripts/a6000/p4_purge.py", f"{p4dir}/results.jsonl"], "purge_since": [py, "scripts/a6000/p4_purge_since.py", f"{p4dir}/results.jsonl"],
          "post": [[py, "scripts/a6000/p4_judge.py", "--out", p4dir, "--proxy-log", f"{runs}/p4_adapter_proxy.jsonl"],
                   [py, "scripts/a6000/v7_counters.py", p4dir, "--json", f"{runs}/p4_adapter_counters.json"],
                   [py, "scripts/a6000/backup_results.py"]]}
    return [probe, s50, p4]


def finalize_hooks(runs, py):
    return [[py, "scripts/a6000/final_summary.py"], [py, "scripts/a6000/backup_results.py"],
            ["bash", "-c", "kill $(pgrep -f '[b]ackup_results.py --loop') 2>/dev/null; true"]]


def write_plan(path, runs, py, arms, serve_bundle, ref=REF, scale_fallback=1.0):
    plan = {"steps": p12_steps(runs, py, arms, ref, scale_fallback), "finalize": finalize_hooks(runs, py), "open": False, "serve_bundle": str(serve_bundle)}
    Path(path).write_text(json.dumps(plan, indent=1))
    return plan


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--serve-bundle", required=True, help="the union bundle (scripts/a6000/union_bundle.py) vLLM registers as LoRA modules")
    ap.add_argument("--arms", nargs="+", default=DEFAULT_ARMS); ap.add_argument("--ref", default=REF)
    ap.add_argument("--plan", default=str(G4 / "runs" / "autopilot_plan.json")); ap.add_argument("--scale-fallback", type=float, default=1.0); ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    py = str(G4 / "venv" / "bin" / "python")
    sb = Path(a.serve_bundle).expanduser()
    names = sorted(p.name for p in (sb / "adapters").iterdir() if p.is_dir()) if (sb / "adapters").is_dir() else []
    missing = [arm for arm in a.arms if not (ROOT / "submissions" / arm / "agent.yaml").is_file()]
    if missing:
        raise SystemExit(f"no bundle for arms {missing} under submissions/")
    if a.dry_run:
        print(json.dumps({"steps": [s["name"] for s in p12_steps(str(G4 / "runs"), py, a.arms, a.ref, a.scale_fallback)], "serve_bundle": str(sb), "adapters": names}))
        return 0
    if not names:
        raise SystemExit(f"{sb}: no adapters/<name>/ directories: build it with scripts/a6000/union_bundle.py first")
    plan = write_plan(a.plan, str(G4 / "runs"), py, a.arms, sb, a.ref, a.scale_fallback)
    print("plan steps:", [s["name"] for s in plan["steps"]], "| arms:", a.arms, "vs", a.ref, "| serve_bundle:", sb, "adapters:", names, "| open:", plan["open"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
