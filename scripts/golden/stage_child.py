"""One golden case sample in its own process (docs/eval/GOLDEN_EVALS_SPEC.md v1.1, 5.4, 5.5).

    stage_child.py [--no-extract-cache] [--agent-env {kpar,host}] [--kpar-site DIR] [--harness-verify]
                   [--plain-cache DIR] [--faithful-env] -- <scripts/run_eval.py argv: eval --tasks ...>

The parent (run_suite.py) builds the environment (OPENAI_BASE_URL = the case's router route, OPENAI_API_KEY=EMPTY,
TMPDIR=<case>/sbx, G4_FAITHFUL_ENV, G4_L4_SCALE, no OPENROUTER_KEY / OPENAI_* / MODEL_PROXY_* / LITELLM_* / LOCAL_*).
This process installs four restorable wrappers around harness module globals, then calls ``run_eval.main(argv)``:

- baseline date  (agent_runner.setup_baseline_commit): after the harness commit, the commit is amended with a committer
  date one day back and the tag file mtime moved back too, so the helpers' t0() falls through to $SWE/t0 (gotcha 7);
- cached extraction (agent_runner.extract_snapshot): for the duration of that one call only, an INSTANCE attribute
  ``docker.extract_archive_to_container`` clones ~/.cache/g4/plain/<tid>/ into the sandbox workspace; it is deleted
  afterwards even on an exception. Never class-level: setup_container_wheels skips /wheels when hasattr() is true
  (container_setup.py:405-408, gotcha 17);
- agent env (agent_runner.install_test_dependencies, a plain function WITHOUT ``_g4`` so run_eval records it as the
  harness original and composes the clock-scale write after it): writes ``_g4_kpar.pth`` (sorts before
  ``_host_env.pth``, gotcha 18) into the sandbox venv so Kaggle-parity versions shadow the host ones;
- verification skip (swegemma.evaluate.verify_task): ``async def _skip(docker, config, task, snapshot_path, **kw)``
  saves the trace and returns a TaskResult so patches/<tid>.patch is still written (gotchas 13, 19).
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(HERE), str(ROOT / "tests"), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

PLAIN_CACHE = Path(os.environ.get("G4_PLAIN_CACHE") or Path.home() / ".cache" / "g4" / "plain")
KPAR_PTH = "_g4_kpar.pth"
HOST_PTH = "_host_env.pth"
BASELINE_SHIFT_S = 86400
STRIP_PREFIXES = ("OPENAI_", "MODEL_PROXY_", "LITELLM_", "LOCAL_")
STRIP_KEYS = ("OPENROUTER_KEY",)


def _warn(msg: str) -> None:
    print(f"[golden-child] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------------------------- 1. baseline date
def baseline_date_cmd(now: float | None = None, shift_s: int = BASELINE_SHIFT_S) -> str:
    past = int(now if now is not None else time.time()) - shift_s
    return ("cd /workspace && GIT_COMMITTER_DATE='%d +0000' git commit --amend --no-edit -q --allow-empty && "
            "git tag -f _swegemma_baseline >/dev/null && python3 -c \"import os;p='.git/refs/tags/_swegemma_baseline';"
            "os.path.exists(p) and os.utime(p,(%d,)*2)\"") % (past, past)


def make_baseline_hook(orig: Callable) -> Callable:
    def setup_baseline_commit(docker, container_id, commit_msg="baseline"):
        orig(docker, container_id, commit_msg)
        res = docker.exec(container_id, baseline_date_cmd())
        if getattr(res, "exit_code", 0) not in (0, None):
            _warn(f"baseline date shift failed: {(getattr(res, 'stderr', '') or '')[-300:]}")
    setup_baseline_commit.__wrapped__ = orig
    return setup_baseline_commit


# ------------------------------------------------------------------------------------------ 2. cached extraction
def _tid_of(tar: Path) -> str:
    n = Path(tar).name
    for suf in (".tar.gz", ".tgz"):
        if n.endswith(suf):
            return n[: -len(suf)]
    return n


def _stamp_of(tar: Path) -> str:
    st = Path(tar).stat()
    return json.dumps({"size": st.st_size, "mtime": int(st.st_mtime), "v": 1}, sort_keys=True)


@contextlib.contextmanager
def _flock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _build_plain(tar: Path, dest: Path, stamp: Path) -> None:
    """A verbatim extraction with the harness's own tar line, swapped in with renames."""
    tmp = dest.parent / f".{dest.name}.building.{os.getpid()}"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        r = subprocess.run(["tar", "--no-same-owner", "-xzf", str(tar), "-C", str(tmp)], capture_output=True, text=True,
                           timeout=300)
        if r.returncode != 0:
            raise RuntimeError(f"tar failed for {tar}: {r.stderr[-300:]}")
        stamp.unlink(missing_ok=True)
        if dest.exists():
            old = dest.parent / f".{dest.name}.old.{os.getpid()}"
            os.replace(dest, old)
            shutil.rmtree(old, ignore_errors=True)
        os.replace(tmp, dest)
        stamp.write_text(_stamp_of(tar))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def clone_contents(src: Path, dst: Path) -> bool:
    """Copy the CONTENTS of src into the existing dst (APFS clone on macOS, reflink on Linux, else plain copy)."""
    dst.mkdir(parents=True, exist_ok=True)
    tries = ([["cp", "-c", "-pR", f"{src}/.", f"{dst}/"]] if platform.system() == "Darwin"
             else [["cp", "-a", "--reflink=auto", f"{src}/.", f"{dst}/"]])
    tries.append(["cp", "-pR", f"{src}/.", f"{dst}/"])
    for argv in tries:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=600)
        if r.returncode == 0:
            return True
        _warn(f"{' '.join(argv[:3])} failed: {r.stderr[-200:]}")
    return False


