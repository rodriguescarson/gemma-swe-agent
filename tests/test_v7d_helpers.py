"""v7d fix 1 (docs/a6000/V7C_FAILURE_ANALYSIS.md, step 1; the box's analysis of the v7c run, 2026-10-08): view.py never
answers a re-read with a bare refusal.

Evidence (the v7c traces, 35 items): view.py keeps one ledger of viewed ranges for the whole task, but the fixer is a
fresh agent that only has the locator's text summary, so its FIRST view of the range the locator read came back
"ALREADY SHOWN ... edit now" and it asked again, up to 44 times (attrs_c2824ac: locator step 18 views _make.py 660-680,
fixer steps 20-41 repeat it 22 times). 10 of 35 items began the fixer on a refused view: 1 solved, against 11 of 25
for the rest (v7: 7 of 50, 1 solved, against 18 of 43). On the 28 items with local traces, 136 of the 299 identical
consecutive repeats were view.py calls and 89 of those got the refusal line.

v7d against v7c (view.py only; _ws.py changes in its docstring alone):
  * an identical re-read of an unchanged range prints its numbered lines AGAIN, under one line that starts
    "SHOWN AGAIN:" and names the cause and the next action. The line comes FIRST, so it arrives before run_command's
    5,000-char cut. No helper prints "ALREADY SHOWN" any more.
  * v7c's run of identical re-reads is unchanged: the 3rd, 6th, 9th ... identical re-read in a row of the same range
    still gets the file outline (new content) in place of the lines; any other view.py call and an OK edit end the run.
  * a re-read that printed no lines the first time (PAST END, EMPTY FILE) prints that one line again, without the
    SHOWN AGAIN line: nothing was shown.
  * everything else (range shapes, MAX 120, the views log, the ledger's shape, the locate cap, the outline code)
    is v7c's, checked by re-running v7c's helper tests on v7d at the end of this file (the ones that assert the
    refusal line are EXCLUDED, each replaced here).

The helpers run the way the sandbox runs them (installed copies in a task's own TMPDIR, cwd = the task's workspace):
tests/test_v7_helpers.py's task() with its scripts dir pointed at v7d. Written before the change (strict test-first)."""
import json, re
from pathlib import Path

import pytest

import test_v7_helpers as v7h
import test_v7c_helpers as v7ch
from test_v7_helpers import block, ledger, numbered, run, task, view
from test_v7b_helpers import E_OUTLINE, LAST, OUTLINED, OUTLINED_ENTRIES, entries, many_defs
from test_v7c_helpers import code_strings_and_names, top_level, ws_attrs

ROOT = Path(__file__).resolve().parents[1]
V7C, V7D = ROOT / "submissions" / "v7c", ROOT / "submissions" / "v7d"
SCRIPTS, V7C_SCRIPTS = V7D / "skills" / "swe-tools" / "scripts", V7C / "skills" / "swe-tools" / "scripts"
SEARCH_CAP = "search cap reached: use `git grep -n <name>` or write the plan now"
AGAIN = ("SHOWN AGAIN: %s lines %d-%d are unchanged since they were shown earlier in this task, so use them now instead "
         "of viewing them again")
FRESH = {"locate": 0, "view": 0, "edited": False, "repeat_key": None, "repeat_run": 0}


@pytest.fixture(autouse=True)
def _v7d_scripts(monkeypatch):
    """test_v7_helpers.task() reads the scripts dir from its module global, and test_v7c_helpers' own tests read theirs
    from SCRIPTS: v7d's in this module."""
    monkeypatch.setattr(v7h, "SCRIPTS", SCRIPTS)
    monkeypatch.setattr(v7ch, "SCRIPTS", SCRIPTS)


