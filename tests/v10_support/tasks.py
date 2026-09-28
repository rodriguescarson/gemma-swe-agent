"""Per-task offline test support for v10 (docs/v10/SPEC.md section 8). Test-harness code, not bundle code.

Nothing here touches a GPU, the network, Kaggle or a pod. Repo tests run in the Kaggle-parity uv venvs that
scripts/build_kpar.sh builds OUTSIDE the repo (~/.cache/g4/kpar/<repo>, override G4_KPAR). Extracted task workspaces
are cached in ~/.cache/g4/ws/<tid>/ (override G4_CACHE); every test works on an APFS clone of that cache, never on it.

Pinned API (SPEC 8): TASK_IDS, load_task, parse_patch, has_snapshot, fetch_cmd, kpar_python, base_ws, fresh_ws,
sandbox_env, install_helpers, run_helper, mini_verify, hidden_claims_repro, results.

Environment knobs: G4_J (worker threads, default 4), G4_NIGHTLY=1 (nightly tier), G4_TASKS (a subset of task ids;
aggregate bars then skip), G4_BUNDLE (bundle root, default submissions/v10), G4_KPAR, G4_CACHE, G4_OFFLINE_OUT
(default eval/offline). The cache holds about 90 MB per task (base; base_tp is an APFS clone of it) and is safe to
delete: rm -rf ~/.cache/g4/ws ~/.cache/g4/work.
"""
from __future__ import annotations

import ast
import concurrent.futures as cf
import contextlib
import dataclasses
import fcntl
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
SNAP_DIR = DATA / "raw" / "snapshots"
TASKS_JSONL = DATA / "tasks.jsonl"
FREEZE = ROOT / "eval" / "kaggle" / "rescore_fair" / "pip_freeze.txt"
BUNDLE = Path(os.environ.get("G4_BUNDLE") or ROOT / "submissions" / "v10")
SCRIPTS = BUNDLE / "skills" / "swe-tools" / "scripts"
KPAR = Path(os.environ.get("G4_KPAR") or Path.home() / ".cache" / "g4" / "kpar")
CACHE = Path(os.environ.get("G4_CACHE") or Path.home() / ".cache" / "g4" / "ws")
WORK = CACHE.parent / "work"            # same APFS volume as CACHE, so fresh_ws can clone
OFFLINE_OUT = Path(os.environ.get("G4_OFFLINE_OUT") or ROOT / "eval" / "offline")
J = max(1, int(os.environ.get("G4_J", "4") or 4))
NIGHTLY = os.environ.get("G4_NIGHTLY") == "1"
BUILD_KPAR = ROOT / "scripts" / "build_kpar.sh"

TASK_IDS: list[str] = (DATA / "kaggle_valid_ids.txt").read_text().split()
REPO_KPAR = {"Textualize/rich": "rich", "psf/requests": "requests", "fastapi/fastapi": "fastapi"}
# The six packages R107 pins for the rich venv (SPEC R107); the fastapi list is test_plan section 2.
KPAR_PINS = {
    "rich": ("pytest", "Pygments", "markdown-it-py", "mdurl", "typing_extensions", "attrs"),
    "requests": ("pytest", "Pygments", "markdown-it-py", "mdurl", "typing_extensions", "attrs"),
    "fastapi": ("pytest", "pydantic", "pydantic_core", "starlette", "anyio", "httpx", "python-multipart",
                "email-validator", "PyYAML", "SQLAlchemy", "orjson", "ujson", "Flask", "Jinja2", "typing-inspection",
                "PyJWT", "typing_extensions", "annotated-types", "Pygments"),
}
KPAR_FORBIDDEN = ("dirty-equals", "inline-snapshot")     # Kaggle has neither (test_plan section 2)

# Known, documented exceptions (SPEC R98, R102, R104, R105; test_plan appendix A).
KNOWN_LOCATE_MISS = frozenset({"rich_3953", "rich_3944", "rich_3468", "rich_3105", "rich_3067", "rich_3063"})
KNOWN_BEHAVIOUR_CHANGE = frozenset({"rich_3942", "rich_3935", "rich_3470", "rich_3105", "rich_3043", "rich_3061"})
KNOWN_EMPTY_HANG = frozenset({"rich_4006", "rich_3772", "rich_3480"})
KNOWN_FREE = frozenset({"requests_6644"})       # the empty patch resolves in parity: tests import site-packages (F10)
KNOWN_GOLD_LOST = frozenset({"requests_6644"})  # gold resolves only with requests installed in site-packages (F10);
#                                                 the requests venv has it (measured: resolves), a bare one would not
# test_plan section 3 / appendix A: gold patches that add files, and how many.
EXPECTED_NEW_FILES = {"fastapi_15661": 1, "fastapi_15280": 1, "rich_3930": 23, "fastapi_15800": 6}

HARNESS_PROTECTED_NAMES = ("conftest.py", "pytest.ini", "sitecustomize.py", "usercustomize.py", "_swegemma_stubs.py")
FETCH_PREFIX = "source /Users/carson/Projects/kaggriculture/.venv/bin/activate && python scripts/fetch_data.py"
SETUP_VERSION = "v10-tasks-1"      # bump to invalidate every cached base workspace
SANDBOX_PATH_TAIL = "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin"
HERMETIC_GIT = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
                "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "a@b", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "a@b"}


# ----------------------------------------------------------------------------------------------------------- tasks
_TASKS: dict | None = None
_TASKS_LOCK = threading.Lock()


