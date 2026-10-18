"""Run a Harness² sweep with the competition's agent (Gemma 4 on the A6000) as the executor.

    python -m h2g4.run RUNS_ROOT --only-domains tomlkit --max-tasks 8 --k 1 --modes sequential --dry-run
    python -m h2g4.run RUNS_ROOT --only-domains tomlkit --max-tasks 8 --k 1 --modes sequential        # on the box
    python -m h2g4.run RUNS_ROOT --only-domains tomlkit --k 1 --modes sequential --judge              # after the sweep

The improver comes from HARNESS2_IMPROVER_MODEL (+ HARNESS2_IMPROVER_KIND): an OpenCode provider/model id (Phase 1: Gemma on
the box's own vLLM, $0; Phase 2: an OpenRouter model, capped) or a bare Claude id for the Claude CLI on a normal login
(LocalClaudeProposer drops Harness²'s Vertex wiring). Harness² itself is pinned at 1cfe254 (README)."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from harness2.cli import _common as C
from harness2.cli.judge import collect_selections, judge_bases
from harness2.core import judge as J
from harness2.core import library as LIB
from harness2.core import schedule
from harness2.core.proposer import Proposer, ProposerError

from .swe import SweAdapter

VERTEX_ENV = ("CLAUDE_CODE_USE_VERTEX", "ANTHROPIC_VERTEX_PROJECT_ID", "CLOUD_ML_REGION", "GOOGLE_VERTEX_PROJECT",
              "GOOGLE_VERTEX_LOCATION", "VERTEXAI_LOCATION")


def _openrouter_get(path: str) -> dict:
    req = urllib.request.Request("https://openrouter.ai/api/v1/" + path,
                                 headers={"Authorization": "Bearer " + os.environ["OPENROUTER_API_KEY"]})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)["data"]


def openrouter_usage() -> float:
    """Dollars charged so far to the OPENROUTER_API_KEY on this machine (every billed request, retries included)."""
    return float(_openrouter_get("key")["usage"])


def openrouter_available() -> float:
    """Account credit left (total credits - total usage), the real ceiling whatever the key's own limit says."""
    d = _openrouter_get("credits")
    return float(d["total_credits"]) - float(d["total_usage"])


class BudgetStop(BaseException):
    """Ends the whole sweep: Harness² catches Exception (never BaseException) around stages and tasks, so this propagates
    out of run_sweep, while every task that already finished keeps its summary.json for --judge."""


class BudgetGuard:
    """A per-sweep dollar cap on improver sessions (Phase 2, OpenRouter). Before every session: stop the sweep if the key's
    usage since this sweep's start plus a margin reaches the budget (margin = max(fixed, 2 x the costliest session so far),
    since a session is paid after it runs and up to two can run at once), if the account's credit is below a reserve, or if
    either number cannot be read (never spend blind). The start is kept in <runs_root>/_budget.json, so a restarted sweep
    keeps counting from its own start."""

    def __init__(self, budget_usd: float, state: Path, usage=openrouter_usage, available=openrouter_available,
                 margin_usd: float = 3.0, reserve_usd: float = 10.0):
        self.budget, self.state, self.usage, self.available = float(budget_usd), Path(state), usage, available
        self.margin, self.reserve, self.max_session = float(margin_usd), float(reserve_usd), 0.0
        if self.state.is_file():
            self.start = float(json.loads(self.state.read_text())["start_usage"])
        else:
            self.start = self._read(self.usage, "key usage")
            self.state.parent.mkdir(parents=True, exist_ok=True)
            self.state.write_text(json.dumps({"start_usage": self.start, "budget_usd": self.budget, "t": time.time()}))

    @staticmethod
    def _read(fn, what: str) -> float:
        try:
            return float(fn())
        except Exception as e:                                   # noqa: BLE001 - any failure means we cannot account
            raise BudgetStop(f"h2g4: {what} unavailable ({type(e).__name__}: {e}); stopping rather than spending blind")

    def spent(self) -> float:
        return self._read(self.usage, "key usage") - self.start

    def check(self, label: str = "") -> float:
        spent = self.spent()
        margin = max(self.margin, 2 * self.max_session)
        if spent + margin >= self.budget:
            raise BudgetStop(f"h2g4 budget stop before session {label!r}: ${spent:.2f} spent + ${margin:.2f} margin "
                             f">= ${self.budget:.2f}")
        avail = self._read(self.available, "account credit")
        if avail < self.reserve:
            raise BudgetStop(f"h2g4 budget stop before session {label!r}: account credit ${avail:.2f} is below the "
                             f"${self.reserve:.2f} reserve")
        return spent

    def record(self, before: float, after: float) -> float:
        cost = max(0.0, after - before)
        self.max_session = max(self.max_session, cost)
        return cost


