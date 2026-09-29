"""Golden single-stage suite runner (docs/eval/GOLDEN_EVALS_SPEC.md v1.1, sections 5 and 6). Run with .venv/bin/python.

    run_suite.py run --suite {L,F,V} --split {dev,holdout} --endpoint {openrouter,vllm,oracle,null} [options]
    run_suite.py write RUN_DIR [-j 6]           exec checks + flat JSON + EvaluationDataset traces (run does this too)
    run_suite.py controls --suite S --split dev [-j 6]      oracle and null arms, asserts the 5.9 expectations
    run_suite.py smoke --endpoint openrouter [--max-usd 0.40]   the one paid step (never run by tests)

Every case sample is one child process (stage_child.py -> scripts/run_eval.py -> the REAL swegemma Evaluator) on an
unmodified copy of the bundle; the router (router.py) answers the child's LLM requests by agent name: the target stage
LIVE, its neighbours SCRIPTED (stage_scripts.py). Grading is ours (checks.py) and agents-cli's (called as a subprocess,
with component c's summary.py, only when both exist). scripts/golden is not a package: siblings and v10_support are
imported by name through sys.path.

Money and state (review 2026-09-30):
- The dollar cap applies to openrouter (default $1.00) and to vllm only when --max-usd is given; vllm is free per token
  and its token-price figure is recorded as est_usd_at_proxy_prices. Before launching, a capped run refuses when its
  estimate (race-2 tokens per stage x the endpoint's prices x case samples to run) plus what the run already spent
  exceeds --max-usd, and prints the flag value that fits.
- --resume refuses different settings (endpoint, model, provider pin, extra body, seed mode, samples, --l4-scale,
  dataset, filters, environment) than the run.json it continues. It keeps every re-run case's earlier attempt under
  <run>/attempts/<case>.attempt<N>/, counts their spend in spent_usd, and seeds the budget with it, so --max-usd caps the
  run's total. Each case's meta.json carries the endpoint and label that served it.
- Ctrl-C or SIGTERM stops launching, cancels queued cases, kills the live children, writes the partial run with status
  "interrupted" (graded, resumable) and exits 130.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(HERE), str(ROOT / "tests"), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import checks as CK            # noqa: E402
import router as RT            # noqa: E402
import stage_child as SC       # noqa: E402
import stage_scripts as SS     # noqa: E402
import trace_writer as TW      # noqa: E402

DEFAULT_OUT = ROOT / "eval" / "golden" / "runs"
DATASETS = ROOT / "eval" / "golden" / "datasets"
HOLDOUT_LOG = ROOT / "eval" / "golden" / "holdout_log.jsonl"
MANIFEST = ROOT / "eval" / "golden" / "fixtures" / "MANIFEST.json"
EVAL_DIR = ROOT / "eval" / "golden"
BUNDLE_DEFAULT = ROOT / "submissions" / "v10"
EXPECTED_AGENTS = ("setup", "locator", "fixer", "verifier", "submitter")
AGENTS_CLI = Path(os.environ.get("G4_AGENTS_CLI") or "/Users/carson/.local/bin/agents-cli")
SUMMARY = HERE / "summary.py"
CHILD = HERE / "stage_child.py"
CHILD_GRACE_S = 240
UPSTREAM_DEAD_S = 120          # kill a child whose upstream has failed continuously this long (infra_error upstream_http)
LIVE_SERVED = ("upstream", "oracle", "null")
SMOKE_CAP = 0.40
DEFAULT_MAX_USD = 1.00         # openrouter's cap when --max-usd is not given (vllm is uncapped unless it is given)
# section 9: mean OpenRouter cost per live stage run (r2_v10_1 usage x $0.09/M in, $0.34/M out)
EST_COST = {"L": 0.0102, "F": 0.0115, "V": 0.0070}
# the r2_v10_1 means behind it (74 ATIF traces, prompt and completion tokens per live stage run), to reprice EST_COST
EST_TOKENS = {"L": (107590, 1557), "F": (121158, 1419), "V": (69666, 632)}
# run.json settings a --resume must match (the bundle is checked by sha in prepare)
RESUME_KEYS = ("suite", "split", "endpoint", "upstream_base", "upstream_model", "or_provider", "upstream_extra",
               "seed_mode", "samples", "l4_scale", "dataset_sha", "task_filter", "variant_filter", "agent_env",
               "faithful_env", "harness_verify")


class UsageError(Exception):
    pass


def log(msg: str) -> None:
    print(msg, flush=True)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _env(name: str, default: Any) -> Any:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


def est_cost(suite: str, price_in: float = RT.REF_PRICE_IN, price_out: float = RT.REF_PRICE_OUT) -> float:
    """Mean cost of one live stage run of `suite` at these $/M prices: EST_COST repriced with EST_TOKENS' in/out mix."""
    tin, tout = EST_TOKENS[suite]
    ref = tin * RT.REF_PRICE_IN + tout * RT.REF_PRICE_OUT
    return EST_COST[suite] * (tin * float(price_in) + tout * float(price_out)) / ref


def needed_usd(est: float) -> float:
    """The --max-usd to pass for an estimate: 25 % headroom over the mean plus the router's 0.01 refusal margin."""
    return math.ceil((est * 1.25 + 0.01) * 100) / 100


def sha256_file(p: Path) -> str | None:
    try:
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()
    except OSError:
        return None


