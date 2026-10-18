"""h2g4 end to end, offline: harness2's own domain driver (schedule.run_domain, the call run_sweep makes on the box) runs a full
Propose -> Probe -> Compose -> Select -> Reflect cycle on one held-out task through SweAdapter + AdkSubstrate, with a scripted
proposer (in the style of harness2.demo.DemoProposer) and a fake launcher that writes the run folders p2_race writes and compiles
every candidate bundle with the official validator. Written after the box's first sweep died on "no prompt surface for 'adk'"
(B-203): any further integration gap must fail here, on the Mac, not on the box."""
import json
from pathlib import Path

import pytest

pytest.importorskip("harness2")

from harness2.cli import _common as C  # noqa: E402
from harness2.core import schedule  # noqa: E402
from harness2.core.proposer import Proposer, Reply  # noqa: E402
from harness2.core.spec import ChannelSpec  # noqa: E402

from h2g4.adk import validate_bundle  # noqa: E402
from h2g4.swe import SweAdapter  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HAS_HELDOUT = (ROOT / "data/heldout1k/tasks.jsonl").is_file()
TASK = "arrow_06fe693"


class ScriptedProposer(Proposer):
    """Edits guardrails.md in proposals and compositions, picks the first candidate, writes one lesson."""

    def call(self, mission, context_dir, label, **kwargs):
        ctx = Path(context_dir)
        workspace = None
        if label.startswith("select."):
            stems = sorted(p.stem for p in (ctx / "candidates").glob("*.md"))
            text = f"<why>first candidate</why>\n```choice\n{stems[0]}\n```"
        elif label.startswith("experience."):
            text = ("<edits>\ncomponent: guardrails.md\ncandidates: inv1\nchange: edit early\nobserved: test\nverdict: helped\n</edits>\n\n"
                    "<experience>\ncue: When a fix is located\nlesson: Edit before reading further.\nevidence: scripted\n"
                    "confidence: low\n</experience>")
        else:
            workspace = ctx / "harness"
            g = workspace / "guardrails.md"
            g.write_text(g.read_text() + "- Make the source edit before the third minute.\n", encoding="utf-8")
            text = "<notes>scripted: edit early</notes>"
        rep = Reply(label=label, text=text, ok=True, attempts=1, workspace=workspace)
        self._calls.append(rep)
        return rep


class FakeLauncher:
    """Writes what p2_race writes for one task (task_results.jsonl, a patch, an ATIF trace) after compiling the candidate."""

    def __init__(self, root: Path):
        self.root, self.calls, self.compiled = root, [], 0

    def __call__(self, req, install):
        validate_bundle(Path(install.staging_dir))
        self.compiled += 1
        dirs = []
        for run_id in req.run_ids:
            d = self.root / "rollouts" / run_id / "items" / f"_staging/h2_{install.fingerprint[:12]}" / req.task_ref
            (d / "traces").mkdir(parents=True, exist_ok=True)
            (d / "patches").mkdir(exist_ok=True)
            solved = "guardrails" in (Path(install.staging_dir) / "prompts" / "system.md").read_text() and "third minute" in \
                (Path(install.staging_dir) / "prompts" / "system.md").read_text()
            (d / "task_results.jsonl").write_text(json.dumps({"instance_id": req.task_ref, "resolved": solved,
                                                              "agent_patch_size": 40}) + "\n")
            (d / "patches" / f"{req.task_ref}.patch").write_text("diff --git a/arrow/x.py b/arrow/x.py\n+fix\n")
            (d / "traces" / f"trace_{req.task_ref}.json").write_text(json.dumps({"steps": [
                {"source": "agent", "message": "Looking at the parser.", "extra": {},
                 "tool_calls": [{"function_name": "run_command", "arguments": {"command": "git grep -n parse"}}],
                 "observation": {"content": json.dumps({"status": "ok", "stdout": "arrow/x.py:1: def parse"})}}]}))
            self.calls.append((req.task_ref, run_id))
            dirs.append(d)
        return dirs


@pytest.mark.skipif(not HAS_HELDOUT, reason="needs data/heldout1k/tasks.jsonl")
def test_a_full_sequential_cycle_runs_through_the_adk_adapter(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS2_IMPROVER_MODEL", "local/scripted")        # as on the box: one channel for improver and selector
    monkeypatch.delenv("HARNESS2_IMPROVER_KIND", raising=False)
    launcher = FakeLauncher(tmp_path / "runs")
    ad = SweAdapter(tmp_path / "runs", launcher=launcher)
    prop = ScriptedProposer(ad.spec.channels["proposer"], audit_dir=tmp_path / "audit")
    assert schedule._selector_for(ad, prop, None) is prop     # selection reuses the (budget-guarded) proposer, never a fresh one
    rep = schedule.run_domain("arrow", [TASK], 1, adapter=ad, prop=prop, runs_root=C.runs_root_for(ad),
                              library_root=C.library_root_for(ad, 1, seed=None), modes=("seq",))
    assert not rep.get("error"), rep
    assert int(rep.get("done", 0)) == 1, rep
    summaries = list(C.runs_root_for(ad).glob(f"*/{TASK}/summary.json"))
    assert summaries, "no summary.json written"
    assert len(launcher.calls) >= 4, launcher.calls                     # k = 1: base + 2 probes + composition
    assert launcher.compiled >= 3                                       # every distinct candidate compiled
    labels = [c.label for c in prop._calls]
    stages = [l.split(".")[0] for l in labels]                            # k = 1 sequential: no selection stage
    assert sorted(stages[:2]) == ["dom1", "inv1"] and stages[2:] == ["c1", "experience"], labels   # INV and DOM run in parallel
    lib = C.library_root_for(ad, 1, seed=None) / "seq" / "arrow" / "harnesses" / TASK / "harness" / "guardrails.md"
    assert lib.is_file() and "third minute" in lib.read_text()           # the adopted tree reached the library