def kind(out, rel="pkg/e.py", a=4, b=8):
    """'lines' for a plain numbered reply, 'again' for the SHOWN AGAIN line followed by numbered lines, 'outline' for an
    outline reply (it ends with the outline-only line); anything else comes back as it is."""
    lines = [l.rstrip() for l in out.strip().splitlines()]                           # "8| " (an empty source line) ends in a space
    nums = [l.rstrip() for l in numbered(out)]
    body = [l for l in lines if not l.startswith(("(capped at 120 lines;", "(one range per call:"))]   # v7's trailers
    if body and body[0] == AGAIN % (rel, a, b) and nums and nums == body[1:]:
        return "again"
    if lines and lines[-1].startswith("outline only: pick a range and edit it now with `python3 /tmp/swe/edit.py "):
        return "outline"
    if nums and nums == body:
        return "lines"
    return out


def repeats(t, n, rel="pkg/e.py", a=4, b=8):
    return [kind(view(t, rel, str(a), str(b)), rel, a, b) for _ in range(n)]


# ------------------------------------------------------------------ fix 1: the lines again, never a bare refusal

def test_the_fixers_first_view_of_the_range_the_locator_read_gets_the_lines(tmp_path):
    """The stage-crossing case: the locator read 4-8, the fixer (a fresh agent, same task ledger) asks for 4-8."""
    t = task(tmp_path)
    first = view(t, "pkg/e.py", "4", "8")                                             # the locator's read
    second = view(t, "pkg/e.py", "4", "8")                                            # the fixer's first view
    assert kind(first) == "lines" and kind(second) == "again", (first, second)
    assert numbered(second) == numbered(first) == ["%d| %s" % (i, l) for i, l in zip(range(4, 9), v7h.SRC.splitlines()[3:8])]
    assert "ALREADY SHOWN" not in second and "refused" not in second.lower()


def test_the_note_is_one_line_first_that_names_the_cause_and_the_next_action(tmp_path):
    t = task(tmp_path)
    view(t, "m.py", "10", "40")
    out = view(t, "m.py", "10-40")                                                    # the same range in another shape
    lines = out.strip().splitlines()
    assert lines[0] == AGAIN % ("m.py", 10, 40) and lines[1:] == ["%d| line%d" % (n, n) for n in range(10, 41)], out
    assert re.search(r"\b(instead|now|next)\b", lines[0]) and "unchanged" in lines[0]
    assert not re.search(r"cap", lines[0]) and "Traceback" not in out
    assert out == lines[0] + "\n" + "\n".join(lines[1:]) + "\n"                      # the note, then the lines, nothing else


def test_the_repeat_sequence_again_again_outline_again_again_outline(tmp_path):
    t = task(tmp_path)
    assert kind(view(t, "pkg/e.py", "4", "8")) == "lines"                            # the first read is no repeat
    outs, runs = [], []
    for _ in range(6):                                                               # the identical call, six more times
        rc, out = run(t, "view.py", "pkg/e.py", "4", "8")
        assert rc == 0 and "Traceback" not in out, out
        outs.append(out)
        runs.append(ledger(t)["repeat_run"])
    assert [kind(o) for o in outs] == ["again", "again", "outline", "again", "again", "outline"], outs
    assert outs[0] == outs[1] == outs[3] == outs[4]                                   # the same reply every time
    assert outs[2].strip() == outs[5].strip() == E_OUTLINE                           # v7c's outline of pkg/e.py
    assert runs == [1, 2, 0, 1, 2, 0]
    led = ledger(t)
    assert (led["repeat_key"], led["view"], bool(led.get("edited"))) == ("pkg/e.py:4-8", 7, False), led


def test_the_sequence_continues_past_six(tmp_path):
    t = task(tmp_path)
    view(t, "pkg/e.py", "1-20")
    assert repeats(t, 12, "pkg/e.py", 1, 20) == ["again", "again", "outline"] * 4


