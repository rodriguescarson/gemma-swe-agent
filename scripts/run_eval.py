"""swegemma eval with a faithful per-task Python environment for the subprocess sandbox.

Why: SubprocessManager builds each sandbox venv with system_site_packages=True, so the harness's own packages
(requests, rich, httpx, starlette via litellm/ADK) shadow the repository under test, and install_test_dependencies
is a no-op for subprocess sandboxes. Here each sandbox (agent phase and verification phase alike) drops the host link and
pip-installs /workspace plus its test requirements from the competition wheels, letting pip honour version pins.
Usage: python scripts/run_eval.py [--oracle] eval <swegemma eval args>

Faithfulness switches (SPEC section 10.1, R115); every default leaves other callers of swegemma untouched:
  G4_COMPACTION   default 1: EvalConfig gets EventsCompactionConfig(compaction_interval=15, overlap_size=2,
                  token_threshold=14336, event_retention_size=5), the live organiser README value (HARNESS_README section
                  7.2; the 25 Sep copy said interval 5) and the one scripts/make_eval_kernel.py COMPACTION uses on Kaggle.
                  Pod races never compacted before this (config_space finding 6). 0 disables it.
  G4_L4_SCALE=s   divides --max-time-minutes and --timeout-seconds by s (H100 -> L4 wall ratio, time_model 6) and
                  writes s to /tmp/swe/clock_scale in every AGENT sandbox (the command text is rewritten by the
                  subprocess sandbox, so it lands in <sandbox>/tmp/swe), so v10 helper footers fire at L4-equivalent times.
  G4_NO_EDITABLE  1: skip the `pip install -e /workspace` step (Kaggle installs nothing into /workspace, F9d).
  G4_FAITHFUL_ENV default 1: the pod environment install below. 0 keeps the stock harness environment (the offline
                  Mac flow tests use it; /root/buildenv does not exist there). Replay mode defaults it to 0.
Importing this module changes nothing; only main() patches the harness.

Replay mode (the scorer-faithful grader):
  python scripts/run_eval.py --patches FILE eval --tasks T --snapshots-dir S --results-dir R [--timeout-seconds 300] ...
  FILE is a JSON list (or JSONL) of {"task": id, "cfg": any label, "patch": unified diff, "agent_error": optional text};
  "id" is accepted for "task". The agent phase is replaced, like --oracle, by the listed patch (and agent_error) of that
  entry. A run that errored AND left an empty patch is unresolved without any test run (swegemma evaluate_task returns early),
  so a "free" task (one whose hidden tests pass on the unpatched base) is resolved with an empty patch only when the run
  had no agent_error; pass the error text to replay that. The verification phase is swegemma's
  own verify_task (protected-file stripping, git apply pipeline, test_patch, pytest with -p no:anyio, JUnit checks), run on
  the subprocess sandbox. Output: R/replay_results.jsonl, one row per entry in entry order: idx, cfg, task, resolved,
  test_exit_code, phase (tests | patch_apply | agent_error | infra), error, secs, patch_sha1, patch_len, agent_error, timed_out,
  test_summary,
  failed (up to 40 node ids), test_tail (last 3,000 characters), dedup_of when the row repeats an earlier identical
  (task, patch) and was not re-run. resolved is null for phase infra (no verdict: the tests never ran).
  Phase 2 uses --timeout-seconds (the scorer fixes it at 300; it is the default here). G4_L4_SCALE is ignored.
  The host python's site-packages are the test environment (SubprocessManager links them into every sandbox), so run it
  with the interpreter of a scorer-faithful venv. --concurrency N grades N entries at once.
  G4_WS_CACHE=DIR   clone DIR/<task>/base (an extracted, harness-prepared workspace) into the sandbox instead of
                    extracting <snapshots-dir>/<task>.tgz; a missing <task>.tgz is created empty so the task is found.
                    cp -c makes it an APFS clone (no disk, no gzip). Tasks without DIR/<task>/base use the tarball.
  G4_REPLAY_DEDUPE  default 1: grade each distinct (task, patch) once. 0 grades every entry (flake checks).
  G4_REPLAY_RESUME  1: keep rows already in R/replay_results.jsonl (same cfg, task and patch) and run only the rest;
                    rows with phase infra are run again.
  G4_REPLAY_LOGS    1: also write each entry's full test output to R/replay_logs/<idx>_<task>.log.
  G4_REPLAY_KEEP_RESULTS  1: also write swegemma's own task_results.jsonl/summary.json/patches/test_outputs for the graded rows
                    (they are keyed by task only, so a repeated task keeps the last one).
"""
import hashlib
import json
import logging
import os
import re
import shlex
import sys

