"""or_race_summary: paired counts, sign test, missing rows flagged."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "pallets"))
import or_race_summary as s  # noqa: E402


def _arm(d, name, res):
    (d / f"pl_{name}").mkdir()
    (d / f"pl_{name}" / "task_results.jsonl").write_text("\n".join(json.dumps(
        {"instance_id": i, "resolved": str(v), "agent_patch_size": "10", "error": "None", "duration_seconds": "100"})
        for i, v in res.items()))


def test_paired_counts_and_missing(tmp_path):
    (tmp_path / "ids.txt").write_text("a b c d")
    _arm(tmp_path, "v4", {"a": True, "b": False, "c": True, "d": False})
    _arm(tmp_path, "v10", {"a": True, "b": True, "c": False})
    out = s.main(str(tmp_path), "v4", "v10")
    assert "v4: solved 2/4" in out and "v10: solved 2/4 (rows 3)" in out
    assert "v10 wins 1, v4 wins 1, both 1" in out and "INCOMPLETE: 1" in out


def test_sign_p():
    assert s.sign_p(0, 0) == 1.0 and abs(s.sign_p(10, 0) - 2 / 1024) < 1e-12 and s.sign_p(3, 3) == 1.0
