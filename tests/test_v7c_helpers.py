"""v7c fixes 1 and 2 (docs/GAPS_2026-10-06.md, "v7c pre-registration"; Carson 2026-10-08): the pre-edit read cap is gone,
and v7b's outline answers repeats instead of cap refusals.

Evidence (docs/v4h/GATE.md "v7 on the stage-1a ids"; the GAPS sections above the pre-registration): on 50 off-repo
tasks v7's read cap produced 737 refusals, the model repeated a refused read up to 49 times, loop tasks went 7 (v4h2)
-> 18 (v7) and tasks that ran out of calls did not fall (10 -> 11). A refused call costs a harness call too, so the
cap cannot save budget.

v7c against v7b:
  1 no read cap: VIEW_CAP, its refusal text and the refusal path are deleted, not set high. Any number of distinct
    reads prints numbered lines, before and after the first edit. The ledger still counts the view.py calls made before
    the task's first OK edit, for the record only. LOCATE_CAP = 3 and its refusal are unchanged, and so is the ALREADY
    SHOWN check for an identical re-read of an unchanged range.
  2 the outline on repeats: the 1st and 2nd identical re-read of an unchanged range get the ALREADY SHOWN line (v7's
    text); the 3rd gets v7b's outline of the requested file (v7b's code and last line, unchanged); then the counter
    restarts (4th, 5th: the line, 6th: the outline). The counter is per (file, range) and lives in the ledger
    (repeat_key, repeat_run). A different range, any other view.py call and an OK edit reset it (an OK edit to the
    re-read file also changes it, so the next read of that range goes ahead). Failed edits, locate.py and raw greps
    do not reset it. Consequence of "per (file, range)": two ranges re-read in alternation never reach the outline;
    each such call still gets the line.

The helpers run the way the sandbox runs them (installed copies in a task's own TMPDIR, cwd = the task's workspace):
tests/test_v7_helpers.py's task() with its scripts dir pointed at v7c. Every v7 helper test is re-run on v7c except the
ones that test the read cap or v7's ledger shape (EXCLUDED below, each replaced here). Written before the change
(strict test-first)."""
import ast, json, os, re, subprocess, sys
from pathlib import Path

import pytest

import test_v7_helpers as v7h
from test_v7_helpers import block, ledger, numbered, run, task, view
from test_v7b_helpers import E_OUTLINE, LAST, OUTLINED, OUTLINED_ENTRIES, READ_CAP as V7B_READ_CAP, entries, many_defs

ROOT = Path(__file__).resolve().parents[1]
V7B, V7C = ROOT / "submissions" / "v7b", ROOT / "submissions" / "v7c"
SCRIPTS, V7B_SCRIPTS = V7C / "skills" / "swe-tools" / "scripts", V7B / "skills" / "swe-tools" / "scripts"
SEARCH_CAP = "search cap reached: use `git grep -n <name>` or write the plan now"
ALREADY = ("ALREADY SHOWN: %s lines %d-%d are unchanged since you saw them, so edit now with python3 /tmp/swe/edit.py "
           "or view different lines instead")
FRESH = {"locate": 0, "view": 0, "edited": False, "repeat_key": None, "repeat_run": 0}


@pytest.fixture(autouse=True)
def _v7c_scripts(monkeypatch):
    """test_v7_helpers.task() reads the scripts dir from its module global: v7c's in this module."""
    monkeypatch.setattr(v7h, "SCRIPTS", SCRIPTS)


def kind(out, rel="pkg/e.py", a=4, b=8):
    """'already' for the one-line ALREADY SHOWN reply on rel a-b, 'outline' for an outline reply (it ends with the
    outline-only line), 'lines' for numbered lines; anything else comes back as it is."""
    lines = out.strip().splitlines()
    if lines == [ALREADY % (rel, a, b)]:
        return "already"
    if lines and lines[-1].startswith("outline only: pick a range and edit it now with `python3 /tmp/swe/edit.py "):
        return "outline"
    if numbered(out) and "ALREADY SHOWN" not in out:
        return "lines"
    return out


def repeats(t, n, rel="pkg/e.py", a=4, b=8):
    return [kind(view(t, rel, str(a), str(b)), rel, a, b) for _ in range(n)]


