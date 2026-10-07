"""v7's helpers (submissions/v7/skills/swe-tools/scripts), run the way the sandbox runs them: installed copies in a task's
own tmp dir (TMPDIR), cwd = the task's git workspace. Written before the changes (strict test-first).

  fix 1  view.py accepts FILE START END, START-END, START:END, START (START..START+119) and bare FILE (1..120); MAX,
         the per-task views log and the ALREADY SHOWN refusal unchanged (docs/a6000/FAILURE_FORENSICS.md finding 1:
         139 usage-line calls in 63 tasks; P4 + P2 traces: 172 `FILE N-N`, 24 bare `FILE`, 7 several ranges)
  fix 7  edit.py applies a --lines body that carries SEARCH/REPLACE markers as a SEARCH/REPLACE edit (finding 11: 13
         SYNTAX-ERROR reverts were markers written into the file by a --lines edit)
  fix 9  the pre-edit caps: locate.py refuses after 3 calls per task, view.py after 8 calls made before the task's first
         OK edit.py call, uncapped after it; the counts live in <TMPDIR>/swe/.ledger.json next to the views log
  audit  every message a helper prints when it declines or fails an input is ONE line that names the cause and the
         next action (instead / now / next), never a bare usage line; the semantics stay (a test-file edit is still
         refused, a syntax error still rolled back)"""
import collections, json, os, pathlib, re, shutil, subprocess, sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
V7 = ROOT / "submissions" / "v7"
SCRIPTS = V7 / "skills" / "swe-tools" / "scripts"
READ_CAP = "read cap reached before any edit: edit now with edit.py (fixer) or write the plan (locator)"
SEARCH_CAP = "search cap reached: use `git grep -n <name>` or write the plan now"
VIEW_BAD = "usage: view.py takes FILE then line numbers"
BARE_USAGE = re.compile(r"\s*(usage:\s*python3 /tmp/swe/|give args=)")      # v5h2's synopsis lines
MOD = "def f(x):\n    return x\n"
SRC = "import os\n\n\ndef f(x):\n    if x:\n        return 1\n    return 2\n\n\ndef g():\n    return \"a\"\n"
Task = collections.namedtuple("Task", "ws tmp")


def task(tmp_path, name="t"):
    """A task: a git workspace and its own tmp dir with the helpers in <tmp>/swe (what install.py does)."""
    base = tmp_path / name
    ws, tmp = base / "ws", base / "tmp"
    (ws / "pkg").mkdir(parents=True)
    (ws / "tests").mkdir()
    tmp.mkdir()
    (ws / "pkg" / "__init__.py").write_text("")
    (ws / "pkg" / "mod.py").write_text(MOD)
    (ws / "pkg" / "e.py").write_text(SRC)
    (ws / "m.py").write_text("".join(f"line{i}\n" for i in range(1, 301)))
    (ws / "tests" / "test_mod.py").write_text("from pkg.mod import f\n\n\ndef test_f():\n    assert f(2) == 4\n")
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    for c in (["git", "init", "-q"], ["git", "add", "-A"], ["git", "commit", "-qm", "base"]):
        subprocess.run(c, cwd=ws, env=env, check=True, capture_output=True)
    shutil.copytree(SCRIPTS, tmp / "swe", ignore=shutil.ignore_patterns("__pycache__"))
    return Task(ws, tmp)


def env_of(t):
    return dict(os.environ, SWE_WS=str(t.ws), TMPDIR=str(t.tmp), TEST_TMPDIR=str(t.tmp), PYTHONPATH=str(t.ws),
                PYTHONDONTWRITEBYTECODE="1")


def run(t, helper, *args, stdin=""):
    p = subprocess.run([sys.executable, str(t.tmp / "swe" / helper), *args], cwd=t.ws, env=env_of(t), input=stdin,
                       capture_output=True, text=True, timeout=120)
    return p.returncode, p.stdout + p.stderr


