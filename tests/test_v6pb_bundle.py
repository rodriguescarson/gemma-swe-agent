"""v6p-b (docs/v4h/GATE.md, P2 addendum 6): v6p rebased on v4h2, thinking OFF, a fixed tool-call share per stage inside the 70-call total, the locator and
the verifier keep a reserved share, and the remaining fixers stop once one of them passes its tests. Written before the bundle (strict test-first).

The harness counts every tool call of every agent against ONE budget (swegemma/tools/base.py budget_gated) and compile_submission is given no callback
registry, so a per-agent cap cannot be enforced by the harness: it lives in the helper scripts (a per-fixer call ledger in _budget.py) and in the text of
the tool results the model reads."""
import importlib.util, json, os, re, subprocess, sys, textwrap, time
from pathlib import Path

import pytest
import yaml

sys.dont_write_bytecode = True                       # a .pyc inside the bundle makes the official validator refuse it
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

ROOT = Path(__file__).resolve().parent.parent
SUB = ROOT / "submissions"
V4H2, V6P, B = SUB / "v4h2", SUB / "v6p", SUB / "v6p-b"
SCRIPTS = B / "skills" / "swe-tools" / "scripts"
FIXERS = ("fixer_a", "fixer_b", "fixer_c")
TEMPS = {"fixer_a": 0.2, "fixer_b": 0.6, "fixer_c": 0.9}
BUDGET = 70


@pytest.fixture(autouse=True)
def _no_pycache():
    import shutil
    for d in B.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)
    yield
    for d in B.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)


def test_the_bundle_has_no_compiled_files():
    assert not list(B.rglob("*.pyc"))


def _yaml(p):
    return yaml.safe_load(re.sub(r"!include\s+\S+", "INCLUDED", p.read_text()))


