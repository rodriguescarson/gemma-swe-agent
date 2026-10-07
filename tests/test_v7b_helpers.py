"""v7b fix 1 (docs/GAPS_2026-10-06.md, last section): the read-cap refusal stops being a loop trap.

Evidence (eval/a6000/results/p4_v7, the box's v7 run, cap 14): 6 of 74 tasks hit the read cap, 107 refusals, every one a
fixer call; in 4 of them the identical refused view.py call came back >= 5 times in a row (rich_3930 x41, fastapi_15280
x29 then x8, rich_3468 x18): identical call, identical one-line refusal, until the 70-call budget ran out.

v7b keeps the cap (VIEW_CAP reads before the task's first OK edit) and counts the task's consecutive refused reads in the
ledger (refused_run). The 3rd consecutive refused read gets, instead of the refusal line, an outline of the REQUESTED
file: every top-level def/class (module-level if/try blocks included) and every method (a def in a class body, nested
classes included) as `START-END kind name(args)`, one per line, at most 60 (the rest summed up in "... N more" lines; the
60 shown start a few entries above the requested line, so a long file shows the part the model asked for), then the line
"outline only: pick a range and edit it now with `python3 /tmp/swe/edit.py FILE --lines A-B`" with FILE the requested
path. The run then restarts: the 4th and 5th refused reads get the refusal line, the 6th the outline, and so on. A read
that goes ahead and an OK edit end the run; nothing else does (failed edits, locate.py, raw greps). A file that cannot
be outlined gets one "outline unavailable (...)" line in place of the entries (a syntax error: "outline unavailable
(syntax error at line N)").

The helpers run the way the sandbox runs them (installed copies in a task's own TMPDIR, cwd = the task's workspace):
tests/test_v7_helpers.py's task() with its scripts dir pointed at v7b. Every v7 helper test is re-run on v7b at the end
of this file, except the ledger-shape one, which v7b replaces (its ledger has one more key). Written before the change
(strict test-first)."""
import json, os, shutil, subprocess, sys
from pathlib import Path

import pytest

import test_v7_helpers as v7h
from test_v7_helpers import block, ledger, numbered, run, task, view

ROOT = Path(__file__).resolve().parents[1]
V7B = ROOT / "submissions" / "v7b"
SCRIPTS = V7B / "skills" / "swe-tools" / "scripts"
READ_CAP = "read cap reached before any edit: edit now with edit.py (fixer) or write the plan (locator)"
LAST = "outline only: pick a range and edit it now with `python3 /tmp/swe/edit.py %s --lines A-B`"
E_OUTLINE = "4-7 def f(x)\n10-11 def g()\n" + LAST % "pkg/e.py"      # v7h.SRC: f at 4-7, g at 10-11
OUTLINED = '''"""A module with every shape the outline lists or skips."""
import abc
from typing import TYPE_CHECKING


def top(a, b=1, *args, key=None, **kw):
    def inner():
        return 1
    return inner


async def fetch(url):
    return url


def pos(a, /, b):
    return a


class Base:
    """doc"""

    def __init__(self, x):
        self.x = x

    @staticmethod
    def make(*, size):
        class Local:
            pass
        return Local

    async def run(self):
        return self.x

    class Meta:
        def opts(cls):
            return {}


class Child(Base, metaclass=abc.ABCMeta):
    def run(self):
        return 2


if TYPE_CHECKING:
    def typed() -> int:
        ...
else:
    try:
        def typed():
            return 0
    except ImportError:
        pass

square = lambda v: v * v
'''
OUTLINED_ENTRIES = ["6-9 def top(a, b, *args, key, **kw)",          # inner (a def inside a def) is not listed
                    "12-13 async def fetch(url)",
                    "16-17 def pos(a, /, b)",
                    "20-37 class Base",
                    "23-24 def Base.__init__(self, x)",
                    "27-30 def Base.make(*, size)",                 # the def line, not the decorator; Local is not listed
                    "32-33 async def Base.run(self)",
                    "35-37 class Base.Meta",
                    "36-37 def Base.Meta.opts(cls)",
                    "40-42 class Child(Base, metaclass=abc.ABCMeta)",
                    "41-42 def Child.run(self)",
                    "46-47 def typed()",                            # both branches of the module-level if/try
                    "50-51 def typed()"]                            # the lambda is not listed


