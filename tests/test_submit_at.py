"""submit_at.sh must never double-submit when two machines are armed, must exit 0 only when its tag is on Kaggle, and its
GPU-overlap guard must work from the day the slot falls in. Chain exit statuses (eval/arm_sub2*.sh) are tested here too."""
import json, os, re, shutil, signal, subprocess, sys, datetime, pathlib, time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "submit_at.sh"
UTC = datetime.timezone.utc
NOON = int(datetime.datetime(2026, 10, 29, 12, 0, tzinfo=UTC).timestamp())          # a fixed clock: no test below depends on the wall clock
LATE = int(datetime.datetime(2026, 10, 29, 23, 55, tzinfo=UTC).timestamp())         # inside the guard's last ten minutes of the UTC day


def _fake_clock(tmp, now_epoch, sleeps=True):
    """A bin dir for the front of PATH: `date -u +%s` reports now_epoch (every other form of date is the real one), so the
    scripts' day arithmetic is the same at any hour (the guard tests failed from 23:50 to 00:00 UTC while they used the wall
    clock). sleeps=False also makes `sleep` return at once, for the retry loops (6 x 60 s, 2 x 120 s, 2 x 30 s); sleeps=<a path>
    does that and appends each call's arguments to the file, so a test can pin how long the script waits."""
    b = tmp / "fakebin"; b.mkdir(exist_ok=True)
    (b / "date").write_text(f'#!/bin/bash\n[ "$1 $2" = "-u +%s" ] && {{ echo {now_epoch}; exit 0; }}\nexec /bin/date "$@"\n')
    (b / "date").chmod(0o755)
    if sleeps is not True:
        record = f'echo "$@" >> {sleeps}\n' if sleeps else ""
        (b / "sleep").write_text(f"#!/bin/bash\n{record}exit 0\n"); (b / "sleep").chmod(0o755)
    return {"PATH": f"{b}:{os.environ['PATH']}"}


def _run_for(args, env, seconds):
    """Run a script that is expected to still be waiting after `seconds`; True if it finished by itself. A script still running is
    killed with its whole process group: killing only bash (p.kill()) left its `sleep 600` / `sleep 20` / `sleep 120` behind."""
    p = subprocess.Popen(args, env=env, start_new_session=True)
    try:
        p.wait(timeout=seconds); return True
    except subprocess.TimeoutExpired:
        return False
    finally:
        if p.poll() is None:
            os.killpg(p.pid, signal.SIGKILL); p.wait()


def test_run_for_leaves_no_orphaned_sleep_behind(tmp_path):
    # the three tests that stop a waiting script with it used p.kill(): bash died, its `sleep 600` was re-parented to pid 1 and ran on
    script = tmp_path / "waits.sh"; script.write_text("#!/bin/bash\nsleep 987\n")
    assert _run_for(["bash", str(script)], dict(os.environ), 1) is False
    assert subprocess.run(["pgrep", "-f", "^sleep 987$"], capture_output=True).returncode == 1


# One fake Kaggle CLI. `submit` registers its -m text as a PENDING row of the listing (like Kaggle), unless submit="fail";
# submit="ghost" registers it but prints an error (a 400 whose submission landed anyway); lag = how many listings after a
# submit still hide the new row; gpu = the status of our g4-l4-v10 kernel (None: no GPU kernels exist); listing_fails.
_FAKE = r"""#!/bin/bash
echo "$@" >> @CALLS@
if [ "$1" = kernels ] && [ "$2" = list ]; then
  [ -s @GPU@ ] && printf 'ref title\n---- ----\ncarsonrodrigues/g4-l4-v10 x\ncarsonrodrigues/g4agent-v10 y\n'
  exit 0
fi
if [ "$1" = kernels ] && [ "$2" = status ]; then echo "has status \"KernelWorkerStatus.$(cat @GPU@)\""; exit 0; fi
if [ "$2" = submissions ]; then
  [ -e @LISTFAIL@ ] && { echo ConnectionError >&2; exit 1; }
  echo 'ref,fileName,date,description,status'
  cat @ROWS@
  n=$(cat @LAG@); if [ "$n" -gt 0 ]; then echo $((n - 1)) > @LAG@
  else while IFS= read -r m; do echo "9,submission.zip,d,\"$m\",SubmissionStatus.PENDING"; done < @SUBS@; fi
  exit 0
fi
if [ "$2" = submit ]; then
  if [ @REGISTER@ = 1 ]; then echo @LAGN@ > @LAG@; while [ $# -gt 0 ]; do [ "$1" = -m ] && echo "$2" >> @SUBS@; shift; done; fi
  echo "@OUT@"; exit @RC@
fi
echo "Successfully submitted"
"""