def view(t, *args):
    return run(t, "view.py", *args)[1]


def ledger(t):
    return json.loads((t.tmp / "swe" / ".ledger.json").read_text())


def block(search, repl):
    return "<<<<<<< SEARCH\n" + search + "=======\n" + repl + ">>>>>>> REPLACE\n"


def numbered(out):
    return [l for l in out.splitlines() if re.match(r"^\d+\| ", l)]


# ------------------------------------------------------------------ fix 1: view.py call shapes

def test_every_range_shape_prints_the_same_numbered_lines(tmp_path):
    outs = {}
    for k, args in {"two": ("m.py", "10", "40"), "dash": ("m.py", "10-40"), "colon": ("m.py", "10:40")}.items():
        outs[k] = view(task(tmp_path, k), *args)                     # a fresh task each: no repeat refusal
    assert len(set(outs.values())) == 1, outs
    lines = numbered(outs["two"])
    assert lines[0] == "10| line10" and lines[-1] == "40| line40" and len(lines) == 31


def test_start_alone_is_120_lines_from_start_and_bare_file_is_lines_1_to_120(tmp_path):
    assert view(task(tmp_path, "a"), "m.py", "10") == view(task(tmp_path, "b"), "m.py", "10", "129")
    assert numbered(view(task(tmp_path, "c"), "m.py", "10"))[-1] == "129| line129"
    bare = view(task(tmp_path, "d"), "m.py")
    assert bare == view(task(tmp_path, "e"), "m.py", "1", "120")
    assert numbered(bare)[0] == "1| line1" and numbered(bare)[-1] == "120| line120" and len(numbered(bare)) == 120


@pytest.mark.parametrize("args", [("m.py", "abc"), ("m.py", "10", "abc"), ("m.py", "ten-twenty"), ("m.py", "10-x"),
                                  ("m.py", "abc", "10"), ()])
def test_only_non_numeric_input_gets_the_usage_sentence(tmp_path, args):
    # one sentence that starts "usage:" (so the forensics counter keeps seeing it) and names the cause and the next step
    out = view(task(tmp_path), *args)
    assert out.startswith(VIEW_BAD) and len(out.strip().splitlines()) == 1 and not numbered(out), out
    assert "not %r" % " ".join(args) in out and " next" in out


@pytest.mark.parametrize("args", [("m.py", "10", "40"), ("m.py", "10-40"), ("m.py", "10:40"), ("m.py", "10"), ("m.py",),
                                  ("m.py", "40", "10"), ("m.py", "10-20", "30-40"), ("m.py", "10", "20", "30", "40")])
def test_numeric_shapes_never_get_a_usage_or_bad_arguments_line(tmp_path, args):
    out = view(task(tmp_path), *args)
    assert "usage" not in out.lower() and numbered(out), out


def test_reversed_range_and_several_ranges(tmp_path):
    assert numbered(view(task(tmp_path, "r"), "m.py", "40", "10"))[0] == "10| line10"
    out = view(task(tmp_path, "s"), "m.py", "10-20", "30-40")          # P2 traces: typer_42196d4, arrow_1278a21
    assert numbered(out)[0] == "10| line10" and numbered(out)[-1] == "20| line20"
    assert out.strip().splitlines()[-1] == "(one range per call: view 30-40 next)"


def test_the_repeat_refusal_fires_for_the_same_range_in_another_shape(tmp_path):
    t = task(tmp_path)
    assert numbered(view(t, "m.py", "10", "40"))
    for shape in (("m.py", "10-40"), ("m.py", "10:40")):
        out = view(t, *shape)
        assert out.startswith("ALREADY SHOWN") and not numbered(out), (shape, out)
    assert numbered(view(t, "m.py"))                                   # 1-120, a new range
    for shape in (("m.py", "1", "120"), ("m.py", "1"), ("m.py", "1-120"), ("m.py", "1", "300")):   # 1 300 caps to 1-120
        assert view(t, *shape).startswith("ALREADY SHOWN"), shape


