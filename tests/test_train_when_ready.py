"""scripts/train_when_ready.sh: launch the Adaption LoRA run exactly once, only when the stitched-rows report says ok
with >= MIN_ROWS rows and the report is newer than the chain start; never on a stale or failing report. Written first."""
import json, os, pathlib, subprocess, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "train_when_ready.sh"


def _run(tmp, report, report_age_s=0, launched_before=False):
    rep = tmp / "report.json"; rep.write_text(json.dumps(report)); os.utime(rep, (time.time() - report_age_s,) * 2)
    fake = tmp / "trainer.sh"; fake.write_text('#!/bin/bash\necho "FAKE_TRAIN $*" >> "$CALLS"\necho "LAUNCHED job-1"\n'); fake.chmod(0o755)
    marker = tmp / "launched"
    if launched_before:
        marker.write_text("x")
    env = dict(os.environ, REPORT=str(rep), TRAINER=str(fake), CALLS=str(tmp / "calls"), MARKER=str(marker), ROWS=str(tmp / "rows.jsonl"),
               SINCE_EPOCH=str(int(time.time()) - 60), READY_POLL_S="0", READY_MAX_POLLS="2", MIN_ROWS="10000")
    r = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60)
    calls = (tmp / "calls").read_text() if (tmp / "calls").exists() else ""
    return r.returncode, calls, r.stdout + r.stderr, marker.exists()


def test_launches_once_on_a_fresh_ok_report(tmp_path):
    rc, calls, out, marker = _run(tmp_path, {"ok": True, "rows": 10400})
    assert rc == 0 and calls.count("FAKE_TRAIN") == 1 and "--launch" in calls and marker


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
