"""v12b_ctx_sed = v12b_ctx with ONE change, how step 2 reads code. vLLM 0.19.1's gemma4 tool parser sometimes writes the
read_file key as `start_line"` (stray quote, a few `end_line"` / `"end_line"` too); the tool then ignores the range, returns
lines 1-150 and reports status ok (17 calls in 7 of the 74 runs of the Kaggle v12 run, eval/analysis/silent_range_drops.py).
v12b_ctx makes ranges mandatory, which raises the exposure. run_command takes one string and is never garbled this way, so
step 2 now reads through `sed -n 'A,Bp'` and tells the model not to pass a range to read_file. read_file stays in the tool
list (the model may still call it without a range). Every other file and every other line of the prompt is byte-identical
to v12b_ctx, including the single {problem_description?} pin. Pinned before any v12b_ctx_sed row exists."""
import filecmp
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "submissions" / "v12b_ctx"
NEW = ROOT / "submissions" / "v12b_ctx_sed"
OLD_STEP = ("2. Read only the function that must change, with the read_file tool and always a start_line and end_line (at "
            "most 80 lines); never read a whole file. One or two reads are enough.")
NEW_STEP = ("2. Read only the function that must change with run_command, as `sed -n '120,175p' path/to/file.py` with the "
            "line numbers from your grep -n hit (at most 80 lines per read; longer output is cut at 5000 characters). Do "
            "not pass a start_line or end_line to read_file: it can drop them and return lines 1-150. One or two reads "
            "are enough.")


def files(d):
    return sorted(str(p.relative_to(d)) for p in d.rglob("*") if p.is_file() and "__pycache__" not in p.parts)


def test_only_the_prompt_differs():
    assert files(BASE) == files(NEW)
    assert [f for f in files(BASE) if not filecmp.cmp(BASE / f, NEW / f, shallow=False)] == ["prompts/system.md"]


def test_prompt_is_v12b_ctx_with_step_2_replaced():
    s = (BASE / "prompts/system.md").read_text()
    assert s.count(OLD_STEP) == 1
    assert (NEW / "prompts/system.md").read_text() == s.replace(OLD_STEP, NEW_STEP)


def test_step_2_reads_through_sed_and_bans_read_file_ranges():
    s = (NEW / "prompts/system.md").read_text()
    step = next(line for line in s.splitlines() if line.startswith("2. "))
    assert step == NEW_STEP
    assert "sed -n '120,175p'" in step and "run_command" in step
    assert "Do not pass a start_line or end_line to read_file" in step
    assert "always a start_line and end_line" not in s          # the v12b_ctx rule that raised the exposure is gone


def test_read_file_is_still_a_tool():
    tools = re.findall(r"^  - (\w+)$", (NEW / "agent.yaml").read_text(), re.M)
    assert tools == ["run_command", "read_file", "edit_file", "write_file", "get_status", "submit_patch"]


def test_the_only_state_placeholder_is_the_optional_issue():
    # ADK injects every {name} in a string instruction and raises "Context variable not found" on a missing required
    # one (a crash row); the optional form becomes '' instead. The new step adds no braces, so the pin stays exactly once.
    s = (NEW / "prompts/system.md").read_text()
    assert re.findall(r"{+[^{}]*}+", s) == ["{problem_description?}"]
    assert s.count("{problem_description?}") == 1


def test_still_the_31b():
    assert "model: gemma-4-31b-it-qat-w4a16-ct" in (NEW / "agent.yaml").read_text().splitlines()
