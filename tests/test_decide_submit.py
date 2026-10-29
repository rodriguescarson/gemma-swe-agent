"""Pre-registered nightly choice (2026-09-29): candidate only if its faithful L4 eval COMPLETED with >= MIN solved and no crash rows."""
import datetime, json, os, pathlib, subprocess, pytest
ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "decide_submit.sh"
UTC = datetime.timezone.utc
NOON = int(datetime.datetime(2026, 10, 29, 12, 0, tzinfo=UTC).timestamp())
LATE = int(datetime.datetime(2026, 10, 29, 23, 50, tzinfo=UTC).timestamp())       # inside the last 15 minutes of the UTC day


def _fake_clock(tmp, now_epoch):
    """PATH for a fixed clock: `date -u +%s` reports now_epoch, every other form of date is the real one, and `sleep` returns at once
    (the eval wait loop sleeps 600 s between status reads)."""
    b = tmp / "fakebin"; b.mkdir(exist_ok=True)
    (b / "date").write_text(f'#!/bin/bash\n[ "$1 $2" = "-u +%s" ] && {{ echo {now_epoch}; exit 0; }}\nexec /bin/date "$@"\n')
    (b / "sleep").write_text("#!/bin/bash\nexit 0\n")
    for f in b.iterdir():
        f.chmod(0o755)
    return {"PATH": f"{b}:{os.environ['PATH']}"}


