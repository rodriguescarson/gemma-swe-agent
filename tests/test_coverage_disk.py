"""E7 (docs/PLAN_TO_FINISH.txt): a collection pass must not start under MIN_FREE_GB. Written before the fix.
scripts/collect/disk_guard.sh prints the free GB and exits 0 when >= MIN_FREE_GB, 3 otherwise; a fake df drives it."""
import os, pathlib, subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
GUARD = ROOT / "scripts" / "collect" / "disk_guard.sh"


def _run(tmp, free_gb, min_free="6"):
    fake = tmp / "df"
    fake.write_text(f'#!/bin/bash\necho "Filesystem Size Used Avail Capacity"\necho "/dev/disk3s5 460 420 {free_gb} 95%"\n'); fake.chmod(0o755)
    env = dict(os.environ, PATH=f"{tmp}:{os.environ['PATH']}", MIN_FREE_GB=min_free)
    r = subprocess.run(["bash", str(GUARD)], env=env, capture_output=True, text=True, timeout=30)
    return r.returncode, r.stdout + r.stderr


def test_guard_blocks_under_min_free(tmp_path):
    rc, out = _run(tmp_path, 4)
    assert rc == 3 and "4GB" in out and "below" in out


def test_guard_allows_at_or_above_min_free(tmp_path):
    rc, out = _run(tmp_path, 6)
    assert rc == 0 and "6GB" in out


def test_collect_sh_calls_the_guard_before_each_pass():
    src = (ROOT / "scripts" / "collect" / "collect.sh").read_text()
    assert "disk_guard.sh" in src
