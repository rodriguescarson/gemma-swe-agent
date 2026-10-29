"""scripts/decide_or_skip.sh: the slot decision with no fallback (2026-10-10, sub13 = v5h2-think). A fake kaggle binary plays
Kaggle (status, output), a stub submit_at.sh records what would have been submitted. PASS submits the candidate with the
message; FAIL (too few solved, a crash row, too many seconds) and a non-COMPLETE eval leave the slot unused with exit 3 and a
SKIPPED line; a missing results file is NO_RESULTS; the eval wait loop polls until COMPLETE. Written before the script was armed.

2026-10-29: the script judged every row of the results file, but the competition's tasks.jsonl has 129 tasks and only the 74
in data/kaggle_valid_ids.txt are graded (55 fail even with the gold patch), so extra rows could pass or fail a candidate on
tasks that do not count, and a file missing a graded id still passed. Rows are now filtered to the valid ids, all of them
must be present, and a failed output download is retried (3 tries) before the slot is given up as NO_RESULTS."""
import datetime, json, os, shutil, stat, subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "decide_or_skip.sh"


def rows(n_solved, n_total=74, crash=False, secs=120.0):
    out = []
    for i in range(n_total):
        out.append({"id": f"t{i}", "resolved": i < n_solved, "err": ("Tool 'view.py' not found." if crash and i == 3 else None), "secs": secs})
    return out


def harness(tmp_path, statuses, results, fail_outputs=0):
    """A scripts/ dir with decide_or_skip.sh, a stub submit_at.sh and a fake kaggle; statuses are consumed in order. The
    repository layout is mimicked: data/kaggle_valid_ids.txt (t0..t73, the ids rows() makes) sits next to scripts/, and
    the first `fail_outputs` calls of 'kernels output' fail with exit 1 and no file (their count is in outputs.count), or with
    a truncated results.jsonl left behind when the test sets FAKE_PARTIAL in the script's environment."""
    sdir = tmp_path / "scripts"; sdir.mkdir()
    (tmp_path / "data").mkdir(); (tmp_path / "data" / "kaggle_valid_ids.txt").write_text("".join(f"t{i}\n" for i in range(74)))
    shutil.copy(SCRIPT, sdir / "decide_or_skip.sh")
    (sdir / "submit_at.sh").write_text("#!/bin/bash\necho \"SUBMIT $1 at=$2 msg=$3 version=${KERNEL_VERSION:-}\" >> \"$SUBMIT_LOG\"\nexit 0\n")
    (sdir / "submit_at.sh").chmod(0o755)
    seq = tmp_path / "statuses.txt"; seq.write_text("\n".join(statuses) + "\n")
    res = tmp_path / "results.jsonl"
    if results is not None:
        res.write_text("".join(json.dumps(r) + "\n" for r in results))
    kaggle, cnt = tmp_path / "kaggle", tmp_path / "outputs.count"
    kaggle.write_text(f"""#!/bin/bash
# fake kaggle: 'kernels status X' pops the next status; 'kernels output X -p DIR' copies results.jsonl into DIR
if [ "$1 $2" = "kernels status" ]; then
  s=$(head -n 1 {seq}); [ -z "$s" ] && s=KernelWorkerStatus.COMPLETE
  tail -n +2 {seq} > {seq}.tmp; [ -s {seq}.tmp ] && mv {seq}.tmp {seq} || echo "$s" > {seq}
  echo "carsonrodrigues/$3 has status \\"$s\\""; exit 0
fi
if [ "$1 $2" = "kernels output" ]; then
  n=$(cat {cnt} 2>/dev/null || echo 0); n=$((n+1)); echo $n > {cnt}
  for ((i=1;i<=$#;i++)); do [ "${{!i}}" = "-p" ] && j=$((i+1)) && d=${{!j}}; done
  [ "$n" -le {fail_outputs} ] && {{ [ -n "${{FAKE_PARTIAL:-}}" ] && {{ mkdir -p "$d"; printf '{{"id": "t0", "resol' > "$d/results.jsonl"; }}; echo "fake kaggle: output download failed" >&2; exit 1; }}
  mkdir -p "$d"; [ -f {res} ] && cp {res} "$d/results.jsonl"; exit 0
fi
echo "fake kaggle: unknown $*" >&2; exit 1
""")
    kaggle.chmod(kaggle.stat().st_mode | stat.S_IEXEC)
    return sdir, kaggle


