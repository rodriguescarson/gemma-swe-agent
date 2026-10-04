"""scripts/collect/watchdog.sh with SESSION=- runs standalone: it guards every Docker emulation container whatever
launched it (2026-10-04: an or_race_public screen took free disk 19 -> 6 GB while the session-bound watchdog had
exited because no tmux session named 'collect' existed). Fake df/docker/tmux; WATCHDOG_MAX_LOOPS bounds the loop."""
import os, pathlib, subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "collect" / "watchdog.sh"


def _fakes(tmp, free):
    for name, body in (("df", f'echo "F S U A C"; echo "/dev/x 460 400 {free} 9%"'),
                       ("docker", 'echo "docker $*" >> "$CALLS"; [ "$1" = ps ] && echo cid1'),
                       ("tmux", 'echo "tmux $*" >> "$CALLS"; exit 1')):
        f = tmp / name; f.write_text("#!/bin/bash\n" + body + "\n"); f.chmod(0o755)
    (tmp / "eval" / "collect").mkdir(parents=True)
    return dict(os.environ, PATH=f"{tmp}:{os.environ['PATH']}", CALLS=str(tmp / "calls"), WATCHDOG_MAX_LOOPS="2", WATCHDOG_SLEEP_S="0")


def test_standalone_mode_kills_containers_when_disk_is_low(tmp_path):
    env = _fakes(tmp_path, 2)
    r = subprocess.run(["bash", str(SCRIPT), "-"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    calls = (tmp_path / "calls").read_text()
    assert r.returncode == 0 and "docker kill cid1" in calls
    assert "WATCHDOG" in (tmp_path / "eval" / "collect" / "watchdog.log").read_text()


def test_standalone_mode_keeps_running_without_any_session_and_leaves_healthy_disk_alone(tmp_path):
    env = _fakes(tmp_path, 20)
    r = subprocess.run(["bash", str(SCRIPT), "-"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    calls = (tmp_path / "calls").read_text() if (tmp_path / "calls").exists() else ""
    assert r.returncode == 0 and "docker kill" not in calls
