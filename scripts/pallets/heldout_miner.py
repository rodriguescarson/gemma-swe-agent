"""Mine execution-verified SWE-bench-style tasks from public Python repos into data/heldout1k/tasks.jsonl (metadata only).

  .venv/bin/python scripts/pallets/heldout_miner.py --repo python-attrs/attrs [--limit 300] [--since 2021-01-01]
                                                    [--batch 30] [-j 4] [--target 525] [--floor-gb 8]

Per repo: one full clone into the scratch dir; merged PRs from `gh pr list` (one call, gh pages it at 100); per PR the
diff first-parent..merge-commit, split into patch (source) and test_patch (tests), docs/changelog dropped
(split_diff). A PR is a candidate when it changes both source and tests, has no binary file, the diff's files equal
the PR's own file list (a rebase-merge's last commit is only part of the PR), and is not already known (data/pallets,
the competition's public set, this file). Candidates go in date-ordered batches; per batch a fresh venv
(python 3.12, pytest 8.4.2, the repo's deps from REPO_CFG, as scripts/pallets/build_envs.sh does) and per task a
git worktree, both deleted after the batch / task. `df` is checked before every batch: below --floor-gb the run stops.

Validation (validate_one), the grader's semantics (tests/v10_support/tasks.mini_verify): the harness pytest.ini is
written at the workspace root, PYTHONPATH=<ws>:<ws>/src, the grader's pytest line on the test_patch's .py files:
  base = base_commit + test_patch          (once)
  gold = base_commit + test_patch + patch  (twice)
valid = FAIL_TO_PASS (passed in both gold runs, not passed at base) is non-empty, every gold run exits 0 with the
grader's junit check (swegemma _validate_junit_xml) passing, within MARGIN_S. PASS_TO_PASS = passed in all three.
Only valid tasks are written; data/heldout1k/rejects.jsonl keeps one small row per rejected candidate (id + reason).
Problem statement = PR title + "\\n\\n" + body (scripts/pallets/pr_statements.py), title-only flag from
scripts/pallets/pallets_profile.py statement_stats.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import contextlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]


def _load_profile():
    """scripts/pallets/pallets_profile.py by path: the name clashes with the stdlib profiler, which may already be imported."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("pallets_profile", Path(__file__).resolve().parent / "pallets_profile.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


statement_stats = _load_profile().statement_stats


def _load_coverage():
    """train/task_coverage.py (the coverage tagger the mining is steered by)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("task_coverage", ROOT / "train" / "task_coverage.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


COVERAGE_SRCS = (ROOT / "data" / "pallets" / "tasks.jsonl", ROOT / "data" / "heldout1k" / "tasks.jsonl",
                 ROOT / "data" / "tasks.jsonl")
NEG_ROUTE_BONUS = 0.5       # negative_route is under-covered (about 21%) but above the 8% gap line

OUT_DIR = ROOT / "data" / "heldout1k"
PALLETS = ROOT / "data" / "pallets" / "tasks.jsonl"
PUBLIC = ROOT / "data" / "tasks.jsonl"
SCRATCH = Path(os.environ.get("G4_HELDOUT_SCRATCH") or Path.home() / ".cache" / "g4" / "heldout1k")
DISK_PATH = "/System/Volumes/Data"
DISK_FLOOR_GB = 8.0
EXCLUDED_REPOS = frozenset({"fastapi/fastapi", "textualize/rich", "psf/requests", "encode/httpx"})
MAX_SRC_LINES = 300
MAX_TEST_LINES = 1000
TIMEOUT_S = 180.0           # the grader's pytest timeout
MARGIN_S = 90.0             # finalize.py: a gold run slower than this is not kept
PYTEST_PIN = "pytest==8.4.2"
SCHEMA_KEYS = ("instance_id", "repo", "base_commit", "fix_commit", "pr_number", "created_at", "merged_at",
               "problem_statement", "statement_title_only", "hints_text", "patch", "test_patch", "test_files",
               "FAIL_TO_PASS", "PASS_TO_PASS", "env", "validation")
# swegemma container_setup.setup_workspace_test_config writes exactly this (tests/test_heldout_miner.py checks it)
HARNESS_PYTEST_INI = """[pytest]
addopts = -p no:anyio
norecursedirs = .* build dist venv
python_classes = Test* *Test
python_files = test_*.py *_test.py
filterwarnings =
    ignore::DeprecationWarning
    ignore::UserWarning
