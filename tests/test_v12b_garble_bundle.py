"""v12b_garble = v12b (hidden 0.17, our best) with ONE change: a rule for tool calls the harness rejects as "mandatory input
parameters are not present". vLLM's gemma4 parser garbles an edit_file/write_file call when the model closes a string
argument with a backtick (forum 747168); the model then resends the identical call, up to 34 times. Evidence (GAPS 'v12b_garble
pre-registration', eval/analysis/parser_rejections.py): 54 of 1,625 local runs looped (3+ rejections), solving 29 against 35.7
for the same tasks' runs that edited without a rejection; run_command was never rejected. Every other file is byte-identical
to v12b. Pinned before any v12b_garble row exists."""
import filecmp
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "submissions" / "v12b"
NEW = ROOT / "submissions" / "v12b_garble"
ANCHOR = "- If a tool reply says the budget is exhausted, call submit_patch at once.\n"
RULE = ("- If a tool reply says mandatory input parameters are not present, the call was garbled on its way to the tool and "
        "resending it fails the same way. Do not resend it: make that change with the run_command tool instead, as one "
        "`python3 - <<'EOF'` script that reads the file, checks the old text occurs exactly once, replaces it and writes the "
        "file back (a new file is written the same way).\n")


def files(d):
    return sorted(str(p.relative_to(d)) for p in d.rglob("*") if p.is_file() and "__pycache__" not in p.parts)


def test_only_the_prompt_differs():
    assert files(BASE) == files(NEW)
    assert [f for f in files(BASE) if not filecmp.cmp(BASE / f, NEW / f, shallow=False)] == ["prompts/system.md"]


def test_prompt_is_v12b_plus_the_one_rule():
    base = (BASE / "prompts/system.md").read_text()
    assert base.count(ANCHOR) == 1
    assert (NEW / "prompts/system.md").read_text() == base.replace(ANCHOR, ANCHOR + RULE)


def test_rule_quotes_the_harness_message():
    # the rule only fires if its words match ADK's rejection text
    assert "mandatory input parameters are not present" in RULE


def test_still_the_31b():
    assert "model: gemma-4-31b-it-qat-w4a16-ct" in (NEW / "agent.yaml").read_text().splitlines()
