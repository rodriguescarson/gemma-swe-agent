"""h2g4: Harness² (google-research/harness2 @ 1cfe254) driving the competition's agent (GAPS 'Harness² pilot pre-registration',
2026-10-18). Pinned here, before any rollout: a tree composes into a bundle the official compiler accepts and whose prompt is
the tree's always-on text; the surface rejects what this runtime cannot carry; the fixed files (model, tools, 5-minute cap,
sampling) are never on the surface; the renderer reads a real held-out ATIF trace; the improver never sees gold; the launcher
stages the candidate and calls the race runner one task at a time; score() reads the box's verdict."""
import json
import os
import shutil
from pathlib import Path

import pytest

pytest.importorskip("harness2")

from harness2.core import tree as HT  # noqa: E402

from h2g4.adk import ADK_SURFACE, ALWAYS_ON_MAX, BASE_BUNDLE, FIXED, compose_bundle, render_atif, tree_problems, validate_bundle  # noqa: E402
from h2g4.swe import RaceLauncher, SweAdapter, _records  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
V12_PROMPT = (BASE_BUNDLE / "prompts" / "system.md").read_text(encoding="utf-8")
TRACE = ROOT / "eval/a6000/results/p2/items/v4h2/attrs_af9c510/traces/trace_attrs_af9c510.json"
ROW = ROOT / "eval/a6000/results/p3/items/v7/arrow_197bd64__s2"
HAS_HELDOUT = (ROOT / "data/heldout1k/tasks.jsonl").is_file()


def test_base_tree_composes_to_v12_and_compiles(tmp_path):
    b = compose_bundle({"systemprompt.md": V12_PROMPT}, tmp_path / "b")
    assert (b / "prompts" / "system.md").read_text() == V12_PROMPT.strip() + "\n"
    for rel in FIXED:
        assert (b / rel).read_bytes() == (BASE_BUNDLE / rel).read_bytes(), rel
    out = validate_bundle(b)
    assert "tools=['run_command', 'read_file', 'edit_file', 'write_file', 'get_status', 'submit_patch']" in out


def test_always_on_files_join_in_order_and_skills_are_declared(tmp_path):
    tree = {"systemprompt.md": V12_PROMPT, "guardrails.md": "- Never edit test files.\n",
            "tool_descriptions/tool_guidance.md": "- Prefer git grep -n.\n",
            "skills/repro-check/SKILL.md": "---\nname: repro-check\ndescription: run a one-line reproduction\n---\nUse it.\n",
            "skills/repro-check/scripts/check.py": "import sys\nprint('ok', sys.argv[1:])\n"}
    b = compose_bundle(tree, tmp_path / "b")
    body = (b / "prompts" / "system.md").read_text()
    assert body.index(V12_PROMPT.strip()[:40]) < body.index("Never edit test files") < body.index("Prefer git grep")
    assert (b / "agent.yaml").read_text().rstrip().endswith("skills: [skills/repro-check]")
    assert (b / "skills/repro-check/scripts/check.py").is_file()
    validate_bundle(b)


def test_surface_rejects_what_the_runtime_cannot_carry():
    errs = " | ".join(tree_problems({"systemprompt.md": "Fix {thing}.", "scripts/helper.py": "x = 1\n",
                                     "sub_agents/a/AGENT.md": "a", "plugin/p.ts": "x", "skills/s/data.bin": "x"}))
    for needle in ("top-level scripts", "sub-agents", "plugins", "skill files must be", "brace"):
        assert needle in errs, needle
    assert "all empty" in " ".join(tree_problems({"guardrails.md": "  "}))
    assert "over the" in " ".join(tree_problems({"systemprompt.md": "x" * (ALWAYS_ON_MAX + 1)}))


def test_fixed_files_are_not_on_the_editable_surface():
    for rel in FIXED + ("prompts/system.md",):
        assert not HT.is_allowed(ADK_SURFACE, rel), rel
    assert HT.is_allowed(ADK_SURFACE, "guardrails.md") and HT.is_allowed(ADK_SURFACE, "skills/x/SKILL.md")


@pytest.mark.skipif(not TRACE.is_file(), reason="needs a held-out trace from the box")
def test_renderer_reads_a_real_heldout_trace():
    out = render_atif(TRACE, obs_trunc=20_000, max_chars=60_000)
    assert "[ACTION] run_command(" in out and "[OBSERVATION ERROR]" in out
    short = render_atif(TRACE, obs_trunc=200, max_chars=1_000)
    assert len(short) < 1_200 and "render truncation" in short
    assert render_atif(TRACE.with_name("missing.json"), obs_trunc=1, max_chars=1).startswith("(failed to read")


