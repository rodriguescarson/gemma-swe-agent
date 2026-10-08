"""v7d wording (docs/a6000/V7C_FAILURE_ANALYSIS.md, step 1): the prompts stop promising a refusal that view.py no longer
makes. v7c's locator.md says "a range already shown is refused" and its fixer.md "a range you already saw is refused, so
edit instead of re-reading"; v7d says what happens now (the range comes back marked SHOWN AGAIN) and keeps the
instruction (never ask twice; edit instead of re-reading). Exactly one line changes in each of the two files, inside
the parenthesis; the backticked shell line in it is untouched, so every shell-line check stays v7c's. setup.md,
verifier.md and SKILL.md are byte-identical to v7c's. No read-cap text anywhere (v7c's rule), no prompt promises a
refusal for a re-read, and the prose promise holds against v7d's helpers: the second view starts with SHOWN AGAIN and
carries the lines. v7b's and v7's prompt tests are re-run on v7d, except the ones that compare whole prompts with
v7's or assert the refusal (each replaced here). Written before the prompts changed (strict test-first)."""
import re
from pathlib import Path

import pytest

import test_v7_prompts as v7p
import test_v7b_prompts as v7bp
import test_v7c_prompts as v7cp
from test_v7_bundle import FORBIDDEN, STAGES, TOOL_NAMES, prompt, spans
from test_v7_helpers import block, run, task, view
import test_v7_helpers as v7h

ROOT = Path(__file__).resolve().parents[1]
V7C, V7D = ROOT / "submissions" / "v7c", ROOT / "submissions" / "v7d"
SCRIPTS = V7D / "skills" / "swe-tools" / "scripts"
OLD = {"locator": "(at most 120 lines per call; a range already shown is refused)",
       "fixer": "(at most 120 lines; a range you already saw is refused, so edit instead of re-reading)"}
NEW = {"locator": "(at most 120 lines per call; a range already shown comes back marked SHOWN AGAIN, so never ask for it twice)",
       "fixer": "(at most 120 lines; a range you already saw comes back marked SHOWN AGAIN, so edit instead of re-reading)"}


@pytest.fixture(autouse=True)
def _v7d_bundle(monkeypatch):
    """test_v7b_prompts reads its bundle from V7B/SCRIPTS, test_v7_prompts from V7/SCRIPTS, test_v7c_prompts from
    V7C/SCRIPTS: v7d's in this module."""
    monkeypatch.setattr(v7bp, "V7B", V7D)
    monkeypatch.setattr(v7bp, "SCRIPTS", SCRIPTS)
    monkeypatch.setattr(v7p, "V7", V7D)
    monkeypatch.setattr(v7p, "SCRIPTS", SCRIPTS)
    monkeypatch.setattr(v7cp, "V7C", V7D)
    monkeypatch.setattr(v7cp, "SCRIPTS", SCRIPTS)
    monkeypatch.setattr(v7h, "SCRIPTS", SCRIPTS)


# ------------------------------------------------------------------ the two spans

@pytest.mark.parametrize("stage", ["locator", "fixer"])
def test_one_line_changes_in_each_of_the_two_prompts_and_only_inside_the_parenthesis(stage):
    old, new = ((b / "prompts" / f"{stage}.md").read_bytes().split(b"\n") for b in (V7C, V7D))
    assert len(old) == len(new)
    diff = [i for i, (a, b) in enumerate(zip(old, new)) if a != b]
    assert len(diff) == 1, diff
    i = diff[0]
    assert old[i].decode().count(OLD[stage]) == 1 and new[i].decode() == old[i].decode().replace(OLD[stage], NEW[stage])
    assert OLD[stage] in prompt(stage, V7C) and OLD[stage] not in prompt(stage, V7D)   # control: v7c promises the refusal


def test_the_other_files_that_speak_are_v7cs_byte_for_byte():
    for rel in ("prompts/setup.md", "prompts/verifier.md", "skills/swe-tools/SKILL.md", "agent.yaml", "eval_config.yaml",
                "configs/sampling.yaml", "sub_agents/setup.yaml", "sub_agents/fixer.yaml", "sub_agents/verifier.yaml"):
        assert (V7D / rel).read_bytes() == (V7C / rel).read_bytes(), rel


