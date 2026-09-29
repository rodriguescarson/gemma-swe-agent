#!/usr/bin/env python3
"""Build the golden-eval fixtures (docs/eval/GOLDEN_EVALS_SPEC.md v1.1 sections 2 and 4, component a).

    .venv/bin/python scripts/golden/build_fixtures.py -j 6        # build (cold 4.5-5.5 min measured, warm ~25 s)
    .venv/bin/python scripts/golden/build_fixtures.py --check     # rebuild in memory, exit 1 if a committed file differs

Writes, deterministically (sorted keys, 1-space indent, trailing newline): eval/golden/split.json,
eval/golden/fixtures/{task_fixtures,MANIFEST}.json and eval/golden/datasets/{L,F,V}_{dev,holdout}.json. Reads the
hand-written eval/golden/fixtures/plan_overrides.json. Every result that runs code in a task tree (gradability, repro
validation, wrong-patch qualification, replay validation, hidden-node outcomes) is cached per task in
~/.cache/g4/golden/<tid>.json (override G4_GOLDEN_CACHE) under the sha256 of exactly the inputs it depends on, so a
warm build or --check reuses it and a changed input recomputes only what it feeds. --no-cache recomputes everything.
A cold rebuild (empty cache) writes the same bytes: the committed evidence never records whether a load-dependent
flake fired (KNOWN_FLAKY retries run alone under fixture_lib.LOAD and are only logged), and failure reasons list the
failing node ids other than known flakes instead of pytest's counts.

Exit codes: 0 ok; 1 --check found a difference; 2 leak violations remain after overrides (listed), or a bad
overrides file, or a failed static phase. Nothing here touches the network, a model, Kaggle or a pod.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import fixture_lib as F  # noqa: E402

# Bump an op's version when the code that computes it changes meaning; the cache key includes it.
OP_VERSION = {"gradable": 3, "nodes": 1, "repro": 2, "replay": 2, "canonical": 2, "wrong_mv": 3, "hidden": 3}


# ------------------------------------------------------------------------------------------------------- cache
class Cache:
    """Per-task JSON cache: {"entries": {key: result}}. One task is handled by one thread, so a file has one writer;
    save() keeps only the keys this build used, so stale entries drop out."""

    def __init__(self, root: Path = F.CACHE_DIR, enabled: bool = True):
        self.root, self.enabled = Path(root), enabled
        self.used: dict = {}
        self.data: dict = {}
        self.hits = self.misses = 0
        self.lock = threading.Lock()

    def _load(self, tid: str) -> dict:
        with self.lock:
            if tid not in self.data:
                p = self.root / f"{tid}.json"
                d = {}
                if self.enabled and p.is_file():
                    try:
                        d = json.loads(p.read_text()).get("entries") or {}
                    except (OSError, ValueError):
                        d = {}
                self.data[tid] = d
            return self.data[tid]

    def get(self, tid: str, op: str, inputs: dict, fn):
        """The cached result of fn() for these inputs; fn runs outside the lock (several ops of a task run at once)."""
        key = F.sha_obj({"op": op, "v": OP_VERSION[op], "builder": F.BUILDER_VERSION, **inputs})
        entries = self._load(tid)
        with self.lock:
            self.used.setdefault(tid, set()).add(key)
            if self.enabled and key in entries and "result" in entries[key]:
                self.hits += 1
                return entries[key]["result"]
            self.misses += 1
        res = fn()
        if isinstance(res, dict) and res.get("error"):
            return res                                   # never cache a crash or a skip
        with self.lock:
            entries[key] = {"op": op, "result": res}
        return res

    def save(self, tid: str) -> None:
        with self.lock:
            if tid not in self.data:
                return
            keep = {k: v for k, v in self.data[tid].items() if k in self.used.get(tid, ())}
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.root / f".{tid}.json.{os.getpid()}.{threading.get_ident()}"
        tmp.write_text(json.dumps({"tid": tid, "builder": F.BUILDER_VERSION, "entries": keep}, sort_keys=True))
        os.replace(tmp, self.root / f"{tid}.json")


def stamp(path: Path):
    try:
        st = Path(path).stat()
    except OSError:
        return None
    return [st.st_size, int(st.st_mtime)]


# ------------------------------------------------------------------------------------------------------- context
class Ctx:
    def __init__(self, no_cache: bool = False):
        self.T = F._T()
        self.ids = F.load_ids()
        self.rows = F.load_rows()
        self.catalog = F.load_catalog()
        self.split = F.build_split()
        self.overrides = load_overrides()
        self.traces = {tid: F.load_trace(tid) for tid in self.ids}
        self.t0 = F.compute_t0({k: v for k, v in self.traces.items() if v is not None})
        self.helpers_sha = F.sha_tree(F.BUNDLE_SCRIPTS)
        self.cache = Cache(enabled=not no_cache)

    def task_inputs(self, tid: str) -> dict:
        """What every exec op of a task depends on (4.6 cache key): task row, snapshot and kpar stamps, helpers."""
        T = self.T
        kmark = T.kpar_dir(tid) / ".g4_kpar_ok"
        return {"tid": tid, "row": F.sha_obj(self.rows[tid]), "snapshot": stamp(T.SNAP_DIR / f"{tid}.tgz"),
                "kpar": stamp(kmark), "helpers": self.helpers_sha, "mv_timeout": F.MV_TIMEOUT}


def load_overrides(path: Path = F.OVERRIDES_FILE) -> dict:
    if not Path(path).is_file():
        return {}
    data = json.loads(Path(path).read_text())
    return {k: v for k, v in data.items() if not k.startswith("_")}


def check_overrides(overrides: dict, ids: list) -> list:
    errs = []
    for tid, ov in overrides.items():
        if tid not in ids:
            errs.append(f"plan_overrides.json: unknown task {tid}")
            continue
        if not isinstance(ov, dict) or not (ov.get("FIX") or ov.get("CAUSE")):
            errs.append(f"plan_overrides.json: {tid} needs FIX and/or CAUSE")
        if not ov.get("why"):
            errs.append(f"plan_overrides.json: {tid} needs a why")
        bad = set(ov) - {"FIX", "CAUSE", "why"}
        if bad:
            errs.append(f"plan_overrides.json: {tid} has unknown keys {sorted(bad)}")
    return errs


# ------------------------------------------------------------------------------------------------------- static
class RepoIndex:
    """Rule-2 lookups over the original repository: git grep on the harness-exact base workspace (snapshot), or the
    gold patch's context and removed lines (no snapshot)."""

    def __init__(self, ctx: Ctx, tid: str):
        self.T, self.tid = ctx.T, tid
        self.snap = ctx.T.has_snapshot(tid)
        self.memo: dict = {}
        if self.snap:
            self.ws = ctx.T.base_ws(tid)
            self.paths = ctx.T.git(self.ws, "ls-files", timeout=60).out
        else:                  # no snapshot: the original lines the gold and test patches show (context, removed)
            row = ctx.rows[tid]
            olds = {**F.old_side_by_file(row["test_patch"]), **F.old_side_by_file(row["patch"])}
            self._has, self._word, self.paths = F.text_known(
                list(olds.values()), [fp.path for fp in F.parse(row["patch"]) if not fp.new_file]
                + [fp.path for fp in F.parse(row["test_patch"]) if not fp.new_file])

    def has(self, s: str) -> bool:
        if not self.snap:
            return self._has(s)
        k = ("F", s)
        if k not in self.memo:
            self.memo[k] = self.T.git(self.ws, "grep", "-q", "-I", "-F", "-e", s, "--", ".", timeout=60).rc == 0
        return self.memo[k]

    def has_word(self, w: str) -> bool:
        if not self.snap:
            return self._word(w)
        k = ("W", w)
        if k not in self.memo:
            self.memo[k] = self.T.git(self.ws, "grep", "-q", "-I", "-w", "-F", "-e", w, "--", ".", timeout=60).rc == 0
        return self.memo[k]

    def original(self, path: str):
        """The original text of a repository file, or None (absent, or no snapshot)."""
        if not self.snap:
            return None
        p = self.ws / path
        return p.read_text(encoding="utf-8", errors="surrogateescape") if p.is_file() else None

    def exists(self, path: str):
        return (self.ws / path).is_file() if self.snap else None


