"""aws/jobs/g1_autorun.sh (the launchd agent that launches the G1 pilot once AWS grants the quota, then fetches and scores it),
every branch of one `tick`, run by macOS's /bin/bash 3.2 like launchd runs it. A fake python answers the AWS-touching calls
(quota, launch.py, status.py, stage.py fetch, usable.py) from a scenario dir and runs the real python for everything else;
a fake launchctl records what it was asked. Nothing here talks to AWS or loads a real agent."""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "aws" / "jobs" / "g1_autorun.sh"
BASH = "/bin/bash" if Path("/bin/bash").exists() else shutil.which("bash")

FAKE_PY = r'''#!/bin/sh
case "$*" in
  *service-quotas*L-DB2E81BA*) cat "$FK/q_od" 2>/dev/null || echo 0; exit 0 ;;
  *service-quotas*L-3819A6DF*) cat "$FK/q_spot" 2>/dev/null || echo 0; exit 0 ;;
  *get_caller_identity*) echo "s3://gemma4-agent-123456789012/runs/g1"; exit 0 ;;
  aws/launch.py*)
    echo "$*" >> "$FK/launch_args"; n=$(wc -l < "$FK/launch_args" | tr -d ' ')
    if [ "$n" -le "$(cat "$FK/fail_n" 2>/dev/null || echo 0)" ]; then echo "LAUNCH FAILED $(cat "$FK/fail_code" 2>/dev/null || echo InsufficientInstanceCapacity): x" >&2; exit 1; fi
    echo "role teacher: ..."; echo "LAUNCHED i-0abc123; watch: python aws/status.py"; exit 0 ;;
  aws/status.py*) cat "$FK/status.json" 2>/dev/null || echo '[]'; exit 0 ;;
  aws/stage.py*)
    echo "$*" >> "$FK/fetch_args"; d=$4; mkdir -p "$d/box/i-0abc123" "$d/keep/eval/g1"
    echo rc=0 > "$d/box/i-0abc123/RESULT"; echo '{}' > "$d/keep/eval/g1/capture_devstral.jsonl"; exit 0 ;;
  scripts/distill/usable.py*) echo "$*" >> "$FK/usable_args"; exit 0 ;;
esac
exec "$REALPY" "$@"
'''
FAKE_LAUNCHCTL = '#!/bin/sh\necho "$*" >> "$FK/launchctl"\nexit 0\n'


@pytest.fixture
def env(tmp_path):
    fk, state = tmp_path / "fk", tmp_path / "state"
    fk.mkdir(); state.mkdir()
    for name, body in (("python", FAKE_PY), ("launchctl", FAKE_LAUNCHCTL)):
        (fk / name).write_text(body); (fk / name).chmod(0o755)
    plist = tmp_path / "agent.plist"; plist.write_text("<plist/>")
    e = {**os.environ, "FK": str(fk), "REALPY": sys.executable, "G1A_STATE": str(state), "G1A_PY": str(fk / "python"),
         "G1A_LAUNCHCTL": str(fk / "launchctl"), "G1A_PLIST": str(plist), "G1A_DEST": str(tmp_path / "dest"), "G1A_NOTIFY": "0"}
    (state / "deadline").write_text(str(int(time.time()) + 3600))
    return type("E", (), {"fk": fk, "state": state, "plist": plist, "dest": tmp_path / "dest", "env": e})