def _budget_mod():
    spec = importlib.util.spec_from_file_location("bundle_budget", SCRIPTS / "_budget.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def _compile(b):
    from unittest.mock import MagicMock
    from adk_submission import compile_submission, discover_adapters
    from swegemma.config import ALLOWED_ADAPTER_EXTENSIONS, build_submission_limits
    from swegemma.models import setup_gemma_model_registry
    from swegemma.tools import create_tools
    limits, gen = build_submission_limits()
    return compile_submission(submission_dir=str(b), adapter_manifest=discover_adapters(str(b), ALLOWED_ADAPTER_EXTENSIONS),
                              tool_registry=create_tools(MagicMock()), model_registry=setup_gemma_model_registry(), limits=limits, generation_constraints=gen)


# ------------------------------------------------------------------------------------------------ the shares
def test_shares_sum_to_at_most_70_and_leave_the_downstream_stages_their_calls_even_when_every_capped_stage_overshoots():
    s = _budget_mod().SHARES
    nominal = s["setup"] + s["locator"] + 3 * s["fixer"] + s["selector"] + s["verifier"]
    assert nominal <= BUDGET, nominal
    # worst case: the locator and every fixer overshoot their share by the allowance (raw run_command calls the helper ledger cannot see)
    worst = s["setup"] + (s["locator"] + s["allowance"]) + 3 * (s["fixer"] + s["allowance"])
    assert BUDGET - worst >= s["selector"] + s["verifier"], BUDGET - worst


def test_no_single_stage_can_exhaust_the_whole_budget():
    s = _budget_mod().SHARES
    reserved = s["setup"] + s["selector"] + s["verifier"]
    assert s["locator"] + s["allowance"] < BUDGET - reserved - 3 * s["fixer"]       # the locator at its worst still leaves the three fixers their shares
    assert s["fixer"] + s["allowance"] < BUDGET - reserved - s["locator"]
    assert s["helper"] <= s["fixer"] - 2                                          # the copy command and the final diff are the fixer's two raw calls
    assert s["locator_helper"] <= s["locator"] - 1                                # install is the locator's one uncounted call
    assert s["total"] == BUDGET


def test_prompts_state_exactly_the_shares_of_the_ledger():
    s = _budget_mod().SHARES
    for f in FIXERS:
        t = (B / "prompts" / f"{f}.md").read_text()
        assert f"At most {s['fixer']} tool calls" in t and f"at most {s['helper']} helper calls" in t, f
    loc = (B / "prompts" / "locator.md").read_text()
    assert f"at most {s['locator']} tool calls" in loc and f"{s['locator_helper']}th helper call" in loc


# ------------------------------------------------------------------------------------------------ the rebase on v4h2
def test_locator_is_v4h2s_except_it_reads_through_the_counted_view_helper_and_sampling_is_v4h2s():
    a = (V4H2 / "prompts" / "locator.md").read_text().splitlines()
    b = (B / "prompts" / "locator.md").read_text().splitlines()
    changed = [l for l in b if l not in a]
    assert 1 <= len(changed) <= 5, changed                                          # the read step, the cap sentence, the tools sentence
    txt = "\n".join(b)
    assert "view.py" in txt and "read_file" not in txt.replace("There is no read_file", "")
    assert all(l in b for l in a if l.startswith(("FILES:", "ROOT CAUSE:", "CHANGE:", "TEST:", "Issue:", "{problem_description}")))      # the plan format is untouched
    assert (B / "configs" / "sampling.yaml").read_text() == (V4H2 / "configs" / "sampling.yaml").read_text()
    tools = _yaml(B / "sub_agents" / "locator.yaml")["tools"]
    assert "run_command" in tools and not {"read_file", "write_file", "edit_file"} & set(tools)         # every read goes through a counted helper
    a2 = (V4H2 / "prompts" / "verifier.md").read_text().splitlines()
    b2 = (B / "prompts" / "verifier.md").read_text().splitlines()
    changed2 = [l for l in b2 if l not in a2]
    assert 1 <= len(changed2) <= 5 and all(("election" in l or "candidate" in l or "fixers" in l or "applied" in l) for l in changed2), changed2
    assert "{selection?}" in "\n".join(b2) and "{fix_notes?}" not in "\n".join(b2)


def test_structure_is_setup_locator_parallel_fixers_selector_verifier():
    assert _yaml(B / "agent.yaml")["agent_class"] == "SequentialAgent"
    assert [Path(x["config_path"]).stem for x in _yaml(B / "agent.yaml")["sub_agents"]] == ["setup", "locator", "fixers", "selector", "verifier"]
    assert _yaml(B / "sub_agents" / "fixers.yaml")["agent_class"] == "ParallelAgent"
    assert (B / "eval_config.yaml").read_text() == (V4H2 / "eval_config.yaml").read_text()          # 5 min, 70 calls, 150 turns, 180 s: the bundle's own budget


def test_thinking_is_off_everywhere_and_the_fixers_keep_three_temperatures():
    for p in sorted((B / "configs").glob("*.yaml")):
        assert _yaml(p)["thinking_config"]["include_thoughts"] is False, p.name
    for f in FIXERS:
        cfg = _yaml(B / "configs" / f"sampling_{f[-1]}.yaml")
        assert cfg["temperature"] == TEMPS[f]
    assert "thinking_budget" not in "".join(p.read_text() for p in (B / "configs").glob("*.yaml"))


# ------------------------------------------------------------------------------------------------ the official compiler
def test_the_official_compiler_accepts_the_bundle_and_the_fixers_cannot_read_or_write_outside_their_copy():
    agent = _compile(B)
    names = [type(a).__name__ + ":" + a.name for a in agent.sub_agents]
    assert names == ["LlmAgent:setup", "LlmAgent:locator", "ParallelAgent:fixers", "LlmAgent:selector", "LlmAgent:verifier"]
    fx = {a.name: [getattr(t, "name", getattr(t, "__name__", "")) for t in (a.tools or [])] for a in agent.sub_agents[2].sub_agents}
    for f in FIXERS:
        assert "run_command" in fx[f] and not {"read_file", "write_file", "edit_file", "submit_patch"} & set(fx[f]), (f, fx[f])


def test_validate_script_passes():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(B)], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0 and "OK model=" in r.stdout, r.stdout[-400:] + r.stderr[-400:]


