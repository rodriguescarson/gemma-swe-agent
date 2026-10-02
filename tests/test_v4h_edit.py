"""v4h edit.py: the one helper added to v4. Every case is a failure mode seen in v4 traces or a rule from the docstring."""
import os, subprocess, sys
from pathlib import Path

EDIT = Path(__file__).resolve().parent.parent / "submissions" / "v4h" / "skills" / "swe-tools" / "scripts" / "edit.py"
SRC = "import os\n\n\ndef f(x):\n    if x:\n        return 1\n    return 2\n\n\ndef g():\n    return \"a\"\n"


def run(cwd, args, stdin=""):
    p = subprocess.run([sys.executable, str(EDIT)] + args, input=stdin, capture_output=True, text=True, cwd=cwd)
    return p.returncode, p.stdout


def block(search, repl):
    return "<<<<<<< SEARCH\n" + search + "=======\n" + repl + ">>>>>>> REPLACE\n"


def write(d, name, text=SRC):
    (d / name).write_text(text)
    return d / name


def test_exact_block_edits_and_shows_region(tmp_path):
    f = write(tmp_path, "m.py")
    rc, out = run(tmp_path, ["m.py"], block("        return 1\n", "        return 10\n"))
    assert rc == 0 and out.startswith("OK m.py: lines 6-6 replaced (1 -> 1 lines)") and "Now:" in out and "6| " in out
    assert f.read_text() == SRC.replace("return 1\n", "return 10\n")


def test_trailing_whitespace_and_indent_shift_fallbacks(tmp_path):
    f = write(tmp_path, "m.py", SRC.replace("    if x:\n", "    if x:   \n"))
    rc, out = run(tmp_path, ["m.py"], block("    if x:\n        return 1\n", "    if x:\n        return 3\n"))
    assert rc == 0 and "matched by rstrip" in out and "return 3" in f.read_text()
    f = write(tmp_path, "n.py")
    rc, out = run(tmp_path, ["n.py"], block("if x:\n    return 1\n", "if x:\n    return 4\n"))
    assert rc == 0 and "matched by strip" in out
    assert "    if x:\n        return 4\n    return 2\n" in f.read_text()           # re-indented to the file's 4 spaces


def test_json_escaped_copy_matches(tmp_path):
    # the model copies read_file output, which it sees JSON-escaped: \" for " and \n for a newline
    f = write(tmp_path, "m.py")
    rc, out = run(tmp_path, ["m.py"], block('    return \\"a\\"\n', '    return "b"\n'))
    assert rc == 0 and "matched by unescaped" in out and 'return "b"' in f.read_text()


def test_numbered_prefixes_and_fences_are_stripped(tmp_path):
    f = write(tmp_path, "m.py")
    body = "```python\n" + block("7| return 2\n", "7| return 20\n") + "```\n"
    rc, out = run(tmp_path, ["m.py"], body)
    assert rc == 0 and "    return 20\n" in f.read_text()


def test_no_match_prints_closest_lines_and_changes_nothing(tmp_path):
    f = write(tmp_path, "m.py")
    rc, out = run(tmp_path, ["m.py"], block("        return 99\n", "        return 1\n"))
    assert rc == 1 and out.startswith("NO MATCH in m.py") and "Closest current lines:" in out and "6| " in out
    assert "--lines 6-6" in out and f.read_text() == SRC


def test_ambiguous_match_refused(tmp_path):
    f = write(tmp_path, "m.py", "x = 1\ny = 2\nx = 1\n")
    rc, out = run(tmp_path, ["m.py"], block("x = 1\n", "x = 3\n"))
    assert rc == 1 and out.startswith("AMBIGUOUS in m.py: the SEARCH block matches 2 places (lines 1, 3)")
    assert f.read_text() == "x = 1\ny = 2\nx = 1\n"


def test_multiple_blocks_are_all_or_nothing(tmp_path):
    f = write(tmp_path, "m.py")
    rc, out = run(tmp_path, ["m.py"], block("        return 1\n", "        return 5\n") + block("nope\n", "x\n"))
    assert rc == 1 and "NO MATCH" in out and f.read_text() == SRC
    rc, out = run(tmp_path, ["m.py"], block("        return 1\n", "        return 5\n") + block("    return 2\n", "    return 6\n"))
    assert rc == 0 and out.count("OK m.py") == 2 and "return 5" in f.read_text() and "return 6" in f.read_text()