log = logging.getLogger("run_eval")

# The scorer's values, HARNESS_README section 7.2 (compaction_interval 15; the 25 Sep README said 5) and the host notebook;
# tests/test_v10_runner.py pins them equal to scripts/make_eval_kernel.py COMPACTION.
COMPACTION = {"compaction_interval": 15, "overlap_size": 2, "token_threshold": 14336, "event_retention_size": 5}

SETUP_HEAD = r'''
set -e
SP=$(python3 -c "import sysconfig;print(sysconfig.get_paths()['purelib'])")
echo /root/buildenv/lib/python3.12/site-packages > "$SP/_host_env.pth"
REPO_PKG="${REPO_PKG:-}"
cd /workspace
python3 - <<'PY' > /tmp/_reqs.txt
import os, re, glob, tomllib
have = {re.split(r"-", f)[0].lower().replace("_", "-") for f in os.listdir("/wheels") if f.endswith(".whl")}
have -= {os.environ.get("REPO_PKG", "").lower()}
lines = ["pytest"]
def keep(req):
    req = req.split(";")[0].strip()
    m = re.match(r"([A-Za-z0-9_.\-]+)(\[[^\]]*\])?\s*(.*)", req)
    if not m: return
    name = m.group(1).lower().replace("_", "-")
    if name in have: lines.append(name + " " + m.group(3).strip())
for f in sorted(set(glob.glob("requirements*.txt") + glob.glob("requirements/*.txt"))):
    if "doc" in f: continue
    for l in open(f):
        l = l.strip()
        if l and not l.startswith(("#", "-")): keep(l)
if os.path.exists("pyproject.toml"):
    d = tomllib.load(open("pyproject.toml", "rb"))
    for r in (d.get("project", {}).get("dependencies") or []): keep(r)
    for n in (d.get("tool", {}).get("poetry", {}).get("dependencies") or {}): keep(n)
    for grp in list((d.get("project", {}).get("optional-dependencies") or {}).values()) + list((d.get("dependency-groups") or {}).values()):
        for r in grp:
            if isinstance(r, str) and not any(k in r for k in ("doc", "mkdocs")): keep(r)
    poetry = d.get("tool", {}).get("poetry", {})
    for sec in [poetry.get("dev-dependencies") or {}] + [g.get("dependencies", {}) for g in (poetry.get("group") or {}).values()]:
        for n in sec: keep(n)
print("\n".join(dict.fromkeys(l.strip() for l in lines)))
PY
printf "pydantic>=2\n" > /tmp/_cons.txt
python3 -m pip install -q --no-index --find-links=/wheels -c /tmp/_cons.txt -r /tmp/_reqs.txt 2>/tmp/_pip.err \
 || while read -r r; do python3 -m pip install -q --no-index --find-links=/wheels "$(echo $r | cut -d' ' -f1)" 2>>/tmp/_pip.err || true; done < /tmp/_reqs.txt
python3 -m pip install -q --no-index --find-links=/wheels "pydantic>=2" 2>>/tmp/_pip.err || true
'''
EDITABLE_STEP = "python3 -m pip install -q --no-index --find-links=/wheels --no-deps --force-reinstall --no-build-isolation -e /workspace 2>>/tmp/_pip.err || true\n"
SETUP_TAIL = "echo ENV_OK\n"


def setup_script(no_editable=False):
    """The pod environment script; with no_editable the repo is only importable through PYTHONPATH, as on Kaggle."""
    return SETUP_HEAD + ("" if no_editable else EDITABLE_STEP) + SETUP_TAIL


SETUP = setup_script(False)   # backwards-compatible name (the historical script, editable install included)


