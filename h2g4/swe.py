"""Harness² benchmark adapter for SWE tasks run by the competition's agent on the A6000 box (harness2.core.spec.BenchmarkAdapter).

Refinement set: the held-out tasks from OTHER repositories (data/heldout1k/harness_s200, s200_valid_ids.txt: ~20 repos, never
the public 74), so whatever harness Harness² adopts is learned off the repos the public read uses. Domain = repository.
The improver never sees gold: task_prompt() is the issue text only, and the gold patch / FAIL_TO_PASS lists stay in
tasks.jsonl, which is never copied into a session. score() is the box's test verdict (FAIL_TO_PASS + PASS_TO_PASS) and is
used only by Harness²'s judge stage, after selection, exactly as the method separates them.

Rollouts run on the box through scripts/a6000/p2_race.py (the faithful Docker sandbox + the pace proxy), one at a time behind
a lock (one model, and the scorer is sequential)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from functools import lru_cache
from pathlib import Path

from harness2.core import tree as HT
from harness2.core.spec import BenchPrompts, BenchSpec, ChannelSpec, resolve_channel_model
from harness2.substrate.base import Install, RunRequest

from .adk import ADK_SURFACE, BASE_BUNDLE, AdkSubstrate, compose_bundle, tree_problems, validate_bundle

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "data" / "heldout1k" / "harness_s200"
IDS = ROOT / "data" / "heldout1k" / "s200_valid_ids.txt"
TASKS = ROOT / "data" / "heldout1k" / "tasks.jsonl"
# rendered trajectory cap per run: 60k chars is about 15k tokens; Phase 1 (Gemma as its own improver, 32k context, OpenCode
# overhead) sets H2G4_MAX_CHARS lower so a mission plus two trajectories fit
MAX_CHARS = int(os.environ.get("H2G4_MAX_CHARS") or 60_000)

SWE_PROMPTS = BenchPrompts(
    work=(
        "Maintenance of a Python library from an issue report: make the smallest correct change to the library's source "
        "in a sandboxed, offline checkout so that the behaviour the issue describes holds, within 5 minutes and 40 tool "
        "calls per issue. The issue text is the specification: its exact names, messages, types and behaviours. Test "
        "files are reset afterwards, so only source changes count, and an unedited tree delivers nothing."
    ),
    domain_word="repository",
    deliverable_word="source patch",
    inv_levers=(
        "- locate the code that produces the wrong behaviour within the first few calls, using targeted git grep for the "
        "issue's literal identifiers and messages, then read only the regions needed\n"
        "- make an edit early: a reasoned best-guess edit beats exploration that reaches the time limit with nothing "
        "written\n"
        "- check the change with one targeted test file or a python -c snippet, never a whole test suite\n"
        "- keep every step decisive: nearly all of the 5 minutes is spent generating text, so fewer and shorter steps "
        "leave room to finish\n"
        "- end with a source diff and submit_patch before the time runs out"
    ),
    dom_levers=(
        "- learn this repository's layout and idioms: where the public API is exported, how errors are raised and "
        "worded, and which parallel implementations (sync/async, Python and C fallbacks, overloads) must change "
        "together\n"
        "- note this repository's recurring traps: vendored or generated code, compatibility shims, version-dependent "
        "branches, slow or network-bound tests"
    ),
    yardstick=(
        "Did the run find the code responsible for the issue, change the library's source so that it implements the "
        "issue's exact names, messages and behaviour, check the change with a targeted command, leave the tests alone, "
        "and submit a non-empty patch before the time ran out?"
    ),
    selection_checks=(
        "Prefer the patch that changes the library source where the wrong behaviour is produced; implements the issue's "
        "literal names, messages, types and edge cases; leaves test files untouched; is minimal and internally "
        "consistent; and was checked by running code rather than asserted."
    ),
)


@lru_cache(maxsize=1)
def _records() -> dict[str, dict]:
    out = {}
    with open(TASKS, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                out[r["instance_id"]] = {"repo": r["repo"], "problem_statement": r["problem_statement"]}
    return out


def improver_channel() -> ChannelSpec:
    """HARNESS2_IMPROVER_MODEL (+ HARNESS2_IMPROVER_KIND, inferred from the id when unset: a provider-prefixed id is an
    OpenCode model, a bare one a Claude CLI model). Both unset = Harness²'s defaults (an empty model the Proposer refuses)."""
    model = os.environ.get("HARNESS2_IMPROVER_MODEL") or None
    kind = os.environ.get("HARNESS2_IMPROVER_KIND") or (None if model is None else ("opencode" if "/" in model else "claude_cli"))
    return resolve_channel_model(kind, model, effort="high", steps=int(os.environ.get("H2G4_IMPROVER_STEPS") or 60))