def output_calls(tmp_path):
    f = tmp_path / "outputs.count"
    return int(f.read_text()) if f.exists() else 0


NOON = int(datetime.datetime(2026, 10, 29, 12, 0, tzinfo=datetime.timezone.utc).timestamp())


def fake_clock(tmp_path, now_epoch=NOON):
    """PATH for a fixed clock: `date -u +%s` reports now_epoch, every other form of date is the real one. The script waits for
    the eval kernel only until 15 minutes before the end of the UTC day, so with the wall clock the wait-loop test failed from
    23:45 to 00:00 UTC (the loop saw the day as over and skipped at the first RUNNING status)."""
    b = tmp_path / "fakebin"; b.mkdir(exist_ok=True)
    (b / "date").write_text(f'#!/bin/bash\n[ "$1 $2" = "-u +%s" ] && {{ echo {now_epoch}; exit 0; }}\nexec /bin/date "$@"\n')
    (b / "date").chmod(0o755)
    return {"PATH": f"{b}:{os.environ['PATH']}"}


def run(tmp_path, statuses, results, min_solved=29, env=None, fail_outputs=0, now_epoch=NOON):
    sdir, kaggle = harness(tmp_path, statuses, results, fail_outputs)
    log = tmp_path / "log.txt"
    e = dict(os.environ, KAGGLE_BIN=str(kaggle), SUBMIT_LOG=str(log), DECIDE_OUT=str(tmp_path / "out"), SUBMIT_TARGET_EPOCH="0",
             DECIDE_POLL_S="0", DECIDE_RETRY_S="0", KERNEL_VERSION="1", **fake_clock(tmp_path, now_epoch), **(env or {}))
    p = subprocess.run(["bash", str(sdir / "decide_or_skip.sh"), "g4-eval74-v4", "g4agent-v5h2-think", "0001", str(min_solved), "sub13: test"],
                       capture_output=True, text=True, env=e, timeout=60)
    return p.returncode, log.read_text() if log.exists() else ""


def test_pass_submits_the_candidate_with_the_message_and_version(tmp_path):
    rc, log = run(tmp_path, ["KernelWorkerStatus.COMPLETE"], rows(31))
    assert rc == 0, log
    assert "decision: PASS 31 74 0 8880" in log and "SUBMIT g4agent-v5h2-think at=0000 msg=sub13: test version=1" in log, log


def test_a_failing_submit_at_is_the_scripts_exit_status_not_skipped(tmp_path):
    # PASS execs submit_at.sh: its give-up (exit 1) must come out as 1, not 0 and not the SKIPPED status 3
    sdir, kaggle = harness(tmp_path, ["KernelWorkerStatus.COMPLETE"], rows(31))
    (sdir / "submit_at.sh").write_text('#!/bin/bash\necho "SUBMIT $1 at=$2" >> "$SUBMIT_LOG"\nexit 1\n')
    log = tmp_path / "log.txt"
    e = dict(os.environ, KAGGLE_BIN=str(kaggle), SUBMIT_LOG=str(log), DECIDE_OUT=str(tmp_path / "out"), SUBMIT_TARGET_EPOCH="0",
             DECIDE_POLL_S="0", KERNEL_VERSION="1", **fake_clock(tmp_path))
    p = subprocess.run(["bash", str(sdir / "decide_or_skip.sh"), "g4-eval74-v4", "g4agent-v5h2-think", "0001", "29", "sub13: test"],
                       capture_output=True, text=True, env=e, timeout=60)
    text = log.read_text()
    assert p.returncode == 1 and "decision: PASS 31 74 0" in text and "SUBMIT g4agent-v5h2-think at=0000" in text and "SKIPPED" not in text, text