def _fake_kaggle(tmp, existing, submit="ok", lag=0, gpu=None, listing_fails=False):
    calls = tmp / "calls.txt"; fake = tmp / "kaggle"
    for name, text in (("rows", "".join(f"1,submission.zip,d,\"{d}\",COMPLETE\n" for d in existing)), ("subs", ""), ("lag", "0\n"),
                       ("gpu", "" if gpu is None else gpu)):
        (tmp / name).write_text(text)
    if listing_fails:
        (tmp / "listfail").write_text("")
    ok = submit == "ok"
    body = (_FAKE.replace("@CALLS@", str(calls)).replace("@GPU@", str(tmp / "gpu")).replace("@LISTFAIL@", str(tmp / "listfail"))
            .replace("@ROWS@", str(tmp / "rows")).replace("@LAG@", str(tmp / "lag")).replace("@SUBS@", str(tmp / "subs"))
            .replace("@REGISTER@", "0" if submit == "fail" else "1").replace("@LAGN@", str(lag))
            .replace("@OUT@", "Successfully submitted" if ok else "Bad Request").replace("@RC@", "0" if ok else "1"))
    fake.write_text(body); fake.chmod(0o755)
    return fake, calls


def _submits(calls):
    return [l for l in calls.read_text().splitlines() if l.startswith("competitions submit ")]


def _run(tmp, existing, msg):
    fake, calls = _fake_kaggle(tmp, existing)
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%H%M")
    env = dict(os.environ, KAGGLE_BIN=str(fake), SUBMIT_LOG=str(tmp / "log.txt"), SUBMIT_TARGET_EPOCH="0", SKIP_GPU_GUARD="1")
    subprocess.run(["bash", str(SCRIPT), "k", now, msg], env=env, check=True, timeout=60)
    return [l for l in calls.read_text().splitlines() if l.startswith("competitions submit ")]


def test_skips_when_tag_already_on_kaggle(tmp_path):
    assert _run(tmp_path, ["sub3: v4 staged"], "sub3: v4 staged") == []


def test_submits_once_when_absent(tmp_path):
    assert len(_run(tmp_path, ["sub2: older"], "sub3: v4 staged")) == 1


def test_afternoon_arming_does_not_fire_early(tmp_path):
    # regression 2026-09-27: arming at 16:12 UTC for "0001" fired immediately
    fake, calls = _fake_kaggle(tmp_path, [])
    past = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)).strftime("%H%M")
    env = dict(os.environ, KAGGLE_BIN=str(fake), SUBMIT_LOG=str(tmp_path / "log.txt"))
    env.pop("SUBMIT_TARGET_EPOCH", None)
    fired = _run_for(["bash", str(SCRIPT), "k", past, "sub9: x"], env, 4)
    assert not fired and not calls.exists()
    log = (tmp_path / "log.txt").read_text()
    target = int(log.split("target epoch ")[1].split()[0])
    assert target - datetime.datetime.now(datetime.timezone.utc).timestamp() > 22 * 3600   # next day, ~23 h away


def test_listing_failure_never_submits_blind(tmp_path):
    # 2026-09-28: network outage made the listing fail and the backup submitted blind
    calls = tmp_path / "calls.txt"; fake = tmp_path / "kaggle"
    fake.write_text(f"""#!/bin/bash
echo "$@" >> {calls}
if [ "$2" = submissions ]; then echo "ConnectionError" >&2; exit 1; fi
echo "Successfully submitted"
""")
    fake.chmod(0o755)
    env = dict(os.environ, KAGGLE_BIN=str(fake), SUBMIT_LOG=str(tmp_path / "log.txt"), SUBMIT_TARGET_EPOCH="0", SKIP_GPU_GUARD="1")
    _run_for(["bash", str(SCRIPT), "k", "0000", "sub9: x"], env, 5)
    assert not any(l.startswith("competitions submit ") for l in calls.read_text().splitlines())
    assert "not submitting blind" in (tmp_path / "log.txt").read_text()


def test_waits_while_own_gpu_kernel_is_running(tmp_path):
    # regression 2026-09-29: queued GPU eval kernels overlapped sub5's scoring
    calls = tmp_path / "calls.txt"; state = tmp_path / "state"; state.write_text("RUNNING")
    fake = tmp_path / "kaggle"
    fake.write_text(f"""#!/bin/bash
echo "$@" >> {calls}
if [ "$1" = kernels ] && [ "$2" = list ]; then printf 'ref title\\n---- ----\\ncarsonrodrigues/g4-l4-v10 x\\ncarsonrodrigues/g4agent-v10 y\\n'; exit 0; fi
if [ "$1" = kernels ] && [ "$2" = status ]; then echo "has status \\"KernelWorkerStatus.$(cat {state})\\""; exit 0; fi
if [ "$2" = submissions ]; then echo 'ref,fileName,date,description,status'; exit 0; fi
echo "Successfully submitted"
""")
    fake.chmod(0o755)
    # the clock is fixed at noon UTC: with the wall clock this test fell over from 23:50 to 00:00 UTC, when "now" is already past
    # the guard's day end and it submits anyway
    env = dict(os.environ, KAGGLE_BIN=str(fake), SUBMIT_LOG=str(tmp_path / "log.txt"), SUBMIT_TARGET_EPOCH=str(NOON), **_fake_clock(tmp_path, NOON))
    _run_for(["bash", str(SCRIPT), "k", "0000", "sub9: x"], env, 4)
    log = (tmp_path / "log.txt").read_text()
    assert "own GPU kernels busy: carsonrodrigues/g4-l4-v10" in log
    assert not any(l.startswith("competitions submit ") for l in calls.read_text().splitlines())
    assert "g4agent-v10" not in log.split("busy:")[1]          # CPU submission notebooks are not GPU kernels