"""
HERMETIC_GIT = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"}

# repo -> test environment. deps: PyPI requirements besides pytest (runtime + test-only); own: the repo's own
# distribution, installed only for importlib.metadata and its runtime deps (code is imported from the workspace).
REPO_CFG: dict = {
    "python-attrs/attrs": {"own": "attrs", "deps": ["hypothesis", "cloudpickle", "zope.interface"]},
    "python-attrs/cattrs": {"own": "cattrs", "deps": ["attrs", "hypothesis", "immutables", "pyyaml", "tomlkit",
                                                      "cbor2", "msgpack", "ujson", "orjson", "pymongo",
                                                      "typing_extensions", "exceptiongroup", "msgspec"]},
    "marshmallow-code/marshmallow": {"own": "marshmallow", "deps": ["simplejson", "pytz"]},
    "Kludex/starlette": {"own": "starlette", "deps": ["anyio", "httpx", "itsdangerous", "jinja2", "python-multipart",
                                                      "pyyaml", "trio", "typing_extensions"]},
    "httpie/cli": {"own": "httpie", "deps": ["pytest-httpbin", "responses", "pytest-mock", "werkzeug<2.1", "mock"]},
    "more-itertools/more-itertools": {"own": "more-itertools", "deps": []},
    "pytoolz/toolz": {"own": "toolz", "deps": []},
    "dateutil/dateutil": {"own": "python-dateutil", "deps": ["freezegun", "hypothesis", "six"]},
    "pyparsing/pyparsing": {"own": "pyparsing", "deps": ["railroad-diagrams", "jinja2"]},
    "python-poetry/tomlkit": {"own": "tomlkit", "deps": ["pyyaml"]},
    "python-jsonschema/jsonschema": {"own": "jsonschema", "deps": ["attrs", "referencing", "rpds-py",
                                                                   "jsonschema-specifications", "pyrsistent"]},
    "psf/black": {"own": "black", "deps": ["click", "mypy_extensions", "packaging", "pathspec", "platformdirs",
                                           "aiohttp", "tokenize-rt", "ipython", "pytokens"]},
    "PyCQA/isort": {"own": "isort", "deps": ["hypothesis", "hypothesmith", "black", "colorama",
                                             "pip-api", "pipreqs", "toml"]},
    "hynek/structlog": {"own": "structlog", "deps": ["freezegun", "pretend", "simplejson", "rich", "better-exceptions",
                                                     "pytest-asyncio"]},
    "pytest-dev/pluggy": {"own": "pluggy", "deps": []},
    "andialbrecht/sqlparse": {"own": "sqlparse", "deps": []},
}


class DiskFloor(RuntimeError):
    pass


class RateLimited(RuntimeError):
    pass


class ExcludedRepo(ValueError):
    pass


# ------------------------------------------------------------------------------------------- diff handling
TEST_DIRS = {"tests", "test", "testing"}
DOC_DIRS = {"docs", "doc", "changelog.d", "changes", "news", "newsfragments", ".github", "changelog"}
SRC_ROOT_FILES = {"pyproject.toml", "setup.py", "setup.cfg"}


def classify_path(path: str) -> str:
    """'test' | 'doc' | 'src'. Tests: under a tests/test/testing dir, test_*.py, *_test.py, conftest.py. Docs:
    docs/changelog dirs, .md/.rst, and root-level non-code files (tox.ini, CHANGES, ...)."""
    p = PurePosixPath(path)
    name = p.name
    if any(part in TEST_DIRS for part in p.parts[:-1]) or name == "conftest.py" or \
            (name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py"))):
        return "test"
    if p.parts[0] in DOC_DIRS or p.suffix in (".md", ".rst"):
        return "doc"
    if len(p.parts) == 1 and name not in SRC_ROOT_FILES and p.suffix not in (".py", ".pyi"):
        return "doc"
    return "src"


def _diff_blocks(diff: str) -> list:
    blocks, cur = [], []
    for ln in diff.splitlines(keepends=True):
        if ln.startswith("diff --git ") and cur:
            blocks.append("".join(cur))
            cur = []
        cur.append(ln)
    if cur and cur[0].startswith("diff --git "):
        blocks.append("".join(cur))
    return blocks


def _block_path(block: str) -> str:
    m = re.match(r'^diff --git "?a/(.*?)"? "?b/(.*?)"?$', block.splitlines()[0])
    return m.group(2) if m else ""


def changed_lines(patch: str) -> int:
    return sum(1 for ln in patch.splitlines() if ln[:1] in "+-" and not ln.startswith(("+++", "---")))


def split_diff(diff: str) -> dict:
    out = {"patch": "", "test_patch": "", "src_files": [], "test_files": [], "dropped": [], "binary": False,
           "all_files": []}
    for b in _diff_blocks(diff):
        path = _block_path(b)
        out["all_files"].append(path)
        if "\nBinary files " in b or "\nGIT binary patch" in b:
            out["binary"] = True
        kind = classify_path(path)
        if kind == "test":
            out["test_patch"] += b
            out["test_files"].append(path)
        elif kind == "src":
            out["patch"] += b
            out["src_files"].append(path)
        else:
            out["dropped"].append(path)
    return out


def reject_reason(s: dict, pr_files: set | None) -> str | None:
    if s["binary"]:
        return "binary"
    if not any(f.endswith(".py") for f in s["test_files"]):
        return "no_test_change"
    if not any(f.endswith((".py", ".pyi")) for f in s["src_files"]):
        return "no_src_change"
    if pr_files is not None and set(s["all_files"]) != set(pr_files):
        return "files_mismatch"
    if changed_lines(s["patch"]) > MAX_SRC_LINES:
        return "src_too_big"
    if changed_lines(s["test_patch"]) > MAX_TEST_LINES:
        return "test_too_big"
    return None


# ------------------------------------------------------------------------------------------- known ids
@dataclass
class Known:
    ids: set = field(default_factory=set)
    fixes: set = field(default_factory=set)          # (repo, fix_commit)
    excluded_repos: set = field(default_factory=set)


def _rows(path: Path):
    if not Path(path).is_file():
        return []
    return [json.loads(ln) for ln in Path(path).read_text().splitlines() if ln.strip()]


def load_known(pallets: Path = PALLETS, public: Path = PUBLIC, out: Path = OUT_DIR / "tasks.jsonl") -> Known:
    k = Known(excluded_repos=set(EXCLUDED_REPOS))
    for r in _rows(public):
        k.ids.add(r["instance_id"])
        k.excluded_repos.add(r["repo"].lower())
    for r in _rows(pallets) + _rows(out):
        k.ids.add(r["instance_id"])
        if r.get("fix_commit"):
            k.fixes.add((r["repo"], r["fix_commit"]))
    return k


def check_repo_allowed(repo: str, known: Known) -> None:
    if repo.lower() in known.excluded_repos:
        raise ExcludedRepo(f"{repo} is in the competition's public set / exclusion list")


SHORT_NAME = {"httpie/cli": "httpie", "cpburnz/python-pathspec": "pathspec",   # repos whose GitHub name is not
              "rspeer/python-ftfy": "ftfy"}                                     # the package name
OWN_NAME = {"jpadilla/pyjwt": "PyJWT", "cpburnz/python-pathspec": "pathspec", "rspeer/python-ftfy": "ftfy",
            "Python-Markdown/markdown": "Markdown"}


def own_package(repo: str) -> str:
    return (REPO_CFG.get(repo) or {}).get("own") or OWN_NAME.get(repo) or repo.split("/")[-1]


_REQ_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9_.\-]*)")
_TEST_GROUP = re.compile(r"^(tests?|testing|dev|test-?deps|tests?-?requirements)$", re.I)
REQ_GLOBS = ("requirements/test*.txt", "requirements/tests*.txt", "requirements-test*.txt", "requirements_test*.txt",
             "test-requirements.txt", "test_requirements.txt", "tests/requirements*.txt", "requirements-dev.txt",
             "dev-requirements.txt", "requirements/dev*.txt")


def _norm_name(spec: str) -> str:
    m_ = _REQ_NAME.match(spec)
    return m_.group(1).lower().replace("_", "-") if m_ else ""


COMMON_TEST_DEPS = ("mock", "parameterized", "pytest-mock", "freezegun")   # cheap, plugin-safe; often only in tox/CI


def _tox_deps(root: Path) -> list:
    import configparser
    f = Path(root) / "tox.ini"
    if not f.is_file():
        return []
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        cp.read_string(f.read_text(errors="replace"))
    except configparser.Error:
        return []
    if not cp.has_option("testenv", "deps"):
        return []
    out = []
    for ln in cp.get("testenv", "deps").splitlines():
        ln = ln.split(" #")[0].strip()
        if ln and not ln.startswith(("-", "#", ".")) and not re.match(r"^[{\w,.\-}]+:\s", ln):
            out.append(ln)
    return out


def auto_deps(root: Path, own: str, common: bool = False) -> list:
    """Runtime + test requirements declared by the repo at its default-branch head: pyproject [project] dependencies,
    optional-dependencies and [dependency-groups] named test/tests/testing/dev, and requirement files (REQ_GLOBS).
    pytest and pluggy are dropped (pytest is pinned to the grader's 8.4.2) and so is the repo's own package."""
    import tomllib
    root, out = Path(root), []
    pp = root / "pyproject.toml"
    if pp.is_file():
        try:
            d = tomllib.loads(pp.read_text())
        except Exception:
            d = {}
        proj = d.get("project") or {}
        out += [x for x in proj.get("dependencies") or [] if isinstance(x, str)]
        for k, v in (proj.get("optional-dependencies") or {}).items():
            if _TEST_GROUP.match(k):
                out += [x for x in v if isinstance(x, str)]
        for k, v in (d.get("dependency-groups") or {}).items():
            if _TEST_GROUP.match(k):
                out += [x for x in v if isinstance(x, str)]
    out += _tox_deps(root)
    if common:
        out += list(COMMON_TEST_DEPS)
    for g in REQ_GLOBS:
        for f in sorted(root.glob(g)):
            for ln in f.read_text(errors="replace").splitlines():
                ln = ln.split(" #")[0].strip()
                if ln and not ln.startswith(("#", "-")):
                    out.append(ln)
    drop = {"pytest", "pluggy", own.lower().replace("_", "-")}
    seen, deps = set(), []
    for spec in out:
        n = _norm_name(spec)
        if not n or n in drop or spec in seen:
            continue
        seen.add(spec)
        deps.append(spec)
    return deps


def instance_id(repo: str, fix_commit: str) -> str:
    short = SHORT_NAME.get(repo) or repo.split("/")[-1]
    return f"{short.lower().replace('-', '_')}_{fix_commit[:7]}"


def is_duplicate(c: dict, known: Known) -> bool:
    return (c["repo"], c["fix_commit"]) in known.fixes or instance_id(c["repo"], c["fix_commit"]) in known.ids


def statement(title: str, body: str | None) -> tuple:
    text = title + "\n\n" + (body or "")
    return text, bool(statement_stats(text)["title_only"])


# ------------------------------------------------------------------------------------------- coverage steering
def candidate_tags(c: dict) -> set:
    text, title_only = statement(c["title"], c.get("body"))
    return set(_load_coverage().tags({"patch": c["patch"], "test_patch": c["test_patch"], "problem_statement": text,
                                      "statement_title_only": title_only}))


def gap_score(tags: set, gaps: set) -> float:
    return len(set(tags) & set(gaps)) + (NEG_ROUTE_BONUS if "negative_route" in tags else 0.0)


def prioritize(cands: list, gaps: set) -> list:
    """Candidates hitting the most current coverage gaps first (stable: date order inside equal scores)."""
    for c in cands:
        c["tags"] = sorted(candidate_tags(c))
        c["gap_score"] = gap_score(set(c["tags"]), gaps)
    return sorted(cands, key=lambda c: -c["gap_score"])


def repo_budget(repo: str, out: Path, global_left: int, cap: int) -> int:
    have = sum(1 for r in _rows(out) if r["repo"] == repo)
    return max(0, min(global_left, cap - have))


def tags_added(out: Path, before_ids: set) -> dict:
    tagger = _load_coverage().tags
    c = Counter()
    for r in _rows(out):
        if r["instance_id"] not in before_ids:
            c.update(tagger(r))
    return dict(c)


def coverage_gaps(out_json: Path, min_share: float = 0.08) -> set:
    cmd = [sys.executable, str(ROOT / "train" / "task_coverage.py"), *[str(p) for p in COVERAGE_SRCS if p.is_file()],
           "--out", str(out_json), "--min-share", str(min_share)]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return set(json.loads(Path(out_json).read_text())["gaps"])


# ------------------------------------------------------------------------------------------- disk + batches
def free_gb(path=None) -> float:
    """Free GB on `path`; by default the macOS data volume (DISK_PATH), or the repo's filesystem where that volume does
    not exist (Linux)."""
    if path is None:
        path = DISK_PATH if Path(DISK_PATH).exists() else ROOT
    return shutil.disk_usage(path).free / 1e9


def require_disk(path, floor_gb: float = DISK_FLOOR_GB, free_fn=free_gb) -> float:
    free = free_fn(DISK_PATH if Path(DISK_PATH).exists() else path)
    if free < floor_gb:
        raise DiskFloor(f"free {free:.1f} GB < floor {floor_gb} GB")
    return free


@contextlib.contextmanager
def batch_dir(root: Path, name: str):
    d = Path(root) / name
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ------------------------------------------------------------------------------------------- junit + verdict
_ADDR = re.compile(r"0x[0-9a-fA-F]{6,}")          # object reprs in parametrize ids differ per process


def parse_junit(xml: str, targets: list) -> dict:
    """{nodeid: passed|failed|error|skipped}. classname 'tests.test_x.TestC' -> 'tests/test_x.py::TestC::name'."""
    out = {}
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return out
    mods = sorted(((t[:-3].replace("/", "."), t) for t in targets if t.endswith(".py")), key=lambda x: -len(x[0]))
    for tc in root.iter("testcase"):
        cls, name = tc.attrib.get("classname", ""), tc.attrib.get("name", "")
        node = None
        for mod, path in mods:
            if cls == mod or cls.startswith(mod + "."):
                rest = cls[len(mod) + 1:]
                node = "::".join([path] + (rest.split(".") if rest else []) + [name])
                break
        if node is None:
            node = f"{cls}::{name}" if cls else name
        node = _ADDR.sub("0x?", node)
        if tc.find("failure") is not None:
            o = "failed"
        elif tc.find("error") is not None:
            o = "error"
        elif tc.find("skipped") is not None:
            o = "skipped"
        else:
            o = "passed"
        if out.get(node) in ("failed", "error"):      # a teardown error after a pass is a second testcase row
            continue
        out[node] = o
    return out


def _passed(run: dict) -> set:
    return {k for k, v in run["outcomes"].items() if v == "passed"}


def volatile_re(today: str) -> re.Pattern:
    """Node ids embedding the run's date (any common order/separator) are wall-clock parametrize ids."""
    y, mo, d = today.split("-")
    forms = [f"{y}{s}{mo}{s}{d}" for s in "-/."] + [f"{mo}{s}{d}{s}{y}" for s in "-/."] + \
            [f"{d}{s}{mo}{s}{y}" for s in "-/."]
    return re.compile("|".join(re.escape(f) for f in forms))


def judge(base: dict, gold1: dict, gold2: dict | None, today: str | None = None) -> dict:
    v = {"valid": False, "reason": None, "FAIL_TO_PASS": [], "PASS_TO_PASS": [], "base": base,
         "gold": [g for g in (gold1, gold2) if g]}

    def gold_reason(g):
        if g["timed_out"]:
            return "gold_timeout"
        if g["rc"] == 5:
            return "gold_no_tests"
        if g["rc"] != 0:
            return "gold_fails"
        return None if _passed(g) else "gold_no_tests"

    r1 = gold_reason(gold1)
    if r1:
        v["reason"] = r1
        return v
    r2 = gold_reason(gold2) if gold2 else "gold_flaky"
    if r2:
        v["reason"] = "gold_flaky" if r2 == "gold_fails" else r2
        return v
    vol = volatile_re(today or time.strftime("%Y-%m-%d", time.gmtime()))
    if {n for n in _passed(gold1) if not vol.search(n)} != {n for n in _passed(gold2) if not vol.search(n)}:
        v["reason"] = "gold_flaky"
        return v
    f2p = sorted(n for n in _passed(gold1) - _passed(base) if not vol.search(n))
    p2p = sorted(n for n in _passed(gold1) & _passed(base) if not vol.search(n))
    v["FAIL_TO_PASS"], v["PASS_TO_PASS"] = f2p, p2p
    if not f2p:
        v["reason"] = "no_fail_to_pass"
    elif max(gold1["secs"], gold2["secs"]) > MARGIN_S:
        v["reason"] = "gold_slow"
    elif not (gold1.get("harness_junit_ok") and gold2.get("harness_junit_ok")):
        v["reason"] = "harness_junit_reject"
    else:
        v["valid"], v["reason"] = True, "valid"
    return v


def make_row(c: dict, verdict: dict, env: dict) -> dict:
    text, title_only = statement(c["title"], c.get("body"))
    base, gold = verdict["base"], verdict["gold"]
    row = {
        "instance_id": instance_id(c["repo"], c["fix_commit"]), "repo": c["repo"], "base_commit": c["base_commit"],
        "fix_commit": c["fix_commit"], "pr_number": c["pr_number"], "created_at": c["created_at"],
        "merged_at": c["merged_at"], "problem_statement": text, "statement_title_only": title_only, "hints_text": "",
        "patch": c["patch"], "test_patch": c["test_patch"], "test_files": c["test_files"],
        "FAIL_TO_PASS": verdict["FAIL_TO_PASS"], "PASS_TO_PASS": verdict["PASS_TO_PASS"],
        "env": {"python": env["python"], "deps": env["deps"], "env_id": env["env_id"]},
        "validation": {"os": sys.platform, "base_rc": base["rc"], "gold_rc": [g["rc"] for g in gold],
                       "gold_secs": [round(g["secs"], 1) for g in gold], "base_secs": round(base["secs"], 1),
                       "harness_junit_ok": all(g.get("harness_junit_ok") for g in gold),
                       "prep": verdict.get("prep") or [],
                       "validated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
    }
    return {k: row[k] for k in SCHEMA_KEYS}


def append_rows(path: Path, rows: list, known: Known) -> int:
    n = 0
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as fh:
        for r in rows:
            if r["instance_id"] in known.ids or (r["repo"], r["fix_commit"]) in known.fixes:
                continue
            known.ids.add(r["instance_id"])
            known.fixes.add((r["repo"], r["fix_commit"]))
            fh.write(json.dumps(r) + "\n")
            n += 1
    return n


def run_batches(cands: list, validate_batch, *, out_path: Path, scratch: Path, known: Known, batch_size: int = 30,
                floor_gb: float = DISK_FLOOR_GB, free_fn=free_gb, target: int | None = None,
                rejects_path: Path | None = None, log=print) -> dict:
    """validate_batch(batch, batch_dir) -> [(cand, verdict, env)]. Stops at the disk floor or the target."""
    stats = {"batches": 0, "validated": 0, "reasons": Counter(), "stopped": None, "free_gb": []}
    todo = [c for c in cands if not is_duplicate(c, known)]
    stats["duplicates"] = len(cands) - len(todo)
    for i in range(0, len(todo), batch_size):
        if target is not None and stats["validated"] >= target:
            stats["stopped"] = "target"
            break
        try:
            stats["free_gb"].append(round(require_disk(scratch, floor_gb, free_fn), 1))
        except DiskFloor as e:
            log(f"heldout: stop: {e}")
            stats["stopped"] = "disk_floor"
            break
        batch = todo[i:i + batch_size]
        with batch_dir(scratch, f"batch{stats['batches']}") as bdir:
            results = validate_batch(batch, bdir)
        stats["batches"] += 1
        rows, rej = [], []
        for c, v, env in results:
            stats["reasons"][v["reason"]] += 1
            if v["valid"]:
                rows.append(make_row(c, v, env))
            else:
                rej.append({"instance_id": instance_id(c["repo"], c["fix_commit"]), "repo": c["repo"],
                            "pr_number": c["pr_number"], "reason": v["reason"], "detail": v.get("detail")})
        if target is not None:
            rows = rows[:max(0, target - stats["validated"])]
        stats["validated"] += append_rows(out_path, rows, known)
        if rejects_path is not None and rej:
            with open(rejects_path, "a") as fh:
                fh.writelines(json.dumps(r) + "\n" for r in rej)
        log(f"heldout: batch {stats['batches']}: {len(rows)}/{len(results)} valid, total {stats['validated']}, "
            f"reasons {dict(stats['reasons'])}")
    if stats["stopped"] is None:
        stats["stopped"] = "target" if target is not None and stats["validated"] >= target else "exhausted"
    stats["reasons"] = dict(stats["reasons"])
    return stats


# ------------------------------------------------------------------------------------------- gh
def gh_json(args: list, runner=subprocess.run, tries: int = 3):
    """gh ... --json; RateLimited on any rate-limit message (never retried); a 5xx is retried tries-1 times."""
    for attempt in range(tries):
        p = runner(["gh", *args], capture_output=True, text=True)
        err = (p.stderr or "") + ("" if p.returncode == 0 else p.stdout or "")
        if re.search(r"rate limit|abuse detection|secondary rate", err, re.I):
            raise RateLimited(err.strip()[-300:])
        if p.returncode == 0:
            return json.loads(p.stdout)
        if not re.search(r"HTTP 50[0234]|Bad Gateway|timed out|timeout", err, re.I) or attempt == tries - 1:
            break
        time.sleep(30 * (attempt + 1))
    raise RuntimeError(f"gh {' '.join(args[:3])}: {err.strip()[-300:]}")


def list_merged_prs(repo: str, limit: int = 300, since: str = "2021-01-01", runner=subprocess.run) -> list:
    rows = gh_json(["pr", "list", "-R", repo, "--state", "merged", "--limit", str(min(limit, 1000)), "--json",
                    "number,title,body,mergedAt,createdAt,mergeCommit,baseRefName,files"], runner=runner)
    out = []
    for r in rows:
        if (r.get("mergedAt") or "") < since or not r.get("mergeCommit"):
            continue
        files = r.get("files") or []
        out.append({"number": r["number"], "title": r["title"], "body": r.get("body") or "",
                    "merged_at": r["mergedAt"], "created_at": r["createdAt"], "merge_commit": r["mergeCommit"]["oid"],
                    "base_ref": r.get("baseRefName"),
                    "files": {f["path"] for f in files} if len(files) < 100 else None})
    return out


def graphql_remaining(runner=subprocess.run) -> int:
    d = gh_json(["api", "rate_limit"], runner=runner)
    return int(d["resources"]["graphql"]["remaining"])


# ------------------------------------------------------------------------------------------- git + pytest
def git(cwd, *args, timeout=300, check=True) -> subprocess.CompletedProcess:
    env = {**os.environ, **HERMETIC_GIT}
    p = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=timeout, env=env,
                       errors="surrogateescape")
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])}: {p.stderr.strip()[-300:]}")
    return p