@pytest.fixture(autouse=True)
def _v7b_scripts(monkeypatch):
    """test_v7_helpers.task() and ws_constants() read the scripts dir from their module global: v7b's in this module."""
    monkeypatch.setattr(v7h, "SCRIPTS", SCRIPTS)


def spend_reads(t):
    """The 14 counted reads of the pre-edit cap (on m.py, so pkg/ stays unread)."""
    for i in range(14):
        assert numbered(view(t, "m.py", str(10 * i + 101), str(10 * i + 105))), i


def capped(tmp_path, name="t"):
    t = task(tmp_path, name)
    spend_reads(t)
    return t


def kind(out):
    """'refuse' for the one-line refusal, 'outline' for an outline reply (it ends with the outline-only line)."""
    lines = out.strip().splitlines()
    if lines == [READ_CAP]:
        return "refuse"
    if lines and lines[-1].startswith("outline only: pick a range and edit it now with `python3 /tmp/swe/edit.py "):
        return "outline"
    return out


def outline_of(tmp_path, rel, text, *args, name="o"):
    """The outline view.py prints for `rel` (written with `text`) on the 3rd consecutive refused read."""
    t = capped(tmp_path, name)
    if text is not None:
        (t.ws / rel).parent.mkdir(parents=True, exist_ok=True)
        (t.ws / rel).write_text(text)
    for _ in range(2):
        assert view(t, rel, *args).strip() == READ_CAP
    rc, out = run(t, "view.py", rel, *args)
    assert rc == 0 and "Traceback" not in out, out
    return out


def ws_attrs(*names):
    """Attributes of v7b's _ws.py, read in a child that writes no bytecode into the bundle."""
    code = ("import json, sys\nsys.dont_write_bytecode = True\nsys.path.insert(0, %r)\nimport _ws\n"
            "print(json.dumps([getattr(_ws, n, None) for n in %r]))\n" % (str(SCRIPTS), list(names)))
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


# ------------------------------------------------------------------ the sequence

def test_the_exact_sequence_refuse_refuse_outline_refuse_refuse_outline(tmp_path):
    t = capped(tmp_path)
    outs, runs = [], []
    for _ in range(6):                                                  # the identical call, six times in a row
        rc, out = run(t, "view.py", "pkg/e.py", "4", "8")
        assert rc == 0, out
        outs.append(out)
        runs.append(ledger(t)["refused_run"])
    assert [kind(o) for o in outs] == ["refuse", "refuse", "outline", "refuse", "refuse", "outline"], outs
    assert outs[2].strip() == outs[5].strip() == E_OUTLINE, outs[2]
    assert runs == [1, 2, 0, 1, 2, 0]
    assert ledger(t)["view"] == 14 and not ledger(t).get("edited")       # refused reads are not counted reads


def test_the_sequence_continues_past_six(tmp_path):
    t = capped(tmp_path)
    kinds = [kind(view(t, "pkg/e.py", "1-20")) for _ in range(12)]
    assert kinds == ["refuse", "refuse", "outline"] * 4


def test_the_one_line_refusal_is_v7s_text(tmp_path):
    assert ws_attrs("READ_CAP_MSG", "SEARCH_CAP_MSG", "LOCATE_CAP", "VIEW_CAP", "OUTLINE_EVERY") == [
        READ_CAP, "search cap reached: use `git grep -n <name>` or write the plan now", 3, 14, 3]
    t = capped(tmp_path)
    assert view(t, "pkg/e.py", "4", "8") == READ_CAP + "\n"            # one line, exactly v7's


# ------------------------------------------------------------------ the outline's content

