#!/usr/bin/env python3
"""Checks added on 2026-10-30 for paper 23 (rigor items X9, X11, X13, XL2 and the outside reader's objections 1 and 2).

Reads the competition repository (read only; never written):

    python3 analysis/decision_checks.py --repo <path to a gemma-swe-agent checkout>

Writes results/decision_checks.json, results/decision_checks.md, results/decision_macros.tex,
results/exclusions.tex (appendix table), and results/checksums.sha256 (X13 manifest). Aggregates only: no task text,
patches or traces are written. Runs on a laptop CPU in about a minute. No network, no model, no GPU.

What it computes
  X9   how many of the 74 tasks were created on or before the Gemma 4 pretraining cutoff recorded in the repository
       (January 2025, from the Hugging Face model card, per research/hidden.md), and the local-versus-hidden rank
       correlation computed on the older tasks only and on the newer tasks only (paced A6000, seven configurations).
  X11  a reason for each complete 74-task run and each Kaggle submission that the paper does not analyse, with the
       checks that back the reason (is the bundle's name in any submission description; did it score).
       Also the rank correlation on Kaggle's four-L4 runs with the one omitted scored bundle (v9_eog) added.
  Obj1 a decision-level count over the 21 pairs of paced configurations: when the local gap is at least the repeat
       noise floor (4 tasks), did the local winner also score higher on the hidden set?
  Obj2 the dates of every hidden read that enters the correlation tables (all after the 30 September scorer rebuild),
       per-repository correlations, and the older/newer task split above.
  XL2  a search of what the agent saw (tool observations in the traces of every analysed run) for lines that occur only
       in the hidden tests (test_patch) or only in the reference patch, excluding text in the problem statement and text
       the agent itself wrote earlier in the same trace.
  X13  sha256 of every input file the analyses read, so a later run can verify them.
"""
from __future__ import annotations

import argparse
import collections
import glob
import hashlib
import io
import json
import re
import statistics as st
import sys
import tarfile
from datetime import datetime
from math import comb
from pathlib import Path

import numpy as np
from scipy.stats import beta, rankdata

HERE = Path(__file__).resolve().parent
OUT = HERE / "results"
sys.path.insert(0, str(HERE))
import calibration_robustness as cr  # noqa: E402  (reuses rho, exact_perm_p)

CUTOFF = "2025-01-31"        # "January 2025": the last day of the month, the most generous reading
REBUILD = "2026-09-30"       # scorer rebuild, docs/v4h/THINK_SLOT.md and docs/v4h/GATE.md

# the seven paced-A6000 configurations of Table 2: name -> (result dirs relative to eval/, hidden scores, submission tags)
A6000 = {
    "thinking-only variant": (["a6000/results/p4_v0t2"], [0.10], ["sub16"]),
    "thinking budget 1,024": (["a6000/results/p4_b1024"], [0.10], ["sub15b"]),
    "public sampling + heredoc edits, 60 s commands": (["a6000/results/p4_v15b"], [0.10], ["sub22"]),
    "baseline": (["a6000/results/p4_v12", "a6000/results/p4_v12r"], [0.15, 0.13], ["sub14", "sub21"]),
    "baseline + public sampling": (["a6000/results/p4_v12b"], [0.17], ["sub20"]),
    "baseline + two prompt rules": (["a6000/results/p4_v13", "a6000/results/p4_v13r"], [0.13], ["sub17"]),
    "public sampling + 6-minute cap": (["a6000/results/p4_v12b6"], [0.15], ["sub23"]),
}
L4 = {
    "staged agent": (["kaggle/g4-l4-v4-wh28-p312"], [0.05], ["sub10"]),
    "+ edit helper": (["kaggle/g4-l4-v4h2-p312"], [0.10, 0.08], ["sub9", "sub12"]),
    "+ recovery step": (["kaggle/g4-l4-v4h2g-p312"], [0.08], ["sub11"]),
    "baseline (on L4)": (["kaggle/g4-l4-v12-p312"], [0.15], ["sub14"]),
}
# the one omitted bundle that has both a complete local run and a hidden score
L4_OMITTED = {"v9_eog (omitted)": (["kaggle/g4-l4-v9-eog"], [0.06], ["sub4"])}
A6000_OMITTED = {"v5h2 = v4h2 (omitted)": (["a6000/results/p4"], [0.10, 0.08], ["sub9", "sub12"])}
ANALYSED_DIRS = {d for g in (A6000, L4) for v in g.values() for d in v[0]}

