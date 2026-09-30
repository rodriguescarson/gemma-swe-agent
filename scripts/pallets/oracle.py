"""Gold-patch oracle for SWE-Pallets-X under the competition harness's verification semantics.

  .venv/bin/python scripts/pallets/oracle.py [--repos click flask ...] [--ids ID ...] [-j 4] [--timeout 180]
                                             [--venv flask-wz2] [--out FILE]

Per task, on a harness-exact base workspace (tests/v10_support/tasks.base_ws: snapshot extracted, .git/info/exclude,
the harness pytest.ini + conftest hook written by swegemma's own setup_workspace_test_config, baseline commit):
  gold  x2  tests/v10_support/tasks.mini_verify(gold patch)   (port of swegemma verify_task: 4-pass apply, protected
                                                              reset, test_patch, pytest.ini/conftest overwrite, the
                                                              grader's pytest line, _validate_junit_xml, stdout checks)
  empty x1  mini_verify("")                                   (the task must NOT resolve without a fix)
valid = gold resolves both times AND the empty patch does not (the "gradable" rule of docs/eval/GOLDEN_EVALS_SPEC.md 4.5).

Environment: the repo's venv from scripts/pallets/build_envs.sh; PYTHONPATH=<ws>:<ws>/src (src only when it exists), the
stand-in for the pod's `pip install -e /workspace`. Everything else is tasks.sandbox_env (the subprocess-sandbox env).
The shared module is used unmodified: scripts/pallets/source.py only rebinds its path globals (TASKS_JSONL, SNAP_DIR,
CACHE, WORK) and its sandbox_env, so the golden-eval caches (~/.cache/g4/ws, kpar) are never touched.

Output: data/pallets/oracle/results.jsonl (one row per task; re-running skips finished ids unless --redo) and
data/pallets/oracle/logs/<tid>.<run>.log (full pytest output of every run).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
import shutil
import sys
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import source  # noqa: E402

T = source.activate(task_env=None)        # default venv = the repo's short name; --venv overrides per run
PAL = source.PAL
OUT = PAL / "oracle"
VENVS = source.VENVS
VENV_OVERRIDE = source.VENV_OVERRIDE
repo_name, venv_name, venv_dir = source.repo_name, source.venv_name, source.venv_dir

_ORIG_RUN = T.run
_TL = threading.local()


def recording_run(cmd, *a, **kw):
    """tasks.run, keeping the last pytest command's output per thread (mini_verify returns only a summary)."""
    r = _ORIG_RUN(cmd, *a, **kw)
    if isinstance(cmd, str) and " -m pytest " in cmd:
        _TL.last = (r.out or "") + ("\n--- stderr ---\n" + r.err if r.err else "")
    return r


T.run = recording_run

ENV_ERR = re.compile(r"(ModuleNotFoundError|ImportError|cannot import name|No module named|AttributeError: module "
                     r"'[\w.]+' has no attribute|fixture '[\w]+' not found|SyntaxError|unrecognized arguments)")


LOGS = OUT / "logs"


def one(tid: str, patch: str, test_patch: str, timeout: float, tag: str) -> dict:
    _TL.last = ""
    base = T.base_ws(tid)
    ok, why, secs = T.mini_verify(base, patch, test_patch, timeout=timeout, repo=tid)
    out = getattr(_TL, "last", "")
    LOGS.mkdir(parents=True, exist_ok=True)
    (LOGS / f"{tid}.{tag}.log").write_text(out, errors="replace")
    m = re.findall(r"^(?:=+ )?(\d+ (?:passed|failed|errors?|skipped|xfailed|xpassed|deselected|warnings?)\b.*?) "
                   r"in ([\d.]+)s", out, re.M)
    return {"resolved": bool(ok), "why": why, "secs": round(secs, 1),
            "pytest_s": float(m[-1][1]) if m else None, "summary": m[-1][0] if m else None,
            "env_error": bool(ENV_ERR.search(out)) and not ok}