def _tasks() -> dict:
    global _TASKS
    with _TASKS_LOCK:
        if _TASKS is None:
            rows = {}
            with open(TASKS_JSONL, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        r = json.loads(line)
                        rows[r["instance_id"]] = r
            _TASKS = rows
        return _TASKS


def load_task(tid: str) -> dict:
    """The tasks.jsonl row (instance_id, repo, base_commit, patch, test_patch, problem_statement, hints_text, ...)."""
    return _tasks()[tid]


def repo_key(tid_or_repo: str) -> str:
    """'rich' | 'requests' | 'fastapi' for a task id, a 'owner/name' repo, or a key."""
    if tid_or_repo in REPO_KPAR.values():
        return tid_or_repo
    if tid_or_repo in REPO_KPAR:
        return REPO_KPAR[tid_or_repo]
    return REPO_KPAR[load_task(tid_or_repo)["repo"]]


# ------------------------------------------------------------------------------------------------------- patches
_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclasses.dataclass
class Hunk:
    old_start: int
    old_len: int
    new_start: int
    new_len: int
    lines: list = dataclasses.field(default_factory=list)   # raw body lines, prefix and line ending kept
    header: str = ""                                          # the raw "@@ ... @@ ..." line

    def _side(self, keep: str) -> list:
        out: list = []
        prev_in = False
        for raw in self.lines:
            if raw.startswith("\\"):                     # "\ No newline at end of file": the previous line has none
                if prev_in and out and out[-1].endswith("\n"):
                    out[-1] = out[-1][:-1]
                continue
            kind, text = _body_kind(raw)
            prev_in = kind == " " or kind in keep
            if prev_in:                                   # a patch stored without its final "\n" (tasks.jsonl)
                out.append(text if text.endswith("\n") else text + "\n")
        return out

    @property
    def old_lines(self) -> list:
        """Old-side content lines (context and removed), line endings kept."""
        return self._side("-")

    @property
    def new_lines(self) -> list:
        """New-side content lines (context and added), line endings kept."""
        return self._side("+")

    @property
    def counts_ok(self) -> bool:
        return len(self.old_lines) == self.old_len and len(self.new_lines) == self.new_len


@dataclasses.dataclass
class FilePatch:
    path: str
    new_file: bool
    hunks: list = dataclasses.field(default_factory=list)
    old_path: str = ""
    deleted: bool = False
    header: list = dataclasses.field(default_factory=list)   # raw lines up to and including "+++ "
    trailer: list = dataclasses.field(default_factory=list)  # raw lines after the last hunk of the last file


def _body_kind(raw: str) -> tuple:
    if raw in ("\n", "\r\n"):                    # a blank context line whose leading space was stripped
        return " ", raw
    return raw[0], raw[1:]


def split_lines(text: str) -> list:
    """Split on "\\n" only, keeping it (str.splitlines would also split on \\f, \\x1c, U+2028 ...)."""
    parts = text.split("\n")
    out = [p + "\n" for p in parts[:-1]]
    if parts[-1]:
        out.append(parts[-1])
    return out


def _hdr_path(raw: str) -> str:
    s = raw[4:].rstrip("\r\n").split("\t", 1)[0].strip()
    if len(s) >= 2 and s[0] == s[-1] == '"':             # git C-quoting: octal escapes of UTF-8 bytes
        try:
            s = s[1:-1].encode("latin-1", "backslashreplace").decode("unicode_escape").encode("latin-1").decode("utf-8")
        except (UnicodeError, ValueError):
            s = s[1:-1]
    if s != "/dev/null" and s[:2] in ("a/", "b/"):
        s = s[2:]
    return s


def parse_patch(text: str) -> list:
    """Unified diff -> [FilePatch(path, new_file, hunks=[Hunk(old_start, old_len, new_start, new_len, lines)])].

    Port of scratchpad/tpv10/measure2.py:parse_patch, made lossless (render_patch(parse_patch(t)) == t): hunk bodies are
    consumed by their header counts, so a removed line like "-- x" is never taken for a file header; "\\ No newline"
    markers and blank context lines are kept. new_file: "--- /dev/null", "new file mode", or every hunk is @@ -0,0."""
    lines = split_lines(text)
    files: list = []
    pending: list = []
    cur: FilePatch | None = None
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
            old, new = _hdr_path(ln), _hdr_path(lines[i + 1])
            header = pending + [ln, lines[i + 1]]
            pending = []
            deleted = new == "/dev/null"
            cur = FilePatch(path=old if deleted else new, new_file=False, old_path=old, deleted=deleted, header=header)
            cur.new_file = old == "/dev/null" or any(h.startswith("new file mode") for h in header)
            files.append(cur)
            i += 2
            continue
        m = _HUNK_RE.match(ln)
        if m and cur is not None and not pending:
            h = Hunk(int(m.group(1)), int(m.group(2)) if m.group(2) is not None else 1,
                     int(m.group(3)), int(m.group(4)) if m.group(4) is not None else 1, [], ln)
            ro, rn = h.old_len, h.new_len
            i += 1
            while i < len(lines) and (ro > 0 or rn > 0):
                x = lines[i]
                if x.startswith("\\"):
                    h.lines.append(x)
                    i += 1
                    continue
                kind = _body_kind(x)[0]
                if kind == " ":
                    ro -= 1
                    rn -= 1
                elif kind == "-":
                    ro -= 1
                elif kind == "+":
                    rn -= 1
                else:
                    break
                h.lines.append(x)
                i += 1
            while i < len(lines) and lines[i].startswith("\\"):
                h.lines.append(lines[i])
                i += 1
            cur.hunks.append(h)
            continue
        pending.append(ln)
        i += 1
    if files:
        files[-1].trailer = pending
        for fp in files:
            if not fp.new_file and fp.hunks and all(h.old_start == 0 and h.old_len == 0 for h in fp.hunks):
                fp.new_file = True
    elif pending:
        files.append(FilePatch(path="", new_file=False, header=pending))
    return files


def render_patch(files: list) -> str:
    """Inverse of parse_patch (lossless)."""
    out: list = []
    for fp in files:
        out += fp.header
        for h in fp.hunks:
            out.append(h.header)
            out += h.lines
        out += fp.trailer
    return "".join(out)


def patch_files(text: str) -> list:
    return [fp.path for fp in parse_patch(text) if fp.path]


# --------------------------------------------------------------------------------------- snapshots and venvs
def has_snapshot(tid: str) -> bool:
    return (SNAP_DIR / f"{tid}.tgz").is_file()


def fetch_cmd(tid: str) -> str:
    """The exact, free (network, Carson's go) command that downloads a missing snapshot."""
    return f"cd {ROOT} && {FETCH_PREFIX} snapshots/{tid}.tgz"


def require_snapshot(tid: str) -> None:
    if not has_snapshot(tid):
        pytest.skip(f"snapshot missing (not fetched; Carson's go): {fetch_cmd(tid)}")


def kpar_dir(repo: str) -> Path:
    return KPAR / repo_key(repo)


def kpar_ok(repo: str) -> bool:
    d = kpar_dir(repo)
    return (d / ".g4_kpar_ok").is_file() and (d / "bin" / "python").exists()


def build_cmd(repo: str) -> str:
    key = repo_key(repo)
    return f"{BUILD_KPAR} {key}" + ("   (needs the network once: Carson's call)" if key == "fastapi" else "")


def kpar_python(repo: str) -> str:
    """The parity venv's python for a task id / repo; skips with the build command when the venv is absent."""
    if not kpar_ok(repo):
        pytest.skip(f"parity venv missing: {build_cmd(repo)}")
    return str(kpar_dir(repo) / "bin" / "python")


def kpar_versions(repo: str) -> dict:
    """{canonical name: version} from the venv's *.dist-info dirs (no subprocess)."""
    out = {}
    for sp in (kpar_dir(repo) / "lib").glob("python3*/site-packages"):
        for d in sp.glob("*.dist-info"):
            name, _, ver = d.name[:-len(".dist-info")].rpartition("-")
            out[canon(name)] = ver
    return out


def freeze_versions(path: Path = FREEZE) -> dict:
    out = {}
    for line in path.read_text(errors="replace").splitlines():
        if "==" in line and not line.startswith("#"):
            name, _, ver = line.partition("==")
            out[canon(name)] = ver.strip()
    return out


def canon(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


# ------------------------------------------------------------------------------------------------- processes
def run(cmd, cwd=None, env=None, timeout: float = 60, stdin: str | None = None) -> SimpleNamespace:
    """Run argv (list) or a bash command (str) in its own session; the deadline and normal exit both kill the group.
    Returns rc (None on timeout), out, err, secs, timed_out."""
    argv = ["bash", "-c", cmd] if isinstance(cmd, str) else [str(c) for c in cmd]
    t0 = time.monotonic()
    p = subprocess.Popen(argv, cwd=str(cwd) if cwd else None, env=env, start_new_session=True,
                         stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    timed_out = False
    try:
        out, err = p.communicate(input=stdin.encode("utf-8", "surrogateescape") if stdin is not None else None,
                                 timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _killpg(p.pid)
        try:
            out, err = p.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            out, err = b"", b""
    finally:
        _killpg(p.pid)
    return SimpleNamespace(rc=None if timed_out else p.returncode, out=out.decode("utf-8", "replace"),
                           err=err.decode("utf-8", "replace"), secs=time.monotonic() - t0, timed_out=timed_out)


def _killpg(pgid: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        os.killpg(pgid, signal.SIGKILL)


def git(ws, *args, timeout: float = 60, env=None, stdin=None) -> SimpleNamespace:
    e = dict(env or os.environ)
    e.update(HERMETIC_GIT)
    return run(["git", "-c", "core.quotepath=off", *args], cwd=ws, env=e, timeout=timeout, stdin=stdin)


class LocalSandbox:
    """Duck-typed stand-in for the harness sandbox manager: exec(cid, cmd) runs cmd with bash, mapping the literal
    /workspace path to a local directory, so swegemma.harness functions run unmodified on a local tree."""
    _WS = re.compile(r"(?<![\w./-])/workspace(?![\w.-])")

    def __init__(self, ws, env=None, timeout: float = 120):
        self.ws = str(ws)
        env = dict(env or os.environ)
        env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env.get("PATH", SANDBOX_PATH_TAIL)
        env.update(HERMETIC_GIT)
        self.env = env
        self.timeout = timeout

    def exec(self, container_id, cmd, timeout=None, **_kw):
        cmd = self._WS.sub(lambda _m: shlex.quote(self.ws), cmd)
        r = run(cmd, cwd=self.ws, env=self.env, timeout=timeout or self.timeout)
        return SimpleNamespace(exit_code=-1 if r.rc is None else r.rc, stdout=r.out, stderr=r.err)


def _harness():
    """Lazy import: swegemma pulls in litellm (about 3 s), which only the verify/setup paths need."""
    from swegemma.harness import container_setup as cs, verification as vf
    from swegemma.models.task import extract_test_files_from_patch
    return SimpleNamespace(cs=cs, vf=vf, extract=extract_test_files_from_patch)


def harness_apply(ws, patch_text: str, env=None, scratch=None) -> tuple:
    """The harness apply pipeline (apply_patch_in_container: git apply variants, symlink normalisation, -p0, patch)."""
    h = _harness()
    scratch = Path(scratch or f"{ws}_tmp")
    scratch.mkdir(parents=True, exist_ok=True)
    pf = scratch / f"p_{hashlib.sha1(patch_text.encode('utf-8', 'surrogateescape')).hexdigest()[:10]}.patch"
    pf.write_text(patch_text if patch_text.endswith("\n") else patch_text + "\n", encoding="utf-8",
                  errors="surrogateescape")
    try:
        rc, out, err = h.cs.apply_patch_in_container(LocalSandbox(ws, env), "local", str(pf), workspace_dir=str(ws))
    finally:
        with contextlib.suppress(OSError):
            pf.unlink()
    return rc, (err or out)[-600:]


def git_apply(ws, patch_text: str, env=None) -> tuple:
    """Plain git apply with measure2's fallbacks (--recount, --ignore-whitespace). (ok, error tail)."""
    text = patch_text if patch_text.endswith("\n") else patch_text + "\n"
    last = ""
    for extra in ((), ("--recount",), ("--ignore-whitespace",)):
        r = git(ws, "apply", *extra, "-", env=env, stdin=text)
        if r.rc == 0:
            return True, ""
        last = (r.err or r.out)[-300:]
    return False, last


# --------------------------------------------------------------------------------------------- workspaces
_TID_LOCKS: dict = {}
_TID_LOCKS_GUARD = threading.Lock()
_BASE_MEMO: dict = {}


@contextlib.contextmanager
def _locked(path: Path):
    """Thread lock plus an flock, so parallel threads and parallel pytest processes build a base only once."""
    with _TID_LOCKS_GUARD:
        tl = _TID_LOCKS.setdefault(str(path), threading.Lock())
    with tl:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a+") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _base_key(tid: str, with_test_patch: bool) -> str:
    st = (SNAP_DIR / f"{tid}.tgz").stat()
    t = load_task(tid)
    key = {"v": SETUP_VERSION + ("-tp-clone" if with_test_patch else ""), "size": st.st_size,
           "mtime": int(st.st_mtime), "tp": with_test_patch,
           "tp_sha": hashlib.sha1(t["test_patch"].encode()).hexdigest() if with_test_patch else ""}
    return json.dumps(key, sort_keys=True)


def base_ws(tid: str, with_test_patch: bool = False) -> Path:
    """The harness-exact base workspace of a task, cached in $G4_CACHE/<tid>/base (base_tp with the test_patch):
    1. extract the snapshot; 2. append the harness exclude lines (container_setup.setup_git_exclude);
    3. write pytest.ini and the conftest hook (container_setup.setup_workspace_test_config, run unmodified through
    LocalSandbox); 4. git add -A, a baseline commit and the _swegemma_baseline tag. The with_test_patch variant
    (base_tp) is an APFS clone of base plus the harness apply of the test_patch, step 3 again and a second commit that
    the tag moves to (R103). Never modify the returned tree: use fresh_ws()."""
    require_snapshot(tid)
    memo = (tid, with_test_patch)
    if memo in _BASE_MEMO and (_BASE_MEMO[memo] / ".git").is_dir():
        return _BASE_MEMO[memo]
    plain = base_ws(tid) if with_test_patch else None     # base_tp is an APFS clone of base: no second extraction
    tdir = CACHE / tid
    dest = tdir / ("base_tp" if with_test_patch else "base")
    stamp = tdir / (dest.name + ".ok")
    want = _base_key(tid, with_test_patch)
    with _locked(tdir / ".lock"):
        if not (stamp.is_file() and stamp.read_text() == want and (dest / ".git").is_dir()):
            _build_base(tid, dest, stamp, want, plain)
    _BASE_MEMO[memo] = dest
    return dest


def _build_base(tid: str, dest: Path, stamp: Path, want: str, plain: Path | None) -> None:
    """Build into a temp dir, then swap it in with two renames (a concurrent reader never sees a half-built tree)."""
    h = _harness()
    task = load_task(tid)
    tmp = dest.parent / f".{dest.name}.building.{os.getpid()}.{threading.get_ident()}"
    shutil.rmtree(tmp, ignore_errors=True)
    old = None
    try:
        if plain is None:
            tmp.mkdir(parents=True)
            # --no-same-owner: as root (the Linux gate) tar keeps the archive's uid and git then refuses the tree
            # ("dubious ownership"; GIT_CONFIG_GLOBAL=/dev/null rules out safe.directory)
            r = run(["tar", "--no-same-owner", "-xzf", str(SNAP_DIR / f"{tid}.tgz"), "-C", str(tmp)], timeout=120)
            if r.rc != 0:
                raise RuntimeError(f"extract {tid}: {r.err[-300:]}")
            sb = LocalSandbox(tmp)
            h.cs.setup_git_exclude(sb, "local")
            h.cs.setup_workspace_test_config(sb, "local", task["repo"], workspace_dir=str(tmp))
            msg = "baseline"
        else:                                             # the harness-exact base plus the test_patch, committed
            r = run(["cp", "-c", "-R", str(plain), str(tmp)], timeout=120)
            if r.rc != 0:
                shutil.rmtree(tmp, ignore_errors=True)
                r = run(["cp", "-R", str(plain), str(tmp)], timeout=300)
                if r.rc != 0:
                    raise RuntimeError(f"copy {plain}: {r.err[-300:]}")
            sb = LocalSandbox(tmp)
            scratch = tmp.parent / (tmp.name + "_scratch")
            try:
                rc, err = harness_apply(tmp, task["test_patch"], scratch=scratch)
            finally:
                shutil.rmtree(scratch, ignore_errors=True)
            if rc != 0:
                raise RuntimeError(f"test_patch does not apply to {tid}: {err}")
            h.cs.setup_workspace_test_config(sb, "local", task["repo"], workspace_dir=str(tmp))
            msg = "baseline with the hidden tests"
        r = run(f"git add -A && git -c user.email=a@b -c user.name=t commit -qm {shlex.quote(msg)} --allow-empty "
                "&& git tag -f _swegemma_baseline >/dev/null", cwd=tmp, env=sb.env, timeout=120)
        if r.rc != 0:
            raise RuntimeError(f"baseline commit {tid}: {r.err[-300:]}")
        stamp.unlink(missing_ok=True)
        if dest.exists():
            old = dest.parent / f".{dest.name}.old.{os.getpid()}.{threading.get_ident()}"
            os.replace(dest, old)
        os.replace(tmp, dest)
        stamp.write_text(want)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        if old is not None:
            shutil.rmtree(old, ignore_errors=True)


def fresh_ws(tid_or_base, tmp) -> Path:
    """A private copy of a base workspace at <tmp>/ws (APFS clone with cp -c, else cp -R), plus the empty <ws>_tmp."""
    base = tid_or_base if isinstance(tid_or_base, Path) else base_ws(str(tid_or_base))
    tmp = Path(tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    ws = tmp / "ws"
    if ws.exists():
        shutil.rmtree(ws)
    for attempt in range(2):                              # a base swapped in by another session mid-copy: retry once
        r = run(["cp", "-c", "-R", str(base), str(ws)], timeout=120)
        if r.rc != 0:
            shutil.rmtree(ws, ignore_errors=True)
            r = run(["cp", "-R", str(base), str(ws)], timeout=300)
        if r.rc == 0:
            break
        shutil.rmtree(ws, ignore_errors=True)
        if attempt:
            raise RuntimeError(f"copy {base}: {r.err[-300:]}")
        time.sleep(1)
    (tmp / "ws_tmp").mkdir(exist_ok=True)
    # The clone has new inodes/ctimes, so git would re-hash every file on its first status. In the harness the index
    # is fresh (git add -A plus commit just ran), so refresh it here: helper timings then match the sandbox.
    git(ws, "update-index", "-q", "--refresh", timeout=120)
    return ws


@contextlib.contextmanager
def work_dir(tag: str = "job"):
    """A scratch dir on the cache volume, removed afterwards."""
    WORK.mkdir(parents=True, exist_ok=True)
    d = Path(tempfile.mkdtemp(prefix=f"{tag}_", dir=WORK))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def sandbox_env(ws, repo: str, fake_clock: str | None = "20") -> dict:
    """The subprocess-sandbox environment (build_sanitized_env plus subprocess.py:483-501), pointed at <ws>_tmp.
    SWE_DUAL=0 and SWE_DOCKER_TMP_FOR_TESTS keep the helpers away from the host /tmp. SWE_FAKE_CLOCK (default 20 s)
    makes footers and budgets independent of the cached baseline's age; pass None for the real clock."""
    ws = Path(ws)
    tmp = Path(f"{ws}_tmp")
    tmp.mkdir(parents=True, exist_ok=True)
    kbin = kpar_dir(repo) / "bin"
    env = {"PATH": f"{kbin}:{SANDBOX_PATH_TAIL}", "HOME": str(tmp), "TMPDIR": str(tmp), "TEST_TMPDIR": str(tmp),
           "SWE_DIR": str(tmp / "swe"), "PYTHONPATH": str(ws), "PYTHONNOUSERSITE": "1",
           "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "SWE_DUAL": "0",
           "SWE_DOCKER_TMP_FOR_TESTS": str(tmp / "dockertmp"), "VIRTUAL_ENV": str(kbin.parent), "PWD": str(ws)}
    # Never NO_COLOR here: rich honours it and 7 hidden tests of rich_3105/rich_3043 then fail on gold (measured).
    if fake_clock is not None:
        env["SWE_FAKE_CLOCK"] = str(fake_clock)
    return env


# ------------------------------------------------------------------------------------------------- helpers
def bundle_has(*names: str) -> bool:
    return all((SCRIPTS / f"{n}.py").is_file() for n in names)


def require_helpers(*names: str) -> None:
    missing = [n for n in names if not (SCRIPTS / f"{n}.py").is_file()]
    if missing:
        pytest.skip(f"helper(s) not built yet: {', '.join(missing)} in {SCRIPTS}")


def install_helpers(env: dict) -> SimpleNamespace:
    """Run the bundle's install.py from a temp copy (like the skill wrapper: cwd = the copy's parent,
    argv[0] = scripts/install.py). Never runs anything inside submissions/."""
    swe = Path(env["SWE_DIR"])
    skill = Path(tempfile.mkdtemp(prefix="skill_", dir=env["TMPDIR"]))
    try:
        shutil.copytree(SCRIPTS, skill / "scripts", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        r = run(["python3", "scripts/install.py"], cwd=skill, env=env, timeout=30)
    finally:
        shutil.rmtree(skill, ignore_errors=True)
    r.installed = (swe / "VERSION").is_file()
    return r


def run_helper(name: str, args=(), ws=None, env=None, stdin: str | None = None, timeout: float = 90) -> SimpleNamespace:
    """python3 $SWE_DIR/<name>.py ARGS in ws (the installed copy, as the prompts call it); installs first if needed."""
    swe = Path(env["SWE_DIR"])
    if not (swe / "VERSION").is_file() or not (swe / f"{name}.py").is_file():
        install_helpers(env)
    return run(["python3", str(swe / f"{name}.py"), *[str(a) for a in args]], cwd=ws, env=env, timeout=timeout,
               stdin=stdin)


def first_line(text: str) -> str:
    return next((ln for ln in text.splitlines() if ln.strip()), "")


# ------------------------------------------------------------------------------------------ mini verifier
def _existing_test_files(ws, test_patch: str) -> list:
    return [fp.path for fp in parse_patch(test_patch) if fp.path and not fp.new_file and (Path(ws) / fp.path).is_file()]


def tamper_line(test_patch: str, path: str) -> int | None:
    """1-based old-side line inside the first hunk of `path` that `patch --fuzz 2` (the harness's last apply fallback)
    cannot skip: the first removed line when the first change is a removal, else the context line right before the
    first change, else the first context line after it. None when the hunk has no old-side line to edit."""
    fp = next((f for f in parse_patch(test_patch) if f.path == path), None)
    if fp is None or not fp.hunks:
        return None
    body = [r for r in fp.hunks[0].lines if not r.startswith("\\")]
    n, before = fp.hunks[0].old_start, None
    for raw in body:
        kind = _body_kind(raw)[0]
        if kind == "-":
            return n
        if kind == "+":
            if before is not None:
                return before
            break
        before, n = n, n + 1
    seen = False
    for raw in body:
        kind = _body_kind(raw)[0]
        if kind == "+":
            seen = True
        elif seen:
            return n
    return None


def tamper_test_hunk(ws, test_patch: str) -> str | None:
    """What an agent 'fixing the test' does: a raw edit inside the first test_patch hunk of the first existing test
    file. Returns the edited path, or None when the test_patch only adds new files."""
    for rel in _existing_test_files(ws, test_patch):
        ln = tamper_line(test_patch, rel)
        if ln is None:
            continue
        p = Path(ws) / rel
        data = p.read_bytes().split(b"\n")
        k = min(max(ln - 1, 0), len(data) - 1)
        line = data[k]
        cr = b"\r" if line.endswith(b"\r") else b""
        body = line[:-1] if cr else line
        cand = body + b"  # agent edit" + cr
        trial = data[:k] + [cand] + data[k + 1:]
        try:
            compile(b"\n".join(trial), rel, "exec", dont_inherit=True)
        except (SyntaxError, ValueError):
            indent = re.match(rb"[ \t]*", body).group(0)
            trial = data[:k] + [indent + b"# agent edit" + cr] + data[k:]
        p.write_bytes(b"\n".join(trial))
        return rel
    return None


def mini_verify(ws, patch: str, test_patch: str, *, tamper=None, timeout: float = 20, repo: str | None = None,
                info: dict | None = None) -> tuple:
    """Port of swegemma verification.verify_task (verification.py:305-505) on a fresh clone of the base `ws`: the
    harness apply pipeline for the agent patch, the harness-exact reset list (incl. sitecustomize.py, so F1 is
    reproduced), the test_patch, pytest.ini/conftest rewritten, the grader pytest line, _validate_junit_xml and the
    stdout checks. tamper: None | "test_hunk" | callable(clone), applied after the agent patch and before the reset.
    info (optional dict) receives tamper_file, reset_ok (the reset really restored it) and tp_git_apply_ok (plain
    git apply --check of the test_patch after the reset). Returns (resolved, why, secs); why is None when resolved."""
    info = {} if info is None else info
    t0 = time.monotonic()
    h = _harness()
    base = Path(ws)
    if repo is None:
        tid = base.parent.name
        repo = tid if tid in _tasks() else "rich"
    full_repo = load_task(repo)["repo"] if repo in _tasks() else repo
    with work_dir("mv") as wd:
        clone = fresh_ws(base, wd)
        env = sandbox_env(clone, repo, fake_clock=None)
        sb = LocalSandbox(clone, env)
        scratch = Path(f"{clone}_tmp")
        if patch.strip():
            rc, err = harness_apply(clone, patch, env, scratch)
            if rc != 0:
                return False, f"agent patch did not apply: {err}", time.monotonic() - t0
        if tamper == "test_hunk":
            info["tamper_file"] = tamper_test_hunk(clone, test_patch)
        elif callable(tamper):
            info["tamper_file"] = tamper(clone)
        targets = h.extract(test_patch)
        touched = list(h.extract(patch))
        if patch.strip():
            for raw in patch.splitlines():
                if raw.startswith("diff --git "):
                    m = re.match(r'^diff --git "?a/(.*?)"? "?b/(.*?)"?$', raw)
                    if m:
                        for g in (m.group(1), m.group(2)):
                            if g and g not in touched:
                                touched.append(g)
                elif raw.startswith(("--- a/", "+++ b/")):
                    rel = raw[6:].strip().strip('"')
                    if rel and rel != "/dev/null" and rel not in touched:
                        touched.append(rel)
                elif raw.startswith("rename from "):
                    rel = raw[len("rename from "):].strip().strip('"')
                    if rel and rel not in touched:
                        touched.append(rel)
            st = sb.exec("local", "cd /workspace && (git diff --name-only HEAD 2>/dev/null; "
                                  "git ls-files --others --exclude-standard 2>/dev/null) || true")
            for ln in (st.stdout or "").splitlines():
                if ln.strip() and ln.strip() not in touched:
                    touched.append(ln.strip())
        protected = [p for p in touched if h.vf._is_protected_test_or_config_path(p)]
        reset = list(dict.fromkeys(targets + protected + list(HARNESS_PROTECTED_NAMES)))
        q = " ".join(shlex.quote(p) for p in reset)
        sb.exec("local", f"cd /workspace && git checkout HEAD -- {q} 2>/dev/null || true")
        sb.exec("local", f"cd /workspace && git clean -f -- {q} 2>/dev/null || true")
        if info.get("tamper_file"):
            info["reset_ok"] = git(clone, "diff", "--quiet", "HEAD", "--", info["tamper_file"], env=env).rc == 0
        if test_patch.strip():
            tp = test_patch if test_patch.endswith("\n") else test_patch + "\n"
            info["tp_git_apply_ok"] = git(clone, "apply", "--check", "-", env=env, stdin=tp).rc == 0
            rc, err = harness_apply(clone, test_patch, env, scratch)
            if rc != 0:
                return False, f"test_patch did not apply: {err}", time.monotonic() - t0
        h.cs.setup_workspace_test_config(sb, "local", full_repo, workspace_dir=str(clone), overwrite=True)
        py_targets = [p for p in targets if Path(p).name != "conftest.py" and p.endswith(".py")] or targets
        tfs = " ".join(shlex.quote(p) for p in py_targets) if py_targets else "."
        junit = scratch / "_swegemma_junit.xml"
        cmd = (f"cd {shlex.quote(str(clone))} && PYTHONSAFEPATH=1 PYTHONNOUSERSITE=1 python3 -s -m pytest {tfs} "
               f"--junitxml={shlex.quote(str(junit))} -p no:anyio -o timeout=0 -o python_classes=\"Test* *Test\" -q")
        r = run(cmd, cwd=clone, env=env, timeout=timeout)
        if r.timed_out:
            return False, f"timeout after {timeout:g}s (hang)", time.monotonic() - t0
        resolved = r.rc == 0
        why = None if resolved else f"pytest exit {r.rc}: {_summary(r.out)}"
        if resolved:
            xml = junit.read_text(errors="replace") if junit.is_file() else ""
            so = (r.out or "").lower()
            bad_stdout = (bool(re.search(r"\b0 passed\b", so)) or "no tests ran" in so or "collected 0 items" in so
                          or (so.strip() != "" and "passed" not in so))
            if xml.strip():
                ok, reason = h.vf._validate_junit_xml(xml, test_patch=test_patch)
                if not ok:
                    resolved, why = False, reason
                elif bad_stdout:
                    resolved, why = False, "Pytest stdout summary indicates zero or no passing tests"
            else:
                resolved, why = False, "Missing JUnit XML report (possible premature os._exit(0))"
        return resolved, why, time.monotonic() - t0


def extract_targets(test_patch: str) -> list:
    """The grader's pytest targets: test_patch files minus conftest.py, .py only (verification.py:481-486)."""
    files = _harness().extract(test_patch)
    return [p for p in files if Path(p).name != "conftest.py" and p.endswith(".py")] or files


def _summary(out: str) -> str:
    tail = [ln for ln in out.splitlines() if re.search(r"\d+ (passed|failed|error)", ln)]
    return (tail[-1] if tail else out.strip()[-200:]).strip()


# ------------------------------------------------------------------------------------------- claim repro
_ADDED_TEST = re.compile(r"^\+\s*(?:async\s+)?def\s+(test_[A-Za-z0-9_]+)\s*\(")


def added_tests(test_patch: str) -> list:
    """[(file, name, new-side line)] for every "+def test_x(" line of the test_patch."""
    out = []
    for fp in parse_patch(test_patch):
        for h in fp.hunks:
            n = h.new_start
            for raw in h.lines:
                if raw.startswith("\\"):
                    continue
                kind = _body_kind(raw)[0]
                if kind == "+":
                    m = _ADDED_TEST.match(raw)
                    if m:
                        out.append((fp.path, m.group(1), n))
                    n += 1
                elif kind == " ":
                    n += 1
    return out


def _qualnames(src: str) -> dict:
    """{def line: 'Class::Inner::name'} for every function in a module."""
    out = {}

    def walk(node, prefix):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out[ch.lineno] = prefix + ch.name
            elif isinstance(ch, ast.ClassDef):
                walk(ch, prefix + ch.name + "::")
    walk(ast.parse(src), "")
    return out


def hidden_claim_nodes(tid: str) -> list:
    """Node ids (file::[Class::]test) of the test functions the test_patch adds ("+def test_x(" lines), located with
    ast in the base tree that has the test_patch committed. A test_patch that only modifies existing tests adds none;
    then the grader's own required list (verification._extract_test_functions_from_patch) is used, resolved by name in
    the files the test_patch touches."""
    tp = load_task(tid)["test_patch"]
    base = base_ws(tid, with_test_patch=True)
    cache: dict = {}

    def names_in(path: str) -> dict:
        if path not in cache:
            try:
                cache[path] = _qualnames((base / path).read_text(encoding="utf-8", errors="replace"))
            except (OSError, SyntaxError, ValueError):
                cache[path] = {}
        return cache[path]

    nodes: list = []
    for path, name, line in added_tests(tp):
        q = names_in(path).get(line)
        if q is None or q.rsplit("::", 1)[-1] != name:
            q = next((v for v in names_in(path).values() if v.rsplit("::", 1)[-1] == name), name)
        if f"{path}::{q}" not in nodes:
            nodes.append(f"{path}::{q}")
    if not nodes:
        files = [fp.path for fp in parse_patch(tp) if fp.path.endswith(".py") and not fp.deleted]
        for name in _harness().vf._extract_test_functions_from_patch(tp):
            for path in files:
                for q in names_in(path).values():
                    if q.rsplit("::", 1)[-1] == name and f"{path}::{q}" not in nodes:
                        nodes.append(f"{path}::{q}")
    return nodes


def hidden_claims_repro(tid: str, nodes: list | None = None) -> str:
    """A claim-structured repro (SPEC 4.9.2) with one '# CLAIM n: <file>::<test>' section per test function the
    test_patch adds (or per given node); each section runs exactly that hidden test with pytest and exits with its
    status. Test-harness code, not bundle code."""
    parts = []
    for n, node in enumerate(hidden_claim_nodes(tid) if nodes is None else nodes, 1):
        parts.append(f"# CLAIM {n}: {node}\n"
                     "import subprocess, sys; sys.exit(subprocess.call([sys.executable, \"-m\", \"pytest\", \"-q\", "
                     "\"-x\", \"-p\", \"no:cacheprovider\", \"-p\", \"no:anyio\", " + json.dumps(node) + "]))\n")
    return "".join(parts)


def _node_key(node: str) -> tuple:
    """('stem', 'Class', ..., 'func') for 'dir/test_stem.py::Class::func': JUnit classnames are the dotted module as
    pytest imported it (with rootdir-prepend and no tests/__init__.py that is just 'test_stem'), plus the classes."""
    path, _, rest = node.partition("::")
    parts = rest.split("::") if rest else []
    stem = Path(path).stem
    return tuple([stem] + parts)


def _junit_match(key: tuple, classname: str, name: str) -> bool:
    want_cls, want_fn = key[:-1], key[-1]
    got = tuple(classname.split("."))
    return name.split("[", 1)[0] == want_fn and got[-len(want_cls):] == want_cls


GRADER_FLAGS = ("-p", "no:anyio", "-o", "timeout=0", "-o", "python_classes=Test* *Test", "-q")   # verification.py:493


def junit_cases(tree, selectors: list, env: dict, timeout: float) -> tuple:
    """One grader-style pytest run (python3 -s -m pytest, PYTHONSAFEPATH=1, the grader's flags plus
    -p no:cacheprovider) with JUnit. Returns ([(classname, name, failed_or_skipped)] | None, timed_out)."""
    import xml.etree.ElementTree as ET
    e = dict(env, PYTHONSAFEPATH="1", PYTHONNOUSERSITE="1")
    junit = Path(f"{tree}_tmp") / "hidden_junit.xml"
    junit.parent.mkdir(parents=True, exist_ok=True)
    junit.unlink(missing_ok=True)
    r = run(["python3", "-s", "-m", "pytest", *selectors, f"--junitxml={junit}", "-p", "no:cacheprovider",
             *GRADER_FLAGS], cwd=tree, env=e, timeout=timeout)
    if r.timed_out or not junit.is_file():
        return None, r.timed_out
    cases = []
    with contextlib.suppress(ET.ParseError):
        for tc in ET.parse(junit).getroot().iter("testcase"):
            bad = any(tc.find(x) is not None for x in ("failure", "error", "skipped"))
            cases.append((tc.get("classname", ""), tc.get("name", ""), bad))
    return cases, False


def hidden_outcomes(tree, nodes: list, env: dict, timeout: float = 40, node_cap: float = 10) -> dict:
    """{node: pass|fail|hang|missing|unknown} for hidden-test nodes in `tree`, independent of the helpers: one
    junit_cases run over all nodes; after a timeout (or for nodes the batch did not report) each node alone with
    node_cap seconds, at most 12 of them (the rest are 'unknown'). A parametrised node passes only if every case
    passes; skipped counts as not passed (as in the grader)."""
    def outcome(cases, node):
        hits = [bad for cls, name, bad in cases if _junit_match(_node_key(node), cls, name)]
        return "missing" if not hits else ("fail" if any(hits) else "pass")

    cases, to = junit_cases(tree, nodes, env, timeout)
    out = {node: outcome(cases, node) for node in nodes} if cases is not None else {}
    # Alone: every node after a timeout, and a 'missing' one after a batch that one bad node id can abort (exit 4).
    redo = [n for n in nodes if out.get(n, "missing") == "missing"] if len(nodes) > 1 or to else []
    for i, node in enumerate(redo):
        if i >= 12:
            out[node] = "unknown"                         # not measured: never counted as failing
            continue
        c, solo_to = junit_cases(tree, [node], env, node_cap)
        out[node] = "hang" if solo_to else ("missing" if c is None else outcome(c, node))
    return {n: out.get(n, "missing") for n in nodes}


# ----------------------------------------------------------------------------------------- stage prompts
STAGES = ("setup", "locator", "fixer", "verifier", "submitter")
# SPEC section 6: 12 tool declarations about 7,200 chars (+250 for submit_patch), skill boilerplate 1,333 chars,
# ADK identity about 150 chars; prose at 3.4 chars/token.
DECL_CHARS, SUBMIT_DECL_CHARS, SKILL_CHARS, IDENTITY_CHARS, CHARS_PER_TOKEN = 7200, 250, 1333, 150, 3.4
STAGE_BUDGET_TOKENS = 8000                                       # R94
PLAN_120 = " ".join(["planned"] * 120)
NOTES_60 = " ".join(["changed"] * 60)
# `find . -maxdepth 3 ... | sort | head -150` (agent_runner.py:312): rich's real tree is 3,283 chars; 150 lines of 31
# chars (4,650) matches the SPEC section 6 worst case and leaves room for fastapi's longer docs_src paths.
TREE_150 = "\n".join(f"./pkg_dir/subdir/module_{i:03d}.py" for i in range(150))


def harness_prompt(task: dict) -> str:
    """The harness user prompt (agent_runner.build_agent_prompt) with the v10 eval_config budgets, the graph section
    and a 150-line tree: the worst case setup sees."""
    from swegemma.harness.agent_runner import build_agent_prompt
    cfg = SimpleNamespace(
        budget=SimpleNamespace(time_minutes=5, tool_calls=100, turns=200, cost_usd=None),
        harness=SimpleNamespace(command_timeout_seconds=120, max_stdout_chars=5000, max_file_lines=2000,
                                max_file_chars=100000),
        graph_dir=str(DATA / "raw" / "graphs"), embeddings_dir=str(DATA / "raw" / "embeddings"),
        enable_sandbox_testing=True)
    t = SimpleNamespace(repo=task["repo"], problem_statement=task["problem_statement"],
                        hints_text=task.get("hints_text") or "", base_commit=task.get("base_commit"))
    return build_agent_prompt(t, cfg, workspace_tree=TREE_150)


def stage_start_tokens(stage: str, task: dict) -> int:
    text = (BUNDLE / "prompts" / f"{stage}.md").read_text(encoding="utf-8")
    text = (text.replace("{problem_description}", task["problem_statement"]).replace("{plan?}", PLAN_120)
            .replace("{fix_notes?}", NOTES_60))
    chars = len(text) + DECL_CHARS + SKILL_CHARS + IDENTITY_CHARS
    if stage in ("verifier", "submitter"):
        chars += SUBMIT_DECL_CHARS
    if stage == "setup":
        chars += len(harness_prompt(task))
    return math.ceil(chars / CHARS_PER_TOKEN)


# --------------------------------------------------------------------------------------------- thresholds
def need(k: int, base_n: int, n: int) -> int:
    """The SPEC's 'k of base_n' bar scaled to n eligible tasks (exactly k when n == base_n)."""
    return math.ceil(k * n / base_n) if n else 0


# ------------------------------------------------------------------------------------ per-task computations
def _gold_py(tid: str) -> list:
    return [p for p in patch_files(load_task(tid)["patch"]) if p.endswith(".py")]


def _job_static(tid: str) -> dict:
    t = load_task(tid)
    h = _harness()
    res: dict = {"id": tid}
    for kind in ("patch", "test_patch"):
        text = t[kind]
        fps = parse_patch(text)
        res[kind] = {
            "files": [fp.path for fp in fps],
            "roundtrip": render_patch(fps) == text,
            "counts_ok": all(hk.counts_ok for fp in fps for hk in fp.hunks),
            "new": [fp.path for fp in fps if fp.new_file],
            "new_consistent": all(fp.new_file == (fp.old_path == "/dev/null" or all(
                hk.old_start == 0 and hk.old_len == 0 for hk in fp.hunks) or any(
                x.startswith("new file mode") for x in fp.header)) for fp in fps),
            "n_hunks": sum(len(fp.hunks) for fp in fps),
            "harness_files": h.extract(text) if kind == "test_patch" else [],
            "protected": [fp.path for fp in fps if h.vf._is_protected_test_or_config_path(fp.path)],
        }
    res["n_added_tests"] = len(added_tests(t["test_patch"]))
    res["harness_test_funcs"] = h.vf._extract_test_functions_from_patch(t["test_patch"])
    return res


def _protected_by_helpers(paths: list) -> dict | None:
    """{path: reason|None} from the bundle's _swe_common.is_protected (one subprocess), or None if not built."""
    if not bundle_has("_swe_common"):
        return None
    with work_dir("prot") as wd:
        shutil.copytree(SCRIPTS, wd / "scripts", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (wd / "repo").mkdir()
        git(wd / "repo", "init", "-q")
        code = ("import json, sys; sys.dont_write_bytecode = True; sys.path.insert(0, sys.argv[1]); "
                "import _swe_common as C; ps = json.load(sys.stdin); "
                "print(json.dumps({p: C.is_protected(p) for p in ps}))")
        env = dict(os.environ, SWE_DIR=str(wd / "swe"), TMPDIR=str(wd), PYTHONDONTWRITEBYTECODE="1", SWE_DUAL="0",
                   SWE_DOCKER_TMP_FOR_TESTS=str(wd / "dockertmp"), SWE_WS=str(wd / "repo"))
        r = run([sys.executable, "-c", code, str(wd / "scripts")], cwd=wd / "repo", env=env, timeout=60,
                stdin=json.dumps(paths))
        if r.rc != 0:
            raise RuntimeError(f"is_protected probe failed: {r.err[-400:]}")
        return json.loads(r.out.strip().splitlines()[-1])


_PROT: dict = {}


def helper_protection() -> dict | None:
    """{path: reason|None} from the helpers' is_protected for every gold and test_patch path of the 74 tasks
    (one subprocess per session), or None while _swe_common is not built."""
    if "v" not in _PROT:
        paths = sorted({p for tid in TASK_IDS for k in ("patch", "test_patch") for p in patch_files(load_task(tid)[k])})
        _PROT["v"] = _protected_by_helpers(paths)
    return _PROT["v"]


def _job_locate(tid: str) -> dict:
    t = load_task(tid)
    with work_dir("loc") as wd:
        ws = fresh_ws(tid, wd)
        env = sandbox_env(ws, tid)
        ins = install_helpers(env)
        r = run_helper("locate", ["--query", t["problem_statement"]], ws, env, timeout=60)
        ranked = re.findall(r"^\s*\d+\.\s+(\S+)", r.out, re.M)
        gold = _gold_py(tid)
        ranks = {g: (ranked.index(g) + 1 if g in ranked else 99) for g in gold}
        return {"id": tid, "rank": min(ranks.values(), default=99), "ranks": ranks, "ranked": ranked[:10],
                "secs": round(r.secs, 3), "chars": len(r.out), "first": first_line(r.out), "rc": r.rc,
                "err": r.err[-300:], "installed": ins.installed, "timed_out": r.timed_out}


def _edit_input(h: Hunk) -> str:
    return ("<<<<<<< SEARCH\n" + "".join(h.old_lines) + "=======\n" + "".join(h.new_lines) + ">>>>>>> REPLACE\n")


_MARKER = re.compile(r"^\s*(<{5,9} ?SEARCH|={5,9}|>{5,9} ?REPLACE)\s*$", re.I)


def _sr_expressible(h: Hunk) -> bool:
    body = h.old_lines + h.new_lines
    return (h.old_len > 0 and all(x.endswith("\n") for x in body)
            and not any(_MARKER.match(x.rstrip("\r\n")) for x in body))


def _apply_hunks_edit(tid: str, ws: Path, env: dict, mode: str) -> dict:
    """Apply every gold hunk with edit.py. mode "sr": one SEARCH/REPLACE call per file with every hunk as a block
    (per-hunk bottom-up retries, widening context on AMBIGUOUS); mode "lines": --lines/--insert-after/--delete per hunk,
    bottom-up. New files use --create in both modes."""
    log: list = []
    ok = True
    for fp in parse_patch(load_task(tid)["patch"]):
        if not fp.path:
            continue
        if fp.new_file:
            text = "".join(ln for hk in fp.hunks for ln in hk.new_lines)
            r = run_helper("edit", [fp.path, "--create"], ws, env, stdin=text, timeout=60)
            log.append({"file": fp.path, "mode": "create", "first": first_line(r.out)})
            ok &= first_line(r.out).startswith("OK")
            continue
        if mode == "sr" and all(_sr_expressible(hk) for hk in fp.hunks):
            r = run_helper("edit", [fp.path], ws, env, stdin="".join(_edit_input(hk) for hk in fp.hunks), timeout=60)
            log.append({"file": fp.path, "mode": "sr-multi", "blocks": len(fp.hunks), "first": first_line(r.out)})
            if first_line(r.out).startswith("OK"):
                continue
        for hk in sorted(fp.hunks, key=lambda x: -x.old_start):
            if mode == "sr" and _sr_expressible(hk):
                res = _sr_one(fp.path, hk, ws, env)
                log.append(res)
                ok &= res["first"].startswith("OK")
                continue
            new = "".join(hk.new_lines)
            if hk.old_len == 0:
                args = [fp.path, "--insert-after", str(hk.old_start)]
            elif not new:
                args = [fp.path, "--lines", f"{hk.old_start}-{hk.old_start + hk.old_len - 1}", "--delete"]
            else:
                args = [fp.path, "--lines", f"{hk.old_start}-{hk.old_start + hk.old_len - 1}"]
            r = run_helper("edit", args, ws, env, stdin=new if new else None, timeout=60)
            log.append({"file": fp.path, "mode": "lines", "args": args[1:], "first": first_line(r.out)})
            ok &= first_line(r.out).startswith("OK")
    return {"ok": ok, "log": log}


def _sr_one(path: str, hk: Hunk, ws: Path, env: dict) -> dict:
    """One hunk as SEARCH/REPLACE; on AMBIGUOUS, widen the block with the file's own surrounding lines (what the
    AMBIGUOUS message asks the model to do), up to 12 lines each side."""
    old, new = list(hk.old_lines), list(hk.new_lines)
    cur = (ws / path).read_bytes().decode("utf-8", "surrogateescape")
    flines = split_lines(cur)
    a, b = hk.old_start - 1, hk.old_start - 1 + hk.old_len
    res: dict = {}
    for widen in range(0, 13):
        pre = flines[max(0, a - widen):a]
        post = flines[b:b + widen]
        block = ("<<<<<<< SEARCH\n" + "".join(pre + old + post) + "=======\n" + "".join(pre + new + post)
                 + ">>>>>>> REPLACE\n")
        r = run_helper("edit", [path], ws, env, stdin=block, timeout=60)
        res = {"file": path, "mode": "sr", "hunk": hk.old_start, "widen": widen, "first": first_line(r.out)}
        if not res["first"].startswith("AMBIGUOUS"):
            break
    return res


def _job_edit(tid: str) -> dict:
    t = load_task(tid)
    out: dict = {"id": tid, "modes": {}}
    fps = [fp for fp in parse_patch(t["patch"]) if fp.path]
    out["n_hunks"] = sum(len(fp.hunks) for fp in fps)
    with work_dir("edit") as wd:
        gold = fresh_ws(tid, wd / "gold")
        ok, err = git_apply(gold, t["patch"])
        if not ok:
            return {**out, "error": f"gold does not git-apply: {err}"}
        for mode in ("sr", "lines"):
            t0 = time.monotonic()
            ws = fresh_ws(tid, wd / mode)
            env = sandbox_env(ws, tid)
            install_helpers(env)
            applied = _apply_hunks_edit(tid, ws, env, mode)
            mism = []
            for fp in fps:
                a, b = ws / fp.path, gold / fp.path
                if a.exists() != b.exists() or (a.is_file() and a.read_bytes() != b.read_bytes()):
                    mism.append(fp.path)
            paths = {fp.path for fp in fps}
            st = git(ws, "status", "--porcelain", "-uall").out.splitlines()
            stray = [ln for ln in st if ln[3:].strip().strip('"') not in paths]
            out["modes"][mode] = {"ok": applied["ok"] and not mism and not stray, "calls_ok": applied["ok"],
                                  "mismatch": mism, "stray": stray[:10], "log": applied["log"][-12:],
                                  "secs": round(time.monotonic() - t0, 2)}
    return out


def _job_verify_empty(tid: str) -> dict:
    with work_dir("ve") as wd:
        ws = fresh_ws(tid, wd)
        env = sandbox_env(ws, tid)
        install_helpers(env)
        r = run_helper("verify", [], ws, env, timeout=30)
        return {"id": tid, "first": first_line(r.out), "secs": round(r.secs, 3), "chars": len(r.out),
                "rc": r.rc, "err": r.err[-300:]}


_COLLECTABLE = re.compile(r"(^|/)(test_[^/]*|[^/]*_test)\.py$")
_NEVER_PICK = re.compile(r"(^|/)(conftest\.py|render\.py|_card_render\.py)$|^tools/")


def _job_discovery(tid: str) -> dict:
    t = load_task(tid)
    with work_dir("disc") as wd:
        ws = fresh_ws(tid, wd)
        ok, err = git_apply(ws, t["patch"])
        if not ok:
            return {"id": tid, "error": f"gold does not apply: {err}"}
        env = sandbox_env(ws, tid)
        install_helpers(env)
        r = run_helper("verify", ["--list-tests"], ws, env, timeout=60)
        line = next((ln for ln in r.out.splitlines() if ln.startswith("TESTS:")), "")
        picked = [p.split("::")[0] for p in line[len("TESTS:"):].split() if p.endswith(".py") or "::" in p]
        existing = [fp.path for fp in parse_patch(t["test_patch"]) if not fp.new_file and (ws / fp.path).is_file()]
        bad = [p for p in picked if not _COLLECTABLE.search(p) or _NEVER_PICK.search(p)]
        return {"id": tid, "picked": picked, "targets": existing, "hit": bool(set(picked) & set(existing)),
                "noncollectable": bad, "first": first_line(r.out), "secs": round(r.secs, 3)}


_REGRESSION_WORDS = re.compile(r"\bundo\b|must fix", re.I)


def _job_verify_gold(tid: str) -> dict:
    t = load_task(tid)
    kpar_python(tid)
    with work_dir("vg") as wd:
        ws = fresh_ws(tid, wd)
        ok, err = git_apply(ws, t["patch"])
        if not ok:
            return {"id": tid, "error": f"gold does not apply: {err}"}
        env = sandbox_env(ws, tid)
        install_helpers(env)
        r = run_helper("verify", [], ws, env, timeout=90)
        regs = re.findall(r"^REGRESSIONS.*\n((?:  .*\n?)+)", r.out, re.M)
        return {"id": tid, "first": first_line(r.out), "red": first_line(r.out).startswith("VERIFY: RED"),
                "regressions": bool(regs), "bad_words": bool(_REGRESSION_WORDS.search(r.out)),
                "secs": round(r.secs, 2), "out": r.out[-2000:], "rc": r.rc, "timed_out": r.timed_out}


def file_f2p(orig, gold, files: list, env_of, timeout: float = 40, node_cap: float = 10) -> list:
    """Function-level fail-to-pass nodes of whole test files: every case of the function passes with gold and it
    does not pass on the original (fail, hang or missing). Catches hidden changes that add no "+def test_" line, such
    as new parametrize cases of an existing test. The gold side runs the files; the original side runs only the
    candidates, through hidden_outcomes (so a hanging test costs node_cap, not the whole batch)."""
    cases, _ = junit_cases(gold, files, env_of(gold), timeout)
    per: dict = {}
    for cls, name, bad in cases or []:
        comps = cls.split(".")
        for f in files:
            stem = Path(f).stem
            if stem in comps:
                node = "::".join([f] + comps[comps.index(stem) + 1:] + [name.split("[", 1)[0]])
                per[node] = "fail" if bad or per.get(node) == "fail" else "pass"
                break
    cand = [n for n, v in per.items() if v == "pass"]
    if not cand:
        return []
    o = hidden_outcomes(orig, cand, env_of(orig), timeout=timeout, node_cap=node_cap)
    return [n for n in cand if o[n] in ("fail", "hang", "missing")]


def _job_repro(tid: str) -> dict:
    """R103. The claims are the hidden tests that fail (or hang) on the original code and pass with gold (F2P,
    measured here with plain pytest, independent of the helpers); hidden tests that pass on the original are test-data
    facts, not helper behaviour (measured: rich_3067, rich_3006, rich_3454, rich_3782, rich_3675, requests_6644 in
    parity), so a task with no F2P hidden test is skipped. At most 6 claims, as verify.py runs at most 6."""
    t = load_task(tid)
    kpar_python(tid)
    nodes = hidden_claim_nodes(tid)
    base = base_ws(tid, with_test_patch=True)
    with work_dir("rp") as wd:
        orig = fresh_ws(base, wd / "o")
        gold = fresh_ws(base, wd / "g")
        ok, err = git_apply(gold, t["patch"])
        if not ok:
            return {"id": tid, "error": f"gold does not apply: {err}"}
        o = hidden_outcomes(orig, nodes, sandbox_env(orig, tid, None)) if nodes else {}
        g = hidden_outcomes(gold, nodes, sandbox_env(gold, tid, None)) if nodes else {}
        f2p = [n for n in nodes if o.get(n) in ("fail", "hang", "missing") and g.get(n) == "pass"][:6]
        source = "added tests"
        if not f2p:
            files = [p for p in extract_targets(t["test_patch"]) if (orig / p).is_file()]
            f2p = file_f2p(orig, gold, files, lambda tree: sandbox_env(tree, tid, None))[:6] if files else []
            source = "test files"
        if not f2p:
            return {"id": tid, "skip": f"no hidden test fails on the original and passes with gold (F2P empty; "
                                       f"{len(nodes)} hidden: orig {sorted(set(o.values()))}, gold "
                                       f"{sorted(set(g.values()))})"}
        repro = hidden_claims_repro(tid, f2p)
        ws = fresh_ws(base, wd / "w")
        env = sandbox_env(ws, tid)
        install_helpers(env)
        r1 = run_helper("verify", ["--repro-only"], ws, env, stdin=repro, timeout=60)
        ok, err = git_apply(ws, t["patch"])
        if not ok:
            return {"id": tid, "error": f"gold does not apply: {err}"}
        r2 = run_helper("verify", [], ws, env, timeout=90)
        m = re.search(r"^REPRO:\s*(\d+)/(\d+) claims fixed", r2.out, re.M)
        k, n = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
        return {"id": tid, "claims": len(f2p), "claims_from": source, "hidden": len(nodes), "orig": first_line(r1.out),
                "after": first_line(r2.out), "repro_line": m.group(0) if m else "", "k": k, "n": n,
                "flip": bool(m) and n == len(f2p) and k == n,
                "orig_fails": bool(re.match(r"REPRO: (fails on original|claim \d+ hangs on original)",
                                            first_line(r1.out))),
                "secs": round(r1.secs + r2.secs, 2), "out_orig": r1.out[-1200:], "out_after": r2.out[-2000:]}


def submit_diff(ws, env=None) -> str:
    """What submit_patch captures (tools/execution.py:83-86): git add -N . then git diff --binary <baseline>."""
    git(ws, "add", "-N", ".", env=env)
    r = git(ws, "diff", "--binary", "_swegemma_baseline", env=env)
    return r.out


def _job_finalize(tid: str) -> dict:
    t = load_task(tid)
    kpar_python(tid)
    with work_dir("fin") as wd:
        ws = fresh_ws(tid, wd / "a")
        ok, err = git_apply(ws, t["patch"])
        if not ok:
            return {"id": tid, "error": f"gold does not apply: {err}"}
        tampered = tamper_test_hunk(ws, t["test_patch"])
        (ws / "repro.py").write_text("print('repro')\n")
        (ws / "reproduce_issue.py").write_text("print('reproduce')\n")
        env = sandbox_env(ws, tid)
        install_helpers(env)
        r = run_helper("finalize", [], ws, env, timeout=60)
        diff = submit_diff(ws)
        chk = fresh_ws(tid, wd / "b")
        d = diff if diff.endswith("\n") or not diff else diff + "\n"
        applies = bool(diff.strip()) and git(chk, "apply", "--check", "-", stdin=d).rc == 0
        tp_ok = False
        if applies and git(chk, "apply", "-", stdin=d).rc == 0:
            tp = t["test_patch"] if t["test_patch"].endswith("\n") else t["test_patch"] + "\n"
            tp_ok = git(chk, "apply", "--check", "-", stdin=tp).rc == 0
        if diff.strip():
            resolved, why, secs = mini_verify(base_ws(tid), diff, t["test_patch"], repo=tid)
        else:
            resolved, why, secs = False, "empty final diff", 0.0
        files = [fp.path for fp in parse_patch(diff)] if diff.strip() else []
        return {"id": tid, "first": first_line(r.out), "ready": first_line(r.out).startswith("READY"),
                "tampered": tampered, "diff_applies": applies, "test_patch_applies": tp_ok,
                "resolved": resolved, "why": why, "final_files": files,
                "scratch_left": [f for f in files if Path(f).name in ("repro.py", "reproduce_issue.py")],
                "secs": round(r.secs, 2), "mv_secs": round(secs, 2), "out": r.out[-1000:]}


def _job_mini(tid: str) -> dict:
    t = load_task(tid)
    kpar_python(tid)
    base = base_ws(tid)
    g = mini_verify(base, t["patch"], t["test_patch"], repo=tid)
    e = mini_verify(base, "", t["test_patch"], repo=tid)
    return {"id": tid, "gold": g[0], "gold_why": g[1], "gold_secs": round(g[2], 2),
            "empty": e[0], "empty_why": e[1], "empty_secs": round(e[2], 2)}


def _job_tamper(tid: str) -> dict:
    t = load_task(tid)
    kpar_python(tid)
    base = base_ws(tid)
    with work_dir("tq") as wd:                            # can this task be tampered at all?
        if tamper_test_hunk(fresh_ws(base, wd), t["test_patch"]) is None:
            return {"id": tid, "skip": "the test_patch only adds new test files"}
    info: dict = {}
    resolved, why, secs = mini_verify(base, t["patch"], t["test_patch"], tamper="test_hunk", repo=tid, info=info)
    return {"id": tid, "resolved": resolved, "why": why, "secs": round(secs, 2), "file": info.get("tamper_file"),
            "reset_ok": info.get("reset_ok"), "tp_git_apply_ok": info.get("tp_git_apply_ok"),
            "lost": not resolved and (why or "").startswith("test_patch did not apply")}


KINDS = {
    "static": (_job_static, False, ()),
    "locate": (_job_locate, True, ("install", "locate")),
    "edit": (_job_edit, True, ("install", "edit")),
    "verify_empty": (_job_verify_empty, True, ("install", "verify")),
    "discovery": (_job_discovery, True, ("install", "verify")),
    "verify_gold": (_job_verify_gold, True, ("install", "verify")),
    "repro": (_job_repro, True, ("install", "verify")),
    "finalize": (_job_finalize, True, ("install", "finalize")),
    "mini": (_job_mini, True, ()),
    "tamper": (_job_tamper, True, ()),
}


# Budgets asserted by the tests (SPEC R98, R100, R102, R105).
LOCATE_BUDGET_S, VERIFY_EMPTY_BUDGET_S, VERIFY_GOLD_P90_S, MINI_GOLD_BUDGET_S = 3.0, 1.0, 8.0, 30.0


def _retry_serially(out: dict, fn, bad) -> None:
    """Re-run, one at a time, the tasks whose parallel result `bad(tid, r)` flags; the serial result replaces it and
    the parallel one is kept under 'parallel'. The scorer runs one task at a time, while the Mac runs G4_J jobs (and
    other work): load-sensitive repo tests flake (measured: rich's test_brokenpipeerror failed under J=4 in rich_3777
    verify and rich_3470 mini_verify, and passed 3/3 serially) and first-call timings stretch. A serial retry that is
    still bad is a real finding."""
    for tid, r in list(out.items()):
        if "skip" in r or "error" in r or not bad(tid, r):
            continue
        r2 = _safe(fn, tid)
        r2["retried_serially"] = True
        r2["parallel"] = {k: v for k, v in r.items() if not isinstance(v, (dict, list)) and k != "id"}
        out[tid] = r2


def _post_locate(out: dict) -> None:
    _retry_serially(out, _job_locate, lambda tid, r: r["secs"] > LOCATE_BUDGET_S)


def _post_verify_empty(out: dict) -> None:
    _retry_serially(out, _job_verify_empty, lambda tid, r: r["secs"] >= VERIFY_EMPTY_BUDGET_S)


def _post_verify_gold(out: dict) -> None:
    """RED outside KNOWN_BEHAVIOUR_CHANGE, and the slowest tasks when the parallel p90 is over budget."""
    _retry_serially(out, _job_verify_gold, lambda tid, r: r.get("red") and tid not in KNOWN_BEHAVIOUR_CHANGE)
    secs = sorted(r["secs"] for r in out.values() if "secs" in r)
    if secs and secs[min(len(secs) - 1, int(0.9 * len(secs)))] > VERIFY_GOLD_P90_S:
        slow = sorted((r["secs"], t) for t, r in out.items() if r.get("secs", 0) > VERIFY_GOLD_P90_S)[-12:]
        pick = {t for _, t in slow}
        _retry_serially(out, _job_verify_gold, lambda tid, r: tid in pick)


def _post_repro(out: dict) -> None:
    _retry_serially(out, _job_repro, lambda tid, r: not (r.get("orig_fails") and r.get("flip")))


def _post_finalize(out: dict) -> None:
    _retry_serially(out, _job_finalize, lambda tid, r: not (r.get("ready") and r.get("resolved")))


def _post_mini(out: dict) -> None:
    _retry_serially(out, _job_mini, lambda tid, r: (not r["gold"] and tid not in KNOWN_GOLD_LOST)
                    or (r["empty"] and tid not in KNOWN_FREE) or r["gold_secs"] >= MINI_GOLD_BUDGET_S
                    or r["empty_secs"] >= MINI_GOLD_BUDGET_S)


POST = {"locate": _post_locate, "verify_empty": _post_verify_empty, "verify_gold": _post_verify_gold,
        "repro": _post_repro, "finalize": _post_finalize, "mini": _post_mini}
_RESULTS: dict = {}
_RESULTS_LOCK = threading.Lock()


SELECT = frozenset(os.environ.get("G4_TASKS", "").replace(",", " ").split())   # optional subset, e.g. "rich_3278"


def eligible(kind: str) -> list:
    """Task ids a kind runs on: all 74 for 'static', else the local snapshots whose parity venv exists (restricted to
    $G4_TASKS when set)."""
    ids = [tid for tid in TASK_IDS if not SELECT or tid in SELECT]
    if kind == "static":
        return ids
    return [tid for tid in ids if has_snapshot(tid) and kpar_ok(tid)]


def results(kind: str) -> dict:
    """{tid: result} for one kind, computed once per session over eligible(kind) with ThreadPoolExecutor(G4_J) and
    written to $G4_OFFLINE_OUT/v10_<kind>.json. A task whose job skipped holds {"skip": reason}; a crashed job holds
    {"error": traceback}. Skips the caller when a needed helper is not built yet."""
    fn, needs_ws, helpers = KINDS[kind]
    require_helpers(*helpers)
    with _RESULTS_LOCK:
        if kind in _RESULTS:
            return _RESULTS[kind]
        ids = eligible(kind)
        if needs_ws:                                      # build missing bases in parallel before timing anything
            with cf.ThreadPoolExecutor(J) as ex:
                list(ex.map(_safe_base, ids))
        t0 = time.monotonic()
        load0 = os.getloadavg()[0]
        out: dict = {}
        with cf.ThreadPoolExecutor(J) as ex:
            for tid, res in zip(ids, ex.map(lambda x: _safe(fn, x), ids)):
                out[tid] = res
        if kind in POST:
            POST[kind](out)
        wall = time.monotonic() - t0
        _META[kind] = {"load_start": round(load0, 1), "load_end": round(os.getloadavg()[0], 1),
                       "ncpu": os.cpu_count() or 1, "retried": sorted(t for t, r in out.items()
                                                                     if r.get("retried_serially"))}
        _write(kind, out, wall)
        _RESULTS[kind] = out
        return out


def _safe_base(tid: str) -> None:
    with contextlib.suppress(BaseException):
        base_ws(tid)


def _safe(fn, tid: str) -> dict:
    try:
        return fn(tid)
    except pytest.skip.Exception as e:
        return {"id": tid, "skip": str(e.msg if hasattr(e, "msg") else e)}
    except Exception:
        return {"id": tid, "error": traceback.format_exc()[-3000:]}


_META: dict = {}


def busy_machine(kind: str) -> str | None:
    """Why timing aggregates of a kind are not trustworthy (other work already loaded the Mac beyond half its cores
    when the kind started), or None."""
    m = _META.get(kind)
    if m and m["load_start"] > m["ncpu"] / 2:
        return f"1-min load {m['load_start']} on {m['ncpu']} cores when {kind} started"
    return None


def _write(kind: str, out: dict, wall: float) -> None:
    OFFLINE_OUT.mkdir(parents=True, exist_ok=True)
    doc = {"kind": kind, "bundle": str(BUNDLE), "j": J, "wall_secs": round(wall, 1),
           "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **_META.get(kind, {}), "tasks": out}
    tmp = OFFLINE_OUT / f".v10_{kind}.json.{os.getpid()}"
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True, default=str))
    os.replace(tmp, OFFLINE_OUT / f"v10_{kind}.json")


def task_result(kind: str, tid: str) -> dict:
    """One task's result for a parametrised test: skips for a missing snapshot/venv/helper, fails on a crashed job."""
    if kind != "static":
        require_snapshot(tid)
        kpar_python(tid)
    res = results(kind).get(tid)
    if res is None:
        pytest.skip(f"{tid} not in the {kind} run")
    if "skip" in res:
        pytest.skip(res["skip"])
    if "error" in res:
        pytest.fail(f"{kind} job crashed for {tid}:\n{res['error']}", pytrace=False)
    return res


def computed(kind: str) -> dict:
    """The results of a kind without skipped or crashed tasks, for the aggregate bars. The bars are defined on the full
    local population, so an aggregate test skips when G4_TASKS selects a subset."""
    if SELECT:
        pytest.skip("aggregate bars need the full local population (unset G4_TASKS)")
    return {k: v for k, v in results(kind).items() if "skip" not in v and "error" not in v}