def ws_attrs(*names, scripts=SCRIPTS):
    """Attributes of a bundle's _ws.py, read in a child that writes no bytecode into the bundle (None when missing)."""
    code = ("import json, sys\nsys.dont_write_bytecode = True\nsys.path.insert(0, %r)\nimport _ws\n"
            "print(json.dumps([getattr(_ws, n, None) for n in %r]))\n" % (str(scripts), list(names)))
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def top_level(path):
    """A helper's top-level defs and single-name assignments as {name: ast.dump} (comments and layout aside)."""
    out = {}
    for n in ast.parse(path.read_text()).body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[n.name] = ast.dump(n)
        elif isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            out[n.targets[0].id] = ast.dump(n)
    return out


def code_strings_and_names(path):
    """The string constants (docstrings left out) and the names a helper's code uses."""
    tree = ast.parse(path.read_text())
    docs = {id(n.body[0].value) for n in [tree] + [x for x in ast.walk(tree) if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
            if n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    strings = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]
    names = ({n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
             | {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names})
    return strings, names


# ------------------------------------------------------------------ fix 1: no read cap

def test_the_read_cap_is_deleted_not_raised():
    assert ws_attrs("VIEW_CAP", "READ_CAP_MSG", "LOCATE_CAP", "SEARCH_CAP_MSG", "OUTLINE_EVERY", "OUTLINE") == [
        None, None, 3, SEARCH_CAP, 3, "OUTLINE"]
    for h in sorted(SCRIPTS.glob("*.py")):
        strings, names = code_strings_and_names(h)
        assert not [s for s in strings if "read cap" in s.lower() or "before any edit" in s.lower()], h.name
        assert not names & {"VIEW_CAP", "READ_CAP_MSG"}, h.name
    strings, names = code_strings_and_names(V7B_SCRIPTS / "_ws.py")                  # control: v7b has both
    assert V7B_READ_CAP in strings and "VIEW_CAP" in names


def test_no_refusal_after_any_number_of_distinct_reads(tmp_path, monkeypatch):
    t = task(tmp_path)
    outs = [view(t, "m.py", str(5 * i + 1), str(5 * i + 3)) for i in range(60)]       # 60 distinct ranges, no edit yet
    outs += [view(t, "pkg/e.py", str(a)) for a in (1, 2, 3)] + [view(t, "pkg/mod.py")]
    assert all(kind(o) == "lines" for o in outs), [o for o in outs if kind(o) != "lines"][:2]
    assert ledger(t)["view"] == 64 and not ledger(t).get("edited")                  # counted for the record only
    assert run(t, "edit.py", "pkg/mod.py", stdin=block("    return x\n", "    return x * 2\n"))[0] == 0
    assert all(kind(view(t, "m.py", str(5 * i + 2), str(5 * i + 4))) == "lines" for i in range(20))
    assert ledger(t)["view"] == 64                                                   # the record stops at the first OK edit
    monkeypatch.setattr(v7h, "SCRIPTS", V7B_SCRIPTS)                                 # control: v7b refuses the 15th
    b = task(tmp_path, "v7b")
    outs = [view(b, "m.py", str(5 * i + 1), str(5 * i + 3)) for i in range(15)]
    assert all(numbered(o) for o in outs[:14]) and outs[14].strip() == V7B_READ_CAP


def test_twenty_distinct_reads_all_print_numbered_lines(tmp_path):
    t = task(tmp_path)
    for i in range(20):
        a, b = 10 * i + 101, 10 * i + 105
        rc, out = run(t, "view.py", "m.py", str(a), str(b))
        assert rc == 0 and out.splitlines() == ["%d| line%d" % (n, n) for n in range(a, b + 1)], (i, out)
    assert ledger(t)["view"] == 20 and ledger(t)["repeat_run"] == 0


def test_every_reply_but_the_third_repeat_is_v7bs(tmp_path, monkeypatch):
    """Past v7b's cap (lifted by an OK edit in both tasks), the same calls get byte-identical replies, the 1st and 2nd
    repeat included; the 3rd repeat is the one designed difference (v7c: the outline; v7b: the line again)."""
    calls = [("m.py", "10", "40"), ("m.py", "10-40"), ("m.py", "10:40"), ("m.py", "10"), ("m.py",), ("m.py", "40", "10"),
             ("m.py", "10-20", "30-40"), ("m.py", "1", "300"), ("m.py", "abc"), (), ("nope.py", "1", "5"),
             ("m.py", "900", "950"), ("m.py", "900", "950"), ("pkg/__init__.py", "1", "5"), ("{ws}/pkg/e.py", "1", "3"),
             ("{ws}/pkg/e.py", "1", "3"), ("pkg/e.py", "4", "8"), ("pkg/e.py", "4", "8"), ("pkg/e.py", "4", "8")]
    c = task(tmp_path, "v7c")
    monkeypatch.setattr(v7h, "SCRIPTS", V7B_SCRIPTS)
    b = task(tmp_path, "v7b")
    for t in (c, b):
        assert run(t, "edit.py", "pkg/mod.py", stdin=block("    return x\n", "    return x * 2\n"))[0] == 0
    for args in calls:
        got_c, got_b = (view(t, *(a.format(ws=t.ws) for a in args)).replace(str(t.ws), "{ws}") for t in (c, b))
        assert got_c == got_b, (args, got_c, got_b)
    third_c, third_b = view(c, "pkg/e.py", "4", "8"), view(b, "pkg/e.py", "4", "8")     # the 3rd repeat in a row
    assert kind(third_c) == "outline" and third_c.strip() == E_OUTLINE and kind(third_b) == "already"


# ------------------------------------------------------------------ fix 2: the repeat sequence

def test_the_repeat_sequence_one_liner_one_liner_outline_one_liner_one_liner_outline(tmp_path):
    t = task(tmp_path)
    assert kind(view(t, "pkg/e.py", "4", "8")) == "lines"                            # the first read is no repeat
    outs, runs = [], []
    for _ in range(6):                                                               # the identical call, six more times
        rc, out = run(t, "view.py", "pkg/e.py", "4", "8")
        assert rc == 0 and "Traceback" not in out, out
        outs.append(out)
        runs.append(ledger(t)["repeat_run"])
    assert [kind(o) for o in outs] == ["already", "already", "outline", "already", "already", "outline"], outs
    assert outs[0] == ALREADY % ("pkg/e.py", 4, 8) + "\n"                            # one line, v7's text
    assert outs[2].strip() == outs[5].strip() == E_OUTLINE                           # v7b's outline of pkg/e.py
    assert runs == [1, 2, 0, 1, 2, 0]
    led = ledger(t)
    assert (led["repeat_key"], led["view"], bool(led.get("edited"))) == ("pkg/e.py:4-8", 7, False), led


def test_the_sequence_continues_past_six(tmp_path):
    t = task(tmp_path)
    view(t, "pkg/e.py", "1-20")
    assert repeats(t, 12, "pkg/e.py", 1, 20) == ["already", "already", "outline"] * 4


def test_the_same_range_in_any_shape_is_one_run(tmp_path):
    """The repeat check compares the range after parsing (v7), so the run does too: 1-120 sent four ways."""
    t = task(tmp_path)
    assert kind(view(t, "m.py")) == "lines"                                          # bare FILE: 1-120
    absolute = str(t.ws / "m.py")
    got = [kind(view(t, rel, *rng), rel, 1, 120) for rel, *rng in (("m.py", "1", "120"), ("m.py", "1"), ("m.py", "1-120"),
                                                                   ("m.py", "1", "300"), (absolute, "1:120"), ("m.py", "120", "1"))]
    assert got == ["already", "already", "outline", "already", "already", "outline"], got   # the absolute path: same key
    assert ledger(t)["repeat_key"] == "m.py:1-120"


def test_a_different_range_resets_the_counter(tmp_path):
    t = task(tmp_path)
    view(t, "pkg/e.py", "4", "8")
    assert repeats(t, 2) == ["already", "already"] and ledger(t)["repeat_run"] == 2
    assert kind(view(t, "pkg/e.py", "1", "3")) == "lines"                             # a different range goes ahead
    assert (ledger(t)["repeat_key"], ledger(t)["repeat_run"]) == (None, 0)
    assert repeats(t, 3) == ["already", "already", "outline"]                         # counted from the 1st again


def test_a_repeat_of_another_range_starts_its_own_count(tmp_path):
    t = task(tmp_path)
    view(t, "pkg/e.py", "4", "8")
    view(t, "pkg/e.py", "10", "11")
    assert repeats(t, 2) == ["already", "already"]
    assert repeats(t, 1, "pkg/e.py", 10, 11) == ["already"]                            # 10-11's 1st repeat, not 4-8's 3rd
    assert (ledger(t)["repeat_key"], ledger(t)["repeat_run"]) == ("pkg/e.py:10-11", 1)
    assert repeats(t, 1) == ["already"]                                               # 4-8 counts from 1 again
    alternating = [repeats(t, 1, *r)[0] for r in [("pkg/e.py", 10, 11), ("pkg/e.py", 4, 8)] * 4]
    assert alternating == ["already"] * 8                                             # per (file, range): never the outline


def test_any_other_view_call_ends_the_run(tmp_path):
    for i, other in enumerate((("m.py", "abc"), ("nope.py", "1", "5"), ("m.py", "1", "5"))):   # usage, no such file, a read
        t = task(tmp_path, "t%d" % i)
        view(t, "pkg/e.py", "4", "8")
        assert repeats(t, 2) == ["already", "already"]
        view(t, *other)
        assert ledger(t)["repeat_run"] == 0, other
        assert repeats(t, 3) == ["already", "already", "outline"], other


def test_an_ok_edit_resets_the_counter_and_the_edited_range_reads_again(tmp_path):
    t = task(tmp_path)
    view(t, "pkg/e.py", "4", "8")
    assert repeats(t, 2) == ["already", "already"] and ledger(t)["repeat_run"] == 2
    rc, out = run(t, "edit.py", "pkg/e.py", stdin=block("        return 1\n", "        return 10\n"))
    assert rc == 0 and out.startswith("OK pkg/e.py"), out
    led = ledger(t)
    assert (led["edited"], led["repeat_key"], led["repeat_run"]) == (True, None, 0), led
    again = view(t, "pkg/e.py", "4", "8")                                             # the file changed: shown, not a repeat
    assert "6|         return 10" in numbered(again), again
    assert repeats(t, 3) == ["already", "already", "outline"]                          # counted from the 1st again


def test_an_ok_edit_of_another_file_resets_the_counter_too(tmp_path):
    t = task(tmp_path)
    view(t, "pkg/e.py", "4", "8")
    assert repeats(t, 2) == ["already", "already"]
    assert run(t, "edit.py", "pkg/mod.py", stdin=block("    return x\n", "    return x * 2\n"))[0] == 0
    assert ledger(t)["repeat_run"] == 0
    assert repeats(t, 3) == ["already", "already", "outline"]                          # e.py is unchanged: still repeats


def test_failed_edits_and_other_helpers_do_not_reset_the_counter(tmp_path):
    t = task(tmp_path)
    view(t, "pkg/e.py", "4", "8")
    assert repeats(t, 2) == ["already", "already"]
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
    assert repeats(a, 2) == ["already", "already"]
    assert repeats(b, 1) == ["already"]                                               # b's own ledger: its 1st repeat
    assert repeats(a, 1) == ["outline"]


def test_the_repeat_turns_log_no_view(tmp_path):
    t = task(tmp_path)
    view(t, "pkg/e.py", "1", "11")
    log = (t.tmp / "swe" / ".views.json").read_text()
    outs = [view(t, "pkg/e.py", "1", "11") for _ in range(3)]
    assert kind(outs[2], "pkg/e.py", 1, 11) == "outline" and not numbered(outs[2])
    assert (t.tmp / "swe" / ".views.json").read_text() == log


# ------------------------------------------------------------------ the outline: v7b's code, now on the 3rd repeat

def test_the_outline_code_and_the_other_view_code_are_v7bs():
    old, new = top_level(V7B_SCRIPTS / "view.py"), top_level(SCRIPTS / "view.py")
    for name in ("MAX", "NUM", "RANGE", "OUTLINE_MAX", "OUTLINE_BEFORE", "OUTLINE_WIDTH", "OUTLINE_LAST",
                 "ranges", "signature", "bases", "outline_entries", "outline_reply"):
        assert new[name] == old[name], name
    assert set(new) == set(old)                                                       # main() is the only other def


def test_the_rest_of_the_ledger_code_is_v7bs():
    old, new = top_level(V7B_SCRIPTS / "_ws.py"), top_level(SCRIPTS / "_ws.py")
    for name in ("LOCATE_CAP", "SEARCH_CAP_MSG", "OUTLINE_EVERY", "OUTLINE", "ws", "ledger_path", "ledger_load",
                 "ledger_save", "take_locate"):
        assert new[name] == old[name], name
    assert set(new) == set(old) - {"VIEW_CAP", "READ_CAP_MSG"}                        # deleted, not re-valued


def outline_of(tmp_path, rel, text, *args, name="o"):
    """The outline view.py prints for `rel` (written with `text`) on the 3rd identical re-read."""
    t = task(tmp_path, name)
    if text is not None:
        (t.ws / rel).parent.mkdir(parents=True, exist_ok=True)
        (t.ws / rel).write_text(text)
    first = view(t, rel, *args)
    assert "ALREADY SHOWN" not in first and "outline only:" not in first, first
    for _ in range(2):
        assert view(t, rel, *args).startswith("ALREADY SHOWN: ")
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
        assert kind(view(t, absolute, "1", "5"), absolute, 1, 5) == "already"
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


# ------------------------------------------------------------------ the ledger

def test_the_ledger_shape(tmp_path):
    import shutil
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
    repeats(t, 2)
    assert ledger(t) == dict(FRESH, locate=1, view=23, repeat_key="pkg/e.py:4-8", repeat_run=2)
    subprocess.run([sys.executable, str(SCRIPTS / "install.py")], cwd=t.ws, env=v7h.env_of(t), capture_output=True, text=True)
    assert ledger(t) == dict(FRESH, locate=1, view=23, repeat_key="pkg/e.py:4-8", repeat_run=2)   # a recovery install keeps it
    repeats(t, 1)
    assert ledger(t) == dict(FRESH, locate=1, view=24, repeat_key="pkg/e.py:4-8", repeat_run=0)   # the outline restarted it
    assert run(t, "edit.py", "pkg/new.py", "--create", stdin="X = 1\n")[0] == 0
    assert ledger(t) == dict(FRESH, locate=1, view=24, edited=True)
    view(t, "m.py", "1", "5")
    assert ledger(t) == dict(FRESH, locate=1, view=24, edited=True)                    # no count after the first OK edit


def test_a_missing_ledger_still_outlines(tmp_path):
    # the helpers create the ledger when it is missing (install.py never ran, as in v7)
    t = task(tmp_path)
    (t.tmp / "swe" / ".ledger.json").unlink(missing_ok=True)
    view(t, "pkg/e.py", "4", "8")
    assert repeats(t, 3) == ["already", "already", "outline"]
    assert set(ledger(t)) == {"view", "repeat_key", "repeat_run"}


# ------------------------------------------------------------------ the locate cap, unchanged

def test_the_locate_cap_is_unchanged(tmp_path):
    t = task(tmp_path)
    for q in ("f", "g", "parse"):
        assert "workspace=" in run(t, "locate.py", q)[1]
    for _ in range(2):
        rc, out = run(t, "locate.py", "f")
        assert rc == 0 and out == SEARCH_CAP + "\n", out
    assert ledger(t)["locate"] == 3
    for i in range(20):                                                               # reads stay open after the search cap
        assert kind(view(t, "m.py", str(10 * i + 1), str(10 * i + 5))) == "lines"


# ------------------------------------------------------------------ the refusal-message audit (v7's table, on v7c)

def _shown_twice(t):
    view(t, "m.py", "1", "5")
    view(t, "m.py", "1", "5")


READ_CAP_ROW = "view: read cap before any edit"
V7C_REFUSALS = [r for r in v7h.REFUSALS if r[0] != READ_CAP_ROW] + [
    ("view: range already shown, 2nd repeat", "view.py", _shown_twice, ["m.py", "1-5"], "", "ALREADY SHOWN", 0)]


@pytest.mark.parametrize("rid,helper,setup,argv,stdin,starts,code", V7C_REFUSALS, ids=[r[0] for r in V7C_REFUSALS])
def test_every_refusal_is_one_line_with_the_cause_and_the_next_action(tmp_path, rid, helper, setup, argv, stdin, starts, code):
    v7h.test_every_refusal_is_one_line_with_the_cause_and_the_next_action(tmp_path, rid, helper, setup, argv, stdin, starts, code)


def test_the_audit_table_is_v7s_without_the_read_cap_row(tmp_path):
    dropped = [r for r in v7h.REFUSALS if r not in V7C_REFUSALS]
    assert [r[0] for r in dropped] == [READ_CAP_ROW] and len(V7C_REFUSALS) == len(v7h.REFUSALS)
    assert not any("read cap" in r[5] for r in V7C_REFUSALS)
    _, helper, setup, argv, _, _, _ = dropped[0]
    t = task(tmp_path)
    setup(t)                                                                          # v7's 14 counted reads
    assert kind(run(t, helper, *argv)[1]) == "lines"                                   # the 15th read is no refusal now


# ------------------------------------------------------------------ the counters read v7c's replies

def test_the_counters_read_v7cs_replies(tmp_path):
    """scripts/a6000/v7_counters.py on v7c's real replies: 20 distinct reads, the first read of pkg/e.py and six repeats,
    five locate calls (the 4th and 5th refused). repeat_outlines 2; cap_refusals counts the two search-cap lines only."""
    from test_v7_counters import ok, rc, vc, write_run
    t = task(tmp_path)
    steps = [rc("locator", "python3 /tmp/swe/view.py m.py %d %d" % (a, a + 4), ok(view(t, "m.py", str(a), str(a + 4))))
             for a in range(1, 100, 5)]
    steps += [rc("fixer", "python3 /tmp/swe/view.py pkg/e.py 4 8", ok(view(t, "pkg/e.py", "4", "8"))) for _ in range(7)]
    steps += [rc("locator", 'python3 /tmp/swe/locate.py "%s"' % q, ok(run(t, "locate.py", q)[1])) for q in ("f", "g", "parse", "x", "y")]
    c = vc.counters(str(write_run(tmp_path / "run", {"t": (steps, False)})), "v7")
    assert (c["repeat_outlines"], c["cap_refusals"], c["view_usage_calls"], c["loops_ge5"]) == (2, 2, 0, 1), c


# ------------------------------------------------------------------ every v7 helper test, re-run on v7c

EXCLUDED = {   # v7 test -> its v7c replacement in this file
    "test_view_cap_boundary_before_the_first_edit": "test_no_refusal_after_any_number_of_distinct_reads",
    "test_failed_edits_do_not_lift_the_cap_and_a_create_does": "test_failed_edits_and_other_helpers_do_not_reset_the_counter",
    "test_the_caps_are_the_constants_the_locator_yaml_states": "test_the_read_cap_is_deleted_not_raised",
    "test_install_creates_the_ledger_next_to_the_views_log_and_a_reinstall_keeps_the_counts": "test_the_ledger_shape",
    "test_the_repeat_refusal_fires_for_the_same_range_in_another_shape": "test_the_same_range_in_any_shape_is_one_run",
    "test_every_refusal_is_one_line_with_the_cause_and_the_next_action": "test_every_refusal_is_one_line_with_the_cause_and_the_next_action",
}
V7_TESTS = sorted(n for n in vars(v7h) if n.startswith("test_") and callable(getattr(v7h, n)))
for _name in V7_TESTS:
    if _name not in EXCLUDED:
        globals()["test_v7_rerun_" + _name[len("test_"):]] = getattr(v7h, _name)


def test_every_v7_helper_test_is_rerun_on_v7c_but_the_excluded_ones():
    assert len(V7_TESTS) == 23 and set(EXCLUDED) <= set(V7_TESTS)
    assert {n for n in globals() if n.startswith("test_v7_rerun_")} == {
        "test_v7_rerun_" + n[len("test_"):] for n in V7_TESTS if n not in EXCLUDED}
    assert all(callable(globals().get(r)) for r in EXCLUDED.values())                  # each one has its replacement here
