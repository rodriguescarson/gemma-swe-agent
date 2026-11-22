#!/usr/bin/env python3
"""Run inventory, outcome categories, per-repository results and ledger counts for paper 23 (rigor sweep X18, X20-X23, XL1).

Reads the competition repository (read only; it is not in this folder):

    python3 analysis/run_inventory.py --repo <path to a gemma-swe-agent checkout>

and writes results/run_inventory.json, results/run_inventory.md, results/inventory_macros.tex and the two table
fragments results/outcomes.tex and results/by_repo.tex (copied into draft-emse/tables/ by draft-emse/make_emse.py).
Only aggregates are written: no traces, patches or task text.

What it counts
  * every directory holding a complete 74-task result set (results.jsonl with 74 distinct task ids), by setup, with
    wall hours (the sum of the per-task wall seconds the runs recorded: tool and model time, not model loading);
  * duplicates (identical per-task results under two names) are counted once;
  * every Kaggle submission in the newest snapshot (eval/analysis/out/kaggle_submissions_*.json): scored, over the
    twelve-hour limit, or failed for another reason, and how many distinct bundles that is;
  * the rented-pod spend recorded in eval/ledger.md;
  * the claim log's pre-registered / observed split (eval/analysis/check_claims.py, which reads git and prints a table).
"""
from __future__ import annotations

import argparse
import collections
import glob
import hashlib
import json
import re
import statistics as st
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "results"

# configurations of Tables 1 and 2 of the paper: (label, results dir relative to eval/, setup)
ANALYSED = [
    ("staged agent (v4)", "kaggle/g4-l4-v4-wh28-p312", "L4"),
    ("+ edit helper (v4h2)", "kaggle/g4-l4-v4h2-p312", "L4"),
    ("+ recovery step (v4h2g)", "kaggle/g4-l4-v4h2g-p312", "L4"),
    ("baseline (v12, L4)", "kaggle/g4-l4-v12-p312", "L4"),
    ("thinking-only (v0-think)", "a6000/results/p4_v0t2", "A6000"),
    ("thinking budget 1,024", "a6000/results/p4_b1024", "A6000"),
    ("public sampling + L1, L2 (v15b)", "a6000/results/p4_v15b", "A6000"),
    ("baseline (v12), run 1", "a6000/results/p4_v12", "A6000"),
    ("baseline (v12), run 2", "a6000/results/p4_v12r", "A6000"),
    ("baseline + public sampling (v12b)", "a6000/results/p4_v12b", "A6000"),
    ("baseline + L1, L2 (v13), run 1", "a6000/results/p4_v13", "A6000"),
    ("baseline + L1, L2 (v13), run 2", "a6000/results/p4_v13r", "A6000"),
    ("v12b, 6-minute cap (v12b6)", "a6000/results/p4_v12b6", "A6000"),
    ("public 0.24 notebook (8 min)", "a6000/results/p4_pub024", "A6000"),
]



# Result folders added after the period this paper reports (submissions to 21 Oct 2026): the repository has moved on since
# the analysis was pinned (HEAD badaaa102a), and these would change the run counts. Added 4 to 7 Nov 2026 (sub28 gate run,
# time-ladder run and its rescore).
AFTER_PERIOD = {"kaggle/g4-l4-v12b55-p312", "kaggle/g4-ladder-rescore", "kaggle/g4-ladder-v12b8"}


def tasks_path(repo):
    """data/raw/tasks.jsonl in the author's checkout; data/tasks.jsonl in the public clone (same file, moved)."""
    p = Path(repo) / "data" / "raw" / "tasks.jsonl"
    return p if p.exists() else Path(repo) / "data" / "tasks.jsonl"


def rows_of(f: Path) -> list[dict]:
    out = []
    for line in f.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def tid(r: dict) -> str:
    return r.get("id") or r.get("task") or r.get("instance_id") or ""


def fingerprint(rows: list[dict]) -> str:
    return hashlib.sha256(json.dumps(sorted((tid(r), bool(r.get("resolved")), round(r.get("secs") or 0, 1)) for r in rows)).encode()).hexdigest()[:16]


def category(r: dict) -> str:
    capped = "timeout" in (r.get("err") or "")
    if r.get("resolved"):
        return "solved"
    if not r.get("patch"):
        return "empty patch, cap hit" if capped else "empty patch, ended early"
    return "patch fails, cap hit" if capped else "patch fails, ended early"