# complete 74-task runs the paper does not analyse: dir -> (configuration, reason). Facts below are checked against the
# submission list in main(); the free-text reasons come from the run records named in the table.
EXCLUDED = {
    "a6000/results/p4": ("v5h2 (the repository's notes equate it with the submitted v4h2)",
                         "A6000 run of v5h2; docs/GAPS_2026-10-06.md line 6 writes v4h2 = v5h2, and v4h2 has hidden reads 0.10 and 0.08, "
                         "but Table 2 pairs v4h2 with its L4 run only; added back in the sensitivity row"),
    "a6000/results/p4_v7": ("v7", "no hidden read: bundle never submitted"),
    "a6000/results/p4_v7c": ("v7c", "no hidden read: bundle never submitted"),
    "a6000/results/p4_v7d": ("v7d", "no hidden read: bundle never submitted"),
    "decide_out": ("v5h2-think (identical per-task results to kaggle/g4-l4-v5h2-think-p312, counted once)",
                   "no hidden read: bundle never submitted"),
    "kaggle/e74_v2": ("v2", "its only submission (sub2) failed on a platform resource error, so no hidden score"),
    "kaggle/e74_v3": ("v3", "no hidden read: bundle never submitted; replaced by v4"),
    "kaggle/g4-l4-v4": ("v4, 28 Sept run", "second local run of an analysed configuration; the paper uses the 3 Oct rerun "
                        "(wh28, same wheelhouse as the other L4 rows, taken beside the rebuilt-scorer read)"),
    "kaggle/g4-l4-v4h2f-p312": ("v4h2f", "no hidden read: bundle never submitted (v4h2g was submitted later)"),
    "kaggle/g4-l4-v5h2-t0-p312": ("v5h2-t0", "no hidden read: thinking-off control for local pairing only, never submitted"),
    "kaggle/g4-l4-v7c-t0-p312": ("v7c-t0", "no hidden read: thinking-off control for local pairing only, never submitted"),
    "kaggle/g4-l4-v9-eog": ("v9_eog", "scored 0.06 as sub4 on 28 Sept, before the scorer rebuild; its local run is on Kaggle "
                            "L4s, and its hidden read is on the old scorer, so it was left out of the main correlation; "
                            "added back in the sensitivity row"),
}
SUB_OMITTED = {
    "v0": "starter bundle with no local 74-task run (it is the competition sample, calibration of the submission path)",
    "sub2": "failed: platform resource error (two of our own kernels were running); no score",
    "sub4": "v9_eog, scored 0.06 on the old scorer (28 Sept); see sensitivity row",
    "sub7": "failed: unhandled error in our bundle while rerunning; no score",
}
SUB_REPEAT_ONLY = {"sub3", "sub5", "sub6", "sub8"}   # old-scorer v4 and v10.1 reads: used in the repeats text only



def run_file(ev, d):
    """results.jsonl of a run folder; decide_out (a local copy) falls back to its original in a public clone."""
    p = Path(ev) / d / "results.jsonl"
    if not p.exists() and d == "decide_out":
        p = Path(ev) / "kaggle" / "g4-l4-v5h2-think-p312" / "results.jsonl"
    return p


def tasks_path(repo):
    """data/raw/tasks.jsonl in the author's checkout; data/tasks.jsonl in the public clone (same file, moved)."""
    p = Path(repo) / "data" / "raw" / "tasks.jsonl"
    return p if p.exists() else Path(repo) / "data" / "tasks.jsonl"


def rows_of(f: Path) -> list[dict]:
    return [json.loads(x) for x in f.read_text().splitlines() if x.strip()]


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def clopper_pearson(k: int, n: int, a: float = 0.05) -> tuple[float, float]:
    lo = 0.0 if k == 0 else float(beta.ppf(a / 2, k, n - k + 1))
    hi = 1.0 if k == n else float(beta.ppf(1 - a / 2, k + 1, n - k))
    return lo, hi


def per_task(ev: Path, dirs: list[str]) -> dict[str, float]:
    """Mean over the runs of one configuration of the 0/1 solved indicator, per task id."""
    acc = collections.defaultdict(list)
    for d in dirs:
        for r in rows_of(run_file(ev, d)):
            acc[r["id"]].append(1.0 if r.get("resolved") else 0.0)
    return {k: st.mean(v) for k, v in acc.items()}