def test_kernel_version_is_passed_through(tmp_path):
    # regression 2026-09-29: the version was hard-coded to 1, which for g4agent-v10 is the stale v10.0 zip
    fake, calls = _fake_kaggle(tmp_path, [])
    env = dict(os.environ, KAGGLE_BIN=str(fake), SUBMIT_LOG=str(tmp_path / "log.txt"), SUBMIT_TARGET_EPOCH="0",
               SKIP_GPU_GUARD="1", KERNEL_VERSION="2")
    subprocess.run(["bash", str(SCRIPT), "g4agent-v10", "0000", "sub6: v10.1"], env=env, check=True, timeout=60)
    sub = [l for l in calls.read_text().splitlines() if l.startswith("competitions submit ")]
    assert sub and "-v 2 " in sub[0] + " " and "carsonrodrigues/g4agent-v10" in sub[0]
    assert "armed g4agent-v10 v2" in (tmp_path / "log.txt").read_text()


def test_missing_kaggle_binary_aborts_at_arm_time(tmp_path):
    # 2026-10-02: sub8 was lost because the detached VPS shell had no `kaggle` on PATH; the job must refuse to arm
    env = dict(os.environ, KAGGLE_BIN=str(tmp_path / "nope"), SUBMIT_LOG=str(tmp_path / "log.txt"), SUBMIT_TARGET_EPOCH="0")
    p = subprocess.run(["bash", str(SCRIPT), "k", "0001", "sub9: x"], env=env, capture_output=True, text=True, timeout=30)
    assert p.returncode == 2 and "kaggle binary not found" in p.stderr
    log = (tmp_path / "log.txt").read_text()
    assert "ABORT: kaggle binary not found" in log and "] armed " not in log and "target epoch" not in log


def test_venv_kaggle_next_to_the_script_is_found(tmp_path):
    # the VPS layout: g4submit/submit_at.sh + g4submit/venv/bin/kaggle, PATH without it
    d = tmp_path / "g4submit"; (d / "venv" / "bin").mkdir(parents=True)
    script = d / "submit_at.sh"; script.write_text(SCRIPT.read_text()); script.chmod(0o755)
    fake, calls = _fake_kaggle(d / "venv" / "bin", ["sub2: older"])
    env = dict(os.environ, SUBMIT_LOG=str(tmp_path / "log.txt"), SUBMIT_TARGET_EPOCH="0", SKIP_GPU_GUARD="1", PATH="/usr/bin:/bin")
    env.pop("KAGGLE_BIN", None)
    subprocess.run(["bash", str(script), "k", "0001", "sub3: v4 staged"], env=env, check=True, timeout=60)
    assert len([l for l in calls.read_text().splitlines() if l.startswith("competitions submit ")]) == 1


def _fake_kaggle_17(tmp, existing):
    """kaggle 1.7.4.5 (the Mac's ~/Library/Python/3.9 CLI) prints the -v listing WITHOUT a ref column:
    'fileName,date,description,status,publicScore,privateScore'. 2026-10-05: submit_at's header check required '^ref,'
    and read every 1.7 listing as a failure, so sub11 refused to submit for 26 minutes."""
    calls = tmp / "calls.txt"; fake = tmp / "kaggle"
    fake.write_text(f"""#!/bin/bash
echo "$@" >> {calls}
if [ "$2" = submissions ]; then
  echo 'fileName,date,description,status,publicScore,privateScore'
  {"".join(f'echo \'submission.zip,d,"{d}",COMPLETE,0.1,\';' for d in existing)}
  while IFS= read -r m; do echo "submission.zip,d,\\"$m\\",SubmissionStatus.PENDING,,"; done < {tmp / "subs"}
  exit 0
fi
if [ "$2" = submit ]; then while [ $# -gt 0 ]; do [ "$1" = -m ] && echo "$2" >> {tmp / "subs"}; shift; done; fi
echo "Successfully submitted"
""")
    (tmp / "subs").write_text("")
    fake.chmod(0o755)
    return fake, calls


def _run17(tmp, existing, msg):
    fake, calls = _fake_kaggle_17(tmp, existing)
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%H%M")
    env = dict(os.environ, KAGGLE_BIN=str(fake), SUBMIT_LOG=str(tmp / "log.txt"), SUBMIT_TARGET_EPOCH="0", SKIP_GPU_GUARD="1")
    subprocess.run(["bash", str(SCRIPT), "k", now, msg], env=env, check=True, timeout=60)
    return [l for l in calls.read_text().splitlines() if l.startswith("competitions submit ")]


def test_kaggle_17_listing_without_ref_column_submits_once(tmp_path):
    assert len(_run17(tmp_path, ["sub10: older"], "sub11: v4h2g")) == 1


def test_kaggle_17_listing_still_detects_the_tag(tmp_path):
    assert _run17(tmp_path, ["sub11: v4h2g"], "sub11: v4h2g") == []


