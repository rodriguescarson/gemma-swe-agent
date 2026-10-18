"""h2g4: Harness² (google-research/harness2 @ 1cfe254) driving the competition's agent (GAPS 'Harness² pilot pre-registration',
2026-10-18). Pinned here, before any rollout: a tree composes into a bundle the official compiler accepts and whose prompt is
the tree's always-on text; the surface rejects what this runtime cannot carry; the fixed files (model, tools, 5-minute cap,
sampling) are never on the surface; the renderer reads a real held-out ATIF trace; the improver never sees gold; the launcher
stages the candidate and calls the race runner one task at a time; score() reads the box's verdict."""
import hashlib
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


def test_launcher_stages_per_rollout_and_calls_the_race_runner_per_run(tmp_path):
    from harness2.substrate.base import Install, RunRequest
    stage = tmp_path / "subs"
    src = compose_bundle({"systemprompt.md": V12_PROMPT}, tmp_path / "staged")
    L = RaceLauncher(tmp_path / "runs", dry=True, stage_root=stage)
    inst = Install(staging_dir=src, fingerprint="ab" * 32)
    dirs = L(RunRequest(task_ref="tomlkit_abc1234", run_ids=("r1", "r2"), timeout=600), inst)
    arms = [L.arm(inst, "r1"), L.arm(inst, "r2")]
    assert arms[0] != arms[1] and all(a.startswith("_h2_" + "ab" * 6 + "_") for a in arms)
    assert all((stage / a / "agent.yaml").is_file() for a in arms)
    assert [d.name for d in dirs] == ["tomlkit_abc1234", "tomlkit_abc1234"]
    assert [d.parent.name for d in dirs] == arms and all(d.parents[2] == L.out for d in dirs)
    assert len(L.calls) == 2
    cmd = L.calls[0]
    assert cmd[1].endswith("scripts/a6000/p2_race.py") and cmd[cmd.index("--conc") + 1] == "1"
    assert cmd[2] == str(L.out) and cmd[cmd.index("--label") + 1] == L.label
    assert cmd[cmd.index("--arms") + 1] == arms[0] and "--keep" in cmd
    assert Path(cmd[cmd.index("--ids") + 1]).read_text() == "tomlkit_abc1234\n"


def test_two_trees_and_one_tree_twice_never_share_an_arm_or_a_result(tmp_path):
    """2026-10-19 (box B-208): every candidate of task 1 ran as the base arm, and results landed in the rollout smoke's folder.
    Two different trees and the same tree twice must give three arms, three staged bundles and three item dirs, all under this
    root's race dir, each with a staged.json naming the fingerprint that ran."""
    from harness2.substrate.base import Install, RunRequest
    stage = tmp_path / "subs"
    a = compose_bundle({"systemprompt.md": V12_PROMPT}, tmp_path / "a")
    b = compose_bundle({"systemprompt.md": V12_PROMPT, "guardrails.md": "- Edit early.\n"}, tmp_path / "b")
    L = RaceLauncher(tmp_path / "runs", dry=True, stage_root=stage)
    ia, ib = Install(staging_dir=a, fingerprint="aa" * 32), Install(staging_dir=b, fingerprint="bb" * 32)
    dirs = []
    for inst, rid in ((ia, "base-0"), (ib, "inv1-0"), (ia, "base-1")):
        d = L(RunRequest(task_ref="arrow_06fe693", run_ids=(rid,), timeout=600), inst)[0]
        d.mkdir(parents=True, exist_ok=True)
        (d / "task_results.jsonl").write_text("{}\n")
        dirs.append(d)
    assert len({d.parent.name for d in dirs}) == 3 and len({str(d) for d in dirs}) == 3
    assert all(str(d).startswith(str((tmp_path / "runs" / "race").resolve())) for d in dirs)
    assert len(list(stage.glob("_h2_*"))) == 3
    L(RunRequest(task_ref="arrow_06fe693", run_ids=("inv1-0",), timeout=600), ib)        # a rerun writes the record
    rec = json.loads((dirs[1] / "staged.json").read_text())
    assert rec["fingerprint"] == "bb" * 32 and rec["run_id"] == "inv1-0" and rec["arm"] == dirs[1].parent.name
    assert rec["system_md_sha256"] == hashlib.sha256((stage / rec["arm"] / "prompts" / "system.md").read_bytes()).hexdigest()


