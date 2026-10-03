"""Failure taxonomy of one faithful run (Kaggle L4: results.jsonl + traces/trace_<id>.json), unsolved tasks only.

    python scripts/analyze_failures.py eval/kaggle/g4-l4-v4 --tasks data/tasks.jsonl [--out report.json]

Classes (first that applies): crash (non-timeout error), timeout_no_patch, no_patch (finished with an empty diff),
wrong_files (the diff touches none of the gold patch's files), right_file_wrong_fix (touches a gold file, tests fail),
timeout_with_patch is folded into the two patch classes with `timed_out` set. Per task: stage reached (last author),
edit calls, test runs, sandbox command timeouts, tool errors, seconds by stage. tests/test_analyze_failures.py.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

FILE_RE = re.compile(r"^\+\+\+ b/(\S+)|^--- a/(\S+)|^diff --git a/(\S+) b/", re.M)


def patch_files(patch: str) -> list[str]:
    files = []
    for m in FILE_RE.finditer(patch or ""):
        f = next(g for g in m.groups() if g)
        if f not in files and f != "/dev/null":
            files.append(f)
    return files


def classify(row: dict, gold_files: list[str]) -> str:
    err = str(row.get("err") or "")
    patch = (row.get("patch") or "").strip()
    timed_out = "timeout" in err.lower()
    if err and not timed_out:
        return "crash"
    if not patch:
        return "timeout_no_patch" if timed_out else "no_patch"
    touched = patch_files(patch)
    return "right_file_wrong_fix" if any(f in gold_files for f in touched) else "wrong_files"


def trace_stats(trace: dict) -> dict:
    edits = tests = timeouts = errors = 0
    secs = collections.Counter()
    last_author = None
    for s in trace.get("steps", []):
        for tc in s.get("tool_calls") or []:
            a = tc.get("arguments") or {}
            cmd = str(a.get("command") or "")
            name = tc.get("function_name")
            author = (tc.get("extra") or {}).get("author")
            if author:
                last_author = author
                secs[author] += float((tc.get("extra") or {}).get("elapsed_s") or 0)
            if name == "edit_file" or "edit.py" in cmd:
                edits += 1
            if "pytest" in cmd or "python -m unittest" in cmd:
                tests += 1
        obs = str((s.get("observation") or {}).get("content") or "")
        if "timed out" in obs.lower():
            timeouts += 1
        if '"status": "error"' in obs or "Error" in obs[:80]:
            errors += 1
    return {"stage": last_author, "edit_calls": edits, "test_runs": tests, "cmd_timeouts": timeouts, "tool_errors": errors,
            "secs_by_stage": {k: round(v, 1) for k, v in secs.items()}}


def normalize(r: dict, run: Path) -> dict:
    """One row shape for both layouts: Kaggle (id/resolved/err/secs/calls/patch) and the Pallets runner (instance_id,
    resolved as a string, error, duration_seconds, tool_calls, diff under patches/<id>.patch)."""
    tid = r.get("id") or r.get("instance_id")
    resolved = r.get("resolved")
    if isinstance(resolved, str):
        resolved = resolved.strip().lower() == "true"
    patch = r.get("patch")
    if patch is None:
        pf = run / "patches" / f"{tid}.patch"
        patch = pf.read_text(errors="replace") if pf.exists() else ""
    def num(v):
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None
    secs = num(r.get("secs") if r.get("secs") is not None else r.get("duration_seconds"))
    calls = r.get("calls") if r.get("calls") is not None else r.get("tool_calls")
    try:
        calls = int(calls) if calls is not None else None
    except (TypeError, ValueError):
        pass
    return {"id": tid, "resolved": bool(resolved), "err": r.get("err") if r.get("err") is not None else r.get("error"),
            "secs": secs, "calls": calls, "patch": patch}


def analyze(run: Path, tasks_path: Path) -> dict:
    gold = {}
    for l in open(tasks_path):
        if l.strip():
            t = json.loads(l)
            gold[t["instance_id"]] = patch_files(t.get("patch") or "")
    rfile = run / "results.jsonl" if (run / "results.jsonl").exists() else run / "task_results.jsonl"
    rows = [normalize(json.loads(l), run) for l in open(rfile) if l.strip()]
    out = []
    for r in rows:
        tid = r["id"]
        if r.get("resolved"):
            continue
        rec = {"id": tid, "class": classify(r, gold.get(tid, [])), "err": str(r.get("err") or "")[:80], "secs": r.get("secs"),
               "calls": r.get("calls"), "timed_out": "timeout" in str(r.get("err") or "").lower(),
               "patch_files": patch_files(r.get("patch") or ""), "gold_files": gold.get(tid, [])}
        tp = run / "traces" / f"trace_{tid}.json"
        if tp.exists():
            rec.update(trace_stats(json.load(open(tp))))
        out.append(rec)
    classes = collections.Counter(t["class"] for t in out)
    stages = collections.Counter(t.get("stage") for t in out)
    return {"run": str(run), "summary": {"rows": len(rows), "solved": sum(bool(r.get("resolved")) for r in rows), "unsolved": len(out),
                                         "classes": dict(classes), "stage_reached": dict(stages),
                                         "mean_edit_calls": round(sum(t.get("edit_calls", 0) for t in out) / max(1, len(out)), 1),
                                         "mean_test_runs": round(sum(t.get("test_runs", 0) for t in out) / max(1, len(out)), 1),
                                         "tasks_with_cmd_timeout": sum(1 for t in out if t.get("cmd_timeouts"))},
            "tasks": out}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("run"); ap.add_argument("--tasks", required=True); ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    rep = analyze(Path(a.run), Path(a.tasks))
    print(json.dumps(rep["summary"], indent=1))
    for t in sorted(rep["tasks"], key=lambda t: t["class"]):
        print(f"{t['id']:<22} {t['class']:<21} stage={t.get('stage')} edits={t.get('edit_calls')} tests={t.get('test_runs')} "
              f"cmd_to={t.get('cmd_timeouts')} secs={t.get('secs')} files={t['patch_files'][:2]} gold={t['gold_files'][:2]}")
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        json.dump(rep, open(a.out, "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