def _fake_kaggle_pending(tmp, flips_after):
    """The listing shows sub15b as SubmissionStatus.PENDING for the first `flips_after` listings, then COMPLETE."""
    calls = tmp / "calls.txt"; n = tmp / "n"; n.write_text("0"); fake = tmp / "kaggle"
    fake.write_text(f"""#!/bin/bash
echo "$@" >> {calls}
if [ "$2" = submissions ]; then
  c=$(( $(cat {n}) + 1 )); echo $c > {n}
  st=SubmissionStatus.COMPLETE; [ $c -le {flips_after} ] && st=SubmissionStatus.PENDING
  echo 'ref,fileName,date,description,status,publicScore,privateScore'
  echo "57154639,submission.zip,d,\\"sub15b: v12-b1024, box 74 public: solved 28/74\\",$st,,"
  while IFS= read -r m; do echo "57154640,submission.zip,d,\\"$m\\",SubmissionStatus.PENDING,,"; done < {tmp / "subs"}
  exit 0
fi
if [ "$2" = submit ]; then while [ $# -gt 0 ]; do [ "$1" = -m ] && echo "$2" >> {tmp / "subs"}; shift; done; fi
echo "Successfully submitted"
""")
    (tmp / "subs").write_text("")
    fake.chmod(0o755)
    return fake, calls


def test_waits_while_another_submission_is_still_scoring(tmp_path):
    # regression 2026-10-14: sub16 got six 400s ("Your team already has 1 pending submissions; please wait for one to
    # finish scoring") because sub15b was still scoring; the CLI hides that body. Wait on the listing instead.
    fake, calls = _fake_kaggle_pending(tmp_path, flips_after=3)
    env = dict(os.environ, KAGGLE_BIN=str(fake), SUBMIT_LOG=str(tmp_path / "log.txt"), SUBMIT_TARGET_EPOCH="0",
               SKIP_GPU_GUARD="1", PENDING_POLL="1")
    subprocess.run(["bash", str(SCRIPT), "k", "0000", "sub16: v0-think"], env=env, check=True, timeout=60)
    sub = [l for l in calls.read_text().splitlines() if l.startswith("competitions submit ")]
    log = (tmp_path / "log.txt").read_text()
    assert len(sub) == 1 and "still scoring" in log and "attempt 1: Successfully" in log


def test_gives_up_without_submitting_if_still_scoring_at_the_deadline(tmp_path):
    fake, calls = _fake_kaggle_pending(tmp_path, flips_after=10**6)
    deadline = int(datetime.datetime.now(datetime.timezone.utc).timestamp()) + 3
    env = dict(os.environ, KAGGLE_BIN=str(fake), SUBMIT_LOG=str(tmp_path / "log.txt"), SUBMIT_TARGET_EPOCH="0",
               SKIP_GPU_GUARD="1", PENDING_POLL="1", PENDING_DEADLINE_EPOCH=str(deadline))
    p = subprocess.run(["bash", str(SCRIPT), "k", "0000", "sub16: v0-think"], env=env, timeout=60)
    assert p.returncode == 4
    assert not any(l.startswith("competitions submit ") for l in calls.read_text().splitlines())
    assert "still scoring at the pending deadline" in (tmp_path / "log.txt").read_text()


# ---- the GPU-overlap guard works from the day the slot falls in, also with SUBMIT_TARGET_EPOCH=0 (every arm script)

def _guard_run(tmp, clock_epoch, target, timeout):
    fake, calls = _fake_kaggle(tmp, [], gpu="RUNNING")
    env = dict(os.environ, KAGGLE_BIN=str(fake), SUBMIT_LOG=str(tmp / "log.txt"), SUBMIT_TARGET_EPOCH=str(target), FINAL_POLL="0",
               **_fake_clock(tmp, clock_epoch))
    p = subprocess.Popen(["bash", str(SCRIPT), "k", "0000", "sub9: x"], env=env, start_new_session=True)
    log = tmp / "log.txt"; end = time.time() + timeout
    # done, or parked in the guard's `sleep 600` (its "waiting" line is written right before the sleep, so nothing can follow it)
    while p.poll() is None and time.time() < end and not (log.exists() and "waiting: own GPU kernels busy" in log.read_text()):
        time.sleep(0.05)
    if p.poll() is None:
        os.killpg(p.pid, signal.SIGKILL); p.wait()          # the whole group: a killed bash leaves its `sleep 600` behind
    return p, calls, log.read_text()


def test_guard_waits_for_a_busy_gpu_kernel_with_target_epoch_zero(tmp_path):
    # regression 2026-10-29: with SUBMIT_TARGET_EPOCH=0 the day end was computed from 1970, so the guard logged "still busy at
    # day end; submitting anyway" on its first look and the submission went out over a running eval kernel
    p, calls, log = _guard_run(tmp_path, NOON, 0, timeout=20)
    assert p.returncode != 0                                    # still waiting (killed by the test), not finished
    assert "own GPU kernels busy: carsonrodrigues/g4-l4-v10" in log and "submitting anyway" not in log
    assert _submits(calls) == []


def test_guard_gives_way_at_the_end_of_the_slots_utc_day(tmp_path):
    # the day end is the later of the target and now: at 23:55 UTC the slot's day is over, so a busy kernel no longer holds it
    p, calls, log = _guard_run(tmp_path, LATE, 0, timeout=20)
    assert p.returncode == 0 and "GPU kernels still busy (carsonrodrigues/g4-l4-v10 ) at day end; submitting anyway" in log
    assert len(_submits(calls)) == 1


