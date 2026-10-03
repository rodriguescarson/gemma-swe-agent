"""scripts/collect/solved_ids.py: the set of target tasks any collection pass has solved (for resampling), and the
unsolved remainder (for coverage). Written before the script."""
import json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "collect" / "solved_ids.py"


def _pass(root, tag, rows):
    d = root / "eval" / "collect" / tag / "s1"; d.mkdir(parents=True)
    (d / "task_results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_solved_and_remaining(tmp_path):
    (tmp_path / "target.txt").write_text("a\nb\nc\nd\n")
    (tmp_path / "harness_ids.txt").write_text("a\nb\nc\n")          # d is not packed
    _pass(tmp_path, "p1", [{"instance_id": "a", "resolved": "True"}, {"instance_id": "b", "resolved": "False"}])
    _pass(tmp_path, "p2", [{"instance_id": "b", "resolved": True}, {"instance_id": "c", "resolved": False, "error": "x"}])
    base = [sys.executable, str(SCRIPT), "--target", str(tmp_path / "target.txt"), "--harness-ids", str(tmp_path / "harness_ids.txt"),
            "--collect-dir", str(tmp_path / "eval" / "collect")]
    solved = subprocess.run(base + ["solved"], capture_output=True, text=True, check=True).stdout.split()
    remaining = subprocess.run(base + ["remaining"], capture_output=True, text=True, check=True).stdout.split()
    assert solved == ["a", "b"] and remaining == ["c"]
    inv = tmp_path / "invalid.txt"; inv.write_text("c\tgold fails\n")
    remaining2 = subprocess.run(base + ["remaining", "--invalid", str(inv)], capture_output=True, text=True, check=True).stdout.split()
    assert remaining2 == []