def test_no_prompt_promises_a_refusal_for_a_re_read_and_each_names_shown_again_once():
    for s in STAGES:
        t = prompt(s, V7D)
        assert not re.search(r"\brefused\b", t), s
        assert t.count("SHOWN AGAIN") == (1 if s in NEW else 0), s
    for s in ("locator", "fixer"):                                           # the new span: no call shape, no tool name, no cap word
        assert not any(bad in NEW[s] for bad in FORBIDDEN)
        assert not re.search(r"\b(%s)\b" % "|".join(TOOL_NAMES), NEW[s]) and not v7cp.cap_words(NEW[s])
        assert "`" not in NEW[s]


def test_the_shell_lines_are_v7cs():
    for s in STAGES:
        assert v7p.shell_lines(prompt(s, V7D)) == v7p.shell_lines(prompt(s, V7C)), s


def test_the_locator_yaml_comment_says_what_view_does_now():
    """The arithmetic comment (tests/test_v7c_bundle.py checks its numbers on v7c; v7d's numbers are the same) said
    "view.py declines only an identical re-read of an unchanged range"; nothing declines a read now."""
    old, new = ((b / "sub_agents" / "locator.yaml").read_text().splitlines() for b in (V7C, V7D))
    assert [l for l in new if not l.startswith("#")] == [l for l in old if not l.startswith("#")]
    c = "\n".join(l for l in new if l.startswith("#"))
    assert "declines" not in c and "SHOWN AGAIN" in c and "view.py calls and raw greps: no helper limits them" in c
    assert "the prompt cap is their only bound" in c
    shares = {k: int(v) for k, v in re.findall(r"^#\s+(setup|locator|fixer|verifier)\s+(\d+)\b", c, re.M)}
    assert shares == {"setup": 1, "locator": 8, "fixer": 12, "verifier": 49}
    assert "declines" in "\n".join(l for l in old if l.startswith("#"))             # control


# ------------------------------------------------------------------ prompt vs reality

def test_the_promises_in_the_prose_hold(tmp_path):
    s = v7p.Scratch(tmp_path)
    v = v7p.fill("python3 /tmp/swe/view.py path/to/file.py START END")
    first = s.sh(v)[1]
    assert first.startswith("1| ")
    second = s.sh(v)[1]                                                             # "comes back marked SHOWN AGAIN"
    assert second.startswith("SHOWN AGAIN: pkg/mod.py lines 1-2 ") and second.splitlines()[1:] == first.splitlines(), second
    rc, out = s.sh("python3 /tmp/swe/edit.py pkg/mod.py <<'EOF'\n<<<<<<< SEARCH\n    return x\n=======\n    return (x\n>>>>>>> REPLACE\nEOF")
    assert rc == 1 and (s.ws / "pkg" / "mod.py").read_text() == v7p.MOD                # "A broken edit is undone"
    rc, out = s.sh("python3 /tmp/swe/edit.py pkg/mod.py <<'EOF'\n<<<<<<< SEARCH\n    return y\n=======\n    return x\n>>>>>>> REPLACE\nEOF")
    assert re.search(r"closest .*line 2", out) and "--lines 2-2" in out              # "names the closest line and the --lines range to use"
    (s.ws / "repro.py").write_text("x = 1\n")
    (s.ws / "tests" / "test_mod.py").write_text("def test_f():\n    assert True\n")
    out = s.sh("python3 /tmp/swe/check.py --mode preflight")[1]
    assert "repro.py" in out and "tests/test_mod.py" in out and "NOT READY" in out   # "revert test/config edits, delete scratch files"