def test_guard_day_end_follows_a_target_in_the_future(tmp_path):
    # armed for tomorrow 00:01 (target = the next 00:01) the guard works to the end of THAT day, not today's
    tomorrow_0001 = int(datetime.datetime(2026, 10, 30, 0, 1, tzinfo=UTC).timestamp())
    p, calls, log = _guard_run(tmp_path, tomorrow_0001, tomorrow_0001, timeout=20)
    assert p.returncode != 0 and "own GPU kernels busy" in log and "submitting anyway" not in log and _submits(calls) == []


# ---- the exit status is the listing's verdict: 0 only when the tag is on Kaggle

def _status_run(tmp, fake, msg="sub9: x", tag=(), **env_extra):
    env = dict(os.environ, KAGGLE_BIN=str(fake), SUBMIT_LOG=str(tmp / "log.txt"), SUBMIT_TARGET_EPOCH="0", SKIP_GPU_GUARD="1",
               FINAL_POLL="0", **_fake_clock(tmp, NOON, sleeps=False), **env_extra)
    p = subprocess.run(["bash", str(SCRIPT), "k", "0000", msg, *tag], env=env, capture_output=True, text=True, timeout=60)
    return p, (tmp / "log.txt").read_text()


def test_exit_zero_and_a_final_listing_line_when_the_submission_landed(tmp_path):
    fake, calls = _fake_kaggle(tmp_path, [])
    p, log = _status_run(tmp_path, fake)
    assert p.returncode == 0 and len(_submits(calls)) == 1
    assert "sub9: is on Kaggle (final listing)" in log and "GAVE UP" not in log


def test_exit_zero_when_the_tag_was_already_on_kaggle(tmp_path):
    fake, calls = _fake_kaggle(tmp_path, ["sub9: staged earlier"])
    p, log = _status_run(tmp_path, fake)
    assert p.returncode == 0 and _submits(calls) == [] and "sub9: already on Kaggle, skipping" in log and "GAVE UP" not in log


def test_gives_up_with_exit_1_when_every_attempt_fails(tmp_path):
    # regression 2026-10-29: six 400s fell out of the loop and the script exited 0; the chains logged "submit_at exited 0"
    fake, calls = _fake_kaggle(tmp_path, [], submit="fail")
    p, log = _status_run(tmp_path, fake)
    assert p.returncode == 1 and len(_submits(calls)) == 6
    assert "GAVE UP: sub9: is not on Kaggle (absent from the final listing) after 6 attempts" in log and "is on Kaggle" not in log


def test_gives_up_with_exit_1_when_the_listing_never_comes_back_and_never_submits_blind(tmp_path):
    fake, calls = _fake_kaggle(tmp_path, [], listing_fails=True)
    p, log = _status_run(tmp_path, fake)
    assert p.returncode == 1 and _submits(calls) == []
    assert "GAVE UP: sub9: is not on Kaggle (final listing unreadable) after 6 attempts" in log


def test_a_rejected_attempt_that_actually_landed_counts_as_success(tmp_path):
    # the CLI printed an error but the submission is on the board: the next look finds the tag, so no second submit
    fake, calls = _fake_kaggle(tmp_path, [], submit="ghost")
    p, log = _status_run(tmp_path, fake)
    assert p.returncode == 0 and len(_submits(calls)) == 1 and "sub9: already on Kaggle, skipping" in log and "GAVE UP" not in log


def test_a_slow_listing_is_waited_for_but_not_forever(tmp_path):
    # Kaggle can take a moment to list a submission that just succeeded: two hidden listings are retried, three are a give-up
    fake, calls = _fake_kaggle(tmp_path, [], lag=2)
    p, log = _status_run(tmp_path, fake)
    assert p.returncode == 0 and len(_submits(calls)) == 1
    (tmp_path / "b").mkdir()
    fake2, calls2 = _fake_kaggle(tmp_path / "b", [], lag=3)
    p2, log2 = _status_run(tmp_path / "b", fake2)
    # it submitted once and could not confirm it: Kaggle printed success, so that is not a give-up (exit 3, not 1)
    assert p2.returncode == 5 and len(_submits(calls2)) == 1 and "GAVE UP" not in log2
    assert "SUBMITTED, UNCONFIRMED: sub9: (absent from the final listing) after 1 attempts" in log2