def init_submodules(ws: Path, reference: Path | None = None) -> None:
    """git submodule update --init for every submodule of ws (no-op without .gitmodules). With reference=<clone>, objects
    come from the clone's own initialised submodule (<clone>/.git/modules/<name>), so a worktree needs no network."""
    if not (Path(ws) / ".gitmodules").is_file():
        return
    cfg = git(ws, "config", "-f", ".gitmodules", "--get-regexp", r"^submodule\..*\.path$", check=False).stdout
    for ln in cfg.splitlines():
        key, _, path = ln.partition(" ")
        name = key[len("submodule."):-len(".path")]
        extra = []
        if reference is not None:
            ref = Path(reference) / ".git" / "modules" / name
            if ref.is_dir():
                extra = ["--reference", str(ref)]
        git(ws, "-c", "protocol.file.allow=always", "submodule", "update", "--init", "-q", *extra, "--", path,
            timeout=600)


def build_candidates(repo: str, clone: Path, prs: list, log=print) -> tuple:
    cands, why = [], Counter()
    for pr in prs:
        sha = pr["merge_commit"]
        if git(clone, "cat-file", "-e", f"{sha}^{{commit}}", check=False).returncode != 0:
            why["not_in_clone"] += 1
            continue
        parents = git(clone, "rev-list", "--parents", "-n", "1", sha).stdout.split()[1:]
        if not parents:
            why["root_commit"] += 1
            continue
        base = parents[0]
        diff = git(clone, "diff", "--no-color", "--no-ext-diff", "--full-index", "--no-renames", base, sha).stdout
        s = split_diff(diff)
        r = reject_reason(s, pr["files"])
        if r:
            why[r] += 1
            continue
        cands.append({"repo": repo, "base_commit": base, "fix_commit": sha, "pr_number": pr["number"],
                      "created_at": pr["created_at"], "merged_at": pr["merged_at"], "title": pr["title"],
                      "body": pr["body"], "patch": s["patch"], "test_patch": s["test_patch"],
                      "test_files": s["test_files"]})
        why["candidate"] += 1
    cands.sort(key=lambda c: c["merged_at"])
    return cands, dict(why)


