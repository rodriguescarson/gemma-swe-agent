"""scripts/train_when_ready.sh: launch the Adaption LoRA run exactly once, only when the stitched-rows report says ok
with >= MIN_ROWS rows and the report is newer than the chain start; never on a stale or failing report. Written first."""
import json, os, pathlib, subprocess, sys, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "train_when_ready.sh"
sys.path.insert(0, str(ROOT / "tests"))
from gnu_stat import gnu_stat_path  # noqa: E402


def _run(tmp, report, report_age_s=0, launched_before=False, path=None):
    rep = tmp / "report.json"; rep.write_text(json.dumps(report)); os.utime(rep, (time.time() - report_age_s,) * 2)
    fake = tmp / "trainer.sh"
    # the real trainer prints a multi-line JSON after LAUNCHED; the id is NOT on the LAUNCHED line (2026-10-03: the
    # marker kept only that line and the run id had to be recovered from the API)
    fake.write_text('#!/bin/bash\necho "FAKE_TRAIN $*" >> "$CALLS"\necho "dataset abc processed"\necho "LAUNCHED {"\necho \' "id": "job-1",\'\necho \' "status": "running"\'\necho "}"\n'); fake.chmod(0o755)
    marker = tmp / "launched"
    if launched_before:
        marker.write_text("x")
    env = dict(os.environ, REPORT=str(rep), TRAINER=str(fake), CALLS=str(tmp / "calls"), MARKER=str(marker), ROWS=str(tmp / "rows.jsonl"),
               SINCE_EPOCH=str(int(time.time()) - 60), READY_POLL_S="0", READY_MAX_POLLS="2", MIN_ROWS="10000",
               SEQ_LOG=str(tmp / "seq.log"), LAUNCH_OUT=str(tmp / "launch.out"))   # never the repo's progress log (a test run polluted it on 10-03)
    if path is not None:
        env["PATH"] = path
    r = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60)
    calls = (tmp / "calls").read_text() if (tmp / "calls").exists() else ""
    return r.returncode, calls, r.stdout + r.stderr, marker.exists()


def test_launches_once_on_a_fresh_ok_report(tmp_path):
    real_log = ROOT / "eval" / "overnight" / "progress.log"
    before = real_log.read_text() if real_log.exists() else None
    rc, calls, out, marker = _run(tmp_path, {"ok": True, "rows": 10400})
    assert rc == 0 and calls.count("FAKE_TRAIN") == 1 and "--launch" in calls and marker
    assert (tmp_path / "seq.log").exists() and "LAUNCHED" in (tmp_path / "seq.log").read_text()
    assert "job-1" in (tmp_path / "launched").read_text()          # the marker carries the whole reply, id included
    assert (tmp_path / "launch.out").exists() and "dataset abc processed" in (tmp_path / "launch.out").read_text()
    assert (real_log.read_text() if real_log.exists() else None) == before   # the test never touches the real log


def test_does_not_launch_on_failing_or_small_report(tmp_path):
    rc, calls, out, marker = _run(tmp_path, {"ok": False, "rows": 2402})
    assert rc != 0 and calls == "" and not marker and "not ready" in out
    rc, calls, out, marker = _run(tmp_path, {"ok": True, "rows": 9000})
    assert rc != 0 and calls == "" and not marker and "not ready" in out


def test_stale_report_and_prior_launch_are_ignored(tmp_path):
    rc, calls, out, marker = _run(tmp_path, {"ok": True, "rows": 12000}, report_age_s=3600)
    assert rc != 0 and calls == "" and "stale" in out
    rc, calls, out, marker = _run(tmp_path / "b" if (tmp_path / "b").mkdir() is None else tmp_path, {"ok": True, "rows": 12000}, launched_before=True)
    assert rc == 0 and calls == "" and "already launched" in out


def test_report_age_is_read_the_same_under_gnu_stat(tmp_path):
    """Linux (the A6000 box, 2026-10-07): `stat -f %m` is GNU's --file-system, mtime() returned the file system's status
    plus the mtime, the age comparison errored and a stale report launched the run (assert (0 != 0))."""
    gnu = gnu_stat_path(tmp_path)
    rc, calls, out, marker = _run(tmp_path, {"ok": True, "rows": 12000}, report_age_s=3600, path=gnu)
    assert rc != 0 and calls == "" and "stale" in out, out
    rc, calls, out, marker = _run(tmp_path, {"ok": True, "rows": 12000}, path=gnu)    # control: a fresh report launches
    assert rc == 0 and calls.count("FAKE_TRAIN") == 1 and marker, out