def test_the_final_listing_is_polled_every_30_s_by_default(tmp_path):
    # FINAL_POLL defaults to 30 s: with the sleep deleted or the default 0 the three listings run back to back and the lag tolerance is gone
    fake, calls = _fake_kaggle(tmp_path, [], lag=2)
    sleeps = tmp_path / "sleeps.txt"
    env = dict(os.environ, KAGGLE_BIN=str(fake), SUBMIT_LOG=str(tmp_path / "log.txt"), SUBMIT_TARGET_EPOCH="0", SKIP_GPU_GUARD="1",
               **_fake_clock(tmp_path, NOON, sleeps=sleeps))
    env.pop("FINAL_POLL", None); env.pop("FINAL_TRIES", None)
    p = subprocess.run(["bash", str(SCRIPT), "k", "0000", "sub9: x"], env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0 and len(_submits(calls)) == 1
    assert sleeps.read_text().split() == ["30", "30"]               # two hidden listings, one wait after each; the third confirms


def test_no_final_listing_wait_when_the_submission_shows_at_once(tmp_path):
    fake, calls = _fake_kaggle(tmp_path, [])
    sleeps = tmp_path / "sleeps.txt"
    env = dict(os.environ, KAGGLE_BIN=str(fake), SUBMIT_LOG=str(tmp_path / "log.txt"), SUBMIT_TARGET_EPOCH="0", SKIP_GPU_GUARD="1",
               **_fake_clock(tmp_path, NOON, sleeps=sleeps))
    env.pop("FINAL_POLL", None)
    p = subprocess.run(["bash", str(SCRIPT), "k", "0000", "sub9: x"], env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0 and len(_submits(calls)) == 1 and not sleeps.exists()


def test_success_printed_but_the_final_listing_unreadable_is_submitted_unconfirmed_exit_3(tmp_path):
    # the listing works until the submit goes through and then fails for good: the submission went out, so this is not a give-up
    # (exit 1) and the chain must not log a failure for it; a re-run asks the listing first and never submits blind
    calls = tmp_path / "calls.txt"; fake = tmp_path / "kaggle"
    fake.write_text(f"""#!/bin/bash
echo "$@" >> {calls}
if [ "$2" = submissions ]; then
  [ -e {tmp_path}/sent ] && {{ echo ConnectionError >&2; exit 1; }}
  echo 'ref,fileName,date,description,status'; exit 0
fi
if [ "$2" = submit ]; then touch {tmp_path}/sent; echo "Successfully submitted"; exit 0; fi
""")
    fake.chmod(0o755)
    p, log = _status_run(tmp_path, fake)
    assert p.returncode == 5 and len(_submits(calls)) == 1
    assert "SUBMITTED, UNCONFIRMED: sub9: (final listing unreadable) after 1 attempts" in log and "GAVE UP" not in log and "is on Kaggle" not in log


def test_a_tag_is_matched_as_a_fixed_string_not_a_regex(tmp_path):
    # "." and "[x]" are regex metacharacters: "sub1.5:" matched the lookalike "sub1x5:" (so the submission was skipped), and "[x] foo:" never
    # matched itself (so it was submitted twice)
    cases = [("sub1.5: new", ["sub1x5: older"], 1),            # a lookalike is not the tag: submit
             ("sub1.5: new", ["sub1.5: staged"], 0),           # the tag itself: already there
             ("[x] foo: bar", ["x foo: other"], 1), ("[x] foo: bar", ["[x] foo: staged"], 0),
             ("sub9*: x", ["sub99: y"], 1), ("sub9*: x", ["sub9*: y"], 0)]
    for n, (msg, existing, expected) in enumerate(cases):
        d = tmp_path / str(n); d.mkdir()
        fake, calls = _fake_kaggle(d, existing)
        p, log = _status_run(d, fake, msg)
        assert p.returncode == 0 and len(_submits(calls)) == expected, (msg, existing, log)


def test_a_message_without_a_colon_is_its_own_tag(tmp_path):
    # the default tag is the message up to the first colon; with no colon it used to be "<message>:", which no listing row starts with
    fake, calls = _fake_kaggle(tmp_path, ["plain message"])
    p, log = _status_run(tmp_path, fake, "plain message")
    assert p.returncode == 0 and _submits(calls) == [] and "plain message already on Kaggle" in log
    (tmp_path / "b").mkdir()
    fake2, calls2 = _fake_kaggle(tmp_path / "b", [])
    p2, log2 = _status_run(tmp_path / "b", fake2, "plain message")
    assert p2.returncode == 0 and len(_submits(calls2)) == 1 and "plain message is on Kaggle (final listing)" in log2


def test_an_explicit_tag_that_the_listing_cannot_show_is_unconfirmed_not_a_give_up(tmp_path):
    # the 4th argument is not a prefix of the message, so the listing can never confirm it; Kaggle did accept the submission
    fake, calls = _fake_kaggle(tmp_path, [])
    p, log = _status_run(tmp_path, fake, "sub9: x", tag=("other:",))
    assert p.returncode == 5 and len(_submits(calls)) == 1 and "SUBMITTED, UNCONFIRMED: other: (absent from the final listing)" in log


# ---- the chains exit with submit_at's status (eval/arm_sub*.sh logged "submit_at exited $?" and then exited 0)

# Every chain, not a numbered subset: a new arm_sub*.sh that does not capture rc fails here until it does.
CHAINS = sorted((ROOT / "eval").glob("arm_sub*.sh"))


def test_there_are_chains_to_check():
    assert {c.name for c in CHAINS} >= {"arm_sub18_chain.sh", "arm_sub19_chain.sh", "arm_sub19b_chain.sh", "arm_sub20_chain.sh", "arm_sub20_sub21.sh",
                                       "arm_sub21_aa.sh", "arm_sub21_chain.sh", "arm_sub22_sub23.sh", "arm_sub24_e4b.sh", "arm_sub25_e4b_card.sh",
                                       "arm_sub26_edit6.sh", "arm_sub27_ctx.sh"}


@pytest.mark.parametrize("chain", CHAINS, ids=lambda c: c.name)
def test_every_chain_captures_and_returns_submit_ats_status(chain):
    lines = chain.read_text().splitlines()
    calls = [i for i, l in enumerate(lines) if "scripts/submit_at.sh" in l and not l.lstrip().startswith("#")]
    assert calls
    for i in calls:
        assert lines[i + 1].lstrip().startswith("rc=$?"), (chain.name, lines[i + 1])      # captured before anything else can reset $?
    assert not any(re.search(r"exited \$\?", l) for l in lines), chain.name        # the log line prints the captured status
    last = [l for l in lines if l.strip()][-1]
    assert re.match(r'^exit "\$(rc|RC)"', last), (chain.name, last)
    assert subprocess.run(["bash", "-n", str(chain)]).returncode == 0


def _checkout(tmp, chain_text, files):
    """A throwaway checkout for a chain: the chain text with its hard-coded `cd` swapped for the sandbox, stubs for ship.sh
    (SHIP OK), kaggle_push_wait.sh (COMPLETE, version 3) and submit_at.sh (records its call, exits $SUBMIT_AT_RC, or the next of
    $SUBMIT_AT_RCS), and a kaggle stub whose listing has no PENDING row. Nothing here can reach the real checkout or Kaggle."""
    real = "/Users/carson/Projects/gemma-swe-agent"
    assert f"cd {real} " in chain_text
    text = chain_text.replace(f"cd {real} ", f"cd {tmp} ")
    assert real not in text
    for d in ("scripts", "eval", ".venv/bin", "sp"):
        (tmp / d).mkdir(parents=True, exist_ok=True)       # tmp may already be a git clone (the two-submit chains need an origin)
    text = re.sub(r"\bSP=/private/\S+", f"SP={tmp / 'sp'}", text)       # arm_sub20_sub21 and arm_sub22_sub23 hard-code the scratchpad for the ship logs
    assert "/private/tmp/claude-501" not in text
    (tmp / "scripts" / "ship.sh").write_text('#!/bin/bash\necho "SHIP OK: kernels/$2"\n')
    (tmp / "scripts" / "kaggle_push_wait.sh").write_text('#!/bin/bash\necho "$1: Kernel version 3 successfully pushed"; echo "$1: COMPLETE"\n')
    # exit status: SUBMIT_AT_RC for every call, or SUBMIT_AT_RCS="1 0" = the 1st call exits 1, the 2nd exits 0 (a chain with two submits)
    (tmp / "scripts" / "submit_at.sh").write_text(
        f'#!/bin/bash\necho "$@" >> {tmp / "submit_calls.txt"}\necho >> {tmp / "submit_n"}\nn=$(wc -l < {tmp / "submit_n"} | tr -d " ")\n'
        'rcs=(${SUBMIT_AT_RCS:-})\n[ -n "${SUBMIT_AT_RCS:-}" ] && exit "${rcs[$((n - 1))]}"\nexit "$SUBMIT_AT_RC"\n')
    (tmp / ".venv" / "bin" / "kaggle").write_text("#!/bin/bash\necho 'ref,fileName,date,description,status'\n")
    for f in (tmp / "scripts").iterdir():
        f.chmod(0o755)
    (tmp / ".venv" / "bin" / "kaggle").chmod(0o755)
    for rel, body in files.items():
        (tmp / rel).parent.mkdir(parents=True, exist_ok=True); (tmp / rel).write_text(body)
    script = tmp / "chain.sh"; script.write_text(text)
    return script


def _prepared_chain(tmp, chain):
    """The four 'PREPARED, NOT RUN' chains (sub24 to sub27): approval variable, bundle, test and pre-registration heading are
    read from the chain's own text."""
    text = chain.read_text()
    var = re.search(r'\[ "\$\{(CARSON_APPROVED_SUB\d+):-\}" = yes \]', text).group(1)
    bundle = re.search(r"^B=(\S+); SLUG=", text, re.M).group(1)
    test = re.search(r"-f (tests/\S+\.py) \]", text).group(1)
    heading = re.search(r'grep -q "\^(### [^"]+)" docs/GAPS_2026-10-06.md', text).group(1)
    script = _checkout(tmp, text, {f"submissions/{bundle}/agent.yaml": "", test: "", "docs/GAPS_2026-10-06.md": heading + "\n"})
    return script, var


@pytest.mark.parametrize("chain", [c for c in CHAINS if re.match(r"arm_sub2[4-7]_", c.name)], ids=lambda c: c.name)
@pytest.mark.parametrize("submit_rc", [0, 1, 4])
def test_a_prepared_chain_exits_with_submit_ats_status(tmp_path, chain, submit_rc):
    script, var = _prepared_chain(tmp_path, chain)
    env = dict(os.environ, SP=str(tmp_path / "sp"), SUBMIT_AT_RC=str(submit_rc), **{var: "yes"})
    p = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=60, cwd=tmp_path)
    assert p.returncode == submit_rc, p.stdout + p.stderr
    log = next((tmp_path / "eval").glob("*.out")).read_text()
    assert f"submit_at exited {submit_rc}" in log and "chain done" in log
    assert len((tmp_path / "submit_calls.txt").read_text().splitlines()) == 1


@pytest.mark.parametrize("submit_rc", [0, 1])
def test_the_aa_chain_exits_with_submit_ats_status(tmp_path, submit_rc):
    script = _checkout(tmp_path, (ROOT / "eval" / "arm_sub21_aa.sh").read_text(), {})
    env = dict(os.environ, SUBMIT_AT_RC=str(submit_rc))
    env.pop("OLD_PID", None)
    p = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=60, cwd=tmp_path)
    assert p.returncode == submit_rc, p.stdout + p.stderr
    assert f"sub21 (v12 A/A) submit_at exited {submit_rc}" in (tmp_path / "eval" / "arm_sub21_aa.out").read_text()


