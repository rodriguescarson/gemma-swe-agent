"""submit_at.sh must never double-submit when two machines are armed."""
import os, subprocess, datetime, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "submit_at.sh"


def _fake_kaggle(tmp, existing):
    calls = tmp / "calls.txt"
    fake = tmp / "kaggle"
    fake.write_text(f"""#!/bin/bash
echo "$@" >> {calls}
if [ "$2" = submissions ]; then
  echo 'ref,fileName,date,description,status'
  {"".join(f'echo \'1,submission.zip,d,"{d}",COMPLETE\';' for d in existing)}
  exit 0
fi
echo "Successfully submitted"
""")
    fake.chmod(0o755)
    return fake, calls


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
    p = subprocess.Popen(["bash", str(SCRIPT), "k", past, "sub9: x"], env=env)
    try:
        p.wait(timeout=4); fired = True
    except subprocess.TimeoutExpired:
        fired = False
    finally:
        p.kill()
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
    p = subprocess.Popen(["bash", str(SCRIPT), "k", "0000", "sub9: x"], env=env)
    try: p.wait(timeout=5)
    except subprocess.TimeoutExpired: pass
    finally: p.kill()
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
    env = dict(os.environ, KAGGLE_BIN=str(fake), SUBMIT_LOG=str(tmp_path / "log.txt"),
               SUBMIT_TARGET_EPOCH=str(int(datetime.datetime.now(datetime.timezone.utc).timestamp())))
    p = subprocess.Popen(["bash", str(SCRIPT), "k", "0000", "sub9: x"], env=env)
    try:
        p.wait(timeout=4)
    except subprocess.TimeoutExpired:
        pass
    finally:
        p.kill()
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
  exit 0
fi
echo "Successfully submitted"
""")
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
  exit 0
fi
echo "Successfully submitted"
""")
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
