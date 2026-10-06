"""scripts/kaggle_push_retry.sh <slug>: re-run kaggle_push_wait.sh while the push is refused with Kaggle's
'Maximum batch GPU session count' message (2 GPU sessions per account), stop on any other outcome. Written first."""
import os, pathlib, subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "kaggle_push_retry.sh"


def _run(tmp, outcomes):
    fake = tmp / "push_wait.sh"
    fake.write_text('#!/bin/bash\nn=$(cat "$CNT" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$CNT"\n'
                    'o=$(sed -n "${n}p" "$OUTCOMES")\ncase "$o" in\n'
                    '  busy) echo "k: Kernel push error: Maximum batch GPU session count of 2 reached."; echo "k: push FAILED"; exit 1;;\n'
                    '  ok) echo "k: COMPLETE"; exit 0;;\n  err) echo "k: KernelWorkerStatus.ERROR"; exit 1;;\nesac\n')
    fake.chmod(0o755)
    (tmp / "outcomes").write_text("\n".join(outcomes) + "\n")
    env = dict(os.environ, PUSH_WAIT_SH=str(fake), CNT=str(tmp / "cnt"), OUTCOMES=str(tmp / "outcomes"), RETRY_S="0", RETRY_MAX="10")
    r = subprocess.run(["bash", str(SCRIPT), "k"], env=env, capture_output=True, text=True, timeout=60)
    return r.returncode, int((tmp / "cnt").read_text()), r.stdout


def test_retries_while_sessions_are_full_then_succeeds(tmp_path):
    rc, n, out = _run(tmp_path, ["busy", "busy", "ok"])
    assert rc == 0 and n == 3 and "COMPLETE" in out


def test_other_failures_stop_immediately(tmp_path):
    rc, n, out = _run(tmp_path, ["err", "ok"])
    assert rc != 0 and n == 1


def test_weekly_quota_refusal_is_retried_too(tmp_path):
    fake = tmp_path / "push_wait.sh"
    fake.write_text('#!/bin/bash\nn=$(cat "$CNT" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$CNT"\n'
                    '[ $n -lt 3 ] && { echo "k: Kernel push error: Maximum weekly GPU quota of 30.00 hours reached."; echo "k: push FAILED"; exit 1; }\n'
                    'echo "k: COMPLETE"; exit 0\n')
    fake.chmod(0o755)
    env = dict(os.environ, PUSH_WAIT_SH=str(fake), CNT=str(tmp_path / "cnt"), RETRY_S="0", RETRY_MAX="10")
    r = subprocess.run(["bash", str(SCRIPT), "k"], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and (tmp_path / "cnt").read_text().strip() == "3" and "quota" in r.stdout.lower()


def _fake(tmp, script):
    fake = tmp / "push_wait.sh"; fake.write_text("#!/bin/bash\n" + script); fake.chmod(0o755)
    return fake


def test_transient_connection_error_during_push_is_retried(tmp_path):
    """2026-10-06 13:00 IST: 'Connection aborted / RemoteDisconnected' on push ended the loop, so the queue dropped v5h2."""
    fake = _fake(tmp_path, 'n=$(cat "$CNT" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$CNT"\n'
                           '[ $n -lt 3 ] && { echo "k: (\'Connection aborted.\', RemoteDisconnected(\'Remote end closed connection without response\'))"; echo "k: push FAILED"; exit 1; }\n'
                           'echo "k: COMPLETE"; exit 0\n')
    env = dict(os.environ, PUSH_WAIT_SH=str(fake), CNT=str(tmp_path / "cnt"), RETRY_S="0", RETRY_MAX="10")
    r = subprocess.run(["bash", str(SCRIPT), "k"], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and (tmp_path / "cnt").read_text().strip() == "3", r.stdout


def test_connection_error_after_a_successful_push_is_not_retried(tmp_path):
    """A drop while POLLING a kernel that did start must not push a second (quota-billed) run."""
    fake = _fake(tmp_path, 'n=$(cat "$CNT" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$CNT"\n'
                           'echo "k: pushed v3"; echo "k: (\'Connection aborted.\', RemoteDisconnected(\'x\'))"; exit 1\n')
    env = dict(os.environ, PUSH_WAIT_SH=str(fake), CNT=str(tmp_path / "cnt"), RETRY_S="0", RETRY_MAX="10")
    r = subprocess.run(["bash", str(SCRIPT), "k"], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode != 0 and (tmp_path / "cnt").read_text().strip() == "1"


def test_max_retries_exceeded_during_push_is_retried(tmp_path):
    """2026-10-06 23:20 IST: urllib3 'Max retries exceeded' on the push also never started a run."""
    fake = _fake(tmp_path, 'n=$(cat "$CNT" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$CNT"\n'
                           '[ $n -lt 2 ] && { echo "k: HTTPSConnectionPool(host=\'api.kaggle.com\', port=443): Max retries exceeded with url: /v1/kernels"; echo "k: push FAILED"; exit 1; }\n'
                           'echo "k: COMPLETE"; exit 0\n')
    env = dict(os.environ, PUSH_WAIT_SH=str(fake), CNT=str(tmp_path / "cnt"), RETRY_S="0", RETRY_MAX="10")
    r = subprocess.run(["bash", str(SCRIPT), "k"], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and (tmp_path / "cnt").read_text().strip() == "2", r.stdout