def classify(g1: dict, g2: dict | None, e: dict) -> str:
    if g1["resolved"] and g2 and g2["resolved"] and not e["resolved"]:
        return "valid"
    if g1["resolved"] and g2 and g2["resolved"] and e["resolved"]:
        return "empty_resolves"                     # the hidden tests pass without any fix
    if g1["resolved"] != (g2 or {}).get("resolved", g1["resolved"]):
        return "gold_flaky"
    why = g1["why"] or ""
    if why.startswith("test_patch did not apply"):
        return "test_patch_no_apply"
    if why.startswith("agent patch did not apply"):
        return "gold_no_apply"
    if why.startswith("timeout"):
        return "gold_timeout"
    if g1["env_error"]:
        return "gold_env_error"
    if "Required test node did not pass" in why or "No passing tests" in why or "zero or no passing" in why:
        return "gold_junit_reject"
    return "gold_tests_fail"


def run_task(tid: str, timeout: float, keep: bool) -> dict:
    t = T.load_task(tid)
    t0 = time.monotonic()
    row = {"instance_id": tid, "repo": t["repo"], "created_at": t["created_at"], "venv": venv_name(tid)}
    try:
        g1 = one(tid, t["patch"], t["test_patch"], timeout, "gold1")
        e = one(tid, "", t["test_patch"], timeout, "empty")
        g2 = one(tid, t["patch"], t["test_patch"], timeout, "gold2") if g1["resolved"] else None
        row.update(gold1=g1, gold2=g2, empty=e, cls=classify(g1, g2, e))
    except BaseException as ex:                     # pytest.skip (missing snapshot) is a BaseException
        row.update(cls="harness_error", error=f"{type(ex).__name__}: {ex}"[:500], tb=traceback.format_exc()[-1500:])
    finally:
        if not keep:
            T._BASE_MEMO.pop((tid, False), None)
            shutil.rmtree(T.CACHE / tid, ignore_errors=True)
    row["valid"] = row.get("cls") == "valid"
    row["wall_s"] = round(time.monotonic() - t0, 1)
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repos", nargs="*", default=None, help="repo short names (click flask ...); default all")
    ap.add_argument("--ids", nargs="*", default=None)
    ap.add_argument("-j", type=int, default=4)
    ap.add_argument("--timeout", type=float, default=180.0, help="the grader's pytest timeout (eval_config 180 s)")
    ap.add_argument("--redo", action="store_true", help="re-run ids already in results.jsonl")
    ap.add_argument("--keep", action="store_true", help="keep the base workspaces in the cache")
    ap.add_argument("--out", default=str(OUT / "results.jsonl"))
    ap.add_argument("--venv", default=None, help="run every selected task in this venv (e.g. flask-wz2)")
    ap.add_argument("--logs", default=None, help="pytest log dir (default data/pallets/oracle/logs)")
    a = ap.parse_args()
    global LOGS
    if a.logs:
        LOGS = Path(a.logs)

    rows = T._tasks()
    ids = sorted(rows)
    if a.repos:
        ids = [i for i in ids if rows[i]["repo"].split("/")[-1] in a.repos]
    if a.ids:
        ids = [i for i in ids if i in set(a.ids)]
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists() and not a.redo:
        done = {json.loads(ln)["instance_id"] for ln in out.read_text().splitlines() if ln.strip()}
    todo = [i for i in ids if i not in done and T.has_snapshot(i)]
    missing = [i for i in ids if not T.has_snapshot(i)]
    if a.venv:
        VENV_OVERRIDE.update({i: a.venv for i in todo})
    for r in {venv_name(i) for i in todo}:
        if not (VENVS / r / ".g4_pallets_ok").is_file():
            print(f"oracle: venv missing for {r}: scripts/pallets/build_envs.sh {r}", file=sys.stderr)
            return 2
    print(f"oracle: {len(todo)} to run, {len(done)} done, {len(missing)} without snapshot", flush=True)
    lock = threading.Lock()
    n = 0
    with cf.ThreadPoolExecutor(max(1, a.j)) as ex, open(out, "a") as fh:
        futs = {ex.submit(run_task, tid, a.timeout, a.keep): tid for tid in todo}
        for f in cf.as_completed(futs):
            row = f.result()
            with lock:
                n += 1
                fh.write(json.dumps(row, sort_keys=True) + "\n")
                fh.flush()
                g = row.get("gold1") or {}
                print(f"[{n}/{len(todo)}] {row['instance_id']:<22} {row['cls']:<20} gold={g.get('summary')} "
                      f"wall={row['wall_s']}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