def static_task(ctx: Ctx, tid: str) -> dict:
    """Everything that needs no execution: plan pieces, leak inputs, replay steps of gold, the wrong candidates."""
    row, cat = ctx.rows[tid], ctx.catalog[tid]
    idx = RepoIndex(ctx, tid)
    gold, tp = row["patch"], row["test_patch"]
    gold_fps = [fp for fp in F.parse(gold) if fp.path]
    tp_fps = [fp for fp in F.parse(tp) if fp.path]
    if idx.snap:
        originals = {fp.old_path or fp.path: idx.original(fp.old_path or fp.path) for fp in gold_fps if not fp.new_file}

        def exists(p):
            return idx.exists(p)
    else:
        originals = {}                         # plan_entries then uses the hunk headers (plan_basis hunk_header)
        known_paths = {fp.path for fp in gold_fps + tp_fps if not fp.new_file}

        def exists(p):
            return p in known_paths
    entries, basis = F.plan_entries(gold, originals)
    gold_files = [fp.path for fp in gold_fps]
    tests = F.tests_line(tp, gold_files, exists)
    known = F.Known(row["problem_statement"], idx.has, idx.has_word, idx.paths)
    ov = ctx.overrides.get(tid)
    tmpl_plan, _ = F.make_plan(entries, cat.get("root_cause") or "", cat.get("one_line_solution") or "", True, tests)
    tmpl_leaks = F.leak_check(tmpl_plan, gold, tp, row["problem_statement"], known)
    return {"tid": tid, "row": row, "cat": cat, "entries": entries, "basis": basis, "tests": tests,
            "gold_files": gold_files, "gold_new_files": [fp.path for fp in gold_fps if fp.new_file],
            "test_files": ctx.T.extract_targets(tp), "known": known, "originals": originals, "override": ov,
            "template_leaks": tmpl_leaks,
            "idx": idx}


