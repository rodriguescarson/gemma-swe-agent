"""v13_title_repro = submissions/v13 plus ONE change: a sentence at the end of step 1 (Locate) of prompts/system.md.

Lever (docs/forty_two/tasks/rich_3472.md): when an issue is only a short title plus a link the sandbox cannot open, locate by
running a few lines as a user would and reading the traceback or the wrong output, instead of grepping the title's words.
On rich_3472 ("fix for missing field in dataclass") p4_b1024 and p4_v0t2 spent all 40 / 38 calls grepping the repository's own
`@dataclass` definitions and never opened the module that renders user objects; a 6-line user program on the base commit names
that module in its traceback (measured offline, the write-up). The rule names no task, file, function or test.

Constraints pinned here:
- every file other than prompts/system.md is byte-identical to submissions/v13 (same modes);
- prompts/system.md is v13's with exactly one inserted sentence, placed at the end of step 1;
- the inserted text has no fenced block, no backtick, no brace and nothing shaped like a tool call (the coordinator's 2026-10-14
  warning: on the v13 screen one task's first reply put a tool call in the message text, suspected to follow the fenced heredoc);
- no public-task specifics (the deny list of tests/test_v13_leakage.py) and scripts/validate.py passes."""
import filecmp, importlib.util, os, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE, DST = ROOT / "submissions" / "v13", ROOT / "submissions" / "v13_title_repro"
STEP1_END = "Do not read files that are not in the hits."
ADDED = (" If the issue gives no identifier, error text or example (only a short title and a link you cannot open), the title"
         " says what the library does wrong with some input: first run a few lines of Python as a user would (build that input"
         " and pass it to the library's usual public call), then take the candidate file from the traceback or from the code"
         " that produced the wrong result.")


def all_files(d):
    return {str(p.relative_to(d)) for p in Path(d).rglob("*") if p.is_file()}


def test_only_the_prompt_differs_from_v13():
    assert all_files(DST) == all_files(BASE)
    for rel in sorted(all_files(BASE)):
        assert filecmp.cmp(BASE / rel, DST / rel, shallow=False) == (rel != "prompts/system.md"), rel
        assert os.stat(BASE / rel).st_mode == os.stat(DST / rel).st_mode, rel


def test_the_prompt_is_v13_plus_one_sentence_at_the_end_of_step_1():
    old, new = (BASE / "prompts" / "system.md").read_text(), (DST / "prompts" / "system.md").read_text()
    assert old.count(STEP1_END) == 1
    assert new == old.replace(STEP1_END, STEP1_END + ADDED)
    step1 = new.split("1. Locate.")[1].split("\n2. Read")[0]
    assert step1.endswith(ADDED)


def test_the_added_text_has_no_code_block_or_tool_call_shape():
    for bad in ("```", "`", "{", "}", "<|", "|>", "call:", "tool_call", "<<", "run_command", "read_file", "submit_patch"):
        assert bad not in ADDED, bad
    assert ADDED.count(".") == 1 and ADDED.endswith(".")                      # one sentence


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