def pytest_cmd(venv: Path, targets: list, junit: Path) -> str:
    tfs = " ".join(shlex.quote(t) for t in targets) or "."
    py = shlex.quote(str(Path(venv) / "bin" / "python"))
    return (f"PYTHONSAFEPATH=1 PYTHONNOUSERSITE=1 {py} -s -m pytest {tfs} --junitxml={shlex.quote(str(junit))} "
            f"-p no:anyio -o timeout=0 -o python_classes=\"Test* *Test\" -q -p no:cacheprovider")


_VF = None


def _junit_ok(xml: str, test_patch: str) -> bool:
    global _VF
    if _VF is None:
        try:
            from swegemma.harness import verification as vf
            _VF = vf
        except Exception:          # no harness installed: count it as unchecked (False), never as passed
            _VF = False
    if not _VF:
        return False
    return bool(_VF._validate_junit_xml(xml, test_patch=test_patch)[0])


def run_pytest(ws: Path, venv: Path, targets: list, test_patch: str, timeout: float, tag: str) -> dict:
    junit = ws.parent / f"{ws.name}.{tag}.xml"
    junit.unlink(missing_ok=True)
    (ws / "pytest.ini").write_text(HARNESS_PYTEST_INI)
    env = {"PATH": f"{Path(venv) / 'bin'}:/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(ws.parent),
           "VIRTUAL_ENV": str(venv), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TMPDIR": str(ws.parent),
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0", "TZ": "UTC", **HERMETIC_GIT,
           "PYTHONPATH": os.pathsep.join([str(ws)] + ([str(ws / "src")] if (ws / "src").is_dir() else []))}
    t0 = time.monotonic()
    timed_out = False
    p = subprocess.Popen(pytest_cmd(venv, targets, junit), shell=True, cwd=ws, env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, errors="replace", start_new_session=True)
    try:
        out, _ = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        with contextlib.suppress(ProcessLookupError):
            os.killpg(p.pid, 9)
        out, _ = p.communicate()
    secs = time.monotonic() - t0
    xml = junit.read_text(errors="replace") if junit.is_file() else ""
    junit.unlink(missing_ok=True)
    rc = -9 if timed_out else p.returncode
    return {"rc": rc, "outcomes": parse_junit(xml, targets), "timed_out": timed_out, "secs": secs,
            "harness_junit_ok": rc == 0 and _junit_ok(xml, test_patch), "tail": (out or "")[-400:]}