def final_plan(st: dict, reproducible: bool) -> tuple:
    cat, row = st["cat"], st["row"]
    plan, info = F.make_plan(st["entries"], cat.get("root_cause") or "", cat.get("one_line_solution") or "",
                             reproducible, st["tests"], st["override"])
    leaks = F.leak_check(plan, row["patch"], row["test_patch"], row["problem_statement"], st["known"])
    return plan, info, leaks


# ------------------------------------------------------------------------------------------------------- exec
def not_measured(why: str) -> str:
    return f"not measured: {why}"


def exec_task(ctx: Ctx, st: dict, par: int = 2) -> dict:
    """The executed evidence of one runnable task, each piece cached by its inputs. Independent pieces run `par` at a
    time (gradability; repro + gold replay; wrong selection + its replay; the pre-state hidden runs), so a task whose
    empty and wrong trees hang overlaps its 180 s waits instead of adding them up."""
    tid, row = st["tid"], st["row"]
    T, C = ctx.T, ctx.cache
    base_in = ctx.task_inputs(tid)
    gold, tp = row["patch"], row["test_patch"]
    out: dict = {}
    nodes = C.get(tid, "nodes", {**base_in, "tp": F.sha_text(tp)},
                  lambda: F.guarded(lambda: {"nodes": T.hidden_claim_nodes(tid)}))
    out["nodes"] = nodes
    node_list = (nodes or {}).get("nodes") or []

    def pre(patch):
        return C.get(tid, "hidden", {**base_in, "patch": F.sha_text(patch), "tp": F.sha_text(tp), "nodes": node_list,
                                     "timeout": F.HIDDEN_DEFAULTS},
                     lambda: F.guarded(F.x_hidden_pass, tid, node_list, patch))

    def grad():
        out["grad"] = C.get(tid, "gradable", {**base_in, "gold": F.sha_text(gold), "tp": F.sha_text(tp)},
                            lambda: F.guarded(F.x_gradable, tid))

    def repro_and_gold_replay():
        cand = F.extract_repro(ctx.traces.get(tid) or {})
        out["repro_src"] = cand
        if cand:
            def val():
                o = F.x_run_repro(tid, cand["body"], gold=False)
                gg = F.x_run_repro(tid, cand["body"], gold=True)
                ok, why = F.repro_verdict(o, gg)
                return {"orig": o, "gold": gg, "ok": ok, "why": why}
            out["repro"] = C.get(tid, "repro", {**base_in, "body": F.sha_text(cand["body"]),
                                                "gold": F.sha_text(gold)}, lambda: F.guarded(val))
        out["gold_tree"] = replay_variant(ctx, tid, gold, base_in)

    def wrong():                                       # 4.3
        recs = F.static_wrong(F.wrong_candidates(tid), gold, st["gold_files"])
        picked = F.select_wrong(
            recs, gold,
            canonical=lambda patch: C.get(tid, "canonical", {**base_in, "patch": F.sha_text(patch)},
                                          lambda: F.guarded(F.x_canonical, tid, patch)),
            verify=lambda canon: C.get(tid, "wrong_mv", {**base_in, "patch": F.sha_text(canon), "tp": F.sha_text(tp)},
                                       lambda: F.guarded(F.x_mini_verify, tid, canon)))
        out["wrong_recs"], out["wrong"] = recs, picked
        if picked:
            out["wrong_tree"] = replay_variant(ctx, tid, picked["canonical"], base_in)
            out.setdefault("pre", {})["wrong"] = pre(picked["canonical"])

    def pre_gold_empty():
        out.setdefault("pre", {})
        out["pre"]["empty"] = pre("")
        out["pre"]["gold"] = pre(gold)

    out["pre"] = {}
    jobs = (grad, wrong, pre_gold_empty, repro_and_gold_replay)
    if par <= 1:
        for j in jobs:
            j()
    else:
        with cf.ThreadPoolExecutor(par) as pool:
            for fut in [pool.submit(j) for j in jobs]:
                fut.result()
    return out