def test_container_label_is_stable_within_a_root_and_differs_across_roots(tmp_path):
    a1 = RaceLauncher(tmp_path / "pilot1", dry=True)
    a2 = RaceLauncher(tmp_path / "pilot1", dry=True)
    b = RaceLauncher(tmp_path / "rollout_smoke", dry=True)
    assert a1.label == a2.label != b.label and a1.label.startswith("h2")
    assert a1.out == (tmp_path / "pilot1" / "race").resolve()


def _fake_bin(path: Path, body: str) -> str:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return str(path)


def test_a_rollout_whose_result_lands_elsewhere_raises(tmp_path):
    from harness2.substrate.base import Install, RunRequest
    src = compose_bundle({"systemprompt.md": V12_PROMPT}, tmp_path / "staged")
    L = RaceLauncher(tmp_path / "runs", dry=False, stage_root=tmp_path / "subs")
    L.docker = _fake_bin(tmp_path / "docker", "exit 1\n")                                 # no container
    elsewhere = tmp_path / "rollout_smoke" / "race"
    L.command = lambda ids_file, arm: ["/bin/sh", "-c", f'mkdir -p "{elsewhere}/items/{arm}/t1" && '
                                                        f'echo "{{}}" > "{elsewhere}/items/{arm}/t1/task_results.jsonl"']
    with pytest.raises(RuntimeError, match="no result"):
        L(RunRequest(task_ref="t1", run_ids=("r1",), timeout=60), Install(staging_dir=src, fingerprint="ab" * 32))
    L.command = lambda ids_file, arm: ["/bin/sh", "-c", f'mkdir -p "{L.out}/items/{arm}/t1" && '
                                                        f'echo "{{}}" > "{L.out}/items/{arm}/t1/task_results.jsonl"']
    d = L(RunRequest(task_ref="t1", run_ids=("r2",), timeout=60), Install(staging_dir=src, fingerprint="ab" * 32))[0]
    assert json.loads((d / "staged.json").read_text())["run_id"] == "r2"


def test_a_live_container_mounted_on_another_folder_is_removed_not_reused(tmp_path):
    log = tmp_path / "docker.log"
    L = RaceLauncher(tmp_path / "runs", dry=False, stage_root=tmp_path / "subs")
    L.docker = _fake_bin(tmp_path / "docker", f'echo "$@" >> "{log}"\n'
                         f'[ "$1" = inspect ] && echo "{tmp_path}/pilot1_failed_reuse/race"\nexit 0\n')
    L.ensure_container_mount()
    calls = log.read_text().splitlines()
    assert calls[0].startswith("inspect") and calls[1] == f"rm -f g4-{L.label}"
    log.write_text("")
    M = RaceLauncher(tmp_path / "runs2", dry=False)
    M.docker = _fake_bin(tmp_path / "docker2", f'echo "$@" >> "{log}"\n[ "$1" = inspect ] && echo "{M.out}"\nexit 0\n')
    M.ensure_container_mount()
    assert [c.split()[0] for c in log.read_text().splitlines()] == ["inspect"]          # its own folder: kept


def test_the_race_command_survives_the_containers_own_copies(tmp_path):
    """2026-10-19 (box B-206): inside its container p2_race runs `cp -r "/g4/$HARNESS" /root/h` and
    `cp -r /g4/submissions/$a /tmp/bundle_$a` with the repo mounted at /g4. An absolute --harness became /g4//home/... and every
    rollout's setup failed; an arm with a slash (the old _staging/h2_x) would fail the second copy for want of a parent dir.
    Both copies are replayed here against the real repo layout."""
    from harness2.substrate.base import Install
    L = RaceLauncher(tmp_path / "runs", dry=True)
    cmd = L.command(tmp_path / "ids.txt", L.arm(Install(staging_dir=tmp_path, fingerprint="cd" * 32), "inv1-0"))
    harness = cmd[cmd.index("--harness") + 1]
    arm = cmd[cmd.index("--arms") + 1]
    assert not harness.startswith("/") and (ROOT / harness / "manifest.json").is_file(), harness   # /g4/$HARNESS exists
    assert "/" not in arm and arm.startswith("_h2_"), arm                                           # /tmp/bundle_$a is flat
    assert (ROOT / "submissions").is_dir()                                                          # /g4/submissions/$a


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
    arms = [c[c.index("--arms") + 1] for c in L.calls]
    assert [a[-6:] for a in arms] == [hashlib.sha1(f"eval-base-{t}".encode()).hexdigest()[:6]
                                      for t in ("arrow_06fe693", "attrs_af9c510")]                 # one arm per run id
    assert [Path(c[c.index("--ids") + 1]).read_text() for c in L.calls] == ["arrow_06fe693\n", "attrs_af9c510\n"]
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