def test_max_120_and_the_views_log_are_v5h2s(tmp_path):
    src = (SCRIPTS / "view.py").read_text()
    assert re.search(r"^MAX = 120$", src, re.M)
    t = task(tmp_path)
    out = view(t, "m.py", "1", "300")
    assert len(numbered(out)) == 120 and out.strip().splitlines()[-1] == "(capped at 120 lines; view the next range if needed)"
    log = json.loads((t.tmp / "swe" / ".views.json").read_text())
    assert list(log) == ["m.py:1-120"]                                 # key = relative path:start-end after the cap
    (t.ws / "m.py").write_text((t.ws / "m.py").read_text().replace("line11\n", "EDITED\n"))
    assert "11| EDITED" in view(t, "m.py", "1-120")                   # the file changed: shown again


# ------------------------------------------------------------------ fix 7: SEARCH/REPLACE markers in a --lines body

def test_a_lines_body_with_markers_is_applied_as_a_search_replace_block(tmp_path):
    t = task(tmp_path)
    rc, out = run(t, "edit.py", "pkg/e.py", "--lines", "5-6", stdin=block("        return 1\n", "        return 10\n"))
    assert rc == 0 and out.startswith("OK pkg/e.py: lines 6-6 replaced (1 -> 1 lines)"), out
    text = (t.ws / "pkg" / "e.py").read_text()
    assert text == SRC.replace("return 1\n", "return 10\n") and "<<<<<<<" not in text and "=======" not in text
    notes = [l for l in out.splitlines() if l.startswith("NOTE:")]
    assert len(notes) == 1 and "SEARCH/REPLACE" in notes[0] and "--lines 5-6" in notes[0], out


def test_the_forensics_case_markers_inside_lines_on_a_unique_search(tmp_path):
    # v5h2 fastapi_14306: `edit.py fastapi/routing.py --lines 637-640 <<'EOF'` + a whole block -> SYNTAX ERROR revert
    t = task(tmp_path)
    rc, out = run(t, "edit.py", "pkg/e.py", "--lines", "10-11", stdin=block("def g():\n    return \"a\"\n", "def g():\n    return \"b\"\n"))
    assert rc == 0 and 'return "b"' in (t.ws / "pkg" / "e.py").read_text() and "SYNTAX ERROR" not in out, out


def test_a_plain_lines_body_is_unchanged(tmp_path):
    t = task(tmp_path)
    f = t.ws / "pkg" / "e.py"
    rc, out = run(t, "edit.py", "pkg/e.py", "--lines", "5-6", stdin="    if x:\n        return 7\n")
    assert rc == 0 and "lines 5-6 replaced (2 -> 2 lines)" in out and "NOTE:" not in out and "return 7" in f.read_text()
    rc, out = run(t, "edit.py", "pkg/e.py", "--lines", "1-1", stdin="")
    assert rc == 0 and f.read_text().startswith("\n\ndef f")
    rc, out = run(t, "edit.py", "pkg/e.py", "--lines", "90-95", stdin="x\n")
    assert rc == 1 and "outside" in out


def test_syntax_rollback_still_works(tmp_path):
    t = task(tmp_path)
    f = t.ws / "pkg" / "e.py"
    cases = [(["pkg/e.py"], block("def g():\n", "def g(:\n")),                          # block form
             (["pkg/e.py", "--lines", "10-10"], "def g(:\n"),                         # plain --lines
             (["pkg/e.py", "--lines", "5-6"], block("        return 1\n", "        return (1\n"))]   # markers in --lines
    for args, body in cases:
        rc, out = run(t, "edit.py", *args, stdin=body)
        assert rc == 1 and out.startswith("SYNTAX ERROR") and "REVERTED" in out and f.read_text() == SRC, (args, out)
    assert not list((t.ws / "pkg").glob("*.swe_pyc_check")) and not list((t.ws / "pkg").glob("*.swe_edit_tmp"))
    rc, out = run(t, "edit.py", "pkg/bad.py", "--create", stdin="def (:\n")
    assert rc == 1 and out.startswith("SYNTAX ERROR") and not (t.ws / "pkg" / "bad.py").exists()


