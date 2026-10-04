"""scripts/l4_result_summary.sh: on a completed slug with results.jsonl + traces.tar.gz the result file must carry the
summary, the paired lines, the taxonomy classes and the helper-reachability line (2026-10-04: the taxonomy section
came out empty because mktemp was pointed at a directory that did not exist). Uses the local v4-wh28 run if present."""
import os, pathlib, subprocess, pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "l4_result_summary.sh"
SLUG = "g4-l4-v4-wh28-p312"


@pytest.mark.skipif(not (ROOT / "eval" / "kaggle" / SLUG / "traces.tar.gz").exists(), reason="local L4 run data absent")
def test_summary_has_taxonomy_and_helper_lines(tmp_path):
    log = tmp_path / "log"; log.write_text(f"x {SLUG}: KernelWorkerStatus.COMPLETE\n")
    out = tmp_path / "result.txt"
    env = dict(os.environ, SUMMARY_OUT=str(out), SUMMARY_SETTLE_S="0", SUMMARY_PROGRESS=str(tmp_path / "progress.log"))
    r = subprocess.run(["bash", str(SCRIPT), SLUG, str(log)], env=env, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr[-800:]
    text = out.read_text()
    assert "solved 27/74" in text and "paired vs v4h2" in text
    assert '"classes"' in text or "classes" in text, text[-600:]
    assert "helper can't-open-file" in text, text[-600:]
