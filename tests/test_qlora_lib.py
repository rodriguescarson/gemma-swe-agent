"""train/qlora_lib.py: supervision from stitched spans lands on the right tokens (the real Gemma tokenizer when its tokenizer.json is
in the repo), the chunked soft-capped loss equals the full one and its gradient flows, the schedule and the probe verdict follow
docs/a6000/TRAIN_LOCAL.md. CPU only. Written before the GPU driver."""
import json, sys
from pathlib import Path

import pytest
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from train import qlora_lib as Q  # noqa: E402
from train import spans as S  # noqa: E402

TOK_JSON = ROOT / "adapters" / "v11b" / "tokenizer.json"


def tokenizer():
    from tokenizers import Tokenizer
    return Tokenizer.from_file(str(TOK_JSON))


@pytest.mark.skipif(not TOK_JSON.exists(), reason="the Gemma tokenizer.json is not in this checkout")
def test_supervised_tokens_are_exactly_the_model_bytes_and_the_loss_sits_one_position_before():
    tok = tokenizer()
    text = ("<bos><|turn>system\nSYS<turn|>\n<|turn>user\nFIX IT<turn|>\n<|turn>model\n<|channel>thought\nread first\n<channel|>"
            "<|tool_call>call:read_file{filepath:\"a.py\"}<tool_call|><|tool_response>response:x{\"content\": \"SECRET\"}<tool_response|>"
            "<|channel>thought\ndone\n<channel|>Changed a.py.<turn|>")
    spans = S.supervised_char_spans(text)
    weighted = [(a, b, 1.0) for a, b in spans]
    ids, pos, tgt, w = Q.token_targets(text, weighted, tok)
    sup = tok.decode(tgt, skip_special_tokens=False)
    assert "read first" in sup and "call:read_file" in sup and "Changed a.py." in sup and "<turn|>" in sup
    assert "SECRET" not in sup and "FIX IT" not in sup and "SYS" not in sup
    assert all(ids[p + 1] == t for p, t in zip(pos, tgt)) and len(pos) == len(tgt) == len(w) and set(w) == {1.0}
    # a weight-0 span contributes no positions
    weighted0 = [(a, b, 0.0 if i == 0 else 1.0) for i, (a, b) in enumerate(spans)]
    ids2, pos2, tgt2, w2 = Q.token_targets(text, weighted0, tok)
    assert len(pos2) < len(pos) and "read first" not in tok.decode(tgt2, skip_special_tokens=False)
    # the token cap truncates ids and drops positions beyond it
    ids3, pos3, _, _ = Q.token_targets(text, weighted, tok, max_tokens=20)
    assert len(ids3) == 20 and all(p < 19 for p in pos3)


def test_chunked_loss_equals_full_loss_and_backpropagates():
    torch.manual_seed(0)
    N, H, V = 37, 16, 50
    hidden = torch.randn(N, H, requires_grad=True)
    W = torch.randn(V, H)
    tgt = torch.randint(0, V, (N,))
    w = torch.rand(N); w[::5] = 0.0
    a = Q.chunked_weighted_ce(hidden, W, tgt, w, softcap=30.0, chunk=8)
    b = Q.full_weighted_ce(hidden.detach().clone().requires_grad_(True), W, tgt, w, softcap=30.0)
    assert torch.allclose(a, b, atol=1e-5), (a.item(), b.item())
    a.backward()
    assert hidden.grad is not None and hidden.grad.abs().sum() > 0
    assert hidden.grad[::5].abs().sum() == 0                              # weight-0 rows get no gradient
    # softcap bounds the logits: a huge hidden still gives a finite loss
    big = Q.full_weighted_ce(hidden.detach() * 1e4, W, tgt, w, softcap=30.0)
    assert torch.isfinite(big)