def test_too_few_solved_skips_the_slot(tmp_path):
    rc, log = run(tmp_path, ["KernelWorkerStatus.COMPLETE"], rows(28))
    assert rc == 3 and "decision: FAIL 28 74 0" in log and "SKIPPED: slot left unused" in log and "SUBMIT" not in log, log


def test_a_crash_row_skips_even_with_enough_solved(tmp_path):
    rc, log = run(tmp_path, ["KernelWorkerStatus.COMPLETE"], rows(35, crash=True))
    assert rc == 3 and "decision: FAIL 35 74 1" in log and "SUBMIT" not in log, log


def test_too_many_seconds_skips(tmp_path):
    rc, log = run(tmp_path, ["KernelWorkerStatus.COMPLETE"], rows(35, secs=400.0))        # 74 x 400 = 29,600 > 23,000
    assert rc == 3 and "decision: FAIL 35 74 0 29600" in log, log


def test_the_wait_loop_polls_until_complete_then_decides(tmp_path):
    rc, log = run(tmp_path, ["KernelWorkerStatus.RUNNING", "KernelWorkerStatus.RUNNING", "KernelWorkerStatus.COMPLETE"], rows(30))
    assert rc == 0 and log.count("waiting for eval kernel") == 2 and "decision: PASS 30 74" in log, log


def test_an_errored_eval_skips(tmp_path):
    rc, log = run(tmp_path, ["KernelWorkerStatus.ERROR"], rows(40))
    assert rc == 3 and "decision: NO_EVAL status=KernelWorkerStatus.ERROR" in log and "SUBMIT" not in log, log


def test_missing_results_is_no_results(tmp_path):
    rc, log = run(tmp_path, ["KernelWorkerStatus.COMPLETE"], None)
    assert rc == 3 and "decision: NO_RESULTS" in log, log
    assert output_calls(tmp_path) == 3 and log.count("output download of g4-eval74-v4 failed") == 3, log     # no file = a failed try


def test_missing_kaggle_binary_aborts_at_arm_time(tmp_path):
    sdir, _ = harness(tmp_path, ["KernelWorkerStatus.COMPLETE"], rows(31))
    log = tmp_path / "log.txt"
    e = dict(os.environ, KAGGLE_BIN=str(tmp_path / "nope"), SUBMIT_LOG=str(log), SUBMIT_TARGET_EPOCH="0")
    p = subprocess.run(["bash", str(sdir / "decide_or_skip.sh"), "e", "c", "0001", "29", "m"], capture_output=True, text=True, env=e, timeout=30)
    assert p.returncode == 2 and "ABORT: kaggle binary not found" in log.read_text()


def test_a_still_running_eval_at_the_end_of_the_utc_day_skips_the_slot(tmp_path):
    # the other side of the wait loop, on a fixed clock at 23:50 UTC (inside the last 15 minutes): no further wait, no submission
    late = int(datetime.datetime(2026, 10, 29, 23, 50, tzinfo=datetime.timezone.utc).timestamp())
    rc, log = run(tmp_path, ["KernelWorkerStatus.RUNNING"], rows(40), now_epoch=late)
    assert rc == 3 and "waiting for eval kernel" not in log and "decision: NO_EVAL status=KernelWorkerStatus.RUNNING" in log and "SUBMIT" not in log, log


# ------------------------------------------------------------------------------ only the 74 graded ids are judged
def extra_rows(n=55, resolved=False, crash=False, secs=500.0):
    """Rows for tasks outside data/kaggle_valid_ids.txt (the 55 ungradable ones in the competition's tasks.jsonl)."""
    return [{"id": f"x{i}", "resolved": resolved, "err": ("Tool 'view.py' not found." if crash else None), "secs": secs}
            for i in range(n)]


