"""v13_keep_contract = submissions/v13 plus one rule: when a change makes a function accept new inputs (looser matching, a new
option, a new type), the check must assert that for those new inputs the function still keeps its return promise: the same
type, and a value from the allowed values the caller passed rather than the raw input.

Why (measured, docs/forty_two/tasks/rich_3052.md): five box runs (v7, v7c, b1024, v0-think and v13 itself) added the option and
made matching looser, and every one returns the raw input. On the issue's own example (edge_sweep in the task's ground-truth
JSON) each patch returns a value outside the declared allowed values for 3 of 4 newly accepted inputs, so a one-line
membership assert fails on every one of them; their own checks asserted only that the input was accepted.
Lever text constraints as in tests/test_v13_repro_timeout.py (no code fence, no tool-call-like syntax)."""
import filecmp, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE, DST = ROOT / "submissions" / "v13", ROOT / "submissions" / "v13_keep_contract"
RULE_START = "- When your change makes a function accept new inputs"


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
    for word in ("return", "allowed values", "raw input", "assert"):
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
