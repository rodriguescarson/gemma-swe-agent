"""E6 (docs/PLAN_TO_FINISH.txt): the overnight Kaggle gate. Written before the fix.
The sequence may start GPU kernels only when (a) the day's submission marker exists and (b) no submission is PENDING,
checked against the kaggle listing, with a fake clock/fake kaggle; the gate must never pass on a stale marker from an
earlier day, and the 'PENDING' check must read the newest row only."""
import os, pathlib, subprocess, sys, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
LIB = ROOT / "scripts" / "overnight_gate.sh"
sys.path.insert(0, str(ROOT / "tests"))
from gnu_stat import gnu_stat_path  # noqa: E402


def _run(tmp, marker_age_s, listing, now_epoch=None, path=None):
    fake = tmp / "kaggle"
    fake.write_text('#!/bin/bash\ncat "$FAKE_LISTING"\n'); fake.chmod(0o755)
    (tmp / "listing.csv").write_text(listing)
    marker = tmp / "sub_submitted"
    if marker_age_s is not None:
        marker.write_text("x"); os.utime(marker, (time.time() - marker_age_s, time.time() - marker_age_s))
    env = dict(os.environ, KAGGLE_BIN=str(fake), FAKE_LISTING=str(tmp / "listing.csv"), MARKER=str(marker), GATE_POLL_S="0", GATE_MAX_POLLS="3")
    if now_epoch is not None:
        env["FAKE_NOW_EPOCH"] = str(now_epoch)
    if path is not None:
        env["PATH"] = path
    r = subprocess.run(["bash", str(LIB)], env=env, capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout + r.stderr


PENDING = "fileName,date,description,status,publicScore,privateScore\nsubmission.zip,2026-10-03 03:06:11,sub9,SubmissionStatus.PENDING,,\nsubmission.zip,2026-10-02 04:11:39,sub8,SubmissionStatus.COMPLETE,0.08,\n"
DONE = PENDING.replace("SubmissionStatus.PENDING,,", "SubmissionStatus.COMPLETE,0.12,")


def test_gate_waits_while_the_newest_submission_is_pending(tmp_path):
    rc, out = _run(tmp_path, 60, PENDING)
    assert rc != 0 and "PENDING" in out


def test_gate_passes_when_marker_is_fresh_and_nothing_pending(tmp_path):
    rc, out = _run(tmp_path, 60, DONE)
    assert rc == 0 and "GATE OPEN" in out


def test_gate_rejects_a_marker_older_than_the_current_utc_day(tmp_path):
    # the marker was written for yesterday's submission; today's has not happened: the gate must not open
    rc, out = _run(tmp_path, 36 * 3600, DONE)
    assert rc != 0 and "stale" in out


def test_gate_waits_when_marker_missing(tmp_path):
    rc, out = _run(tmp_path, None, DONE)
    assert rc != 0 and "no marker" in out


def test_marker_age_is_read_the_same_under_gnu_stat(tmp_path):
    """Linux (the A6000 box, 2026-10-07): `stat -f %m` is GNU's --file-system, mtime() returned the file system's status
    plus the mtime, the age comparison errored and the gate opened on yesterday's marker (assert (0 != 0))."""
    gnu = gnu_stat_path(tmp_path)
    rc, out = _run(tmp_path, 36 * 3600, DONE, path=gnu)
    assert rc != 0 and "stale" in out, out
    rc, out = _run(tmp_path, 60, DONE, path=gnu)                           # control: a fresh marker still opens it
    assert rc == 0 and "GATE OPEN" in out, out