def bundle_sha(bundle: Path) -> str:
    """sha256 over the sorted relative paths and bytes of every file of the bundle (bytecode ignored)."""
    h = hashlib.sha256()
    bundle = Path(bundle)
    for p in sorted(x for x in bundle.rglob("*") if x.is_file()):
        rel = p.relative_to(bundle).as_posix()
        if "__pycache__" in rel or rel.endswith(".pyc") or p.name in (".DS_Store",) or p.name.startswith("._"):
            continue
        h.update(rel.encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def check_bundle(bundle: Path) -> list:
    """The sub-agent names in order; UsageError unless exactly setup, locator, fixer, verifier, submitter."""
    try:
        names = [n for n, _ in TW.bundle_agents(bundle)]
    except Exception as e:
        raise UsageError(f"cannot read the bundle's sub-agents in {bundle}: {type(e).__name__}: {e}") from None
    if tuple(names) != EXPECTED_AGENTS:
        raise UsageError(f"bundle {bundle} has sub-agents {names}; the runner needs exactly {list(EXPECTED_AGENTS)}")
    return names


def eval_budgets(bundle: Path) -> dict:
    import yaml
    try:
        ev = (yaml.safe_load((Path(bundle) / "eval_config.yaml").read_text()) or {}).get("evaluation") or {}
    except (OSError, ValueError):
        ev = {}
    return {"max_tool_calls": int(ev.get("max_tool_calls") or 100), "max_turns": int(ev.get("max_turns") or 200),
            "timeout_seconds": int(ev.get("timeout_seconds") or 180)}


def versions() -> dict:
    import importlib.metadata as md
    out = {"python": sys.version.split()[0]}
    for k in ("swegemma", "google-adk", "litellm"):
        try:
            out[k] = md.version(k)
        except md.PackageNotFoundError:
            out[k] = None
    return out


def git_state() -> tuple:
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10)
        if head.returncode != 0:
            return None, None
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, timeout=30)
        return head.stdout.strip(), bool(dirty.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return None, None


def write_json(path: Path, obj: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def read_jsonl(path: Path) -> list:
    try:
        return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]
    except (OSError, ValueError):
        return []


def router_logs(run_dir: Path) -> list:
    """Every router.jsonl of a run: the current case dirs and every earlier attempt kept by --resume."""
    run_dir = Path(run_dir)
    return sorted(run_dir.glob("cases/*/router.jsonl")) + sorted(run_dir.glob("attempts/*/router.jsonl"))


def spent_on_disk(run_dir: Path) -> dict:
    """{"cost_usd": billed or estimated dollars, "est_usd_at_proxy_prices": vllm's figure, "budget": their sum (what
    a cap counts)} over every attempt of every case."""
    cost = est = 0.0
    for fp in router_logs(run_dir):
        for r in read_jsonl(fp):
            cost += float(r.get("cost_usd") or 0)
            est += float(r.get("est_usd_at_proxy_prices") or 0)
    return {"cost_usd": cost, "est_usd_at_proxy_prices": est, "budget": cost + est}


# --------------------------------------------------------------------------------------------------------- datasets
def load_dataset(path: Path) -> list:
    d = read_json(path)
    if not isinstance(d, dict) or not isinstance(d.get("eval_cases"), list):
        raise UsageError(f"not an EvaluationDataset: {path} (component a builds eval/golden/datasets/*.json)")
    return d["eval_cases"]


VARIANTS = ("gold", "wrong", "empty")


def select_cases(cases: list, *, suite: str, split: str, tasks: list | None = None,
                 variants: list | None = None) -> list:
    """The cases of one suite x split, optionally filtered. A filter value that matches nothing is refused: a typo
    would otherwise shrink the population without a word."""
    bad_v = sorted(set(variants or ()) - set(VARIANTS))
    if bad_v:
        raise UsageError(f"--variants {','.join(bad_v)} unknown; choose from {','.join(VARIANTS)}")
    if tasks:
        known = {(c.get("golden") or {}).get("task") for c in cases}
        missing = sorted(set(tasks) - known)
        if missing:
            raise UsageError(f"--tasks {','.join(missing)} not in the dataset")
    out = []
    for c in cases:
        g = c.get("golden") or {}
        if g.get("suite") != suite:
            raise UsageError(f"dataset case {c.get('eval_case_id')} is suite {g.get('suite')}, not {suite}")
        if g.get("split") != split:
            raise UsageError(f"dataset case {c.get('eval_case_id')} is split {g.get('split')}, not {split}")
        if tasks and g.get("task") not in tasks:
            continue
        if variants and suite == "V" and (g.get("variant") or "gold") not in variants:
            continue
        out.append(c)
    return sorted(out, key=lambda c: c["eval_case_id"])


# ------------------------------------------------------------------------------------------------------------- run
def _kill_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def kill_stragglers(marker: str) -> list:
    """Kill every process whose command line contains `marker` (never this process)."""
    try:
        ps = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    killed = []
    for line in ps.splitlines():
        pid_s, _, cmdline = line.strip().partition(" ")
        if marker in cmdline and pid_s.isdigit() and int(pid_s) != os.getpid():
            try:
                os.kill(int(pid_s), signal.SIGKILL)
                killed.append(int(pid_s))
            except OSError:
                pass
    return killed


def child_env(base_url: str, sbx: Path, *, scale: float, faithful: bool, plain_cache: Path | None,
              secrets: tuple = ()) -> dict:
    """The child's environment (5.5): no router secrets, no model-endpoint overrides, its own route and TMPDIR."""
    env = SC.scrub_env(dict(os.environ))
    for k in ("G4_L4_SCALE", "G4_COMPACTION", "G4_NO_EDITABLE", "TEST_TMPDIR"):
        env.pop(k, None)
    for k in [k for k, v in env.items() if any(s and s in v for s in secrets)]:
        env.pop(k)                      # any other variable that carries the key
    env.update({"OPENAI_BASE_URL": base_url, "OPENAI_API_KEY": "EMPTY", "TMPDIR": str(sbx),
                "G4_FAITHFUL_ENV": "1" if faithful else "0", "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONUNBUFFERED": "1"})
    if plain_cache is not None:
        env["G4_PLAIN_CACHE"] = str(plain_cache)
    if scale and abs(scale - 1.0) > 1e-9:
        env["G4_L4_SCALE"] = repr(scale)
    return env


def harness_minutes(t0: float, pre_s: float, scale: float) -> float:
    """--max-time-minutes M = ((300 - t0) + pre_s * scale) / 60; run_eval divides it by scale (5.5)."""
    return round(((SS.CAP_S - t0) + pre_s * scale) / 60.0, 6)


def cap_seconds(t0: float, scale: float) -> float:
    return (SS.CAP_S - t0) / scale


def case_id_of(case: dict, k: int) -> str:
    return f"{case['eval_case_id']}__s{k}"


class Runner:
    """One `run` invocation: dataset cases x samples through children, then `write`."""

    def __init__(self, a: argparse.Namespace, *, script_hook: Callable | None = None,
                 endpoint: RT.Endpoint | None = None, clock: Callable[[], float] = time.monotonic):
        self.a = a
        self.script_hook = script_hook
        self.endpoint = endpoint
        self.clock = clock
        self.stop = threading.Event()
        self.interrupted = threading.Event()
        self._procs: set = set()                # live child process-group ids
        self._plock = threading.Lock()
        self.cap: float | None = None
        self.prior_spent = 0.0
        self.est_usd = 0.0
        self.old_run: dict | None = None

    # -- preparation -------------------------------------------------------------------------------------------------
    def prepare(self) -> None:
        a = self.a
        if a.split == "holdout" and not (a.holdout_reason or "").strip():
            raise UsageError("--split holdout needs --holdout-reason TEXT (tune on dev; grade holdout once)")
        if a.agent_env == "kpar" and a.faithful_env:
            raise UsageError("--agent-env kpar together with --faithful-env is refused: the pod's faithful_install "
                             "owns the environment there")
        if a.samples < 1:
            raise UsageError("--samples must be >= 1")
        if not 0.2 <= a.l4_scale <= 5.0:
            raise UsageError(f"--l4-scale must be within 0.2..5, got {a.l4_scale}")
        CK.configure_tasks(a.tasks_jsonl, a.snapshots_dir, a.ws_cache)
        if self.endpoint is None:
            try:
                extra = json.loads(a.upstream_extra) if a.upstream_extra else {}
            except ValueError as e:
                raise UsageError(f"--upstream-extra is not JSON: {e}") from None
            try:
                self.endpoint = RT.make_endpoint(a.endpoint, upstream_base=a.upstream_base,
                                                 upstream_model=a.upstream_model, env_file=a.env_file,
                                                 or_provider=a.or_provider, upstream_extra=extra,
                                                 seed_mode=a.seed_mode, price_in=a.price_in, price_out=a.price_out)
            except ValueError as e:
                raise UsageError(str(e)) from None
        ds = Path(a.dataset) if a.dataset else DATASETS / f"{a.suite}_{a.split}.json"
        self.dataset_path = ds
        all_cases = load_dataset(ds)
        self.task_filter = sorted({t for t in (a.tasks or "").split(",") if t}) or None
        self.variant_filter = sorted({v for v in (a.variants or "").split(",") if v}) or None
        self.dataset_tasks = len({c["golden"]["task"] for c in select_cases(all_cases, suite=a.suite, split=a.split)})
        self.cases = select_cases(all_cases, suite=a.suite, split=a.split, tasks=self.task_filter,
                                  variants=self.variant_filter)
        if not self.cases:
            raise UsageError(f"no cases selected from {ds}")
        self.run_id = a.run_id or f"{a.suite}_{a.split}_{a.endpoint}_{time.strftime('%Y%m%d_%H%M%S')}"
        if not re.match(r"^[A-Za-z0-9_.-]+$", self.run_id):
            raise UsageError(f"--run-id must be [A-Za-z0-9_.-]+, got {self.run_id!r}")
        self.run_dir = Path(a.out) / self.run_id
        ep = self.endpoint
        if not ep.live:
            self.cap = None
        elif a.max_usd is not None:
            self.cap = float(a.max_usd)
        else:
            self.cap = DEFAULT_MAX_USD if ep.name == "openrouter" else None     # vllm: no per-token price to cap
        self.old_run = read_json(self.run_dir / "run.json") if a.resume else None
        if self.old_run:
            new = json.loads(json.dumps(self.settings()))
            diff = [f"{k}: {self.old_run[k]!r} -> {new[k]!r}" for k in RESUME_KEYS
                    if k in self.old_run and self.old_run[k] != new[k]]
            if diff:
                raise UsageError(f"--resume of {self.run_dir} with other settings than its run.json ("
                                 + "; ".join(diff) + "): its cases would be mixed and relabelled; use a new --run-id")
            self.prior_spent = spent_on_disk(self.run_dir)["budget"]
        todo = sum(1 for c in self.cases if not self.skip_reason(c) for k in range(a.samples)
                   if not self.done(case_id_of(c, k)))
        self.est_usd = round(todo * est_cost(a.suite, ep.price_in, ep.price_out), 4) if ep.live else 0.0
        if self.cap is not None and self.prior_spent + self.est_usd > self.cap:
            need = needed_usd(self.prior_spent + self.est_usd)
            raise UsageError(
                f"estimated ${self.est_usd:.3f} for {todo} case samples to run ({a.suite}: "
                f"${est_cost(a.suite, ep.price_in, ep.price_out):.4f} each at ${ep.price_in:g}/${ep.price_out:g} per M)"
                + (f" plus ${self.prior_spent:.4f} this run already spent" if self.prior_spent else "")
                + f" exceeds --max-usd {self.cap:g}; pass --max-usd {need:.2f} (25 % headroom) or select fewer cases")
        src = Path(a.bundle)
        if not src.is_absolute():
            src = ROOT / src
        check_bundle(src)
        dst = self.run_dir / "bundle" / src.name
        if dst.exists() and a.resume:
            if bundle_sha(dst) != bundle_sha(src):
                raise UsageError(f"--resume with a different bundle than {dst}; use a new --run-id")
        else:
            shutil.rmtree(self.run_dir / "bundle", ignore_errors=True)
            from v10_support.sandbox import copy_bundle
            (self.run_dir / "bundle").mkdir(parents=True, exist_ok=True)
            copy_bundle(self.run_dir / "bundle", src)
        check_bundle(dst)
        self.bundle = dst
        self.bundle_src = src
        self.bundle_sha = bundle_sha(dst)
        self.budgets = eval_budgets(dst)

    def settings(self) -> dict:
        """The run.json fields a --resume must match (RESUME_KEYS)."""
        a, pub = self.a, self.endpoint.public()
        return {"suite": a.suite, "split": a.split, "endpoint": pub["endpoint"], "upstream_base": pub["upstream_base"],
                "upstream_model": pub["upstream_model"], "or_provider": pub["or_provider"],
                "upstream_extra": pub["upstream_extra"], "seed_mode": pub["seed_mode"], "samples": a.samples,
                "l4_scale": a.l4_scale, "dataset_sha": sha256_file(self.dataset_path), "task_filter": self.task_filter,
                "variant_filter": self.variant_filter if a.suite == "V" else None, "agent_env": a.agent_env,
                "faithful_env": bool(a.faithful_env), "harness_verify": bool(a.harness_verify)}

    def skip_reason(self, case: dict) -> str:
        """Why a case is recorded as skipped instead of launched ('' when it runs)."""
        g = case["golden"]
        if g.get("runnable") is False:
            return "not runnable: " + (g.get("runnable_why") or "dataset says runnable=false")
        if g.get("gradable") is False and not self.a.include_ungradable:
            return "not gradable (run with --include-ungradable for X metrics): " + (g.get("gradable_why") or "")
        ok, rwhy = CK.runnable(g["task"], g)
        return "" if ok else "not runnable: " + rwhy

    def done(self, cid: str) -> bool:
        """--resume keeps a case whose flat record is ok or model_error."""
        return bool(self.a.resume) and (read_json(self.run_dir / "cases" / f"{cid}.json") or {}).get("status") in (
            "ok", "model_error")

    def stamp(self) -> dict:
        """What served a case, written into its meta.json at launch (assemble reads it before run.json's)."""
        ep = self.endpoint
        return {"endpoint": ep.name, "label": ep.label, "upstream_model": ep.model, "or_provider": ep.provider}

    def interrupt(self) -> None:
        """Stop launching, and kill every live child's process group now (their cases record 'interrupted')."""
        self.interrupted.set()
        self.stop.set()
        with self._plock:
            pgids = list(self._procs)
        for pg in pgids:
            _kill_group(pg)

    def run_manifest(self) -> dict:
        a, ep = self.a, self.endpoint
        head, dirty = git_state()
        t0s = sorted({SS.case_t0(c) for c in self.cases})
        m = {"run_id": self.run_id, "created": _now(), "git_head": head, "git_dirty": dirty, "suite": a.suite,
             "split": a.split, "dataset_path": str(self.dataset_path), "dataset_sha": sha256_file(self.dataset_path),
             "fixture_manifest_sha": sha256_file(MANIFEST), "task_filter": self.task_filter,
             "variant_filter": self.variant_filter if a.suite == "V" else None, "dataset_tasks": self.dataset_tasks,
             **ep.public(), "providers_seen": [],
             "l4_scale": a.l4_scale, "agent_env": a.agent_env, "samples": a.samples, "bundle_path": str(self.bundle_src),
             "bundle_copy": str(self.bundle), "bundle_sha": self.bundle_sha, "versions": versions(),
             "t0": t0s[0] if len(t0s) == 1 else t0s, "budget_usd": self.cap, "est_usd": self.est_usd,
             "spent_usd": 0.0, "est_usd_at_proxy_prices": 0.0, "prior_spent_usd": round(self.prior_spent, 6),
             "wall_s_before": 0.0,
             "wall_s": None, "mean_live_latency_s": None, "cases": {}, "holdout_reason": a.holdout_reason or None,
             "harness_verify": bool(a.harness_verify), "faithful_env": bool(a.faithful_env),
             "extract_cache": not a.no_extract_cache, "tasks_jsonl": str(a.tasks_jsonl or CK.DEFAULT_TASKS),
             "snapshots_dir": str(a.snapshots_dir or CK.DEFAULT_SNAPS), "ws_cache": a.ws_cache, "nodes": a.nodes,
             "budgets": self.budgets, "status": "running", "t_start": time.time()}
        return m

    # -- one case sample ---------------------------------------------------------------------------------------------
    def run_one(self, router: RT.StageRouter, case: dict, k: int) -> None:
        a = self.a
        cid = case_id_of(case, k)
        cdir = self.run_dir / "cases" / cid
        flat = self.run_dir / "cases" / f"{cid}.json"
        if self.done(cid):
            return
        if a.resume and worth_keeping(cdir):
            keep_attempt(self.run_dir, cid)     # its spend still counts, and its logs stay readable
        shutil.rmtree(cdir, ignore_errors=True)
        flat.unlink(missing_ok=True)
        cdir.mkdir(parents=True)
        write_json(cdir / "case.json", {"case": case, "sample": k})
        meta: dict = {"launched": False, **self.stamp()}
        try:
            why = self.skip_reason(case)
            if why:
                meta["skipped"] = why
                return
            if self.interrupted.is_set():
                meta["interrupted"] = True
                return
            if self.stop.is_set() or router.budget.refused:
                meta["budget_stop"] = True
                return
            meta.update(self._launch(router, case, k, cid, cdir))
            if "budget" in (meta.get("route") or {}).get("infra", []):
                self.stop.set()
        except Exception as e:
            meta["runner_error"] = f"{type(e).__name__}: {e}"
            (cdir / "runner_error.txt").write_text(traceback.format_exc())
        finally:
            write_json(cdir / "meta.json", meta)
            try:
                rec = assemble(self.run_dir, cid, checks=False)
                write_json(flat, rec["flat"])
            except Exception as e:
                write_json(flat, {"case_id": cid, "status": "infra_error", "status_detail": f"assemble: {e}"})

    def _launch(self, router: RT.StageRouter, case: dict, k: int, cid: str, cdir: Path) -> dict:
        a, g = self.a, case["golden"]
        tid, suite = g["task"], g["suite"]
        scale = a.l4_scale
        t0, pre_s = SS.case_t0(case), SS.case_pre_s(case)
        row = CK.task_row(tid)
        (cdir / "tasks.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
        snaps = cdir / "snapshots"
        snaps.mkdir()
        from v10_support import tasks as T
        (snaps / f"{tid}.tgz").symlink_to(Path(T.SNAP_DIR).resolve() / f"{tid}.tgz")
        results = cdir / "results"
        sbx = cdir / "sbx"
        results.mkdir()
        sbx.mkdir()
        live = SS.live_agent(suite)
        scripts = SS.neighbour_scripts(case, scale)
        ep = router.endpoint
        live_script = SS.oracle_script(case) if ep.name == "oracle" else []
        if self.script_hook is not None:
            scripts, live_script = self.script_hook(case, k, scripts, live_script)
        cap_s = cap_seconds(t0, scale)
        base = router.add_route(cid, cid, live, scripts, live_script, cap_s, log_path=cdir / "router.jsonl",
                                bodies_path=cdir / "router_bodies.jsonl")
        minutes = harness_minutes(t0, pre_s, scale)
        budget_s = cap_s + pre_s
        key_ok = CK.kpar_key(tid, g)
        agent_env = a.agent_env
        site = None
        if agent_env == "kpar":
            site = SC.kpar_site(key_ok)
            if site is None:
                agent_env = "host"
        own = ["--agent-env", agent_env]
        if site is not None:
            own += ["--kpar-site", str(site)]
        if a.no_extract_cache:
            own.append("--no-extract-cache")
        if a.plain_cache:
            own += ["--plain-cache", str(a.plain_cache)]
        if a.harness_verify:
            own.append("--harness-verify")
        if a.faithful_env:
            own.append("--faithful-env")
        b = self.budgets
        argv = [sys.executable, str(CHILD), *own, "--", "eval", "--tasks", str(cdir / "tasks.jsonl"),
                "--snapshots-dir", str(snaps), "--submission-dir", str(self.bundle), "--results-dir", str(results),
                "--sandbox", "subprocess", "--max-time-minutes", repr(minutes), "--max-tool-calls",
                str(b["max_tool_calls"]), "--max-turns", str(b["max_turns"]), "--timeout-seconds",
                str(b["timeout_seconds"]), "--concurrency", "1", "--display", "quiet", "--task-ids", tid]
        secrets = tuple(x for x in (ep.key,) if x and x != "EMPTY")
        env = child_env(base, sbx, scale=scale, faithful=a.faithful_env,
                        plain_cache=Path(a.plain_cache) if a.plain_cache else None, secrets=secrets)
        write_json(cdir / "child_cmd.json", {"argv": argv, "env_keys": sorted(env)})
        t_start = time.monotonic()
        deadline = t_start + budget_s + a.child_grace
        timed_out, killed = False, None
        log(f"[{time.strftime('%H:%M:%S')}] launch {cid}")
        with open(cdir / "child.out", "w") as out, open(cdir / "child.err", "w") as err:
            p = subprocess.Popen(argv, cwd=results, env=env, stdout=out, stderr=err, stdin=subprocess.DEVNULL,
                                 start_new_session=True)
            with self._plock:
                self._procs.add(p.pid)       # start_new_session: pid == its process-group id
            try:
                if self.interrupted.is_set():  # interrupted between the check in run_one and Popen
                    _kill_group(p.pid)
                while True:
                    try:
                        rc = p.wait(timeout=0.5)
                        break
                    except subprocess.TimeoutExpired:
                        pass
                    st = router.route(cid).state()
                    if self.interrupted.is_set():
                        killed = "interrupted"
                    elif "budget" in st["infra"]:
                        killed = "budget"           # a refused case would otherwise retry until its harness budget
                    elif st["fail_streak_s"] is not None and st["fail_streak_s"] > a.upstream_dead_s:
                        killed = "upstream_dead"
                    elif time.monotonic() > deadline:
                        timed_out = True
                    if killed or timed_out:
                        _kill_group(p.pid)
                        rc = p.wait()
                        break
            finally:
                _kill_group(p.pid)
                with self._plock:
                    self._procs.discard(p.pid)
        if self.interrupted.is_set() and not killed and rc is not None and rc < 0:
            killed = "interrupted"             # Runner.interrupt killed it before this loop saw the flag
        if timed_out or killed:
            kill_stragglers(str(sbx))
        wall = time.monotonic() - t_start
        state = router.route(cid).state()
        router.remove_route(cid)
        return {"launched": True, "child_rc": rc, "child_timeout": timed_out, "killed": killed, "wall_s": round(wall, 2),
                "route": state, "cap_s": round(cap_s, 3), "harness_minutes": minutes, "t0": t0, "pre_s": pre_s,
                "agent_env": agent_env, "kpar_site": str(site) if site else None}

    # -- the whole run -----------------------------------------------------------------------------------------------
    def run(self) -> Path:
        a = self.a
        self.prepare()
        man = self.run_manifest()
        old = self.old_run
        if old:                               # active time only: the gap between invocations is not run time
            man["wall_s_before"] = float(old.get("wall_s") or 0.0)
            man["created"] = old.get("created") or man["created"]
            man["resumes"] = int(old.get("resumes") or 0) + 1
        write_json(self.run_dir / "run.json", man)
        if a.split == "holdout":
            HL = Path(a.holdout_log)
            HL.parent.mkdir(parents=True, exist_ok=True)
            with open(HL, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": _now(), "suite": a.suite, "bundle_sha": self.bundle_sha,
                                    "run_id": self.run_id, "reason": a.holdout_reason}, sort_keys=True) + "\n")
        items = [(c, k) for c in self.cases for k in range(a.samples)]
        ep = self.endpoint
        log(f"golden run {self.run_id}: {len(items)} case samples, endpoint {ep.name} ({ep.label}"
            + (f", provider pin {ep.provider}" if ep.provider else "") + f"), -j {a.j}"
            + (f", cap ${self.cap:g}, estimate ${self.est_usd:.3f}" if self.cap is not None else "")
            + (f", already spent ${self.prior_spent:.4f}" if self.prior_spent else ""))
        budget = RT.Budget(self.cap)
        budget.spent = self.prior_spent          # --max-usd caps the run's total across --resume invocations
        err: BaseException | None = None
        with RT.StageRouter(ep, budget, clock=self.clock, log_bodies=a.log_bodies) as router:
            ex = cf.ThreadPoolExecutor(max(1, a.j))
            trap = _trap_sigterm()
            try:
                try:
                    futs = [ex.submit(self.run_one, router, c, k) for c, k in items]
                    for f in cf.as_completed(futs):
                        f.result()
                except KeyboardInterrupt:
                    log(f"[{time.strftime('%H:%M:%S')}] interrupted: no new launches; killing live children")
                    self.interrupt()
                except BaseException as e:   # never leave queued cases running behind an error
                    err = e
                    self.stop.set()
                if self.interrupted.is_set() or err is not None:
                    ex.shutdown(wait=False, cancel_futures=True)
                while True:
                    try:
                        ex.shutdown(wait=True)
                        break
                    except KeyboardInterrupt:
                        self.interrupt()
            finally:
                _restore_sigterm(trap)
            if router.errors:
                (self.run_dir / "router_errors.txt").write_text("\n".join(router.errors))
        if err is not None:
            raise err
        run = read_json(self.run_dir / "run.json") or man
        run["t_end"] = time.time()
        if self.interrupted.is_set():
            run["status"] = "interrupted"     # visible even if the write below is cut short
        write_json(self.run_dir / "run.json", run)
        write_run(self.run_dir, j=a.j, keep=a.keep_sandboxes,
                  status="interrupted" if self.interrupted.is_set() else "written")
        if self.interrupted.is_set():
            log(f"interrupted: partial run written to {self.run_dir} (status interrupted); continue it with the same "
                "command plus --resume")
            raise KeyboardInterrupt
        if a.grade:
            grade(self.run_dir)
        return self.run_dir