SCM_VERSION_BODY = ('__version__ = version = "0.0.0"\n__version_tuple__ = version_tuple = (0, 0, 0)\n'
                    "commit_id = __commit_id__ = None\n")


def write_scm_version_file(ws: Path) -> list:
    """Write the version module hatch-vcs / setuptools-scm would generate at `pip install -e` (gitignored, so absent
    from a checkout). Returns the paths written; never overwrites."""
    import tomllib
    pp = Path(ws) / "pyproject.toml"
    if not pp.is_file():
        return []
    try:
        d = tomllib.loads(pp.read_text())
    except Exception:
        return []
    tool = d.get("tool") or {}
    cands = [((tool.get("hatch") or {}).get("build") or {}).get("hooks", {}).get("vcs", {}).get("version-file"),
             (tool.get("setuptools_scm") or {}).get("write_to"),
             (tool.get("setuptools_scm") or {}).get("version_file")]
    out = []
    for rel in cands:
        if isinstance(rel, str) and rel.endswith(".py") and not (Path(ws) / rel).exists() \
                and (Path(ws) / rel).parent.is_dir():
            (Path(ws) / rel).write_text(SCM_VERSION_BODY)
            out.append(rel)
    return out


def _apply(ws: Path, patch: str) -> str | None:
    text = patch if patch.endswith("\n") else patch + "\n"
    for extra in ((), ("--recount",)):
        p = subprocess.run(["git", "-C", str(ws), "apply", *extra, "-"], input=text, capture_output=True, text=True,
                           env={**os.environ, **HERMETIC_GIT})
        if p.returncode == 0:
            return None
    return (p.stderr or "").strip()[-200:]