def sh(repo: Path, *a: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True).stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    repo = Path(ap.parse_args().repo)
    ev = repo / "eval"
    res: dict = {"repo_head": sh(repo, "rev-parse", "HEAD"), "repo_branch": sh(repo, "branch", "--show-current"),
                 "repo_tags": sh(repo, "tag").splitlines()}

    # ---- complete 74-task runs ----------------------------------------------------------------------------------
    seen: dict[str, str] = {}
    complete, partial = [], []
    for f in sorted(glob.glob(str(ev / "**" / "results.jsonl"), recursive=True)):
        rows = rows_of(Path(f))
        d = str(Path(f).parent.relative_to(ev))
        if d in AFTER_PERIOD:
            continue
        ids = {tid(r) for r in rows}
        # decide_out is a copy of a Kaggle 4xL4 run (identical per-task results to kaggle/g4-l4-v5h2-think-p312)
        setup = "A6000" if d.startswith("a6000") else ("L4" if d.startswith(("kaggle", "decide_out")) else "other")
        item = {"dir": d, "setup": setup, "rows": len(rows), "solved": sum(bool(r.get("resolved")) for r in rows),
                "wall_hours": round(sum(r.get("secs") or 0 for r in rows) / 3600, 2)}
        if len(ids) == 74 and len(rows) == 74:
            fp = fingerprint(rows)
            item["duplicate_of"] = seen.get(fp)
            seen.setdefault(fp, d)
            complete.append(item)
        elif len(rows) >= 5 and not d.startswith("a6000/results/q_"):
            partial.append(item)
    import sqlite3
    db = sqlite3.connect(ev / "experiments.sqlite")
    pod = []
    for cfg, n, s, secs in db.execute("select config, count(*), sum(resolved), sum(secs) from runs group by config"):
        pod.append({"config": cfg, "rows": n, "solved": s, "wall_hours": round((secs or 0) / 3600, 2)})
    uniq = [c for c in complete if not c["duplicate_of"]]
    by_setup = collections.Counter(c["setup"] for c in uniq)
    res["complete_74_task_runs"] = {
        "unique_by_setup": dict(by_setup), "duplicates_dropped": [c["dir"] for c in complete if c["duplicate_of"]],
        "a6000_wall_hours_complete_runs": round(sum(c["wall_hours"] for c in uniq if c["setup"] == "A6000"), 1),
        "kaggle_l4_wall_hours_complete_runs": round(sum(c["wall_hours"] for c in uniq if c["setup"] == "L4"), 1),
        "runs": uniq, "partial_or_smaller_runs_5plus_rows": partial,
        "experiments_sqlite_pod_runs": pod,
        "note": "wall hours are sums of recorded per-task seconds; setup and model-load time are not in them. "
                "experiments.sqlite holds H100-pod runs of 25-26 Sep; some may duplicate Kaggle runs of the same bundle."}
    all_a = [r for r in glob.glob(str(ev / "a6000" / "results" / "*" / "results.jsonl"))]
    res["a6000_all_rows_wall_hours"] = round(sum(sum(r.get("secs") or 0 for r in rows_of(Path(f))) for f in all_a) / 3600, 1)
    res["a6000_results_dirs"] = len(all_a)

    # ---- outcome categories and per-repository solves for the configurations of Tables 1 and 2 -----------------------
    cats = ["solved", "patch fails, ended early", "patch fails, cap hit", "empty patch, ended early", "empty patch, cap hit"]
    table = []
    repos_tot = collections.Counter()
    for label, d, setup in ANALYSED:
        rows = rows_of(ev / d / "results.jsonl")
        if len(rows) != 74:
            print("skip (not 74 rows):", d, len(rows), file=sys.stderr)
            continue
        c = collections.Counter(category(r) for r in rows)
        rep = collections.Counter(tid(r).split("_")[0] for r in rows if r.get("resolved"))
        repos_tot = collections.Counter(tid(r).split("_")[0] for r in rows)
        table.append({"label": label, "dir": d, "setup": setup, **{k: c.get(k, 0) for k in cats},
                      "zero_calls": sum((r.get("calls") or 0) == 0 for r in rows),
                      "mean_s": round(st.mean(r.get("secs") or 0 for r in rows)),
                      "solved_by_repo": dict(rep)})
    res["outcomes"] = table
    res["public_74_by_repo"] = dict(repos_tot)

    # ---- creation dates of the 74 tasks (contamination note; aggregates only) ---------------------------------------------
    valid = set((repo / "data" / "kaggle_valid_ids.txt").read_text().split())
    dates = sorted(r["created_at"][:10] for r in rows_of(tasks_path(repo)) if r["instance_id"] in valid)
    res["task_creation_dates"] = {"n": len(dates), "first": dates[0], "last": dates[-1],
                                  "by_year": dict(collections.Counter(d[:4] for d in dates)),
                                  "note": "created_at of the task record; the model's training-data cutoff is not recorded in the repository"}

    # ---- submissions ---------------------------------------------------------------------------------------------------
    snap = sorted(glob.glob(str(ev / "analysis" / "out" / "kaggle_submissions_*.json")))[-1]
    subs = json.load(open(snap))["submissions"]
    sc, runtime, other = [], [], []
    for s in subs:
        err = (s.get("error_description") or "")
        if s.get("public_score") not in (None, ""):
            sc.append(s)
        elif "exceeded" in err.lower() or "runtime" in err.lower():
            runtime.append(s)
        else:
            other.append(s)
    dates = sorted(datetime.fromisoformat(s["date"]) for s in subs)
    res["kaggle_submissions"] = {
        "snapshot": Path(snap).name, "total": len(subs), "scored": len(sc), "over_twelve_hours": len(runtime),
        "failed_other": len(other), "first": str(dates[0]), "last": str(dates[-1]),
        "scores": [{"ref": s["ref"], "date": s["date"][:10], "tag": (re.match(r"(v0|sub\d+b?):?", s["description"] or "") or [None, None])[1],
                    "public_score": s.get("public_score") or None,
                    "status": "scored" if s in sc else ("over 12 h" if s in runtime else "failed")} for s in subs],
        "note": "later submissions (sub24 onward) exist in the repository log after this snapshot and are outside the period the paper reports"}

    # ---- ledger spend ----------------------------------------------------------------------------------------------------
    led = (ev / "ledger.md").read_text().splitlines()
    spend = []
    for line in led:
        cells = [c.strip() for c in line.split("|")]
        # one row per finished cost ("~$..."); launch-time estimates and hourly rates are not added
        if len(cells) > 4 and cells[3].startswith("~$") and "launched" not in cells[2]:
            spend.append({"when": cells[1], "what": cells[2][:80], "cost": cells[3]})
    res["ledger_pod_spend_rows"] = spend
    res["ledger_last_row"] = led[-1].split("|")[1].strip() if led else None

    # ---- claim log -----------------------------------------------------------------------------------------------------------
    p = subprocess.run([sys.executable, str(repo / "eval" / "analysis" / "check_claims.py")], cwd=repo, capture_output=True, text=True)
    kinds = collections.Counter()
    verdict = collections.Counter()
    for line in p.stdout.splitlines():
        m = re.match(r"\| (C\d+b?|D\d+) \| ([^|]+) \| [^|]+ \| .* \| (ok|post hoc|pending|FAIL|VIOLATION) \|$", line)
        if m:
            kinds["pre-registered" if m.group(2).strip().startswith("pre-registered") else "observed"] += 1
            verdict[(("pre" if m.group(2).strip().startswith("pre-registered") else "obs"), m.group(3))] += 1
    res["claim_log"] = {"claims": sum(kinds.values()), "rule_committed_first": kinds["pre-registered"], "observed_post_hoc": kinds["observed"],
                        "order_ok": verdict[("pre", "ok")], "rule_first_result_pending": verdict[("pre", "pending")],
                        "order_violations": verdict[("pre", "FAIL")] + verdict[("pre", "VIOLATION")],
                        "check_claims_exit": p.returncode}

    OUT.mkdir(exist_ok=True)
    (OUT / "run_inventory.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
    write_tex(res)
    write_md(res)
    print((OUT / "run_inventory.md").read_text())
    return 0


def write_tex(r: dict) -> None:
    cats = ["solved", "patch fails, ended early", "patch fails, cap hit", "empty patch, ended early", "empty patch, cap hit"]
    L = ["% generated by analysis/run_inventory.py; do not edit",
         "\\setlength{\\tabcolsep}{3pt}", "\\begin{tabular}{lrrrrrr}", "\\toprule",
         "configuration & solved & patch fails & empty patch & cap hit & zero calls & mean s \\\\",
         "\\midrule"]
    for t in r["outcomes"]:
        L.append(f"{t['label']} & {t['solved']} & {t['patch fails, ended early'] + t['patch fails, cap hit']} & "
                 f"{t['empty patch, ended early'] + t['empty patch, cap hit']} & "
                 f"{t['patch fails, cap hit'] + t['empty patch, cap hit']} & {t['zero_calls']} & {t['mean_s']} \\\\")
    L += ["\\bottomrule", "\\end{tabular}"]
    (OUT / "outcomes.tex").write_text("\n".join(L) + "\n")
    tot = r["public_74_by_repo"]
    names = sorted(tot, key=lambda k: -tot[k])
    L = ["% generated by analysis/run_inventory.py; do not edit", "\\begin{tabular}{l" + "r" * len(names) + "}", "\\toprule",
         "configuration & " + " & ".join(f"{n} (of {tot[n]})" for n in names) + " \\\\", "\\midrule"]
    for t in r["outcomes"]:
        L.append(f"{t['label']} & " + " & ".join(str(t['solved_by_repo'].get(n, 0)) for n in names) + " \\\\")
    L += ["\\bottomrule", "\\end{tabular}"]
    (OUT / "by_repo.tex").write_text("\n".join(L) + "\n")
    c, k, cl = r["complete_74_task_runs"], r["kaggle_submissions"], r["claim_log"]
    spend = 0.0
    for s in r["ledger_pod_spend_rows"]:
        m = re.search(r"\$([\d.]+)", s["cost"])
        spend += float(m.group(1)) if m else 0
    M = {
        "nRunsA": c["unique_by_setup"].get("A6000", 0), "nRunsL": c["unique_by_setup"].get("L4", 0),
        "nRunsPod": sum(1 for p_ in c["experiments_sqlite_pod_runs"] if p_["rows"] == 74),
        "nRunsAll": sum(c["unique_by_setup"].values()) + sum(1 for p_ in c["experiments_sqlite_pod_runs"] if p_["rows"] == 74),
        "hoursA": f"{r['a6000_all_rows_wall_hours']:.0f}", "hoursACompl": f"{c['a6000_wall_hours_complete_runs']:.0f}",
        "hoursL": f"{c['kaggle_l4_wall_hours_complete_runs']:.0f}",
        "nSubs": k["total"], "nSubsScored": k["scored"], "nSubsRuntime": k["over_twelve_hours"], "nSubsFailed": k["failed_other"],
        "subsFirst": k["first"][:10], "subsLast": k["last"][:10],
        "nClaims": cl["claims"], "nClaimsPre": cl["rule_committed_first"], "nClaimsObs": cl["observed_post_hoc"],
        "nClaimsPreOk": cl["order_ok"], "nClaimsPrePending": cl["rule_first_result_pending"],
        "podSpend": f"{spend:.0f}",
        "taskFirst": r["task_creation_dates"]["first"], "taskLast": r["task_creation_dates"]["last"],
        "tasksYrD": r["task_creation_dates"]["by_year"].get("2026", 0),
        "tasksYrA": r["task_creation_dates"]["by_year"].get("2023", 0),
        "tasksYrB": r["task_creation_dates"]["by_year"].get("2024", 0),
        "tasksYrC": r["task_creation_dates"]["by_year"].get("2025", 0),
    }
    (OUT / "inventory_macros.tex").write_text("% generated by analysis/run_inventory.py; do not edit\n" +
                                              "\n".join(f"\\newcommand{{\\{k}}}{{{v}}}" for k, v in M.items()) + "\n")


def write_md(r: dict) -> None:
    c, k = r["complete_74_task_runs"], r["kaggle_submissions"]
    L = ["# Run inventory (generated by analysis/run_inventory.py; do not edit)", "",
         f"Repository HEAD {r['repo_head'][:10]} on branch {r['repo_branch']}; tags: {r['repo_tags'] or 'none'}.", "",
         f"Complete 74-task runs (unique): {c['unique_by_setup']}; duplicates dropped: {c['duplicates_dropped']}.",
         f"A6000 wall hours: complete runs {c['a6000_wall_hours_complete_runs']}, all rows {r['a6000_all_rows_wall_hours']} "
         f"({r['a6000_results_dirs']} result folders); Kaggle L4 complete-run wall hours {c['kaggle_l4_wall_hours_complete_runs']} (4 GPUs each).", "",
         "| dir | setup | solved | wall h |", "|---|---|---|---|"]
    L += [f"| {x['dir']} | {x['setup']} | {x['solved']} | {x['wall_hours']} |" for x in c["runs"]]
    L += ["", "Partial runs (5 or more rows, not 74):", ""]
    L += [f"- {x['dir']}: {x['rows']} rows, {x['solved']} solved, {x['wall_hours']} h" for x in c["partial_or_smaller_runs_5plus_rows"]]
    L += ["", "experiments.sqlite pod runs: " + "; ".join(f"{p['config']} {p['solved']}/{p['rows']}" for p in c["experiments_sqlite_pod_runs"]), "",
          f"Kaggle submissions in {k['snapshot']}: total {k['total']}, scored {k['scored']}, over 12 h {k['over_twelve_hours']}, "
          f"failed otherwise {k['failed_other']}; {k['first'][:10]} to {k['last'][:10]}.", "",
          "| ref | date | tag | score | status |", "|---|---|---|---|---|"]
    L += [f"| {s['ref']} | {s['date']} | {s['tag']} | {s['public_score']} | {s['status']} |" for s in k["scores"]]
    L += ["", f"Ledger rows with a stated pod cost: {len(r['ledger_pod_spend_rows'])}; ledger's last row dated {r['ledger_last_row']}.", ""]
    L += [f"- {s['when']}: {s['what']} ({s['cost']})" for s in r["ledger_pod_spend_rows"]]
    L += ["", f"Task creation dates: {r['task_creation_dates']}"]
    L += ["", f"Claim log: {r['claim_log']}", "", "## Outcome categories (74 tasks each)", ""]
    L += [json.dumps(t) for t in r["outcomes"]]
    (OUT / "run_inventory.md").write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    sys.exit(main())
