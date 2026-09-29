"""Real-harness sandboxes for the v10 integration tests (SPEC R108-R114).

Nothing here re-implements harness behaviour; every call goes through the installed swegemma / ADK code:
- ``Box``: a real ``swegemma.sandbox.subprocess.SubprocessManager`` sandbox (per-task venv, command-text rewriting of
  /tmp and /workspace, sanitised env, process-group kill), prepared with the harness's own ``setup_git_exclude``,
  ``setup_workspace_test_config`` and ``setup_baseline_commit`` exactly like ``agent_runner.run_agent_sandbox``.
- ``Box.run_command``: the real ``run_command`` tool closure of a ``SwegemmaContext`` (5,000-char head cut, JSON reply,
  CommandError duplication), i.e. byte-for-byte what the model receives.
- ``Box.run_skill``: the real ``_SkillScriptCodeExecutor.execute_script_async`` over the real
  ``AdkSandboxCodeExecutor`` (``skill_toolset.py:571`` wrapper: files materialised in a TemporaryDirectory, cwd = that
  dir, ``sys.argv = [scripts/x.py, --k, v, ...]``, ``runpy.run_path``), so dict args arrive as ``--key value``.
- ``inherited_silent_stdin``: puts an open pipe that nobody writes on fd 0, which every sandbox command inherits
  (the harness never redirects stdin, harness_runtime 2.4).
- ``DockerBox``: the Docker backend's contract without Docker (TEST_TMPDIR=<root>/tmp, TMPDIR unset, PYTHONPATH unset,
  no command rewriting, the package pip-installed editable into a throwaway venv).
- ``run_eval_cli``: ``scripts/run_eval.py eval`` (the pod runner, so the compaction wiring is exercised) in a child
  process against a mock-LLM route, returning the task rows and traces.
Heavy harness imports are lazy so collecting the test modules stays fast.
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
import time
import venv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / (os.environ.get("G4_BUNDLE") or "submissions/v10")   # G4_BUNDLE: run the v10 suite on a variant arm
SKILL_DIR = BUNDLE / "skills" / "swe-tools"
SCRIPTS = SKILL_DIR / "scripts"
HELPERS = ("install", "locate", "grep", "view", "edit", "run", "verify", "finalize", "status")
DISPLAY_SWE = "/tmp/swe"   # the path the prompts teach; the sandbox rewrites it in command text


def v10_missing() -> str | None:
    """Why the v10 helpers cannot be exercised yet (None when every CLI helper exists)."""
    if not SCRIPTS.is_dir():
        return f"v10 bundle not built yet: {SCRIPTS} missing"
    gone = [h for h in HELPERS if not (SCRIPTS / f"{h}.py").is_file()]
    return f"v10 helpers missing: {', '.join(gone)}" if gone else None


def bundle_missing() -> str | None:
    need = [BUNDLE / "agent.yaml", BUNDLE / "eval_config.yaml", SKILL_DIR / "SKILL.md"]
    gone = [str(p.relative_to(ROOT)) for p in need if not p.is_file()]
    return v10_missing() or (f"v10 bundle incomplete: {', '.join(gone)}" if gone else None)


def copy_bundle(dst: Path, src: Path = BUNDLE) -> Path:
    """Copy the bundle so tests never run helpers inside submissions/ (no __pycache__ can land there, SPEC hard rule)."""
    out = Path(dst) / src.name
    shutil.copytree(src, out, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", "._*"))
    return out


def write_tree(root: Path, files: dict[str, str | bytes]) -> None:
    for rel, content in files.items():
        p = Path(root) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8")


def git_init(ws: Path) -> None:
    """A snapshot-like repo: the snapshot's .git/config carries user.name=Agent, user.email=agent@eval."""
    for c in (["git", "init", "-q"], ["git", "config", "user.name", "Agent"], ["git", "config", "user.email", "agent@eval"],
              ["git", "add", "-A"], ["git", "commit", "-qm", "snapshot", "--allow-empty"]):
        subprocess.run(c, cwd=ws, check=True, capture_output=True)


# ---------------------------------------------------------------------------------------------------------------------
# Real subprocess sandbox
# ---------------------------------------------------------------------------------------------------------------------
@dataclass
class Box:
    mgr: Any
    sid: str
    ctx: Any
    tools: dict
    paths: dict = field(default_factory=dict)

    @property
    def root(self) -> Path:
        return Path(self.paths["root"])

    @property
    def ws(self) -> Path:
        return Path(self.paths["workspace"])

    @property
    def tmp(self) -> Path:
        return Path(self.paths["tmp"])

    @property
    def swe(self) -> Path:
        return self.tmp / "swe"

    def exec(self, command: str, timeout: int = 60):
        """Raw ``SubprocessManager.exec`` (ExecutionResult with stdout/stderr/exit_code/duration_seconds)."""
        return self.mgr.exec(self.sid, command, timeout=timeout)

    def run_command(self, command: str) -> dict:
        """The model-facing ``run_command`` tool: returns the parsed JSON reply plus ``_raw`` and ``_secs``."""
        t = time.perf_counter()
        raw = self.tools["run_command"](command=command)
        out = json.loads(raw)
        out["_raw"], out["_secs"] = raw, time.perf_counter() - t
        return out

    def run_skill(self, file_path: str, args: dict | list | None = None, positional: list | None = None,
                  skill_dir: Path = SKILL_DIR, timeout: int = 120) -> dict:
        """``run_skill_script`` through the real ADK wrapper and the real sandbox code executor."""
        import asyncio
        from google.adk.skills import load_skill_from_dir
        from google.adk.tools.skill_toolset import _SkillScriptCodeExecutor
        from swegemma.sandbox import AdkSandboxCodeExecutor

        skill = load_skill_from_dir(skill_dir)
        base = AdkSandboxCodeExecutor(sandbox=self.ctx.sandbox, timeout_seconds=timeout)
        runner = _SkillScriptCodeExecutor(base, timeout)
        t = time.perf_counter()
        res = asyncio.run(runner.execute_script_async(None, skill, file_path, args, None, positional))
        res["_secs"] = time.perf_counter() - t
        return res

    def wrapper_code(self, file_path: str, args: dict | list | None = None, positional: list | None = None,
                     skill_dir: Path = SKILL_DIR) -> str:
        from google.adk.skills import load_skill_from_dir
        from google.adk.tools.skill_toolset import _SkillScriptCodeExecutor
        return _SkillScriptCodeExecutor(None, 60)._build_wrapper_code(load_skill_from_dir(skill_dir), file_path, args,
                                                                      None, positional)

    def reset(self) -> None:
        """Test-harness reset between parametrised cases: tree back to the baseline tag, helpers uninstalled."""
        self.exec("cd /workspace && git reset -q --hard _swegemma_baseline && git clean -fdq && rm -rf /tmp/swe")

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.mgr.cleanup_all()


def make_box(files: dict[str, str | bytes], *, base_dir: Path | None = None, timeout_seconds: int = 120,
             time_minutes: float = 5.0) -> Box:
    """A sandbox prepared exactly like the agent phase of ``run_agent_sandbox`` (minus the snapshot tarball)."""
    from swegemma.budget import EvaluationBudget, HarnessLimits
    from swegemma.context import SwegemmaContext
    from swegemma.harness.container_setup import setup_baseline_commit, setup_git_exclude, setup_workspace_test_config
    from swegemma.sandbox.subprocess import SubprocessManager

    mgr = SubprocessManager(timeout_seconds=timeout_seconds, base_dir=base_dir)
    sid = mgr.start()
    paths = mgr.sandboxes[sid]
    write_tree(paths["workspace"], files)
    git_init(paths["workspace"])
    setup_git_exclude(mgr, sid)
    setup_workspace_test_config(mgr, sid, repo="synthetic/calc")
    setup_baseline_commit(mgr, sid, "baseline")
    ctx = SwegemmaContext(docker_manager=mgr, container_id=sid, problem_statement="synthetic",
                          budget=EvaluationBudget(time_minutes=time_minutes, tool_calls=1000, turns=2000),
                          harness=HarnessLimits(command_timeout_seconds=timeout_seconds))
    ctx.start_agent_session()
    return Box(mgr=mgr, sid=sid, ctx=ctx, tools=ctx.create_tools(), paths={k: str(v) for k, v in paths.items()})