def env_flag(name, default="0"):
    return (os.environ.get(name, default) or default).strip().lower() in ("1", "true", "yes", "on")


def faithful_install(docker, container_id, repo="", *, fast_path=True, config=None):
    pkg = (repo or "").rsplit("/", 1)[-1].lower()
    script = setup_script(no_editable=env_flag("G4_NO_EDITABLE"))
    res = docker.exec(container_id, "REPO_PKG=" + shlex.quote(pkg) + " bash -c " + shlex.quote(script))
    if "ENV_OK" not in (res.stdout or ""):
        log.warning("env setup failed for %s: %s", repo, (res.stderr or "")[-800:])


faithful_install._g4 = True
_HARNESS_ORIG = {}   # module name -> the harness's own install_test_dependencies (main() may run more than once)


def _harness_original(mod):
    cur = mod.install_test_dependencies
    if not getattr(cur, "_g4", False):
        _HARNESS_ORIG[mod.__name__] = cur
    return _HARNESS_ORIG.get(mod.__name__, cur)


def l4_scale():
    """G4_L4_SCALE as a float > 0, or None when unset/empty. Invalid values stop the run before any GPU time."""
    raw = (os.environ.get("G4_L4_SCALE") or "").strip()
    if not raw:
        return None
    try:
        s = float(raw)
    except ValueError:
        raise SystemExit(f"run_eval: G4_L4_SCALE must be a number, got {raw!r}")
    if not 0.2 <= s <= 5.0:   # the helpers clamp clock_scale to 0.2..5 (SPEC 4.1.5); refuse what they would ignore
        raise SystemExit(f"run_eval: G4_L4_SCALE must be within 0.2..5, got {s}")
    return s


def scale_argv(argv, s):
    """Divide --max-time-minutes (float) and --timeout-seconds (int, rounded, >= 1) by s; both '--k v' and '--k=v'."""
    def conv(key, val):
        if key == "--max-time-minutes":
            return repr(round(float(val) / s, 6))
        return str(max(1, int(round(float(val) / s))))
    out, i = [], 0
    keys = ("--max-time-minutes", "--timeout-seconds")
    while i < len(argv):
        a = argv[i]
        k, eq, v = a.partition("=")
        if k in keys and eq:
            out.append(f"{k}={conv(k, v)}")
        elif a in keys and i + 1 < len(argv):
            out += [a, conv(a, argv[i + 1])]
            i += 1
        else:
            out.append(a)
        i += 1
    return out


def clock_scale_cmd(s):
    # /tmp is rewritten to <sandbox>/tmp in command text by the subprocess sandbox (subprocess.py:432-481), so this
    # lands exactly where the helpers look ($TEST_TMPDIR/swe); in Docker /tmp is the container's own.
    return f"mkdir -p /tmp/swe && printf '%s\\n' {shlex.quote(repr(s))} > /tmp/swe/clock_scale"


def agent_install(base, s):
    """The agent-phase install_test_dependencies: base behaviour, then the clock_scale write."""
    def install(docker, container_id, repo="", *, fast_path=True, config=None):
        base(docker, container_id, repo, fast_path=fast_path, config=config)
        res = docker.exec(container_id, clock_scale_cmd(s))
        if getattr(res, "exit_code", 0) not in (0, None):
            log.warning("clock_scale write failed in %s: %s", container_id, getattr(res, "stderr", ""))
    install.__name__ = "agent_install_with_clock_scale"
    install._g4 = True
    return install


def install_patches(faithful, scale):
    """Patch the harness module globals (idempotent: always built from the harness originals).

    Returns the harness originals so callers (tests) can restore them."""
    import swegemma.harness.agent_runner as ar
    import swegemma.harness.container_setup as cs
    import swegemma.harness.verification as vf
    orig = {m: _harness_original(m) for m in (ar, vf, cs)}
    base = faithful_install if faithful else orig[ar]
    ar.install_test_dependencies = agent_install(base, scale) if scale else base
    for m in (vf, cs):
        m.install_test_dependencies = faithful_install if faithful else orig[m]
    return orig


def compaction_config():
    import warnings
    try:
        from google.adk.apps._configs import EventsCompactionConfig
    except ImportError:
        from google.adk.apps.app import EventsCompactionConfig
    with warnings.catch_warnings():   # ADK flags the class [EXPERIMENTAL] on every construction; the scorer uses it
        warnings.simplefilter("ignore", UserWarning)
        return EventsCompactionConfig(**COMPACTION)


def wrap_eval_config(enabled):
    """cli.EvalConfig -> a factory that adds the compaction config unless the caller passed one."""
    import swegemma.cli as cli
    base = getattr(cli.EvalConfig, "__wrapped__", cli.EvalConfig)   # re-entrant: never wrap our own wrapper

    def EvalConfig(*a, **kw):
        if enabled and kw.get("events_compaction_config") is None:
            kw["events_compaction_config"] = compaction_config()
        return base(*a, **kw)

    EvalConfig.__wrapped__ = base
    cli.EvalConfig = EvalConfig
    return base


def log_compactions(path):
    """Append every in-flow compaction to a JSONL file (events in, characters the summarizer saw, the summary it wrote):
    the trace records no compaction event, and the summary is what the agent keeps of everything before it."""
    import json
    import time
    from google.adk.apps.llm_event_summarizer import LlmEventSummarizer
    orig = getattr(LlmEventSummarizer.maybe_summarize_events, "__wrapped__", LlmEventSummarizer.maybe_summarize_events)

    async def maybe_summarize_events(self, *, events):
        t = time.perf_counter()
        ev = await orig(self, events=events)
        comp = ev.actions.compaction if ev is not None and ev.actions else None
        parts = (comp.compacted_content.parts or []) if comp and comp.compacted_content else []
        rec = {"t": round(time.time(), 3), "secs": round(time.perf_counter() - t, 2), "events_in": len(events),
               "chars_in": len(self._format_events_for_prompt(events)),
               "summary": "".join(p.text or "" for p in parts if not getattr(p, "thought", False))}
        with open(path, "a") as f:
            f.write(json.dumps(rec) + "\n")
        return ev

    maybe_summarize_events.__wrapped__ = orig
    LlmEventSummarizer.maybe_summarize_events = maybe_summarize_events
    return orig


# ---------------------------------------------------------------------------------------------------------------------
# Replay mode: grade given patches with the scorer's own verification
# ---------------------------------------------------------------------------------------------------------------------
TEST_TAIL_CHARS = 3000
MAX_FAILED_IDS = 40
SUMMARY_RE = re.compile(r"^[= ]*(\d+ (?:passed|failed|skipped|errors?|deselected|xfailed|xpassed|warnings?)[^\n]*?) in [0-9.]+s",
                        re.M)
FAILED_RE = re.compile(r"^(?:FAILED|ERROR) (\S+)", re.M)


def pop_option(argv, name):
    """Remove `--name VALUE` or `--name=VALUE` from argv (in place); the value, or None when absent."""
    for i, a in enumerate(argv):
        if a == name and i + 1 < len(argv):
            v = argv[i + 1]
            del argv[i:i + 2]
            return v
        if a.startswith(name + "="):
            del argv[i]
            return a.split("=", 1)[1]
    return None


def has_option(argv, name):
    return any(a == name or a.startswith(name + "=") for a in argv)


def patch_sha1(patch):
    return hashlib.sha1(patch.encode("utf-8", "surrogateescape")).hexdigest()


def entry_key(e):
    """Two entries with the same key get the same verdict: task, patch and agent error (cfg is only a label)."""
    return (e["task"], patch_sha1(e["patch"]), e.get("agent_error"))


def load_patches(path):
    """[{task, cfg, patch}] from a JSON list or JSONL file; "id" stands in for "task", a missing patch is empty."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    try:
        data = json.loads(text) if text.lstrip().startswith("[") else [json.loads(x) for x in text.splitlines() if x.strip()]
    except ValueError as e:
        raise SystemExit(f"run_eval: --patches {path} is not valid JSON/JSONL: {e}")
    if not isinstance(data, list) or not data:
        raise SystemExit(f"run_eval: --patches {path} holds no entries (expected a non-empty JSON list)")
    out = []
    for n, e in enumerate(data):
        if not isinstance(e, dict):
            raise SystemExit(f"run_eval: --patches entry {n} is not an object")
        task = e.get("task", e.get("id"))
        patch = e.get("patch")
        patch = "" if patch is None else patch
        if not isinstance(task, str) or not task.strip():
            raise SystemExit(f"run_eval: --patches entry {n} has no task id")
        if not isinstance(patch, str):
            raise SystemExit(f"run_eval: --patches entry {n} ({task}): patch must be a string")
        agent_error = e.get("agent_error")
        if agent_error is not None and not isinstance(agent_error, str):
            raise SystemExit(f"run_eval: --patches entry {n} ({task}): agent_error must be a string")
        out.append({"task": task.strip(), "cfg": e.get("cfg"), "patch": patch, "agent_error": agent_error or None})
    return out


def replay_row(idx, entry, res, wall):
    """One result row from a swegemma TaskResult (or None when grading itself raised)."""
    patch = entry["patch"]
    out = (getattr(res, "test_output", "") or "") if res is not None else ""
    code = getattr(res, "test_exit_code", -1) if res is not None else -1
    err = (str(res.error) if res is not None and res.error else None)
    if res is None:
        phase = "infra"
    elif entry.get("agent_error") and not patch.strip():
        phase = "agent_error"                     # unresolved without a test run: the scorer's early return
    elif err and err.startswith("Failed to apply agent patch"):
        phase = "patch_apply"
    elif code == -1:
        phase = "infra"
    else:
        phase = "tests"
    sums = SUMMARY_RE.findall(out)
    failed = list(dict.fromkeys(FAILED_RE.findall(out)))
    return {"idx": idx, "cfg": entry["cfg"], "task": entry["task"],
            "resolved": None if phase == "infra" else bool(res.resolved),
            "test_exit_code": code, "phase": phase, "error": (err or "")[:500] or None, "secs": round(wall, 1),
            "patch_sha1": patch_sha1(patch), "patch_len": len(patch), "agent_error": entry.get("agent_error"),
            "timed_out": code == 124,
            "test_summary": sums[-1] if sums else None, "failed": failed[:MAX_FAILED_IDS], "test_tail": out[-TEST_TAIL_CHARS:]}


def make_ws_cache_extractor(manager, cache_dir):
    """The harness's own extension point (extract_snapshot calls docker.extract_archive_to_container when it exists):
    clone <cache_dir>/<task>/base into the sandbox workspace. False -> the harness falls back to extracting the tarball."""
    import subprocess
    from pathlib import Path
    cache = Path(cache_dir)

    def extract_archive_to_container(container_id, archive_path, dst_dir="/workspace"):
        tid = Path(archive_path).name.split(".")[0]
        src = cache / tid / "base"
        if not src.is_dir():
            return False
        ws = manager.sandboxes[container_id]["workspace"]
        for flags in (["-c", "-R"], ["-R"]):         # APFS clone first, plain copy when the volumes differ
            r = subprocess.run(["cp", *flags, f"{src}/.", str(ws)], capture_output=True, text=True)
            if r.returncode == 0:
                return True
        raise RuntimeError(f"ws cache copy of {src} failed: {r.stderr[-300:]}")

    return extract_archive_to_container


def make_replay_evaluator(entries):
    """A swegemma Evaluator whose run() grades `entries` (the --patches list) instead of running an agent."""
    import asyncio
    import contextvars
    import time
    from pathlib import Path

    from adk_eval_core.tracing import SessionTrace
    import swegemma.evaluate as ev
    from swegemma.models import EvaluationResult, TaskResult, load_tasks

    current = contextvars.ContextVar("g4_replay_entry", default=("", None))

    class ReplayEvaluator(ev.Evaluator):
        replay_entries = entries

        def __init__(self, config):
            super().__init__(config)
            self.rows = []
            cache = os.environ.get("G4_WS_CACHE", "").strip()
            self.ws_cache = cache or None
            if self.ws_cache and config.sandbox == "subprocess":
                self.sandbox.extract_archive_to_container = make_ws_cache_extractor(self.sandbox, self.ws_cache)

        async def _run_agent_sandbox(self, task, snapshot_path, task_index, total_tasks, **kw):
            patch, agent_error = current.get()
            return patch, agent_error, SessionTrace()       # the listed patch and error; no agent

        def _placeholder_snapshots(self, ids):
            """With a ws cache, a task whose tarball is absent still has to be found by evaluate_task."""
            from swegemma.deduplication import resolve_task_snapshot_paths
            for tid, repo in ids:
                if not (Path(self.ws_cache) / tid / "base").is_dir():
                    continue
                if not resolve_task_snapshot_paths(self.config.snapshots_dir, tid, repo)[0].exists():
                    Path(self.config.snapshots_dir).mkdir(parents=True, exist_ok=True)
                    (Path(self.config.snapshots_dir) / f"{tid}.tgz").touch()

        async def run(self):
            cfg = self.config
            tasks = {t.instance_id: self._hydrate_task_from_secret(t) for t in load_tasks(cfg.tasks_path)}
            want = set(cfg.task_ids) if cfg.task_ids else None
            todo = [(i, e) for i, e in enumerate(self.replay_entries) if want is None or e["task"] in want]
            res_dir = Path(cfg.results_dir)
            res_dir.mkdir(parents=True, exist_ok=True)
            out_path = res_dir / "replay_results.jsonl"
            logs = res_dir / "replay_logs" if env_flag("G4_REPLAY_LOGS") else None
            if logs:
                logs.mkdir(exist_ok=True)
            if self.ws_cache:
                self._placeholder_snapshots([(e["task"], tasks[e["task"]].repo) for _, e in todo if e["task"] in tasks])

            keep = {}                                    # (cfg, task, sha1) -> a row from an earlier run (resume)
            if env_flag("G4_REPLAY_RESUME") and out_path.is_file():
                for line in out_path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        r = json.loads(line)
                        if r.get("phase") != "infra":
                            keep[(json.dumps(r["cfg"]), r["task"], r["patch_sha1"], r.get("agent_error"))] = r
            dedupe = env_flag("G4_REPLAY_DEDUPE", "1")
            sem = asyncio.Semaphore(max(1, cfg.concurrency or 1))
            lock = asyncio.Lock()
            first = {}                                   # (task, sha1) -> asyncio.Future of the first entry's row
            rows, results = {}, []

            async def emit(row):
                async with lock:
                    rows[row["idx"]] = row
                    with open(out_path, "a", encoding="utf-8") as f:
                        f.write(json.dumps(row) + "\n")

            async def grade(idx, e):
                task = tasks.get(e["task"])
                if task is None:
                    return replay_row(idx, e, None, 0.0) | {"error": f"task {e['task']} is not in {cfg.tasks_path}"}
                tok = current.set((e["patch"], e.get("agent_error")))
                t0 = time.perf_counter()
                try:
                    res = await self.evaluate_task(task, task_index=idx + 1, total_tasks=len(self.replay_entries))
                except Exception as ex:                  # never lose the other entries to one failure
                    logging.getLogger("run_eval").exception("replay entry %d (%s) raised", idx, e["task"])
                    return replay_row(idx, e, None, time.perf_counter() - t0) | {"error": f"grader exception: {ex!r}"[:500]}
                finally:
                    current.reset(tok)
                if logs and res.test_output:
                    (logs / f"{idx}_{e['task']}.log").write_text(res.test_output, encoding="utf-8")
                results.append(res)
                return replay_row(idx, e, res, time.perf_counter() - t0)

            async def one(idx, e):
                key = entry_key(e)
                if dedupe and key in first:              # an earlier entry (or a resumed row) already owns this key
                    src = await first[key]
                    await emit(dict(src, idx=idx, cfg=e["cfg"], dedup_of=src.get("dedup_of", src["idx"])))
                    return
                fut = asyncio.get_running_loop().create_future()
                if dedupe:
                    first[key] = fut
                prior = keep.get((json.dumps(e["cfg"]), *key))
                if prior is not None:
                    row = {k: v for k, v in prior.items() if k != "dedup_of"} | {"idx": idx, "resumed": True}
                else:
                    async with sem:
                        row = await grade(idx, e)
                fut.set_result(row)
                await emit(row)

            out_path.unlink(missing_ok=True)             # rewritten row by row from here (resumed rows included)
            try:
                await asyncio.gather(*(one(i, e) for i, e in todo))
            finally:
                if hasattr(self.docker, "cleanup_all"):
                    try:
                        self.docker.cleanup_all()
                    except Exception as cleanup_err:     # noqa: BLE001
                        logging.getLogger("run_eval").debug("cleanup_all notice: %s", cleanup_err)
            ordered = [rows[i] for i in sorted(rows)]
            tmp = out_path.with_suffix(".jsonl.tmp")
            tmp.write_text("".join(json.dumps(r) + "\n" for r in ordered), encoding="utf-8")
            tmp.replace(out_path)                        # final file: one row per entry, entry order
            self.rows = ordered
            if env_flag("G4_REPLAY_KEEP_RESULTS"):       # swegemma's own task_results.jsonl/summary for the unique runs
                ev.save_results(EvaluationResult(task_results=results), res_dir)
            n_ok = sum(1 for r in ordered if r["resolved"] is True)
            n_infra = sum(1 for r in ordered if r["phase"] == "infra")
            log.info("replay: %d entries, %d resolved, %d infra (no verdict) -> %s", len(ordered), n_ok, n_infra, out_path)
            return EvaluationResult(task_results=[
                TaskResult(instance_id=r["task"], repo="", resolved=bool(r["resolved"]), agent_patch="", test_output="",
                           test_exit_code=r["test_exit_code"], duration_seconds=r["secs"], error=r["error"]) for r in ordered])

    return ReplayEvaluator


def replay_main(argv, patches_file):
    """--patches: the scorer's verification on the listed patches (see the module docstring). No agent, no model."""
    entries = load_patches(patches_file)
    if not has_option(argv, "--timeout-seconds"):
        argv += ["--timeout-seconds", "300"]             # the scorer's fixed Phase 2 limit (HARNESS_README 7.1)
    if not has_option(argv, "--submission-dir"):         # the cli wants one to build a model registry nobody calls
        argv += ["--submission-dir", results_dir_option(argv) or "."]
    if not has_option(argv, "--sandbox"):
        argv += ["--sandbox", "subprocess"]
    install_patches(faithful=env_flag("G4_FAITHFUL_ENV", "0"), scale=None)   # the stock harness environment by default
    import swegemma.cli as cli
    cli.Evaluator = make_replay_evaluator(entries)
    log.info("run_eval: replay of %d entries from %s", len(entries), patches_file)
    return cli.main(argv)