def _trap_sigterm():
    """SIGTERM raises KeyboardInterrupt in the main thread while a run is in progress (None elsewhere)."""
    if threading.current_thread() is not threading.main_thread():
        return None

    def _on_term(signum, frame):
        raise KeyboardInterrupt
    prev = signal.getsignal(signal.SIGTERM)      # None when the handler was not installed from Python
    signal.signal(signal.SIGTERM, _on_term)
    return {"prev": prev}


def _restore_sigterm(trap) -> None:
    if trap is not None:
        signal.signal(signal.SIGTERM, trap["prev"] if trap["prev"] is not None else signal.SIG_DFL)


def worth_keeping(cdir: Path) -> bool:
    """An earlier attempt is kept when it launched a child or talked to the router (a skipped or never-launched case
    has nothing to keep, and would otherwise pile up one empty attempt per --resume)."""
    if not Path(cdir).is_dir():
        return False
    rl = Path(cdir) / "router.jsonl"
    return bool((read_json(Path(cdir) / "meta.json") or {}).get("launched")) or (rl.is_file() and rl.stat().st_size > 0)


def keep_attempt(run_dir: Path, cid: str) -> Path:
    """Move a case's earlier attempt (its dir and flat record) to <run>/attempts/<cid>.attempt<N>/ before a re-run."""
    run_dir = Path(run_dir)
    att = run_dir / "attempts"
    att.mkdir(parents=True, exist_ok=True)
    n = 1
    while (att / f"{cid}.attempt{n}").exists():
        n += 1
    dst = att / f"{cid}.attempt{n}"
    shutil.move(str(run_dir / "cases" / cid), str(dst))
    flat = run_dir / "cases" / f"{cid}.json"
    if flat.is_file():
        shutil.move(str(flat), str(dst / "flat.json"))
    shutil.rmtree(dst / "sbx", ignore_errors=True)
    return dst


