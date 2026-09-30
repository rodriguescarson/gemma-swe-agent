"""Merge oracle runs into the SWE-Pallets-X dev set: valid ids, per-task venv, summary and a DEV/HOLDOUT split.

  python3 scripts/pallets/finalize.py --results MAC.jsonl ... [--linux LINUX.jsonl ...]

Inside each group (Mac --results, Linux --linux) a task's row is its first VALID row in file order (so the default
venv wins over an era venv), else its row from the first file that has it. The verdict is the LINUX row when the task
has one (Linux is the scoring OS), else the Mac row; both verdicts are kept per task in split.json (mac_valid,
linux_valid), because the golden runner executes on the Mac. Writes (sorted keys, 1-space indent, trailing newline):
  data/pallets/valid_ids.txt              valid ids, sorted: harness-valid (gold resolves twice, empty does not) AND the
                                          slowest gold pytest run <= MARGIN_S (see below)
  data/pallets/slow_ids.txt               harness-valid ids excluded by MARGIN_S, with their gold pytest seconds
  data/pallets/task_env.json              {tid: venv} for the valid ids (read by scripts/pallets/source.py)
  data/pallets/oracle/summary.json        counts per repo x class, venvs, gold pytest times, the merge inputs' sha256
  data/pallets/split.json                 stratified split (below) + dev_order / holdout_order
  data/pallets/dev_ids.txt, holdout_ids.txt   one id per line, in dev_order / holdout_order
Split: strata = repo. Inside a stratum the tasks are sorted by gold-patch size (changed lines, ties by
sha256(f"{SEED}:{tid}")) and every third one is holdout, starting at offset int(sha256(f"{SEED}:{repo}"), 16) % 3:
systematic sampling, so dev and holdout get the same patch-size mix inside every repo (the golden spec's plain
"first k by sha" rule left this holdout at median 27 changed lines vs dev 16). No RNG; about FRAC = 1/3 holdout.
dev_order / holdout_order interleave the strata round-robin (strata sorted by name, each in sha order), so ANY prefix of
dev_order is spread across repos instead of being mostly click: run the first N for a cheaper, balanced subset.
"""
import argparse
import hashlib
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAL = ROOT / "data" / "pallets"
SEED = "pallets-v1"
STEP = 3                # every third task is holdout: about 60 of about 190, the size of the public leaderboard slice
CORE = ("pallets/click", "pallets/flask", "pallets/werkzeug")
SLOW_S = 60             # gold pytest slower than this: flagged "slow" in split.json (eats the agent's 5-min budget per test run)
MARGIN_S = 90           # gold pytest slower than this (on the verdict's machine) is NOT in the dev set: half the grader's 180 s
                        # timeout, so a machine 2x slower still grades the gold patch; sympy_37bde31 (160.8 s on Linux) already
                        # flipped to a timeout on the loaded Mac (gold1 passed, gold2 hung: results_sympy_mac2.jsonl)


