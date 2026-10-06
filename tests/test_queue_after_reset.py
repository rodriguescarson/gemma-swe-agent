"""scripts/queue_after_reset.sh: a failed push must not hand the slug to l4_result_summary (which then waits forever
for a run that never started; 2026-10-06 the queue sat 9 h on v5h2 this way). Log it and move to the next slug."""
import os, pathlib, subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "queue_after_reset.sh"


def test_failed_push_skips_summary_and_continues(tmp_path):
    calls = tmp_path / "calls"
    push = tmp_path / "push.sh"; push.write_text(f'#!/bin/bash\necho "push $1" >> {calls}\n[ "$1" = a ] && exit 1\nexit 0\n')
    summ = tmp_path / "summ.sh"; summ.write_text(f'#!/bin/bash\necho "summary $1" >> {calls}\n')
    for f in (push, summ): f.chmod(0o755)
    logdir = tmp_path / "ov"; logdir.mkdir()
    env = dict(os.environ, PUSH_RETRY_SH=str(push), SUMMARY_SH=str(summ), QUEUE_LOG_DIR=str(logdir))
    r = subprocess.run(["bash", str(SCRIPT), "a", "b"], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert calls.read_text().splitlines() == ["push a", "push b", "summary b"]
    assert "PUSH_FAILED a" in (logdir / "progress.log").read_text()