def test_a_marker_body_that_does_not_match_fails_in_one_line_that_says_how_it_was_read(tmp_path):
    t = task(tmp_path)
    rc, out = run(t, "edit.py", "pkg/e.py", "--lines", "5-6", stdin=block("        return 99\n", "        return 1\n"))
    assert rc == 1 and out.startswith("NO MATCH in pkg/e.py") and len(out.strip().splitlines()) == 1
    assert "SEARCH/REPLACE markers" in out and (t.ws / "pkg" / "e.py").read_text() == SRC


def test_range_shapes_the_model_sends_without_the_flag_are_accepted(tmp_path):
    # P2 traces: `edit.py arrow/util.py 34-37 <<'EOF'`, `edit.py src/attr/validators.py 39 39`, `--create FILE` first
    for args in (("pkg/e.py", "5-6"), ("pkg/e.py", "5", "6"), ("pkg/e.py", "--lines", "5", "6"), ("pkg/e.py", "--lines", "5:6")):
        t = task(tmp_path, "_".join(args).replace("/", "_"))
        rc, out = run(t, "edit.py", *args, stdin="    if x:\n        return 8\n")
        assert rc == 0 and "lines 5-6 replaced (2 -> 2 lines)" in out, (args, out)
    t = task(tmp_path, "create_first")
    rc, out = run(t, "edit.py", "--create", "pkg/new.py", stdin="def h():\n    return 1\n")
    assert rc == 0 and out.startswith("OK created pkg/new.py") and (t.ws / "pkg" / "new.py").exists(), out


# ------------------------------------------------------------------ fix 9: the pre-edit caps

def test_locate_cap_counts_per_task_dir_and_resets_in_another(tmp_path):
    a = task(tmp_path, "a")
    for i in range(3):
        rc, out = run(a, "locate.py", "f", "parse")
        assert rc == 0 and "workspace=" in out and "symbols=" in out, (i, out)
    for _ in range(2):
        rc, out = run(a, "locate.py", "f")
        assert rc == 0 and out.strip() == SEARCH_CAP, out
    assert ledger(a)["locate"] == 3
    b = task(tmp_path, "b")
    assert "workspace=" in run(b, "locate.py", "f")[1]                 # another task: its own ledger
    assert ledger(b)["locate"] == 1


def test_view_cap_boundary_before_the_first_edit(tmp_path):
    t = task(tmp_path)
    for i in range(8):
        out = view(t, "m.py", str(10 * i + 1), str(10 * i + 5))
        assert numbered(out), (i, out)
    rc, out = run(t, "view.py", "m.py", "200", "210")
    assert rc == 0 and out.strip() == READ_CAP, out
    assert ledger(t)["view"] == 8 and not ledger(t).get("edited")
    assert view(t, "m.py", "abc").strip() == READ_CAP                   # the cap comes first, whatever the arguments


def test_view_is_uncapped_after_the_first_ok_edit_and_the_repeat_refusal_still_applies(tmp_path):
    t = task(tmp_path)
    for i in range(8):
        view(t, "m.py", str(10 * i + 1), str(10 * i + 5))
    rc, out = run(t, "edit.py", "pkg/mod.py", stdin=block("    return x\n", "    return x * 2\n"))
    assert rc == 0 and out.startswith("OK pkg/mod.py") and ledger(t)["edited"] is True, out
    for i in range(8, 14):
        assert numbered(view(t, "m.py", str(10 * i + 1), str(10 * i + 5))), i
    assert view(t, "m.py", "131", "135").startswith("ALREADY SHOWN")