def test_the_same_range_in_any_shape_is_one_run(tmp_path):
    t = task(tmp_path)
    assert kind(view(t, "m.py")) == "lines"                                          # bare FILE: 1-120
    absolute = str(t.ws / "m.py")
    got = [kind(view(t, rel, *rng), rel, 1, 120) for rel, *rng in (("m.py", "1", "120"), ("m.py", "1"), ("m.py", "1-120"),
                                                                   ("m.py", "1", "300"), (absolute, "1:120"), ("m.py", "120", "1"))]
    assert got == ["again", "again", "outline", "again", "again", "outline"], got      # the absolute path: same key
    assert ledger(t)["repeat_key"] == "m.py:1-120"


def test_a_different_range_resets_the_counter(tmp_path):
    t = task(tmp_path)
    view(t, "pkg/e.py", "4", "8")
    assert repeats(t, 2) == ["again", "again"] and ledger(t)["repeat_run"] == 2
    assert kind(view(t, "pkg/e.py", "1", "3"), "pkg/e.py", 1, 3) == "lines"           # a different range: plain lines
    assert (ledger(t)["repeat_key"], ledger(t)["repeat_run"]) == (None, 0)
    assert repeats(t, 3) == ["again", "again", "outline"]                             # counted from the 1st again


def test_a_repeat_of_another_range_starts_its_own_count(tmp_path):
    t = task(tmp_path)
    view(t, "pkg/e.py", "4", "8")
    view(t, "pkg/e.py", "10", "11")
    assert repeats(t, 2) == ["again", "again"]
    assert repeats(t, 1, "pkg/e.py", 10, 11) == ["again"]                              # 10-11's 1st repeat, not 4-8's 3rd
    assert (ledger(t)["repeat_key"], ledger(t)["repeat_run"]) == ("pkg/e.py:10-11", 1)
    assert repeats(t, 1) == ["again"]                                                 # 4-8 counts from 1 again
    alternating = [repeats(t, 1, *r)[0] for r in [("pkg/e.py", 10, 11), ("pkg/e.py", 4, 8)] * 4]
    assert alternating == ["again"] * 8                                               # per (file, range): never the outline


def test_any_other_view_call_ends_the_run(tmp_path):
    for i, other in enumerate((("m.py", "abc"), ("nope.py", "1", "5"), ("m.py", "1", "5"))):   # usage, no such file, a read
        t = task(tmp_path, "t%d" % i)
        view(t, "pkg/e.py", "4", "8")
        assert repeats(t, 2) == ["again", "again"]
        view(t, *other)
        assert ledger(t)["repeat_run"] == 0, other
        assert repeats(t, 3) == ["again", "again", "outline"], other


def test_an_ok_edit_resets_the_counter_and_the_edited_range_reads_again(tmp_path):
    t = task(tmp_path)
    view(t, "pkg/e.py", "4", "8")
    assert repeats(t, 2) == ["again", "again"] and ledger(t)["repeat_run"] == 2
    rc, out = run(t, "edit.py", "pkg/e.py", stdin=block("        return 1\n", "        return 10\n"))
    assert rc == 0 and out.startswith("OK pkg/e.py"), out
    led = ledger(t)
    assert (led["edited"], led["repeat_key"], led["repeat_run"]) == (True, None, 0), led
    again = view(t, "pkg/e.py", "4", "8")                                             # the file changed: plain lines
    assert kind(again) == "lines" and "6|         return 10" in numbered(again), again
    assert repeats(t, 3) == ["again", "again", "outline"]                              # counted from the 1st again


def test_an_ok_edit_of_another_file_resets_the_counter_too(tmp_path):
    t = task(tmp_path)
    view(t, "pkg/e.py", "4", "8")
    assert repeats(t, 2) == ["again", "again"]
    assert run(t, "edit.py", "pkg/mod.py", stdin=block("    return x\n", "    return x * 2\n"))[0] == 0
    assert ledger(t)["repeat_run"] == 0
    assert repeats(t, 3) == ["again", "again", "outline"]                              # e.py is unchanged: still a repeat