def replay_variant(ctx: Ctx, tid: str, patch: str, base_in: dict) -> dict:
    """Build the replay (edit first); validate; fall back to git_apply when the edit replay fails validation."""
    rp = F.build_replay(patch)
    first_why = rp["why"]

    def validate(r):
        return ctx.cache.get(tid, "replay", {**base_in, "patch": F.sha_text(patch), "replay": r["replay"],
                                             "steps": F.sha_obj(r["steps"])},
                             lambda: F.guarded(F.x_replay, tid, r["steps"], patch, r["replay"]))
    v = validate(rp)
    if not v.get("ok") and rp["replay"] == "edit":
        edit_why = v.get("why") or v.get("error") or "validation failed"
        rp = {"replay": "git_apply", "steps": F.git_apply_steps(patch), "why": "edit replay failed validation: "
              + edit_why}
        v = validate(rp)
    return {"replay": rp["replay"], "steps": rp["steps"], "fallback_why": rp["why"] or first_why,
            "ok": bool(v.get("ok")), "why": v.get("why") or v.get("error") or ""}


# ------------------------------------------------------------------------------------------------------- assemble
def tree_entries(st: dict, patch: str) -> list:
    """FILES-style entries of a tree patch against the original files (for notes_changed)."""
    if not patch.strip():
        return []
    idx = st["idx"]
    originals = {}
    for fp in F.parse(patch):
        if fp.path and not fp.new_file:
            p = fp.old_path or fp.path
            originals[p] = idx.original(p)
    return F.plan_entries(patch, originals)[0]