class RaceLauncher:
    """One rollout = one scripts/a6000/p2_race.py call for one task, the candidate bundle staged under
    submissions/_staging/h2_<fingerprint12>; serialised behind a lock."""

    def __init__(self, runs_root: Path, *, harness: Path = HARNESS, port: int = 8001, python: str = sys.executable,
                 dry: bool = False, stage_root: Path = ROOT / "submissions"):
        self.runs_root, self.harness, self.port, self.python, self.dry = Path(runs_root), Path(harness), port, python, dry
        self.stage_root = Path(stage_root)            # p2_race resolves an arm as submissions/<arm>; tests pass a tmp dir
        self.lock = threading.Lock()
        self.calls: list[list[str]] = []

    def arm(self, install: Install) -> str:
        return f"_staging/h2_{install.fingerprint[:12]}"

    def command(self, out: Path, ids_file: Path, arm: str) -> list[str]:
        return [self.python, str(ROOT / "scripts" / "a6000" / "p2_race.py"), str(out), "--harness", str(self.harness),
                "--ids", str(ids_file), "--arms", arm, "--conc", "1", "--port", str(self.port), "--keep",
                "--label", "h2"]

    def __call__(self, req: RunRequest, install: Install) -> list[Path]:
        arm = self.arm(install)
        dest = self.stage_root / arm
        dirs = []
        with self.lock:
            if not dest.is_dir():
                shutil.copytree(install.staging_dir, dest)
            for run_id in req.run_ids:
                out = self.runs_root / "rollouts" / run_id
                run_dir = out / "items" / arm / req.task_ref
                if not (run_dir / "task_results.jsonl").is_file():
                    out.mkdir(parents=True, exist_ok=True)
                    ids_file = out / "ids.txt"
                    ids_file.write_text(req.task_ref + "\n", encoding="utf-8")
                    cmd = self.command(out, ids_file, arm)
                    self.calls.append(cmd)
                    if not self.dry:
                        with open(out / "launch.log", "a", encoding="utf-8") as log:
                            subprocess.run(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                           timeout=int(req.timeout) + 900, check=False)
                dirs.append(run_dir)
        return dirs


class SweAdapter:
    def __init__(self, runs_root: Path, *, launcher=None, ids: Path = IDS, timeout: int = 600):
        self.runs_root = Path(runs_root)
        self.launcher = launcher or RaceLauncher(self.runs_root)
        self.substrate = AdkSubstrate(launcher=self.launcher)
        self.ids_file = Path(ids)
        self.timeout = timeout
        ch = improver_channel()
        self.spec = BenchSpec(name="swe-g4", runs_root=self.runs_root, install_mode="workspace_config", prompts=SWE_PROMPTS,
                              channels={"proposer": ch, "selector": ch}, domain_word="repository",
                              leak_globs=("tasks.jsonl", "*.patch_gold", "test_patch*"), allow_subagents=False,
                              obs_trunc=20_000)

    # --- the task stream
    def tasks(self, split: str = "all") -> list[str]:
        ids = [l.strip() for l in self.ids_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        recs = _records()
        return [i for i in ids if i in recs]

    def domain_of(self, task_id: str) -> str:
        return _records()[task_id]["repo"].split("/")[-1]

    def task_prompt(self, task_id: str) -> str:
        r = _records()[task_id]
        return f"Repository: {r['repo']}\n\nProblem statement:\n{r['problem_statement']}"

    def task_files(self, task_id: str) -> Path | None:
        return None

    # --- rollouts
    def execute(self, task_id: str, harness_dir: Path | None, run_id: str, *, timeout: int | None = None) -> Path:
        install = self.substrate.materialise(Path(harness_dir) if harness_dir else self.base_harness(), self.spec, {})
        try:
            return self.substrate.execute(task_id, install, [run_id], int(timeout or self.timeout))[0]
        finally:
            shutil.rmtree(install.staging_dir, ignore_errors=True)

    def _row(self, run_dir: Path) -> dict:
        p = Path(run_dir) / "task_results.jsonl"
        rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.is_file() else []
        return rows[-1] if rows else {}

    def delivered(self, run_dir: Path) -> bool:
        return int(self._row(run_dir).get("agent_patch_size") or 0) > 0

    def trajectory(self, run_dir: Path, *, obs_trunc: int) -> str:
        traces = sorted((Path(run_dir) / "traces").glob("trace_*.json"))
        if not traces:
            return "(no trajectory captured for this run)"
        return self.substrate.read_trajectory(traces[-1], obs_trunc=obs_trunc, max_chars=MAX_CHARS)

    def deliverable_files(self, run_dir: Path) -> dict[str, str]:
        return {p.name: p.read_text(encoding="utf-8", errors="replace") for p in sorted((Path(run_dir) / "patches").glob("*.patch"))}

    def deliverable_text(self, run_dir: Path) -> str:
        return "\n".join(self.deliverable_files(run_dir).values())

    # --- the harness
    def base_harness(self) -> Path:
        d = self.runs_root / "base_tree"
        if not HT.is_tree(ADK_SURFACE, d):
            tree = {"systemprompt.md": (BASE_BUNDLE / "prompts" / "system.md").read_text(encoding="utf-8")}
            HT.write_tree(ADK_SURFACE, tree, d)
        return d

    def validate_tree(self, tree: dict[str, str]) -> None:
        errs = tree_problems(tree)
        if not errs:
            tmp = self.runs_root / "_validate"
            shutil.rmtree(tmp, ignore_errors=True)
            try:
                compose_bundle(tree, tmp)
                validate_bundle(tmp)
            except ValueError as e:
                errs.append(str(e))
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        if errs:
            raise ValueError("Harness problems:\n- " + "\n- ".join(errs))

    def score(self, run_dir: Path, task_id: str) -> dict | None:
        row = self._row(run_dir)
        if not row or row.get("instance_id") not in (None, task_id):
            return None
        ok = bool(row.get("resolved"))
        return {"n_passed": int(ok), "n_criteria": 1, "all_pass": ok, "raw": row}