def test_no_helper_reply_carries_read_cap_or_refusal_text(tmp_path, monkeypatch):
    """What the model reads back: a session through v7d's helpers (20 distinct reads, 6 repeats with their outlines, a
    usage error, the locate cap, a failed and an OK edit, reads after it) prints no read-cap text and no ALREADY SHOWN."""
    t = task(tmp_path)
    outs = [view(t, "m.py", str(10 * i + 1), str(10 * i + 5)) for i in range(20)]
    outs += [view(t, "pkg/e.py", "4", "8") for _ in range(7)] + [view(t, "m.py", "abc"), view(t)]
    outs += [run(t, "locate.py", q)[1] for q in ("f", "g", "parse", "x")]
    outs += [run(t, "edit.py", "pkg/mod.py", stdin=block("    return 9\n", "    return 1\n"))[1],
             run(t, "edit.py", "pkg/mod.py", stdin=block("    return x\n", "    return x * 2\n"))[1]]
    outs += [view(t, "m.py", "201", "205"), view(t, "pkg/mod.py")]
    text = "\n".join(outs).replace(str(tmp_path), "TMP").replace(str(tmp_path.resolve()), "TMP").lower()   # paths aside
    assert not [c for c in v7cp.CAP_TEXTS if c in text]
    assert [w for w in re.findall(r"\w*cap\w*", text)] == ["cap"]                # only the search cap's line
    assert "search cap reached" in text and text.count("outline only:") == 2
    assert "already shown" not in text and text.count("shown again:") == 4


# ------------------------------------------------------------------ v7c's, v7b's and v7's prompt tests, re-run on v7d

V7C_EXCLUDED = {"test_the_prompts_and_the_skill_are_v7bs_byte_for_byte": "test_the_other_files_that_speak_are_v7cs_byte_for_byte",
                "test_the_shell_lines_are_v7bs": "test_the_shell_lines_are_v7cs",
                "test_no_helper_reply_carries_read_cap_text": "test_no_helper_reply_carries_read_cap_or_refusal_text",
                "test_every_v7b_prompt_test_is_rerun_on_v7c": "test_every_earlier_prompt_test_is_rerun_on_v7d_but_the_excluded_ones",
                "test_the_control_v7b_states_the_cap_only_in_the_locator_yaml": "test_no_read_cap_text_anywhere"}
V7B_EXCLUDED = {"test_one_new_line_after_how_to_call_and_every_other_line_byte_identical": "test_one_line_changes_in_each_of_the_two_prompts_and_only_inside_the_parenthesis",
                "test_the_locator_gets_its_own_sentence_once_and_v7_never_had_it": "test_one_line_changes_in_each_of_the_two_prompts_and_only_inside_the_parenthesis",
                "test_the_shell_lines_are_v7s": "test_the_shell_lines_are_v7cs",
                "test_every_v7_prompt_test_is_rerun_on_v7b": "test_every_earlier_prompt_test_is_rerun_on_v7d_but_the_excluded_ones",
                "test_v7_rerun_the_promises_in_the_prose_hold": "test_the_promises_in_the_prose_hold"}
V7C_OWN = sorted(n for n in vars(v7cp) if n.startswith("test_") and callable(getattr(v7cp, n)) and not n.startswith("test_v7b_rerun_"))
V7B_ALL = sorted(n for n in vars(v7bp) if n.startswith("test_") and callable(getattr(v7bp, n)))
for _name in V7C_OWN:
    if _name not in V7C_EXCLUDED:
        globals()["test_v7c_rerun_" + _name[len("test_"):]] = getattr(v7cp, _name)
for _name in V7B_ALL:
    if _name not in V7B_EXCLUDED:
        globals()["test_v7b_rerun_" + _name[len("test_"):]] = getattr(v7bp, _name)


@pytest.mark.parametrize("path", v7cp.said(V7D), ids=lambda p: str(p.relative_to(V7D)))
def test_no_read_cap_text_anywhere(path):
    v7cp.test_no_read_cap_text_anywhere(path)


def test_every_earlier_prompt_test_is_rerun_on_v7d_but_the_excluded_ones():
    assert set(V7C_EXCLUDED) <= set(V7C_OWN) and set(V7B_EXCLUDED) <= set(V7B_ALL), (set(V7C_EXCLUDED) - set(V7C_OWN), set(V7B_EXCLUDED) - set(V7B_ALL))
    assert {n for n in globals() if n.startswith("test_v7c_rerun_")} == {"test_v7c_rerun_" + n[5:] for n in V7C_OWN if n not in V7C_EXCLUDED}
    assert {n for n in globals() if n.startswith("test_v7b_rerun_")} == {"test_v7b_rerun_" + n[5:] for n in V7B_ALL if n not in V7B_EXCLUDED}
    assert all(callable(globals().get(r)) for r in list(V7C_EXCLUDED.values()) + list(V7B_EXCLUDED.values()))
