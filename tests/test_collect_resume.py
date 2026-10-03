"""collect.sh must protect a resumed sample's earlier rows: copy task_results.jsonl to task_results.prev.jsonl before
the harness runs and fold it back with scripts/collect/merge_results.py afterwards (swegemma rewrites the file at the
end of a run with only that run's tasks). Source-level check, written before the patch; the merge itself is tested in
tests/test_merge_results.py."""
import pathlib, re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = (ROOT / "scripts" / "collect" / "collect.sh").read_text()


def test_backup_before_run_and_merge_after():
    i_backup = SRC.find('cp "$DONE" "${DONE%.jsonl}.prev.jsonl"')
    i_run = SRC.find("run_eval_pallets.py eval")
    i_merge = SRC.find("python /g4/scripts/collect/merge_results.py")   # the call, not the comment that names the script
    assert i_backup != -1 and i_merge != -1, "backup and merge steps missing"
    assert i_backup < i_run < i_merge, "backup must precede the run and the merge must follow it"
    assert re.search(r"python /g4/scripts/collect/merge_results\.py \"?/out/s\$SAMPLE", SRC), "merge must run inside the container on /out/s$SAMPLE"