def validate_one(c: dict, *, clone: Path, venv: Path, work: Path, timeout: float = TIMEOUT_S) -> dict:
    tid = instance_id(c["repo"], c["fix_commit"])
    ws = Path(work) / tid
    Path(work).mkdir(parents=True, exist_ok=True)
    git(clone, "worktree", "add", "--detach", "-f", str(ws), c["base_commit"])
    try:
        try:
            init_submodules(ws, reference=clone)
        except Exception as e:
            return {"valid": False, "reason": "submodule_failed", "detail": str(e)[-200:]}
        targets = [t for t in c["test_files"] if t.endswith(".py") and PurePosixPath(t).name != "conftest.py"]
        targets = [t for t in targets if (ws / t).exists() or t in c["test_patch"]]
        prep = write_scm_version_file(ws)
        err = _apply(ws, c["test_patch"])
        if err:
            return {"valid": False, "reason": "test_patch_no_apply", "detail": err}
        targets = [t for t in targets if (ws / t).exists()]
        if not targets:
            return {"valid": False, "reason": "no_test_targets"}
        base = run_pytest(ws, venv, targets, c["test_patch"], timeout, "base")
        (ws / "pytest.ini").unlink(missing_ok=True)
        git(ws, "checkout", "--", "pytest.ini", check=False)
        err = _apply(ws, c["patch"])
        if err:
            return {"valid": False, "reason": "gold_no_apply", "detail": err}
        g1 = run_pytest(ws, venv, targets, c["test_patch"], timeout, "gold1")
        g2 = None
        if g1["rc"] == 0 and not g1["timed_out"]:
            g2 = run_pytest(ws, venv, targets, c["test_patch"], timeout, "gold2")
        v = judge(base, g1, g2)
        v["prep"] = prep
        if not v["valid"]:
            v["detail"] = (g1.get("tail") or "")[-200:]
            if v["reason"] == "gold_flaky" and g2:
                diff = sorted(_passed(g1) ^ _passed(g2))
                v["detail"] = f"{len(diff)} nodes differ: {diff[:3]}"[:300]
        for r in (base, g1, g2):
            if r:
                r.pop("tail", None)
        return v
    finally:
        shutil.rmtree(ws, ignore_errors=True)
        git(clone, "worktree", "prune", check=False)


