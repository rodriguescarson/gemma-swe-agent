"""scripts/decide_or_skip.sh: the slot decision with no fallback (2026-10-10, sub13 = v5h2-think). A fake kaggle binary plays
Kaggle (status, output), a stub submit_at.sh records what would have been submitted. PASS submits the candidate with the
message; FAIL (too few solved, a crash row, too many seconds) and a non-COMPLETE eval leave the slot unused with exit 3 and a
SKIPPED line; a missing results file is NO_RESULTS; the eval wait loop polls until COMPLETE. Written before the script was armed."""
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


def harness(tmp_path, statuses, results):
    """A scripts/ dir with decide_or_skip.sh, a stub submit_at.sh and a fake kaggle; statuses are consumed in order."""
    sdir = tmp_path / "scripts"; sdir.mkdir()
    shutil.copy(SCRIPT, sdir / "decide_or_skip.sh")
    (sdir / "submit_at.sh").write_text("#!/bin/bash\necho \"SUBMIT $1 at=$2 msg=$3 version=${KERNEL_VERSION:-}\" >> \"$SUBMIT_LOG\"\nexit 0\n")
    (sdir / "submit_at.sh").chmod(0o755)
    seq = tmp_path / "statuses.txt"; seq.write_text("\n".join(statuses) + "\n")
    res = tmp_path / "results.jsonl"
    if results is not None:
        res.write_text("".join(json.dumps(r) + "\n" for r in results))
    kaggle = tmp_path / "kaggle"
    kaggle.write_text(f"""#!/bin/bash
# fake kaggle: 'kernels status X' pops the next status; 'kernels output X -p DIR' copies results.jsonl into DIR
if [ "$1 $2" = "kernels status" ]; then
  s=$(head -n 1 {seq}); [ -z "$s" ] && s=KernelWorkerStatus.COMPLETE
  tail -n +2 {seq} > {seq}.tmp; [ -s {seq}.tmp ] && mv {seq}.tmp {seq} || echo "$s" > {seq}
  echo "carsonrodrigues/$3 has status \\"$s\\""; exit 0
fi
if [ "$1 $2" = "kernels output" ]; then
  for ((i=1;i<=$#;i++)); do [ "${{!i}}" = "-p" ] && j=$((i+1)) && d=${{!j}}; done
  mkdir -p "$d"; [ -f {res} ] && cp {res} "$d/results.jsonl"; exit 0
fi
echo "fake kaggle: unknown $*" >&2; exit 1
""")
    kaggle.chmod(kaggle.stat().st_mode | stat.S_IEXEC)
    return sdir, kaggle


NOON = int(datetime.datetime(2026, 10, 29, 12, 0, tzinfo=datetime.timezone.utc).timestamp())


def fake_clock(tmp_path, now_epoch=NOON):
    """PATH for a fixed clock: `date -u +%s` reports now_epoch, every other form of date is the real one. The script waits for
    the eval kernel only until 15 minutes before the end of the UTC day, so with the wall clock the wait-loop test failed from
    23:45 to 00:00 UTC (the loop saw the day as over and skipped at the first RUNNING status)."""
    b = tmp_path / "fakebin"; b.mkdir(exist_ok=True)
    (b / "date").write_text(f'#!/bin/bash\n[ "$1 $2" = "-u +%s" ] && {{ echo {now_epoch}; exit 0; }}\nexec /bin/date "$@"\n')
    (b / "date").chmod(0o755)
    return {"PATH": f"{b}:{os.environ['PATH']}"}


def run(tmp_path, statuses, results, min_solved=29, env=None, now_epoch=NOON):
    sdir, kaggle = harness(tmp_path, statuses, results)
    log = tmp_path / "log.txt"
    e = dict(os.environ, KAGGLE_BIN=str(kaggle), SUBMIT_LOG=str(log), DECIDE_OUT=str(tmp_path / "out"), SUBMIT_TARGET_EPOCH="0",
             DECIDE_POLL_S="0", KERNEL_VERSION="1", **fake_clock(tmp_path, now_epoch), **(env or {}))
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