def results_dir_option(argv):
    for i, a in enumerate(argv):
        if a == "--results-dir" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--results-dir="):
            return a.split("=", 1)[1]
    return None


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    oracle = "--oracle" in argv
    if oracle:
        argv.remove("--oracle")
    patches_file = pop_option(argv, "--patches")
    if patches_file is not None:
        if oracle:
            raise SystemExit("run_eval: --patches and --oracle both replace the agent; pick one")
        return replay_main(argv, patches_file)
    scale = l4_scale()
    if scale:
        argv = scale_argv(argv, scale)
    install_patches(faithful=env_flag("G4_FAITHFUL_ENV", "1"), scale=scale)
    wrap_eval_config(enabled=env_flag("G4_COMPACTION", "1"))
    if env_flag("G4_COMPACTION", "1") and "--results-dir" in argv:
        log_compactions(os.environ.get("G4_COMPACTION_LOG")
                        or os.path.join(argv[argv.index("--results-dir") + 1], "compactions.jsonl"))
    log.info("run_eval: compaction=%s l4_scale=%s no_editable=%s", env_flag("G4_COMPACTION", "1"), scale,
             env_flag("G4_NO_EDITABLE"))
    if oracle:
        from adk_eval_core.tracing import SessionTrace
        import swegemma.evaluate as ev

        async def _oracle(self, task, snapshot_path, task_index, total_tasks, **kw):
            return task.patch, None, SessionTrace()
        ev.Evaluator._run_agent_sandbox = _oracle
    from swegemma.cli import main as cli_main
    return cli_main(argv)


if __name__ == "__main__":
    sys.exit(main())
