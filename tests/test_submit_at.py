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