def assemble(ctx: Ctx, st: dict, ex: dict | None, run_ok: bool, run_why: str) -> dict:
    tid, row = st["tid"], st["row"]
    sp = ctx.split["tasks"][tid]
    fx: dict = {"task": tid, "repo": sp["repo"], "split": sp["split"], "race2": sp["race2"],
                "stratum": f"{sp['repo']}/{sp['race2']}", "runnable": run_ok, "runnable_why": run_why,
                "title_words": F.title_words(row["problem_statement"]), "gold_files": st["gold_files"],
                "gold_new_files": st["gold_new_files"], "gold_functions": F.gold_functions(st["entries"]),
                "plan_entries": [{k: e[k] for k in ("file", "start", "end", "qualname", "new_file")}
                                 for e in st["entries"]],
                "plan_basis": st["basis"], "plan_source": "override" if st["override"] else "template",
                "test_files": st["test_files"], "tests_line": st["tests"], "known": F.known_sets(tid),
                "known_flaky_targets": F.known_flaky_targets(st["test_files"]),
                "leaks_template": st["template_leaks"], "catalog_gold_lines_changed": st["cat"].get("gold_lines_changed")}
    nm = not_measured(run_why)
    if ex is None:
        fx.update({"reproducible": False, "repro": None, "repro_why": nm, "repro_source": None,
                   "repro_orig_rc": None, "repro_orig_timed_out": None, "repro_gold_rc": None,
                   "repro_gold_timed_out": None, "gradable": False, "gradable_why": nm, "gold_pass_runs": None,
                   "gold_runs": 0, "gold_why": [], "empty_pass": None, "empty_why": "",
                   "hidden_nodes": [], "hidden_nodes_why": nm, "wrong_source": None,
                   "wrong_why": nm, "wrong_mini_verify_why": "", "wrong_candidates": [
                       {"source": c["source"], "status": "not_evaluated", "why": nm}
                       for c in F.wrong_candidates(tid)]})
        gold_rp = F.build_replay(row["patch"])
        fx["variants"] = {
            "gold": {"tree_patch": row["patch"], "tree_source": "gold", "replay": gold_rp["replay"],
                     "replay_steps": gold_rp["steps"], "replay_ok": None, "replay_why": not_measured(run_why),
                     "replay_fallback_why": gold_rp["why"], "notes_changed": F.notes_changed(st["entries"]),
                     "pre_hidden_nodes_pass": None, "pre_hidden_outcomes": {}},
            "empty": empty_variant(None)}
        return fx
    g = ex["grad"]
    if g.get("error"):
        fx.update({"gradable": False, "gradable_why": "crashed: " + g["error"], "gold_pass_runs": None, "gold_runs": 0,
                   "gold_why": [], "empty_pass": None, "empty_why": ""})
    else:
        fx.update({k: g[k] for k in ("gradable", "gradable_why", "gold_pass_runs", "gold_runs", "gold_why",
                                     "empty_pass", "empty_why")})
    n = ex["nodes"]
    fx["hidden_nodes"] = [] if n.get("error") else n["nodes"]
    fx["hidden_nodes_why"] = n.get("error") or ("" if fx["hidden_nodes"] else "the test_patch adds no test function")
    src, rv = ex["repro_src"], ex.get("repro")
    fx["repro_source"] = ({"run": F.REPRO_RUN, "step_id": src["step_id"], "verdict": src["verdict"],
                           "first": src["first"]} if src else None)
    if not src:
        fx.update({"reproducible": False, "repro": None, "repro_orig_rc": None, "repro_orig_timed_out": None,
                   "repro_gold_rc": None, "repro_gold_timed_out": None,
                   "repro_why": "no r2_v10_1 locator repro said fails/hangs on original"})
    elif rv.get("error"):
        fx.update({"reproducible": False, "repro": None, "repro_orig_rc": None, "repro_orig_timed_out": None,
                   "repro_gold_rc": None, "repro_gold_timed_out": None, "repro_why": "crashed: " + rv["error"]})
    else:
        fx.update({"reproducible": bool(rv["ok"]), "repro": src["body"] if rv["ok"] else None,
                   "repro_why": rv["why"], "repro_orig_rc": rv["orig"].get("rc"),
                   "repro_orig_timed_out": rv["orig"].get("timed_out"), "repro_gold_rc": rv["gold"].get("rc"),
                   "repro_gold_timed_out": rv["gold"].get("timed_out")})
        if not rv["ok"]:
            fx["repro_rejected_body_sha"] = F.sha_text(src["body"])
    fx["wrong_candidates"] = [{k: r.get(k) for k in ("source", "status", "why", "dropped", "unsubmittable",
                                                     "touches_gold", "n_changed", "mini_verify_why")
                               if k in r}
                              for r in ex["wrong_recs"]]
    w = ex["wrong"]
    fx["wrong_source"] = w["source"] if w else None
    fx["wrong_why"] = "" if w else ("no candidate patch in any source" if not ex["wrong_recs"]
                                    else "no candidate qualified")
    fx["wrong_mini_verify_why"] = w.get("mini_verify_why", "") if w else ""
    pre = ex["pre"]

    def pre_fields(var):
        p = pre.get(var) or {}
        if p.get("error"):
            return {"pre_hidden_nodes_pass": None, "pre_hidden_outcomes": {}, "pre_hidden_why": p["error"]}
        return {"pre_hidden_nodes_pass": p["pass"], "pre_hidden_outcomes": p["outcomes"]}
    gt = ex["gold_tree"]
    variants = {"gold": {"tree_patch": row["patch"], "tree_source": "gold", "replay": gt["replay"],
                         "replay_steps": gt["steps"], "replay_ok": gt["ok"], "replay_why": gt["why"],
                         "replay_fallback_why": gt["fallback_why"], "notes_changed": F.notes_changed(st["entries"]),
                         **pre_fields("gold")},
                "empty": {**empty_variant(None), **pre_fields("empty")}}
    if w:
        wt = ex["wrong_tree"]
        variants["wrong"] = {"tree_patch": w["canonical"], "tree_source": w["source"], "replay": wt["replay"],
                             "replay_steps": wt["steps"], "replay_ok": wt["ok"], "replay_why": wt["why"],
                             "replay_fallback_why": wt["fallback_why"], "dropped_protected": w["dropped"],
                             "dropped_unsubmittable": w.get("unsubmittable") or [],
                             "notes_changed": F.notes_changed(tree_entries(st, w["canonical"])),
                             **pre_fields("wrong")}
    fx["variants"] = variants
    return fx


def empty_variant(_):
    return {"tree_patch": "", "tree_source": "empty", "replay": "none", "replay_steps": [], "replay_ok": True,
            "replay_why": "", "replay_fallback_why": "", "notes_changed": "CHANGED: nothing",
            "pre_hidden_nodes_pass": None, "pre_hidden_outcomes": {}}


