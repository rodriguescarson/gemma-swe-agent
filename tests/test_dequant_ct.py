"""train/dequant_ct.py: the int4 unpack equals compressed-tensors' own, the dequantised weight is q * scale per group of 32 along the
input dim, and the written checkpoint is a plain bf16 HF layout (shards + index + config without quantization_config)."""
import json, sys
from pathlib import Path

import pytest
import torch
from safetensors.torch import save_file, load_file

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from train import dequant_ct as D  # noqa: E402

ct = pytest.importorskip("compressed_tensors.compressors.pack_quantized.helpers")


def test_unpack_matches_the_library_and_dequant_is_q_times_group_scale():
    torch.manual_seed(0)
    q = torch.randint(-8, 8, (16, 64), dtype=torch.int8)
    packed = ct.pack_to_int32(q, 4, packed_dim=1)
    assert packed.dtype == torch.int32 and packed.shape == (16, 8)
    assert torch.equal(D.unpack_int4(packed, (16, 64)), q)
    assert torch.equal(D.library_unpack(packed, (16, 64)), q)
    scale = (torch.rand(16, 2) * 0.1).to(torch.bfloat16)
    w = D.dequant(packed, scale, (16, 64))
    want = (q.float() * scale.float().repeat_interleave(32, dim=1)).to(torch.bfloat16)
    assert w.dtype == torch.bfloat16 and torch.equal(w, want)


def test_convert_writes_a_plain_bf16_checkpoint(tmp_path):
    src = tmp_path / "ct"; src.mkdir()
    q = torch.randint(-8, 8, (16, 64), dtype=torch.int8)
    scale = (torch.rand(16, 2) * 0.1).to(torch.bfloat16)
    norm = torch.ones(64, dtype=torch.bfloat16)
    save_file({"model.language_model.layers.0.self_attn.q_proj.weight_packed": ct.pack_to_int32(q, 4),
               "model.language_model.layers.0.self_attn.q_proj.weight_scale": scale,
               "model.language_model.layers.0.self_attn.q_proj.weight_shape": torch.tensor([16, 64]),
               "model.language_model.layers.0.input_layernorm.weight": norm}, str(src / "model.safetensors"))
    cfg = {"architectures": ["Gemma4ForConditionalGeneration"], "quantization_config": {"format": "pack-quantized", "config_groups": {"group_0": {"weights": {
        "num_bits": 4, "group_size": 32, "symmetric": True, "strategy": "group"}}}}, "text_config": {"final_logit_softcapping": 30.0}}
    (src / "config.json").write_text(json.dumps(cfg)); (src / "tokenizer.json").write_text("{}")
    out = tmp_path / "bf16"
    rep = D.convert(src, out, shard_gb=1000 / 1024 ** 3, check=3, log=lambda *_: None)   # 1000-byte shards: the 128-byte norm, then the 2 KB weight
    assert rep["dequantised"] == 1 and rep["checked_against_library"] == 1 and rep["shards"] == 2
    idx = json.loads((out / "model.safetensors.index.json").read_text())
    assert set(idx["weight_map"]) == {"model.language_model.layers.0.self_attn.q_proj.weight", "model.language_model.layers.0.input_layernorm.weight"}
    w = load_file(str(out / idx["weight_map"]["model.language_model.layers.0.self_attn.q_proj.weight"]))["model.language_model.layers.0.self_attn.q_proj.weight"]
    assert w.dtype == torch.bfloat16 and w.shape == (16, 64) and torch.equal(w, D.dequant(ct.pack_to_int32(q, 4), scale, (16, 64)))
    c = json.loads((out / "config.json").read_text())
    assert "quantization_config" not in c and c["dtype"] == "bfloat16" and c["text_config"]["final_logit_softcapping"] == 30.0
    assert (out / "tokenizer.json").exists() and json.loads((out / "DEQUANT.json").read_text())["tensors"] == 2


def test_refuses_an_unknown_quant_format():
    with pytest.raises(AssertionError):
        D.check_quant_config({"quantization_config": {"format": "float-quantized"}})
