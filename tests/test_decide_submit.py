"""Pre-registered nightly choice (2026-09-29): candidate only if its faithful L4 eval COMPLETED with >= MIN solved and no crash rows."""
import json, os, pathlib, subprocess, pytest
ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "decide_submit.sh"


def _run(tmp, status, rows):
    (tmp / "res.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    calls = tmp / "calls.txt"; fake = tmp / "kaggle"
    fake.write_text(f"""#!/bin/bash
echo "$@" >> {calls}
if [ "$1" = kernels ] && [ "$2" = status ]; then echo 'x has status "KernelWorkerStatus.{status}"'; exit 0; fi
if [ "$1" = kernels ] && [ "$2" = output ]; then d=""; while [ $# -gt 0 ]; do [ "$1" = -p ] && d=$2; shift; done; cp {tmp}/res.jsonl "$d/results.jsonl"; exit 0; fi
if [ "$1" = kernels ] && [ "$2" = list ]; then printf 'ref t\\n-- --\\n'; exit 0; fi
if [ "$2" = submissions ]; then echo 'ref,fileName,date,description,status'; exit 0; fi
echo "Successfully submitted"
""")
    fake.chmod(0o755)
    (tmp / "submit_at.sh").write_text((ROOT / "scripts/submit_at.sh").read_text())
    script = tmp / "decide_submit.sh"; script.write_text(SCRIPT.read_text())
    env = dict(os.environ, KAGGLE_BIN=str(fake), SUBMIT_LOG=str(tmp / "log.txt"), SUBMIT_TARGET_EPOCH="0", DECIDE_OUT=str(tmp / "out"))
    subprocess.run(["bash", str(script), "g4-l4-v10-1", "g4agent-v10", "g4agent-sub3", "0000", "29", "sub6: v10.1", "sub6: v4"],
                   env=env, timeout=60, check=True)
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
