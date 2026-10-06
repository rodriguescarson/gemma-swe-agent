"""Build SFT rows from what the P3 pass finished (docs/v4h/GATE.md, 'P2 addendum 4', step 4): merge the items' results, train/build_sft.py (test-verified successes only,
the 200 sample ids refused), train/rebalance_rows.py with the v11b recipe, train/validate_rows.py; counts and the preference-pair count to GATE.md and P2_LOG.md.

    python scripts/a6000/p3_build.py [--out ~/g4/runs/p3] [--no-append]"""
import argparse, glob, json, os, subprocess, sys, time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PY = str(Path.home() / "g4" / "venv" / "bin" / "python")


def merge_results(out, dest):
    n = 0
    with open(dest, "w") as w:
        for f in sorted(glob.glob(os.path.join(out, "items", "*", "*", "task_results.jsonl"))):
            for line in open(f):
                if line.strip():
                    w.write(line if line.endswith("\n") else line + "\n"); n += 1
    return n


def commands(out, tasks):
    ex = ["--exclude-ids", str(ROOT / "data" / "heldout1k" / "sample200_ids.txt"), "--exclude-ids", str(ROOT / "data" / "heldout1k" / "s200_valid_ids.txt")]
    return {"sft": [PY, "train/build_sft.py", "--capture", f"{out}/capture.jsonl", "--tasks", tasks, "--results", f"{out}/results_all.jsonl", "--out", f"{out}/rows.jsonl", *ex],
            "rebalance": [PY, "train/rebalance_rows.py", f"{out}/rows.jsonl", "--out", f"{out}/rows_rebalanced.jsonl", "--report", f"{out}/rebalance_report.json", "--drop-repeats",
                          "--max-tool-share", "read_file=0.15", "--max-per-task", "200", "--drop-unknown-tools"],
            "validate": [PY, "train/validate_rows.py", f"{out}/rows_rebalanced.jsonl", *ex, "--min-rows", "0", "--no-tokenizer", "--report", f"{out}/validate_report.json"]}


def pair_count(attempts):
    """Tasks with both a solved and a failed attempt (a preference pair needs two attempts of one task)."""
    return sum(1 for v in attempts.values() if any(v) and not all(v))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=str(Path.home() / "g4" / "runs" / "p3")); ap.add_argument("--no-append", action="store_true")
    a = ap.parse_args(argv)
    out = a.out
    n = merge_results(out, f"{out}/results_all.jsonl")
    rows = [json.loads(l) for l in open(f"{out}/results_all.jsonl") if l.strip()]
    attempts = {}
    for r in rows:
        attempts.setdefault(r["instance_id"], []).append(bool(r.get("resolved")))
    solved = sum(any(v) for v in attempts.values())
    tasks = str(ROOT / "data" / "heldout1k" / "harness_p3" / "tasks.jsonl")
    cmds = commands(out, tasks)
    res = {}
    for name, c in cmds.items():
        r = subprocess.run(c, cwd=ROOT, capture_output=True, text=True)
        res[name] = (r.returncode, (r.stdout + r.stderr)[-300:])
    prof = {}
    try:
        prof = json.load(open(f"{out}/rebalance_report.json"))
    except Exception:
        pass
    nrows = sum(1 for _ in open(f"{out}/rows.jsonl")) if os.path.exists(f"{out}/rows.jsonl") else 0
    nreb = sum(1 for _ in open(f"{out}/rows_rebalanced.jsonl")) if os.path.exists(f"{out}/rows_rebalanced.jsonl") else 0
    cap = sum(1 for _ in open(f"{out}/capture.jsonl")) if os.path.exists(f"{out}/capture.jsonl") else 0
    text = (f"\n### P3 data report ({time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}; ONE pass, bundle {Path(out, 'ARM').read_text().strip() if Path(out, 'ARM').exists() else '?'}, "
            f"stopped at the hard stop; weights and data stay out of git)\n"
            f"- tasks finished {len(attempts)} (solved {solved}); captured model calls {cap}\n"
            f"- SFT rows (test-verified successes only, sample-200 ids refused): {nrows}; after rebalance (drop repeats, read_file share 0.15, 200 per task, unknown tools dropped): {nreb}\n"
            f"- rebalance profile: `{json.dumps(prof)[:400]}`\n"
            f"- validation rc: {res['validate'][0]} (build rc {res['sft'][0]}, rebalance rc {res['rebalance'][0]}); `{res['validate'][1].strip()[-160:]}`\n"
            f"- preference pairs (a solved and a failed attempt of the same task): **{pair_count(attempts)}** (a single pass cannot produce pairs; they need a second attempt per task)\n")
    print(text)
    if not a.no_append:
        with open(ROOT / "docs" / "v4h" / "GATE.md", "a") as f:
            f.write(text)
        with open(ROOT / "docs" / "a6000" / "P2_LOG.md", "a") as f:
            f.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