def test_the_aa_chain_is_stood_down_only_by_a_v16_chain_whose_submission_landed(tmp_path):
    # the v16 chain's log line now carries a real status: "exited 1" means sub21 is NOT on Kaggle, so the A/A must still go
    text = (ROOT / "eval" / "arm_sub21_aa.sh").read_text()
    landed = tmp_path / "landed"; gave_up = tmp_path / "gave_up"
    for d, status in ((landed, 0), (gave_up, 1)):
        d.mkdir()
        script = _checkout(d, text, {"eval/arm_sub21_chain.out": f"Thu Oct 29 00:01:00 UTC 2026 sub21 submit_at exited {status}\n"})
        env = dict(os.environ, SUBMIT_AT_RC="0"); env.pop("OLD_PID", None)
        p = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=60, cwd=d)
        assert p.returncode == 0, p.stdout + p.stderr
    assert not (landed / "submit_calls.txt").exists()                  # stood down: the v16 chain submitted sub21 itself
    assert len((gave_up / "submit_calls.txt").read_text().splitlines()) == 1      # it had given up: the A/A takes the slot


# ---- the two chains with two submits keep the FIRST non-zero submit_at status (a later success must not hide an earlier give-up)

GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x", "GIT_CONFIG_NOSYSTEM": "1"}


