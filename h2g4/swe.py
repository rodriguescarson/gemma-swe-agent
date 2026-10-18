"""Harness² benchmark adapter for SWE tasks run by the competition's agent on the A6000 box (harness2.core.spec.BenchmarkAdapter).

Refinement set: the held-out tasks from OTHER repositories (data/heldout1k/harness_s200, s200_valid_ids.txt: ~20 repos, never
the public 74), so whatever harness Harness² adopts is learned off the repos the public read uses. Domain = repository.
The improver never sees gold: task_prompt() is the issue text only, and the gold patch / FAIL_TO_PASS lists stay in
tasks.jsonl, which is never copied into a session. score() is the box's test verdict (FAIL_TO_PASS + PASS_TO_PASS) and is
used only by Harness²'s judge stage, after selection, exactly as the method separates them.

Rollouts run on the box through scripts/a6000/p2_race.py (the faithful Docker sandbox + the pace proxy), one at a time behind
a lock (one model, and the scorer is sequential)."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
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


DOCKER = "/usr/bin/docker"                    # as in scripts/a6000/p2_race.py


class RaceLauncher:
    """One rollout = one scripts/a6000/p2_race.py call for one task. Layout per sweep root, from p2_race's own behaviour
    (box B-206, B-208):
    - ONE output dir <runs_root>/race and ONE container g4-<label>, the label derived from runs_root. p2_race --keep reuses a
      live container whose /out mount was fixed when it was created, so a container must never be shared across output dirs
      (B-208: a container created by the rollout smoke swallowed every later sweep result).
    - ONE staged bundle per ROLLOUT, submissions/_h2_<fp12>_<run6> (flat: p2_race copies /g4/submissions/<arm> to
      /tmp/bundle_<arm>; unique per run: p2_race skips items whose results already exist, so two rollouts of one harness on one
      task must not share an item dir).
    - --harness repo-relative (p2_race copies "/g4/$HARNESS").
    - After each call the result must exist at <runs_root>/race/items/<arm>/<task>, or the rollout raises (recorded by
      harness2 as a dead rollout, never as a silent miss); staged.json beside it records run_id, arm, fingerprint and the
      sha256 of the staged prompts/system.md, so the archive proves which harness ran.
    Rollouts are serialised behind a lock (one model; the scorer is sequential)."""

    def __init__(self, runs_root: Path, *, harness: Path = HARNESS, port: int = 8001, python: str = sys.executable,
                 dry: bool = False, stage_root: Path = ROOT / "submissions"):
        self.runs_root, self.harness, self.port, self.python, self.dry = Path(runs_root), Path(harness), port, python, dry
        self.stage_root = Path(stage_root)            # p2_race resolves an arm as submissions/<arm>; tests pass a tmp dir
        self.out = (self.runs_root / "race").resolve()
        self.label = "h2" + hashlib.sha1(str(self.runs_root.resolve()).encode()).hexdigest()[:8]
        self.lock = threading.Lock()
        self.calls: list[list[str]] = []
        self.docker = DOCKER
        self._mount_checked = False

    def container_out(self) -> str | None:
        """Host path mounted at /out in the live g4-<label> container, or None if there is no such container."""
        r = subprocess.run([self.docker, "inspect", "-f", '{{range .Mounts}}{{if eq .Destination "/out"}}{{.Source}}{{end}}{{end}}',
                            f"g4-{self.label}"], capture_output=True, text=True, check=False)
        if r.returncode != 0:
            return None
        return r.stdout.strip() or None

    def ensure_container_mount(self) -> None:
        """A bind mount follows the directory, not its path: after `mv root root_failed` a live container with this root's label
        still writes into root_failed/race. Remove any g4-<label> container whose /out is not this root's race dir."""
        if self._mount_checked:
            return
        src = self.container_out()
        if src is not None and Path(src).resolve() != self.out:
            subprocess.run([self.docker, "rm", "-f", f"g4-{self.label}"], capture_output=True, check=False)
        self._mount_checked = True

    def arm(self, install: Install, run_id: str) -> str:
        return f"_h2_{install.fingerprint[:12]}_{hashlib.sha1(run_id.encode()).hexdigest()[:6]}"

    def harness_arg(self) -> str:
        return str(Path(self.harness).resolve().relative_to(ROOT.resolve()))

    def command(self, ids_file: Path, arm: str) -> list[str]:
        return [self.python, str(ROOT / "scripts" / "a6000" / "p2_race.py"), str(self.out), "--harness", self.harness_arg(),
                "--ids", str(ids_file), "--arms", arm, "--conc", "1", "--port", str(self.port), "--keep",
                "--label", self.label]

    def __call__(self, req: RunRequest, install: Install) -> list[Path]:
        dirs = []
        with self.lock:
            for run_id in req.run_ids:
                arm = self.arm(install, run_id)
                dest = self.stage_root / arm
                if not dest.is_dir():
                    shutil.copytree(install.staging_dir, dest)
                run_dir = self.out / "items" / arm / req.task_ref
                if not (run_dir / "task_results.jsonl").is_file():
                    self.out.mkdir(parents=True, exist_ok=True)
                    ids_file = self.out / f"ids_{arm}.txt"
                    ids_file.write_text(req.task_ref + "\n", encoding="utf-8")
                    cmd = self.command(ids_file, arm)
                    self.calls.append(cmd)
                    if not self.dry:
                        self.ensure_container_mount()
                        with open(self.out / "launch.log", "a", encoding="utf-8") as log:
                            log.write(f"== {run_id} {arm} {req.task_ref}\n")
                            log.flush()
                            subprocess.run(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                           timeout=int(req.timeout) + 900, check=False)
                        if not (run_dir / "task_results.jsonl").is_file():
                            raise RuntimeError(f"rollout {run_id}: no result at {run_dir}; see {self.out}/race.log and launch.log")
                if run_dir.is_dir():
                    sysmd = dest / "prompts" / "system.md"
                    (run_dir / "staged.json").write_text(json.dumps({
                        "run_id": run_id, "arm": arm, "fingerprint": install.fingerprint,
                        "system_md_sha256": hashlib.sha256(sysmd.read_bytes()).hexdigest() if sysmd.is_file() else None,
                        "skills": sorted(x.name for x in (dest / "skills").iterdir()) if (dest / "skills").is_dir() else []},
                        indent=1), encoding="utf-8")
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
            # a private directory per call: harness2 validates parallel candidates (INV and DOM) in threads, and a shared
            # fixed directory let one thread delete what the other was compiling (found by tests/test_h2g4_end_to_end.py)
            self.runs_root.mkdir(parents=True, exist_ok=True)
            tmp = Path(tempfile.mkdtemp(prefix="_validate-", dir=self.runs_root))
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