def test_failed_edits_and_other_helpers_do_not_reset_the_counter(tmp_path):
    t = task(tmp_path)
    view(t, "pkg/e.py", "4", "8")
    assert repeats(t, 2) == ["again", "again"]
    assert run(t, "edit.py", "pkg/mod.py", stdin=block("    return 99\n", "    return 1\n"))[0] == 1       # NO MATCH
    assert run(t, "edit.py", "pkg/mod.py", stdin=block("    return x\n", "    return (x\n"))[0] == 1      # SYNTAX ERROR
    assert run(t, "edit.py", "tests/test_mod.py", stdin=block("x\n", "y\n"))[0] == 1                      # REFUSED
    assert run(t, "edit.py", "pkg/mod.py", stdin=block("    return x\n", "    return x\n"))[0] == 1       # NO CHANGE
    assert "workspace=" in run(t, "locate.py", "f")[1]
    assert ledger(t)["repeat_run"] == 2 and not ledger(t).get("edited")
    assert repeats(t, 1) == ["outline"]                                               # still the 3rd repeat in a row


def test_the_counter_is_per_task(tmp_path):
    a, b = task(tmp_path, "a"), task(tmp_path, "b")
    for t in (a, b):
        view(t, "pkg/e.py", "4", "8")
    assert repeats(a, 2) == ["again", "again"]
    assert repeats(b, 1) == ["again"]                                                 # b's own ledger: its 1st repeat
    assert repeats(a, 1) == ["outline"]


def test_the_repeat_turns_log_no_view(tmp_path):
    t = task(tmp_path)
    view(t, "pkg/e.py", "1", "11")
    log = (t.tmp / "swe" / ".views.json").read_text()
    outs = [view(t, "pkg/e.py", "1", "11") for _ in range(3)]
    assert [kind(o, "pkg/e.py", 1, 11) for o in outs] == ["again", "again", "outline"]
    assert (t.tmp / "swe" / ".views.json").read_text() == log


def test_a_changed_file_prints_plain_lines_without_the_note(tmp_path):
    t = task(tmp_path)
    view(t, "m.py", "1", "5")
    (t.ws / "m.py").write_text((t.ws / "m.py").read_text().replace("line3\n", "EDITED\n"))
    out = view(t, "m.py", "1", "5")
    assert kind(out, "m.py", 1, 5) == "lines" and "3| EDITED" in out, out


def test_a_repeat_that_showed_no_lines_the_first_time_keeps_its_one_line_reply(tmp_path):
    t = task(tmp_path)
    (t.ws / "pkg" / "empty.py").write_text("")
    for args, starts in ((("m.py", "900", "950"), "PAST END"), (("pkg/empty.py", "1", "5"), "EMPTY FILE")):
        outs = [run(t, "view.py", *args) for _ in range(4)]                           # the call, then 3 identical re-reads
        assert all(rc == 0 for rc, _ in outs)
        assert [o.strip().splitlines() for _, o in outs[:3]] == [[outs[0][1].strip()]] * 3, outs     # one line, three times
        assert outs[0][1].startswith(starts) and "SHOWN AGAIN" not in outs[1][1] + outs[2][1], outs
        assert kind(outs[3][1]) == "outline"                                           # the run still counts: the 3rd re-read outlines


def test_no_helper_ever_says_already_shown(tmp_path):
    for h in sorted(SCRIPTS.glob("*.py")):
        strings, _ = code_strings_and_names(h)
        assert not [s for s in strings if "ALREADY SHOWN" in s], h.name
        if h.name in ("view.py", "_ws.py"):                                           # edit.py's REFUSED (test files) stays
            assert not [s for s in strings if "refus" in s.lower()], h.name
    strings, _ = code_strings_and_names(V7C_SCRIPTS / "view.py")                     # control: v7c has the line
    assert any("ALREADY SHOWN" in s for s in strings)
    t = task(tmp_path)                                                                # what the model reads back
    outs = [view(t, "m.py", str(10 * i + 1), str(10 * i + 5)) for i in range(20)]
    outs += [view(t, "pkg/e.py", "4", "8") for _ in range(7)] + [view(t, "m.py", "abc"), view(t), view(t, "m.py", "900", "950")]
    outs += [run(t, "locate.py", q)[1] for q in ("f", "g", "parse", "x")]
    outs += [run(t, "edit.py", "pkg/mod.py", stdin=block("    return x\n", "    return x * 2\n"))[1], view(t, "pkg/mod.py")]
    text = "\n".join(outs)
    assert "ALREADY SHOWN" not in text and text.count("SHOWN AGAIN:") == 4 and text.count("outline only:") == 2


