"""scripts/kaggle_sequence.sh: after the gate opens, push-and-wait each slug in order, one at a time, stop at the first
failure, log one line per kernel. Composed of tested parts (overnight_gate.sh, kaggle_push_wait.sh) swapped by env."""
import os, pathlib, subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "kaggle_sequence.sh"


def _run(tmp, gate_rc, push_fail_on=None, slugs=("a", "b", "c")):
    gate = tmp / "gate.sh"; gate.write_text(f'#!/bin/bash\necho gate >> "$CALLS"\nexit {gate_rc}\n'); gate.chmod(0o755)
    push = tmp / "push.sh"
    push.write_text('#!/bin/bash\necho "push $1" >> "$CALLS"\n' + (f'[ "$1" = {push_fail_on} ] && exit 1\n' if push_fail_on else "") + "exit 0\n")
    push.chmod(0o755)
    env = dict(os.environ, GATE_SH=str(gate), PUSH_WAIT_SH=str(push), CALLS=str(tmp / "calls"), SEQ_LOG=str(tmp / "seq.log"))
    r = subprocess.run(["bash", str(SCRIPT), *slugs], env=env, capture_output=True, text=True, timeout=60)
    calls = (tmp / "calls").read_text() if (tmp / "calls").exists() else ""
    return r.returncode, calls, r.stdout + r.stderr


def test_runs_slugs_in_order_after_the_gate(tmp_path):
    rc, calls, out = _run(tmp_path, 0)
    assert rc == 0 and calls.splitlines() == ["gate", "push a", "push b", "push c"]


def test_closed_gate_runs_nothing(tmp_path):
    rc, calls, out = _run(tmp_path, 1)
    assert rc != 0 and calls.splitlines() == ["gate"] and "gate" in out


def test_stops_at_first_failed_kernel(tmp_path):
    rc, calls, out = _run(tmp_path, 0, push_fail_on="b")
    assert rc != 0 and calls.splitlines() == ["gate", "push a", "push b"] and "b" in out
