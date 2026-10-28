"""v12b_ctx = v12b (hidden 0.17, our best) with ONE change, its context rules. The scorer compacts in-flow at 14,336 prompt
tokens; ADK's summarizer keeps only text parts, so the summary drops every tool output and the task message itself
(eval/analysis/compaction_l4.py: 39-42 of 74 L4 runs compacted, about 21 s per summary, 140-153 re-reads of files read
before it). The rule set: ranged reads of at most 80 lines (reads without a range were 24% of reads and 36% of read
tokens), trimmed search and test output, the edit plan written into the reasoning the summary keeps, and the issue pinned
in the system instruction through ADK state injection ({problem_description?}, set by swegemma's runner), which no
compaction removes. Every other file is byte-identical to v12b. Pinned before any v12b_ctx row exists."""
import filecmp
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "submissions" / "v12b"
NEW = ROOT / "submissions" / "v12b_ctx"
EDITS = [
    ("2. Read only the function that must change, with the read_file tool and a line range (at most 150 lines). One or "
     "two reads are enough.",
     "2. Read only the function that must change, with the read_file tool and always a start_line and end_line (at most "
     "80 lines); never read a whole file. One or two reads are enough."),
    ("for example `python3 -m pytest tests/test_x.py -x -q -k name` with a 60-second timeout in the command, or",
     "for example `timeout 60 python3 -m pytest tests/test_x.py -x -q --tb=short -k name 2>&1 | tail -n 40`, or"),
    ("- If a tool reply says the budget is exhausted, call submit_patch at once.\n",
     "- If a tool reply says the budget is exhausted, call submit_patch at once.\n"
     "- Keep every tool output short. A long conversation is replaced by a summary that keeps your reasoning but drops "
     "every file and command output you have seen, so end searches with `| head -n 20` and test runs with "
     "`| tail -n 40`, and before your first edit write in your reasoning the file, the line numbers and the exact lines "
     "you will change.\n"),
]
PIN = "\nThe issue, repeated here so that it stays in view after a summary:\n{problem_description?}\n"


def files(d):
    return sorted(str(p.relative_to(d)) for p in d.rglob("*") if p.is_file() and "__pycache__" not in p.parts)


def test_only_the_prompt_differs():
    assert files(BASE) == files(NEW)
    assert [f for f in files(BASE) if not filecmp.cmp(BASE / f, NEW / f, shallow=False)] == ["prompts/system.md"]


def test_prompt_is_v12b_plus_the_context_rules():
    s = (BASE / "prompts/system.md").read_text()
    for old, new in EDITS:
        assert s.count(old) == 1, old
        s = s.replace(old, new)
    assert (NEW / "prompts/system.md").read_text() == s + PIN


def test_the_only_state_placeholder_is_the_optional_issue():
    # ADK injects every {name} in a string instruction and raises "Context variable not found" on a missing required
    # one (a crash row); the optional form becomes '' instead
    s = (NEW / "prompts/system.md").read_text()
    assert re.findall(r"{+[^{}]*}+", s) == ["{problem_description?}"]


def test_the_runner_still_sets_the_state_key():
    import inspect
    from swegemma.harness import agent_runner
    assert "'problem_description': task.problem_statement" in inspect.getsource(agent_runner)


def test_still_the_31b():
    assert "model: gemma-4-31b-it-qat-w4a16-ct" in (NEW / "agent.yaml").read_text().splitlines()