def test_lines_mode_replace_delete_and_range_check(tmp_path):
    f = write(tmp_path, "m.py")
    rc, out = run(tmp_path, ["m.py", "--lines", "5-6"], "    if x:\n        return 7\n")
    assert rc == 0 and "lines 5-6 replaced (2 -> 2 lines)" in out and "return 7" in f.read_text()
    rc, out = run(tmp_path, ["m.py", "--lines", "1-1"], "")
    assert rc == 0 and f.read_text().startswith("\n\ndef f")
    rc, out = run(tmp_path, ["m.py", "--lines", "90-95"], "x\n")
    assert rc == 1 and "outside the file" in out


def test_create_and_refuse_existing(tmp_path):
    rc, out = run(tmp_path, ["pkg/new.py", "--create"], "def h():\n    return 1\n")
    assert rc == 0 and out.startswith("OK created pkg/new.py (2 lines)") and (tmp_path / "pkg" / "new.py").read_text() == "def h():\n    return 1\n"
    rc, out = run(tmp_path, ["pkg/new.py", "--create"], "x\n")
    assert rc == 1 and "already exists" in out


def test_protected_paths_refused(tmp_path):
    for p in ("tests/test_x.py", "conftest.py", "pyproject.toml", "a/testing/b.py", "x_test.py"):
        rc, out = run(tmp_path, [p, "--create"], "x\n")
        assert rc == 1 and out.startswith("REFUSED " + p), (p, out)
        assert not (tmp_path / p).exists()


def test_syntax_error_is_reverted(tmp_path):
    f = write(tmp_path, "m.py")
    rc, out = run(tmp_path, ["m.py"], block("def g():\n", "def g(:\n"))
    assert rc == 1 and out.startswith("SYNTAX ERROR after the edit, so it was REVERTED") and f.read_text() == SRC
    assert not list(tmp_path.glob("*.swe_pyc_check")) and not list(tmp_path.glob("*.swe_edit_tmp"))
    rc, out = run(tmp_path, ["bad.py", "--create"], "def (:\n")
    assert rc == 1 and not (tmp_path / "bad.py").exists()


def test_newline_state_and_raw_bytes_round_trip(tmp_path):
    f = tmp_path / "data.txt"
    f.write_bytes(b"a = 1\nb = \xff\xfe\nc = 3")                                      # no final newline, non-UTF-8 bytes
    rc, out = run(tmp_path, ["data.txt"], block("a = 1\n", "a = 2\n"))
    assert rc == 0 and f.read_bytes() == b"a = 2\nb = \xff\xfe\nc = 3"
    g = tmp_path / "m.py"
    g.write_bytes(b"a = 1\n")
    run(tmp_path, ["m.py"], block("a = 1\n", "a = 3\n"))
    assert g.read_bytes() == b"a = 3\n"


def test_early_eof_no_change_and_missing_file_messages(tmp_path):
    f = write(tmp_path, "m.py")
    rc, out = run(tmp_path, ["m.py"], "<<<<<<< SEARCH\n    return 2\n")
    assert rc == 1 and out.startswith("ERROR: the edit ended early") and f.read_text() == SRC
    rc, out = run(tmp_path, ["m.py"], block("    return 2\n", "    return 2\n"))
    assert rc == 1 and out.startswith("NO CHANGE")
    rc, out = run(tmp_path, ["missing.py"], block("a\n", "b\n"))
    assert rc == 1 and out.startswith("NO SUCH FILE: missing.py") and "git ls-files | grep missing.py" in out
    rc, out = run(tmp_path, [], "")
    assert rc == 1 and out.startswith("usage:")


def test_output_is_bounded(tmp_path):
    write(tmp_path, "m.py")
    big = "".join("    y%d = %d\n" % (i, i) for i in range(400))
    rc, out = run(tmp_path, ["m.py"], block("    return 2\n", big + "    return 2\n"))
    assert rc == 0 and len(out) <= 3600 and "Now:" in out