# ----------------------------------------------------------------------------------------------------------- write
def _row(results: Path, tid: str) -> dict | None:
    for r in read_jsonl(results / "task_results.jsonl"):
        if r.get("instance_id") == tid:
            return r
    return None


def assemble(run_dir: Path, cid: str, *, checks: bool = True, nodes: bool | None = None) -> dict:
    """{flat, trace}: the flat per-case record (6.3) and the grading-input trace case (6.2), from files only."""
    run_dir = Path(run_dir)
    run = read_json(run_dir / "run.json") or {}
    cdir = run_dir / "cases" / cid
    cj = read_json(cdir / "case.json") or {}
    case, k = cj.get("case") or {}, int(cj.get("sample") or 0)
    g = case.get("golden") or {}
    tid, suite = g.get("task"), g.get("suite")
    live = SS.live_agent(suite) if suite in SS.LIVE_AGENT else None
    meta = read_json(cdir / "meta.json") or {}
    # what served THIS case (stamped at launch); run.json only for cases written before the stamp existed
    served_by = {k2: (meta[k2] if k2 in meta else run.get(k2))
                 for k2 in ("endpoint", "label", "upstream_model", "or_provider")}
    results = cdir / "results"
    records = read_jsonl(cdir / "router.jsonl")
    row = _row(results, tid) if meta.get("launched") else None
    atif_p = results / "traces" / f"trace_{tid}.json"
    atif = read_json(atif_p) if atif_p.is_file() else None
    patch_p = results / "patches" / f"{tid}.patch"
    final_patch = patch_p.read_text(encoding="utf-8", errors="replace") if patch_p.is_file() else ""
    rs = meta.get("route") or {}
    err_txt = str((row or {}).get("error") or "")
    crash = CK.crash_class([err_txt]) if row is not None else None
    if crash is None and row is None and meta.get("launched"):
        try:
            crash = CK.crash_class([(cdir / "child.err").read_text(errors="replace")[-20000:]])
        except OSError:
            crash = None
    steps = (atif or {}).get("steps") or []
    replay_bad = []
    if suite == "V" and (g.get("variant") or "gold") != "empty":
        replay_bad += CK.replay_failures(steps, "fixer")
    if served_by["endpoint"] == "oracle" and live:
        replay_bad += CK.replay_failures(steps, live)
    skipped = meta.get("skipped")
    if meta.get("runner_error"):
        status, detail = "infra_error", "runner: " + meta["runner_error"]
    elif meta.get("interrupted") or meta.get("killed") == "interrupted":
        status, detail = "infra_error", "interrupted"
    elif meta.get("budget_stop"):
        status, detail = "infra_error", "budget"
    else:
        status, detail = CK.decide_status(skipped=skipped, launched=bool(meta.get("launched")),
                                          child_timeout=bool(meta.get("child_timeout")), child_rc=meta.get("child_rc"),
                                          row=row, route_state=rs, pre_s=SS.case_pre_s(case), replay_bad=replay_bad,
                                          crash=crash)
    live_recs = [r for r in records if r.get("live") and r.get("served") in LIVE_SERVED]
    tools_seen = {r["agent"]: r["tools"] for r in records if r.get("kind") == "agent" and r.get("tools")}
    bundle = Path(run["bundle_copy"]) if run.get("bundle_copy") else None
    agents = TW.agents_map(bundle, tools_seen) if (bundle and bundle.is_dir()) else {}
    agent_data = None
    if atif:
        agent_data, _ = TW.atif_to_agent_data(atif, agents)
    exec_checks = None
    if checks and status in ("ok", "model_error"):
        repro = TW.repro_text_of(agent_data, live) if (suite == "L" and agent_data and live) else None
        want_nodes = run.get("nodes") if nodes is None else nodes
        exec_checks = CK.compute(case, final_patch, repro_text=repro, nodes=want_nodes or None,
                                 harness_resolved=(row or {}).get("resolved") if run.get("harness_verify") else None)
        if status == "model_error" and exec_checks.get("hidden_pass") is not None:
            exec_checks["hidden_pass"] = False
            exec_checks["hidden_why"] = f"model_error: {crash}"
    elif checks:
        exec_checks = {"not_computed": f"status {status}"}
    prov = sorted({r["provider"] for r in records if r.get("provider")})
    flat = {
        "case_id": cid, "dataset_case_id": case.get("eval_case_id"), "suite": suite, "task": tid,
        "variant": g.get("variant") or "-", "sample": k, "split": g.get("split"), "status": status,
        "status_detail": detail, "crash_class": crash, "endpoint": served_by["endpoint"], "label": served_by["label"],
        "upstream_model": served_by["upstream_model"], "or_provider": served_by["or_provider"], "providers": prov,
        "bundle_sha": run.get("bundle_sha"),
        "fixture_sha": g.get("fixture_sha"), "wall_s": meta.get("wall_s"), "pre_stage_s": rs.get("pre_stage_s"),
        "capped": bool(rs.get("capped")),
        "live": {"agent": live, "llm_calls": len(live_recs),
                 "tool_calls": TW.live_tool_calls(agent_data, live) if (agent_data and live) else 0,
                 "prompt_tokens": sum(int(r.get("prompt_tokens") or 0) for r in live_recs),
                 "completion_tokens": sum(int(r.get("completion_tokens") or 0) for r in live_recs),
                 "cost_usd": round(sum(float(r.get("cost_usd") or 0) for r in live_recs), 8),
                 "max_prompt_tokens": max((int(r.get("prompt_tokens") or 0) for r in live_recs), default=0),
                 "t_first": live_recs[0]["t_in"] if live_recs else None,
                 "t_last": live_recs[-1]["t_out"] if live_recs else None},
        "cost_usd_total": round(sum(float(r.get("cost_usd") or 0) for r in records), 8),
        "est_usd_at_proxy_prices": round(sum(float(r.get("est_usd_at_proxy_prices") or 0) for r in records), 8),
        "prior_attempts": len(list((run_dir / "attempts").glob(f"{cid}.attempt*"))),
        "harness": {"error": (row or {}).get("error"), "tool_calls": (row or {}).get("tool_calls"),
                    "llm_calls": (row or {}).get("total_llm_calls"), "duration_s": (row or {}).get("duration_seconds")},
        "harness_resolved": (row or {}).get("resolved") if run.get("harness_verify") else None,
        "paths": {"patch": str(patch_p.relative_to(run_dir)) if patch_p.is_file() else None,
                  "atif": str(atif_p.relative_to(run_dir)) if atif_p.is_file() else None,
                  "router_log": str((cdir / "router.jsonl").relative_to(run_dir))
                  if (cdir / "router.jsonl").is_file() else None},
        "exec_checks": exec_checks,
    }
    run_info = {k2: run.get(k2) for k2 in ("run_id", "bundle_sha", "l4_scale")}
    run_info.update(served_by)
    run_info["max_output_tokens"] = TW.max_output_tokens(bundle) if (bundle and bundle.is_dir()) else {}
    trace = TW.build_case(case=case, sample=k, case_id=cid, agents=agents, atif=atif, extra_golden={
        "live_agents": [live] if live else [], "status": status, "status_detail": detail, "crash_class": crash,
        "final_patch": final_patch, "run": run_info, "llm_calls": records, "exec_checks": exec_checks or {},
        "writer_warnings": []})
    return {"flat": flat, "trace": trace}