def golden_block(fx: dict, suite: str, variant: str, t0: dict) -> dict:
    v = fx["variants"].get(variant) if suite == "V" else None
    b = {"schema": F.CASE_SCHEMA, "suite": suite, "task": fx["task"], "variant": variant if suite == "V" else "-",
         "split": fx["split"], "repo": fx["repo"], "stratum": fx["stratum"], "runnable": fx["runnable"],
         "runnable_why": fx["runnable_why"], "gradable": fx["gradable"], "gradable_why": fx["gradable_why"],
         "t0": t0[suite]["t0"], "pre_s": F.PRE_S, "plan": fx["plan"], "plan_source": fx["plan_source"],
         "plan_basis": fx["plan_basis"], "title_words": fx["title_words"], "repro": fx["repro"],
         "reproducible": fx["reproducible"], "gold_files": fx["gold_files"], "gold_new_files": fx["gold_new_files"],
         "gold_functions": fx["gold_functions"], "test_files": fx["test_files"], "hidden_nodes": fx["hidden_nodes"],
         "known": fx["known"],
         "tree_patch": v["tree_patch"] if v else "", "tree_source": v["tree_source"] if v else "",
         "replay": v["replay"] if v else "", "replay_steps": v["replay_steps"] if v else [],
         "notes_changed": v["notes_changed"] if v else "",
         "pre_hidden_nodes_pass": v["pre_hidden_nodes_pass"] if v else None}
    b["fixture_sha"] = F.sha_obj(b)
    return b


def eval_case(fx: dict, row: dict, suite: str, variant: str, t0: dict) -> dict:
    cid = f"{suite}__{fx['task']}" + (f"__{variant}" if suite == "V" else "")
    ref = fx["plan"] if suite == "L" else row["patch"]
    return {"eval_case_id": cid, "prompt": {"role": "user", "parts": [{"text": row["problem_statement"]}]},
            "reference": {"response": {"role": "model", "parts": [{"text": ref}]}},
            "golden": golden_block(fx, suite, variant, t0)}


def datasets(fixtures: dict, rows: dict, t0: dict) -> dict:
    out = {}
    for suite in F.SUITES:
        for split in ("dev", "holdout"):
            cases = []
            for tid in sorted(fixtures):
                fx = fixtures[tid]
                if fx["split"] != split:
                    continue
                if suite == "V":
                    for var in F.VARIANTS:
                        if var in fx["variants"]:
                            cases.append(eval_case(fx, rows[tid], suite, var, t0))
                else:
                    cases.append(eval_case(fx, rows[tid], suite, "-", t0))
            out[f"{suite}_{split}"] = {"eval_cases": sorted(cases, key=lambda c: c["eval_case_id"])}
    return out


def manifest(ctx: Ctx, fixtures: dict, sets: dict, outputs: dict, leak_summary: dict) -> dict:
    T = ctx.T
    counts: dict = {}
    for name, ds in sets.items():
        suite, split = name.split("_")
        c = counts.setdefault(suite, {}).setdefault(split, {})
        for case in ds["eval_cases"]:
            gb = case["golden"]
            key = gb["variant"] if suite == "V" else "all"
            k = c.setdefault(key, {"cases": 0, "runnable": 0, "gradable": 0, "reproducible": 0, "runnable_gradable": 0,
                                   "cells": {}})
            k["cases"] += 1
            k["runnable"] += int(gb["runnable"])
            k["gradable"] += int(gb["gradable"])
            k["runnable_gradable"] += int(gb["runnable"] and gb["gradable"])
            k["reproducible"] += int(gb["reproducible"])
            cell = "runnable=%d gradable=%d reproducible=%d" % (gb["runnable"], gb["gradable"], gb["reproducible"])
            k["cells"][cell] = k["cells"].get(cell, 0) + 1          # the suite x split x R x G x P cross-tab (4.6)
    replay = {}
    for fx in fixtures.values():
        for var, v in fx["variants"].items():
            if var == "empty":
                continue
            r = replay.setdefault(var, {"edit": 0, "git_apply": 0, "validated": 0, "fallback_reasons": {}})
            r[v["replay"]] = r.get(v["replay"], 0) + 1
            r["validated"] += int(bool(v["replay_ok"]))
            if v["replay"] == "git_apply":
                r["fallback_reasons"][fx["task"]] = v["replay_fallback_why"]
    inputs = {F.rel(p): F.sha_file(p) for p in (F.IDS_FILE, F.TASKS_FILE, F.CATALOG_FILE)}
    inputs.update(ctx.split["inputs"])
    inputs[F.rel(F.RACE2_DIR / F.REPRO_RUN / "traces")] = F.sha_tree(F.RACE2_DIR / F.REPRO_RUN / "traces")
    for label, kind, loc in F.WRONG_SOURCES:
        inputs[F.rel(loc)] = F.sha_tree(loc) if kind == "patch_dir" else F.sha_file(loc)
    if F.OVERRIDES_FILE.is_file():
        inputs[F.rel(F.OVERRIDES_FILE)] = F.sha_file(F.OVERRIDES_FILE)
    inputs[F.rel(F.BUNDLE_SCRIPTS)] = ctx.helpers_sha
    return {"schema": F.MANIFEST_SCHEMA, "builder_version": F.BUILDER_VERSION, "inputs": dict(sorted(inputs.items())),
            "snapshots_local": sorted(t for t in ctx.ids if T.has_snapshot(t)),
            "kpar_ok": sorted(r for r in ("rich", "requests", "fastapi") if T.kpar_ok(r)),
            "t0": ctx.t0, "pre_s": F.PRE_S, "mini_verify_timeout": F.MV_TIMEOUT, "repro_timeout": F.REPRO_TIMEOUT,
            "hidden_outcomes": {"how": F.HIDDEN_DEFAULTS, **F.hidden_outcome_defaults()}, "counts": counts,
            "tasks": {"total": len(fixtures), "runnable": sum(f["runnable"] for f in fixtures.values()),
                      "gradable": sum(f["gradable"] for f in fixtures.values()),
                      "reproducible": sum(f["reproducible"] for f in fixtures.values()),
                      "wrong": sum("wrong" in f["variants"] for f in fixtures.values()),
                      "not_gradable_runnable": {t: f["gradable_why"] for t, f in sorted(fixtures.items())
                                                if f["runnable"] and not f["gradable"]},
                      "no_wrong_runnable": {t: f["wrong_why"] for t, f in sorted(fixtures.items())
                                            if f["runnable"] and "wrong" not in f["variants"]}},
            "replay": replay, "leaks": leak_summary, "outputs": outputs}