class LocalClaudeProposer(Proposer):
    """Harness²'s Proposer with its Vertex routing removed, so the claude_cli / opencode channels use the local login and
    the provider config already on the machine; optionally capped by a BudgetGuard (attribute `guard`), with every
    session's label, wall time and the key's spend so far appended to <audit_dir>/../_spend.jsonl."""

    guard = None

    def env(self) -> dict[str, str]:
        e = super().env()
        for k in VERTEX_ENV:
            e.pop(k, None)
        return e

    def call(self, mission, context_dir, label, **kw):
        if self.guard is None:
            return super().call(mission, context_dir, label, **kw)
        before = self.guard.check(label)
        rep = super().call(mission, context_dir, label, **kw)
        after = self.guard.spent()
        cost = self.guard.record(before, after)
        if self.audit_dir is not None:
            row = {"t": time.time(), "label": label, "ok": rep.ok, "wall_s": rep.wall_s, "session_usd": round(cost, 4),
                   "spent_usd": round(after, 4)}
            with open(Path(self.audit_dir).parent / "_spend.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
        return rep


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="h2g4.run", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("runs_root", type=Path)
    p.add_argument("--k", type=int, default=1)
    p.add_argument("--modes", default="sequential", help="sequential | parallel | both (comma list)")
    p.add_argument("--only-domains", default="")
    p.add_argument("--max-tasks", type=int)
    p.add_argument("--seed", type=int)
    p.add_argument("--dry-run", action="store_true", help="print the task stream; no rollouts, no sessions")
    p.add_argument("--judge", action="store_true", help="grade the runs selection chose (test verdicts), then summarise")
    p.add_argument("--smoke", action="store_true", help="one improver session with a trivial mission; prints the reply")
    p.add_argument("--evaluate", metavar="HARNESS_DIR", help="no improvement: run this harness tree once on every task of the "
                   "stream and record the box's verdicts ('base' = the unedited harness); the transfer test")
    p.add_argument("--label", default="", help="name of an --evaluate run (rollouts eval-<label>-<task>, table eval_<label>.json)")
    p.add_argument("--final-harness", metavar="DOMAIN", help="print the directory of the last harness this sweep adopted in "
                   "DOMAIN (the input of the transfer test), or nothing and exit 1 if none was adopted")
    return p


def modes_of(raw: str) -> tuple[str, ...]:
    return tuple(schedule.mode_token(m) for m in raw.replace("both", "sequential,parallel").split(",") if m.strip())


def final_harness(adapter: SweAdapter, k: int, seed, mode: str, domain: str) -> Path | None:
    """The adopted tree of the LAST task in stream order that has a library entry: <library>/<mode>/<domain>/harnesses/<task>/
    harness (harness2.core.library), i.e. what the sweep would hand the next task in this repository."""
    lib = LIB.Library(root=C.library_root_for(adapter, k, seed=seed) / mode, domain=domain, surface=adapter.substrate.surface())
    order = [t for t in adapter.tasks() if adapter.domain_of(t) == domain]
    have = [t for t in order if (lib.entry_dir(t) / "harness").is_dir()]
    return lib.entry_dir(have[-1]) / "harness" if have else None


def evaluate(adapter: SweAdapter, harness: Path | None, label: str, tasks: list[str]) -> int:
    """Run one harness once per task, with no improvement, and record the box's verdicts: the transfer test (GAPS, 18 Oct)."""
    rows = []
    for t in tasks:
        rd = adapter.execute(t, harness, f"eval-{label}-{t}")
        s = adapter.score(rd, t)
        rows.append({"task": t, "domain": adapter.domain_of(t), "run_dir": str(rd), "solved": None if s is None else s["all_pass"],
                     "delivered": adapter.delivered(rd)})
        print(f"{label} {t}: solved={rows[-1]['solved']} delivered={rows[-1]['delivered']}", flush=True)
    out = Path(adapter.runs_root) / f"eval_{label}.json"
    out.write_text(json.dumps({"label": label, "harness": str(harness or "base"), "rows": rows}, indent=2), encoding="utf-8")
    graded = [r for r in rows if r["solved"] is not None]
    print(f"{label}: solved {sum(r['solved'] for r in graded)}/{len(graded)} graded of {len(rows)}; table {out}")
    return 0


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    adapter = SweAdapter(a.runs_root)
    if a.smoke:
        prop = LocalClaudeProposer(adapter.spec.channels["proposer"], audit_dir=a.runs_root / "_audit_smoke")
        rep = prop.call("Reply with exactly the word READY and nothing else.", None, "smoke", timeout=600, max_attempts=1)
        print(f"smoke: ok={rep.ok} channel={rep.channel} model={adapter.spec.channels['proposer'].model} "
              f"wall={rep.wall_s}s reply={rep.text.strip()[:80]!r} error={rep.error[:200]!r}")
        return 0 if rep.ok and "READY" in rep.text else 1
    only = tuple(s.strip() for s in a.only_domains.split(",") if s.strip())
    by_domain = schedule.task_stream(adapter, split="all", seed=a.seed, only_domains=only, max_tasks=a.max_tasks)
    stream = [(d, t) for d, ts in by_domain.items() for t in ts]
    if a.final_harness:
        h = final_harness(adapter, a.k, a.seed, modes_of(a.modes)[0], a.final_harness)
        if h is None:
            return 1
        print(h)
        return 0
    if a.evaluate:
        if not a.label:
            print("error: --evaluate needs --label", file=sys.stderr)
            return 1
        return evaluate(adapter, None if a.evaluate == "base" else Path(a.evaluate), a.label, [t for _, t in stream])
    if a.dry_run:
        for i, (d, t) in enumerate(stream, 1):
            print(f"{i:>4}  {d:<24} {t}")
        print(f"# {len(stream)} tasks over {len(by_domain)} domains; k={a.k}; modes={modes_of(a.modes)}; "
              f"rollouts = 4k per task = {4 * a.k * len(stream)}, improver sessions = 3k per task = {3 * a.k * len(stream)}")
        return 0 if stream else 1
    if not stream:
        print("error: empty task stream", file=sys.stderr)
        return 1
    modes = modes_of(a.modes)
    runs_root = C.runs_root_for(adapter)                       # <RUNS_ROOT>/adapt, as the official CLI lays it out
    library_root = C.library_root_for(adapter, a.k, seed=a.seed)
    if a.judge:
        ns_dir = runs_root / C.summary_namespace(adapter, a.k, seed=a.seed)
        sels = collect_selections(ns_dir, modes)
        rows = J.judge_selections(adapter, sels, parallel=1)
        J.write(rows, ns_dir / "judged.json")
        judge_bases(adapter, ns_dir)                           # base_judged.json: the unedited harness on the same tasks
        chosen = sum(bool(r.all_pass) for r in rows)
        print(f"judged {len(rows)} selections: chosen run solved {chosen}; base runs in {ns_dir / 'base_judged.json'}")
        return 0
    prop = LocalClaudeProposer(adapter.spec.channels["proposer"], audit_dir=runs_root / "_audit")
    if os.environ.get("H2G4_BUDGET_USD"):
        prop.guard = BudgetGuard(float(os.environ["H2G4_BUDGET_USD"]), runs_root / "_budget.json")
        print(f"budget guard: ${prop.guard.budget:.2f} on top of key usage ${prop.guard.start:.2f}", flush=True)
    adapter.substrate.preflight()
    try:
        rep = schedule.run_sweep(a.k, adapter=adapter, prop=prop, runs_root=runs_root, library_root=library_root, split="all",
                                 modes=modes, seed=a.seed, tag="", domain_parallel=1, only_domains=only, max_tasks=a.max_tasks,
                                 pool_policy="finals")
    except BudgetStop as e:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        rec = runs_root / "_sweeps" / f"budget-stop-{stamp}.json"
        rec.parent.mkdir(parents=True, exist_ok=True)
        finished = sorted(p.parent.name for p in runs_root.glob("*/*/summary.json"))
        rec.write_text(json.dumps({"budget_stop": str(e), "finished_task_summaries": finished}, indent=2), encoding="utf-8")
        print(f"BUDGET STOP: {e}; {len(finished)} finished task summaries kept; record {rec}")
        return 3
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rec = runs_root / "_sweeps" / f"sweep-{stamp}.json"
    rec.parent.mkdir(parents=True, exist_ok=True)
    rec.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    done = sum(int(d.get("done", 0)) for d in rep["domains"])
    failed = sum(int(d.get("failed", 0)) for d in rep["domains"])
    print(f"sweep done: {done} tasks ok, {failed} failed; record {rec}")
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
