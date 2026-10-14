"""v13_edge_sweep = submissions/v13 plus one rule: when the fix is inside a loop that walks over its input, call the function
before submitting on the edge inputs (empty, one special item alone, the special item first, last and repeated), each call
under `timeout 10`, and require every call to finish with output shaped like the existing test expectations.

Why (measured, docs/forty_two/tasks/rich_4006.md): the bug had three non-advancing branches. At base 6 of 13 edge inputs hang
(bounded.py, 10 s each). p4 (v5h2) and p4_v7c fixed one branch and submitted at 43-47 s, with 3 of the 13 inputs still hanging;
p4_v7d fixed the other branch and left 3 hanging the other way. Each would have seen the remaining hang within 10 s of a sweep;
none ran one. Lever text constraints as in tests/test_v13_repro_timeout.py (no code fence, no tool-call-like syntax)."""
import filecmp, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE, DST = ROOT / "submissions" / "v13", ROOT / "submissions" / "v13_edge_sweep"
RULE_START = "- When your fix is inside a loop that walks over its input"


def all_files(d):
    return {str(p.relative_to(d)) for p in Path(d).rglob("*") if p.is_file()}


def added_text():
    old = (BASE / "prompts" / "system.md").read_text()
    new = (DST / "prompts" / "system.md").read_text()
    assert new.startswith(old), "the lever only appends to v13's prompt"
    return new[len(old):]


def test_only_the_prompt_differs_from_v13():
    assert all_files(DST) == all_files(BASE)
    for rel in sorted(all_files(BASE)):
        assert filecmp.cmp(BASE / rel, DST / rel, shallow=False) == (rel != "prompts/system.md"), rel


def test_the_lever_is_one_appended_rule_line():
    add = added_text()
    assert add.count("\n") == 1 and add.endswith("\n") and add.startswith(RULE_START)
    for word in ("empty", "first", "last", "repeated", "timeout 10", "existing tests"):
        assert word in add, word


def test_the_added_rule_has_no_code_fence_tool_syntax_or_template_braces():
    add = added_text()
    assert "```" not in add and "<|" not in add and "|>" not in add
    assert "tool_call" not in add and not re.search(r"\bcall:\w", add)
    assert "{" not in add and "}" not in add


def test_no_public_task_specifics_in_the_bundle():
    sys.path.insert(0, str(ROOT / "tests"))
    from test_v13_leakage import leaks
    assert not leaks(DST)


def test_validator_passes():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(DST)], capture_output=True, text=True,
                       timeout=180)
    assert r.returncode == 0 and "OK model=gemma-4-31b-it-qat-w4a16-ct" in r.stdout, r.stdout[-500:] + r.stderr[-1500:]
    assert "tools=['run_command', 'read_file', 'get_status', 'submit_patch']" in r.stdout