def test_failed_edits_do_not_lift_the_cap_and_a_create_does(tmp_path):
    t = task(tmp_path)
    for i in range(8):
        view(t, "m.py", str(10 * i + 1), str(10 * i + 5))
    assert run(t, "edit.py", "pkg/mod.py", stdin=block("    return 99\n", "    return 1\n"))[0] == 1          # NO MATCH
    assert run(t, "edit.py", "pkg/mod.py", stdin=block("    return x\n", "    return (x\n"))[0] == 1         # SYNTAX ERROR
    assert run(t, "edit.py", "tests/test_mod.py", stdin=block("x\n", "y\n"))[0] == 1                         # REFUSED
    assert view(t, "m.py", "200", "210").strip() == READ_CAP
    assert run(t, "edit.py", "pkg/new.py", "--create", stdin="X = 1\n")[0] == 0
    assert numbered(view(t, "m.py", "200", "210"))


def test_install_creates_the_ledger_next_to_the_views_log_and_a_reinstall_keeps_the_counts(tmp_path):
    t = task(tmp_path)
    shutil.rmtree(t.tmp / "swe")
    p = subprocess.run([sys.executable, str(SCRIPTS / "install.py")], cwd=t.ws, env=env_of(t), capture_output=True, text=True)
    assert p.returncode == 0 and "installed:" in p.stdout, p.stdout + p.stderr
    assert ledger(t) == {"locate": 0, "view": 0, "edited": False}
    run(t, "locate.py", "f")
    view(t, "m.py", "1", "5")
    assert (t.tmp / "swe" / ".views.json").exists() and ledger(t)["locate"] == 1 and ledger(t)["view"] == 1
    subprocess.run([sys.executable, str(SCRIPTS / "install.py")], cwd=t.ws, env=env_of(t), capture_output=True, text=True)
    assert ledger(t)["locate"] == 1 and ledger(t)["view"] == 1          # the recovery install does not reset the caps


def ws_constants():
    """LOCATE_CAP, VIEW_CAP and the two refusal texts from v7's _ws.py, read in a child that writes no bytecode into the
    bundle (a __pycache__ there fails tests/test_bundles.py and ships in the zip)."""
    code = ("import json, sys\nsys.dont_write_bytecode = True\nsys.path.insert(0, %r)\nimport _ws\n"
            "print(json.dumps([_ws.LOCATE_CAP, _ws.VIEW_CAP, _ws.READ_CAP_MSG, _ws.SEARCH_CAP_MSG]))\n" % str(SCRIPTS))
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_the_caps_are_the_constants_the_locator_yaml_states():
    assert ws_constants() == [3, 8, READ_CAP, SEARCH_CAP]


# ------------------------------------------------------------------ the refusal-message audit

def _view_once(t):
    view(t, "m.py", "1", "5")


def _spend_reads(t):
    for i in range(8):
        view(t, "m.py", str(10 * i + 101), str(10 * i + 105))


def _spend_locates(t):
    for _ in range(3):
        run(t, "locate.py", "f")


def _ambiguous(t):
    (t.ws / "pkg" / "amb.py").write_text("x = 1\ny = 2\nx = 1\n")


def _slow_test(t):
    (t.ws / "tests" / "test_slow.py").write_text("import time\n\n\ndef test_slow():\n    time.sleep(20)\n")


def _empty_test(t):
    (t.ws / "tests" / "test_empty.py").write_text("X = 1\n")


def _bad_checkpoint(t):
    (t.tmp / "_swe_best.diff").write_text("diff --git a/nope.py b/nope.py\n--- a/nope.py\n+++ b/nope.py\n@@ -1 +1 @@\n-a\n+b\n")