def write_run(run_dir: Path, *, j: int = 6, keep: bool = False, nodes: bool | None = None,
              status: str | None = None) -> dict:
    """`write`: exec checks + flat JSON + traces/<suite>_<split>.json + run.json (idempotent). Spend counts every
    attempt (<run>/attempts/ too); status None keeps 'interrupted' on a run that was interrupted, else 'written'."""
    run_dir = Path(run_dir)
    run = read_json(run_dir / "run.json")
    if not run:
        raise UsageError(f"no run.json in {run_dir}")
    CK.configure_tasks(run.get("tasks_jsonl"), run.get("snapshots_dir"), run.get("ws_cache"))
    cids = sorted(p.name for p in (run_dir / "cases").iterdir() if p.is_dir() and (p / "case.json").is_file())
    out: dict = {}

    def one(cid):
        try:
            return cid, assemble(run_dir, cid, checks=True, nodes=nodes)
        except Exception as e:
            (run_dir / "cases" / cid / "write_error.txt").write_text(traceback.format_exc())
            return cid, {"flat": {"case_id": cid, "status": "infra_error", "status_detail": f"write: {e}"},
                         "trace": None}
    with cf.ThreadPoolExecutor(max(1, j)) as ex:
        for cid, rec in ex.map(one, cids):
            out[cid] = rec
    traces = []
    counts = {"total": 0, "ok": 0, "model_error": 0, "infra_error": 0, "skipped": 0}
    lat, providers = [], set()
    for cid, rec in sorted(out.items()):
        write_json(run_dir / "cases" / f"{cid}.json", rec["flat"])
        if rec["trace"] is not None:
            traces.append(rec["trace"])
        st = rec["flat"].get("status")
        counts["total"] += 1
        counts[st] = counts.get(st, 0) + 1
        for r in read_jsonl(run_dir / "cases" / cid / "router.jsonl"):
            if r.get("live") and r.get("served") == "upstream":
                lat.append(float(r.get("latency_s") or 0))
    for fp in router_logs(run_dir):              # every attempt was served and paid for
        providers.update(r["provider"] for r in read_jsonl(fp) if r.get("provider"))
    sp = spent_on_disk(run_dir)
    name = f"{run.get('suite')}_{run.get('split')}.json"
    (run_dir / "traces").mkdir(parents=True, exist_ok=True)
    TW.write_dataset(run_dir / "traces" / name, traces)
    if status is None:
        status = "interrupted" if run.get("status") == "interrupted" else "written"
    t_start = float(run.get("t_start") or time.time())
    t_end = float(run.get("t_end") or time.time())
    run.update({"cases": counts, "spent_usd": round(sp["cost_usd"], 6),
                "est_usd_at_proxy_prices": round(sp["est_usd_at_proxy_prices"], 6),
                "attempts_kept": len([p for p in (run_dir / "attempts").glob("*") if p.is_dir()]),
                "providers_seen": sorted(providers),
                "mean_live_latency_s": round(sum(lat) / len(lat), 3) if lat else None, "status": status,
                "wall_s": round(float(run.get("wall_s_before") or 0.0) + max(0.0, t_end - t_start), 1)})
    write_json(run_dir / "run.json", run)
    if not keep:
        for cid in cids:
            shutil.rmtree(run_dir / "cases" / cid / "sbx", ignore_errors=True)
            shutil.rmtree(run_dir / "cases" / cid / "results" / "logs", ignore_errors=True)
    return run