def test_schedule_warms_up_and_decays_to_the_floor():
    peak, total = 5e-5, 200
    assert Q.lr_at(0, total, peak) < Q.lr_at(5, total, peak) <= peak
    assert abs(Q.lr_at(6, total, peak) - peak) < 1e-12                     # warmup = 3% of 200 = 6 steps
    assert Q.lr_at(100, total, peak) < peak and abs(Q.lr_at(total, total, peak) - 0.1 * peak) < 1e-9


def test_probe_plan_and_verdict():
    seqs = [{"meta": {"tokens": t}} for t in (1000, 4000, 4500, 6000, 8000, 8500, 9500, 12000, 12500, 13500, 15000, 16000)]
    plan = Q.probe_plan(seqs, per_bucket=2)
    assert [[s["meta"]["tokens"] for s in b] for b in plan] == [[4500, 4000], [8500, 8000], [12500, 12000], [16000, 15000]]
    assert Q.probe_verdict(41.0, 210, 1.0, 0.5)[0] == "FULL"
    assert Q.probe_verdict(41.0, 120, 1.0, 0.5)[0] == "REDUCED"
    assert Q.probe_verdict(41.0, 80, 1.0, 0.5)[0] == "FALLBACK"
    assert Q.probe_verdict(45.0, 210, 1.0, 0.5)[0] == "FALLBACK"           # over 44 GB at 12k
    assert Q.probe_verdict(41.0, 210, 1.0, 0.9)[0] == "FALLBACK"           # loss did not fall 30%
    assert Q.probe_verdict(41.0, 210, 1.0, 0.5, nan=True)[0] == "FALLBACK"


def test_cursor_round_trips(tmp_path):
    c = Q.Cursor(tmp_path / "cursor.json")
    assert c["step"] == 0
    c.save(step=12, seq=40, epoch=0, best=0.31)
    assert Q.Cursor(tmp_path / "cursor.json")["seq"] == 40 and json.loads((tmp_path / "cursor.json").read_text())["best"] == 0.31
    assert Q.epoch_order(5, seed=1) != Q.epoch_order(5, seed=2) and sorted(Q.epoch_order(5)) == [0, 1, 2, 3, 4]


def test_probe_throughput_excludes_buckets_that_oom_or_thrash():
    """2026-10-12 on the box: the 13-16k bucket ran one step at 83 tok/s (46.5 GB) and one at 6 tok/s (47.8 GB, 2,460 s). The
    old average over every step would have called the whole card FALLBACK although everything up to 13k ran at 100-130 tok/s;
    the run never uses that length (cap 12,288), so such a bucket is excluded and reported."""
    from train.qlora_lib import bucket_unusable, probe_throughput
    good = {"range": [9000, 13000], "oom": False, "steps": [{"tokens": 12000, "s": 120.0, "tok_s": 100}, {"tokens": 12000, "s": 115.0, "tok_s": 104}]}
    mid = {"range": [5000, 9000], "oom": False, "steps": [{"tokens": 8000, "s": 61.5, "tok_s": 130}]}
    thrash = {"range": [13000, 10 ** 9], "oom": False, "steps": [{"tokens": 15844, "s": 195.0, "tok_s": 83}, {"tokens": 15844, "s": 2459.65, "tok_s": 6}]}
    oom = {"range": [13000, 10 ** 9], "oom": True, "steps": [{"tokens": 15844, "oom": True}]}
    assert not bucket_unusable(good) and not bucket_unusable(mid) and bucket_unusable(thrash) and bucket_unusable(oom)
    tok_s, excluded = probe_throughput([mid, good, thrash])
    assert excluded == [[13000, 10 ** 9]] and abs(tok_s - (32000 / 296.5)) < 1e-6
    all_in = sum(s["tokens"] for b in (mid, good, thrash) for s in b["steps"]) / sum(s["s"] for b in (mid, good, thrash) for s in b["steps"])
    assert all_in < 30 < tok_s                                 # the old average would have read ~20 tok/s
    assert probe_throughput([oom]) == (0.0, [[13000, 10 ** 9]])
