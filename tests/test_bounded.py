"""scripts/forty_two/bounded.py: run a command with a memory and a wall-time ceiling over its whole process group (2026-10-14:
rich_3480's pytest grew to 4.3 GB RSS on the 16 GB Mac and pushed swap to its limit). Written before the script."""
import subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
B = [sys.executable, str(ROOT / "scripts" / "forty_two" / "bounded.py")]


def run(*args, timeout=60):
    return subprocess.run([*B, *args], capture_output=True, text=True, timeout=timeout)


def test_passes_output_and_exit_code_through():
    r = run("--mb", "500", "--secs", "30", "--", sys.executable, "-c", "print('hello'); raise SystemExit(3)")
    assert r.returncode == 3 and "hello" in r.stdout and "bounded:" not in r.stderr


def test_kills_a_memory_hog_in_a_grandchild_quickly():
    hog = f"{sys.executable} -c \"a = b'x' * (900 * 1024 * 1024); import time; time.sleep(60)\""
    t0 = time.time()
    r = run("--mb", "300", "--secs", "60", "--", "bash", "-c", hog)
    assert r.returncode == 137 and "bounded: killed" in r.stderr and "MB >" in r.stderr and time.time() - t0 < 20


def test_wall_time_limit_returns_124():
    r = run("--mb", "500", "--secs", "1", "--", "sleep", "30")
    assert r.returncode == 124 and "bounded: timed out" in r.stderr