def _git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, env=GIT_ENV, capture_output=True, text=True, check=True).stdout


def _mac_clone(tmp, steps, baseline):
    """The Mac's checkout for a two-submit chain: a clone of a bare origin on wip/gemma-agent where the box has pushed an END line
    and a results.jsonl (the 74 public ids, 30 solved, 100 s each: it passes the gate) for every step and for the baseline, plus the
    real scripts/box_p4_gate.py."""
    bare = tmp / "origin.git"; _git(tmp, "init", "-q", "--bare", "-b", "wip/gemma-agent", str(bare))
    box = tmp / "box"; _git(tmp, "clone", "-q", str(bare), str(box)); _git(box, "checkout", "-q", "-b", "wip/gemma-agent")
    ids = [l.strip() for l in open(ROOT / "data" / "kaggle_valid_ids.txt") if l.strip()]
    (box / "docs" / "a6000" / "channel").mkdir(parents=True)
    (box / "docs" / "a6000" / "channel" / "box_to_mac.md").write_text("".join(f"- x | step=p4_{n} | END done: done=74/74 solved=30\n" for n in steps))
    for n in (*steps, baseline):
        d = box / "eval" / "a6000" / "results" / f"p4_{n}"; d.mkdir(parents=True)
        d.joinpath("results.jsonl").write_text("".join(json.dumps({"id": t, "resolved": i < 30, "secs": 100, "err": None}) + "\n" for i, t in enumerate(ids)))
    _git(box, "add", "-A"); _git(box, "commit", "-q", "-m", "box"); _git(box, "push", "-q", "-u", "origin", "wip/gemma-agent")
    mac = tmp / "mac"; _git(tmp, "clone", "-q", "-b", "wip/gemma-agent", str(bare), str(mac))
    (mac / "scripts").mkdir(); (mac / "data").mkdir()
    shutil.copy(ROOT / "scripts" / "box_p4_gate.py", mac / "scripts"); shutil.copy(ROOT / "data" / "kaggle_valid_ids.txt", mac / "data")
    return mac


@pytest.mark.parametrize("chain, steps, baseline, tags", [
    ("arm_sub20_sub21.sh", ["v16"], "v12", ["sub20:", "sub21:"]),
    ("arm_sub22_sub23.sh", ["v12b6", "v15b"], "v12b", ["sub22:", "sub23:"]),
])
@pytest.mark.parametrize("rcs, expected", [("1 0", 1), ("0 4", 4), ("0 0", 0), ("1 4", 1)])
def test_a_two_submit_chain_exits_with_the_first_non_zero_submit_at_status(tmp_path, chain, steps, baseline, tags, rcs, expected):
    mac = _mac_clone(tmp_path, steps, baseline)
    script = _checkout(mac, (ROOT / "eval" / chain).read_text(), {})
    (mac / ".venv" / "bin" / "python").write_text(f'#!/bin/bash\nexec {sys.executable} "$@"\n'); (mac / ".venv" / "bin" / "python").chmod(0o755)
    env = dict(GIT_ENV, SUBMIT_AT_RCS=rcs)
    for var in ("BUNDLES", "NEXT", "MEAN_GATE", "V", "OLD_PID"):
        env.pop(var, None)
    p = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=120, cwd=mac)
    assert p.returncode == expected, p.stdout + p.stderr
    calls = (mac / "submit_calls.txt").read_text().splitlines()
    assert [c.split()[-1] for c in calls] == tags, calls              # both submits ran, whatever the first one returned
    log = (mac / "eval" / (chain[:-3] + ".out")).read_text()
    assert re.findall(r"submit_at exited (\d+)", log) == rcs.split(), log