# ------------------------------------------------------------------ the rest of view.py and all of _ws.py are v7c's

def test_the_outline_code_and_the_other_view_code_are_v7cs():
    old, new = top_level(V7C_SCRIPTS / "view.py"), top_level(SCRIPTS / "view.py")
    for name in ("MAX", "NUM", "RANGE", "OUTLINE_MAX", "OUTLINE_BEFORE", "OUTLINE_WIDTH", "OUTLINE_LAST",
                 "ranges", "signature", "bases", "outline_entries", "outline_reply"):
        assert new[name] == old[name], name
    assert set(new) == set(old) | {"AGAIN"}                                           # main() and the new line's text


def test_ws_is_v7cs_code():
    assert top_level(V7C_SCRIPTS / "_ws.py") == top_level(SCRIPTS / "_ws.py")
    assert ws_attrs("VIEW_CAP", "READ_CAP_MSG", "LOCATE_CAP", "SEARCH_CAP_MSG", "OUTLINE_EVERY", "OUTLINE", scripts=SCRIPTS) == [
        None, None, 3, SEARCH_CAP, 3, "OUTLINE"]
    assert "ALREADY SHOWN" not in (SCRIPTS / "_ws.py").read_text()                    # the docstring says what it does now
    assert "ALREADY SHOWN" not in (SCRIPTS / "view.py").read_text()


def test_the_ledger_shape(tmp_path):
    import shutil, subprocess, sys
    t = task(tmp_path)
    shutil.rmtree(t.tmp / "swe")
    p = subprocess.run([sys.executable, str(SCRIPTS / "install.py")], cwd=t.ws, env=v7h.env_of(t), capture_output=True, text=True)
    assert p.returncode == 0 and "installed:" in p.stdout, p.stdout + p.stderr
    assert ledger(t) == FRESH                                                         # install.py made it
    run(t, "locate.py", "f")
    for i in range(20):
        view(t, "m.py", str(10 * i + 101), str(10 * i + 105))
    assert ledger(t) == dict(FRESH, locate=1, view=20)
    view(t, "pkg/e.py", "4", "8")
    assert repeats(t, 2) == ["again", "again"]
    assert ledger(t) == dict(FRESH, locate=1, view=23, repeat_key="pkg/e.py:4-8", repeat_run=2)
    subprocess.run([sys.executable, str(SCRIPTS / "install.py")], cwd=t.ws, env=v7h.env_of(t), capture_output=True, text=True)
    assert ledger(t) == dict(FRESH, locate=1, view=23, repeat_key="pkg/e.py:4-8", repeat_run=2)   # a recovery install keeps it
    assert repeats(t, 1) == ["outline"]
    assert ledger(t) == dict(FRESH, locate=1, view=24, repeat_key="pkg/e.py:4-8", repeat_run=0)   # the outline restarted it
    assert run(t, "edit.py", "pkg/new.py", "--create", stdin="X = 1\n")[0] == 0
    assert ledger(t) == dict(FRESH, locate=1, view=24, edited=True)
    view(t, "m.py", "1", "5")
    assert ledger(t) == dict(FRESH, locate=1, view=24, edited=True)                    # no count after the first OK edit


def test_a_missing_ledger_still_outlines(tmp_path):
    t = task(tmp_path)
    (t.tmp / "swe" / ".ledger.json").unlink(missing_ok=True)
    view(t, "pkg/e.py", "4", "8")
    assert repeats(t, 3) == ["again", "again", "outline"]
    assert set(ledger(t)) == {"view", "repeat_key", "repeat_run"}


