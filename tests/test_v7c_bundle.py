"""v7c = v7b with no read cap (docs/GAPS_2026-10-06.md, "v7c pre-registration"), built in a new directory so v7 and
v7b stay byte-identical. Strict test-first: step 1, v7c starts as an exact copy of v7b."""
import filecmp, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUB = ROOT / "submissions"
V7B, V7C = SUB / "v7b", SUB / "v7c"


def all_files(d):
    """Every file under d, hidden ones included (a byte-identical copy has no extra .DS_Store either)."""
    return {str(p.relative_to(d)) for p in d.rglob("*") if p.is_file()}


def test_v7c_is_a_byte_identical_copy_of_v7b():
    assert V7C.is_dir(), V7C
    assert all_files(V7C) == all_files(V7B), all_files(V7C) ^ all_files(V7B)
    for rel in sorted(all_files(V7B)):
        assert filecmp.cmp(V7B / rel, V7C / rel, shallow=False), rel
        assert os.stat(V7B / rel).st_mode == os.stat(V7C / rel).st_mode, rel
