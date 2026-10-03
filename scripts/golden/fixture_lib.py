"""Golden-eval fixtures, component (a) of docs/eval/GOLDEN_EVALS_SPEC.md v1.1: the DEV/HOLDOUT split (section 2) and the
golden data (section 4): golden plan with its leak rules, golden repro, wrong patch, tree replay steps, gradability,
hidden nodes and the per-suite start clocks. scripts/golden/build_fixtures.py drives it; tests/test_golden_fixtures.py
tests it.

Two layers:
- pure functions (split, patch parsing, plan, leak rules, ATIF repro extraction, t0, replay-step construction, wrong-patch
  static rules): stdlib only, no subprocess, no harness import; unit-tested on synthetic data.
- exec functions (`x_*`): everything that runs code in a task tree, through tests/v10_support/tasks.py (fresh clones of
  the harness-exact base workspace, the harness apply pipeline, mini_verify, hidden_outcomes, the bundle helpers from a
  temp copy). tasks.py calls pytest.skip for a missing snapshot, venv or helper; `guarded` turns that (and any crash)
  into a recorded reason, and callers check has_snapshot / kpar_ok first (spec gotcha 12).

scripts/golden is not a package: this module inserts its own directory, ROOT/tests and ROOT/scripts into sys.path and
imports tasks.py and replay_l4.py by name. It never edits a shared file and never runs anything inside submissions/.
"""
from __future__ import annotations