def outline_of(tmp_path, rel, text, *args, name="o"):
    """The outline view.py prints for `rel` (written with `text`) on the 3rd identical re-read."""
    t = task(tmp_path, name)
    if text is not None:
        (t.ws / rel).parent.mkdir(parents=True, exist_ok=True)
        (t.ws / rel).write_text(text)
    first = view(t, rel, *args)
    assert "SHOWN AGAIN" not in first and "outline only:" not in first, first
    for _ in range(2):
        out = view(t, rel, *args)
        assert out.startswith("SHOWN AGAIN: ") and numbered(out) == numbered(first), out
    rc, out = run(t, "view.py", rel, *args)
    assert rc == 0 and "Traceback" not in out, out
    return out


def test_the_outline_lists_top_level_defs_classes_and_methods_with_their_line_ranges(tmp_path):
    out = outline_of(tmp_path, "pkg/outlined.py", OUTLINED, "1", "40")
    assert out.strip().splitlines() == OUTLINED_ENTRIES + [LAST % "pkg/outlined.py"], out


def test_the_outline_names_the_requested_path_as_sent(tmp_path):
    assert outline_of(tmp_path, "pkg/e.py", None, "10-11").strip() == E_OUTLINE
    t = task(tmp_path, "abs")
    absolute = str(t.ws / "pkg" / "e.py")
    assert kind(view(t, absolute, "1", "5"), absolute, 1, 5) == "lines"
    for _ in range(2):
        assert kind(view(t, absolute, "1", "5"), absolute, 1, 5) == "again"
    assert view(t, absolute, "1", "5").strip().splitlines() == ["4-7 def f(x)", "10-11 def g()", LAST % absolute]


def test_a_long_file_shows_the_60_entries_around_the_requested_line(tmp_path):
    src = many_defs(100)
    top = outline_of(tmp_path, "pkg/big.py", src, name="top")                         # bare FILE: lines 1-120
    assert top.strip().splitlines()[:60] == ["%d-%d def f%d(x)" % (3 * i + 1, 3 * i + 2, i) for i in range(60)]
    assert top.strip().splitlines()[60:] == ["... 40 more", LAST % "pkg/big.py"]
    mid = outline_of(tmp_path, "pkg/big.py", src, "91-100", name="mid")               # f30 starts at line 91
    lines = mid.strip().splitlines()
    assert lines[0] == "... 20 more" and lines[-2] == "... 20 more" and len(entries(mid)) == 60
    assert lines[1] == "61-62 def f20(x)" and "91-92 def f30(x)" in lines and len(mid) < 4700


@pytest.mark.parametrize("rel,text,line", [
    ("pkg/broken.py", "import os\n\ndef f(:\n    pass\n", "outline unavailable (syntax error at line 3)"),
    ("README.md", "# title\n\nsome text\n", "outline unavailable (not a Python file; it has 3 lines)"),
    ("pkg/consts.py", "A = 1\nB = 2\n", "outline unavailable (no def or class; it has 2 lines)"),
])
def test_a_file_that_cannot_be_outlined_gets_one_line_then_the_outline_only_line(tmp_path, rel, text, line):
    out = outline_of(tmp_path, rel, text, "1", "5")
    assert out.strip().splitlines() == [line, LAST % rel], out


def test_the_outline_reply_ends_with_one_line_that_names_the_next_action(tmp_path):
    t = task(tmp_path)
    view(t, "pkg/e.py", "4", "8")
    out = [view(t, "pkg/e.py", "4", "8") for _ in range(3)][2]
    last = out.strip().splitlines()[-1]
    assert last == LAST % "pkg/e.py" and re.search(r"\bnow\b", last) and "Traceback" not in out


# ------------------------------------------------------------------ the refusal-message audit (v7c's table, minus the re-read row)

