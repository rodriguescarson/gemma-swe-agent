"""v7c fix 3 (docs/GAPS_2026-10-06.md, v7c pre-registration): no read-cap text anywhere the prompts, the skill or the
yamls say something, and every v7b prompt rule still holds on v7c.

Searched as Carson asked ("read cap", "14", "before the first edit", "cap"): v7b's four prompts and SKILL.md never
mention the read cap (their only "cap" is inside "escaping"), so they stay byte-identical to v7b's. The cap was stated
in one place, the arithmetic comment of sub_agents/locator.yaml (`view.py <= 14 calls before the task's first OK edit
... (_ws.VIEW_CAP ...)`); v7c restates that comment without it (tests/test_v7c_bundle.py checks the arithmetic). The
helpers' replies are checked too: a scripted session through v7c's helpers prints no cap text but the search cap's.
v7b's no-call-shape, sentence and prompt-vs-reality tests (and the v7 ones they re-run) are re-run on v7c. Written
before the yaml changed (strict test-first)."""
import re
from pathlib import Path

import pytest

import test_v7_prompts as v7p
import test_v7b_prompts as v7bp
from test_v7_helpers import block, run, task, view
import test_v7_helpers as v7h

ROOT = Path(__file__).resolve().parents[1]
V7B, V7C = ROOT / "submissions" / "v7b", ROOT / "submissions" / "v7c"
SCRIPTS = V7C / "skills" / "swe-tools" / "scripts"
CAP_TEXTS = ("read cap", "view_cap", "before any edit", "before the first edit", "first ok edit", "uncapped")


def said(b):
    """Every file of bundle b that says something to the model or to a reader of its config: the prompts, SKILL.md and
    every yaml (raw text, comments included)."""
    return sorted(list((b / "prompts").glob("*.md")) + [b / "skills" / "swe-tools" / "SKILL.md"] + list(b.glob("*.yaml"))
                  + list(b.glob("*/*.yaml")))


def cap_words(text):
    """Each word that contains "cap", except "escaping", "locate_cap" (_ws.LOCATE_CAP) and "cap" in "prompt cap"."""
    out = []
    for m in re.finditer(r"\w*cap\w*", text.lower()):
        w = m.group(0)
        if w in ("escaping", "locate_cap") or (w == "cap" and text.lower()[:m.start()].endswith("prompt ")):
            continue
        out.append(w)
    return out


@pytest.mark.parametrize("path", said(V7C), ids=lambda p: str(p.relative_to(V7C)))
def test_no_read_cap_text_anywhere(path):
    text = path.read_text()
    assert not [c for c in CAP_TEXTS if c in text.lower()], path
    assert not re.search(r"\b14\b", text), path                         # v7's cap value
    assert cap_words(text) == [], (path, cap_words(text))


def test_the_control_v7b_states_the_cap_only_in_the_locator_yaml():
    flagged = {str(p.relative_to(V7B)) for p in said(V7B)
               if cap_words(p.read_text()) or re.search(r"\b14\b", p.read_text()) or any(c in p.read_text().lower() for c in CAP_TEXTS)}
    assert flagged == {"sub_agents/locator.yaml"}, flagged


def test_the_prompts_and_the_skill_are_v7bs_byte_for_byte():
    for rel in ("prompts/setup.md", "prompts/locator.md", "prompts/fixer.md", "prompts/verifier.md", "skills/swe-tools/SKILL.md"):
        assert (V7C / rel).read_bytes() == (V7B / rel).read_bytes(), rel


def test_no_helper_reply_carries_read_cap_text(tmp_path, monkeypatch):
    """What the model reads back: a session through v7c's helpers (20 distinct reads, 6 repeats with their outlines, a
    usage error, the locate cap, a failed and an OK edit, reads after it) prints no read-cap text."""
    monkeypatch.setattr(v7h, "SCRIPTS", SCRIPTS)
    t = task(tmp_path)
    outs = [view(t, "m.py", str(10 * i + 1), str(10 * i + 5)) for i in range(20)]
    outs += [view(t, "pkg/e.py", "4", "8") for _ in range(7)] + [view(t, "m.py", "abc"), view(t)]
    outs += [run(t, "locate.py", q)[1] for q in ("f", "g", "parse", "x")]
    outs += [run(t, "edit.py", "pkg/mod.py", stdin=block("    return 9\n", "    return 1\n"))[1],
             run(t, "edit.py", "pkg/mod.py", stdin=block("    return x\n", "    return x * 2\n"))[1]]
    outs += [view(t, "m.py", "201", "205"), view(t, "pkg/mod.py")]
    text = "\n".join(outs).replace(str(tmp_path), "TMP").replace(str(tmp_path.resolve()), "TMP").lower()   # paths aside
    assert not [c for c in CAP_TEXTS if c in text]
    assert [w for w in re.findall(r"\w*cap\w*", text)] == ["cap"]                # only the search cap's line
    assert "search cap reached" in text and text.count("outline only:") == 2


# ------------------------------------------------------------------ v7b's prompt tests, re-run on v7c

@pytest.fixture(autouse=True)
def _v7c_bundle(monkeypatch):
    """test_v7b_prompts reads its bundle from V7B/SCRIPTS, and the v7 prompt tests it re-runs from test_v7_prompts'
    V7/SCRIPTS: v7c's in this module (the parametrized shell lines were collected from v7's prompts, equal to v7c's)."""
    monkeypatch.setattr(v7bp, "V7B", V7C)
    monkeypatch.setattr(v7bp, "SCRIPTS", SCRIPTS)
    monkeypatch.setattr(v7p, "V7", V7C)
    monkeypatch.setattr(v7p, "SCRIPTS", SCRIPTS)


V7B_PROMPT_TESTS = sorted(n for n in vars(v7bp) if n.startswith("test_") and callable(getattr(v7bp, n)))
for _name in V7B_PROMPT_TESTS:
    globals()["test_v7b_rerun_" + _name[len("test_"):]] = getattr(v7bp, _name)


def test_every_v7b_prompt_test_is_rerun_on_v7c():
    own = [n for n in V7B_PROMPT_TESTS if not n.startswith("test_v7_rerun_")]
    assert len(own) == 9 and len(V7B_PROMPT_TESTS) == 14                      # v7b's 9 and the 5 v7 ones it re-runs
    assert {"test_no_prompt_but_setup_shows_a_tool_call_shape", "test_the_sentence_is_present_once",
            "test_the_locator_gets_its_own_sentence_once_and_v7_never_had_it"} <= set(own)
    assert {n for n in globals() if n.startswith("test_v7b_rerun_")} == {"test_v7b_rerun_" + n[5:] for n in V7B_PROMPT_TESTS}


def test_the_shell_lines_are_v7bs():
    for s in v7p.STAGES:
        assert v7p.shell_lines((V7C / "prompts" / f"{s}.md").read_text()) == v7p.shell_lines((V7B / "prompts" / f"{s}.md").read_text()), s
