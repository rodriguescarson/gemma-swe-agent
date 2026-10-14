"""v13_repro_timeout = submissions/v13 plus one rule: every command that runs repository code outside a test file (a repro
script, a python3 snippet) starts with `timeout 10`, and exit code 124 is read as "the hang is reproduced", not as a reason to
rerun variations.

Why (measured on the six box runs, docs/forty_two/tasks/rich_3480.md): of 2,208 python repro commands that finished, the
slowest took 2.0 s apart from two that the agent itself had cut at 5 s; 13 hung until the 180 s per-command limit (1,758 s on
rich_3480, rich_4006 and fastapi_14258). v13's per-command limit is 60 s, so each such hang still costs 60 s and the agents
reran hanging repros with small variations (rich_3480 b1024: two hangs in 6 calls). With `timeout 10` a hang costs 10 s.

Lever text constraints (box regression seen on v13, 2026-10-14: a reply put a tool call in plain text): the added rule has no
fenced code block and no tool-call-looking syntax."""
import filecmp, os, re, shutil, subprocess, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE, DST = ROOT / "submissions" / "v13", ROOT / "submissions" / "v13_repro_timeout"
RULE_START = "- Start every command that runs repository code outside a test file"


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
    assert "timeout 10" in add and "124" in add


def test_the_added_rule_has_no_code_fence_tool_syntax_or_template_braces():
    add = added_text()
    assert "```" not in add and "<|" not in add and "|>" not in add
    assert "tool_call" not in add and not re.search(r"\bcall:\w", add)
    assert "{" not in add and "}" not in add          # ADK would template {name} from session state


@pytest.mark.skipif(shutil.which("timeout") is None, reason="needs coreutils timeout (present in the sandbox image)")
def test_timeout_prefix_turns_a_hang_into_exit_124_and_passes_a_heredoc_through(tmp_path):
    hang = subprocess.run(["bash", "-c", "timeout 1 python3 -c 'while True: pass'"], capture_output=True, timeout=30)
    assert hang.returncode == 124
    ok = subprocess.run(["bash", "-c", "timeout 10 python3 - <<'EOF'\nprint(6 * 7)\nEOF"], capture_output=True, text=True,
                        timeout=30)
    assert ok.returncode == 0 and ok.stdout.strip() == "42"


def test_no_public_task_specifics_in_the_bundle():
    sys.path.insert(0, str(ROOT / "tests"))
    from test_v13_leakage import leaks
    assert not leaks(DST)


def test_validator_passes():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(DST)], capture_output=True, text=True,
                       timeout=180)
    assert r.returncode == 0 and "OK model=gemma-4-31b-it-qat-w4a16-ct" in r.stdout, r.stdout[-500:] + r.stderr[-1500:]
    assert "tools=['run_command', 'read_file', 'get_status', 'submit_patch']" in r.stdout