EDIT_OK = block("    return x\n", "    return x * 2\n")
# (id, helper, setup, argv, stdin, the line starts with, exit code)
REFUSALS = [
    ("view: non-numeric range", "view.py", None, ["m.py", "abc"], "", VIEW_BAD, 0),
    ("view: no arguments", "view.py", None, [], "", VIEW_BAD, 0),
    ("view: no such file", "view.py", None, ["nope.py", "1", "5"], "", "no such file", 0),
    ("view: range already shown", "view.py", _view_once, ["m.py", "1-5"], "", "ALREADY SHOWN", 0),
    ("view: range past the end", "view.py", None, ["m.py", "900", "950"], "", "PAST END", 0),
    ("view: read cap before any edit", "view.py", _spend_reads, ["m.py", "1", "5"], "", "read cap reached", 0),
    ("edit: no arguments", "edit.py", None, [], "", "edit.py edits one file", 1),
    ("edit: --help", "edit.py", None, ["--help"], "", "edit.py edits one file", 1),
    ("edit: unknown argument", "edit.py", None, ["pkg/mod.py", "--frob"], EDIT_OK, "ERROR: unknown argument", 1),
    ("edit: test file", "edit.py", None, ["tests/test_mod.py"], EDIT_OK, "REFUSED tests/test_mod.py", 1),
    ("edit: config file", "edit.py", None, ["pyproject.toml", "--create"], "x = 1\n", "REFUSED pyproject.toml", 1),
    ("edit: --create on an existing file", "edit.py", None, ["pkg/mod.py", "--create"], "x\n", "REFUSED --create", 1),
    ("edit: no such file", "edit.py", None, ["pkg/nope.py"], EDIT_OK, "NO SUCH FILE", 1),
    ("edit: --lines not a range", "edit.py", None, ["pkg/mod.py", "--lines", "a-b"], "x\n", "ERROR: --lines", 1),
    ("edit: --lines outside the file", "edit.py", None, ["pkg/mod.py", "--lines", "90-95"], "x\n", "ERROR: --lines 90-95", 1),
    ("edit: heredoc ended early", "edit.py", None, ["pkg/mod.py"], "<<<<<<< SEARCH\n    return x\n", "ERROR: the edit ended early", 1),
    ("edit: empty SEARCH", "edit.py", None, ["pkg/mod.py"], block("\n", "x\n"), "ERROR: the SEARCH part is empty", 1),
    ("edit: no block", "edit.py", None, ["pkg/mod.py"], "just text\n", "ERROR: no <<<<<<< SEARCH", 1),
    ("edit: NO MATCH", "edit.py", None, ["pkg/mod.py"], block("    return 99\n", "    return 1\n"), "NO MATCH in pkg/mod.py", 1),
    ("edit: AMBIGUOUS", "edit.py", _ambiguous, ["pkg/amb.py"], block("x = 1\n", "x = 3\n"), "AMBIGUOUS in pkg/amb.py", 1),
    ("edit: NO CHANGE", "edit.py", None, ["pkg/mod.py"], block("    return x\n", "    return x\n"), "NO CHANGE", 1),
    ("edit: SYNTAX ERROR", "edit.py", None, ["pkg/mod.py"], block("    return x\n", "    return (x\n"), "SYNTAX ERROR", 1),
    ("edit: SYNTAX ERROR in --create", "edit.py", None, ["pkg/new.py", "--create"], "def (:\n", "SYNTAX ERROR", 1),
    ("edit: markers in --lines, NO MATCH", "edit.py", None, ["pkg/mod.py", "--lines", "2-2"],
     block("    return 99\n", "    return 1\n"), "NO MATCH in pkg/mod.py", 1),
    ("test: no target", "test.py", None, [], "", "NO TARGET", 0),
    ("test: timeout", "test.py", _slow_test, ["--target", "tests/test_slow.py", "--timeout", "2"], "", "TIMEOUT", 0),
    ("test: target not found", "test.py", None, ["--target", "tests/test_nope.py"], "", "exit=4", 0),
    ("test: no tests in the target", "test.py", _empty_test, ["--target", "tests/test_empty.py"], "", "exit=5", 0),
    ("check: restore without a checkpoint", "check.py", None, ["--mode", "restore"], "", "no checkpoint", 0),
    ("check: restore that does not apply", "check.py", _bad_checkpoint, ["--mode", "restore"], "", "restore failed", 0),
    ("locate: no matches", "locate.py", None, ["zzqqxx"], "", "no matches", 0),
    ("locate: no query", "locate.py", None, [], "", "no query", 0),
    ("locate: search cap", "locate.py", _spend_locates, ["f"], "", "search cap reached", 0),
]


