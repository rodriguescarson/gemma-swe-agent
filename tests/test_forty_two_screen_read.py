"""scripts/forty_two/screen_read.py applies the pre-registered v13 box-screen rule (docs/forty_two/BOX_SCREEN.md) mechanically."""
import json, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "forty_two"))
import screen_read as sr  # noqa: E402

IDS = (ROOT / "data" / "kaggle_valid_ids.txt").read_text().split()
NEVER = (ROOT / "data" / "never_solved_box5_ids.txt").read_text().split()
OTHERS = [i for i in IDS if i not in NEVER]


def write_run(d: Path, solved: set, trace_tools=None):
    (d / "results" / "traces").mkdir(parents=True)
    with open(d / "results.jsonl", "w") as f:
        for i in IDS:
            f.write(json.dumps({"id": i, "resolved": i in solved, "exit": 0 if i in solved else 1, "err": None, "secs": 100, "patch": "x"}) + "\n")
    steps = [{"step_id": 1, "source": "user", "extra": {"event_type": "task_prompt", "timestamp": 1000.0, "elapsed_s": 0.5}}]
    for k, (name, args, obs, dur) in enumerate(trace_tools or [], start=1):
        ts = 1000.0 + 10 * k
        steps.append({"step_id": k + 1, "source": "agent", "extra": {"timestamp": ts, "elapsed_s": 10 * k},
                      "tool_calls": [{"function_name": name, "arguments": args, "extra": {"timestamp": ts}}],
                      "observation": {"content": obs, "extra": {"timestamp": ts + dur}}})
    (d / "results" / "traces" / f"trace_{IDS[0]}.json").write_text(json.dumps({"steps": steps}))
    return d


EDIT = ("run_command", {"command": "python3 - <<'EDIT'\nprint(1)\nEDIT"}, '{"status": "ok", "stdout": "edited x"}', 0.2)


@pytest.mark.parametrize("ref_n,new,the42,verdict", [
    (28, 30, 2, "PASS"),          # +2 net, 2 of the 42
    (28, 30, 1, "NO EVIDENCE"),   # the 42 bar not met
    (28, 29, 2, "NO EVIDENCE"),   # net +1
    (28, 25, 0, "FAIL"),          # solved <= 25
    (28, 26, 0, "NO EVIDENCE"),
])
def test_verdicts(tmp_path, ref_n, new, the42, verdict):
    ref = set(OTHERS[:ref_n])
    keep = set(OTHERS[:new - the42])
    run = keep | set(NEVER[:the42])
    r = sr.read(write_run(tmp_path / "run", run, [EDIT]), write_run(tmp_path / "ref", ref))
    assert (r["solved"], len(r["the_42_solved"]), r["verdict"]) == (new, the42, verdict), r


def test_a_run_with_v12s_edit_tool_or_a_long_command_is_invalid(tmp_path):
    ok_edit = ("edit_file", {"filepath": "a.py", "old_string": "a", "new_string": "b"}, '{"status": "ok", "filepath": "a.py"}', 0.1)
    r = sr.read(write_run(tmp_path / "a", set(OTHERS[:30]), [ok_edit]), write_run(tmp_path / "ref", set(OTHERS[:28])))
    assert r["verdict"] == "INVALID"
    long_cmd = ("run_command", {"command": "python3 x.py"}, '{"status": "error", "error_type": "TimeoutExceeded"}', 180.0)
    r = sr.read(write_run(tmp_path / "b", set(OTHERS[:30]), [long_cmd]), write_run(tmp_path / "ref2", set(OTHERS[:28])))
    assert r["verdict"] == "INVALID" and r["counters"]["long_commands_ge_61s"] == 1
    tried = ("edit_file", {"filepath": "a.py"}, '{"status": "error", "error_type": "ValueError", "error": "Tool not found"}', 0.0)
    r = sr.read(write_run(tmp_path / "c", set(OTHERS[:28]) | set(NEVER[:2]), [EDIT, tried]), write_run(tmp_path / "ref3", set(OTHERS[:28])))
    assert r["verdict"] == "PASS" and r["counters"]["edit_or_write_attempts"] == 1   # an attempt at a dropped tool is reported only


def test_sign_test():
    assert sr.sign_p(0, 0) == 1.0 and sr.sign_p(5, 7) == pytest.approx(0.774, abs=1e-3) and sr.sign_p(8, 0) == pytest.approx(0.0078, abs=1e-4)