import ast
import base64
import builtins
import contextlib
import dataclasses
import hashlib
import importlib
import json
import keyword
import math
import os
import re
import shlex
import statistics
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (HERE, ROOT / "tests", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import replay_l4 as R  # noqa: E402  (stdlib only: is_protected, scratch_files, FOOT_T)

# ------------------------------------------------------------------------------------------------------ constants
BUILDER_VERSION = "golden-fixtures-1.0"
SPLIT_SCHEMA, FIXTURES_SCHEMA, MANIFEST_SCHEMA, CASE_SCHEMA = (
    "golden-split-v1", "golden-fixtures-v1", "golden-manifest-v1", "golden-case-v1")
SPLIT_SEED = "golden-v1"
HOLDOUT_FRAC = 0.25
SPLIT_RULE = "floor(n*0.25+0.5) by sha256 order"

DATA = ROOT / "data"
IDS_FILE = DATA / "kaggle_valid_ids.txt"
TASKS_FILE = DATA / "tasks.jsonl"
CATALOG_FILE = ROOT / "research" / "task_catalog.json"
RACE2_DIR = ROOT / "eval" / "race2" / "eval" / "runs"
RACE2_RUNS = ("r2_v10_1", "r2_v9_eog_1")
REPRO_RUN = "r2_v10_1"
KAGGLE_DIR = ROOT / "eval" / "kaggle"
# 4.3 candidate order: (source label, kind, location)
WRONG_SOURCES = (("r2_v10_1", "patch_dir", RACE2_DIR / "r2_v10_1" / "patches"),
                 ("r2_v9_eog_1", "patch_dir", RACE2_DIR / "r2_v9_eog_1" / "patches"),
                 ("g4-l4-v9-eog", "results", KAGGLE_DIR / "g4-l4-v9-eog" / "results.jsonl"),
                 ("g4-l4-v4", "results", KAGGLE_DIR / "g4-l4-v4" / "results.jsonl"))
GOLDEN = ROOT / "eval" / "golden"
SPLIT_FILE = GOLDEN / "split.json"
FIXTURES_DIR = GOLDEN / "fixtures"
TASK_FIXTURES_FILE = FIXTURES_DIR / "task_fixtures.json"
OVERRIDES_FILE = FIXTURES_DIR / "plan_overrides.json"
MANIFEST_FILE = FIXTURES_DIR / "MANIFEST.json"
DATASETS_DIR = GOLDEN / "datasets"
BUNDLE_SCRIPTS = ROOT / "submissions" / "v10" / "skills" / "swe-tools" / "scripts"
CACHE_DIR = Path(os.environ.get("G4_GOLDEN_CACHE") or Path.home() / ".cache" / "g4" / "golden")

SUITES = ("L", "F", "V")
STAGE_OF = {"L": "locator", "F": "fixer", "V": "verifier"}
VARIANTS = ("gold", "wrong", "empty")
PRE_S = 150                  # 5.4 step 4: real seconds allowed for the scripted pre-stages
MV_TIMEOUT = 180             # 4.5 / gotcha 21: the grader's command_timeout_seconds, never mini_verify's default 20
# pre_hidden_nodes_pass uses tasks.hidden_outcomes with ITS defaults (40 s batch, 10 s per node), exactly the call
# component (b) makes for hidden_nodes_pass (scripts/golden/checks.py), so v_not_worse compares like with like.
HIDDEN_DEFAULTS = "tasks.hidden_outcomes defaults"
REPRO_TIMEOUT = 20           # 4.2
PLAN_WORDS_MAX, CAUSE_WORDS, CAUSE_WORDS_SHORT, FILES_MAX = 120, 35, 20, 6
LEAK_MIN = 12
REWRITTEN = ("/tmp", "/workspace", "/wheels", "/usr/local/bin")   # the subprocess sandbox rewrites these in COMMAND TEXT
B64_CHUNK = 60000            # one run_command argument stays far below Linux's 128 KiB MAX_ARG_STRLEN
B64_FILE = ".git/_golden_tree.b64"
# Mirror of tests/test_v10_flow.py KNOWN_FLAKY (keys); tests/test_golden_fixtures.py asserts the two agree.
KNOWN_FLAKY = frozenset({"tests/test_console.py::test_brokenpipeerror"})
HELPER = "python3 /tmp/swe/"
EDIT = HELPER + "edit.py"


# ------------------------------------------------------------------------------------------------------ io helpers
def dumps(obj) -> str:
    """The committed-file form: sorted keys, 1-space indent, ASCII, trailing newline (byte-deterministic)."""
    return json.dumps(obj, sort_keys=True, indent=1) + "\n"


def canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def sha_text(text) -> str:
    data = text if isinstance(text, bytes) else str(text).encode("utf-8", "surrogateescape")
    return hashlib.sha256(data).hexdigest()


def sha_obj(obj) -> str:
    return sha_text(canon(obj))


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha_tree(root: Path, pattern: str = "*") -> str:
    """sha256 over sorted relative paths and bytes (no mtimes, so a fresh checkout hashes the same)."""
    h = hashlib.sha256()
    for p in sorted(x for x in Path(root).rglob(pattern) if x.is_file() and "__pycache__" not in x.parts
                    and not x.name.endswith(".pyc")):
        h.update(p.relative_to(root).as_posix().encode() + b"\0")
        h.update(sha_file(p).encode() + b"\n")
    return h.hexdigest()


def rel(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def load_ids(path: Path = IDS_FILE) -> list:
    return Path(path).read_text().split()


def load_rows(path: Path = TASKS_FILE) -> dict:
    rows = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                rows[r["instance_id"]] = r
    return rows


def load_catalog(path: Path = CATALOG_FILE) -> dict:
    data = json.loads(Path(path).read_text())
    return {r["task"]: r for r in data} if isinstance(data, list) else dict(data)


def repo_short(repo: str) -> str:
    return repo.split("/")[-1]


_TMP_PATH = re.compile(r"(/private)?/(tmp|var/folders)/[^\s'\"]*")


def clean_why(text, limit: int = 300, tail: bool = False) -> str:
    """A reason string safe to commit: no timings, no absolute temp or cache paths, one line, bounded (the first
    `limit` characters, or the last ones with tail=True). Clean first, cut second: a cut path cannot be cleaned."""
    if text is None:
        return ""
    s = str(text)
    s = s.replace(str(ROOT), "<repo>").replace(str(Path.home()), "~")
    s = re.sub(r"[^\s'\"]*g4/work/[^\s'\"/]+", "<work>", s)
    s = _TMP_PATH.sub("<tmp>", s)
    s = re.sub(r"\bin \d+(\.\d+)?s\b", "", s)
    s = re.sub(r"\(\d+:\d\d:\d\d\)", "", s)
    s = " ".join(s.split())
    return s[-limit:] if tail else s[:limit]


# ------------------------------------------------------------------------------------------------------ split (2)
def holdout_k(n: int) -> int:
    return math.floor(n * HOLDOUT_FRAC + 0.5)


def order_key(tid: str, seed: str = SPLIT_SEED) -> str:
    return hashlib.sha256(f"{seed}:{tid}".encode()).hexdigest()


def race2_resolved(run_dir: Path) -> dict:
    out = {}
    with open(Path(run_dir) / "task_results.jsonl") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                out[r["instance_id"]] = bool(r.get("resolved"))
    return out


def race2_label(tid: str, runs: list) -> str:
    n = sum(1 for r in runs if r.get(tid))
    return "both" if n == len(runs) and n else ("one" if n else "none")


def compute_split(ids: list, repo_of: dict, label_of: dict, seed: str = SPLIT_SEED) -> tuple:
    """-> (strata {stratum: {n, holdout, dev}}, tasks {tid: {split, repo, race2}}). Pure: sha order, no RNG."""
    groups: dict = {}
    for tid in ids:
        groups.setdefault(f"{repo_of[tid]}/{label_of[tid]}", []).append(tid)
    strata, tasks = {}, {}
    for name in sorted(groups):
        order = sorted(groups[name], key=lambda t: (order_key(t, seed), t))
        k = holdout_k(len(order))
        strata[name] = {"n": len(order), "holdout": order[:k], "dev": order[k:]}
        repo, label = name.split("/")
        for i, tid in enumerate(order):
            tasks[tid] = {"split": "holdout" if i < k else "dev", "repo": repo, "race2": label}
    return strata, tasks


def split_inputs() -> dict:
    paths = [IDS_FILE, TASKS_FILE] + [RACE2_DIR / r / "task_results.jsonl" for r in RACE2_RUNS]
    return {rel(p): sha_file(p) for p in paths}


def build_split() -> dict:
    ids = load_ids()
    rows = load_rows()
    runs = [race2_resolved(RACE2_DIR / r) for r in RACE2_RUNS]
    strata, tasks = compute_split(ids, {t: repo_short(rows[t]["repo"]) for t in ids},
                                  {t: race2_label(t, runs) for t in ids})
    return {"schema": SPLIT_SCHEMA, "seed": SPLIT_SEED, "holdout_frac": HOLDOUT_FRAC, "rule": SPLIT_RULE,
            "inputs": split_inputs(), "strata": strata, "tasks": tasks}


# ------------------------------------------------------------------------------------------------------ patches
@dataclasses.dataclass
class Section:
    """One file section of a diff: its raw text and what edit.py cannot express."""
    path: str
    old_path: str
    text: str
    new: bool = False
    deleted: bool = False
    rename: bool = False
    mode: bool = False
    binary: bool = False
    hunks: int = 0


_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_GIT_HDR = re.compile(r'^diff --git "?a/(.*?)"? "?b/(.*?)"?$')


def _split_keep(text: str) -> list:
    parts = text.split("\n")
    out = [p + "\n" for p in parts[:-1]]
    if parts[-1]:
        out.append(parts[-1])
    return out


def _hdr_path(raw: str) -> str:
    s = raw[4:].rstrip("\r\n").split("\t", 1)[0].strip()
    if len(s) >= 2 and s[0] == s[-1] == '"':
        s = s[1:-1]
    if s != "/dev/null" and s[:2] in ("a/", "b/"):
        s = s[2:]
    return s


def sections(text: str) -> list:
    """File sections of a unified or git diff. Git diffs split on 'diff --git' lines (so binary, mode-only and pure
    rename sections, which have no ---/+++ pair, are their own sections); plain diffs split on ---/+++ pairs. Hunk
    bodies are consumed by their header counts, so a removed '-- x' line is never taken for a header."""
    lines = _split_keep(text or "")
    starts = []
    i = 0
    git = any(ln.startswith("diff --git ") for ln in lines)
    while i < len(lines):
        ln = lines[i]
        m = _HUNK.match(ln)
        if m:                                           # skip the body by its counts
            ro = int(m.group(2)) if m.group(2) is not None else 1
            rn = int(m.group(4)) if m.group(4) is not None else 1
            i += 1
            while i < len(lines) and (ro > 0 or rn > 0):
                x = lines[i]
                k = " " if x in ("\n", "\r\n") else x[:1]
                if k == "\\":
                    pass
                elif k == " ":
                    ro, rn = ro - 1, rn - 1
                elif k == "-":
                    ro -= 1
                elif k == "+":
                    rn -= 1
                else:
                    break
                i += 1
            continue
        if git and ln.startswith("diff --git "):
            starts.append(i)
        elif not git and ln.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
            j = i                                       # attach preceding header lines (index, mode, ...)
            floor = starts[-1] + 1 if starts else 0
            while j > floor and lines[j - 1][:1] not in (" ", "+", "-", "@", "\\") and lines[j - 1].strip():
                j -= 1
            starts.append(j)
            i += 2
            continue
        i += 1
    out = []
    for n, a in enumerate(starts):
        b = starts[n + 1] if n + 1 < len(starts) else len(lines)
        chunk = lines[a:b]
        s = Section(path="", old_path="", text="".join(chunk))
        m = _GIT_HDR.match(chunk[0].rstrip("\n")) if chunk[0].startswith("diff --git ") else None
        if m:
            s.old_path, s.path = m.group(1), m.group(2)
        for k, ln in enumerate(chunk):
            if _HUNK.match(ln):
                s.hunks += 1
                continue
            if ln[:1] in (" ", "+", "-", "\\") and not ln.startswith(("--- ", "+++ ")):
                continue
            if ln.startswith("--- ") and k + 1 < len(chunk) and chunk[k + 1].startswith("+++ "):
                old, new = _hdr_path(ln), _hdr_path(chunk[k + 1])
                s.new = s.new or old == "/dev/null"
                s.deleted = s.deleted or new == "/dev/null"
                s.old_path = old if old != "/dev/null" else (s.old_path or new)
                s.path = new if new != "/dev/null" else (s.path or old)
            elif ln.startswith("new file mode"):
                s.new = True
            elif ln.startswith("deleted file mode"):
                s.deleted = True
            elif ln.startswith(("rename from", "rename to", "copy from", "copy to")):
                s.rename = True
            elif ln.startswith(("old mode", "new mode")):
                s.mode = True
            elif ln.startswith(("GIT binary patch", "Binary files")):
                s.binary = True
        if not s.old_path:
            s.old_path = s.path
        if s.old_path != s.path and not s.new and not s.deleted:
            s.rename = True
        out.append(s)
    return out


def changed_paths(text: str) -> list:
    """Every path a diff touches (new and old side), in order."""
    out = []
    for s in sections(text):
        for q in (s.path, s.old_path):
            if q and q != "/dev/null" and q not in out:
                out.append(q)
    return out


def strip_protected(text: str) -> tuple:
    """Drop every file section whose path (or old path) is protected (replay_l4.is_protected, the harness rule): the
    v10.1 submit guard marks those files assume-unchanged, so a v10.1 run could never submit them (4.3)."""
    keep, dropped = [], []
    for s in sections(text):
        if R.is_protected(s.path) or (s.old_path and R.is_protected(s.old_path)):
            dropped.append(s.path)
        else:
            keep.append(s.text)
    return "".join(keep), dropped


def _body_kind(raw: str) -> tuple:
    if raw in ("\n", "\r\n"):
        return " ", raw
    return raw[:1], raw[1:]


@dataclasses.dataclass
class Line:
    kind: str       # " ", "-", "+"
    text: str       # content with its line ending ("\n" unless the patch says there is none)
    old: int        # old-side number (context/removed), or the old line it follows (added)
    new: int        # new-side number (context/added), or the new line it follows (removed)


def hunk_lines(h) -> list:
    """A tasks.Hunk -> [Line] with old/new numbers and exact line endings ('\\ No newline' drops the previous one)."""
    o = h.old_start if h.old_len > 0 else h.old_start + 1
    n = h.new_start if h.new_len > 0 else h.new_start + 1
    out: list = []
    for raw in h.lines:
        if raw.startswith("\\"):
            if out and out[-1].text.endswith("\n"):
                out[-1].text = out[-1].text[:-1]
            continue
        kind, text = _body_kind(raw)
        if not text.endswith("\n"):
            text += "\n"                                # a patch stored without its final newline (tasks.jsonl)
        if kind == " ":
            out.append(Line(" ", text, o, n))
            o, n = o + 1, n + 1
        elif kind == "-":
            out.append(Line("-", text, o, n - 1))
            o += 1
        elif kind == "+":
            out.append(Line("+", text, o - 1, n))
            n += 1
    return out


def _T():
    """tests/v10_support/tasks.py (imports pytest; loaded on first use)."""
    from v10_support import tasks as T
    return T


def parse(text: str) -> list:
    return _T().parse_patch(text or "")


def changed_lines(text: str) -> list:
    """Sorted '+x' / '-x' body lines of every hunk (header-safe via parse_patch), plus a marker per section edit.py
    cannot express, so two patches compare equal only when they make the same line changes."""
    out = []
    for fp in parse(text):
        for h in fp.hunks:
            for ln in hunk_lines(h):
                if ln.kind in "+-":
                    out.append(ln.kind + ln.text.rstrip("\n") + ("" if ln.text.endswith("\n") else "\\ no-eol"))
    for s in sections(text):
        if s.binary:
            out.append(f"#binary {s.path}")
        if s.mode:
            out.append(f"#mode {s.path}")
        if s.rename:
            out.append(f"#rename {s.old_path} {s.path}")
        if s.deleted and not s.hunks:
            out.append(f"#delete {s.path}")
    return sorted(out)


def added_by_file(text: str) -> dict:
    out: dict = {}
    for fp in parse(text):
        if not fp.path:
            continue
        for h in fp.hunks:
            out.setdefault(fp.path, []).extend(ln.text.rstrip("\n") for ln in hunk_lines(h) if ln.kind == "+")
    return out


def old_side_by_file(text: str) -> dict:
    """{path: context + removed lines + hunk-header context}: the original-file text a no-snapshot task still has."""
    out: dict = {}
    for fp in parse(text):
        if not fp.path:
            continue
        buf = out.setdefault(fp.path, [])
        for h in fp.hunks:
            ctx = h.header.split("@@", 2)[-1].strip() if h.header.count("@@") >= 2 else ""
            if ctx:
                buf.append(ctx)
            buf.extend(ln.text.rstrip("\n") for ln in hunk_lines(h) if ln.kind in " -")
    return {k: "\n".join(v) for k, v in out.items()}


# ------------------------------------------------------------------------------------------------------ plan (4.1)
def scopes(src: str) -> list:
    """[(start, end, qualname)] for every def/class (start includes decorators), dotted like auto.auto_rich_repr."""
    out: list = []

    def walk(node, prefix):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = min([ch.lineno] + [d.lineno for d in ch.decorator_list])
                q = prefix + ch.name
                out.append((start, ch.end_lineno or ch.lineno, q))
                walk(ch, q + ".")
            else:
                walk(ch, prefix)
    walk(ast.parse(src), "")
    return out


def innermost(scope_list: list, line: int):
    best = None
    for start, end, q in scope_list:
        if start <= line <= end and (best is None or start > best[0] or (start == best[0] and end < best[1])):
            best = (start, end, q)
    return best[2] if best else None


_DEF = re.compile(r"^([ \t]*)(?:async[ \t]+)?(def|class)[ \t]+([A-Za-z_]\w*)")


def _indent(text: str) -> int:
    return len(text) - len(text.lstrip(" \t"))


def change_blocks(h) -> list:
    """Contiguous +/- runs of a hunk: [{"old": [anchor old lines], "new": [anchor new lines], "first": Line,
    "before": [Lines before the run]}]. Anchors: the removed lines, or for a pure insertion the old line after which
    it is inserted (clamped to 1); new anchors: the added lines, or for a pure deletion the new line it follows."""
    lines = hunk_lines(h)
    out, i = [], 0
    while i < len(lines):
        if lines[i].kind == " ":
            i += 1
            continue
        j = i
        while j < len(lines) and lines[j].kind != " ":
            j += 1
        run = lines[i:j]
        rem = [x.old for x in run if x.kind == "-"]
        add = [x.new for x in run if x.kind == "+"]
        out.append({"old": rem or [max(1, run[0].old)], "new": add or [max(1, run[0].new)], "first": run[0],
                    "before": lines[:i], "header": h.header})
        i = j
    return out


def _header_scope(blk) -> str | None:
    """No snapshot: the nearest def/class line in the hunk above the change with a smaller indentation, else the
    function context git printed in the hunk header (plan_basis 'hunk_header')."""
    ind = _indent(blk["first"].text)
    for ln in reversed(blk["before"]):
        m = _DEF.match(ln.text)
        if m and len(m.group(1).expandtabs()) < ind:
            return m.group(3)
    hdr = blk["header"]
    ctx = hdr.split("@@", 2)[-1] if hdr.count("@@") >= 2 else ""
    m = _DEF.match(ctx.strip())
    return m.group(3) if m else None


def plan_entries(patch: str, originals: dict) -> tuple:
    """FILES entries of the golden plan: [{"file", "start", "end", "qualname", "new_file", "nstart", "nend"}] in patch
    order, one per (gold file, innermost enclosing def/class of the changed old-side lines), and the basis ('ast' when
    every changed existing file has its original text, else 'hunk_header'). originals: {path: text or None}."""
    entries: list = []
    basis = "ast"
    for fp in parse(patch):
        if not fp.path:
            continue
        if fp.new_file:
            n = sum(1 for h in fp.hunks for ln in hunk_lines(h) if ln.kind == "+")
            entries.append({"file": fp.path, "start": 0, "end": 0, "qualname": None, "new_file": True,
                            "nstart": 1, "nend": max(1, n)})
            continue
        src = originals.get(fp.old_path or fp.path)
        sc = None
        if src is not None:
            try:
                sc = scopes(src)
            except (SyntaxError, ValueError):
                sc = None
        if sc is None:
            basis = "hunk_header"
        groups: dict = {}
        for h in fp.hunks:
            for blk in change_blocks(h):
                if sc is not None:
                    pairs = [(innermost(sc, a), a) for a in blk["old"]]
                else:
                    hq = _header_scope(blk)
                    pairs = [(hq, a) for a in blk["old"]]
                for q, a in pairs:
                    g = groups.setdefault(q, {"file": fp.path, "qualname": q, "old": [], "new": []})
                    g["old"].append(a)
                for q in dict.fromkeys(q for q, _ in pairs):
                    groups[q]["new"].extend(blk["new"])
        for g in groups.values():
            entries.append({"file": g["file"], "start": min(g["old"]), "end": max(g["old"]), "qualname": g["qualname"],
                            "new_file": False, "nstart": min(g["new"]), "nend": max(g["new"])})
    order = {}
    for e in entries:
        order.setdefault(e["file"], len(order))
    entries.sort(key=lambda e: (order[e["file"]], e["start"], e["end"]))
    return entries, basis


def entry_text(e: dict) -> str:
    if e["new_file"]:
        return f"{e['file']} (new file)"
    return f"{e['file']}:{e['start']}-{e['end']} ({e['qualname'] or 'module level'})"


def files_line(entries: list, keep: int = FILES_MAX, name_rest=()) -> str:
    """FILES: the first `keep` entries, then 'and N more places in <files>', plus ' (<qualnames>)' for `name_rest`."""
    shown = [entry_text(e) for e in entries[:keep]]
    rest = entries[keep:]
    if rest:
        files = list(dict.fromkeys(e["file"] for e in rest))
        shown.append(f"and {len(rest)} more places in {', '.join(files)}"
                     + (f" ({', '.join(name_rest)})" if name_rest else ""))
    return "FILES: " + ", ".join(shown)


def named(name: str, text: str) -> bool:
    """`name` occurs as a whole word in `text` (the l_gold_functions_named and oracle plan-check rule)."""
    return re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text) is not None


def unnamed_rest(entries: list, keep: int, plan: str) -> list:
    """Qualnames of the entries cut from FILES (after the first `keep`) whose function name the plan does not name
    anywhere. Regression 2026-09-30: the 6-entry cap dropped gold functions from the golden plan (fastapi_14306,
    fastapi_15800, rich_3061, rich_3930), so the oracle L control failed its 'functions' check."""
    out = []
    for e in entries[keep:]:
        q = e.get("qualname")
        if q and not e.get("new_file") and not named(q.rsplit(".", 1)[-1], plan) and q not in out:
            out.append(q)
    return out


def gold_functions(entries: list) -> list:
    out, seen = [], set()
    for e in entries:
        if e["new_file"] or not e["qualname"]:
            continue
        key = (e["file"], e["qualname"])
        if key not in seen:
            seen.add(key)
            out.append({"file": e["file"], "qualname": e["qualname"], "name": e["qualname"].rsplit(".", 1)[-1]})
    return out


_ABBREV = re.compile(r"(?:\b(?:e\.g|i\.e|etc|vs|cf|approx|incl|resp|Mr|Dr|No|al)|\b[A-Za-z])\.$")


def first_sentence(text: str) -> str:
    """The first sentence: up to the first '.', '!' or '?' that ends a word and is followed by whitespace and an
    upper-case letter, a quote, a bracket or a backtick (or by the end), skipping e.g./i.e./etc./single-letter dots."""
    s = " ".join((text or "").split())
    for m in re.finditer(r"[.!?](?=\s+[A-Z\"'`(\[]|\s*$)", s):
        head = s[:m.end()]
        if m.group(0) == "." and (_ABBREV.search(head) or head.endswith("..")):    # e.g. / an ellipsis
            continue
        return head
    return s


def cut_words(text: str, n: int) -> str:
    w = text.split()
    return " ".join(w[:n])


def tests_line(test_patch: str, gold_files: list, exists) -> str:
    """TESTS: the first test_patch file that exists in the original tree (a .py test file, not conftest.py); else
    tests/test_<stem of the first gold file>.py if it exists; else none. exists(path) -> bool."""
    for fp in parse(test_patch):
        if fp.path and not fp.new_file and not fp.deleted and fp.path.endswith(".py") \
                and Path(fp.path).name != "conftest.py" and exists(fp.path):
            return fp.path
    if gold_files:
        cand = f"tests/test_{Path(gold_files[0]).stem}.py"
        if exists(cand):
            return cand
    return "none"


def title_words(statement: str) -> str:
    """First non-blank line of the statement, shell-safe inside double quotes (no quotes, backticks, $ or \\), <= 80
    chars (the LOCATE step is cmd('python3 /tmp/swe/locate.py "<title_words>"'))."""
    first = next((ln for ln in (statement or "").splitlines() if ln.strip()), "")
    s = re.sub(r"[\"'`$\\]", "", first).strip()
    s = " ".join(s.split())
    return s[:80].rstrip()


def render_plan(files: str, cause: str, fix: str, reproducible: bool, tests: str) -> str:
    return "\n".join([files, f"CAUSE: {cause}", f"FIX: {fix}",
                      "REPRO: " + ("fails on original" if reproducible else "none"), f"TESTS: {tests}"])


def plan_words(plan: str) -> int:
    return len(plan.split())


def make_plan(entries: list, root_cause: str, fix: str, reproducible: bool, tests: str, override: dict | None = None):
    """-> (plan, info). CAUSE = first sentence of root_cause cut to 35 words (20 when the plan is over 120 words);
    FIX = one_line_solution; an override replaces CAUSE and/or FIX. FILES collapses to 3, then 1 entry when needed; the
    functions of the entries it cuts are named in its tail when the plan does not name them elsewhere."""
    ov = override or {}
    cause_full = " ".join(str(ov["CAUSE"]).split()) if ov.get("CAUSE") else first_sentence(root_cause)
    fix = " ".join(str(ov["FIX"] if ov.get("FIX") else fix).split())
    info = {"cause_words": CAUSE_WORDS, "files_keep": FILES_MAX}
    for cw, keep in ((CAUSE_WORDS, FILES_MAX), (CAUSE_WORDS_SHORT, FILES_MAX), (CAUSE_WORDS_SHORT, 3),
                     (CAUSE_WORDS_SHORT, 1)):
        plan = render_plan(files_line(entries, keep), cut_words(cause_full, cw), fix, reproducible, tests)
        missing = unnamed_rest(entries, keep, plan)          # a cut entry's function must still be named
        if missing:
            plan = render_plan(files_line(entries, keep, missing), cut_words(cause_full, cw), fix, reproducible,
                               tests)
        info = {"cause_words": cw, "files_keep": keep}
        if plan_words(plan) <= PLAN_WORDS_MAX:
            break
    info["words"] = plan_words(plan)
    return plan, info


def plan_line(plan: str, key: str) -> str:
    for ln in plan.split("\n"):
        if ln.startswith(key + ":"):
            return ln[len(key) + 1:].strip()
    return ""


# ------------------------------------------------------------------------------------------------------ leak rules
def norm_ws(s: str) -> str:
    return " ".join((s or "").split())


def _maximal(found: set) -> list:
    return sorted(s for s in found if not any(s != o and s in o for o in found))


EDGE = " \t()[]{}\"'`"          # brackets, quotes, backticks: the plan's own wrapping; : , ; . stay code


def rule_substring(plan: str, added: dict, originals: dict, issue: str, rule: int, also_known=None) -> list:
    """Rules 1 and 3: every substring of 12+ characters (whitespace-normalised) of an ADDED line that appears in the
    plan must also appear in that file's original text (originals[path]) or in the issue; also_known(s) -> bool is an
    extra exemption (rule 3: the original repository and the gold patch). A common substring is judged by its core,
    edge whitespace, brackets, quotes and backticks trimmed (the plan's own wrapping around a known name is not code
    from the patch; ':', ',', ';' and '.' stay significant); a core of 12+ characters that is still unknown is a
    violation. For each start only the longest common
    substring needs checking, since 'absent from the original' is monotone in length."""
    P, I = norm_ws(plan), norm_ws(issue)
    out = []
    for path in sorted(added):
        O = norm_ws(originals.get(path) or "")
        found = set()
        for raw in added[path]:
            a = norm_ws(raw)
            for i in range(len(a) - LEAK_MIN + 1):
                if a[i:i + LEAK_MIN] not in P:
                    continue
                L = LEAK_MIN
                while i + L < len(a) and a[i:i + L + 1] in P:
                    L += 1
                s = a[i:i + L].strip(EDGE)
                if len(s) < LEAK_MIN or s in O or s in I or (also_known is not None and also_known(s)):
                    continue
                found.add(s)
        out += [{"rule": rule, "file": path, "text": s} for s in _maximal(found)]
    return out


_BACKTICK = re.compile(r"`([^`\n]+)`")
_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
STDLIB_NO_IMPORT = frozenset({"antigravity", "this", "idlelib", "tkinter", "turtle", "turtledemo", "__main__",
                              "webbrowser", "pydoc", "ensurepip", "venv", "lib2to3"})


_CAMEL = re.compile(r"[a-z0-9][A-Z]")


def is_code_token(tok: str) -> bool:
    """A token with '_', '.', or an inner capital. 'Inner capital' is camelCase (an upper-case letter right after a
    lower-case letter or digit: FastAPIError, NoneType, getValue); ALL-CAPS words (EVERY, BOTH, SIGPIPE, PR) are
    emphasis or acronyms, not code names."""
    return "_" in tok or "." in tok or bool(_CAMEL.search(tok))


def plan_identifiers(text: str) -> list:
    """Code identifiers of rule 2: every backticked span, and every token (outside backticks) with '_', '.', or an inner
    capital. Order of appearance, de-duplicated."""
    out = []
    for m in _BACKTICK.finditer(text):
        out.append(m.group(1).strip())
    rest = _BACKTICK.sub(" ", text)
    for m in _TOKEN.finditer(rest):
        if is_code_token(m.group(0)):
            out.append(m.group(0))
    return list(dict.fromkeys(x for x in out if x))


_STDLIB_CACHE: dict = {}


def _dunder_probe() -> set:
    """Special names Python itself defines: the dunders of builtin objects, of a functools.wraps wrapper and of an
    exception with a note, plus data-model hooks that exist only as lookups (reference manual 3.3)."""
    import functools

    def f():
        return 0
    e = Exception()
    e.add_note("n")
    objs = (object, type, int, str, bytes, list, dict, set, tuple, property, classmethod, staticmethod, f, sys, e,
            functools.wraps(f)(lambda: 0), functools.partial(f), BaseException, (x for x in ()))
    out = {n for o in objs for n in dir(o) if n.startswith("__") and n.endswith("__")}
    return out | {"__getattr__", "__set_name__", "__class_getitem__", "__missing__", "__init_subclass__", "__slots__",
                  "__all__", "__annotations__", "__post_init__", "__main__", "__file__"}


_DUNDERS: set = set()


def stdlib_name(tok: str) -> bool:
    """A Python 3.12 builtin or stdlib name: dir(builtins), a Python special (dunder) name, a stdlib module name, or a
    stdlib `mod.attr` (mod in sys.stdlib_module_names, attr found after importing the stdlib module; never repository
    code). Dotted module prefixes are tried longest first."""
    if tok in _STDLIB_CACHE:
        return _STDLIB_CACHE[tok]
    if not _DUNDERS:
        _DUNDERS.update(_dunder_probe())
    ok = False
    parts = tok.split(".")
    stdmods = getattr(sys, "stdlib_module_names", ())
    if len(parts) == 1:
        ok = tok in dir(builtins) or tok in _DUNDERS or tok in stdmods
    elif parts[0] in stdmods and parts[0] not in STDLIB_NO_IMPORT:
        for k in range(len(parts) - 1, 0, -1):
            modname = ".".join(parts[:k])
            try:
                obj = importlib.import_module(modname)
            except Exception:
                continue
            good = True
            for attr in parts[k:]:
                if not hasattr(obj, attr):
                    good = False
                    break
                obj = getattr(obj, attr)
            ok = good
            break
    _STDLIB_CACHE[tok] = ok
    return ok


class Known:
    """Rule-2 name source: the issue text, the original repository (a has(substr) / has_word(word) pair: git grep over
    the base workspace, or the gold patch's context and removed lines when there is no snapshot), repository paths,
    Python keywords, builtins and stdlib names."""

    def __init__(self, issue: str, has, has_word, paths_text: str = ""):
        self.issue = issue or ""
        self.has, self.has_word, self.paths = has, has_word, paths_text
        self._issue_words = set(_WORD.findall(self.issue))

    def word(self, w: str) -> bool:
        return (keyword.iskeyword(w) or keyword.issoftkeyword(w) or stdlib_name(w) or w in self._issue_words
                or self.has_word(w))

    def name(self, tok: str) -> bool:
        tok = tok.strip().strip(".,;:")
        if not tok:
            return True
        if tok in self.issue or stdlib_name(tok) or (self.paths and tok in self.paths) or self.has(tok):
            return True
        if _TOKEN.fullmatch(tok):
            parts = tok.split(".")
            return len(parts) > 1 and all(self.word(p) for p in parts)
        words = _TOKEN.findall(tok)                    # a backticked expression: every name in it must be known
        return all(self.name(w) if "." in w else self.word(w) for w in words)


def rule_names(plan: str, known: Known) -> list:
    """Rule 2 on the CAUSE, FIX and TESTS lines (FILES holds gold paths and ast names of the original by construction,
    REPRO is fixed text)."""
    out = []
    for key in ("CAUSE", "FIX", "TESTS"):
        for ident in plan_identifiers(plan_line(plan, key)):
            if not known.name(ident):
                out.append({"rule": 2, "line": key, "text": ident})
    return out


def patch_text_norm(text: str) -> str:
    """Every body line (both sides) of a patch, whitespace-normalised, one per line."""
    return "\n".join(norm_ws(ln.text) for fp in parse(text) for h in fp.hunks for ln in hunk_lines(h))


def leak_check(plan: str, gold: str, test_patch: str, issue: str, known: Known) -> list:
    """All three rules of 4.1; [] when the plan is clean.

    'The original file' of rules 1 and 3 is the file's OLD SIDE in the diff (context and removed lines, plus the hunk
    header context): a fix line that also exists elsewhere in the file (rich_3905's `if not self.disable:` copied from
    start(); rich_2943's `style._hash = None`) is still the fix, and this is the reading that catches all 9 leaks v1
    listed. It also treats tasks with and without a snapshot identically. A common substring that is a single name
    rule 2 accepts (an existing repository name, a builtin or stdlib name: strip_control_codes, BrokenPipeError) is
    not code from the patch; code fragments (operators, calls, literals) still must come from the old side or the
    issue. Rule 3 additionally exempts text that exists in the original repository (a repo API the hidden test calls)
    or anywhere in the gold patch (rule 1's business): what it flags is content only the hidden tests have."""
    old = {**old_side_by_file(test_patch), **old_side_by_file(gold)}
    body = checked_text(plan)

    P = norm_ws(body)

    def a_name(s):
        """A name-like fragment is judged by the whole plan token around it: one identifier or dotted name that rule 2
        accepts is not code from the patch (a fragment such as rokenPipeError is part of BrokenPipeError)."""
        return bool(_NAMEISH.fullmatch(s)) and any(known.name(t) for t in enclosing_tokens(P, s))
    v = rule_substring(body, added_by_file(gold), old, issue, 1, also_known=a_name)
    v += rule_names(plan, known)
    g = patch_text_norm(gold)
    v += rule_substring(body, added_by_file(test_patch), old, issue, 3,
                        also_known=lambda s: s in g or s in known.paths or known.has(s) or a_name(s))
    return v


_NAMEISH = re.compile(r"[A-Za-z0-9_.]+")


def enclosing_tokens(text: str, frag: str) -> list:
    """Every occurrence of frag in text, widened to the enclosing run of name characters (letters, digits, _ and .),
    with edge dots dropped."""
    out = []
    for m in re.finditer(re.escape(frag), text):
        a, b = m.start(), m.end()
        while a > 0 and (text[a - 1].isalnum() or text[a - 1] in "_."):
            a -= 1
        while b < len(text) and (text[b].isalnum() or text[b] in "_."):
            b += 1
        tok = text[a:b].strip(".")
        if tok and tok not in out:
            out.append(tok)
    return out


CHECKED_LINES = ("CAUSE", "FIX", "TESTS")


def checked_text(plan: str) -> str:
    """The plan lines the leak rules check. FILES is excluded: it must name every gold file (new ones as '<path> (new
    file)') and its functions come from the ORIGINAL file's ast (or its hunk header), so any overlap with added lines is
    by construction; REPRO is fixed text. A NUL separator (never in a patch line) keeps matches inside one line."""
    return " \0 ".join(plan_line(plan, k) for k in CHECKED_LINES)


def text_known(texts: list, paths: list) -> tuple:
    """(has, has_word, paths_text) over in-memory texts (no snapshot, and the tests)."""
    blob = "\n".join(texts)
    words = set(_WORD.findall(blob))
    return (lambda s: s in blob), (lambda w: w in words), "\n".join(paths)


# ------------------------------------------------------------------------------------------------------ ATIF traces
def step_author(step: dict, tc: dict | None = None) -> str:
    ex = step.get("extra") or {}
    if tc is not None and (tc.get("extra") or {}).get("author"):
        return tc["extra"]["author"]
    tcs = step.get("tool_calls") or []
    return ex.get("author") or (tcs and (tcs[0].get("extra") or {}).get("author")) or "?"


def obs_text(step: dict) -> str:
    o = step.get("observation")
    if isinstance(o, dict):
        return str(o.get("content") or "")
    return str(o or "")


_OPENER = re.compile(r"^python3 /tmp/swe/verify\.py --repro-only <<-?\s*(['\"]?)(\w+)\1\s*$")
_REPRO_FIRST = re.compile(r"REPRO: [^\\\n]*")


def heredoc_body(command: str):
    """The body of a `python3 /tmp/swe/verify.py --repro-only <<'EOF' ... EOF` command: the lines between the opener and
    the delimiter line, as bash reads it (it stops at the first line equal to the delimiter; without one, the rest).
    None when the command is not that form."""
    lines = (command or "").split("\n")
    m = _OPENER.match(lines[0].strip())
    if not m:
        return None
    delim = m.group(2)
    body = []
    for ln in lines[1:]:
        if ln == delim:
            break
        body.append(ln)
    return "\n".join(body) + "\n" if body else ""


def extract_repro(trace: dict):
    """4.2: the LAST locator run_command `verify.py --repro-only` heredoc whose observation says 'fails on original'
    or 'hangs on original' (the v10.0 banner of race 2 is irrelevant: gotcha 11). -> {body, step_id, verdict, first}
    or None."""
    best = None
    for s in trace.get("steps") or []:
        if s.get("source") != "agent":
            continue
        tcs = s.get("tool_calls") or []
        obs = obs_text(s)
        for tc in tcs:
            if tc.get("function_name") != "run_command" or step_author(s, tc) != "locator":
                continue
            body = heredoc_body(str((tc.get("arguments") or {}).get("command") or ""))
            if body is None or not body.strip():
                continue
            verdict = "fails" if "fails on original" in obs else ("hangs" if "hangs on original" in obs else None)
            if verdict:
                m = _REPRO_FIRST.search(obs)
                best = {"body": body, "step_id": s.get("step_id"), "verdict": verdict,
                        "first": m.group(0)[:200] if m else ""}
    return best


def stage_first_footer(trace: dict, stage: str):
    """The last [t=Ns] footer before the stage's first step, or None when the stage never ran (or no footer)."""
    steps = trace.get("steps") or []
    idx = next((i for i, s in enumerate(steps) if s.get("source") == "agent" and step_author(s) == stage), None)
    if idx is None:
        return None
    fts = [int(x) for s in steps[:idx] for x in R.FOOT_T.findall(obs_text(s))]
    return fts[-1] if fts else None


def compute_t0(traces: dict) -> dict:
    """{suite: {"t0": median, "n": tasks}} over the tasks in which that stage ran (gotcha 22)."""
    out = {}
    for suite, stage in STAGE_OF.items():
        vals = [v for v in (stage_first_footer(tr, stage) for tr in traces.values()) if v is not None]
        med = statistics.median(vals) if vals else 0
        out[suite] = {"t0": int(med) if float(med).is_integer() else float(med), "n": len(vals)}
    return out


def load_trace(tid: str, run: str = REPRO_RUN):
    p = RACE2_DIR / run / "traces" / f"trace_{tid}.json"
    return json.loads(p.read_text()) if p.is_file() else None


# ------------------------------------------------------------------------------------------------------ replay (4.4)
_JUNK = re.compile(r"^\s*(?:(?:SWE_)?EOF\W*|`+)\s*$")          # edit.py / _swe_common._normalize_text
_NUMCOL = re.compile(r"^\s*\d+\| ?")                             # edit.py clean_body
_MARKER = re.compile(r"^\s*(<{5,9} ?SEARCH|={5,9}|>{5,9} ?REPLACE)\s*$", re.I)   # tasks._MARKER


def hunk_edit(h) -> dict:
    """One edit.py call for a hunk, trimmed to the span from its first to its last change (so a no-newline last
    context line is never rewritten): lines A-B with the span's new side, insert-after N, or delete A-B."""
    lines = hunk_lines(h)
    idx = [i for i, ln in enumerate(lines) if ln.kind != " "]
    span = lines[idx[0]:idx[-1] + 1]
    old = [ln for ln in span if ln.kind in " -"]
    new = [ln for ln in span if ln.kind in " +"]
    body = [ln.text for ln in new]
    if not old:
        return {"op": "insert", "a": span[0].old, "b": span[0].old, "body": body}
    a, b = old[0].old, old[-1].old
    if not new:
        return {"op": "delete", "a": a, "b": b, "body": []}
    return {"op": "lines", "a": a, "b": b, "body": body}


def body_problem(body_lines: list) -> str | None:
    """Why a heredoc body cannot carry these lines through edit.py exactly (None when it can)."""
    for t in body_lines:
        s = t[:-1] if t.endswith("\n") else t
        if s == "EOF":
            return "a body line is exactly EOF (it would end the heredoc early)"
        if _MARKER.match(s):
            return "a body line matches a SEARCH/REPLACE marker (edit.py would parse the body as blocks)"
        if "\r" in t:
            return "a body line has a CR (edit.py normalises CRLF)"
        if not t.endswith("\n"):
            return "no newline at end of file on the new side (a heredoc always ends with one)"
    nb = [t for t in body_lines if t.strip()]
    if nb and all(_NUMCOL.match(t) for t in nb):
        return "every body line looks like a view.py number column (edit.py strips it)"
    if nb and _JUNK.match(nb[-1].rstrip("\n")):
        return "the last body line looks like a heredoc terminator (edit.py drops it)"
    return None


def replay_fallback_reason(text: str) -> str | None:
    """4.4 static fallback rules; None when edit.py can express the patch."""
    secs = sections(text)
    if not secs:
        return "no file sections"
    for s in secs:
        if s.deleted:
            return f"deletes a file ({s.path})"
        if s.rename:
            return f"renames a file ({s.old_path} -> {s.path})"
        if s.binary:
            return f"binary change ({s.path})"
        if s.mode:
            return f"mode change ({s.path})"
        if not s.hunks:
            return f"a section without hunks ({s.path})"
        if any(x in s.path for x in REWRITTEN):
            return f"the path contains a sandbox-rewritten substring ({s.path})"
    for fp in parse(text):
        for h in fp.hunks:
            for raw in h.lines:
                hit = next((x for x in REWRITTEN if x in raw), None)
                if hit:
                    return f"a hunk contains {hit} (the sandbox rewrites it in command text)"
    for fp in parse(text):
        if fp.new_file:
            prob = body_problem([ln.text for h in fp.hunks for ln in hunk_lines(h) if ln.kind == "+"])
        else:
            prob = next((p for p in (body_problem(hunk_edit(h)["body"]) for h in fp.hunks) if p), None)
        if prob:
            return f"{fp.path}: {prob}"
    return None


def edit_steps(text: str) -> list:
    """edit.py run_command steps: --create per new file, one call per hunk bottom-up per file (the mock_llm cmd/heredoc
    shape: {"tool": "run_command", "args": {"command": ...}})."""
    steps = []
    for fp in parse(text):
        if not fp.path:
            continue
        q = shlex.quote(fp.path)
        if fp.new_file:
            body = "".join(ln.text for h in fp.hunks for ln in hunk_lines(h) if ln.kind == "+")
            steps.append(_step(f"{EDIT} {q} --create <<'EOF'\n{body}EOF"))
            continue
        for h in sorted(fp.hunks, key=lambda x: -x.old_start):
            e = hunk_edit(h)
            body = "".join(e["body"])
            if e["op"] == "insert":
                steps.append(_step(f"{EDIT} {q} --insert-after {e['a']} <<'EOF'\n{body}EOF"))
            elif e["op"] == "delete":
                steps.append(_step(f"{EDIT} {q} --lines {e['a']}-{e['b']} --delete"))
            else:
                steps.append(_step(f"{EDIT} {q} --lines {e['a']}-{e['b']} <<'EOF'\n{body}EOF"))
    return steps


def _step(command: str) -> dict:
    return {"tool": "run_command", "args": {"command": command}}


def git_apply_steps(text: str, chunk: int = B64_CHUNK) -> list:
    """The base64 git-apply fallback: one run_command when the base64 fits one chunk, else chunks appended to
    .git/_golden_tree.b64 and a final apply that removes it (base64 keeps the sandbox's command-text rewrite away)."""
    data = (text if text.endswith("\n") else text + "\n").encode("utf-8", "surrogateescape")
    b64 = base64.b64encode(data).decode("ascii")
    if len(b64) <= chunk:
        return [_step('python3 -c "import base64,subprocess,sys;sys.exit(subprocess.run([\'git\',\'apply\','
                      "'--whitespace=nowarn','-'],input=base64.b64decode('%s')).returncode)\"" % b64)]
    steps = []
    for i in range(0, len(b64), chunk):
        mode = "w" if i == 0 else "a"
        steps.append(_step("python3 -c \"open('%s','%s').write('%s')\"" % (B64_FILE, mode, b64[i:i + chunk])))
    steps.append(_step('python3 -c "import base64,os,subprocess,sys;p=\'%s\';d=base64.b64decode(open(p).read());'
                       "os.remove(p);sys.exit(subprocess.run(['git','apply','--whitespace=nowarn','-'],input=d)"
                       '.returncode)"' % B64_FILE))
    return steps


def build_replay(text: str) -> dict:
    """{"replay": "edit"|"git_apply"|"none", "steps": [...], "why": fallback reason or ""}."""
    if not (text or "").strip():
        return {"replay": "none", "steps": [], "why": ""}
    why = replay_fallback_reason(text)
    if why:
        return {"replay": "git_apply", "steps": git_apply_steps(text), "why": why}
    return {"replay": "edit", "steps": edit_steps(text), "why": ""}


def notes_changed(entries: list) -> str:
    """The scripted fixer's CHANGED line (fixer.md 'CHANGED: file function (lines)'), new-side line ranges."""
    if not entries:
        return "CHANGED: nothing"
    parts = []
    for e in entries:
        func = "new file" if e["new_file"] else (e["qualname"] or "module level")
        parts.append(f"{e['file']} {func} ({e['nstart']}-{e['nend']})")
    return "CHANGED: " + "; ".join(parts)


# ------------------------------------------------------------------------------------------------------ wrong (4.3)
def wrong_candidates(tid: str, sources=WRONG_SOURCES) -> list:
    """[{"source", "raw"}] in 4.3 source order; absent or empty sources are skipped."""
    out = []
    for label, kind, loc in sources:
        raw = ""
        if kind == "patch_dir":
            p = Path(loc) / f"{tid}.patch"
            raw = p.read_text(encoding="utf-8", errors="surrogateescape") if p.is_file() else ""
        else:
            p = Path(loc)
            if p.is_file():
                for line in p.read_text().splitlines():
                    if line.strip():
                        r = json.loads(line)
                        if r.get("id") == tid:
                            raw = r.get("patch") or ""
                            break
        if raw.strip():
            out.append({"source": label, "raw": raw})
    return out


def source_file(path: str) -> bool:
    """A non-test Python source file: not protected (tests, configs), not a scratch file (replay_l4 rules)."""
    if not path.endswith(".py") or R.is_protected(path):
        return False
    if R.scratch_files([(path, True)]):
        return False
    return True


def static_wrong(cands: list, gold: str, gold_files: list) -> list:
    """Strip protected sections first, then the static rejections (empty, test-only / no source file, equals gold);
    identical stripped candidates keep the first source. -> [{source, idx, patch, dropped, files, touches_gold,
    n_changed, status, why}] in source order."""
    gold_cl = changed_lines(gold)
    seen: dict = {}
    out = []
    for idx, c in enumerate(cands):
        text, dropped = strip_protected(c["raw"])
        files = [s.path for s in sections(text)]
        rec = {"source": c["source"], "idx": idx, "patch": text, "dropped": dropped, "files": files,
               "touches_gold": bool(set(files) & set(gold_files)), "n_changed": len(changed_lines(text)),
               "status": "candidate", "why": ""}
        if not text.strip():
            rec.update(status="rejected", why="empty after dropping protected sections" if dropped else "empty")
        elif not any(source_file(p) for p in files):
            rec.update(status="rejected", why="touches no non-test source file")
        elif changed_lines(text) == gold_cl:
            rec.update(status="rejected", why="changed lines equal gold")
        elif sha_text(text) in seen:
            rec.update(status="rejected", why=f"same patch as {seen[sha_text(text)]}")
        else:
            seen[sha_text(text)] = c["source"]
        out.append(rec)
    return out


def pick_order(recs: list) -> list:
    """Candidates still in the running, in pick priority: gold-file-touching first, then source order, then fewest
    changed lines."""
    live = [r for r in recs if r["status"] == "candidate"]
    return sorted(live, key=lambda r: (not r["touches_gold"], r["idx"], r["n_changed"]))


def select_wrong(recs: list, gold: str, canonical, verify):
    """4.3 exec qualification, lazily in pick priority: the first candidate that applies (canonical(patch) ->
    {"applies", "why", "patch", "unsubmittable"} or {"error"}; the patch is what a v10.1 submit would capture), still
    touches a non-test source file and differs from gold after applying, and FAILS the hidden tests
    (verify(canonical_patch) -> {"pass", "why", "retried"} or {"error"}) is picked; candidates behind it are marked
    not_evaluated. Updates recs in place; returns the picked rec (with "canonical") or None."""
    gold_cl = changed_lines(gold)
    picked = None
    for rec in pick_order(recs):
        cn = canonical(rec["patch"])
        if cn.get("error"):
            rec.update(status="rejected", why=cn["error"])
            continue
        if not cn["applies"]:
            rec.update(status="rejected", why=cn["why"] or "does not apply")
            continue
        canon = cn["patch"]
        if cn.get("unsubmittable"):
            rec["unsubmittable"] = list(cn["unsubmittable"])
        if not canon.strip():
            rec.update(status="rejected", why="no change after applying" + (
                " (the v10.1 submit guard keeps the rest out of the diff)" if cn.get("unsubmittable") else ""))
            continue
        if not any(source_file(s.path) for s in sections(canon)):
            rec.update(status="rejected", why="touches no non-test source file after applying under the submit guard")
            continue
        if changed_lines(canon) == gold_cl:
            rec.update(status="rejected", why="changed lines equal gold after applying")
            continue
        mv = verify(canon)
        rec["mini_verify_why"] = mv.get("why") or mv.get("error") or ""
        rec["retried"] = bool(mv.get("retried"))
        if mv.get("error"):
            rec.update(status="rejected", why="mini_verify crashed: " + mv["error"])
            continue
        if mv["pass"]:
            rec.update(status="rejected", why="passes the hidden tests")
            continue
        rec.update(status="picked", canonical=canon)
        picked = rec
        break
    for rec in recs:
        if rec["status"] == "candidate":
            rec.update(status="not_evaluated", why="a higher-priority candidate qualified")
    return picked


# ------------------------------------------------------------------------------------------------------ exec layer
class Skip(Exception):
    pass


def is_pytest_outcome(e: BaseException) -> bool:
    """A pytest skip/fail/xfail outcome. Checked by class, never by __module__: pytest sets
    OutcomeException.__module__ (and its subclasses') to "builtins" so tracebacks print 'Skipped', so a module test
    silently misses every one of them (regression test: test_pytest_skip_never_leaks_out_of_the_builder)."""
    try:
        from _pytest.outcomes import OutcomeException
    except ImportError:                                 # pytest absent: tasks.py could not have raised one
        return False
    return isinstance(e, OutcomeException)


def guarded(fn, *args, **kw):
    """Run fn; a pytest outcome (tasks.py's skip/fail) or any Exception becomes {"error": reason} instead of escaping
    (gotcha 12). KeyboardInterrupt and SystemExit still propagate."""
    try:
        return fn(*args, **kw)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as e:                          # _pytest.outcomes.OutcomeException is a BaseException
        kind = "pytest." + type(e).__name__.lower() if is_pytest_outcome(e) else type(e).__name__
        msg = getattr(e, "msg", None) or str(e)
        return {"error": clean_why(f"{kind}: {msg}", 400)}


def runnable(tid: str) -> tuple:
    """(bool, why) from has_snapshot and kpar_ok, never via tasks.py's skipping helpers."""
    T = _T()
    if not T.has_snapshot(tid):
        return False, f"snapshot missing: data/raw/snapshots/{tid}.tgz"
    if not T.kpar_ok(tid):
        return False, f"kpar venv missing: scripts/build_kpar.sh {T.repo_key(tid)}"
    return True, ""


def failure_count(why: str) -> int | None:
    """Failed + errored tests from a mini_verify reason ('pytest exit 1: 1 failed, 93 passed'), None if unknown."""
    if not why or not why.startswith("pytest exit"):
        return None
    n = sum(int(x) for x in re.findall(r"(\d+) (?:failed|errors?)\b", why))
    return n or None


def x_failing_nodes(tid: str, patch: str) -> list | None:
    """Failing/erroring hidden test cases (classname, name) of the grader's targets with `patch` applied, or None."""
    T = _T()
    t = T.load_task(tid)
    with LOAD.shared(), T.work_dir("gfl") as wd:
        tree = T.fresh_ws(T.base_ws(tid, with_test_patch=True), wd)
        if patch.strip():
            rc, _ = T.harness_apply(tree, patch)
            if rc != 0:
                return None
        cases, _to = T.junit_cases(tree, T.extract_targets(t["test_patch"]), T.sandbox_env(tree, tid, None),
                                   MV_TIMEOUT)
    if cases is None:
        return None
    return [(c, n) for c, n, bad in cases if bad]


def only_flaky(bad: list | None) -> bool:
    if not bad:
        return False
    T = _T()
    return all(any(T._junit_match(T._node_key(node), c, n) for node in KNOWN_FLAKY) for c, n in bad)


# ------------------------------------------------------------------ load gate (the KNOWN_FLAKY retry runs alone)
class LoadGate:
    """A writer-preferring readers/writer gate over the builder's own test runs. Every exec step holds it shared; the
    KNOWN_FLAKY retry holds it exclusively, so it waits for the in-flight runs, blocks new ones, and runs alone, as the
    grader runs one task at a time. Why: tests/test_console.py::test_brokenpipeerror races a pipe and fails often
    under the builder's own load (-j 6, two exec steps per task); two cold builds each flipped a gold run of a
    gradable task (rich_3675, then rich_3468 and rich_4075 whose retry flaked again under load). Never nest: a thread
    holding the gate must not enter it again (a waiting writer would then deadlock it)."""

    def __init__(self):
        self.cv = threading.Condition()
        self.readers = 0
        self.writer = False
        self.waiting = 0

    @contextlib.contextmanager
    def shared(self):
        with self.cv:
            while self.writer or self.waiting:
                self.cv.wait()
            self.readers += 1
        try:
            yield
        finally:
            with self.cv:
                self.readers -= 1
                self.cv.notify_all()

    @contextlib.contextmanager
    def exclusive(self):
        with self.cv:
            self.waiting += 1
            while self.writer or self.readers:
                self.cv.wait()
            self.waiting -= 1
            self.writer = True
        try:
            yield
        finally:
            with self.cv:
                self.writer = False
                self.cv.notify_all()


LOAD = LoadGate()


# ------------------------------------------------------------------ the grader run's own failures (same-run tap)
_TAP_LOCK = threading.Lock()
_TAP = {"n": 0, "orig": None}
_TAP_LOCAL = threading.local()


@contextlib.contextmanager
def pytest_output_tap():
    """Collect, for THIS thread only, the stdout of every `... -m pytest ...` command tasks.mini_verify runs through
    tasks.run while the context is open. A transparent wrapper around the tasks.run module global (mini_verify looks
    it up at call time), installed on first entry and restored on last exit under a lock, so concurrent builder
    threads each see only their own runs and tasks.py itself is never edited. Why: deciding the KNOWN_FLAKY retry
    from a SECOND run is wrong when the flake does not recur there (a loaded cold build: rich_3675's gold failed
    '1 failed, 98 passed', the identification rerun passed, so no retry happened and gradable flipped)."""
    T = _T()
    with _TAP_LOCK:
        if _TAP["n"] == 0:
            orig = T.run

            def run(cmd, *a, **kw):
                r = orig(cmd, *a, **kw)
                outs = getattr(_TAP_LOCAL, "outs", None)
                if outs is not None and isinstance(cmd, str) and " -m pytest " in cmd:
                    outs.append(getattr(r, "out", "") or "")
                return r
            _TAP["orig"] = orig
            T.run = run
        _TAP["n"] += 1
    _TAP_LOCAL.outs = []
    try:
        yield _TAP_LOCAL.outs
    finally:
        _TAP_LOCAL.outs = None
        with _TAP_LOCK:
            _TAP["n"] -= 1
            if _TAP["n"] == 0:
                T.run = _TAP["orig"]
                _TAP["orig"] = None


_FAILED_LINE = re.compile(r"^(?:FAILED|ERROR) (\S+)", re.M)


def failed_node_ids(out: str) -> list:
    """Node ids of pytest's short summary ('FAILED tests/x.py::test_y - msg', 'ERROR tests/x.py - ImportError'), in
    order, de-duplicated (the grader line runs with -q and pytest's default -rfE)."""
    return list(dict.fromkeys(_FAILED_LINE.findall(out or "")))


def all_known_flaky(node_ids: list) -> bool:
    return bool(node_ids) and all(n.split("[", 1)[0] in KNOWN_FLAKY for n in node_ids)


def x_mini_verify(tid: str, patch: str) -> dict:
    """tasks.mini_verify(base_ws(tid), patch, test_patch, repo=tid, timeout=180), retried once when every failing
    hidden test is a KNOWN_FLAKY one (the test_v10_flow rule). The failing tests are read from the SAME run's pytest
    summary (pytest_output_tap); only when that run printed no summary lines is a separate identification run used.
    The reason names up to 3 failing node ids."""
    T = _T()
    t = T.load_task(tid)

    def once(gate):
        with gate, pytest_output_tap() as outs:
            r, w, _secs = T.mini_verify(T.base_ws(tid), patch, t["test_patch"], repo=tid, timeout=MV_TIMEOUT)
        return r, w, (failed_node_ids(outs[-1]) if outs else [])
    res, why, failed = once(LOAD.shared())
    retried = False
    n = failure_count(why or "")
    if not res and n is not None and n <= len(KNOWN_FLAKY):
        flaky = all_known_flaky(failed) if failed else only_flaky(x_failing_nodes(tid, patch))
        if flaky:
            retried = True
            res, why, failed = once(LOAD.exclusive())            # alone, like the grader (LoadGate)
    return {"pass": bool(res), "why": "" if res else failure_reason(why, failed), "retried": retried}


def failure_reason(why: str, failed: list) -> str:
    """The committed reason for a failing grader run. With the run's own failing node ids: the exit code and the
    failing ids other than KNOWN_FLAKY ones (at most 3 shown), without pytest's pass/fail counts; a load-dependent
    flake failing alongside a real failure then changes neither the outcome nor the text, so a cold rebuild records
    the same reason (the counts moved by one whenever test_brokenpipeerror flaked). Only-flaky failures (after the
    isolated retry) say so. Without ids (a hang, an apply error, no summary lines): mini_verify's own reason."""
    m = re.match(r"pytest exit (\d+):", why or "")
    if not (m and failed):
        return clean_why(why)
    real = [n for n in failed if not all_known_flaky([n])]
    shown = real or failed
    label = "failed" if real else "failed, only known-flaky tests"
    ids = ", ".join(shown[:3]) + (", ..." if len(shown) > 3 else "")
    return clean_why(f"pytest exit {m.group(1)}: {len(shown)} {label} [{ids}]")


def x_gradable(tid: str, mv=None) -> dict:
    """4.5: gold passes twice and the empty patch fails (each through x_mini_verify, timeout 180)."""
    mv = mv or x_mini_verify
    t = _T().load_task(tid)
    gold = [mv(tid, t["patch"]) for _ in range(2)]
    empty = mv(tid, "")
    n_pass = sum(g["pass"] for g in gold)
    why = ""
    if n_pass < 2:
        why = f"gold passed {n_pass}/2: " + next(g["why"] for g in gold if not g["pass"])
    elif empty["pass"]:
        why = "the empty patch passes the hidden tests"
    return {"gradable": n_pass == 2 and not empty["pass"], "gradable_why": why, "gold_pass_runs": n_pass,
            "gold_runs": 2, "gold_why": [g["why"] for g in gold], "gold_retried": [g["retried"] for g in gold],
            "empty_pass": empty["pass"], "empty_why": empty["why"], "empty_retried": empty["retried"]}


_WS_LIT = re.compile(r"(?<![\w./-])/workspace(?![\w.-])")


def x_run_repro(tid: str, body: str, gold: bool) -> dict:
    """Run a repro body with the kpar python on a fresh clone (original, or with the gold patch through the harness
    apply pipeline): cwd = PYTHONPATH = the clone, literal /workspace mapped to it, 20 s."""
    T = _T()
    t = T.load_task(tid)
    with LOAD.shared(), T.work_dir("grp") as wd:
        ws = T.fresh_ws(tid, wd)
        if gold:
            rc, err = T.harness_apply(ws, t["patch"])
            if rc != 0:
                return {"rc": None, "timed_out": False, "error": clean_why(f"gold did not apply: {err}")}
        env = T.sandbox_env(ws, tid, fake_clock=None)
        f = Path(f"{ws}_tmp") / "golden_repro.py"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(_WS_LIT.sub(lambda _m: str(ws), body), encoding="utf-8", errors="surrogateescape")
        r = T.run(["python3", str(f)], cwd=ws, env=env, timeout=REPRO_TIMEOUT)
        return {"rc": r.rc, "timed_out": bool(r.timed_out), "tail": clean_why(r.err or r.out, 240, tail=True)}


def repro_verdict(orig: dict, gold: dict) -> tuple:
    """(reproducible, why): fails (or times out) on the original, exits 0 within 20 s on gold."""
    if orig.get("error") or gold.get("error"):
        return False, orig.get("error") or gold.get("error")
    if orig["rc"] == 0 and not orig["timed_out"]:
        return False, "passes on the original tree"
    if gold["timed_out"]:
        return False, f"times out on the gold tree ({REPRO_TIMEOUT}s)"
    if gold["rc"] != 0:
        return False, f"fails on the gold tree (exit {gold['rc']}): {gold.get('tail', '')}"
    return True, ""


def x_replay(tid: str, steps: list, patch: str, replay: str) -> dict:
    """4.4 validation on a fresh clone of the task's base workspace with the installed helpers (replay_in_ws)."""
    T = _T()
    with LOAD.shared(), T.work_dir("grl") as wd:
        ws = T.fresh_ws(tid, wd)
        return replay_in_ws(ws, T.sandbox_env(ws, tid), steps, patch, replay)


def replay_in_ws(ws, env: dict, steps: list, patch: str, replay: str) -> dict:
    """Install the bundle helpers from a temp copy (tasks.install_helpers), run every step's command with bash in ws
    (the literal /tmp/swe/ mapped to $SWE_DIR, as the sandbox maps it), then check: every edit step prints OK
    (git_apply: exits 0), the submit diff's changed lines equal the patch's, and the patch reverse-applies."""
    T = _T()
    ins = T.install_helpers(env)
    if not ins.installed:
        return {"ok": False, "why": clean_why("helpers did not install: " + (ins.err or ins.out), 240, tail=True), "firsts": []}
    firsts = []
    for i, st in enumerate(steps):
        command = st["args"]["command"].replace("/tmp/swe/", env["SWE_DIR"] + "/")
        r = T.run(command, cwd=ws, env=env, timeout=120)
        first = T.first_line(r.out)
        firsts.append(clean_why(first, 160))
        if replay == "edit" and not first.startswith("OK"):
            return {"ok": False, "why": f"step {i + 1} printed: {clean_why(first, 200)}", "firsts": firsts}
        if replay != "edit" and r.rc != 0:
            return {"ok": False, "why": f"step {i + 1} exit {r.rc}: {clean_why(r.err, 200, tail=True)}", "firsts": firsts}
    diff = T.submit_diff(ws, env)
    got, want = changed_lines(diff), changed_lines(patch)
    if got != want:
        extra = sorted(set(got) - set(want))[:2]
        miss = sorted(set(want) - set(got))[:2]
        return {"ok": False, "why": clean_why(f"changed lines differ: extra {extra} missing {miss}"), "firsts": firsts}
    p = patch if patch.endswith("\n") else patch + "\n"
    rv = T.git(ws, "apply", "-R", "--check", "-", env=env, stdin=p)
    if rv.rc != 0:
        return {"ok": False, "why": "the patch does not reverse-apply: " + clean_why(rv.err, 200, tail=True), "firsts": firsts}
    return {"ok": True, "why": "", "firsts": firsts}


def x_canonical(tid: str, patch: str) -> dict:
    """Apply a candidate with the harness pipeline on a fresh clone, arm the v10.1 submit guard exactly as setup's
    install does (tasks.install_helpers, from a temp copy), and take what submit_patch would capture there
    (tasks.submit_diff: git add -N . then git diff --binary <baseline>), restricted to the candidate's paths.
    Line numbers are then exact even if the harness needed an offset or fuzz, and every section a v10.1 run could never
    submit is gone: the guard's exclude file keeps untracked root scratch (reproduce_cjk.py, repro_issue.py) out of
    `git add -N .`, the same reason 4.3 drops protected sections. Without this, rich_3180 and rich_3894's wrong trees
    failed replay validation (the submit diff never shows their scratch files). 'unsubmittable' lists what vanished."""
    T = _T()
    with LOAD.shared(), T.work_dir("gcn") as wd:
        ws = T.fresh_ws(tid, wd)
        return canonical_in_ws(ws, T.sandbox_env(ws, tid), patch)


def canonical_in_ws(ws, env: dict, patch: str) -> dict:
    """x_canonical on a given clean workspace (tagged _swegemma_baseline) and helper environment. The helpers are
    installed BEFORE the candidate is applied, as in a real run (install is setup's first call, before any agent
    write): the guard re-includes root entries that exist when it is armed, so arming it after the apply would keep
    a root reproduce_*.py in the diff."""
    T = _T()
    paths = set(changed_paths(patch))
    ins = T.install_helpers(env)
    if not ins.installed:
        return {"error": clean_why("helpers did not install: " + (ins.err or ins.out), 240, tail=True)}
    rc, err = T.harness_apply(ws, patch, env)
    if rc != 0:
        return {"applies": False, "why": clean_why(f"does not apply: {err}"), "patch": "", "unsubmittable": []}
    text = submitted_part(T.submit_diff(ws, env), paths)
    return {"applies": True, "why": "", "patch": text, "unsubmittable": sorted(paths - set(changed_paths(text)))}


def submitted_part(diff: str, paths) -> str:
    """The file sections of a submit diff that belong to `paths` (a candidate's new or old paths), in diff order."""
    paths = set(paths)
    return "".join(s.text for s in sections(diff) if s.path in paths or s.old_path in paths)


def hidden_outcome_defaults() -> dict:
    import inspect
    sig = inspect.signature(_T().hidden_outcomes)
    return {k: sig.parameters[k].default for k in ("timeout", "node_cap")}


def x_hidden_pass(tid: str, nodes: list, tree_patch: str) -> dict:
    """pre_hidden_nodes_pass: hidden_outcomes (its default timeouts, like component b's hidden_nodes_pass) over the
    hidden nodes on base_ws(tid, with_test_patch=True) plus the tree patch. When a KNOWN_FLAKY node did not pass
    (rich_3468's hidden test IS test_brokenpipeerror), the measurement is repeated once with the load gate held
    exclusively and that result is kept, the same rule as x_mini_verify's retry."""
    if not nodes:
        return {"pass": 0, "outcomes": {}}
    out = _hidden_outcomes(tid, nodes, tree_patch, LOAD.shared())
    if "error" not in out and any(v != "pass" and n.split("[", 1)[0] in KNOWN_FLAKY for n, v in out.items()):
        out = _hidden_outcomes(tid, nodes, tree_patch, LOAD.exclusive())   # a KNOWN_FLAKY node: once more, alone
    if "error" in out:
        return out
    return {"pass": sum(1 for v in out.values() if v == "pass"), "outcomes": dict(sorted(out.items()))}


def _hidden_outcomes(tid: str, nodes: list, tree_patch: str, gate) -> dict:
    T = _T()
    with gate, T.work_dir("ghp") as wd:
        tree = T.fresh_ws(T.base_ws(tid, with_test_patch=True), wd)
        if tree_patch.strip():
            rc, err = T.harness_apply(tree, tree_patch)
            if rc != 0:
                return {"error": clean_why(f"tree patch does not apply on the hidden-test base: {err}")}
        return T.hidden_outcomes(tree, nodes, T.sandbox_env(tree, tid, None))


def known_flaky_targets(test_files: list) -> list:
    """KNOWN_FLAKY nodes inside the task's grader target files: grading this task can hit a load-dependent flake.
    Deterministic, unlike a record of whether a given build's runs happened to hit it (those retries are logged by the
    builder and kept in the cache, never committed: a cold rebuild must write the same bytes)."""
    return sorted(n for n in KNOWN_FLAKY if n.split("::", 1)[0] in set(test_files))


def known_sets(tid: str) -> list:
    T = _T()
    return sorted(name for name in dir(T) if name.startswith("KNOWN_")
                  and isinstance(getattr(T, name), (set, frozenset, dict)) and tid in getattr(T, name))
