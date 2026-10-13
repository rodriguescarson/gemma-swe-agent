"""scripts/box_p4_gate.py: the full-population gate a box 74-task run must pass before the Mac submits (GAPS "sub15b
pre-registration" (b), 2026-10-13): every public id has a row, 0 crash rows (decide_or_skip.sh's crash classes), 0 errored
rows (p4_judge.py's definition: an err that is neither the session timeout nor a budget stop), solved >= the floor.
Written before the script."""
import json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import box_p4_gate as G  # noqa: E402

IDS = [f"t{i}" for i in range(74)]


def rows(solved=30, extra=None):
    out = [{"id": t, "resolved": i < solved, "secs": 200.0, "err": None if i % 3 else "Agent exceeded session timeout (5.0 min)"} for i, t in enumerate(IDS)]
    return out + (extra or [])


def test_pass_and_each_failure_reason():
    ok, rep = G.judge(rows(), IDS, floor=26)
    assert ok and rep["solved"] == 30 and rep["rows"] == 74 and rep["missing"] == [] and rep["crash_rows"] == 0 and rep["errored_rows"] == 0
    assert rep["cap_hits"] == 25                                         # timeouts are allowed and counted
    assert not G.judge(rows(solved=25), IDS, floor=26)[0]
    r = rows(); r[5]["err"] = "Tool 'view' not found."
    ok, rep = G.judge(r, IDS, floor=26); assert not ok and rep["crash_rows"] == 1
    r = rows(); r[7]["err"] = "RuntimeError: sandbox died"
    ok, rep = G.judge(r, IDS, floor=26); assert not ok and rep["errored_rows"] == 1 and rep["crash_rows"] == 0
    r = rows(); r[8]["err"] = "tool call budget exhausted (40)"
    assert G.judge(r, IDS, floor=26)[0]                                  # a budget stop is neither a crash nor an error
    ok, rep = G.judge(rows()[:-1], IDS, floor=26); assert not ok and rep["missing"] == ["t73"]


def test_last_row_per_id_wins_and_unknown_ids_are_ignored():
    r = rows(solved=25) + [{"id": "t40", "resolved": True, "secs": 100.0, "err": None}, {"id": "zz", "resolved": True, "secs": 1, "err": None}]
    ok, rep = G.judge(r, IDS, floor=26)
    assert ok and rep["solved"] == 26 and rep["rows"] == 74


def test_cli_prints_one_line_and_exits_by_verdict(tmp_path):
    f = tmp_path / "results.jsonl"; f.write_text("".join(json.dumps(x) + "\n" for x in rows()))
    ids = tmp_path / "ids.txt"; ids.write_text("\n".join(IDS) + "\n")
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "box_p4_gate.py"), str(f), "--ids", str(ids), "--floor", "26"], capture_output=True, text=True)
    assert p.returncode == 0 and p.stdout.startswith("PASS solved 30/74") and "crash 0" in p.stdout and "errored 0" in p.stdout, p.stdout + p.stderr
    f.write_text("".join(json.dumps(x) + "\n" for x in rows(solved=10)))
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "box_p4_gate.py"), str(f), "--ids", str(ids), "--floor", "26"], capture_output=True, text=True)
    assert p.returncode == 1 and p.stdout.startswith("FAIL solved 10/74")
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "box_p4_gate.py"), str(tmp_path / "none.jsonl"), "--ids", str(ids)], capture_output=True, text=True)
    assert p.returncode == 1 and p.stdout.startswith("FAIL no results")
