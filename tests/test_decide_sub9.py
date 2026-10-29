"""decide_sub9.sh (E3/E4/E5 in docs/PLAN_TO_FINISH.txt), written before the fix:
- provider/infra errors (litellm.APIError, connection refused, proxy budget) never count as a bundle crash class;
- the verdict is v4h2 when rows >= 80, heredoc crashes <= 2 and no other non-timeout crash; else v4;
- when the decision happens after 00:01 UTC of the slot day it submits NOW (SUBMIT_TARGET_EPOCH=0), not tomorrow;
- the submitted marker is written by the script after the submit call returns, never by grepping old log lines."""
import json, os, subprocess, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "decide_sub9.sh"


def _rows(tmp, specs):
    p = tmp / "task_results.jsonl"
    p.write_text("".join(json.dumps({"instance_id": f"t{i}", "resolved": r, "error": e}) + "\n" for i, (r, e) in enumerate(specs)))
    return p


def _run(tmp, rows_path, now_utc_hhmm="0023", submit_rc=0):
    """submit_rc: the stub submit_at.sh's exit status; the script must exit with it."""
    fake = tmp / "submit_at.sh"
    fake.write_text('#!/bin/bash\necho "FAKE_SUBMIT kernel=$1 at=$2 epoch=${SUBMIT_TARGET_EPOCH:-unset} ver=${KERNEL_VERSION:-unset}" >> "$FAKE_LOG"\n'
                    f'exit {submit_rc}\n')
    fake.chmod(0o755)
    env = dict(os.environ, DECIDE_AT="0000", SAMPLE2_RESULTS=str(rows_path), SUBMIT_AT_SH=str(fake), FAKE_LOG=str(tmp / "fake.log"),
               MARKER=str(tmp / "sub9_submitted"), SUBMIT_LOG=str(tmp / "submit_log.txt"), PROGRESS_LOG=str(tmp / "progress.log"),
               FAKE_UTC_HHMM=now_utc_hhmm)
    (tmp / "submit_log.txt").write_text("Mon Sep 28 02:10:44 UTC 2026 [old] attempt 1: HTTPSConnectionPool...\n")   # stale line
    p = subprocess.run(["bash", str(SCRIPT)], env=env, timeout=60)
    assert p.returncode == submit_rc
    return (tmp / "fake.log").read_text(), (tmp / "submit_log.txt").read_text()


def test_provider_errors_do_not_block_v4h2_and_do_not_count_as_rows(tmp_path):
    # 80 rows reached the model (20 solved, 57 timeouts, 1 heredoc, 2 budget) + 7 provider errors: v4h2, rows=80
    rows = _rows(tmp_path, [(True, None)] * 20 + [(False, "Agent exceeded session timeout (5.0 min)")] * 57
                 + [(False, "Sandbox execution error: litellm.APIError: APIError: OpenRouterException")] * 7
                 + [(False, "Sandbox execution error: Tool 'python3 /tmp/swe/edit.py x' not found")] * 1
                 + [(False, "Agent exceeded tool call budget (70 calls)")] * 2)
    fake, log = _run(tmp_path, rows)
    assert "kernel=g4agent-v4h2" in fake and "v4h2 rows=80 infra=7 heredoc=1" in log


def test_phantom_rows_do_not_reach_the_80_floor(tmp_path):
    """GATE.md addendum 2026-10-03: sample 2 had 159 rows of which 85 were 'Key limit exceeded' and never reached the
    model; the floor is on rows that did."""
    rows = _rows(tmp_path, [(True, None)] * 20 + [(False, None)] * 54
                 + [(False, "Sandbox execution error: litellm.APIError: APIError: OpenAIException - Key limit exceeded (total limit)")] * 85)
    fake, log = _run(tmp_path, rows)
    assert "kernel=g4agent-sub3" in fake and "rows=74" in log and "infra=85" in log


def test_real_new_crash_class_falls_back_to_v4(tmp_path):
    rows = _rows(tmp_path, [(True, None)] * 20 + [(False, None)] * 60 + [(False, "Sandbox execution error: KeyError: 'plan'")] * 3)
    fake, log = _run(tmp_path, rows)
    assert "kernel=g4agent-sub3" in fake


def test_too_many_heredoc_crashes_fall_back_to_v4(tmp_path):
    rows = _rows(tmp_path, [(True, None)] * 20 + [(False, None)] * 60 + [(False, "Sandbox execution error: Tool 'python3 /tmp/swe/edit.py' not found")] * 3)
    fake, _ = _run(tmp_path, rows)
    assert "kernel=g4agent-sub3" in fake


def test_decision_after_0001_utc_submits_now_and_writes_marker_itself(tmp_path):
    rows = _rows(tmp_path, [(True, None)] * 20 + [(False, None)] * 60)
    fake, _ = _run(tmp_path, rows, now_utc_hhmm="0023")
    assert "epoch=0" in fake                                   # SUBMIT_TARGET_EPOCH=0: fire now, not tomorrow
    assert (tmp_path / "sub9_submitted").exists()              # written after the submit call, not from a grep


def test_decision_before_0001_utc_waits_for_the_slot(tmp_path):
    rows = _rows(tmp_path, [(True, None)] * 20 + [(False, None)] * 60)
    fake, _ = _run(tmp_path, rows, now_utc_hhmm="2340")
    assert "at=0001" in fake and "epoch=unset" in fake


def test_a_submit_at_give_up_writes_no_marker_logs_failed_and_is_the_scripts_exit_status(tmp_path):
    # submit_at.sh exits 1 when it gave up (since 2026-10-29; it used to exit 0): the marker means "sub9 is on Kaggle" and must not be written
    rows = _rows(tmp_path, [(True, None)] * 20 + [(False, None)] * 60)
    fake, log = _run(tmp_path, rows, now_utc_hhmm="0023", submit_rc=1)
    assert "kernel=g4agent-v4h2" in fake                                   # it did call submit_at
    assert not (tmp_path / "sub9_submitted").exists()
    progress = (tmp_path / "progress.log").read_text()
    assert "decide_sub9: submit_at FAILED (exit 1); no marker" in log and "submit_at FAILED (exit 1); no marker" in progress
    assert "submit_at returned 0" not in progress