@pytest.mark.skipif(not HAS_HELDOUT, reason="needs data/heldout1k/tasks.jsonl")
def test_adapter_stream_domains_and_no_gold_in_prompts(tmp_path, monkeypatch):
    monkeypatch.delenv("HARNESS2_IMPROVER_MODEL", raising=False)
    monkeypatch.delenv("HARNESS2_IMPROVER_KIND", raising=False)
    ad = SweAdapter(tmp_path, launcher=RaceLauncher(tmp_path, dry=True, stage_root=tmp_path / "subs"))
    ids = ad.tasks()
    assert len(ids) >= 150 and len(set(ids)) == len(ids)
    public = set((ROOT / "data" / "kaggle_valid_ids.txt").read_text().split())
    assert not public & set(ids)                                        # refinement never touches the public 74
    full = [json.loads(l) for l in open(ROOT / "data/heldout1k/tasks.jsonl") if json.loads(l)["instance_id"] in set(ids[:25])]
    for r in full:
        t = r["instance_id"]
        p = ad.task_prompt(t)
        assert r["problem_statement"][:80] in p
        assert r["patch"][:200] not in p and r["test_patch"][:200] not in p and "FAIL_TO_PASS" not in p
        assert ad.domain_of(t) == r["repo"].split("/")[-1]
    assert set(_records()[ids[0]]) == {"repo", "problem_statement"}          # gold is never even held in memory


def test_launcher_stages_once_and_calls_the_race_runner_per_run(tmp_path):
    from harness2.substrate.base import Install, RunRequest
    stage = tmp_path / "subs"
    src = compose_bundle({"systemprompt.md": V12_PROMPT}, tmp_path / "staged")
    L = RaceLauncher(tmp_path / "runs", dry=True, stage_root=stage)
    inst = Install(staging_dir=src, fingerprint="ab" * 32)
    dirs = L(RunRequest(task_ref="tomlkit_abc1234", run_ids=("r1", "r2"), timeout=600), inst)
    assert (stage / "_staging" / ("h2_" + "ab" * 6) / "agent.yaml").is_file()
    assert [d.name for d in dirs] == ["tomlkit_abc1234", "tomlkit_abc1234"]
    assert dirs[0].parent.name == "h2_" + "ab" * 6 and dirs[0].parents[3].name == "r1"
    assert len(L.calls) == 2
    cmd = L.calls[0]
    assert cmd[1].endswith("scripts/a6000/p2_race.py") and cmd[cmd.index("--conc") + 1] == "1"
    assert cmd[cmd.index("--arms") + 1] == "_staging/h2_" + "ab" * 6 and "--keep" in cmd
    assert (Path(cmd[2]) / "ids.txt").read_text() == "tomlkit_abc1234\n"


@pytest.mark.skipif(not ROW.is_dir(), reason="needs a race item from the box")
def test_score_and_delivered_read_the_box_verdict(tmp_path):
    ad = SweAdapter(tmp_path, launcher=RaceLauncher(tmp_path, dry=True, stage_root=tmp_path / "subs"))
    s = ad.score(ROW, "arrow_197bd64")
    assert s == {"n_passed": 0, "n_criteria": 1, "all_pass": False, "raw": s["raw"]} and s["raw"]["instance_id"] == "arrow_197bd64"
    assert ad.score(ROW, "some_other_task") is None
    assert ad.delivered(ROW) is True and "diff --git" in ad.deliverable_text(ROW)
    assert ad.score(tmp_path / "nothing", "x") is None and ad.delivered(tmp_path / "nothing") is False


def test_base_harness_is_v12s_prompt_and_validates(tmp_path):
    ad = SweAdapter(tmp_path, launcher=RaceLauncher(tmp_path, dry=True, stage_root=tmp_path / "subs"))
    tree = HT.read_tree(ADK_SURFACE, ad.base_harness())
    assert tree["systemprompt.md"] == V12_PROMPT
    ad.validate_tree(tree)
    with pytest.raises(ValueError, match="brace"):
        ad.validate_tree({"systemprompt.md": "Fix {x}"})


def test_improver_channel_needs_kind_and_model_together(monkeypatch):
    from h2g4.swe import improver_channel
    monkeypatch.setenv("HARNESS2_IMPROVER_MODEL", "vllm/gemma-4-31b")
    monkeypatch.delenv("HARNESS2_IMPROVER_KIND", raising=False)
    assert improver_channel().kind == "opencode"
    monkeypatch.setenv("HARNESS2_IMPROVER_MODEL", "claude-sonnet-5-5")
    assert improver_channel().kind == "claude_cli"