def spearman(x, y) -> float:
    return cr.rho(list(x), list(y))


def strings_of(o) -> list[str]:
    out = []
    if isinstance(o, str):
        out.append(o)
    elif isinstance(o, dict):
        for v in o.values():
            out += strings_of(v)
    elif isinstance(o, list):
        for v in o:
            out += strings_of(v)
    return out


def added_lines(diff: str) -> set[str]:
    keep = set()
    for ln in diff.splitlines():
        if ln.startswith("+") and not ln.startswith("+++"):
            s = ln[1:].strip()
            if len(s) >= 40 and not s.startswith(("#", "import ", "from ", '"""', "//")):
                keep.add(s)
    return keep


def new_test_files(diff: str) -> set[str]:
    return set(re.findall(r"^\+\+\+ b/(\S+)", diff, re.M)) & set(
        re.findall(r"^--- /dev/null\n\+\+\+ b/(\S+)", diff, re.M))


def trace_iter(ev: Path, d: str):
    """Yield (task id, trace dict) for one result dir (A6000 folder of json files, or Kaggle tar.gz)."""
    folder = ev / d / "results" / "traces"
    if folder.is_dir():
        for f in sorted(folder.glob("trace_*.json")):
            yield f.stem[len("trace_"):], json.loads(f.read_text())
        return
    tgz = ev / d / "traces.tar.gz"
    with tarfile.open(tgz) as tf:
        for m in tf:
            if m.isfile() and re.search(r"traces/trace_.*\.json$", m.name):
                yield Path(m.name).stem[len("trace_"):], json.load(io.TextIOWrapper(tf.extractfile(m), encoding="utf-8"))


def test_files(diff: str) -> set[str]:
    return set(re.findall(r"^\+\+\+ b/(\S+)", diff, re.M))