def grade(run_dir: Path) -> dict:
    """agents-cli grade + component c's summary.py, as subprocesses, only when both exist."""
    run_dir = Path(run_dir)
    run = read_json(run_dir / "run.json") or {}
    cfg = EVAL_DIR / f"eval_config_{run.get('suite')}.yaml"
    res: dict = {"agents_cli": None, "summary": None}
    if not AGENTS_CLI.is_file() or not cfg.is_file() or not SUMMARY.is_file():
        miss = [str(p) for p in (AGENTS_CLI, cfg, SUMMARY) if not p.is_file()]
        log(f"--grade skipped: missing {', '.join(miss)}")
        res["skipped"] = miss
        return res
    r = subprocess.run([str(AGENTS_CLI), "eval", "grade", "--traces", str(run_dir / "traces"), "--config", str(cfg),
                        "--output", str(run_dir / "grade"), "--qps", "500"], capture_output=True, text=True,
                       timeout=1800)
    res["agents_cli"] = r.returncode
    (run_dir / "grade").mkdir(exist_ok=True)
    (run_dir / "grade" / "agents_cli.log").write_text(r.stdout + "\n" + r.stderr)
    s = subprocess.run([sys.executable, str(SUMMARY), str(run_dir)], capture_output=True, text=True, timeout=1800)
    res["summary"] = s.returncode
    log(s.stdout[-4000:])
    return res


# -------------------------------------------------------------------------------------------------------- controls
PLAN_KEYS = ("CAUSE", "FIX", "REPRO", "TESTS")