def _fake_session_proposer(tmp_path, monkeypatch, *, sleep_s, on_start=None):
    """A LocalClaudeProposer whose parent call() starts a child that looks like an OpenCode session (its argv carries
    src/index.ts) and waits for it, as Proposer._opencode does with subprocess.run."""
    import subprocess as sp
    import sys as _sys
    from harness2.core.proposer import Proposer, Reply
    from harness2.core.spec import ChannelSpec
    from h2g4.run import LocalClaudeProposer

    def fake_call(self, mission, context_dir, label, **kw):
        if on_start:
            on_start(label)
        t0 = time.time()
        p = sp.run([_sys.executable, "-c", f"import time; time.sleep({sleep_s})", "src/index.ts", "run", label])
        return Reply(label=label, text="" if p.returncode else "done", ok=p.returncode == 0, wall_s=round(time.time() - t0, 2))

    monkeypatch.setattr(Proposer, "call", fake_call)
    prop = LocalClaudeProposer(ChannelSpec("opencode", "openrouter/x/y"), audit_dir=tmp_path / "_audit")
    prop.poll_s = 0.2
    return prop


import time  # noqa: E402


def test_watchdog_kills_a_runaway_session_at_the_cap(tmp_path, monkeypatch):
    from h2g4.run import BudgetGuard, BudgetStop
    t0 = [None]
    prop = _fake_session_proposer(tmp_path, monkeypatch, sleep_s=30, on_start=lambda _: t0.__setitem__(0, time.time()))
    rate = 2.0                                                    # dollars per second while the session runs: a runaway
    usage = lambda: 0.0 if t0[0] is None else rate * (time.time() - t0[0])   # noqa: E731
    prop.guard = BudgetGuard(5.0, tmp_path / "b.json", usage=usage, available=lambda: 90.0, margin_usd=1.0)
    start = time.time()
    with pytest.raises(BudgetStop, match="DURING session"):
        prop.call("m", None, "expensive")
    wall = time.time() - start
    assert wall < 6, wall                                          # killed near the cap (2.5 s of spend), not after 30 s
    overshoot = usage() - 5.0
    assert overshoot < rate * 1.5, overshoot                       # roughly one poll interval plus the kill and join