REPO_EXTRA = {   # test deps that auto_deps cannot see (CI-only installs), added on top of the auto-detected ones
    "jd/tenacity": ["six", "typeguard", "tornado"],
    "scrapinghub/dateparser": ["parameterized", "mock", "regex", "tzlocal", "pytz", "python-dateutil"],
}


def venv_deps(repo: str, clone: Path | None) -> tuple:
    if repo in REPO_CFG:
        return REPO_CFG[repo]["own"], list(REPO_CFG[repo]["deps"])
    own = own_package(repo)
    deps = auto_deps(clone, own, common=True) if clone else list(COMMON_TEST_DEPS)
    return own, deps + [d for d in REPO_EXTRA.get(repo, []) if d not in deps]


def build_venv(dest: Path, repo: str, python: str = "3.12", clone: Path | None = None) -> dict:
    own, deps = venv_deps(repo, clone)
    cfg = {"own": own, "deps": deps}
    env = {**os.environ, "VIRTUAL_ENV": str(dest)}
    subprocess.run(["uv", "venv", "-q", "--clear", "-p", python, str(dest)], check=True, capture_output=True)
    pkgs = [PYTEST_PIN, *cfg["deps"]] + ([cfg["own"]] if cfg.get("own") else [])
    p = subprocess.run(["uv", "pip", "install", "-q", *pkgs], env=env, capture_output=True, text=True)
    if p.returncode != 0:              # an optional dep with no wheel for this python: drop deps one by one
        keep = [PYTEST_PIN] + ([cfg["own"]] if cfg.get("own") else [])
        subprocess.run(["uv", "pip", "install", "-q", *keep], env=env, check=True, capture_output=True)
        for d in cfg["deps"]:
            subprocess.run(["uv", "pip", "install", "-q", d], env=env, capture_output=True)
    freeze = subprocess.run(["uv", "pip", "freeze"], env=env, capture_output=True, text=True).stdout.split()
    ver = subprocess.run([str(dest / "bin" / "python"), "-c", "import platform; print(platform.python_version())"],
                         capture_output=True, text=True).stdout.strip()
    return {"python": ver, "deps": freeze}


def make_validate_batch(repo: str, clone: Path, jobs: int, timeout: float, log=print):
    def validate_batch(batch: list, bdir: Path) -> list:
        venv = bdir / "venv"
        env = build_venv(venv, repo, clone=clone)
        env["env_id"] = f"{repo.split('/')[-1]}-{batch[0]['merged_at'][:10]}"
        out = []

        def one(c):
            try:
                return c, validate_one(c, clone=clone, venv=venv, work=bdir / "wt", timeout=timeout)
            except Exception as e:      # one broken task never sinks the batch
                return c, {"valid": False, "reason": "harness_error", "detail": f"{type(e).__name__}: {e}"[:300]}

        with cf.ThreadPoolExecutor(max(1, jobs)) as ex:
            for c, v in ex.map(one, batch):
                out.append((c, v, env))
        return out
    return validate_batch


# ------------------------------------------------------------------------------------------- progress
def write_progress(path: Path, records: list, out_path: Path) -> None:
    rows = _rows(out_path)
    per = Counter(r["repo"] for r in rows)
    to = Counter(r["repo"] for r in rows if r["statement_title_only"])
    lines = ["# heldout1k mining progress", "",
             f"Validated new tasks: **{len(rows)}** (data/heldout1k/tasks.jsonl), title-only statements "
             f"{sum(to.values())}/{len(rows)}. Disk free now {free_gb():.1f} GB. Updated {time.strftime('%Y-%m-%d %H:%M %Z')}.",
             "", "## Totals per repo", "", "| repo | validated | title-only |", "|---|---|---|"]
    lines += [f"| {r} | {n} | {to[r]}/{n} |" for r, n in sorted(per.items(), key=lambda x: -x[1])]
    lines += ["", "## Rounds", "",
              "| repo | round | PRs listed | candidates | validated | free GB (start/end) | stopped | rejections | tags added |",
              "|---|---|---|---|---|---|---|---|---|"]
    for r in records:
        rej = ", ".join(f"{k} {v}" for k, v in sorted(r.get("reasons", {}).items(), key=lambda x: -x[1])
                        if k != "valid")[:200]
        fg = r.get("free_gb") or []
        lines.append(f"| {r['repo']} | {r.get('round', 1)} | {r.get('prs', 0)} | {r.get('candidates', 0)} | "
                     f"{r.get('validated', 0)} | {fg[0] if fg else '-'} / {r.get('free_end', '-')} | "
                     f"{r.get('stopped')} | {rej} | "
                     + ", ".join(f"{k} {v}" for k, v in sorted((r.get("tags_added") or {}).items(),
                                                              key=lambda x: (-x[1], x[0])))[:240] + " |")
    Path(path).write_text("\n".join(lines) + "\n")


