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


def test_idle_check_reads_nvidia_smi_before_any_cuda_context(tmp_path, monkeypatch):
    """2026-10-12 on the box: torch.cuda.mem_get_info() counted the process's own ~1 GB context on top of the 533 MiB display,
    so the probe refused an idle GPU. The check now reads nvidia-smi (device-level) before torch touches CUDA; torch's figure is
    only the fallback and is logged beside it. Threshold unchanged (1.0 GB)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("qlora_train", ROOT / "train" / "qlora_train.py")
    Q = importlib.util.module_from_spec(spec); spec.loader.exec_module(Q)
    fake = tmp_path / "nvidia-smi"; fake.write_text("#!/bin/sh\necho ' 533 '\n"); fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert Q.nvidia_smi_used_gb() == 0.52
    monkeypatch.setenv("PATH", str(tmp_path / "nothing-here"))
    assert Q.nvidia_smi_used_gb() is None
    assert Q.used_before_load_gb(0.52, 1.56) == 0.52 and Q.used_before_load_gb(None, 1.56) == 1.56
    src = (ROOT / "train" / "qlora_train.py").read_text()
    main_src = src[src.index("def main("):]
    gpu_path = main_src[main_src.index("smi_gb = nvidia_smi_used_gb()"):]        # the dry-run branch above only asks is_available()
    assert gpu_path.index("needs a CUDA GPU") < gpu_path.index("mem_get_info()")       # nvidia-smi first, then the refusals, then torch's reading
    assert "if used_before > 1.0:" in main_src


def test_probe_window_covers_the_first_supervised_positions():
    """2026-10-12: the probe's 2k forward crashed on the box because a v12 sequence's first 2,048 tokens hold no supervised
    position (system prompt + tool declarations + task). The window now extends past 2,048 only as far as needed to cover
    the first 64 supervised positions; a sequence supervised early keeps the plain 2k prefix."""
    import importlib.util, torch
    spec = importlib.util.spec_from_file_location("qlora_train", ROOT / "train" / "qlora_train.py")
    Q = importlib.util.module_from_spec(spec); spec.loader.exec_module(Q)

    def item(n_tokens, first_pos, n_pos):
        pos = torch.arange(first_pos, first_pos + n_pos)
        return {"ids": torch.arange(n_tokens), "positions": pos, "targets": torch.arange(first_pos + 1, first_pos + 1 + n_pos), "weights": torch.ones(n_pos),
                "kinds": torch.zeros(n_pos, dtype=torch.int8), "wsum": float(n_pos), "tokens": n_tokens, "meta": {}}

    late = Q.probe_cut(item(3000, 2500, 100), 2048, 64)            # v12-like: supervision starts after the 2k prefix
    assert late["tokens"] == 2565 and len(late["positions"]) == 64 and int(late["positions"][0]) == 2500 and len(late["ids"]) == 2565
    early = Q.probe_cut(item(3000, 10, 100), 2048, 64)             # supervised early: the plain 2k prefix
    assert early["tokens"] == 2048 and len(early["positions"]) == 100
    few = Q.probe_cut(item(3000, 2900, 5), 2048, 64)               # fewer than 64 positions: cover them all
    assert few["tokens"] == 2906 and len(few["positions"]) == 5
    none = Q.probe_cut(item(3000, 0, 0), 2048, 64)
    assert none["tokens"] == 2048 and len(none["positions"]) == 0
    src = (ROOT / "train" / "qlora_train.py").read_text()
    assert 'probe_cut(max(items, key=lambda it: it["tokens"]), 2048)' in src and '"supervised": int(len(probe_item["positions"]))' in src


def test_log_calls_never_duplicate_a_data_stats_key():
    """2026-10-12 on the box: train_start passed sequences=n beside **data_stats(items), which already carries "sequences";
    TypeError before step 1 (B-005). Every log call that splats data_stats must not name one of its keys."""
    import re
    src = (ROOT / "train" / "qlora_train.py").read_text()
    keys = {"sequences", "tokens", "supervised_tokens", "weighted_tokens", "max_tokens"}
    calls = re.findall(r"log\(([^\n]*\*\*data_stats\(items\)[^\n]*)\)", src)
    assert calls, "no log call splats data_stats any more: update this test"
    for call in calls:
        assert not (set(re.findall(r"(\w+)=", call)) & keys), call