def agent_view_check(ev: Path, tasks: dict, dirs: list[str]) -> dict:
    """What did the environment show the agent? Two screens per trace, loose and strict.

    Loose: some tool observation contains a line (40+ characters) that only the hidden tests (test_patch) or only the
    reference patch add, absent from the problem statement and from anything the agent had itself written earlier.
    Many such lines also exist in the repository's own source (a test repeats a line of the code it tests), so loose hits
    are an upper bound, not a leak count.
    Strict (the count that matters): for the hidden tests, the step's call names a file that test_patch edits and the
    observation contains an added line; for the reference patch, one observation contains three or more distinct added
    lines of it, which duplication of existing code would rarely produce."""
    n_traces = 0
    out = {k: [] for k in ("loose_test", "strict_test", "loose_ref", "strict_ref", "new_test_path")}
    for d in dirs:
        for tid, tr in trace_iter(ev, d):
            t = tasks.get(tid)
            if not t:
                continue
            n_traces += 1
            statement = (t["problem_statement"] or "") + (t.get("hints_text") or "")
            tl = {x for x in added_lines(t["test_patch"]) if x not in statement}
            rl = {x for x in added_lines(t["patch"]) if x not in statement}
            tf = test_files(t["test_patch"])
            nf = new_test_files(t["test_patch"])
            written = ""
            flags = dict.fromkeys(out, False)
            for step in tr.get("steps", []):
                obs = "\n".join(strings_of(step.get("observation") or "")).replace("\\n", "\n")
                calls = json.dumps(step.get("tool_calls") or "")
                if step.get("source") == "agent":
                    written += "\n" + "\n".join(strings_of(step.get("message"))) + "\n".join(strings_of(step.get("tool_calls")))
                    written = written.replace("\\n", "\n")
                if not obs:
                    continue
                ht = [x for x in tl if x in obs and x not in written]
                hr = [x for x in rl if x in obs and x not in written]
                if ht:
                    flags["loose_test"] = True
                    if any(f in calls for f in tf):
                        flags["strict_test"] = True
                if hr:
                    flags["loose_ref"] = True
                    if len(hr) >= 3:
                        flags["strict_ref"] = True
                if any(pth in obs for pth in nf):
                    flags["new_test_path"] = True
            for k, v in flags.items():
                if v:
                    out[k].append((d, tid))
    out["traces_read"] = n_traces
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    repo = Path(ap.parse_args().repo)
    ev = repo / "eval"
    res: dict = {"repo_head": None}
    import subprocess
    res["repo_head"] = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()

    tasks_all = {r["instance_id"]: r for r in rows_of(tasks_path(repo))}
    valid = set((repo / "data" / "kaggle_valid_ids.txt").read_text().split())
    tasks = {k: v for k, v in tasks_all.items() if k in valid}
    assert len(tasks) == 74, len(tasks)

    # ---- submissions -------------------------------------------------------------------------------------------------
    snap = sorted(glob.glob(str(ev / "analysis" / "out" / "kaggle_submissions_*.json")))[-1]
    subs = json.load(open(snap))["submissions"]
    sub_by_tag = {}
    first_names = set()
    for s in subs:
        m = re.match(r"(v0|sub\d+b?):?\s*([\w.\-]+)", s["description"] or "")
        tag = m.group(1) if m else None
        sub_by_tag[tag] = s
        if m:
            first_names.add(m.group(2).lower())
    res["submission_first_tokens"] = sorted(first_names)

    # ---- X9: cutoff ---------------------------------------------------------------------------------------------------
    created = {k: v["created_at"][:10] for k, v in tasks.items()}
    pre = {k for k, d in created.items() if d <= CUTOFF}
    post = set(created) - pre
    res["cutoff"] = {"date_used": CUTOFF, "source": "repository note research/hidden.md: Gemma 4 pretraining cutoff January 2025 "
                     "(Hugging Face model card); not re-verified against the card in this run",
                     "tasks_created_on_or_before": len(pre), "tasks_created_after": len(post),
                     "by_repo_pre": dict(collections.Counter(k.split("_")[0] for k in pre)),
                     "by_repo_post": dict(collections.Counter(k.split("_")[0] for k in post))}

    # per-configuration local solves on older and newer tasks, and by repository
    def local_split(group):
        names, hid, tot, lpre, lpost, repo_sc = [], [], [], [], [], collections.defaultdict(list)
        for name, (dirs, hidden, _) in group.items():
            pt = per_task(ev, dirs)
            names.append(name)
            hid.append(st.mean(hidden))
            tot.append(sum(pt.values()))
            lpre.append(sum(v for k, v in pt.items() if k in pre))
            lpost.append(sum(v for k, v in pt.items() if k in post))
            for rp in ("fastapi", "rich"):
                repo_sc[rp].append(sum(v for k, v in pt.items() if k.startswith(rp + "_")))
        return names, np.array(hid), np.array(tot), np.array(lpre), np.array(lpost), repo_sc

    names, hid, tot, lpre, lpost, repo_sc = local_split(A6000)
    res["a6000_split"] = {
        "configs": names, "hidden_mean": hid.tolist(), "local_mean_all": tot.tolist(),
        "local_older": lpre.tolist(), "local_newer": lpost.tolist(),
        "rho_all": spearman(tot, hid), "rho_older_tasks": spearman(lpre, hid), "rho_newer_tasks": spearman(lpost, hid),
        "perm_p_older": cr.exact_perm_p(lpre, list(hid), cr.rho), "perm_p_newer": cr.exact_perm_p(lpost, list(hid), cr.rho),
        "solve_rate_older": float(lpre.sum() / (len(pre) * len(names))),
        "solve_rate_newer": float(lpost.sum() / (len(post) * len(names))),
        "rho_fastapi_only": spearman(repo_sc["fastapi"], hid), "rho_rich_only": spearman(repo_sc["rich"], hid),
        "perm_p_fastapi": cr.exact_perm_p(repo_sc["fastapi"], list(hid), cr.rho),
        "perm_p_rich": cr.exact_perm_p(repo_sc["rich"], list(hid), cr.rho)}
    assert abs(res["a6000_split"]["rho_all"] - 0.49) < 0.01, res["a6000_split"]["rho_all"]

    # ---- Obj 2: hidden-read dates -----------------------------------------------------------------------------------------
    dates = {}
    for grp in (A6000, L4):
        for name, (_, hidden, tags) in grp.items():
            for tg in tags:
                s = sub_by_tag[tg]
                assert abs(float(s["public_score"] or -1) - hidden[tags.index(tg)]) < 1e-9 or s["public_score"] in (None, ""), (tg, s["public_score"])
                dates[tg] = s["date"][:10]
    res["hidden_reads_in_tables"] = {"n": len(dates), "earliest": min(dates.values()), "latest": max(dates.values()),
                                     "rebuild_date": REBUILD, "all_after_rebuild": all(d > REBUILD for d in dates.values()), "by_tag": dates}

    # ---- Obj 1: decision-level pairs ------------------------------------------------------------------------------------------
    FLOOR = 4
    wins = ties = losses = 0
    pairs = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            gap = tot[i] - tot[j]
            if abs(gap) < FLOOR:
                continue
            w, l = (i, j) if gap > 0 else (j, i)
            if hid[w] > hid[l] + 1e-9:
                wins += 1
                out = "higher"
            elif abs(hid[w] - hid[l]) <= 1e-9:
                ties += 1
                out = "tie"
            else:
                losses += 1
                out = "lower"
            pairs.append({"local_winner": names[w], "local_loser": names[l], "local_gap": float(abs(gap)), "hidden_outcome": out})
    n_dec = wins + losses
    lo, hi = clopper_pearson(wins, n_dec) if n_dec else (float("nan"), float("nan"))
    res["decision_pairs"] = {"local_gap_floor_tasks": FLOOR, "pairs_total": len(names) * (len(names) - 1) // 2,
                             "pairs_at_or_above_floor": len(pairs), "winner_scored_higher": wins, "tied": ties,
                             "winner_scored_lower": losses, "share_higher_of_decided": (wins / n_dec if n_dec else None),
                             "clopper_pearson_95": [lo, hi], "pairs": pairs}

    # ---- X11: omitted runs and submissions ---------------------------------------------------------------------------------------
    inv = json.load(open(OUT / "run_inventory.json"))
    # decide_out is a local copy of kaggle/g4-l4-v5h2-think-p312; a public clone has only the original, so name them alike
    complete = [{"kaggle/g4-l4-v5h2-think-p312": "decide_out"}.get(r["dir"], r["dir"]) for r in inv["complete_74_task_runs"]["runs"]]
    rows_x = []
    analysed_all = [d for d in complete if d not in EXCLUDED]
    assert len(analysed_all) == 20 and ANALYSED_DIRS <= set(analysed_all), (len(analysed_all), ANALYSED_DIRS - set(analysed_all))
    for d in complete:
        if d not in EXCLUDED:
            continue
        rr = rows_of(run_file(ev, d))
        cfg, why = EXCLUDED[d]          # KeyError = a complete run with no recorded reason: fail loudly
        rows_x.append({"dir": d, "config": cfg, "solved": sum(bool(r.get("resolved")) for r in rr),
                       "wall_hours": round(sum(r.get("secs") or 0 for r in rr) / 3600, 2), "reason": why})
    assert len(rows_x) == len(EXCLUDED), (len(rows_x), len(EXCLUDED))
    # check the "never submitted" claims against the submission list
    never = {"v5h2", "v7", "v7c", "v7d", "v5h2-think", "v3", "v4h2f", "v5h2-t0", "v7c-t0"}
    clash = never & first_names
    assert not clash, f"configuration named in a submission after all: {clash}"
    res["omitted_complete_runs"] = rows_x
    # omitted submissions
    om = []
    for tg, why in SUB_OMITTED.items():
        s = sub_by_tag[tg]
        om.append({"tag": tg, "date": s["date"][:10], "score": s.get("public_score") or None, "reason": why})
    res["omitted_submissions"] = om
    used = {tg for g in (A6000, L4) for v in g.values() for tg in v[2]} | {"sub18", "sub19"} | SUB_REPEAT_ONLY
    res["submission_accounting"] = {"total": len(subs), "used_in_tables_or_repeats": sorted(used), "omitted": sorted(SUB_OMITTED),
                                    "n_used": len(used), "n_omitted": len(SUB_OMITTED), "n_total_matches": len(used) + len(SUB_OMITTED) == len(subs)}

    # sensitivity: L4 group with the omitted scored bundle
    def group_rho(group):
        x, y = [], []
        for _, (dirs, hidden, _) in group.items():
            x.append(sum(per_task(ev, dirs).values()))
            y.append(st.mean(hidden))
        return x, y

    x4, y4 = group_rho(L4)
    x5, y5 = group_rho({**L4, **L4_OMITTED})
    pooled_x = x5 + list(tot)
    pooled_y = y5 + list(hid)
    res["sensitivity_with_v9_eog"] = {"l4_rho_n4": spearman(x4, y4), "l4_rho_n5": spearman(x5, y5),
                                      "l4_perm_p_n5": cr.exact_perm_p(x5, y5, cr.rho),
                                      "pooled_rho_n12": spearman(pooled_x, pooled_y),
                                      "note": "v9_eog's hidden read (0.06) is on the old scorer; the others are after the rebuild"}

    xa, ya = group_rho(A6000)
    xb, yb = group_rho({**A6000, **A6000_OMITTED})
    res["sensitivity_with_v5h2"] = {"a6000_rho_n7": spearman(xa, ya), "a6000_rho_n8": spearman(xb, yb),
                                    "a6000_perm_p_n8": cr.exact_perm_p(xb, yb, cr.rho),
                                    "note": "p4 = v5h2, which docs/GAPS_2026-10-06.md equates with the submitted v4h2 (hidden 0.10, 0.08)"}

    # ---- XL2: what the agent saw ------------------------------------------------------------------------------------------------
    def _have_traces(d):
        p = ev / d
        return (p / "results" / "traces").is_dir() or (p / "traces.tar.gz").exists()
    if not all(_have_traces(d) for d in analysed_all):
        # Traces are gitignored, so a public clone has none: keep the numbers from the previous full run and say so.
        prev = json.load(open(OUT / "decision_checks.json"))["agent_view"]
        prev["reused_from_previous_run"] = "traces are not in the public repository; this block was not recomputed"
        print("NOTE: traces missing (not public); agent-view numbers reused from the previous run", file=sys.stderr)
        res["agent_view"] = prev
        chk = None
    else:
        chk = agent_view_check(ev, tasks, sorted(analysed_all))
    if chk is not None:
      res["agent_view"] = {"runs_searched": len(analysed_all), "traces_read": chk["traces_read"],
                           "loose_hidden_test_line_n": len(chk["loose_test"]), "strict_hidden_test_n": len(chk["strict_test"]),
                           "loose_reference_line_n": len(chk["loose_ref"]), "strict_reference_n": len(chk["strict_ref"]),
                           "new_test_file_path_seen_n": len(chk["new_test_path"]),
                           "strict_hidden_test": chk["strict_test"], "strict_reference": chk["strict_ref"],
                           "distinct_tasks_loose_test": len({t for _, t in chk["loose_test"]}),
                           "distinct_tasks_strict_test": len({t for _, t in chk["strict_test"]}),
                           "distinct_tasks_strict_ref": len({t for _, t in chk["strict_ref"]}),
                           "method": agent_view_check.__doc__}

    # ---- X13: checksums ---------------------------------------------------------------------------------------------------------
    inputs = [tasks_path(repo), repo / "data" / "kaggle_valid_ids.txt", Path(snap),
              ev / "ledger.md", ev / "experiments.sqlite"]
    for d in sorted(set(analysed_all) | {x["dir"] for x in rows_x}):
        inputs.append(run_file(ev, d))
    for t in sorted(set(analysed_all) | {x["dir"] for x in rows_x}):
        tgz = ev / t / "traces.tar.gz"
        if tgz.exists():
            inputs.append(tgz)
    lines = [f"{sha(p)}  {p.relative_to(repo)}" for p in inputs if p.exists()]
    missing = [str(p.relative_to(repo)) for p in inputs if not p.exists()]
    (OUT / "checksums.sha256").write_text(
        "# sha256 of the competition-repository files the paper's analyses read (generated by analysis/decision_checks.py).\n"
        f"# repository HEAD {res['repo_head']}. Verify: cd <repo> && shasum -a 256 -c <this file> (comment lines are skipped).\n"
        "# The A6000 per-task traces are folders of JSON files and are covered by results.jsonl only.\n"
        + "\n".join(lines) + "\n")
    res["checksums"] = {"files": len(lines), "missing": missing}

    OUT.mkdir(exist_ok=True)
    (OUT / "decision_checks.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
    write_md(res)
    write_tex(res)
    print((OUT / "decision_checks.md").read_text())
    return 0


def f2(v):
    return f"{v:+.2f}".replace("-", "\\textminus{}") if v == v else "n/a"


def write_tex(r: dict) -> None:
    s, c, d, sv, av = r["a6000_split"], r["cutoff"], r["decision_pairs"], r["sensitivity_with_v9_eog"], r["agent_view"]
    hr = r["hidden_reads_in_tables"]
    m = {
        "cutoffDate": "January 2025", "nPreCut": str(c["tasks_created_on_or_before"]), "nPostCut": str(c["tasks_created_after"]),
        "rhoOlder": f"{s['rho_older_tasks']:+.2f}", "rhoNewer": f"{s['rho_newer_tasks']:+.2f}",
        "pOlder": f"{s['perm_p_older']:.2f}", "pNewer": f"{s['perm_p_newer']:.2f}",
        "rateOlder": f"{100 * s['solve_rate_older']:.0f}", "rateNewer": f"{100 * s['solve_rate_newer']:.0f}",
        "rhoFastapi": f"{s['rho_fastapi_only']:+.2f}", "rhoRich": f"{s['rho_rich_only']:+.2f}",
        "pairsFloor": str(d["local_gap_floor_tasks"]), "pairsN": str(d["pairs_at_or_above_floor"]), "pairsTotal": str(d["pairs_total"]),
        "pairsHigher": str(d["winner_scored_higher"]), "pairsTied": str(d["tied"]), "pairsLower": str(d["winner_scored_lower"]),
        "pairsCILo": f"{d['clopper_pearson_95'][0]:.2f}", "pairsCIHi": f"{d['clopper_pearson_95'][1]:.2f}",
        "hiddenFirstRead": hr["earliest"], "hiddenLastRead": hr["latest"], "nHiddenReads": str(hr["n"]),
        "rhoLfive": f"{sv['l4_rho_n5']:+.2f}", "rhoPoolTwelve": f"{sv['pooled_rho_n12']:+.2f}",
        "rhoAeight": f"{r['sensitivity_with_v5h2']['a6000_rho_n8']:+.2f}", "pAeight": f"{r['sensitivity_with_v5h2']['a6000_perm_p_n8']:.2f}",
        "tracesRead": str(av["traces_read"]), "leakTestLoose": str(av["loose_hidden_test_line_n"]),
        "leakTestStrict": str(av["strict_hidden_test_n"]), "leakRefLoose": str(av["loose_reference_line_n"]),
        "leakRefStrict": str(av["strict_reference_n"]), "leakNewN": str(av["new_test_file_path_seen_n"]),
        "leakTestStrictTasks": str(av["distinct_tasks_strict_test"]), "leakRefStrictTasks": str(av["distinct_tasks_strict_ref"]),
        "nChecksums": str(r["checksums"]["files"]),
        "nExclTotal": str(len(r["omitted_complete_runs"])),
        "nExclNoRead": str(sum(x["reason"].startswith("no hidden read") for x in r["omitted_complete_runs"])),
        "nScoringTests": str(len(re.findall(r"^    def test_", (HERE / "test_scoring.py").read_text(), re.M))),
    }
    for k in ("rhoOlder", "rhoNewer", "rhoFastapi", "rhoRich", "rhoLfive", "rhoPoolTwelve", "rhoAeight"):
        m[k] = m[k].replace("-", "\\textminus{}")
    t = ["% generated by analysis/decision_checks.py; do not edit"]
    for k, v in m.items():
        t.append(f"\\newcommand{{\\{k}}}{{{v}}}")
    (OUT / "decision_macros.tex").write_text("\n".join(t) + "\n")
    rows = []
    esc = lambda x: x.replace("_", "\\_").replace("%", "\\%").replace("&", "\\&")
    for x in r["omitted_complete_runs"]:
        rows.append(f"{esc(x['config'].split(' (')[0])} & {x['solved']} & {esc(x['reason'])} \\\\")
    body = "\n".join(rows)
    (OUT / "exclusions.tex").write_text(
        "% generated by analysis/decision_checks.py; do not edit\n\\begin{tabular}{lrp{0.62\\linewidth}}\n\\toprule\n"
        "configuration & solved & why it is not in the analysis \\\\\n\\midrule\n" + body + "\n\\bottomrule\n\\end{tabular}\n")


def write_md(r: dict) -> None:
    s, c, d, sv, av = r["a6000_split"], r["cutoff"], r["decision_pairs"], r["sensitivity_with_v9_eog"], r["agent_view"]
    L = ["# Decision checks (generated by analysis/decision_checks.py; do not edit)", "",
         f"Repository HEAD {r['repo_head'][:10]}.", "",
         "## X9 contamination split", "",
         f"Cutoff used: {c['date_used']} ({c['source']}). Tasks created on or before: {c['tasks_created_on_or_before']}; after: "
         f"{c['tasks_created_after']}. By repository (older / newer): {c['by_repo_pre']} / {c['by_repo_post']}.", "",
         f"Paced A6000, 7 configurations: rho all tasks {s['rho_all']:+.2f}; older tasks only {s['rho_older_tasks']:+.2f} "
         f"(p {s['perm_p_older']:.2f}); newer tasks only {s['rho_newer_tasks']:+.2f} (p {s['perm_p_newer']:.2f}). "
         f"Mean solve rate older {100*s['solve_rate_older']:.0f}%, newer {100*s['solve_rate_newer']:.0f}%. "
         f"By repository: fastapi only {s['rho_fastapi_only']:+.2f} (p {s['perm_p_fastapi']:.2f}), rich only {s['rho_rich_only']:+.2f} "
         f"(p {s['perm_p_rich']:.2f}).", "",
         "## Scorer version", "",
         f"{r['hidden_reads_in_tables']['n']} hidden reads enter the correlation tables, dated {r['hidden_reads_in_tables']['earliest']} to "
         f"{r['hidden_reads_in_tables']['latest']}; rebuild {r['hidden_reads_in_tables']['rebuild_date']}; all after: "
         f"{r['hidden_reads_in_tables']['all_after_rebuild']}.", "",
         "## Decision-level pairs", "",
         f"{d['pairs_at_or_above_floor']} of {d['pairs_total']} pairs have a local gap of at least {d['local_gap_floor_tasks']} tasks; the "
         f"local winner scored higher on {d['winner_scored_higher']}, tied on {d['tied']}, lower on {d['winner_scored_lower']}. Share higher of "
         f"decided pairs {d['share_higher_of_decided']}, exact 95% interval {d['clopper_pearson_95']}.", "",
         "## X11 sensitivity", "",
         f"Kaggle 4xL4 rho n=4 {sv['l4_rho_n4']:+.2f}; with v9_eog n=5 {sv['l4_rho_n5']:+.2f} (exact p {sv['l4_perm_p_n5']:.2f}); pooled 12 rows "
         f"{sv['pooled_rho_n12']:+.2f}. {sv['note']}.", "",
         f"Paced A6000 with the omitted v5h2 = v4h2 run added (n=8): rho {r['sensitivity_with_v5h2']['a6000_rho_n8']:+.2f} "
         f"(exact p {r['sensitivity_with_v5h2']['a6000_perm_p_n8']:.2f}); n=7 {r['sensitivity_with_v5h2']['a6000_rho_n7']:+.2f}. {r['sensitivity_with_v5h2']['note']}.", "",
         "## X11 complete runs not analysed", "", "| dir | configuration | solved | wall h | reason |", "|---|---|---|---|---|"]
    for x in r["omitted_complete_runs"]:
        L.append(f"| {x['dir']} | {x['config']} | {x['solved']} | {x['wall_hours']} | {x['reason']} |")
    L += ["", "## X11 submissions not analysed", "", "| tag | date | score | reason |", "|---|---|---|---|"]
    for x in r["omitted_submissions"]:
        L.append(f"| {x['tag']} | {x['date']} | {x['score']} | {x['reason']} |")
    L += ["", f"Accounting: {r['submission_accounting']}", "",
          "## XL2 agent view", "",
          f"Traces read {av['traces_read']} across {av['runs_searched']} analysed runs. Loose screen (upper bound): traces where a tool "
          f"observation showed a 40+ character line added only by the hidden tests {av['loose_hidden_test_line_n']} "
          f"({av['distinct_tasks_loose_test']} tasks), only by the reference patch {av['loose_reference_line_n']}. Strict screen: hidden-test "
          f"line shown by a call that names a test file test_patch edits {av['strict_hidden_test_n']} ({av['distinct_tasks_strict_test']} tasks); "
          f"three or more reference-patch lines in one observation {av['strict_reference_n']} ({av['distinct_tasks_strict_ref']} tasks); path of "
          f"a test file the hidden tests create seen: {av['new_test_file_path_seen_n']}.", "",
          f"Method: {av['method']}", "",
          f"Strict hidden-test hits: {av['strict_hidden_test']}", f"Strict reference-patch hits: {av['strict_reference']}", "",
          f"## X13 checksums", "", f"{r['checksums']['files']} files in results/checksums.sha256; missing: {r['checksums']['missing']}."]
    (OUT / "decision_checks.md").write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    sys.exit(main())
