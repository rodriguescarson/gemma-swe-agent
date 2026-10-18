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
import sys
from datetime import datetime, timezone
from pathlib import Path

from harness2.cli import _common as C
from harness2.cli.judge import collect_selections, judge_bases
from harness2.core import judge as J
from harness2.core import schedule
from harness2.core.proposer import Proposer

from .swe import SweAdapter

VERTEX_ENV = ("CLAUDE_CODE_USE_VERTEX", "ANTHROPIC_VERTEX_PROJECT_ID", "CLOUD_ML_REGION", "GOOGLE_VERTEX_PROJECT",
              "GOOGLE_VERTEX_LOCATION", "VERTEXAI_LOCATION")


class LocalClaudeProposer(Proposer):
    """Harness²'s Proposer with its Vertex routing removed, so the claude_cli / opencode channels use the local login and
    the provider config already on the machine."""

    def env(self) -> dict[str, str]:
        e = super().env()
        for k in VERTEX_ENV:
            e.pop(k, None)
        return e


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
    return p


def modes_of(raw: str) -> tuple[str, ...]:
    return tuple(schedule.mode_token(m) for m in raw.replace("both", "sequential,parallel").split(",") if m.strip())


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
    adapter.substrate.preflight()
    rep = schedule.run_sweep(a.k, adapter=adapter, prop=prop, runs_root=runs_root, library_root=library_root, split="all",
                             modes=modes, seed=a.seed, tag="", domain_parallel=1, only_domains=only, max_tasks=a.max_tasks,
                             pool_policy="finals")
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