def cached_extract(tar: Path, ws: Path, cache_root: Path = PLAIN_CACHE) -> bool:
    """Clone the cached plain extraction of `tar` into `ws` (built once per tgz size+mtime, under an flock)."""
    tar = Path(tar)
    tid = _tid_of(tar)
    dest, stamp = cache_root / tid, cache_root / f"{tid}.stamp"
    with _flock(cache_root / f"{tid}.lock"):
        want = _stamp_of(tar)
        if not (stamp.is_file() and stamp.read_text() == want and dest.is_dir()):
            _build_plain(tar, dest, stamp)
        return clone_contents(dest, Path(ws))      # under the lock: a rebuild never swaps the tree mid-copy


def make_extract_hook(orig: Callable, cache_root: Path = PLAIN_CACHE) -> Callable:
    def extract_snapshot(docker, container_id, snapshot_path, *, patch_path=None, base_snapshot_path=None):
        tar = Path(base_snapshot_path if base_snapshot_path is not None else snapshot_path)
        boxes = getattr(docker, "sandboxes", None)
        if not isinstance(boxes, dict) or container_id not in boxes or not tar.is_file():
            return orig(docker, container_id, snapshot_path, patch_path=patch_path,
                        base_snapshot_path=base_snapshot_path)

        def extract_archive_to_container(cid, archive, dest):
            if dest.rstrip("/") != "/workspace" or Path(archive) != tar:
                return False
            try:
                return cached_extract(tar, Path(docker.sandboxes[cid]["workspace"]), cache_root)
            except Exception as e:           # the harness then falls back to its own copy + tar
                _warn(f"cached extraction failed, harness fallback: {type(e).__name__}: {e}")
                return False

        docker.extract_archive_to_container = extract_archive_to_container   # INSTANCE attribute, this call only
        try:
            return orig(docker, container_id, snapshot_path, patch_path=patch_path,
                        base_snapshot_path=base_snapshot_path)
        finally:
            with contextlib.suppress(AttributeError):
                del docker.extract_archive_to_container
    extract_snapshot.__wrapped__ = orig
    return extract_snapshot


# ------------------------------------------------------------------------------------------------ 3. agent env
def kpar_site(repo_key: str, kpar_root: Path | None = None) -> Path | None:
    root = Path(kpar_root or os.environ.get("G4_KPAR") or Path.home() / ".cache" / "g4" / "kpar")
    d = root / repo_key
    if not ((d / ".g4_kpar_ok").is_file() and (d / "bin" / "python").exists()):
        return None
    sps = sorted((d / "lib").glob("python3*/site-packages"))
    return sps[0] if sps else None


def write_kpar_pth(docker, container_id: str, site: str) -> Path | None:
    """_g4_kpar.pth (one line: the kpar site-packages) into every site-packages of the sandbox venv."""
    boxes = getattr(docker, "sandboxes", None)
    written = None
    if isinstance(boxes, dict) and container_id in boxes:
        for sp in Path(boxes[container_id]["venv"]).glob("lib/python*/site-packages"):
            (sp / KPAR_PTH).write_text(str(site) + "\n", encoding="utf-8")
            written = sp / KPAR_PTH
        return written
    res = docker.exec(container_id, "python3 -c \"import sysconfig,sys;open(sysconfig.get_paths()['purelib']+'/"
                      + KPAR_PTH + "','w').write(sys.argv[1]+chr(10))\" " + json.dumps(str(site)))
    if getattr(res, "exit_code", 0) not in (0, None):
        _warn(f"kpar .pth write failed: {getattr(res, 'stderr', '')}")
    return None