# ------------------------------------------------------------------------------------------------------- main
def flaky_retries(ex) -> list:
    """Which runs of this build (or of the cached ones it reused) needed the KNOWN_FLAKY retry: logged, never committed
    (whether a load-dependent flake fired is not a property of the task)."""
    if not isinstance(ex, dict) or ex.get("error"):
        return []
    g = ex.get("grad") or {}
    out = [f"gold#{i + 1}" for i, r in enumerate(g.get("gold_retried") or []) if r]
    out += ["empty"] if g.get("empty_retried") else []
    out += [f"wrong:{r['source']}" for r in ex.get("wrong_recs") or [] if r.get("retried")]
    return out


def static_all(ctx: Ctx, j: int) -> dict:
    """static_task for every task, `j` at a time. The static phase has no fallback (the plan and its leak check need
    the original repository), so a failure stops the build with one clean line per task instead of a traceback, and a
    tasks.py pytest.skip (a base workspace that cannot be built) never escapes as a pytest outcome (gotcha 12)."""
    out, errs = {}, {}
    with cf.ThreadPoolExecutor(max(1, j)) as pool:
        for tid, st in zip(ctx.ids, pool.map(lambda t: F.guarded(static_task, ctx, t), ctx.ids)):
            if isinstance(st, dict) and "error" in st and "tid" not in st:
                errs[tid] = st["error"]
            else:
                out[tid] = st
    if errs:
        print("static phase failed (nothing written):", file=sys.stderr)
        for tid, e in sorted(errs.items()):
            print(f"  {tid}: {e}", file=sys.stderr)
        raise SystemExit(2)
    return out


