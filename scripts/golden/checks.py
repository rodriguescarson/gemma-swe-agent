"""Exec checks and the flat per-case record (docs/eval/GOLDEN_EVALS_SPEC.md v1.1, 6.3).

Every check runs in the task's Kaggle-parity (kpar) venv on a fresh clone of ``tasks.base_ws(tid)``, never in the
agent sandbox, so grading needs only the submitted patch and the fixture and is re-runnable offline:

    patch_files        [[path, is_new], ...] parsed from the final patch
    applies            tasks.harness_apply on a fresh clone of base_ws(tid) (the harness apply pipeline)
    compiles           every changed, non-deleted .py of the patched clone compiles under the kpar python
    hidden_pass        tasks.mini_verify(base_ws(tid), patch, test_patch, repo=..., timeout=180) (gotcha 21), retried
                       once when every failing grader node is in KNOWN_FLAKY
    hidden_nodes_*     tasks.hidden_outcomes over golden.hidden_nodes on base_ws(tid, with_test_patch=True) + patch (V)
    repro_*            L: the locator's last --repro-only body run on the original and the gold tree (section 4.2)

null means "not computed". tasks.py calls pytest.skip when a snapshot or venv is missing; everything here checks
has_snapshot / kpar_ok first and also catches the Skipped outcome (gotcha 12).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(HERE), str(ROOT / "tests"), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

HIDDEN_TIMEOUT = 180            # verification.py:502 command_timeout_seconds (bundle eval_config), gotcha 21
REPRO_TIMEOUT = 20              # section 4.2
# tests/test_v10_flow.py KNOWN_FLAKY (copied: a test module is not a library; tests assert the copy matches)
KNOWN_FLAKY = {
    "tests/test_console.py::test_brokenpipeerror": "`python -m rich | head -1` races the pipe buffer: exit 0 when rich "
                                                  "finishes before head closes the pipe (seen on a loaded Mac)",
}
DEFAULT_TASKS = ROOT / "data" / "tasks.jsonl"
DEFAULT_SNAPS = ROOT / "data" / "raw" / "snapshots"
_CONF_LOCK = __import__("threading").Lock()


def T():
    from v10_support import tasks
    return tasks


def replay_l4():
    import replay_l4 as R
    return R


def _outcome_exc() -> tuple:
    try:
        from _pytest.outcomes import OutcomeException
        return (Exception, OutcomeException)
    except ImportError:      # pragma: no cover
        return (Exception,)


def configure_tasks(tasks_jsonl: Path | str | None = None, snapshots: Path | str | None = None,
                    cache: Path | str | None = None) -> None:
    """Point v10_support.tasks at another tasks.jsonl / snapshots dir / workspace cache (synthetic tasks in tests)."""
    t = T()
    with _CONF_LOCK:
        want_tasks = Path(tasks_jsonl) if tasks_jsonl else DEFAULT_TASKS
        want_snaps = Path(snapshots) if snapshots else DEFAULT_SNAPS
        changed = Path(t.TASKS_JSONL) != want_tasks or Path(t.SNAP_DIR) != want_snaps
        t.TASKS_JSONL, t.SNAP_DIR = want_tasks, want_snaps
        if cache:
            t.CACHE = Path(cache)
            t.WORK = t.CACHE.parent / (t.CACHE.name + "_work")
            changed = True
        if changed:
            t._TASKS = None
            t._BASE_MEMO.clear()


def task_row(tid: str) -> dict | None:
    try:
        return T().load_task(tid)
    except KeyError:
        return None


def kpar_key(tid: str, golden: dict) -> str:
    """The kpar venv key: from the task's repo when it is one of the three, else golden.repo (synthetic tasks)."""
    t = T()
    row = task_row(tid)
    if row and row.get("repo") in t.REPO_KPAR:
        return t.REPO_KPAR[row["repo"]]
    return golden.get("repo") or "rich"


def mv_repo(tid: str, golden: dict) -> str:
    """The ``repo=`` argument of tasks.mini_verify: the task id when tasks.py can resolve its venv, else the key."""
    t = T()
    row = task_row(tid)
    return tid if (row and row.get("repo") in t.REPO_KPAR) else kpar_key(tid, golden)


def runnable(tid: str, golden: dict) -> tuple:
    """(ok, why): snapshot and kpar venv present (checked without tasks.py's pytest.skip, gotcha 12)."""
    t = T()
    if task_row(tid) is None:
        return False, f"task {tid} not in {t.TASKS_JSONL}"
    if not t.has_snapshot(tid):
        return False, f"snapshot missing: {t.fetch_cmd(tid)}"
    key = kpar_key(tid, golden)
    if key not in t.REPO_KPAR.values():
        return False, f"kpar venv missing: no Kaggle-parity venv for repo key {key!r}"
    if not t.kpar_ok(key):
        return False, f"kpar venv missing: {t.build_cmd(key)}"
    return True, ""


