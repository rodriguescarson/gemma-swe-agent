"""v12b_edit6 = v12b (hidden 0.17, our best) with ONE change: an "edit early" paragraph in the system prompt (first source
edit by the 6th tool call; no reproduction scripts before it; never stop without an edit). Evidence (GAPS 'sub26
pre-registration'): on v12b's 74 local traces, runs whose first edit came by call 6 solved 14 of 17, runs that never edited
solved 0 of 17. Every other file is byte-identical to v12b. Pinned before any v12b_edit6 row exists."""
import filecmp
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "submissions" / "v12b"
NEW = ROOT / "submissions" / "v12b_edit6"
RULE = ("Edit early. Make your first edit to the source by your 6th tool call: after at most three searches and two reads, "
        "edit the most likely place with your best fix, then check it and refine it with further edits. Do not write "
        "reproduction scripts before that first edit; run the issue's example only as the check in step 4. Never stop "
        "without having edited the source.\n\n")
ANCHOR = "Work in this order, one step per tool call:\n"


def files(d):
    return sorted(str(p.relative_to(d)) for p in d.rglob("*") if p.is_file() and "__pycache__" not in p.parts)


def test_only_the_prompt_differs():
    assert files(BASE) == files(NEW)
    assert [f for f in files(BASE) if not filecmp.cmp(BASE / f, NEW / f, shallow=False)] == ["prompts/system.md"]


def test_prompt_is_v12b_plus_the_one_paragraph():
    base = (BASE / "prompts/system.md").read_text()
    assert base.count(ANCHOR) == 1
    assert (NEW / "prompts/system.md").read_text() == base.replace(ANCHOR, RULE + ANCHOR)


def test_still_the_31b():
    assert "model: gemma-4-31b-it-qat-w4a16-ct" in (NEW / "agent.yaml").read_text().splitlines()