def test_the_outline_lists_top_level_defs_classes_and_methods_with_their_line_ranges(tmp_path):
    out = outline_of(tmp_path, "pkg/outlined.py", OUTLINED, "1", "40")
    assert out.strip().splitlines() == OUTLINED_ENTRIES + [LAST % "pkg/outlined.py"], out


def test_the_outline_names_the_requested_path_as_sent(tmp_path):
    out = outline_of(tmp_path, "pkg/e.py", None, "10-11")
    assert out.strip() == E_OUTLINE
    t = capped(tmp_path, "abs")
    absolute = str(t.ws / "pkg" / "e.py")
    for _ in range(2):
        view(t, absolute, "1", "5")
    assert view(t, absolute, "1", "5").strip().splitlines() == ["4-7 def f(x)", "10-11 def g()", LAST % absolute]


def many_defs(n, name="f"):
    return "".join("def %s%d(x):\n    return x\n\n" % (name, i) for i in range(n))   # def i at lines 3i+1 .. 3i+2


def entries(out):
    return [l for l in out.strip().splitlines()[:-1] if not l.startswith("... ")]


def test_the_outline_is_capped_at_60_entries_with_n_more(tmp_path):
    src = many_defs(100)
    out = outline_of(tmp_path, "pkg/big.py", src, name="top")             # bare FILE: lines 1-120, so the top of the file
    lines = out.strip().splitlines()
    assert lines[:60] == ["%d-%d def f%d(x)" % (3 * i + 1, 3 * i + 2, i) for i in range(60)]
    assert lines[60:] == ["... 40 more", LAST % "pkg/big.py"]
    exact = outline_of(tmp_path, "pkg/sixty.py", many_defs(60), name="sixty")
    assert len(entries(exact)) == 60 and "... " not in exact               # 60 fit: no marker
    over = outline_of(tmp_path, "pkg/sixty1.py", many_defs(61), name="sixty1")
    assert len(entries(over)) == 60 and over.strip().splitlines()[-2] == "... 1 more"


def test_a_long_file_shows_the_60_entries_around_the_requested_line(tmp_path):
    src = many_defs(100)
    tail = outline_of(tmp_path, "pkg/big.py", src, "280", "300", name="tail")       # f93 starts at line 280
    lines = tail.strip().splitlines()
    assert lines[0] == "... 40 more" and len(entries(tail)) == 60
    assert "280-281 def f93(x)" in lines and lines[-2] == "298-299 def f99(x)"
    mid = outline_of(tmp_path, "pkg/big.py", src, "91-100", name="mid")              # f30 starts at line 91
    lines = mid.strip().splitlines()
    assert lines[0] == "... 20 more" and lines[-2] == "... 20 more" and len(entries(mid)) == 60
    assert lines[1] == "61-62 def f20(x)" and "91-92 def f30(x)" in lines
    assert lines[-1] == LAST % "pkg/big.py"


def test_the_outline_stays_inside_run_commands_5000_char_cut(tmp_path):
    # run_command keeps the first 5,000 chars of stdout with no marker (research/harness_runtime.md 6), so the
    # outline-only line must always arrive: long names and signatures are cut per line
    src = "".join("def a_really_long_function_name_that_keeps_going_number_%d(self, first_argument, second_argument, "
                  "*args, keyword_only_argument=None, **kwargs):\n    return 1\n\n" % i for i in range(100))
    out = outline_of(tmp_path, "pkg/long_names_in_a_deep_package_path/module_with_a_long_name.py", src)
    assert len(out) < 4700, len(out)
    assert out.strip().splitlines()[-1] == LAST % "pkg/long_names_in_a_deep_package_path/module_with_a_long_name.py"
    assert all(len(l) <= 72 for l in entries(out)), max(entries(out), key=len)


