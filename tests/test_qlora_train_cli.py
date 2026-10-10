"""train/qlora_train.py on a CPU box: --dry-run tokenises the stitched sequences with the real Gemma tokenizer and prints the plan;
without a GPU the real modes refuse with exit 2 before touching anything."""
import json, subprocess, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.test_stitch_rows import chain  # noqa: E402
from train import stitch_rows as ST  # noqa: E402

TOK = ROOT / "adapters" / "v11b" / "tokenizer.json"


@pytest.mark.skipif(not TOK.exists(), reason="the Gemma tokenizer.json is not in this checkout")
def test_dry_run_prints_the_plan_and_gpu_modes_refuse_on_cpu(tmp_path):
    import torch
    rows = chain() + [dict(r, prompt=r["prompt"].replace("FIX IT", "FIX THAT")) for r in chain(task="t2", traj="cap|t2")]
    seqs, held, rep = ST.stitch(rows, holdout={"t2"})
    (tmp_path / "seqs.jsonl").write_text("".join(json.dumps(s) + "\n" for s in seqs))
    (tmp_path / "held.jsonl").write_text("".join(json.dumps(s) + "\n" for s in held))
    base = [sys.executable, str(ROOT / "train" / "qlora_train.py"), "--seqs", str(tmp_path / "seqs.jsonl"), "--holdout", str(tmp_path / "held.jsonl"),
            "--tokenizer-json", str(TOK), "--out", str(tmp_path / "out")]
    r = subprocess.run(base + ["--dry-run", "--grad-accum", "1"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-800:]
    plan = json.loads(r.stdout)
    assert plan["data"]["sequences"] == 1 and plan["holdout"] == 1 and plan["steps"] == 1 and plan["data"]["supervised_tokens"] > 0
    assert sum(len(b) for b in plan["probe_buckets"]) == 1
    if not torch.cuda.is_available():
        r2 = subprocess.run(base + ["--probe", "--base", str(tmp_path)], capture_output=True, text=True)
        assert r2.returncode == 2 and "needs a CUDA GPU" in r2.stdout
    r3 = subprocess.run(base + ["--help"], capture_output=True, text=True)
    assert r3.returncode == 0 and "--probe" in r3.stdout and "--resume" in r3.stdout
