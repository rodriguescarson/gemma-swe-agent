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


def merge_results_per_pass(out, passes):
    """items/<arm>/<task>__s<k>/task_results.jsonl -> <out>/s<k>/task_results.jsonl per pass (the layout train/build_sft.py --pair and scripts/collect/pairs.py use),
    and the union into results_all.jsonl. -> {k: rows}"""
    per = {}
    with open(f"{out}/results_all.jsonl", "w") as w:
        for k in range(1, passes + 1):
            d = Path(out) / f"s{k}"; d.mkdir(exist_ok=True)
            n = 0
            with open(d / "task_results.jsonl", "w") as wk:
                for f in sorted(glob.glob(os.path.join(out, "items", "*", f"*__s{k}", "task_results.jsonl"))):
                    for line in open(f):
                        if line.strip():
                            wk.write(line if line.endswith("\n") else line + "\n"); w.write(line if line.endswith("\n") else line + "\n"); n += 1
            per[k] = n
    return per


def attempts_from(results_all):
    attempts = {}
    for line in open(results_all):
        if line.strip():
            r = json.loads(line)
            attempts.setdefault(r["instance_id"], []).append(bool(r.get("resolved")))
    return attempts


def pairs_raw(attempts):
    """Tasks with both a solved and a failed attempt: the raw material of (chosen, rejected) pairs. The SDK's training schema is produced on the Mac
    (the adaption package is not installed here, so its format is not guessed): per task the solved and the failed pass numbers."""
    out = []
    for t, v in sorted(attempts.items()):
        if any(v) and not all(v):
            out.append({"task": t, "solved_passes": [i + 1 for i, x in enumerate(v) if x], "failed_passes": [i + 1 for i, x in enumerate(v) if not x]})
    return out


def commands(out, tasks, passes=1):
    ex = ["--exclude-ids", str(ROOT / "data" / "heldout1k" / "sample200_ids.txt"), "--exclude-ids", str(ROOT / "data" / "heldout1k" / "s200_valid_ids.txt")]
    if passes > 1:
        src = [x for k in range(1, passes + 1) for x in ("--pair", f"{out}/capture_s{k}.jsonl={out}/s{k}/task_results.jsonl")]
    else:
        src = ["--capture", f"{out}/capture.jsonl", "--results", f"{out}/results_all.jsonl"]
    return {"sft": [PY, "train/build_sft.py", *src, "--tasks", tasks, "--out", f"{out}/rows.jsonl", *ex],
            "rebalance": [PY, "train/rebalance_rows.py", f"{out}/rows.jsonl", "--out", f"{out}/rows_rebalanced.jsonl", "--report", f"{out}/rebalance_report.json", "--drop-repeats",
                          "--max-tool-share", "read_file=0.15", "--max-per-task", "200", "--drop-unknown-tools"],
            "validate": [PY, "train/validate_rows.py", f"{out}/rows_rebalanced.jsonl", *ex, "--min-rows", "0", "--no-tokenizer", "--report", f"{out}/validate_report.json"]}


def thought_line(out):
    """The P11 rows gate (2026-10-11): rows whose completion starts with a non-empty thought channel / rows, from validate_report.json."""
    try:
        v = json.load(open(f"{out}/validate_report.json"))
    except Exception:
        return "- thoughts: validate_report.json missing (no rows were validated)\n"
    n, t = int(v.get("rows") or 0), int(v.get("rows_with_thought") or 0)
    return f"- thoughts: {t} of {n} rebalanced rows carry a non-empty thought channel (share {(t / n) if n else 0.0:.2f}; the P11 rows gate is >= 0.80)\n"


def pair_count(attempts):
    """Tasks with both a solved and a failed attempt (a preference pair needs two attempts of one task)."""
    return sum(1 for v in attempts.values() if any(v) and not all(v))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=str(Path.home() / "g4" / "runs" / "p3")); ap.add_argument("--no-append", action="store_true")
    ap.add_argument("--passes", type=int, default=1)
    a = ap.parse_args(argv)
    out = a.out
    if not os.path.isdir(out):                                    # P3 never started (for example the GPU was busy until the hard stop)
        text = (f"\n### P3 data report ({time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())})\n- P3 did not run: no output directory, so no tasks finished, 0 SFT rows, 0 preference pairs.\n")
        print(text)
        if not a.no_append:
            for f in (ROOT / "docs" / "v4h" / "GATE.md", ROOT / "docs" / "a6000" / "P2_LOG.md"):
                with open(f, "a") as fh:
                    fh.write(text)
        return 0
    if a.passes > 1:
        per = merge_results_per_pass(out, a.passes)
    else:
        merge_results(out, f"{out}/results_all.jsonl"); per = None
    attempts = attempts_from(f"{out}/results_all.jsonl")
    solved = sum(any(v) for v in attempts.values())
    raw = pairs_raw(attempts)
    Path(out, "pairs_raw.jsonl").write_text("".join(json.dumps(r) + "\n" for r in raw))
    tasks = str(ROOT / "data" / "heldout1k" / "harness_p3" / "tasks.jsonl")
    cmds = commands(out, tasks, a.passes)
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
    cap = sum(sum(1 for _ in open(f)) for f in glob.glob(f"{out}/capture*.jsonl"))
    text = (f"\n### P3 data report ({time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}; ONE pass, bundle {Path(out, 'ARM').read_text().strip() if Path(out, 'ARM').exists() else '?'}, "
            f"stopped at the hard stop; weights and data stay out of git)\n"
            f"- tasks finished {len(attempts)} (solved in at least one pass {solved}); attempts {sum(len(v) for v in attempts.values())}"
            + (f" over {a.passes} passes (rows per pass {per})" if per else "") + f"; captured model calls {cap}\n"
            f"- SFT rows (test-verified successes only, sample-200 ids refused): {nrows}; after rebalance (drop repeats, read_file share 0.15, 200 per task, unknown tools dropped): {nreb}\n"
            f"- rebalance profile: `{json.dumps(prof)[:400]}`\n"
            f"- validation rc: {res['validate'][0]} (build rc {res['sft'][0]}, rebalance rc {res['rebalance'][0]}); `{res['validate'][1].strip()[-160:]}`\n"
            + thought_line(out) +
            f"- preference pairs (a solved and a failed attempt of the same task): **{pair_count(attempts)}** (raw material in pairs_raw.jsonl: task, solved passes, failed passes; the Adaption SDK's "
            f"alignment schema is applied on the Mac, the package is not installed here)\n")
    print(text)
    if not a.no_append:
        with open(ROOT / "docs" / "v4h" / "GATE.md", "a") as f:
            f.write(text)
        with open(ROOT / "docs" / "a6000" / "P2_LOG.md", "a") as f:
            f.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
