"""v13 = v12-b1024 (our current line: one thinking-on agent, budget 1,024) plus the general levers of docs/forty_two/LEVERS.md,
each added as its own commit after a failing test. Evidence for every lever: docs/forty_two/TIMING.md (Phase A).

Commit 1 (this file's first version): v13 is a byte-identical copy of v12-b1024, so every later difference is a lever."""
import filecmp, os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC, DST = ROOT / "submissions" / "v12-b1024", ROOT / "submissions" / "v13"


def all_files(d):
    return {str(p.relative_to(d)) for p in Path(d).rglob("*") if p.is_file()}


def test_v13_starts_as_a_byte_identical_copy_of_v12_b1024():
    assert all_files(DST) == all_files(SRC)
    for rel in sorted(all_files(SRC)):
        assert filecmp.cmp(SRC / rel, DST / rel, shallow=False), rel
        assert os.stat(SRC / rel).st_mode == os.stat(DST / rel).st_mode, rel


def test_validator_passes():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(DST)], capture_output=True, text=True, timeout=180)
    assert r.returncode == 0 and "OK model=gemma-4-31b-it-qat-w4a16-ct" in r.stdout, r.stdout[-500:] + r.stderr[-1500:]
