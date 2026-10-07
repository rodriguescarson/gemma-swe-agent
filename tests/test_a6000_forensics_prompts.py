"""scripts/a6000/forensics_prompts.py: every helper invocation a bundle's prompts show, run against the bundle's own scripts in a scratch repo (P5 section 2).
Written before the code."""
import importlib.util, os, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("forensics_prompts", ROOT / "scripts" / "a6000" / "forensics_prompts.py")
fp = importlib.util.module_from_spec(spec); spec.loader.exec_module(fp)

TEXT = """Read with run_command(command="python3 /tmp/swe/view.py path/to/file.py START END") (at most 120 lines).
Run the test: `python3 /tmp/swe/test.py --target <test file>` (never the whole suite).
Call `run_skill_script(skill_name="swe-tools", file_path="select_best.py", args={"test": "tests/test_x.py"})` exactly once.
`python3 /tmp/swe/locate.py "<identifiers, error text and keywords from the issue>"`
python3 /tmp/swe/edit.py path/to/file.py <<'EOF'
<<<<<<< SEARCH
exact current lines (copied as read, unique, short)
=======
new lines
>>>>>>> REPLACE
EOF
Or replace lines by number: python3 /tmp/swe/edit.py path/to/file.py --lines 120-135 <<'EOF' then the new lines, then EOF.
Tools you can call: run_command, read_file, edit_file, write_file, get_status, run_skill_script.
"""


def test_extract_invocations_dedupes_and_keeps_heredoc_forms():
    inv = fp.extract_invocations(TEXT)
    kinds = {i.helper for i in inv}
    assert {"view", "test", "select_best", "locate", "edit"} <= kinds
    assert any(i.heredoc for i in inv if i.helper == "edit") and any("--lines" in i.text for i in inv if i.helper == "edit")
    assert len([i for i in inv if i.helper == "view"]) == 1


def test_placeholders_become_real_arguments():
    s = fp.substitute("python3 /tmp/swe/view.py path/to/file.py START END", repo_file="mod.py", test_file="test_mod.py")
    assert s == "python3 /tmp/swe/view.py mod.py 1 3"
    assert fp.substitute("python3 /tmp/swe/test.py --target <test file>", "mod.py", "test_mod.py") == "python3 /tmp/swe/test.py --target test_mod.py"
    assert fp.substitute("python3 /tmp/swe/test.py --target tests/test_x.py::test_name", "mod.py", "test_mod.py") == "python3 /tmp/swe/test.py --target test_mod.py::test_f"
    assert fp.substitute('python3 /tmp/swe/locate.py "<identifiers, error text and keywords from the issue>"', "mod.py", "test_mod.py") == 'python3 /tmp/swe/locate.py "f"'
    assert fp.substitute("python3 /tmp/swe/edit.py path/to/file.py --lines 120-135", "mod.py", "test_mod.py") == "python3 /tmp/swe/edit.py mod.py --lines 2-2"
    assert fp.substitute("python3 /tmp/swe/view.py FILE START END", "mod.py", "test_mod.py") == "python3 /tmp/swe/view.py mod.py 1 3"


def test_tools_named_in_a_prompt_but_not_declared():
    assert fp.tools_named(TEXT) == ["run_command", "read_file", "edit_file", "write_file", "get_status", "run_skill_script"]
    assert fp.undeclared(TEXT, ["run_command", "read_file", "get_status"], skills=True) == ["edit_file", "write_file"]


def test_run_against_a_bundles_scripts_in_a_scratch_repo(tmp_path):
    r = fp.scratch_repo(tmp_path)
    res = fp.run_invocations(ROOT / "submissions" / "v5h2", r, [
        fp.Invocation("python3 /tmp/swe/view.py path/to/file.py START END", "view", False, False),
        fp.Invocation("python3 /tmp/swe/view.py path/to/file.py 150-160", "view", False, False),
        fp.Invocation("python3 /tmp/swe/test.py --target <test file>", "test", False, False),
        fp.Invocation("python3 /tmp/swe/edit.py path/to/file.py <<'EOF'", "edit", True, False),
        fp.Invocation("python3 /tmp/swe/edit.py path/to/file.py --lines 120-135 <<'EOF' then the new lines, then EOF", "edit", True, False),
        fp.Invocation("python3 /tmp/swe/check.py --mode preflight", "check", False, False),
        fp.Invocation('python3 /tmp/swe/locate.py "<identifiers>"', "locate", False, False),
        fp.Invocation('run_skill_script(skill_name="swe-tools", file_path="install.py")', "install", False, False)])
    by = {x.invocation.text: x for x in res}
    assert by["python3 /tmp/swe/view.py path/to/file.py START END"].ok and "1| " in by["python3 /tmp/swe/view.py path/to/file.py START END"].output
    bad = by["python3 /tmp/swe/view.py path/to/file.py 150-160"]
    assert not bad.ok and "usage:" in bad.output                                   # the dash range the model keeps sending is refused
    assert by["python3 /tmp/swe/test.py --target <test file>"].ok and "exit=" in by["python3 /tmp/swe/test.py --target <test file>"].output
    assert by["python3 /tmp/swe/edit.py path/to/file.py <<'EOF'"].ok and "OK" in by["python3 /tmp/swe/edit.py path/to/file.py <<'EOF'"].output
    lines_form = by["python3 /tmp/swe/edit.py path/to/file.py --lines 120-135 <<'EOF' then the new lines, then EOF"]
    assert lines_form.ok and "OK" in lines_form.output, lines_form.output          # --lines takes plain replacement lines, not a SEARCH/REPLACE block
    assert by["python3 /tmp/swe/check.py --mode preflight"].ok
    assert by['python3 /tmp/swe/locate.py "<identifiers>"'].ok and "workspace=" in by['python3 /tmp/swe/locate.py "<identifiers>"'].output
    assert by['run_skill_script(skill_name="swe-tools", file_path="install.py")'].ok and "installed:" in by['run_skill_script(skill_name="swe-tools", file_path="install.py")'].output


def test_bare_mentions_are_extracted_as_mentions_not_run(tmp_path):
    inv = fp.extract_invocations("edit through `python3 /tmp/swe/edit.py` and run shell commands")
    assert len(inv) == 1 and inv[0].mention
    res = fp.run_invocations(ROOT / "submissions" / "v5h2", fp.scratch_repo(tmp_path), inv)
    assert res[0].ok is None and res[0].output == "mention only, not an invocation"


def test_sentence_tails_are_stripped_before_running():
    assert fp.substitute("python3 /tmp/swe/edit.py path/to/file.py --lines 120-135 <<'EOF' then the new lines, then EOF.", "mod.py", "test_mod.py") == "python3 /tmp/swe/edit.py mod.py --lines 2-2"
    assert fp.substitute("python3 /tmp/swe/check.py --mode preflight` and fix what it flags", "mod.py", "test_mod.py") == "python3 /tmp/swe/check.py --mode preflight"


def test_every_invocation_runs_in_a_fresh_repo_and_ledger(tmp_path):
    inv = [fp.Invocation("python3 /tmp/swe/edit.py path/to/file.py <<'EOF'", "edit", True, False)] * 2 + [fp.Invocation("python3 /tmp/swe/view.py path/to/file.py START END", "view", False, False)] * 7
    res = fp.run_invocations(ROOT / "submissions" / "v6p-b", fp.scratch_repo(tmp_path), inv)
    assert all(r.ok for r in res), [(r.invocation.text, r.output[:60]) for r in res if not r.ok]     # no NO MATCH on the second edit, no SHARE SPENT on the 7th view