def dump(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def merge(files) -> dict:
    out: dict = {}
    for f in files:
        for ln in Path(f).read_text().splitlines():
            if not ln.strip():
                continue
            r = json.loads(ln)
            tid = r["instance_id"]
            if tid not in out or (r.get("valid") and not out[tid].get("valid")):
                out[tid] = r
    return out


def gold_secs(row: dict):
    """Slowest gold pytest run of a row (seconds, on the machine that ran it), None when unknown."""
    vals = [x.get("pytest_s") for x in (row.get("gold1"), row.get("gold2")) if x and x.get("pytest_s") is not None]
    return max(vals) if vals else None


def changed_lines(patch: str) -> int:
    return sum(1 for ln in patch.splitlines() if ln[:1] in "+-" and not ln.startswith(("+++", "---")))


def order_key(tid: str) -> str:
    return hashlib.sha256(f"{SEED}:{tid}".encode()).hexdigest()


def round_robin(groups: dict) -> list:
    out, queues = [], [list(groups[k]) for k in sorted(groups)]
    while any(queues):
        for q in queues:
            if q:
                out.append(q.pop(0))
    return out


def q(vals):
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    return {"n": len(vals), "median": statistics.median(vals), "p90": vals[min(len(vals) - 1, int(0.9 * (len(vals) - 1) + 0.5))],
            "max": vals[-1], "sum": round(sum(vals), 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", nargs="+", default=[str(PAL / "oracle" / "results.jsonl")])
    ap.add_argument("--linux", nargs="*", default=[])
    a = ap.parse_args()
    tasks = {json.loads(ln)["instance_id"]: json.loads(ln) for ln in open(PAL / "tasks.jsonl") if ln.strip()}
    mac, lin = merge(a.results), merge(a.linux)
    final = {t: lin.get(t) or mac[t] for t in set(mac) | set(lin)}
    harness_valid = sorted(t for t, r in final.items() if r.get("valid"))
    slow_excl = {t: gold_secs(final[t]) for t in harness_valid if (gold_secs(final[t]) or 0) > MARGIN_S}
    valid = [t for t in harness_valid if t not in slow_excl]
    (PAL / "slow_ids.txt").write_text("".join(f"{t}\t{slow_excl[t]}\n" for t in sorted(slow_excl)))
    prs = json.loads((PAL / "pr_statements.json").read_text()) if (PAL / "pr_statements.json").is_file() else {}
    (PAL / "valid_ids.txt").write_text("".join(t + "\n" for t in valid))
    dump(PAL / "task_env.json", {t: final[t]["venv"] for t in valid})

    by_repo = defaultdict(Counter)
    for tid, t in tasks.items():
        r = final.get(tid)
        by_repo[t["repo"]]["tasks"] += 1
        by_repo[t["repo"]]["oracle_run"] += bool(r)
        by_repo[t["repo"]][(r or {}).get("cls", "not_run")] += 1
        if tid in slow_excl:
            by_repo[t["repo"]]["valid_but_slow_excluded"] += 1
    gold_s = defaultdict(list)
    for t in valid:
        g = [x.get("pytest_s") for x in (final[t].get("gold1"), final[t].get("gold2")) if x]
        gold_s[final[t]["repo"]].append(max((v for v in g if v is not None), default=None))
    summary = {
        "inputs": {str(Path(f).resolve().relative_to(ROOT)): sha(Path(f)) for f in [*a.results, *a.linux]},
        "linux_run": len(lin), "linux_mac_agree": sum(1 for t in lin if t in mac and lin[t]["valid"] == mac[t]["valid"]),
        "linux_mac_disagree": sorted(f"{t}: mac {mac[t]['cls']}, linux {lin[t]['cls']}" for t in lin
                                     if t in mac and lin[t]["valid"] != mac[t]["valid"]),
        "tasks": len(tasks), "oracle_run": len(final), "harness_valid": len(harness_valid),
        "excluded_slow": {t: slow_excl[t] for t in sorted(slow_excl)}, "margin_s": MARGIN_S, "valid": len(valid),
        "valid_core181": sum(1 for t in valid if tasks[t]["repo"] in CORE),
        "by_repo": {k: dict(v) for k, v in sorted(by_repo.items())},
        "valid_by_venv": dict(Counter(final[t]["venv"] for t in valid)),
        "gold_pytest_seconds_by_repo": {k: q(v) for k, v in sorted(gold_s.items())},
        "valid_by_created_year": dict(sorted(Counter(tasks[t]["created_at"][:4] for t in valid).items())),
    }
    dump(PAL / "oracle" / "summary.json", summary)

    strata = defaultdict(list)
    for t in valid:
        strata[tasks[t]["repo"].split("/")[-1]].append(t)
    split = {"schema": "pallets-split-v1", "seed": SEED, "holdout_every": STEP,
             "rule": "strata = repo; sort by (gold changed lines, sha256(f'{seed}:{tid}')); holdout = every STEP-th "
                     "from offset int(sha256(f'{seed}:{repo}'),16) % STEP; dev_order/holdout_order = repo round-robin "
                     "in sha order",
             "inputs": {"data/pallets/valid_ids.txt": sha(PAL / "valid_ids.txt"),
                        "data/pallets/tasks.jsonl": sha(PAL / "tasks.jsonl")},
             "strata": {}, "tasks": {}}
    dev_g, hold_g = {}, {}
    for name in sorted(strata):
        by_size = sorted(strata[name], key=lambda t: (changed_lines(tasks[t]["patch"]), order_key(t)))
        off = int(hashlib.sha256(f"{SEED}:{name}".encode()).hexdigest(), 16) % STEP
        hold_set = set(by_size[off::STEP])
        ids = sorted(strata[name], key=order_key)
        hold, dev = [t for t in ids if t in hold_set], [t for t in ids if t not in hold_set]
        split["strata"][name] = {"n": len(ids), "holdout": hold, "dev": dev}
        dev_g[name], hold_g[name] = dev, hold
        for t in ids:
            split["tasks"][t] = {"split": "holdout" if t in hold else "dev", "repo": name, "venv": final[t]["venv"],
                                 "era_env": final[t]["venv"] != name, "created_at": tasks[t]["created_at"],
                                 "core181": tasks[t]["repo"] in CORE, "mac_valid": (mac.get(t) or {}).get("valid"),
                                 "linux_valid": (lin.get(t) or {}).get("valid"),
                                 "pr_statement": "title" in prs.get(t, {}), "gold_pytest_s": gold_secs(final[t]),
                                 "slow": (gold_secs(final[t]) or 0) > SLOW_S}
    split["dev_order"] = round_robin(dev_g)
    split["holdout_order"] = round_robin(hold_g)
    split["counts"] = {"dev": len(split["dev_order"]), "holdout": len(split["holdout_order"])}
    dump(PAL / "split.json", split)
    (PAL / "dev_ids.txt").write_text("".join(t + "\n" for t in split["dev_order"]))
    (PAL / "holdout_ids.txt").write_text("".join(t + "\n" for t in split["holdout_order"]))
    print(json.dumps({"valid": len(valid), "dev": split["counts"]["dev"], "holdout": split["counts"]["holdout"],
                      "strata": {k: v["n"] for k, v in split["strata"].items()}}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