def plan_checks(plan: str, golden: dict) -> dict:
    """The L plan checks the controls assert (a minimal copy of component c's L definitions)."""
    lines = plan.splitlines()
    fmt = plan.lstrip().startswith("FILES:") and all(any(ln.startswith(k) for ln in lines) for k in PLAN_KEYS)
    norm = plan.replace("/workspace/", "").replace("./", "")
    files = golden.get("gold_files") or []
    funcs = [f.get("name") for f in golden.get("gold_functions") or [] if f.get("name")]
    return {"format": fmt, "all_gold_files": all(f in norm for f in files),
            "functions": all(re.search(r"\b%s\b" % re.escape(n), plan) for n in funcs),
            "words": len(plan.split()) <= 120}


def control_violations(run_dir: Path, arm: str) -> list:
    """Every gradable runnable case that breaks the pre-registered 5.9 expectation of this arm."""
    run_dir = Path(run_dir)
    tfiles = sorted((run_dir / "traces").glob("*.json"))
    tr = (read_json(tfiles[0]) if tfiles else None) or {}
    by_id = {c["eval_case_id"]: c for c in tr.get("eval_cases") or []}
    bad = []
    for fp in sorted((run_dir / "cases").glob("*.json")):
        f = read_json(fp) or {}
        if f.get("status") == "skipped":
            continue
        cid, suite, variant = f.get("case_id"), f.get("suite"), f.get("variant")
        if f.get("status") != "ok":
            bad.append(f"{cid}: status {f.get('status')} ({f.get('status_detail')})")
            continue
        ec = f.get("exec_checks") or {}
        hp = ec.get("hidden_pass")
        trace = by_id.get(cid) or {}
        reply = "".join(p.get("text", "") for p in ((trace.get("responses") or [{}])[0].get("response") or {})
                        .get("parts") or [])
        golden = trace.get("golden") or {}
        if suite == "F":
            want = arm == "oracle"
            if hp is not want:
                bad.append(f"{cid}: {arm} F hidden_pass={hp}, expected {want}")
        elif suite == "V":
            want = True if arm == "oracle" else (variant == "gold")
            if hp is not want:
                bad.append(f"{cid}: {arm} V/{variant} hidden_pass={hp}, expected {want}")
        elif suite == "L":
            pc = plan_checks(reply, golden)
            if arm == "oracle":
                failed = [k for k, v in pc.items() if not v]
                if failed:
                    bad.append(f"{cid}: oracle L plan checks failed: {failed}")
            else:
                ended = TW.is_text_event(TW.first_stage_run(trace.get("agent_data") or {}, "locator")[-1]) \
                    if TW.first_stage_run(trace.get("agent_data") or {}, "locator") else False
                if not ended or pc["format"]:
                    bad.append(f"{cid}: null L ended_by_text={ended} plan_format={pc['format']}, expected 1 and 0")
    return bad


