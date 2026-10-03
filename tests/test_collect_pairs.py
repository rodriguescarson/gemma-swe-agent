"""scripts/collect/pairs.py: every (capture_s<k>.jsonl, s<k>/task_results.jsonl) pair under eval/collect, all samples,
non-empty only, as build_sft --pair arguments. Written before the script (coverage.sh's stitch only paired s1)."""
import pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "collect" / "pairs.py"


def test_all_samples_paired_and_empty_skipped(tmp_path):
    c = tmp_path / "eval" / "collect"
    for tag, samples in (("p1", [1, 2]), ("p2", [1]), ("p3", [1])):
        for k in samples:
            (c / tag / f"s{k}").mkdir(parents=True)
            (c / tag / f"capture_s{k}.jsonl").write_text("{}\n")
            (c / tag / f"s{k}" / "task_results.jsonl").write_text("{}\n")
    (c / "p3" / "capture_s1.jsonl").write_text("")        # empty capture: skipped
    out = subprocess.run([sys.executable, str(SCRIPT), "--collect-dir", str(c)], capture_output=True, text=True, check=True).stdout.split()
    pairs = [out[i + 1] for i in range(0, len(out), 2)]
    assert out[::2] == ["--pair"] * 3
    assert sorted(pairs) == sorted([f"{c}/p1/capture_s1.jsonl={c}/p1/s1/task_results.jsonl", f"{c}/p1/capture_s2.jsonl={c}/p1/s2/task_results.jsonl",
                                    f"{c}/p2/capture_s1.jsonl={c}/p2/s1/task_results.jsonl"])
