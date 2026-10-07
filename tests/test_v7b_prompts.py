"""v7b fix 2 (docs/GAPS_2026-10-06.md, last section): tool names typed as shell commands.

Evidence (eval/a6000/results/p4_v7, forensics_lib's literal-wrapper rule): 6 commands, 1 verifier `submit_patch` typed
as a shell line (fastapi_15589) and 5 locator `run_command "git grep ..."` (fastapi_14458, fastapi_14616, rich_3043,
rich_3278, rich_3718); the fixer typed none. As pre-registered, v7b changes only fixer.md and verifier.md: one new line
in each, right after the "How to call:" line, saying in words (no call shape, no backticks) that submit_patch is a tool,
not a command to type, and that commands never start with the word run_command. Every other line stays byte-identical,
so every v7 prompt rule still holds. The locator prompt, where 5 of the 6 came from, is out of the pre-registered scope.

The fixer does not declare submit_patch, and an undeclared tool call kills the task with patch 0 (research/pain_points.md
F7; R61, tests/test_v7_bundle.py), so the sentence says the verifier is the one that calls it, and it opens with
"There is no": the R61 lint's negation filter (tests/test_v5b_bundle.affirmative) reads it as the negation it is.
Written before the prompts changed (strict test-first)."""
import re
from pathlib import Path

import pytest

import test_v7_prompts as v7p
from test_v7_bundle import FORBIDDEN, STAGES, TOOL_NAMES, prompt, spans, stage_yaml

ROOT = Path(__file__).resolve().parents[1]
V7, V7B = ROOT / "submissions" / "v7", ROOT / "submissions" / "v7b"
SCRIPTS = V7B / "skills" / "swe-tools" / "scripts"
SENTENCE = ("There is no submit_patch command to type, since submit_patch is a tool that only the verifier calls, and "
            "commands never start with the word run_command.")


@pytest.mark.parametrize("stage", ["fixer", "verifier"])
def test_the_sentence_is_present_once(stage):
    assert prompt(stage, V7B).count(SENTENCE) == 1
    assert prompt(stage, V7B).count("only the verifier calls") == 1


def test_no_other_prompt_carries_it():
    assert (V7B / "prompts" / "setup.md").read_bytes() == (V7 / "prompts" / "setup.md").read_bytes()
    assert SENTENCE not in prompt("locator", V7B)                        # the locator has its own sentence (below)
    for stage in STAGES:
        assert SENTENCE not in prompt(stage, V7)                          # control: v7 never had it


@pytest.mark.parametrize("stage", ["fixer", "verifier"])
def test_one_new_line_after_how_to_call_and_every_other_line_byte_identical(stage):
    old = (V7 / "prompts" / f"{stage}.md").read_bytes().split(b"\n")
    new = (V7B / "prompts" / f"{stage}.md").read_bytes().split(b"\n")
    i = new.index(SENTENCE.encode())
    assert new[:i] + new[i + 1:] == old                                  # one line added, nothing else touched
    assert new[i - 1].startswith(b"How to call: run each shell line below with the run_command tool.")


def test_the_sentence_says_it_in_words():
    assert "submit_patch is a tool that only the verifier calls" in SENTENCE
    assert "no submit_patch command to type" in SENTENCE
    assert "commands never start with the word run_command" in SENTENCE
    assert not set("`():") & set(SENTENCE), SENTENCE                    # no call shape, no label, no backticked span
    assert not any(bad in SENTENCE for bad in FORBIDDEN)


def test_no_prompt_but_setup_shows_a_tool_call_shape():
    """tests/test_v7_bundle.py's call-shape lint, on v7b's prompts."""
    for s in STAGES:
        t = prompt(s, V7B)
        for bad in FORBIDDEN:
            assert bad not in t, (s, bad)
        assert not re.search(r"\b(%s)`?\s*:" % "|".join(TOOL_NAMES), t), s
        assert "with the run_command tool" in t, s
        for sp in spans(t):
            assert not any(re.search(r"\b%s\b" % n, sp) for n in TOOL_NAMES), (s, sp)
    assert 'run_skill_script(skill_name="swe-tools", file_path="install.py")' in (V7B / "prompts" / "setup.md").read_text()


def test_every_tool_named_in_a_prompt_is_declared_by_that_stage():
    """R61 as tests/test_v7_bundle.py runs it on v7, on v7b; and the fixer names submit_patch only in the new sentence."""
    from test_v10_prompts import HALLUCINATED, REGISTRY_FALLBACK, named_tools
    from test_v10_bundle import SKILL_TOOLS
    from test_v5b_bundle import affirmative, declared_tools
    vocab = REGISTRY_FALLBACK | SKILL_TOOLS | HALLUCINATED
    for s in STAGES:
        found = named_tools(affirmative(prompt(s, V7B)), vocab)
        assert found <= declared_tools(s, V7B), (s, found - declared_tools(s, V7B))
        assert ("submit_patch" in found) == (s == "verifier"), s
        listed = re.search(r"^Tools you can call: ([^.]+)\.", prompt(s, V7B), re.M).group(1).split(", ")
        assert set(listed) == set(stage_yaml(s, V7B)["tools"]) | {"run_skill_script"}, (s, listed)
    assert "submit_patch" not in prompt("fixer", V7B).replace(SENTENCE, "")
    assert affirmative(SENTENCE).strip() == ""                          # the lint reads the whole sentence as a negation


# ------------------------------------------------------------------ prompt vs reality (tests/test_v7_prompts.py) on v7b

def test_the_shell_lines_are_v7s():
    for s in STAGES:
        assert v7p.shell_lines(prompt(s, V7B)) == v7p.shell_lines(prompt(s, V7)), s


@pytest.fixture(autouse=True)
def _v7b_bundle(monkeypatch):
    """test_v7_prompts reads the prompts and installs the helpers from its module globals: v7b's in this module (its
    parametrized lines were collected from v7's prompts, equal to v7b's by the test above)."""
    monkeypatch.setattr(v7p, "V7", V7B)
    monkeypatch.setattr(v7p, "SCRIPTS", SCRIPTS)


V7P_TESTS = sorted(n for n in vars(v7p) if n.startswith("test_") and callable(getattr(v7p, n)))
for _name in V7P_TESTS:
    globals()["test_v7_rerun_" + _name[len("test_"):]] = getattr(v7p, _name)


def test_every_v7_prompt_test_is_rerun_on_v7b():
    assert len(V7P_TESTS) == 5
    assert {n for n in globals() if n.startswith("test_v7_rerun_")} == {"test_v7_rerun_" + n[5:] for n in V7P_TESTS}


LOCATOR_SENTENCE = "Commands never start with the word run_command and never contain a tool name, since the command argument is the shell line alone."


def test_the_locator_gets_its_own_sentence_once_and_v7_never_had_it():
    """2026-10-08: on the box's v7 run 5 of the 6 literal-wrapper commands were the LOCATOR's `run_command "git grep ..."`."""
    loc = prompt("locator", V7B)
    assert loc.count(LOCATOR_SENTENCE) == 1 and LOCATOR_SENTENCE not in prompt("locator", V7)
    assert not set("`():") & set(LOCATOR_SENTENCE) and not any(bad in LOCATOR_SENTENCE for bad in FORBIDDEN)
    old, new = prompt("locator", V7).encode().split(b"\n"), loc.encode().split(b"\n")
    assert len(new) == len(old) + 1 and [l for l in new if LOCATOR_SENTENCE.encode() not in l] == old   # one new line, rest byte-identical
