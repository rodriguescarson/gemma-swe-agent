"""scripts/collect/merge_results.py: after a resumed pass, fold the pre-run copy of task_results.jsonl back in. The
harness (swegemma/results.py) appends per task but rewrites the file at the end with only that run's tasks, so a
resumed pass silently drops every earlier row (2026-10-03: resample_A s1 went from 32 rows to 17). Keep one row per
instance_id, the newest run's row winning. Written before the script."""
import json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "collect" / "merge_results.py"


def test_prev_rows_restored_new_rows_win(tmp_path):
    d = tmp_path / "s1"; d.mkdir()
    prev = [{"instance_id": "a", "resolved": "True"}, {"instance_id": "b", "resolved": "False", "error": "x"}, {"instance_id": "c", "resolved": "False"}]
    new = [{"instance_id": "c", "resolved": "True"}, {"instance_id": "d", "resolved": "False"}]
    (d / "task_results.prev.jsonl").write_text("".join(json.dumps(r) + "\n" for r in prev))
    (d / "task_results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in new))
    r = subprocess.run([sys.executable, str(SCRIPT), str(d)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    rows = {json.loads(l)["instance_id"]: json.loads(l) for l in (d / "task_results.jsonl").read_text().splitlines()}
    assert set(rows) == {"a", "b", "c", "d"} and rows["c"]["resolved"] == "True"
    assert "4 rows" in r.stdout and not (d / "task_results.prev.jsonl").exists()


def test_no_prev_is_a_noop(tmp_path):
    d = tmp_path / "s1"; d.mkdir()
    (d / "task_results.jsonl").write_text(json.dumps({"instance_id": "a", "resolved": "True"}) + "\n")
    r = subprocess.run([sys.executable, str(SCRIPT), str(d)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "no prev" in r.stdout and (d / "task_results.jsonl").read_text().count("\n") == 1