def cmd_controls(a: argparse.Namespace, *, script_hook: Callable | None = None) -> int:
    """Both arms at once (they are free), each with half of -j."""
    runners: dict = {}

    def arm_run(arm):
        b = argparse.Namespace(**vars(a))
        b.endpoint = arm
        b.run_id = f"{a.run_id or 'controls'}_{a.suite}_{a.split}_{arm}"
        b.grade = False
        b.j = max(1, a.j // 2)
        runners[arm] = r = Runner(b, script_hook=script_hook)
        run_dir = r.run()
        return arm, {"run_dir": str(run_dir), "violations": control_violations(run_dir, arm)}
    ex = cf.ThreadPoolExecutor(2)
    try:
        futs = [ex.submit(arm_run, arm) for arm in ("oracle", "null")]
        report = dict(f.result() for f in futs)
    except KeyboardInterrupt:               # the arms run in worker threads: stop them from here
        for r in list(runners.values()):
            r.interrupt()
        ex.shutdown(wait=True, cancel_futures=True)
        raise
    ex.shutdown(wait=True)
    viol = [v for arm in report.values() for v in arm["violations"]]
    write_json(Path(a.out) / f"{a.run_id or 'controls'}_{a.suite}_{a.split}_controls.json", report)
    if viol:
        log("CONTROLS FAILED (a violation means the runner or the grader is wrong, or a task is flaky):")
        for v in viol:
            log("  " + v)
        return 1
    log(f"controls {a.suite}/{a.split}: oracle and null expectations hold")
    return 0


# ----------------------------------------------------------------------------------------------------------- smoke
def gold_lines(case: dict) -> int:
    row = CK.task_row(case["golden"]["task"]) or {}
    return sum(1 for ln in (row.get("patch") or "").splitlines()
               if ln[:1] in "+-" and not ln.startswith(("+++", "---")))


def smoke_selection(datasets: dict) -> dict:
    """2 L + 2 F + 3 V (gold, wrong, empty of one task): runnable, gradable, rich, fewest gold changed lines."""
    def ok(c):
        g = c["golden"]
        return g.get("split") == "dev" and g.get("runnable") and g.get("gradable") and g.get("repo") == "rich"
    out = {}
    for s, n in (("L", 2), ("F", 2)):
        pool = sorted((c for c in datasets.get(s, []) if ok(c)), key=lambda c: (gold_lines(c), c["golden"]["task"]))
        out[s] = [c["golden"]["task"] for c in pool[:n]]
    vt = {}
    for c in datasets.get("V", []):
        if ok(c):
            vt.setdefault(c["golden"]["task"], set()).add(c["golden"].get("variant"))
    full = sorted((t for t, v in vt.items() if {"gold", "wrong", "empty"} <= v),
                  key=lambda t: (gold_lines({"golden": {"task": t}}), t))
    out["V"] = full[:1]
    return out


def smoke_estimate(sel: dict, price_in: float = RT.REF_PRICE_IN, price_out: float = RT.REF_PRICE_OUT) -> float:
    return round(sum(est_cost(s, price_in, price_out) * (3 if s == "V" else 1) * len(v) for s, v in sel.items()), 4)


def cmd_smoke(a: argparse.Namespace) -> int:
    CK.configure_tasks(a.tasks_jsonl, a.snapshots_dir, a.ws_cache)
    ds = {s: load_dataset(DATASETS / f"{s}_dev.json") for s in ("L", "F", "V")}
    sel = smoke_selection(ds)
    est = smoke_estimate(sel, a.price_in, a.price_out)
    cap = min(float(a.max_usd), SMOKE_CAP)
    log(f"smoke selection: {json.dumps(sel)}; estimated OpenRouter cost ${est:.3f} (cap ${cap:.2f})")
    if a.dry_run:
        return 0
    stamp = time.strftime("%Y%m%d_%H%M%S")
    spent, calls = 0.0, []
    for s in ("L", "F", "V"):
        if not sel[s]:
            log(f"smoke: no {s} case qualifies")
            return 1
        base = dict(vars(a), suite=s, split="dev", tasks=",".join(sel[s]), variants=None, dataset=None,
                    samples=1, holdout_reason=None, grade=False)
        if cmd_controls(argparse.Namespace(**dict(base, run_id=f"smoke_{stamp}"))) != 0:
            log("smoke: controls failed; the paid step is not run")
            return 1
    for s in ("L", "F", "V"):
        left = cap - spent
        if left <= 0.01:
            log("smoke: budget used up")
            return 1
        b = argparse.Namespace(**dict(vars(a), suite=s, split="dev", tasks=",".join(sel[s]), variants=None,
                                      dataset=None, samples=1, holdout_reason=None, grade=False, max_usd=left,
                                      run_id=f"smoke_{stamp}_{s}_{a.endpoint}"))
        run_dir = Runner(b).run()
        run = read_json(run_dir / "run.json") or {}
        spent += float(run.get("spent_usd") or 0)
        for fp in sorted((run_dir / "cases").glob("*/router.jsonl")):
            calls += [r for r in read_jsonl(fp) if r.get("served") in ("upstream", "refused")]
        g = grade_errors(run_dir)
        log(f"smoke {s}: {run.get('cases')} agents-cli errors={g}")
        if g:
            return 1
    fails = [c for c in calls if c.get("http_status") != 200]
    rt = sum(int(c.get("reasoning_tokens") or 0) for c in calls)
    lat = [float(c.get("latency_s") or 0) for c in calls if c.get("http_status") == 200]
    log(f"smoke: spent ${spent:.4f}; {len(calls)} upstream calls, {len(fails)} failed; mean latency "
        f"{(sum(lat) / len(lat)) if lat else 0:.2f}s; reasoning tokens {rt}; providers "
        f"{sorted({c.get('provider') for c in calls if c.get('provider')})}")
    if rt > 0:
        log('smoke: OpenRouter is reasoning; pass --upstream-extra \'{"reasoning": {"enabled": false}}\' on every '
            "later PROXY run (recorded in run.json)")
    return 1 if fails else 0


def grade_errors(run_dir: Path) -> int | None:
    """agents-cli grade of a run's traces with the union config: total num_cases_error (None when unavailable)."""
    cfg = EVAL_DIR / "eval_config.yaml"
    if not AGENTS_CLI.is_file() or not cfg.is_file():
        return None
    out = Path(run_dir) / "grade"
    r = subprocess.run([str(AGENTS_CLI), "eval", "grade", "--traces", str(Path(run_dir) / "traces"), "--config",
                        str(cfg), "--output", str(out), "--qps", "500"], capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        return -1
    res = sorted(out.glob("results_*.json"))
    d = read_json(res[-1]) if res else {}
    return sum(int(m.get("num_cases_error") or 0) for m in (d or {}).get("summary_metrics") or [])


# ------------------------------------------------------------------------------------------------------------- CLI
def _common_run_args(p: argparse.ArgumentParser, *, endpoint_required: bool = True) -> None:
    p.add_argument("--suite", choices=("L", "F", "V"), required=True)
    p.add_argument("--split", choices=("dev", "holdout"), required=True)
    _endpoint_args(p)
    p.add_argument("--tasks", default=None, help="comma-separated task ids")
    p.add_argument("--variants", default=None, help="V only: comma-separated gold,wrong,empty")


def _endpoint_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--upstream-base", default=_env("G4_GOLDEN_UPSTREAM_BASE", None))
    p.add_argument("--upstream-model", default=_env("G4_GOLDEN_UPSTREAM_MODEL", None))
    p.add_argument("--env-file", default=RT.DEFAULT_ENV_FILE)
    p.add_argument("--or-provider", default=None,
                   help=f"openrouter provider pin (default {RT.OR_PROVIDER_DEFAULT}; 'any' lifts the pin)")
    p.add_argument("--upstream-extra", default=None, help="JSON merged into every forwarded body")
    p.add_argument("--price-in", type=float, default=RT.PRICE_IN_DEFAULT, help="$/M for estimates (billed cost wins)")
    p.add_argument("--price-out", type=float, default=RT.PRICE_OUT_DEFAULT)
    mu = _env("G4_GOLDEN_MAX_USD", None)
    p.add_argument("--max-usd", type=float, default=float(mu) if mu is not None else None,
                   help=f"dollar cap of the run's total spend (openrouter default {DEFAULT_MAX_USD:.2f}; vllm is "
                        "uncapped unless this is given)")
    p.add_argument("--bundle", default=str(BUNDLE_DEFAULT))
    p.add_argument("--samples", type=int, default=1)
    p.add_argument("--seed-mode", choices=("off", "case"), default="off")
    p.add_argument("-j", type=int, default=int(_env("G4_GOLDEN_J", 6)))
    p.add_argument("--l4-scale", type=float, default=1.0)
    p.add_argument("--agent-env", choices=("kpar", "host"), default="kpar")
    p.add_argument("--harness-verify", action="store_true")
    p.add_argument("--faithful-env", action="store_true")
    p.add_argument("--no-extract-cache", action="store_true")
    p.add_argument("--include-ungradable", action="store_true")
    p.add_argument("--run-id", default=None)
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument("--resume", action="store_true")
    p.add_argument("--keep-sandboxes", action="store_true")
    p.add_argument("--log-bodies", action="store_true")
    p.add_argument("--holdout-reason", default=None)
    p.add_argument("--dataset", default=None)
    p.add_argument("--grade", action="store_true")
    p.add_argument("--nodes", action="store_true", help="also count hidden nodes for L and F (V always)")
    # test and relocation knobs (defaults are the real data)
    p.add_argument("--tasks-jsonl", default=None, help=argparse.SUPPRESS)
    p.add_argument("--snapshots-dir", default=None, help=argparse.SUPPRESS)
    p.add_argument("--ws-cache", default=None, help=argparse.SUPPRESS)
    p.add_argument("--plain-cache", default=None, help=argparse.SUPPRESS)
    p.add_argument("--holdout-log", default=str(HOLDOUT_LOG), help=argparse.SUPPRESS)
    p.add_argument("--child-grace", type=float, default=CHILD_GRACE_S, help=argparse.SUPPRESS)
    p.add_argument("--upstream-dead-s", type=float, default=UPSTREAM_DEAD_S, help=argparse.SUPPRESS)


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="run_suite.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run one suite x split")
    _common_run_args(r)
    r.add_argument("--endpoint", choices=("openrouter", "vllm", "oracle", "null"),
                   default=_env("G4_GOLDEN_ENDPOINT", None))
    w = sub.add_parser("write", help="exec checks + flat JSON + traces for an existing run dir")
    w.add_argument("run_dir")
    w.add_argument("-j", type=int, default=int(_env("G4_GOLDEN_J", 6)))
    w.add_argument("--keep-sandboxes", action="store_true")
    w.add_argument("--nodes", action="store_true", default=None)
    c = sub.add_parser("controls", help="oracle and null arms with the 5.9 expectations")
    _common_run_args(c)
    s = sub.add_parser("smoke", help="the one paid step (OpenRouter, <= $0.40)")
    _endpoint_args(s)
    s.add_argument("--endpoint", choices=("openrouter", "vllm"), default="openrouter")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(max_usd=SMOKE_CAP)
    return ap


def main(argv: list | None = None) -> int:
    a = parser().parse_args(argv)
    try:
        return _main(a)
    except KeyboardInterrupt:
        print("run_suite: interrupted (exit 130); a partial run is written with status 'interrupted'",
              file=sys.stderr)
        return 130


def _main(a: argparse.Namespace) -> int:
    try:
        if a.cmd == "run":
            if not a.endpoint:
                raise UsageError("--endpoint is required (or G4_GOLDEN_ENDPOINT)")
            run_dir = Runner(a).run()
            run = read_json(run_dir / "run.json") or {}
            est = run.get("est_usd_at_proxy_prices") or 0
            log(f"run {run_dir}: {run.get('cases')} spent ${run.get('spent_usd')}"
                + (f" (vllm: ${est} at proxy prices, not billed)" if est else ""))
            return 0
        if a.cmd == "write":
            run = write_run(Path(a.run_dir), j=a.j, keep=a.keep_sandboxes, nodes=a.nodes)
            log(f"written {a.run_dir}: {run.get('cases')}")
            return 0
        if a.cmd == "controls":
            return cmd_controls(a)
        if a.cmd == "smoke":
            return cmd_smoke(a)
    except UsageError as e:
        print(f"run_suite: {e}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
