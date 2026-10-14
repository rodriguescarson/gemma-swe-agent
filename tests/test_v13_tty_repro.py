"""v13_tty_repro = submissions/v13 plus ONE change: one rule appended to the Rules list of prompts/system.md.

Lever (docs/forty_two/tasks/rich_3934.md): the sandbox's stdout is a pipe, so a library that checks for a terminal prints less
(no styles, no cursor control, sometimes nothing) in a repro than it does for the user who filed the issue. On rich_3934 p4_b1024's
first command was the right user program, but it printed 0 bytes in the pipe; the run never saw the stray newline and hit the cap
with no edit. The same program with the library's terminal switch on and the output's repr printed shows the newline (measured
offline, the write-up). The rule names no task, file, function, option or test.

Constraints pinned here:
- every file other than prompts/system.md is byte-identical to submissions/v13 (same modes);
- prompts/system.md is v13's with exactly one rule appended after the last rule;
- the rule has no fenced block, backtick, brace and nothing shaped like a tool call (the coordinator's 2026-10-14 warning: on the
  v13 screen one task's first reply put a tool call in the message text, suspected to follow the fenced heredoc);
- no public-task specifics (the deny list of tests/test_v13_leakage.py) and scripts/validate.py passes."""
import filecmp, importlib.util, os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE, DST = ROOT / "submissions" / "v13", ROOT / "submissions" / "v13_tty_repro"
RULE = ("- The sandbox's output goes to a pipe, not a terminal, and many libraries print less or no styling there: when the issue"
        " is about printed or displayed output, make the repro turn on the library's own switch for terminal output if it has"
        " one, capture the output and print its repr, so newlines, colours and escape codes are visible.")


def all_files(d):
    return {str(p.relative_to(d)) for p in Path(d).rglob("*") if p.is_file()}


def test_only_the_prompt_differs_from_v13():
    assert all_files(DST) == all_files(BASE)
    for rel in sorted(all_files(BASE)):
        assert filecmp.cmp(BASE / rel, DST / rel, shallow=False) == (rel != "prompts/system.md"), rel
        assert os.stat(BASE / rel).st_mode == os.stat(DST / rel).st_mode, rel


def test_the_prompt_is_v13_plus_one_rule_at_the_end():
    old, new = (BASE / "prompts" / "system.md").read_text(), (DST / "prompts" / "system.md").read_text()
    assert old.endswith(".\n") and old.rstrip("\n").splitlines()[-1].startswith("- ")      # v13 ends with its last rule
    assert new == old + RULE + "\n"
    assert new.split("Rules:\n")[1].count("\n- ") + 1 == old.split("Rules:\n")[1].count("\n- ") + 2


def test_the_rule_has_no_code_block_or_tool_call_shape():
    for bad in ("```", "`", "{", "}", "<|", "|>", "call:", "tool_call", "<<", "run_command", "read_file", "submit_patch"):
        assert bad not in RULE, bad
    assert RULE.count(".") == 1 and RULE.endswith(".")                        # one sentence


def _leaks(bundle):
    spec = importlib.util.spec_from_file_location("v13_leakage", ROOT / "tests" / "test_v13_leakage.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.leaks(bundle)


def test_no_public_task_specifics_in_the_bundle():
    assert (DST / "agent.yaml").is_file()
    assert not _leaks(DST)


def test_validator_passes():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(DST)], capture_output=True, text=True,
                       timeout=180)
    assert r.returncode == 0 and "OK model=gemma-4-31b-it-qat-w4a16-ct" in r.stdout, r.stdout[-500:] + r.stderr[-1500:]
    assert "tools=['run_command', 'read_file', 'get_status', 'submit_patch']" in r.stdout
    assert "'thinking_budget': 1024" in r.stdout and "'temperature': 1.0" in r.stdout