# ------------------------------------------------------------------------------------------------ the ledger
def test_fixer_id_comes_from_the_copy_directory():
    m = _budget_mod()
    assert m.fixer_id("/sbx/tmp/wa") == "a" and m.fixer_id("/x/wc/") == "c" and m.fixer_id("/workspace") is None and m.fixer_id("/tmp/other") is None


def test_ledger_allows_exactly_the_helper_share_then_refuses(tmp_path):
    m = _budget_mod(); H = m.SHARES["helper"]
    for n in range(1, H + 1):
        refusal, footer = m.enter("/sbx/tmp/wa", base=str(tmp_path))
        assert refusal is None and f"{n}/{H}" in footer
    refusal, footer = m.enter("/sbx/tmp/wa", base=str(tmp_path))
    assert refusal and "SHARE SPENT" in refusal and "git" in refusal and "diff" in refusal
    assert m.enter("/sbx/tmp/wb", base=str(tmp_path))[0] is None                  # another fixer's share is its own


def test_a_non_fixer_workspace_after_the_copies_exist_is_never_counted(tmp_path):
    m = _budget_mod(); tmp = tmp_path / "sbx_tmp"; (tmp / "swe").mkdir(parents=True); (tmp / "wb").mkdir()
    for _ in range(m.SHARES["helper"] + 5):
        assert m.enter("/workspace", base=str(tmp_path / "led"), tmp=str(tmp)) == (None, "")


def test_once_one_fixer_passes_the_others_are_told_to_stop_and_the_passer_is_not(tmp_path):
    m = _budget_mod()
    m.mark_passed("/sbx/tmp/wb", base=str(tmp_path))
    refusal, _ = m.enter("/sbx/tmp/wa", base=str(tmp_path))
    assert refusal and "STOP" in refusal and "candidate b" in refusal and "diff" in refusal
    assert m.enter("/sbx/tmp/wb", base=str(tmp_path))[0] is None


def test_the_ledger_counts_exactly_under_concurrent_fixers(tmp_path):
    code = ("import sys; sys.path.insert(0, %r); import _budget as m\n"
            "for _ in range(6): m.enter('/sbx/tmp/w' + sys.argv[1], base=%r)\n") % (str(SCRIPTS), str(tmp_path))
    ps = [subprocess.Popen([sys.executable, "-c", code, k]) for k in "aaaabbbb"]       # 4 procs hammer fixer a, 4 hammer fixer b
    [p.wait() for p in ps]
    m = _budget_mod()
    assert m.used("/sbx/tmp/wa", base=str(tmp_path)) == 24 and m.used("/sbx/tmp/wb", base=str(tmp_path)) == 24   # no lost update


def _repo(tmp_path, name="wa"):
    r = tmp_path / "sbx" / "tmp" / name
    r.mkdir(parents=True)
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    (r / "mod.py").write_text("def f(x):\n    return x\n")
    (r / "test_mod.py").write_text("from mod import f\n\ndef test_f():\n    assert f(1) == 2\n")
    subprocess.run(["git", "init", "-q"], cwd=r, env=env); subprocess.run(["git", "add", "-A"], cwd=r, env=env)
    subprocess.run(["git", "commit", "-qm", "i"], cwd=r, env=env)
    return r


def _run(helper, args, cwd, tmp_path, stdin=None):
    env = dict(os.environ, TMPDIR=str(tmp_path / "tmpdir"), TEST_TMPDIR=str(tmp_path / "tmpdir"))
    (tmp_path / "tmpdir").mkdir(exist_ok=True)
    return subprocess.run([sys.executable, str(SCRIPTS / helper), *args], cwd=cwd, env=env, input=stdin, capture_output=True, text=True).stdout


def test_helpers_refuse_after_the_share_and_the_footer_counts_down(tmp_path):
    r = _repo(tmp_path); H = _budget_mod().SHARES["helper"]
    outs = [_run("view.py", ["mod.py", str(i), str(i + 1)], r, tmp_path) for i in range(1, H + 1)]
    assert all("mod.py" not in o or "|" in o for o in outs) and f"{H}/{H}" in outs[-1]
    refused = _run("view.py", ["mod.py", "1", "2"], r, tmp_path)
    assert "SHARE SPENT" in refused and "|" not in refused                          # nothing was read