AGAIN_ROWS = ("view: range already shown", "view: range already shown, 2nd repeat")   # v7's row (1st repeat) and v7c's (2nd)
V7D_REFUSALS = [r for r in v7ch.V7C_REFUSALS if r[0] not in AGAIN_ROWS]


@pytest.mark.parametrize("rid,helper,setup,argv,stdin,starts,code", V7D_REFUSALS, ids=[r[0] for r in V7D_REFUSALS])
def test_every_refusal_is_one_line_with_the_cause_and_the_next_action(tmp_path, rid, helper, setup, argv, stdin, starts, code):
    v7h.test_every_refusal_is_one_line_with_the_cause_and_the_next_action(tmp_path, rid, helper, setup, argv, stdin, starts, code)


def test_the_audit_table_is_v7cs_without_the_re_read_rows(tmp_path):
    dropped = [r for r in v7ch.V7C_REFUSALS if r not in V7D_REFUSALS]
    assert [r[0] for r in dropped] == list(AGAIN_ROWS) and len(V7D_REFUSALS) == len(v7ch.V7C_REFUSALS) - 2
    for i, (_, helper, setup, argv, _, _, _) in enumerate(dropped):
        t = task(tmp_path, "t%d" % i)
        setup(t)                                                                      # m.py 1-5 shown once / twice
        rc, out = run(t, helper, *argv)                                               # the repeat: lines, not a refusal
        assert rc == 0 and kind(out, "m.py", 1, 5) == "again", out


# ------------------------------------------------------------------ the counters read v7d's replies

def test_the_counters_read_v7ds_replies(tmp_path):
    """scripts/a6000/v7_counters.py on v7d's real replies: 20 distinct reads, the first read of pkg/e.py and six repeats,
    five locate calls (the 4th and 5th refused). repeat_reads 4 (the SHOWN AGAIN replies), repeat_outlines 2,
    cap_refusals 2 (the search-cap lines only); the four must-be-zero counters stay 0."""
    from test_v7_counters import ok, rc, vc, write_run
    t = task(tmp_path)
    steps = [rc("locator", "python3 /tmp/swe/view.py m.py %d %d" % (a, a + 4), ok(view(t, "m.py", str(a), str(a + 4))))
             for a in range(1, 100, 5)]
    steps += [rc("fixer", "python3 /tmp/swe/view.py pkg/e.py 4 8", ok(view(t, "pkg/e.py", "4", "8"))) for _ in range(7)]
    steps += [rc("locator", 'python3 /tmp/swe/locate.py "%s"' % q, ok(run(t, "locate.py", q)[1])) for q in ("f", "g", "parse", "x", "y")]
    c = vc.counters(str(write_run(tmp_path / "run", {"t": (steps, False)})), "v7")
    assert (c["repeat_reads"], c["repeat_outlines"], c["cap_refusals"], c["view_usage_calls"], c["loops_ge5"]) == (4, 2, 2, 0, 1), c
    assert vc.verdict(c, ("view_usage_calls", "literal_wrapper_commands", "write_file_path_refusals", "forced_install_empty_args"))["pass"]


# ------------------------------------------------------------------ every v7c helper test, re-run on v7d

