"""train/merge_rows.py: merge several row files into one, dropping exact (prompt, completion) duplicates, keeping the
first occurrence; used by stitch.sh to fold frozen row files in (2026-10-03: a resumed pass truncated its results file,
so verdict-bearing rows that existed at the 15:53 stitch would otherwise be lost). Written before the script."""
import json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "train" / "merge_rows.py"


def test_merge_dedups_and_keeps_order(tmp_path):
    a = tmp_path / "a.jsonl"; b = tmp_path / "b.jsonl"; out = tmp_path / "out.jsonl"
    r1 = {"prompt": "p1", "completion": "c1", "meta": {"task": "t1"}}
    r2 = {"prompt": "p2", "completion": "c2", "meta": {"task": "t2"}}
    r3 = {"prompt": "p3", "completion": "c3", "meta": {"task": "t3"}}
    a.write_text(json.dumps(r1) + "\n" + json.dumps(r2) + "\n")
    b.write_text(json.dumps(r2) + "\n" + json.dumps(r3) + "\n" + json.dumps(dict(r1, meta={"task": "other"})) + "\n")
    r = subprocess.run([sys.executable, str(SCRIPT), str(a), str(b), "--out", str(out)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    rows = [json.loads(l) for l in out.read_text().splitlines()]
    assert [x["meta"]["task"] for x in rows] == ["t1", "t2", "t3"]
    assert "3 rows" in r.stdout and "2 duplicates" in r.stdout


def test_missing_input_is_skipped_not_fatal(tmp_path):
    a = tmp_path / "a.jsonl"; a.write_text(json.dumps({"prompt": "p", "completion": "c", "meta": {}}) + "\n")
    out = tmp_path / "out.jsonl"
    r = subprocess.run([sys.executable, str(SCRIPT), str(a), str(tmp_path / "nope.jsonl"), "--out", str(out)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and out.read_text().count("\n") == 1 and "skipped" in r.stdout
