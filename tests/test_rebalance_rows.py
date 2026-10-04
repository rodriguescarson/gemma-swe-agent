"""train/rebalance_rows.py: reshape build_sft rows for v11b (GA_PROBE.md V-1 lessons): drop exact repeated calls per
task, cap one tool's share, cap rows per task (text replies are never dropped by the caps), hold out tasks to a
separate file, deterministic by seed, with a before/after report. Written before the script."""
import json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "train" / "rebalance_rows.py"


def _row(task, tool, comp, stage="fixer", cont=True, p=None):
    return {"prompt": p or f"<bos>{task}-{comp}", "completion": comp, "meta": {"task": task, "stage": stage, "tool": tool, "continuation": cont}}


def _write(tmp, rows):
    f = tmp / "rows.jsonl"; f.write_text("".join(json.dumps(r) + "\n" for r in rows)); return f


def _run(tmp, src, *flags):
    out = tmp / "out.jsonl"; rep = tmp / "rep.json"
    r = subprocess.run([sys.executable, str(SCRIPT), str(src), "--out", str(out), "--report", str(rep), "--seed", "1", *flags],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-1500:]
    return [json.loads(l) for l in out.read_text().splitlines()], json.loads(rep.read_text())


def test_drop_repeats_keeps_first_occurrence_per_task(tmp_path):
    rows = [_row("t1", "read_file", "<|tool_call>read_file(a)<|tool_response>", p="<bos>p1"),
            _row("t1", "read_file", "<|tool_call>read_file(a)<|tool_response>", p="<bos>p2"),      # same call again later
            _row("t2", "read_file", "<|tool_call>read_file(a)<|tool_response>", p="<bos>p3"),      # other task: kept
            _row("t1", None, "done<turn|>", cont=False, p="<bos>p4")]
    out, rep = _run(tmp_path, _write(tmp_path, rows), "--drop-repeats")
    assert len(out) == 3 and rep["dropped"]["repeats"] == 1 and [r["prompt"] for r in out] == ["<bos>p1", "<bos>p3", "<bos>p4"]


def test_tool_share_cap_downsamples_only_that_tool_and_never_replies(tmp_path):
    rows = [_row("t1", "read_file", f"<|tool_call>read_file({i})<|tool_response>") for i in range(8)]
    rows += [_row("t1", "run_command", f"<|tool_call>run_command({i})<|tool_response>") for i in range(2)]
    rows += [_row("t1", None, "reply<turn|>", cont=False)]
    out, rep = _run(tmp_path, _write(tmp_path, rows), "--max-tool-share", "read_file=0.25")
    n_read = sum(1 for r in out if r["meta"]["tool"] == "read_file")
    assert n_read <= 0.25 * len(out) + 1e-9 and sum(1 for r in out if r["meta"]["tool"] is None) == 1
    assert sum(1 for r in out if r["meta"]["tool"] == "run_command") == 2 and rep["dropped"]["tool_share"] == 8 - n_read


def test_per_task_cap_and_holdout_and_determinism(tmp_path):
    rows = [_row("t1", "run_command", f"c{i}") for i in range(10)] + [_row("t1", None, "r<turn|>", cont=False)]
    rows += [_row("t2", "run_command", f"d{i}") for i in range(3)] + [_row("t3", "run_command", "e0")]
    hold = tmp_path / "hold.txt"; hold.write_text("t3\n")
    src = _write(tmp_path, rows)
    out1, rep1 = _run(tmp_path, src, "--max-per-task", "4", "--holdout-tasks", str(hold), "--holdout-out", str(tmp_path / "hold.jsonl"))
    out2, rep2 = _run(tmp_path, src, "--max-per-task", "4", "--holdout-tasks", str(hold), "--holdout-out", str(tmp_path / "hold.jsonl"))
    assert [r["completion"] for r in out1] == [r["completion"] for r in out2]          # seeded
    t1 = [r for r in out1 if r["meta"]["task"] == "t1"]
    assert len(t1) == 4 and any(r["meta"]["tool"] is None for r in t1)                  # cap keeps the reply row
    assert not any(r["meta"]["task"] == "t3" for r in out1) and (tmp_path / "hold.jsonl").read_text().count("\n") == 1
    assert rep1["after"]["rows"] == len(out1) and rep1["before"]["rows"] == len(rows) and rep1["after"]["tasks"] == 2