@pytest.mark.parametrize("rel,text,args,line", [
    ("pkg/broken.py", "import os\n\ndef f(:\n    pass\n", ("1", "5"), "outline unavailable (syntax error at line 3)"),
    ("README.md", "# title\n\nsome text\n", ("1", "5"), "outline unavailable (not a Python file; it has 3 lines)"),
    ("pkg/consts.py", "A = 1\nB = 2\n", ("1", "5"), "outline unavailable (no def or class; it has 2 lines)"),
    ("pkg/nope.py", None, ("1", "5"), "outline unavailable (no such file: pkg/nope.py)"),
    ("m.py", None, ("abc",), "outline unavailable (no def or class; it has 300 lines)"),   # whatever the arguments
])
def test_a_file_that_cannot_be_outlined_gets_one_line_then_the_outline_only_line(tmp_path, rel, text, args, line):
    out = outline_of(tmp_path, rel, text, *args)
    assert out.strip().splitlines() == [line, LAST % rel], out


def test_parse_warnings_never_reach_the_reply(tmp_path):
    # Python 3.12's ast.parse prints "SyntaxWarning: invalid escape sequence" to stderr, which the model would read
    out = outline_of(tmp_path, "pkg/esc.py", 'import re\nPAT = "\\d+"\n\n\ndef f(x):\n    return re.match(PAT, x)\n')
    assert out.strip().splitlines() == ["5-6 def f(x)", LAST % "pkg/esc.py"], out


def test_no_file_named_gets_one_line_then_the_outline_only_line(tmp_path):
    t = capped(tmp_path)
    for _ in range(2):
        assert view(t).strip() == READ_CAP
    assert view(t).strip().splitlines() == ["outline unavailable (no file named)", LAST % "FILE"]


def test_the_outline_turn_shows_no_lines_and_logs_no_view(tmp_path):
    t = capped(tmp_path)
    log = (t.tmp / "swe" / ".views.json").read_text()
    outs = [view(t, "pkg/e.py", "1", "11") for _ in range(3)]
    assert kind(outs[2]) == "outline" and not numbered(outs[2])           # "1| import os" never shows on a refused read
    assert (t.tmp / "swe" / ".views.json").read_text() == log


# ------------------------------------------------------------------ what ends a run, and what does not

def test_an_ok_edit_ends_the_run_and_lifts_the_cap(tmp_path):
    t = capped(tmp_path)
    for _ in range(2):
        view(t, "pkg/e.py", "4", "8")
    assert ledger(t)["refused_run"] == 2
    rc, out = run(t, "edit.py", "pkg/mod.py", stdin=block("    return x\n", "    return x * 2\n"))
    assert rc == 0 and out.startswith("OK pkg/mod.py"), out
    led = ledger(t)
    assert (led["view"], led["edited"], led["refused_run"]) == (14, True, 0), led
    assert numbered(view(t, "pkg/e.py", "4", "8"))                         # uncapped from now on, as in v7
    assert ledger(t)["refused_run"] == 0


def test_a_read_that_goes_ahead_ends_the_run(tmp_path):
    # unreachable in a normal task (only an OK edit lifts the cap), pinned so a cap change cannot leave a stale run
    t = task(tmp_path)
    for i in range(13):
        view(t, "m.py", str(10 * i + 101), str(10 * i + 105))
    (t.tmp / "swe" / ".ledger.json").write_text(json.dumps({"locate": 0, "view": 13, "edited": False, "refused_run": 2}))
    assert numbered(view(t, "pkg/e.py", "4", "8"))                         # the 14th counted read goes ahead
    assert ledger(t) == {"locate": 0, "view": 14, "edited": False, "refused_run": 0}
    assert [kind(view(t, "pkg/e.py", "1", "3")) for _ in range(3)] == ["refuse", "refuse", "outline"]