# ------------------------------------------------------------------------------------------------------ patch facts
def patch_files(patch: str) -> list:
    """[[path, is_new], ...]: git diff headers (replay_l4.patch_files), else the plain ---/+++ sections."""
    R = replay_l4()
    files = R.patch_files(patch or "")
    if files:
        return [[p, bool(n)] for p, n in files]
    return [[fp.path, bool(fp.new_file)] for fp in T().parse_patch(patch or "") if fp.path]


def deleted_files(patch: str) -> set:
    out = set()
    lines = (patch or "").splitlines()
    cur = None
    for i, line in enumerate(lines):
        m = re.match(r'^diff --git "?a/(.*?)"? "?b/(.*?)"?$', line)
        if m:
            cur = m.group(2)
        elif cur and line.startswith("deleted file mode"):
            out.add(cur)
        elif line.startswith("+++ /dev/null") and i > 0 and lines[i - 1].startswith("--- a/"):
            out.add(lines[i - 1][6:].strip())
    return out


def protected_paths(files: list) -> list:
    R = replay_l4()
    return [p for p, _ in files if R.is_protected(p)]


def scratch_paths(files: list) -> list:
    R = replay_l4()
    return R.scratch_files([(p, n) for p, n in files])


# --------------------------------------------------------------------------------------------------------- the checks
def _compile_errors(py: str, ws: Path, rels: list) -> list:
    if not rels:
        return []
    code = ("import json,sys\nerr=[]\nfor f in sys.argv[1:]:\n    try:\n        compile(open(f,'rb').read(),f,'exec',"
            "dont_inherit=True)\n    except (SyntaxError,ValueError) as e:\n        err.append([f,str(e)[:200]])\n"
            "print(json.dumps(err))")
    r = T().run([py, "-c", code, *rels], cwd=ws, timeout=120)
    try:
        return json.loads((r.out or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        return [["<compile run>", (r.err or r.out or "no output")[-200:]]]


def _failing_nodes(tid: str, patch: str, test_patch: str, key: str) -> list | None:
    """[(classname, name)] of grader-style failures (failure/error only) on base_tp + patch; None if not measurable."""
    import xml.etree.ElementTree as ET
    t = T()
    with t.work_dir("gfl") as wd:
        ws = t.fresh_ws(t.base_ws(tid, with_test_patch=True), wd)
        env = t.sandbox_env(ws, key, fake_clock=None)
        if patch.strip():
            rc, _ = t.harness_apply(ws, patch, env, Path(f"{ws}_tmp"))
            if rc != 0:
                return None
        junit = Path(f"{ws}_tmp") / "flaky_junit.xml"
        sel = t.extract_targets(test_patch)
        e = dict(env, PYTHONSAFEPATH="1", PYTHONNOUSERSITE="1")
        r = t.run(["python3", "-s", "-m", "pytest", *sel, f"--junitxml={junit}", "-p", "no:cacheprovider",
                   *t.GRADER_FLAGS], cwd=ws, env=e, timeout=HIDDEN_TIMEOUT)
        if r.timed_out or not junit.is_file():
            return None
        out = []
        for tc in ET.parse(junit).getroot().iter("testcase"):
            if any(tc.find(x) is not None for x in ("failure", "error")):
                out.append((tc.get("classname", ""), tc.get("name", "")))
        return out


def all_flaky(failing: list | None) -> bool:
    if not failing:
        return False
    t = T()
    keys = [t._node_key(n) for n in KNOWN_FLAKY]
    return all(any(t._junit_match(k, cls, name) for k in keys) for cls, name in failing)


def hidden_pass(tid: str, patch: str, test_patch: str, golden: dict, *, mini_verify=None) -> dict:
    """{hidden_pass, hidden_why, hidden_secs, hidden_retried}: mini_verify at timeout=180, one KNOWN_FLAKY retry."""
    t = T()
    mv = mini_verify or t.mini_verify
    base = t.base_ws(tid)
    repo = mv_repo(tid, golden)
    ok, why, secs = mv(base, patch, test_patch, repo=repo, timeout=HIDDEN_TIMEOUT)
    retried = False
    if not ok and any(n.split("::")[0] in test_patch for n in KNOWN_FLAKY):
        if all_flaky(_failing_nodes(tid, patch, test_patch, kpar_key(tid, golden))):
            retried = True
            ok, why, s2 = mv(base, patch, test_patch, repo=repo, timeout=HIDDEN_TIMEOUT)
            secs += s2
    why = re.sub(r" in \d+(?:\.\d+)?s\b", "", why or "")         # pytest's duration: keep `write` deterministic
    return {"hidden_pass": bool(ok), "hidden_why": why, "hidden_secs": round(secs, 2), "hidden_retried": retried}


def hidden_nodes(tid: str, patch: str, nodes: list, key: str) -> dict:
    t = T()
    if not nodes:
        return {"hidden_nodes_total": 0, "hidden_nodes_pass": 0}
    with t.work_dir("gnodes") as wd:
        ws = t.fresh_ws(t.base_ws(tid, with_test_patch=True), wd)
        env = t.sandbox_env(ws, key, fake_clock=None)
        if patch.strip():
            rc, _ = t.harness_apply(ws, patch, env, Path(f"{ws}_tmp"))
            if rc != 0:
                return {"hidden_nodes_total": len(nodes), "hidden_nodes_pass": 0}
        out = t.hidden_outcomes(ws, nodes, env)
    return {"hidden_nodes_total": len(nodes), "hidden_nodes_pass": sum(1 for v in out.values() if v == "pass")}


def run_repro(tid: str, body: str, patch: str | None, key: str) -> bool | None:
    """True when the repro exits 0 within 20 s on base (+ patch), False when it exits non-zero or times out, None when
    the tree could not be built. Literal /workspace is mapped to the clone (section 4.2)."""
    t = T()
    with t.work_dir("grepro") as wd:
        ws = t.fresh_ws(t.base_ws(tid), wd)
        env = t.sandbox_env(ws, key, fake_clock=None)
        if patch and patch.strip():
            rc, _ = t.harness_apply(ws, patch, env, Path(f"{ws}_tmp"))
            if rc != 0:
                return None
        f = Path(f"{ws}_tmp") / "golden_repro.py"
        f.write_text(re.sub(r"(?<![\w./-])/workspace(?![\w.-])", str(ws), body), encoding="utf-8")
        r = t.run(["python3", str(f)], cwd=ws, env=env, timeout=REPRO_TIMEOUT)
        return (r.rc == 0) and not r.timed_out


REPRO_RE = re.compile(r"^\s*python3\s+/tmp/swe/verify\.py\s+--repro-only\s*<<\s*'?EOF'?\s*\n(.*)\nEOF\s*$", re.S)


def repro_body(command: str) -> str | None:
    """The heredoc body of a `python3 /tmp/swe/verify.py --repro-only <<'EOF' ... EOF` command."""
    if "--repro-only" not in (command or ""):
        return None
    lines = command.split("\n")
    if len(lines) < 2:
        return None
    first = lines[0]
    if not re.search(r"<<\s*['\"]?EOF['\"]?\s*$", first):
        return None
    end = max((i for i, ln in enumerate(lines) if ln.strip() == "EOF" and i > 0), default=None)
    if end is None:
        return None
    return "\n".join(lines[1:end]) + "\n"


def compute(case: dict, final_patch: str, *, repro_text: str | None = None, nodes: bool | None = None,
            harness_resolved: bool | None = None, mini_verify=None) -> dict:
    """The exec_checks block of one case sample (6.3). Never raises: failures land in ``errors``."""
    g = case.get("golden") or case
    tid, suite = g["task"], g["suite"]
    files = patch_files(final_patch)
    out: dict[str, Any] = {
        "patch_files": files, "protected_paths": protected_paths(files), "scratch_paths": scratch_paths(files),
        "applies": None, "compiles": None, "compile_errors": None, "hidden_pass": None, "hidden_why": None,
        "hidden_secs": None, "hidden_retried": None, "hidden_nodes_total": None, "hidden_nodes_pass": None,
        "pre_hidden_nodes_pass": g.get("pre_hidden_nodes_pass") if suite == "V" else None,
        "repro_text": repro_text if suite == "L" else None, "repro_fails_orig": None, "repro_passes_gold": None,
        "harness_resolved": harness_resolved, "not_computed": "", "errors": []}
    ok, why = runnable(tid, g)
    if not ok:
        out["not_computed"] = why
        return out
    t = T()
    row = task_row(tid) or {}
    test_patch = row.get("test_patch") or ""
    key = kpar_key(tid, g)
    exc = _outcome_exc()
    py = str(t.kpar_dir(key) / "bin" / "python")
    try:
        with t.work_dir("gapply") as wd:
            ws = t.fresh_ws(t.base_ws(tid), wd)
            env = t.sandbox_env(ws, key, fake_clock=None)
            if final_patch.strip():
                rc, err = t.harness_apply(ws, final_patch, env, Path(f"{ws}_tmp"))
                out["applies"] = rc == 0
                if rc != 0:
                    out["errors"].append(f"apply: {err[-200:]}")
            else:
                out["applies"] = True
            if out["applies"]:
                gone = deleted_files(final_patch)
                rels = [p for p, _ in files if p.endswith(".py") and p not in gone and (ws / p).is_file()]
                errs = _compile_errors(py, ws, rels)
                out["compiles"], out["compile_errors"] = not errs, errs
            else:
                out["compiles"], out["compile_errors"] = False, []
    except exc as e:
        out["errors"].append(f"apply/compile: {type(e).__name__}: {str(e)[:200]}")
    if g.get("gradable", True) and test_patch.strip():
        try:
            out.update(hidden_pass(tid, final_patch, test_patch, g, mini_verify=mini_verify))
        except exc as e:
            out["errors"].append(f"hidden: {type(e).__name__}: {str(e)[:200]}")
        want_nodes = (suite == "V") if nodes is None else nodes
        if want_nodes:
            try:
                out.update(hidden_nodes(tid, final_patch, list(g.get("hidden_nodes") or []), key))
            except exc as e:
                out["errors"].append(f"nodes: {type(e).__name__}: {str(e)[:200]}")
    elif not g.get("gradable", True):
        out["not_computed"] = "not gradable: " + (g.get("gradable_why") or "")
    if suite == "L" and repro_text:
        try:
            orig = run_repro(tid, repro_text, None, key)
            gold = run_repro(tid, repro_text, row.get("patch") or "", key)
            out["repro_fails_orig"] = None if orig is None else (not orig)
            out["repro_passes_gold"] = gold
        except exc as e:
            out["errors"].append(f"repro: {type(e).__name__}: {str(e)[:200]}")
    return out


# ------------------------------------------------------------------------------------------------ status and record
def crash_class(texts: list) -> str | None:
    """The first replay_l4.CRASH class matching any of the texts (harness error first)."""
    R = replay_l4()
    for txt in texts:
        for name, rx in R.CRASH.items():
            if txt and rx.search(str(txt)):
                return name
    return None


REPLAY_BAD = re.compile(r"REFUSED|NO MATCH|REVERTED")


def replay_failures(steps: list, author: str) -> list:
    """Scripted replay steps (edit.py or the base64 git apply) by `author` whose result is not OK."""
    bad = []
    for s in steps:
        if s.get("source") != "agent":
            continue
        tcs = s.get("tool_calls") or []
        for tc in tcs[:1]:
            if ((tc.get("extra") or {}).get("author") or (s.get("extra") or {}).get("author")) != author:
                continue
            cmd_ = str((tc.get("arguments") or {}).get("command") or "")
            obs = s.get("observation") or {}
            txt = str(obs.get("content") if isinstance(obs, dict) else obs or "")
            from stage_scripts import tool_text
            body = tool_text(txt)
            if "/tmp/swe/edit.py" in cmd_:
                if not body.lstrip().startswith("OK") or REPLAY_BAD.search(body):
                    bad.append(cmd_.split("\n", 1)[0][:120])
            elif "git','apply'" in cmd_ or "git apply" in cmd_:
                try:
                    code = json.loads(txt).get("exit_code")
                except (ValueError, AttributeError):
                    code = None
                if code not in (0, None) or '"status": "error"' in txt:
                    bad.append("git apply replay")
    return bad


def decide_status(*, skipped: str | None = None, launched: bool = True, budget_refused: bool = False,
                  child_timeout: bool = False, child_rc: int | None = 0, row: dict | None = None,
                  route_state: dict | None = None, pre_s: float = 150.0, replay_bad: list | None = None,
                  crash: str | None = None) -> tuple:
    """(status, detail) by the 6.3 rules; infra first, then model_error, else ok."""
    rs = route_state or {}
    if skipped:
        return "skipped", skipped
    if budget_refused or "budget" in (rs.get("infra") or []):
        return "infra_error", "budget"
    if not launched:
        return "infra_error", "not launched"
    if child_timeout:
        return "infra_error", "child_timeout"
    if "unknown_request" in (rs.get("infra") or []):
        return "infra_error", "unknown_request"
    if rs.get("upstream_failed_last"):
        return "infra_error", "upstream_http"
    if row is None:
        return "infra_error", f"no task result (child rc {child_rc})"
    err = str(row.get("error") or "")
    if err and re.search(r"Snapshot file not found|ContainerSetupError|Failed to extract|setup failed|"
                         r"Sandbox (setup|start)", err, re.I):
        return "infra_error", "setup: " + err[:160]
    if replay_bad:
        return "infra_error", "replay step not OK: " + "; ".join(replay_bad)[:200]
    if rs.get("t_live0") is None:
        return "infra_error", "live stage never started"
    pss = rs.get("pre_stage_s")
    if pss is not None and pss > pre_s:
        return "infra_error", f"pre_stage_slow ({pss:.1f}s > {pre_s:g}s)"
    if crash:
        return "model_error", crash
    return "ok", ""