def tick(e, *args):
    r = subprocess.run([BASH, str(SCRIPT), *(args or ["tick"])], env=e.env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r


def read(p):
    return p.read_text() if p.exists() else ""


def removed(e):
    return not e.plist.exists() and "bootout" in read(e.fk / "launchctl")


def test_no_quota_does_nothing_but_record_the_check(env):
    tick(env)
    assert not (env.fk / "launch_args").exists() and not (env.state / "launched").exists()
    assert "on-demand=0 spot=0" in read(env.state / "last_check") and not removed(env)


def test_granted_on_demand_quota_launches_once_with_the_g1_cap(env):
    (env.fk / "q_od").write_text("52")
    tick(env)
    args = read(env.fk / "launch_args")
    assert args.count("aws/launch.py") == 1 and "--spot" not in args
    for flag in ("teacher", "--hours 3.75", "--max-usd 40", "--run s3://gemma4-agent-123456789012/runs/g1",
                 "--job bash aws/jobs/g1_teacher.sh", "--az auto", "--yes"):
        assert flag in args, flag
    assert read(env.state / "launched").split()[:2] == ["i-0abc123", "auto"]
    (env.fk / "status.json").write_text(json.dumps([{"id": "i-0abc123", "state": "running"}]))
    tick(env)
    assert read(env.fk / "launch_args").count("aws/launch.py") == 1          # never twice


def test_only_spot_granted_launches_on_spot(env):
    (env.fk / "q_spot").write_text("52")
    tick(env)
    assert "--spot" in read(env.fk / "launch_args")


def test_too_small_a_grant_does_not_launch(env):
    (env.fk / "q_od").write_text("40"); (env.fk / "q_spot").write_text("40")
    tick(env)
    assert not (env.fk / "launch_args").exists()


def test_capacity_errors_move_on_to_the_next_az(env):
    (env.fk / "q_od").write_text("52"); (env.fk / "fail_n").write_text("2")
    tick(env)
    assert read(env.fk / "launch_args").count("aws/launch.py") == 3
    assert read(env.state / "launched").split()[1] == "us-east-1b"


def test_three_non_capacity_failures_remove_the_agent(env):
    (env.fk / "q_od").write_text("52"); (env.fk / "fail_n").write_text("99"); (env.fk / "fail_code").write_text("UnauthorizedOperation")
    tick(env); tick(env)
    assert read(env.state / "failures").strip() == "2" and not removed(env)
    tick(env)
    assert removed(env) and not (env.state / "launched").exists()


def test_the_deadline_removes_the_agent_without_launching(env):
    (env.state / "deadline").write_text(str(int(time.time()) - 1)); (env.fk / "q_od").write_text("52")
    tick(env)
    assert removed(env) and not (env.fk / "launch_args").exists()


def test_a_box_alive_past_launch_plus_5h_raises_one_alarm_and_is_not_touched(env):
    (env.state / "launched").write_text(f"i-0abc123 auto {int(time.time()) - 5 * 3600 - 60}\n")
    (env.fk / "status.json").write_text(json.dumps([{"id": "i-0abc123", "state": "running"}]))
    tick(env); tick(env)
    assert (env.state / "alarmed").exists() and read(env.state / "log").count("ALERT") == 1
    assert not (env.fk / "fetch_args").exists() and not removed(env)


def test_when_the_box_is_gone_results_are_fetched_scored_and_the_agent_removed(env):
    (env.state / "launched").write_text(f"i-0abc123 auto {int(time.time()) - 2 * 3600}\n")
    (env.fk / "status.json").write_text(json.dumps([{"id": "i-0abc123", "state": "terminated"}]))
    tick(env)
    assert read(env.fk / "fetch_args").split()[:4] == ["aws/stage.py", "fetch", "s3://gemma4-agent-123456789012/runs/g1", str(env.dest)]
    usable = read(env.fk / "usable_args")
    assert "capture_devstral.jsonl" in usable and "--ids data/distill/g1_ids.txt" in usable and "gptoss" not in usable
    usd = float(usable.split("--ec2-usd ")[1].split()[0])
    assert 20.0 < usd < 22.0                                                 # about 2 h at $10.54/h, an upper bound
    assert "gptoss: no capture" in read(env.state / "log")
    assert (env.state / "DONE").exists() and removed(env)


def test_a_held_lock_makes_the_tick_a_no_op(env):
    (env.state / "lock").mkdir(); (env.fk / "q_od").write_text("52")
    tick(env)
    assert not (env.fk / "launch_args").exists() and (env.state / "lock").exists()


def test_install_writes_a_valid_agent_and_uninstall_removes_it(env, tmp_path):
    env.plist.unlink()
    r = tick(env, "install", "72")
    assert "installed com.carson.g4-g1-autorun" in r.stdout
    s = env.plist.read_text()
    assert "<string>tick</string>" in s and "<integer>600</integer>" in s and str(SCRIPT) in s
    if shutil.which("plutil"):
        assert subprocess.run(["plutil", "-lint", str(env.plist)], capture_output=True).returncode == 0
    assert f"bootstrap gui/{os.getuid()} {env.plist}" in read(env.fk / "launchctl")
    left = int(read(env.state / "deadline")) - time.time()
    assert 71.9 * 3600 < left <= 72 * 3600
    tick(env, "uninstall")
    assert not env.plist.exists()


def test_script_lints():
    assert subprocess.run([BASH, "-n", str(SCRIPT)], capture_output=True).returncode == 0
    if shutil.which("shellcheck"):
        r = subprocess.run(["shellcheck", str(SCRIPT)], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout
