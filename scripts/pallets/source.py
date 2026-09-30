"""SWE-Pallets-X as a task source for the offline tooling in tests/v10_support/tasks.py (research/pallets.md section 6).

    import sys; sys.path.insert(0, "scripts/pallets"); import source
    T = source.activate()          # tests/v10_support/tasks, rebound to the pallets data; returns the module
    T.mini_verify(T.base_ws(tid), patch, T.load_task(tid)["test_patch"], timeout=180, repo=tid)

activate() rebinds only module globals of the shared tasks module (never edits the file):
  TASKS_JSONL -> data/pallets/tasks.jsonl       SNAP_DIR -> data/pallets/snapshots
  CACHE       -> ~/.cache/g4/pallets/_ws         WORK     -> ~/.cache/g4/pallets/_work   (the kpar/golden caches stay untouched)
  sandbox_env -> PATH = the task's venv (build_envs.sh), PYTHONPATH = <ws>:<ws>/src (src only when it exists)
The venv of a task is data/pallets/task_env.json[tid] when present (written by finalize.py for the valid tasks; era venvs
such as flask-wz2 live there), else the repo's short name. Call it once per process, before any other use of the module.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAL = ROOT / "data" / "pallets"
VENVS = Path(os.environ.get("G4_PALLETS") or Path.home() / ".cache" / "g4" / "pallets")
TASK_ENV = PAL / "task_env.json"

VENV_OVERRIDE: dict = {}          # tid -> venv name; filled from task_env.json by activate(), then by callers
_T = None


def _tasks_module():
    if str(ROOT / "tests") not in sys.path:
        sys.path.insert(0, str(ROOT / "tests"))
    from v10_support import tasks as T
    return T


def repo_name(tid: str) -> str:
    return _T.load_task(tid)["repo"].split("/")[-1]


def venv_name(tid: str) -> str:
    return VENV_OVERRIDE.get(tid) or repo_name(tid)


def venv_dir(tid: str) -> Path:
    return VENVS / venv_name(tid)


def venv_ok(tid: str) -> bool:
    return (venv_dir(tid) / ".g4_pallets_ok").is_file()


def activate(task_env: Path | None = TASK_ENV):
    global _T
    T = _tasks_module()
    if _T is not None:
        return T
    orig_env = T.sandbox_env

    def pallets_sandbox_env(ws, repo: str, fake_clock=None) -> dict:
        """tasks.sandbox_env with the task's pallets venv on PATH and <ws>/src next to <ws> on PYTHONPATH.
        `repo` is the task id here (mini_verify passes repo=tid through)."""
        env = orig_env(ws, "rich", fake_clock=fake_clock)      # any kpar key: only PATH and VIRTUAL_ENV use it
        vbin = venv_dir(repo) / "bin"
        env["PATH"] = f"{vbin}:{T.SANDBOX_PATH_TAIL}"
        env["VIRTUAL_ENV"] = str(vbin.parent)
        pp = [str(ws)]
        if (Path(ws) / "src").is_dir():
            pp.append(str(Path(ws) / "src"))
        env["PYTHONPATH"] = os.pathsep.join(pp)
        return env

    T.TASKS_JSONL = PAL / "tasks.jsonl"
    T.SNAP_DIR = PAL / "snapshots"
    T.CACHE = VENVS / "_ws"
    T.WORK = VENVS / "_work"
    T._TASKS = None
    T._BASE_MEMO.clear()
    T.sandbox_env = pallets_sandbox_env
    _T = T
    if task_env is not None and Path(task_env).is_file():
        VENV_OVERRIDE.update({k: v for k, v in json.loads(Path(task_env).read_text()).items()})
    return T