EXCLUDED = {   # v7c test -> its v7d replacement in this file (each asserts the ALREADY SHOWN line, or compares with v7b's text)
    "test_every_reply_but_the_third_repeat_is_v7bs": "test_the_repeat_sequence_again_again_outline_again_again_outline",
    "test_the_repeat_sequence_one_liner_one_liner_outline_one_liner_one_liner_outline": "test_the_repeat_sequence_again_again_outline_again_again_outline",
    "test_the_sequence_continues_past_six": "test_the_sequence_continues_past_six",
    "test_the_same_range_in_any_shape_is_one_run": "test_the_same_range_in_any_shape_is_one_run",
    "test_a_different_range_resets_the_counter": "test_a_different_range_resets_the_counter",
    "test_a_repeat_of_another_range_starts_its_own_count": "test_a_repeat_of_another_range_starts_its_own_count",
    "test_any_other_view_call_ends_the_run": "test_any_other_view_call_ends_the_run",
    "test_an_ok_edit_resets_the_counter_and_the_edited_range_reads_again": "test_an_ok_edit_resets_the_counter_and_the_edited_range_reads_again",
    "test_an_ok_edit_of_another_file_resets_the_counter_too": "test_an_ok_edit_of_another_file_resets_the_counter_too",
    "test_failed_edits_and_other_helpers_do_not_reset_the_counter": "test_failed_edits_and_other_helpers_do_not_reset_the_counter",
    "test_the_counter_is_per_task": "test_the_counter_is_per_task",
    "test_the_repeat_turns_log_no_view": "test_the_repeat_turns_log_no_view",
    "test_the_outline_code_and_the_other_view_code_are_v7bs": "test_the_outline_code_and_the_other_view_code_are_v7cs",
    "test_the_rest_of_the_ledger_code_is_v7bs": "test_ws_is_v7cs_code",
    "test_the_read_cap_is_deleted_not_raised": "test_ws_is_v7cs_code",
    "test_the_outline_lists_top_level_defs_classes_and_methods_with_their_line_ranges": "test_the_outline_lists_top_level_defs_classes_and_methods_with_their_line_ranges",
    "test_the_outline_names_the_requested_path_as_sent": "test_the_outline_names_the_requested_path_as_sent",
    "test_a_long_file_shows_the_60_entries_around_the_requested_line": "test_a_long_file_shows_the_60_entries_around_the_requested_line",
    "test_a_file_that_cannot_be_outlined_gets_one_line_then_the_outline_only_line": "test_a_file_that_cannot_be_outlined_gets_one_line_then_the_outline_only_line",
    "test_the_outline_reply_ends_with_one_line_that_names_the_next_action": "test_the_outline_reply_ends_with_one_line_that_names_the_next_action",
    "test_the_ledger_shape": "test_the_ledger_shape",
    "test_a_missing_ledger_still_outlines": "test_a_missing_ledger_still_outlines",
    "test_every_refusal_is_one_line_with_the_cause_and_the_next_action": "test_every_refusal_is_one_line_with_the_cause_and_the_next_action",
    "test_the_audit_table_is_v7s_without_the_read_cap_row": "test_the_audit_table_is_v7cs_without_the_re_read_rows",
    "test_the_counters_read_v7cs_replies": "test_the_counters_read_v7ds_replies",
    "test_v7_rerun_view_is_uncapped_after_the_first_ok_edit_and_the_repeat_refusal_still_applies": "test_an_ok_edit_resets_the_counter_and_the_edited_range_reads_again",
    "test_v7_rerun_the_refusals_keep_their_semantics": "test_the_fixers_first_view_of_the_range_the_locator_read_gets_the_lines",
    "test_every_v7_helper_test_is_rerun_on_v7c_but_the_excluded_ones": "test_every_v7c_helper_test_is_rerun_on_v7d_but_the_excluded_ones",
}
V7C_TESTS = sorted(n for n in vars(v7ch) if n.startswith("test_") and callable(getattr(v7ch, n)))
for _name in V7C_TESTS:
    if _name not in EXCLUDED:
        globals()["test_v7c_rerun_" + _name[len("test_"):]] = getattr(v7ch, _name)


def test_every_v7c_helper_test_is_rerun_on_v7d_but_the_excluded_ones():
    assert set(EXCLUDED) <= set(V7C_TESTS), set(EXCLUDED) - set(V7C_TESTS)
    assert {n for n in globals() if n.startswith("test_v7c_rerun_")} == {
        "test_v7c_rerun_" + n[len("test_"):] for n in V7C_TESTS if n not in EXCLUDED}
    assert all(callable(globals().get(r)) for r in EXCLUDED.values())                 # each one has its replacement here
