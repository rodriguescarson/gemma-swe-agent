"""v7b = v7 + the two fixes pre-registered in docs/GAPS_2026-10-06.md (last section, "v7 A6000 screen read"), built in a
new directory so the v7 run on the GPU box is never touched. Strict test-first: step 1, v7b was an exact copy (cp -a,
byte-identical with the same modes, commit 4de4cec); every later step names the files it may change.

  fix 1  the read-cap refusal stops being a loop trap: view.py + _ws.py (tests/test_v7b_helpers.py, _sandbox, _counters)
  fix 2  submit_patch is a tool, commands never start with run_command: one new line in fixer.md and verifier.md
         (tests/test_v7b_prompts.py)"""
import filecmp, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUB = ROOT / "submissions"
V7, V7B = SUB / "v7", SUB / "v7b"
FIX1 = {"skills/swe-tools/scripts/view.py", "skills/swe-tools/scripts/_ws.py"}
FIX2 = {"prompts/fixer.md", "prompts/verifier.md"}
CHANGED = FIX1 | FIX2


def all_files(d):
    """Every file under d, hidden ones included (a stray .DS_Store or __pycache__ is a difference too)."""
    return {str(p.relative_to(d)) for p in d.rglob("*") if p.is_file()}


def changed(a, b):
    return {rel for rel in all_files(a) & all_files(b) if not filecmp.cmp(a / rel, b / rel, shallow=False)}


def test_v7b_differs_from_v7_only_in_the_listed_files():
    assert all_files(V7B) == all_files(V7), all_files(V7B) ^ all_files(V7)
    assert changed(V7, V7B) == CHANGED, changed(V7, V7B) ^ CHANGED
    for rel in sorted(all_files(V7)):
        assert os.stat(V7 / rel).st_mode == os.stat(V7B / rel).st_mode, rel