def build(args) -> dict:
    """-> {path: text} of every output, or raises SystemExit(2) on leak violations / bad overrides."""
    t_start = time.monotonic()
    ctx = Ctx(no_cache=args.no_cache)
    errs = check_overrides(ctx.overrides, ctx.ids)
    if errs:
        print("\n".join(errs), file=sys.stderr)
        raise SystemExit(2)
    log = (lambda *a: print(*a, file=sys.stderr, flush=True)) if not args.quiet else (lambda *a: None)
    statics = static_all(ctx, args.j)
    log(f"static: {len(statics)} tasks in {time.monotonic() - t_start:.1f}s")
    # fail fast on template leaks without an override
    pre = {tid: st["template_leaks"] for tid, st in statics.items() if st["template_leaks"] and not st["override"]}
    if pre:
        print("leak violations with no override in plan_overrides.json:", file=sys.stderr)
        for tid, vs in sorted(pre.items()):
            for v in vs:
                print(f"  {tid}: rule {v['rule']} {v.get('line') or v.get('file')}: {v['text']!r}", file=sys.stderr)
        raise SystemExit(2)

    runnables = {tid: F.runnable(tid) for tid in ctx.ids}
    todo = [t for t in ctx.ids if runnables[t][0]]
    todo.sort(key=lambda t: (t not in ctx.T.KNOWN_EMPTY_HANG, -len(ctx.rows[t]["patch"]), t))
    execs: dict = {}

    def one(tid):
        t0 = time.monotonic()
        res = F.guarded(exec_task, ctx, statics[tid], args.task_par)
        ctx.cache.save(tid)
        flaky = flaky_retries(res)
        log(f"  {tid}: {time.monotonic() - t0:.1f}s" + (f" (KNOWN_FLAKY retries: {', '.join(flaky)})" if flaky else ""))
        return tid, res
    with cf.ThreadPoolExecutor(max(1, args.j)) as pool:
        for tid, res in pool.map(one, todo):
            execs[tid] = res
    crashed = {t: r["error"] for t, r in execs.items() if isinstance(r, dict) and r.get("error")}
    log(f"exec: {len(todo)} runnable tasks, cache hits {ctx.cache.hits} misses {ctx.cache.misses}, "
        f"{time.monotonic() - t_start:.1f}s")

    fixtures, final_leaks = {}, {}
    for tid in ctx.ids:
        ok, why = runnables[tid]
        ex = execs.get(tid)
        if ex is not None and ex.get("error"):
            ok, why, ex = False, "exec crashed: " + ex["error"], None
        fx = assemble(ctx, statics[tid], ex, ok, why)
        plan, info, leaks = final_plan(statics[tid], fx["reproducible"])
        fx.update({"plan": plan, "plan_words": info["words"], "plan_fit": info, "leaks_final": leaks})
        if leaks:
            final_leaks[tid] = leaks
        fixtures[tid] = fx
    if final_leaks:
        print("leak violations remain after overrides:", file=sys.stderr)
        for tid, vs in sorted(final_leaks.items()):
            for v in vs:
                print(f"  {tid}: rule {v['rule']} {v.get('line') or v.get('file')}: {v['text']!r}", file=sys.stderr)
        raise SystemExit(2)

    sets = datasets(fixtures, ctx.rows, ctx.t0)
    files = {F.SPLIT_FILE: F.dumps(ctx.split),
             F.TASK_FIXTURES_FILE: F.dumps({"schema": F.FIXTURES_SCHEMA, "builder_version": F.BUILDER_VERSION,
                                            "tasks": fixtures})}
    for name, ds in sets.items():
        files[F.DATASETS_DIR / f"{name}.json"] = F.dumps(ds)
    outputs = {F.rel(p): F.sha_text(t) for p, t in sorted(files.items(), key=lambda kv: str(kv[0]))}
    used = sorted(t for t, st in statics.items() if st["override"])
    leak_summary = {"template_violations": {t: st["template_leaks"] for t, st in sorted(statics.items())
                                            if st["template_leaks"]},
                    "overrides_used": used,
                    "overrides_unneeded": [t for t in used if not statics[t]["template_leaks"]],
                    "final_violations": 0}
    files[F.MANIFEST_FILE] = F.dumps(manifest(ctx, fixtures, sets, outputs, leak_summary))
    if crashed:
        log("exec crashed for: " + ", ".join(f"{t} ({e[:120]})" for t, e in sorted(crashed.items())))
    log(f"done in {time.monotonic() - t_start:.1f}s")
    return files


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-j", type=int, default=int(os.environ.get("G4_GOLDEN_J", "6")), help="parallel tasks (6)")
    ap.add_argument("--check", action="store_true", help="rebuild in memory; exit 1 if any committed file would change")
    ap.add_argument("--no-cache", action="store_true", help="recompute every executed result")
    ap.add_argument("--task-par", type=int, default=2, help="independent exec pieces of one task run at once (2)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    files = build(args)
    if args.check:
        bad = []
        for p, text in sorted(files.items(), key=lambda kv: str(kv[0])):
            cur = p.read_text() if p.is_file() else None
            if cur != text:
                bad.append(F.rel(p) + (" (missing)" if cur is None else ""))
        if bad:
            print("--check: these files would change:\n  " + "\n  ".join(bad), file=sys.stderr)
            return 1
        print(f"--check: {len(files)} files byte-identical")
        return 0
    for p, text in files.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f".{p.name}.tmp")
        tmp.write_text(text)
        os.replace(tmp, p)
    print(f"wrote {len(files)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
