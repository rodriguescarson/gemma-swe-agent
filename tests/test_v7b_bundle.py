"""v7b = v7 + the two fixes pre-registered in docs/GAPS_2026-10-06.md (last section, "v7 A6000 screen read"), built in a
new directory so the v7 run on the GPU box is never touched. Strict test-first: step 1, v7b starts as an exact copy."""
import filecmp, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUB = ROOT / "submissions"
V7, V7B = SUB / "v7", SUB / "v7b"


def all_files(d):
    """Every file under d, hidden ones included (a byte-identical copy has no extra .DS_Store either)."""
    return {str(p.relative_to(d)) for p in d.rglob("*") if p.is_file()}


def test_v7b_is_a_byte_identical_copy_of_v7():
    assert V7B.is_dir(), V7B
    assert all_files(V7B) == all_files(V7), all_files(V7B) ^ all_files(V7)
    for rel in sorted(all_files(V7)):
        assert filecmp.cmp(V7 / rel, V7B / rel, shallow=False), rel
        assert os.stat(V7 / rel).st_mode == os.stat(V7B / rel).st_mode, rel