def test_a_passing_test_in_one_copy_stops_the_edit_helper_in_another(tmp_path):
    a, b = _repo(tmp_path, "wa"), _repo(tmp_path, "wb")
    (b / "mod.py").write_text("def f(x):\n    return x + 1\n")                       # fixer b's copy passes its test
    out = _run("test.py", ["--target", "test_mod.py"], b, tmp_path)
    assert "all selected tests passed" in out
    stopped = _run("edit.py", ["mod.py", "--lines", "2-2"], a, tmp_path, stdin="    return x + 2\n")
    assert "STOP" in stopped and "candidate b" in stopped
    assert (a / "mod.py").read_text().count("x + 2") == 0                            # the edit was not made
    assert "OK" in _run("edit.py", ["mod.py", "--lines", "2-2"], b, tmp_path, stdin="    return x + 3\n")   # the passer may still work


def test_the_footer_is_the_first_line_of_every_counted_helper_output(tmp_path):
    """The harness truncates tool output (max_stdout_chars 5000): a footer at the end of a long view could be lost, so it comes first."""
    r = _repo(tmp_path)
    (r / "long.py").write_text("".join("x%d = %d  # %s\n" % (i, i, "y" * 60) for i in range(200)))
    view = _run("view.py", ["long.py", "1", "120"], r, tmp_path)
    assert view.splitlines()[0].startswith("[fixer a: helper call 1/") and "1| x0" in view
    edit = _run("edit.py", ["mod.py", "--lines", "2-2"], r, tmp_path, stdin="    return x + 9\n")
    assert edit.splitlines()[0].startswith("[fixer a: helper call 2/") and "OK" in edit
    test = _run("test.py", ["--target", "test_mod.py"], r, tmp_path)
    assert test.splitlines()[0].startswith("[fixer a: helper call 3/")


# ------------------------------------------------------------------------------------------------ the locator's share (2026-10-07)
def test_locator_phase_is_counted_and_refused_after_its_share(tmp_path):
    m = _budget_mod(); H = m.SHARES["locator_helper"]; tmp = tmp_path / "sbx_tmp"; (tmp / "swe").mkdir(parents=True)
    for n in range(1, H + 1):
        refusal, footer = m.enter("/workspace", base=str(tmp_path / "led"), tmp=str(tmp))
        assert refusal is None and f"[locator: helper call {n}/{H}" in footer
    refusal, _ = m.enter("/workspace", base=str(tmp_path / "led"), tmp=str(tmp))
    assert refusal and "SHARE SPENT" in refusal and "plan" in refusal and "FILES" in refusal


def test_once_the_fixers_copies_exist_workspace_calls_are_the_verifiers_and_not_counted(tmp_path):
    m = _budget_mod(); tmp = tmp_path / "sbx_tmp"; (tmp / "swe").mkdir(parents=True); (tmp / "wa").mkdir()
    for _ in range(m.SHARES["locator_helper"] + 5):
        assert m.enter("/workspace", base=str(tmp_path / "led"), tmp=str(tmp)) == (None, "")


def test_locate_and_view_helpers_count_the_locators_calls(tmp_path):
    H = _budget_mod().SHARES["locator_helper"]
    r = _repo(tmp_path, "workspace")                                                # a repo that is not a fixer copy, with no copies around
    (tmp_path / "tmpdir" ).mkdir(exist_ok=True)
    outs = [_run("view.py", ["mod.py", str(i), str(i + 1)], r, tmp_path) for i in range(1, H + 1)]
    assert f"[locator: helper call {H}/{H}" in outs[-1] and outs[0].splitlines()[0].startswith("[locator: helper call 1/")
    refused = _run("locate.py", ["f"], r, tmp_path)
    assert "SHARE SPENT" in refused and "plan" in refused