def test_failed_edits_and_other_helpers_do_not_end_the_run(tmp_path):
    t = capped(tmp_path)
    for _ in range(2):
        view(t, "pkg/e.py", "4", "8")
    assert run(t, "edit.py", "pkg/mod.py", stdin=block("    return 99\n", "    return 1\n"))[0] == 1       # NO MATCH
    assert run(t, "edit.py", "pkg/mod.py", stdin=block("    return x\n", "    return (x\n"))[0] == 1      # SYNTAX ERROR
    assert run(t, "edit.py", "tests/test_mod.py", stdin=block("x\n", "y\n"))[0] == 1                      # REFUSED
    assert "workspace=" in run(t, "locate.py", "f")[1]
    assert ledger(t)["refused_run"] == 2 and not ledger(t).get("edited")
    assert kind(view(t, "pkg/e.py", "4", "8")) == "outline"              # still the 3rd refused read in a row


def test_the_run_is_per_task(tmp_path):
    a, b = capped(tmp_path, "a"), capped(tmp_path, "b")
    for _ in range(2):
        view(a, "pkg/e.py", "4", "8")
    assert kind(view(b, "pkg/e.py", "4", "8")) == "refuse"               # b's own ledger: its first refused read
    assert kind(view(a, "pkg/e.py", "4", "8")) == "outline"


# ------------------------------------------------------------------ the ledger

def test_the_ledger_shape(tmp_path):
    t = task(tmp_path)
    shutil.rmtree(t.tmp / "swe")
    p = subprocess.run([sys.executable, str(SCRIPTS / "install.py")], cwd=t.ws, env=v7h.env_of(t), capture_output=True, text=True)
    assert p.returncode == 0 and "installed:" in p.stdout, p.stdout + p.stderr
    assert ledger(t) == {"locate": 0, "view": 0, "edited": False, "refused_run": 0}       # install.py made it
    run(t, "locate.py", "f")
    spend_reads(t)
    assert ledger(t) == {"locate": 1, "view": 14, "edited": False, "refused_run": 0}
    view(t, "pkg/e.py", "4", "8")
    view(t, "pkg/e.py", "4", "8")
    assert ledger(t) == {"locate": 1, "view": 14, "edited": False, "refused_run": 2}
    subprocess.run([sys.executable, str(SCRIPTS / "install.py")], cwd=t.ws, env=v7h.env_of(t), capture_output=True, text=True)
    assert ledger(t) == {"locate": 1, "view": 14, "edited": False, "refused_run": 2}       # a recovery install keeps it
    view(t, "pkg/e.py", "4", "8")
    assert ledger(t) == {"locate": 1, "view": 14, "edited": False, "refused_run": 0}       # the outline restarted it
    assert run(t, "edit.py", "pkg/new.py", "--create", stdin="X = 1\n")[0] == 0
    assert ledger(t) == {"locate": 1, "view": 14, "edited": True, "refused_run": 0}


def test_a_missing_ledger_still_caps_and_outlines(tmp_path):
    # the helpers create the ledger when it is missing (install.py never ran, as in v7)
    t = task(tmp_path)
    (t.tmp / "swe" / ".ledger.json").unlink(missing_ok=True)
    spend_reads(t)
    assert [kind(view(t, "pkg/e.py", "4", "8")) for _ in range(3)] == ["refuse", "refuse", "outline"]
    assert set(ledger(t)) == {"view", "refused_run"}


# ------------------------------------------------------------------ every v7 helper test, re-run on v7b

V7_LEDGER_SHAPE = "test_install_creates_the_ledger_next_to_the_views_log_and_a_reinstall_keeps_the_counts"
V7_TESTS = sorted(n for n in vars(v7h) if n.startswith("test_") and callable(getattr(v7h, n)))
for _name in V7_TESTS:
    if _name != V7_LEDGER_SHAPE:                                        # replaced by test_the_ledger_shape above
        globals()["test_v7_rerun_" + _name[len("test_"):]] = getattr(v7h, _name)


def test_every_v7_helper_test_is_rerun_on_v7b_but_the_ledger_shape():
    rerun = {n for n in globals() if n.startswith("test_v7_rerun_")}
    assert len(V7_TESTS) == 23 and V7_LEDGER_SHAPE in V7_TESTS
    assert rerun == {"test_v7_rerun_" + n[len("test_"):] for n in V7_TESTS if n != V7_LEDGER_SHAPE}