def test_budget_guard_counts_from_the_sweeps_own_start_and_stops_with_a_margin(tmp_path):
    from h2g4.run import BudgetGuard, BudgetStop
    usage = iter([100.0, 104.0, 106.9, 107.0])
    g = BudgetGuard(10.0, tmp_path / "_budget.json", usage=lambda: next(usage), available=lambda: 90.0, margin_usd=3.0)
    assert g.start == 100.0 and g.check("a") == 4.0 and g.check("b") == pytest.approx(6.9)   # 6.9 + 3 < 10
    with pytest.raises(BudgetStop, match="margin"):
        g.check("c")                                                                          # 7.0 + 3 >= 10
    g2 = BudgetGuard(10.0, tmp_path / "_budget.json", usage=lambda: 105.0, available=lambda: 90.0)   # restart keeps its start
    assert g2.start == 100.0 and g2.spent() == 5.0


def test_budget_guard_margin_grows_with_the_costliest_session(tmp_path):
    from h2g4.run import BudgetGuard, BudgetStop
    g = BudgetGuard(20.0, tmp_path / "b.json", usage=lambda: 0.0, available=lambda: 90.0, margin_usd=1.0)
    assert g.record(2.0, 6.0) == 4.0 and g.max_session == 4.0
    g.usage = lambda: 11.5                                       # 11.5 + 2 x 4 = 19.5 < 20 passes; 12.0 + 8 = 20 stops
    g.check("ok")
    g.usage = lambda: 12.0
    with pytest.raises(BudgetStop):
        g.check("stop")


def test_budget_guard_stops_on_low_account_credit_and_on_blind_accounting(tmp_path):
    from h2g4.run import BudgetGuard, BudgetStop
    g = BudgetGuard(50.0, tmp_path / "b.json", usage=lambda: 0.0, available=lambda: 9.0, reserve_usd=10.0)
    with pytest.raises(BudgetStop, match="reserve"):
        g.check("x")
    def boom():
        raise OSError("network down")
    g.available = boom
    with pytest.raises(BudgetStop, match="spending blind"):
        g.check("y")
    with pytest.raises(BudgetStop, match="spending blind"):
        BudgetGuard(5.0, tmp_path / "fresh.json", usage=boom, available=lambda: 50.0)


def test_budget_stop_escapes_harness2s_exception_handlers():
    from h2g4.run import BudgetStop
    assert not issubclass(BudgetStop, Exception)
    with pytest.raises(BudgetStop):
        try:
            raise BudgetStop("x")
        except Exception:                                          # what every Harness² stage and task handler catches
            pytest.fail("BudgetStop must not be caught as an Exception")


def test_evaluate_runs_each_task_once_with_a_fixed_harness(tmp_path, capsys):
    from h2g4.run import evaluate
    L = RaceLauncher(tmp_path / "runs", dry=True, stage_root=tmp_path / "subs")
    ad = SweAdapter(tmp_path / "runs", launcher=L)
    rc = evaluate(ad, None, "base", ["arrow_06fe693", "attrs_af9c510"])
    assert rc == 0 and len(L.calls) == 2
    assert [Path(c[2]).name for c in L.calls] == ["eval-base-arrow_06fe693", "eval-base-attrs_af9c510"]
    table = json.loads((tmp_path / "runs" / "eval_base.json").read_text())
    assert table["harness"] == "base" and [r["solved"] for r in table["rows"]] == [None, None]   # dry: no verdict, not a zero


def test_improver_steps_default_and_override(monkeypatch):
    from h2g4.swe import improver_channel
    monkeypatch.setenv("HARNESS2_IMPROVER_MODEL", "openrouter/anthropic/claude-fable-5.1")
    monkeypatch.delenv("H2G4_IMPROVER_STEPS", raising=False)
    assert improver_channel().steps == 60
    monkeypatch.setenv("H2G4_IMPROVER_STEPS", "30")
    assert improver_channel().steps == 30 and improver_channel().kind == "opencode"


def test_final_harness_is_the_last_adopted_tree_in_stream_order(tmp_path):
    from harness2.cli import _common as C
    from harness2.core import library as LIB
    from h2g4.run import final_harness
    ad = SweAdapter(tmp_path / "runs", launcher=RaceLauncher(tmp_path / "runs", dry=True, stage_root=tmp_path / "subs"))
    assert final_harness(ad, 1, None, "seq", "arrow") is None
    lib = LIB.Library(root=C.library_root_for(ad, 1, seed=None) / "seq", domain="arrow", surface=ADK_SURFACE)
    arrow = [t for t in ad.tasks() if ad.domain_of(t) == "arrow"]
    for t, body in ((arrow[0], "first"), (arrow[2], "third")):
        HT.write_tree(ADK_SURFACE, {"systemprompt.md": body}, lib.entry_dir(t) / "harness")
    h = final_harness(ad, 1, None, "seq", "arrow")
    assert h == lib.entry_dir(arrow[2]) / "harness" and HT.read_tree(ADK_SURFACE, h)["systemprompt.md"] == "third"