@pytest.mark.parametrize("rid,helper,setup,argv,stdin,starts,code", REFUSALS, ids=[r[0] for r in REFUSALS])
def test_every_refusal_is_one_line_with_the_cause_and_the_next_action(tmp_path, rid, helper, setup, argv, stdin, starts, code):
    t = task(tmp_path)
    if setup:
        setup(t)
    rc, out = run(t, helper, *argv, stdin=stdin)
    lines = out.strip().splitlines()
    assert len(lines) == 1, (rid, out)
    assert lines[0].startswith(starts), (rid, out)
    assert not BARE_USAGE.match(lines[0]), (rid, out)                  # a sentence, not a synopsis
    assert re.search(r"\b(instead|now|next)\b", lines[0]), (rid, out)
    assert "Traceback" not in out and rc == code, (rid, rc, out)


def test_install_that_cannot_write_anywhere_says_what_to_do_instead(tmp_path):
    t = task(tmp_path)
    code = ("import runpy, shutil\n"
            "def boom(*a, **k):\n    raise PermissionError(13, 'Permission denied')\n"
            "shutil.copy = boom\n"
            f"runpy.run_path({str(SCRIPTS / 'install.py')!r}, run_name='__main__')\n")
    p = subprocess.run([sys.executable, "-c", code], cwd=t.ws, env=env_of(t), capture_output=True, text=True)
    lines = (p.stdout + p.stderr).strip().splitlines()
    assert p.returncode == 0 and len(lines) == 1 and lines[0].startswith("INSTALL FAILED"), p.stdout + p.stderr
    assert re.search(r"\b(instead|now|next)\b", lines[0])


def test_the_refusals_keep_their_semantics(tmp_path):
    t = task(tmp_path)
    test_file = t.ws / "tests" / "test_mod.py"
    before = test_file.read_text()
    rc, out = run(t, "edit.py", "tests/test_mod.py", stdin=block("    assert f(2) == 4\n", "    assert True\n"))
    assert rc == 1 and test_file.read_text() == before and "under pkg/" in out          # names the source package
    rc, out = run(t, "edit.py", "pkg/mod.py", stdin=block("    return x\n", "    return (x\n"))
    assert rc == 1 and (t.ws / "pkg" / "mod.py").read_text() == MOD
    rc, out = run(t, "edit.py", "pkg/mod.py", stdin=block("    return 99\n", "    return 1\n"))
    assert "--lines 2-2" in out                                         # the closest line and the range to use instead
    rc, out = run(t, "check.py", "--mode")                              # a missing mode value: preflight, no traceback
    assert "DIFF:" in out and "Traceback" not in out


def test_checkpoints_live_in_the_task_tmp_not_the_host_tmp(tmp_path):
    """check.py --mode save/restore used the host's /tmp/_swe_best.diff: one task could restore another's diff."""
    a, b = task(tmp_path, "a"), task(tmp_path, "b")
    (a.ws / "pkg" / "mod.py").write_text("def f(x):\n    return x * 2\n")
    assert run(a, "check.py", "--mode", "save")[1].startswith("saved checkpoint")
    assert (a.tmp / "_swe_best.diff").exists()
    assert run(b, "check.py", "--mode", "restore")[1].startswith("no checkpoint")
    (a.ws / "pkg" / "mod.py").write_text(MOD)
    assert run(a, "check.py", "--mode", "restore")[1].startswith("restored checkpoint")
    assert "x * 2" in (a.ws / "pkg" / "mod.py").read_text()