def make_kpar_install(base: Callable, site: str) -> Callable:
    """A plain function (no _g4 attribute): run_eval._harness_original records it and composes agent_install."""
    def install_test_dependencies(docker, container_id, repo="", *, fast_path=True, config=None):
        base(docker, container_id, repo, fast_path=fast_path, config=config)
        write_kpar_pth(docker, container_id, site)
    install_test_dependencies.__wrapped__ = base
    return install_test_dependencies


# ----------------------------------------------------------------------------------------- 4. verification skip
def make_verify_skip() -> Callable:
    from swegemma.harness import verification
    from swegemma.models import TaskResult

    async def _skip(docker, config, task, snapshot_path, **kw):
        trace = kw.get("trace")
        json_path = verification.save_trace_artifact(trace, config.results_dir, task.instance_id)
        start = kw.get("start_time") or time.perf_counter()
        return TaskResult(instance_id=task.instance_id, repo=task.repo, resolved=False,
                          agent_patch=kw.get("agent_patch") or "", test_output="", test_exit_code=-2,
                          duration_seconds=time.perf_counter() - start, error=kw.get("agent_error"), trace=trace,
                          trace_json_path=json_path)
    _skip._g4_golden = True
    return _skip


# --------------------------------------------------------------------------------------------------- install
def install_hooks(*, extract_cache: bool = True, cache_root: Path = PLAIN_CACHE, kpar: str | None = None,
                  verify_skip: bool = True, baseline: bool = True) -> Callable[[], None]:
    """Install the hooks; returns restore() which puts every wrapped module global back."""
    import swegemma.evaluate as ev
    import swegemma.harness.agent_runner as ar
    saved: list = []

    def put(mod, name, value):
        saved.append((mod, name, getattr(mod, name)))
        setattr(mod, name, value)

    if baseline:
        put(ar, "setup_baseline_commit", make_baseline_hook(ar.setup_baseline_commit))
    if extract_cache:
        put(ar, "extract_snapshot", make_extract_hook(ar.extract_snapshot, cache_root))
    if kpar:
        put(ar, "install_test_dependencies", make_kpar_install(ar.install_test_dependencies, kpar))
    if verify_skip:
        put(ev, "verify_task", make_verify_skip())

    def restore():
        for mod, name, val in reversed(saved):
            setattr(mod, name, val)
        saved.clear()
    return restore


def scrub_env(env: dict | None = None) -> dict:
    """The environment without the router's secrets and the harness's model-endpoint overrides."""
    env = dict(os.environ if env is None else env)
    for k in list(env):
        if k in STRIP_KEYS or k.startswith(STRIP_PREFIXES):
            env.pop(k)
    return env


def main(argv: list | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--" in argv:
        i = argv.index("--")
        own, rest = argv[:i], argv[i + 1:]
    else:
        own, rest = argv, []
    ap = argparse.ArgumentParser(prog="stage_child.py")
    ap.add_argument("--no-extract-cache", action="store_true")
    ap.add_argument("--plain-cache", default=str(PLAIN_CACHE))
    ap.add_argument("--agent-env", choices=("kpar", "host"), default="host")
    ap.add_argument("--kpar-site", default=None)
    ap.add_argument("--harness-verify", action="store_true")
    ap.add_argument("--faithful-env", action="store_true")
    a = ap.parse_args(own)
    if a.agent_env == "kpar" and a.faithful_env:
        _warn("--agent-env kpar together with --faithful-env is refused (the pod's faithful_install owns the env)")
        return 2
    if a.agent_env == "kpar" and not a.kpar_site:
        _warn("--agent-env kpar needs --kpar-site")
        return 2
    for k in [k for k in os.environ if k in STRIP_KEYS]:
        os.environ.pop(k)            # defence in depth: the parent never passes it
    install_hooks(extract_cache=not a.no_extract_cache, cache_root=Path(a.plain_cache),
                  kpar=a.kpar_site if a.agent_env == "kpar" else None, verify_skip=not a.harness_verify)
    import run_eval
    rc = run_eval.main(rest)
    return int(rc or 0)


if __name__ == "__main__":
    sys.exit(main())
