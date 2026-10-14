"""v13 = v12-b1024 (our current line: one thinking-on agent, budget 1,024) plus the general levers of docs/forty_two/LEVERS.md,
each added as its own commit after a failing test. Evidence for every lever: docs/forty_two/TIMING.md (Phase A).

Commit 1: v13 was a byte-identical copy of v12-b1024, so every later difference is a lever.
Lever 1 (edits through run_command): on p4_b1024 84 of 228 edit_file/write_file calls lost a required argument (the model closed
the first code string with a backtick or quote instead of the <|"|> delimiter and vLLM's gemma4 parser swallowed the next
argument), 883 s over 11 tasks; 0 of 1,521 thinking-on run_command calls were malformed. v13 drops edit_file and write_file and
step 3 of the prompt gives one python heredoc that replaces an exact block, refuses a missing or repeated block, and refuses a
result that does not compile, all before writing."""
import filecmp, os, re, subprocess, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC, DST = ROOT / "submissions" / "v12-b1024", ROOT / "submissions" / "v13"
LEVER_FILES = {"agent.yaml", "prompts/system.md"}          # files a lever has changed so far


def all_files(d):
    return {str(p.relative_to(d)) for p in Path(d).rglob("*") if p.is_file()}


def prompt(d=DST):
    return (d / "prompts" / "system.md").read_text()


def edit_template():
    """The shell command step 3 teaches, as written in the prompt (the fenced block that holds the EDIT heredoc)."""
    blocks = re.findall(r"```\n(.*?)```", prompt(), re.S)
    found = [b for b in blocks if "<<'EDIT'" in b]
    assert len(found) == 1, f"expected one EDIT template, found {len(found)}"
    return found[0]


def fill(template, path, old, new):
    t = template.replace("path/to/module.py", path)
    t = t.replace("<old lines, copied exactly>\n", old).replace("<new lines>\n", new)
    return t


def test_only_the_lever_files_differ_from_v12_b1024():
    assert all_files(DST) == all_files(SRC)
    for rel in sorted(all_files(SRC)):
        assert filecmp.cmp(SRC / rel, DST / rel, shallow=False) == (rel not in LEVER_FILES), rel
        assert os.stat(SRC / rel).st_mode == os.stat(DST / rel).st_mode, rel


def test_lever1_the_agent_has_no_multi_argument_write_tool():
    text = (DST / "agent.yaml").read_text()
    tools = re.findall(r"^  - (\w+)$", text, re.M)
    assert tools == ["run_command", "read_file", "get_status", "submit_patch"]
    assert text.replace("  - edit_file\n  - write_file\n", "") == (SRC / "agent.yaml").read_text().replace("  - edit_file\n  - write_file\n", "")


def test_lever1_prompt_changes_only_step_3_and_never_names_the_dropped_tools():
    old, new = prompt(SRC), prompt()
    head_old, head_new = old.split("3. Edit")[0], new.split("3. Edit")[0]
    tail_old, tail_new = old.split("4. Check.")[1], new.split("4. Check.")[1]
    assert head_old == head_new and tail_old == tail_new
    assert "edit_file" not in new and "write_file" not in new
    assert "run_command tool" in new.split("3. Edit")[1].split("4. Check.")[0]
    assert "{" not in new and "}" not in new      # ADK templates {name} in an instruction from session state


def test_lever1_template_is_a_bash_heredoc_with_a_quoted_delimiter():
    t = edit_template()
    assert t.startswith("python3 - <<'EDIT'\n") and t.rstrip("\n").endswith("\nEDIT")
    assert "assert s.count(old) == 1" in t and 'compile(s, str(p), "exec")' in t
    assert t.index("compile(") < t.index("write_bytes(")         # nothing is written before both checks pass


def _run(cmd, cwd):
    env = dict(os.environ, PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""))   # python3 = the venv's 3.12
    return subprocess.run(["bash", "-c", cmd], cwd=cwd, capture_output=True, text=True, timeout=60, env=env)


def test_lever1_template_applies_an_exact_edit_with_backslashes_and_quotes(tmp_path):
    src = 'import re\n\nURL = re.compile(r"(?P<url>https?://[-0-9a-zA-Z$_+!`(),.?/;:&=%#~]*)")\n\n\ndef f(x):\n    return "a\\nb" + x\n'
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "m.py").write_text(src)
    old = '    return "a\\nb" + x\n'
    new = '    return "a\\nb" + str(x)  # it\'s "fixed"\n'
    r = _run(fill(edit_template(), "pkg/m.py", old, new), tmp_path)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "pkg" / "m.py").read_text() == src.replace(old, new)
    assert "edited pkg/m.py" in r.stdout


@pytest.mark.parametrize("old", ["    return nothing_like_this\n", "    pass\n"])
def test_lever1_template_refuses_a_missing_or_repeated_block_and_writes_nothing(tmp_path, old):
    src = "def a():\n    pass\n\n\ndef b():\n    pass\n"
    (tmp_path / "m.py").write_text(src)
    r = _run(fill(edit_template(), "m.py", old, "    return 1\n"), tmp_path)
    assert r.returncode != 0 and "AssertionError" in r.stderr
    assert (tmp_path / "m.py").read_text() == src


def test_lever1_template_refuses_an_edit_that_does_not_compile_and_writes_nothing(tmp_path):
    src = "def a(x):\n    return x\n"
    (tmp_path / "m.py").write_text(src)
    r = _run(fill(edit_template(), "m.py", "    return x\n", "    return (x\n"), tmp_path)
    assert r.returncode != 0 and "SyntaxError" in r.stderr
    assert (tmp_path / "m.py").read_text() == src


def test_lever1_template_keeps_the_bytes_it_does_not_touch(tmp_path):
    src = b"# caf\xc3\xa9\r\nX = 1\r\nY = 2\r\n"                # CRLF and non-ASCII outside the edit stay as they were
    (tmp_path / "m.py").write_bytes(src)
    r = _run(fill(edit_template(), "m.py", "Y = 2", "Y = 3"), tmp_path)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "m.py").read_bytes() == src.replace(b"Y = 2", b"Y = 3")


def test_validator_passes():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(DST)], capture_output=True, text=True, timeout=180)
    assert r.returncode == 0 and "OK model=gemma-4-31b-it-qat-w4a16-ct" in r.stdout, r.stdout[-500:] + r.stderr[-1500:]
    assert "tools=['run_command', 'read_file', 'get_status', 'submit_patch']" in r.stdout
    assert "'thinking_budget': 1024" in r.stdout and "'temperature': 1.0" in r.stdout