def mine_repo(repo: str, a, known: Known, log=print) -> dict:
    check_repo_allowed(repo, known)
    rec = {"repo": repo}
    if graphql_remaining() < 300:
        raise RateLimited("graphql budget below 300")
    prs = list_merged_prs(repo, a.limit, a.since)
    rec["prs"] = len(prs)
    require_disk(SCRATCH, a.floor_gb)
    clone = SCRATCH / "clones" / repo.replace("/", "__")
    shutil.rmtree(clone, ignore_errors=True)
    clone.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(["git", "clone", "-q", "--no-tags", f"https://github.com/{repo}.git", str(clone)], check=True,
                       env={**os.environ, **HERMETIC_GIT})
        with contextlib.suppress(Exception):
            init_submodules(clone)
        cands, why = build_candidates(repo, clone, prs, log)
        rec["candidates"], rec["prefilter"] = len(cands), why
        budget = repo_budget(repo, a.out, a.target_left, a.cap)
        if a.gaps is not None:
            cands = prioritize(cands, a.gaps)
            rec["candidates_hitting_gaps"] = sum(1 for c in cands if c["gap_score"] >= 1)
        log(f"heldout: {repo}: {len(prs)} PRs since {a.since}, {len(cands)} candidates "
            f"({rec.get('candidates_hitting_gaps', '-')} hit gaps), budget {budget}, prefilter {why}")
        before = {r["instance_id"] for r in _rows(a.out)}
        stats = {"validated": 0, "reasons": {}, "stopped": "repo_cap", "free_gb": [], "duplicates": 0}
        if budget > 0:
            stats = run_batches(cands, make_validate_batch(repo, clone, a.j, a.timeout, log), out_path=a.out,
                                scratch=SCRATCH, known=known, batch_size=a.batch, floor_gb=a.floor_gb,
                                target=budget, rejects_path=a.out.parent / "rejects.jsonl", log=log)
        rec["tags_added"] = tags_added(a.out, before)
    finally:
        shutil.rmtree(clone, ignore_errors=True)
    rec.update(validated=stats["validated"], reasons=stats["reasons"], stopped=stats["stopped"],
               free_gb=stats["free_gb"], duplicates=stats["duplicates"], free_end=round(free_gb(), 1))
    rec["round"] = a.round
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", nargs="+", required=True)
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--since", default="2021-01-01")
    ap.add_argument("--batch", type=int, default=30)
    ap.add_argument("-j", type=int, default=4)
    ap.add_argument("--timeout", type=float, default=TIMEOUT_S)
    ap.add_argument("--target", type=int, default=525, help="stop when this many NEW tasks exist in --out")
    ap.add_argument("--floor-gb", type=float, default=DISK_FLOOR_GB)
    ap.add_argument("--out", type=Path, default=OUT_DIR / "tasks.jsonl")
    ap.add_argument("--round", type=int, default=1)
    ap.add_argument("--cap", type=int, default=10**6, help="max tasks per repo in --out")
    ap.add_argument("--steer", type=float, default=None, metavar="MIN_SHARE",
                    help="coverage steering: gaps = dimensions under this share (train/task_coverage.py), "
                         "refreshed into data/heldout1k/coverage_now.json after every repo")
    a = ap.parse_args()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    progress_json = a.out.parent / "progress.json"
    records = json.loads(progress_json.read_text()) if progress_json.is_file() else []
    cov_json = a.out.parent / "coverage_now.json"
    a.gaps = coverage_gaps(cov_json, a.steer) if a.steer is not None else None
    if a.gaps is not None:
        print(f"heldout: gaps {sorted(a.gaps)}", flush=True)
    for repo in a.repo:
        known = load_known(out=a.out)
        have = len(_rows(a.out))
        a.target_left = a.target - have
        if a.target_left <= 0:
            print(f"heldout: target {a.target} reached ({have})")
            break
        try:
            rec = mine_repo(repo, a, known)
        except (DiskFloor, RateLimited) as e:
            print(f"heldout: STOP {type(e).__name__}: {e}")
            records.append({"repo": repo, "round": a.round, "stopped": type(e).__name__,
                            "free_end": round(free_gb(), 1)})
            progress_json.write_text(json.dumps(records, indent=1) + "\n")
            write_progress(a.out.parent / "PROGRESS.md", records, a.out)
            return 3
        except ExcludedRepo as e:
            print(f"heldout: skip {e}")
            continue
        except RuntimeError as e:          # one repo's gh/git failure never ends the round
            print(f"heldout: {repo}: ERROR {e}", flush=True)
            records.append({"repo": repo, "round": a.round, "stopped": f"error: {str(e)[:80]}",
                            "free_end": round(free_gb(), 1)})
            continue
        records = [r for r in records if (r["repo"], r.get("round", 1)) != (repo, a.round)] + [rec]
        progress_json.write_text(json.dumps(records, indent=1) + "\n")
        write_progress(a.out.parent / "PROGRESS.md", records, a.out)
        print(f"heldout: {repo}: {rec['validated']} validated; total {len(_rows(a.out))}", flush=True)
        if a.steer is not None:
            a.gaps = coverage_gaps(cov_json, a.steer)
            print(f"heldout: gaps now {sorted(a.gaps)}", flush=True)
        if rec["stopped"] == "disk_floor":
            return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