def test_rows_outside_the_valid_ids_are_not_judged(tmp_path):
    """129 rows, 55 of them off-list with crash errors and 27,500 s: the verdict is the 74 valid rows' (31 solved, 8,880 s)."""
    rc, log = run(tmp_path, ["KernelWorkerStatus.COMPLETE"], rows(31) + extra_rows(crash=True))
    assert rc == 0 and "decision: PASS 31 74 0 8880 0" in log and "SUBMIT g4agent-v5h2-think" in log, log


def test_off_list_solves_do_not_count_toward_the_minimum(tmp_path):
    """25 valid solves plus 30 off-list solves is 55 rows resolved, but only 25 are graded tasks: below the minimum of 29."""
    rc, log = run(tmp_path, ["KernelWorkerStatus.COMPLETE"], rows(25) + extra_rows(30, resolved=True))
    assert rc == 3 and "decision: FAIL 25 74 0 8880 0" in log and "SUBMIT" not in log, log


def test_a_valid_id_without_a_row_skips_even_when_everything_else_passes(tmp_path):
    """Every row is clean and 35 solved, but t73 has no row: the file does not cover the 74, so the slot stays unused."""
    rc, log = run(tmp_path, ["KernelWorkerStatus.COMPLETE"], rows(35)[:-1])
    assert rc == 3 and "decision: FAIL 35 73 0 8760 1" in log and "SKIPPED: slot left unused" in log and "SUBMIT" not in log, log


def test_an_off_list_row_does_not_stand_in_for_a_missing_valid_id(tmp_path):
    swapped = rows(35)[:-1] + extra_rows(1)                       # 74 rows in all, but x0 instead of t73
    rc, log = run(tmp_path, ["KernelWorkerStatus.COMPLETE"], swapped)
    assert rc == 3 and "decision: FAIL 35 73 0 8760 1" in log and "SUBMIT" not in log, log


def test_a_repeated_valid_id_counts_once(tmp_path):
    rc, log = run(tmp_path, ["KernelWorkerStatus.COMPLETE"], rows(28) + [dict(rows(28)[0])])   # t0 twice, solved both times
    assert rc == 3 and "decision: FAIL 28 74 0 8880 0" in log, log


def test_the_repo_ids_file_lists_74_distinct_tasks():
    """The harness mimics data/kaggle_valid_ids.txt; the script resolves the real one as ../data/ from its own directory."""
    ids = (ROOT / "data" / "kaggle_valid_ids.txt").read_text().split()
    assert len(ids) == len(set(ids)) == 74
    assert 'VALID_IDS=${DECIDE_IDS_FILE:-$HERE/../data/kaggle_valid_ids.txt}' in SCRIPT.read_text()


def test_missing_ids_file_aborts_at_arm_time(tmp_path):
    sdir, kaggle = harness(tmp_path, ["KernelWorkerStatus.COMPLETE"], rows(31))
    (tmp_path / "data" / "kaggle_valid_ids.txt").unlink()
    log = tmp_path / "log.txt"
    e = dict(os.environ, KAGGLE_BIN=str(kaggle), SUBMIT_LOG=str(log), SUBMIT_TARGET_EPOCH="0")
    p = subprocess.run(["bash", str(sdir / "decide_or_skip.sh"), "e", "c", "0001", "29", "m"], capture_output=True, text=True, env=e, timeout=30)
    assert p.returncode == 2 and "ABORT: valid ids file not found or empty" in log.read_text() and "decision" not in log.read_text()


# ------------------------------------------------------------------------------------ the output download is retried
def test_a_failed_output_download_is_retried_and_the_decision_follows(tmp_path):
    rc, log = run(tmp_path, ["KernelWorkerStatus.COMPLETE"], rows(31), fail_outputs=2)
    assert rc == 0 and "decision: PASS 31 74 0 8880 0" in log and "SUBMIT g4agent-v5h2-think" in log, log
    assert output_calls(tmp_path) == 3 and "(try 1 of 3)" in log and "(try 2 of 3)" in log and "(try 3 of 3)" not in log, log