def test_concurrent_sessions_cannot_both_pass_on_the_same_spend(tmp_path, monkeypatch):
    import threading as th
    from h2g4.run import BudgetGuard, BudgetStop
    spent = [0.0]
    prop = _fake_session_proposer(tmp_path, monkeypatch, sleep_s=0.3, on_start=lambda _: spent.__setitem__(0, spent[0] + 8.0))
    prop.guard = BudgetGuard(10.0, tmp_path / "b.json", usage=lambda: spent[0], available=lambda: 90.0, margin_usd=1.0)
    out = {}

    def go(name):
        try:
            out[name] = prop.call("m", None, name).ok
        except BudgetStop as e:
            out[name] = f"stop: {e}"

    ts = [th.Thread(target=go, args=(n,)) for n in ("a", "b")]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert sorted(v is True for v in out.values()) == [False, True], out    # one ran ($8), the other was refused
    assert spent[0] == 8.0
    rows = [json.loads(l) for l in (tmp_path / "_spend.jsonl").read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["session_usd"] == 8.0


def test_evaluate_freezes_the_harness_and_refuses_a_swap_under_the_same_label(tmp_path):
    from h2g4.adk import fingerprint
    from h2g4.run import evaluate
    L = RaceLauncher(tmp_path / "runs", dry=True, stage_root=tmp_path / "subs")
    ad = SweAdapter(tmp_path / "runs", launcher=L)
    cand = HT.write_tree(ADK_SURFACE, {"systemprompt.md": V12_PROMPT, "guardrails.md": "- Check edits.\n"}, tmp_path / "cand")
    assert evaluate(ad, cand, "fable", ["boltons_139d5dc"]) == 0
    frozen = tmp_path / "runs" / "frozen" / "fable"
    table = json.loads((tmp_path / "runs" / "eval_fable.json").read_text())
    assert table["harness"] == str(frozen) and table["fingerprint"] == fingerprint(HT.read_tree(ADK_SURFACE, cand))
    (cand / "guardrails.md").write_text("- Something else.\n")              # the source changes after freezing
    assert evaluate(ad, cand, "fable", ["boltons_139d5dc"]) == 1              # refused: a different tree under the label


def test_every_improver_prompt_builds_for_the_adk_surface():
    """2026-10-18 (box B-203): every Propose stage failed with "no prompt surface for 'adk'" because harness2's prompts keep a
    per-substrate text and h2g4 never registered one; the 20 tests above never built an improver prompt. This builds every
    prompt the recursion and selection use, in both prompt packs, through the real harness2 functions."""
    import dataclasses
    from harness2.core import prompts as P
    from h2g4.adk import ADK_SURFACE
    from h2g4.swe import SWE_PROMPTS
    for bp in (SWE_PROMPTS, dataclasses.replace(SWE_PROMPTS, prompt_pack="tts")):
        jobs = [P.propose(bp, "INV", ADK_SURFACE), P.propose(bp, "DOM", ADK_SURFACE),
                P.propose(bp, "INV", ADK_SURFACE, k=2, index=2), P.propose(bp, "DOM", ADK_SURFACE, round_t=1),
                P.aggregate(bp, ADK_SURFACE), P.compose_round(bp, ADK_SURFACE, t=1, k=1)]
        for j in jobs:
            assert isinstance(j, str) and len(j) > 500
        body = "\n".join(jobs)
        assert "run_skill_script" in body
        assert "plugin/<name>.ts" not in body and "`task` tool" not in body and "mode: subagent" not in body
    st = P._st(ADK_SURFACE)
    assert "NO CURLY BRACES" in st.surface_md and "5 minutes" in st.surface_md
    assert "__LOOP_LEVER__" not in st.inv and "__TRIGGER_SENTENCE__" not in st.dom


def test_the_adk_surface_text_matches_what_validation_enforces():
    """The rules the improver is told must be the rules tree_problems and harness2's skill check enforce."""
    from h2g4.adk import tree_problems
    from h2g4.prompts_adk import SURFACE_ADK
    assert "sub_agents/" in SURFACE_ADK and "plugin/" in SURFACE_ADK and "16,000 characters" in SURFACE_ADK
    errs = " | ".join(tree_problems({"systemprompt.md": "x", "sub_agents/a/AGENT.md": "a", "scripts/h.py": "x", "plugin/p.ts": "x"}))
    assert "sub-agents" in errs and "top-level scripts" in errs and "plugins" in errs


def test_h2g4_detaches_stdin_so_opencode_never_waits_for_eof(tmp_path):
    """2026-10-19 (box B-205): `opencode run` appends stdin to its message whenever stdin is not a TTY and waits for EOF;
    harness2 launches it without stdin=, so a launcher holding stdin open (a pipe that never closes) made every improver
    session wait forever. h2g4.run detaches its own stdin to /dev/null at start, so every child sees EOF at once. This runs a
    parent with an open stdin pipe that calls detach_stdin() and then starts a child that reads stdin to EOF."""
    import subprocess as sp
    import sys as _sys
    script = (
        "import subprocess, sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "from h2g4.run import detach_stdin\n"
        "detach_stdin()\n"
        "r = subprocess.run([sys.executable, '-c', 'import sys; sys.stdin.read(); print(\"EOF\")'], capture_output=True, text=True, timeout=10)\n"
        "print(r.stdout.strip())\n"
    )
    p = sp.Popen([_sys.executable, "-c", script], stdin=sp.PIPE, stdout=sp.PIPE, text=True)   # stdin stays open: never closed
    try:
        out = p.stdout.read()          # the parent exits within ~10 s either way (its child read has a 10 s timeout)
    finally:
        p.kill()
    assert out.strip() == "EOF", out