@contextlib.contextmanager
def inherited_silent_stdin():
    """fd 0 becomes the read end of a pipe whose write end stays open and silent: a blocking read never returns.

    The harness starts every sandbox command without redirecting stdin, so children inherit this fd.
    """
    r, w = os.pipe()
    saved = os.dup(0)
    try:
        os.dup2(r, 0)
        yield
    finally:
        os.dup2(saved, 0)
        for fd in (saved, r, w):
            with contextlib.suppress(OSError):
                os.close(fd)


# ---------------------------------------------------------------------------------------------------------------------
# Docker-like environment (no Docker needed)
# ---------------------------------------------------------------------------------------------------------------------
@dataclass
class DockerBox:
    root: Path
    ws: Path
    tmp: Path
    venv: Path
    env: dict

    @property
    def swe(self) -> Path:
        return self.tmp / "swe"

    def sh(self, command: str, timeout: int = 120, stdin_data: str | None = None) -> subprocess.CompletedProcess:
        """``bash -c`` in the workspace, new session, NO command rewriting (docker.py:693-712)."""
        return subprocess.run(["/bin/bash", "-c", command], cwd=self.ws, env=self.env, capture_output=True, text=True,
                              timeout=timeout, start_new_session=True, input=stdin_data,
                              stdin=None if stdin_data is not None else subprocess.DEVNULL)

    def helper(self, name: str, *args: str, stdin_data: str | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
        """``python3 /tmp/swe/<name>.py`` inside the container == ``$TEST_TMPDIR/swe/<name>.py`` here."""
        import shlex
        return self.sh(" ".join(["python3", shlex.quote(str(self.swe / f"{name}.py")), *map(shlex.quote, args)]),
                       stdin_data=stdin_data, timeout=timeout)


def make_docker_box(root: Path, files: dict[str, str | bytes], *, wheels: Path) -> DockerBox:
    """TMPDIR unset, TEST_TMPDIR=<root>/tmp (docker.py:93), PYTHONPATH unset, package installed editable."""
    root = Path(root)
    ws, tmp, vdir = root / "workspace", root / "tmp", root / "venv"
    ws.mkdir(parents=True)
    tmp.mkdir()
    write_tree(ws, files)
    git_init(ws)
    with open(ws / ".git" / "info" / "exclude", "a") as f:
        f.write("__pycache__/\n*.pyc\n.pytest_cache/\n*.egg-info/\nbuild/\ndist/\n.coverage\n.adk_exec_*.py\n")
    venv.create(vdir, with_pip=True, symlinks=True, clear=True)
    py = vdir / "bin" / "python3"
    pip_env = {**os.environ, "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    for spec in (["pytest"], ["--no-deps", "-e", str(ws)]):   # the image has pytest; the repo goes in editable
        r = subprocess.run([str(py), "-m", "pip", "install", "-q", "--no-index", "--find-links", str(wheels), *spec],
                           capture_output=True, text=True, timeout=300, env=pip_env)
        if r.returncode != 0:
            raise RuntimeError(f"pip install {spec} failed: " + (r.stderr or r.stdout)[-800:])
    subprocess.run(["git", "add", "-A"], cwd=ws, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "baseline", "--allow-empty"], cwd=ws, check=True, capture_output=True)
    subprocess.run(["git", "tag", "-f", "_swegemma_baseline"], cwd=ws, check=True, capture_output=True)
    env = {"PATH": f"{vdir / 'bin'}:/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(root / "home"), "LANG": "C.UTF-8",
           "TEST_TMPDIR": str(tmp), "SWE_DUAL": "0"}
    (root / "home").mkdir()
    return DockerBox(root=root, ws=ws, tmp=tmp, venv=vdir, env=env)


# ---------------------------------------------------------------------------------------------------------------------
# The pod runner (scripts/run_eval.py) against a mock-LLM route
# ---------------------------------------------------------------------------------------------------------------------
@dataclass
class EvalRun:
    rc: int
    rows: list
    results_dir: Path
    stdout: str
    stderr: str
    secs: float

    def row(self, iid: str) -> dict:
        return next(r for r in self.rows if r["instance_id"] == iid)

    def trace(self, iid: str) -> dict:
        p = self.results_dir / "traces" / f"trace_{iid}.json"
        return json.loads(p.read_text()) if p.is_file() else {}

    def patch(self, iid: str) -> str:
        p = self.results_dir / "patches" / f"{iid}.patch"
        return p.read_text(errors="replace") if p.is_file() else ""

    def log(self, iid: str) -> str:
        p = self.results_dir / "logs" / f"{iid}.log"
        return p.read_text(errors="replace") if p.is_file() else ""


def run_eval_cli(*, bundle: Path, tasks: Path, snapshots: Path, results: Path, api_base: str, task_ids: list[str],
                 max_time_minutes: float = 5, timeout_seconds: int = 120, max_tool_calls: int = 100,
                 max_turns: int = 200, concurrency: int = 1, env_extra: dict | None = None,
                 timeout: float = 600) -> EvalRun:
    """Run ``scripts/run_eval.py eval`` exactly as pod/run_eval.sh does, minus the pod-only environment install.

    ``G4_FAITHFUL_ENV=0`` keeps the stock harness environment (host site-packages; the pod's /root/buildenv does not
    exist here); compaction stays at its run_eval default (on). Sandboxes are created under ``results`` (TMPDIR), so
    the ``no_orphans`` fixture sees every process they start.
    """
    results = Path(results)
    results.mkdir(parents=True, exist_ok=True)
    sbx = results / "sbx"
    sbx.mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items()
           if k not in ("MODEL_PROXY_URL", "LITELLM_API_BASE", "LOCAL_INFERENCE_URL", "MODEL_PROXY_API_KEY",
                        "LITELLM_API_KEY", "LOCAL_API_KEY", "G4_L4_SCALE", "G4_COMPACTION", "G4_NO_EDITABLE")}
    env.update({"OPENAI_BASE_URL": api_base, "OPENAI_API_KEY": "EMPTY", "G4_FAITHFUL_ENV": "0", "TMPDIR": str(sbx),
                "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"})
    env.pop("TEST_TMPDIR", None)
    env.update(env_extra or {})
    argv = [sys.executable, str(ROOT / "scripts" / "run_eval.py"), "eval", "--tasks", str(tasks),
            "--snapshots-dir", str(snapshots), "--submission-dir", str(bundle), "--results-dir", str(results),
            "--sandbox", "subprocess", "--max-time-minutes", str(max_time_minutes), "--max-tool-calls",
            str(max_tool_calls), "--max-turns", str(max_turns), "--timeout-seconds", str(timeout_seconds),
            "--concurrency", str(concurrency), "--display", "quiet", "--task-ids", *task_ids]
    t = time.perf_counter()
    p = subprocess.run(argv, cwd=results, env=env, capture_output=True, text=True, timeout=timeout,
                       stdin=subprocess.DEVNULL, start_new_session=True)
    rows = []
    rp = results / "task_results.jsonl"
    if rp.is_file():
        rows = [json.loads(line) for line in rp.read_text().splitlines() if line.strip()]
    return EvalRun(rc=p.returncode, rows=rows, results_dir=results, stdout=p.stdout, stderr=p.stderr,
                   secs=time.perf_counter() - t)


def trace_observations(trace: dict) -> list[tuple[str, str, str]]:
    """(author, tool name, observation text) for every agent tool step of a SessionTrace JSON."""
    out = []
    for s in trace.get("steps") or []:
        if s.get("source") != "agent":
            continue
        tcs = s.get("tool_calls") or []
        obs = s.get("observation") or {}
        txt = obs.get("content") if isinstance(obs, dict) else str(obs)
        author = (s.get("extra") or {}).get("author") or (tcs and (tcs[0].get("extra") or {}).get("author")) or "?"
        out.append((author, tcs[0]["function_name"] if tcs else "", str(txt or "")))
    return out