def test_three_failed_downloads_leave_the_slot_unused_after_exactly_three_tries(tmp_path):
    rc, log = run(tmp_path, ["KernelWorkerStatus.COMPLETE"], rows(31), fail_outputs=9)
    assert rc == 3 and "decision: NO_RESULTS 0 0 0 0 74" in log and "SUBMIT" not in log, log
    assert output_calls(tmp_path) == 3 and log.count("output download of g4-eval74-v4 failed") == 3 and "(try 3 of 3)" in log, log


def test_a_clean_download_is_tried_once(tmp_path):
    rc, log = run(tmp_path, ["KernelWorkerStatus.COMPLETE"], rows(31))
    assert rc == 0 and output_calls(tmp_path) == 1 and "output download" not in log, log


# ------------------------------------------------- no verdict from a partial download, and the last row per id wins (2026-10-29)
CRASH_T3 = {"id": "t3", "resolved": False, "err": "Tool 'view.py' not found.", "secs": 120.0}


def test_a_truncated_file_left_by_failed_downloads_is_no_results_not_judged(tmp_path):
    """A download that dies half way can leave a truncated results.jsonl while kaggle exits non-zero. After three failed tries
    that file must not reach the judge (it used to: a JSONDecodeError traceback gave an empty verdict)."""
    rc, log = run(tmp_path, ["KernelWorkerStatus.COMPLETE"], rows(31), fail_outputs=9, env={"FAKE_PARTIAL": "1"})
    left = tmp_path / "out" / "results.jsonl"
    assert left.read_text().startswith('{"id": "t0", "resol'), "the fake did not leave a truncated file behind"
    assert rc == 3 and "decision: NO_RESULTS 0 0 0 0 74" in log and "SKIPPED: slot left unused (NO_RESULTS" in log and "SUBMIT" not in log, log
    assert output_calls(tmp_path) == 3 and "Traceback" not in log, log


@pytest.mark.parametrize("body", [
    pytest.param(lambda: "".join(json.dumps(r) + "\n" for r in rows(35)).encode() + b'{"id": "t73", "resol', id="truncated-last-line"),
    pytest.param(lambda: b"[1, 2]\n" + "".join(json.dumps(r) + "\n" for r in rows(35)).encode(), id="a-row-that-is-not-an-object"),
    pytest.param(lambda: b'\xff\xfe{"id": "t0"}\n', id="not-utf-8"),
])
def test_a_results_file_that_is_not_valid_json_lines_is_no_results(tmp_path, body):
    """The download itself succeeded (one try), but the file cannot be read as JSON lines: NO_RESULTS, never a crash of the judge."""
    (tmp_path / "results.jsonl").write_bytes(body())                # harness() copies it when it is given no rows
    rc, log = run(tmp_path, ["KernelWorkerStatus.COMPLETE"], None)
    assert rc == 3 and "decision: NO_RESULTS 0 0 0 0 74" in log and "SUBMIT" not in log and "Traceback" not in log, log
    assert output_calls(tmp_path) == 1, log


def test_the_last_row_for_an_id_wins_so_a_superseded_crash_row_does_not_count(tmp_path):
    """t3 appears twice: a crash row first, then its real (solved) row. One row per id is judged and the later one wins."""
    rc, log = run(tmp_path, ["KernelWorkerStatus.COMPLETE"], [CRASH_T3] + rows(31))
    assert rc == 0 and "decision: PASS 31 74 0 8880 0" in log and "SUBMIT g4agent-v5h2-think" in log, log


def test_the_last_row_for_an_id_wins_also_when_it_is_the_crash(tmp_path):
    """The other order: t3 solved first, then a crash row. The later row wins, so the crash counts and the slot is skipped
    even though 30 of 74 solved is above the minimum of 29."""
    rc, log = run(tmp_path, ["KernelWorkerStatus.COMPLETE"], rows(31) + [CRASH_T3])
    assert rc == 3 and "decision: FAIL 30 74 1 8880 0" in log and "SUBMIT" not in log, log
