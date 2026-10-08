"""v7c = v7b with no read cap (docs/GAPS_2026-10-06.md, "v7c pre-registration"), built in a new directory so v7 and
v7b stay byte-identical. Strict test-first: step 1, v7c was an exact copy (cp -a, byte-identical with the same modes:
commit "v7c step 1"); every later step names the files it may change.

  fixes 1+2  no read cap; the outline on every 3rd identical re-read: view.py + _ws.py (tests/test_v7c_helpers.py,
             tests/test_v7c_sandbox.py)"""
import filecmp, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUB = ROOT / "submissions"
V7B, V7C = SUB / "v7b", SUB / "v7c"
FIX12 = {"skills/swe-tools/scripts/view.py", "skills/swe-tools/scripts/_ws.py"}
CHANGED = FIX12


def all_files(d):
    """Every file under d, hidden ones included (a stray .DS_Store or __pycache__ is a difference too)."""
    return {str(p.relative_to(d)) for p in d.rglob("*") if p.is_file()}


def changed(a, b):
    return {rel for rel in all_files(a) & all_files(b) if not filecmp.cmp(a / rel, b / rel, shallow=False)}


def test_v7c_differs_from_v7b_only_in_the_listed_files():
    assert all_files(V7C) == all_files(V7B), all_files(V7C) ^ all_files(V7B)
    assert changed(V7B, V7C) == CHANGED, changed(V7B, V7C) ^ CHANGED
    for rel in sorted(all_files(V7B)):
        assert os.stat(V7B / rel).st_mode == os.stat(V7C / rel).st_mode, rel