def _run(tmp, status, rows, now=None, submit_at_rc=None):
    """status: one KernelWorkerStatus name for every read, or a list consumed one per read (the last one repeats). now: a fixed UTC epoch.
    submit_at_rc: replace submit_at.sh with a stub that exits with it (the script execs it, so it must be the script's own status)."""
    (tmp / "res.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    seq = [status] if isinstance(status, str) else list(status)
    (tmp / "statuses").write_text("\n".join(seq) + "\n")
    calls = tmp / "calls.txt"; fake = tmp / "kaggle"
    fake.write_text(f"""#!/bin/bash
echo "$@" >> {calls}
if [ "$1" = kernels ] && [ "$2" = status ]; then
  n=$(cat {tmp}/n 2>/dev/null || echo 0); n=$((n + 1)); echo $n > {tmp}/n
  s=$(sed -n "${{n}}p" {tmp}/statuses); [ -z "$s" ] && s=$(tail -1 {tmp}/statuses)
  echo "x has status \\"KernelWorkerStatus.$s\\""; exit 0
fi
if [ "$1" = kernels ] && [ "$2" = output ]; then d=""; while [ $# -gt 0 ]; do [ "$1" = -p ] && d=$2; shift; done; cp {tmp}/res.jsonl "$d/results.jsonl"; exit 0; fi
if [ "$1" = kernels ] && [ "$2" = list ]; then printf 'ref t\\n-- --\\n'; exit 0; fi
if [ "$2" = submissions ]; then
  echo 'ref,fileName,date,description,status'
  while IFS= read -r m; do echo "9,submission.zip,d,\\"$m\\",SubmissionStatus.PENDING"; done < {tmp}/subs
  exit 0
fi
if [ "$2" = submit ]; then while [ $# -gt 0 ]; do [ "$1" = -m ] && echo "$2" >> {tmp}/subs; shift; done; fi
echo "Successfully submitted"
""")
    fake.chmod(0o755)
    (tmp / "subs").write_text("")     # a submission shows up in the listing, as on Kaggle: submit_at.sh exits 0 only when it can see its tag
    (tmp / "submit_at.sh").write_text((ROOT / "scripts/submit_at.sh").read_text() if submit_at_rc is None else
                                     f'#!/bin/bash\necho "STUB $@" >> {tmp}/stub_calls.txt\nexit {submit_at_rc}\n')
    script = tmp / "decide_submit.sh"; script.write_text(SCRIPT.read_text())
    env = dict(os.environ, KAGGLE_BIN=str(fake), SUBMIT_LOG=str(tmp / "log.txt"), SUBMIT_TARGET_EPOCH="0", DECIDE_OUT=str(tmp / "out"),
               **(_fake_clock(tmp, now) if now else {}))
    p = subprocess.run(["bash", str(script), "g4-l4-v10-1", "g4agent-v10", "g4agent-sub3", "0000", "29", "sub6: v10.1", "sub6: v4"],
                       env=env, timeout=60)
    assert p.returncode == (submit_at_rc or 0), p.stdout + p.stderr
    subs = [l for l in calls.read_text().splitlines() if l.startswith("competitions submit ")]
    return subs, (tmp / "log.txt").read_text()


def rows(solved, total=74, crash_err=None, secs=150.0):
    out = [{"id": f"t{i}", "resolved": i < solved, "err": None, "secs": secs} for i in range(total)]
    if crash_err: out[-1]["err"] = crash_err
    return out


def test_candidate_when_eval_passes(tmp_path):
    subs, log = _run(tmp_path, "COMPLETE", rows(30))
    assert len(subs) == 1 and "carsonrodrigues/g4agent-v10 " in subs[0] + " " and "sub6: v10.1" in subs[0]

def test_fallback_when_below_threshold(tmp_path):
    subs, log = _run(tmp_path, "COMPLETE", rows(28))
    assert len(subs) == 1 and "g4agent-sub3" in subs[0] and "FAIL 28 74 0" in log

def test_fallback_on_any_crash_row(tmp_path):
    subs, log = _run(tmp_path, "COMPLETE", rows(40, crash_err="Sandbox execution error: Tool 'view.py' not found."))
    assert "g4agent-sub3" in subs[0] and "FAIL 40 74 1" in log

def test_fallback_when_eval_errored(tmp_path):
    subs, log = _run(tmp_path, "ERROR", rows(40))
    assert "g4agent-sub3" in subs[0] and "eval status KernelWorkerStatus.ERROR" in log


def test_fallback_when_too_slow(tmp_path):
    subs, log = _run(tmp_path, "COMPLETE", rows(40, secs=200.0))      # 74 x 200 = 14,800 s > 13,158
    assert "g4agent-sub3" in subs[0] and "FAIL 40 74 0 14800" in log


def test_the_eval_wait_runs_to_the_end_of_the_utc_day_even_with_target_epoch_zero(tmp_path):
    # the day end came from TARGET, so SUBMIT_TARGET_EPOCH=0 put it in 1970: the first non-COMPLETE status ended the wait and the fallback
    # was submitted over an eval kernel that was still running (decide_or_skip.sh already used the later of TARGET and now)
    subs, log = _run(tmp_path, ["RUNNING", "RUNNING", "COMPLETE"], rows(30), now=NOON)
    assert log.count("waiting for eval kernel") == 2 and "decision: g4agent-v10 (eval PASS 30 74 0" in log
    assert len(subs) == 1 and "carsonrodrigues/g4agent-v10 " in subs[0] + " "


def test_the_eval_wait_ends_fifteen_minutes_before_the_end_of_the_utc_day(tmp_path):
    subs, log = _run(tmp_path, ["RUNNING"], rows(40), now=LATE)
    assert "waiting for eval kernel" not in log and "eval status KernelWorkerStatus.RUNNING" in log
    assert len(subs) == 1 and "g4agent-sub3" in subs[0]


@pytest.mark.parametrize("submit_rc", [1, 3, 4])
def test_the_script_exits_with_submit_ats_status(tmp_path, submit_rc):
    # exec: a give-up (1), an unconfirmed submission (3) or a scoring submission at the deadline (4) is the chain's status, never 0
    subs, log = _run(tmp_path, "COMPLETE", rows(30), submit_at_rc=submit_rc)
    stub = (tmp_path / "stub_calls.txt").read_text().splitlines()
    assert len(stub) == 1 and stub[0].startswith("STUB g4agent-v10 0000 sub6: v10.1")
