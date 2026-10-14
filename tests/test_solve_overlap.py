"""scripts/solve_overlap.py: which tasks each run solved, compared across runs (Carson, 2026-10-14: "are all solved the same? or
uniquely we have more solved?"). Written before the script."""
import json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import solve_overlap  # noqa: E402


def write(d, rows):
    d.mkdir(parents=True)
    (d / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return d


def runs(tmp_path):
    ids = ["t1", "t2", "t3", "t4", "t5"]
    a = write(tmp_path / "a", [{"id": i, "resolved": i in ("t1", "t2", "t3")} for i in ids])
    b = write(tmp_path / "b", [{"id": i, "resolved": i in ("t1", "t2")} for i in ids])
    c = write(tmp_path / "c", [{"id": i, "resolved": i in ("t1", "t4")} for i in ids] + [{"id": "t9", "resolved": True}])
    return a, b, c


def test_core_never_flaky_union_and_unique(tmp_path):
    a, b, c = runs(tmp_path)
    r = solve_overlap.overlap({"a": solve_overlap.load(a), "b": solve_overlap.load(b), "c": solve_overlap.load(c / "results.jsonl")})
    assert r["n"] == 5 and r["dropped"] == {"c": ["t9"]}                  # only ids every run has
    assert r["core"] == ["t1"] and r["never"] == ["t5"] and r["union"] == 4
    assert r["flaky"] == ["t2", "t3", "t4"] and r["by_count"] == {0: 1, 1: 2, 2: 1, 3: 1}
    assert r["runs"]["a"] == {"solved": 3, "unique": ["t3"]} and r["runs"]["b"] == {"solved": 2, "unique": []}
    assert r["runs"]["c"] == {"solved": 2, "unique": ["t4"]}
    assert r["pairs"][("a", "c")] == {"both": 1, "a_only": 2, "b_only": 1, "union": 4}


def test_a_partial_run_is_compared_on_the_ids_it_has_and_the_last_row_per_id_wins(tmp_path):
    a, b, _ = runs(tmp_path)
    p = write(tmp_path / "p", [{"id": "t1", "resolved": False}, {"id": "t2", "resolved": True}, {"id": "t1", "resolved": True}])
    r = solve_overlap.overlap({"a": solve_overlap.load(a), "b": solve_overlap.load(b), "p": solve_overlap.load(p)})
    assert r["n"] == 2 and r["runs"]["p"]["solved"] == 2 and r["dropped"]["a"] == ["t3", "t4", "t5"]


def test_cli_prints_the_tables_and_focus_lists_tasks_by_name(tmp_path):
    a, b, c = runs(tmp_path)
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "solve_overlap.py"), str(a), str(b), str(c), "--focus", "c"],
                         capture_output=True, text=True, check=True).stdout
    assert "tasks compared 5" in out and "union 4" in out and "core 1" in out and "never 1" in out
    assert "c only: t4" in out and "c missed, solved by >= 2 others: t2" in out
