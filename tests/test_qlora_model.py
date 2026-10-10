"""train/qlora_model.py on a 6-layer Gemma 4 text model (CPU, bf16): the LoRA regex hits q/v/o/gate/up/down everywhere and k only on
sliding layers while skipping vision-tower names; the loss back-propagates into the LoRA params; held-out NLL splits by kind; the
exported adapter is bf16, PEFT-shaped and accepted by train/package_adapter.py's key rule."""
import json, re, sys
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from train import qlora_model as M  # noqa: E402
from train import spans as S  # noqa: E402
from train import package_adapter as PA  # noqa: E402

TEXT = ("<bos><|turn>system\nSYS<turn|>\n<|turn>user\nFIX IT<turn|>\n<|turn>model\n<|channel>thought\nread first\n<channel|>"
        "<|tool_call>call:read_file{filepath:\"a.py\"}<tool_call|><|tool_response>response:x{\"content\": \"SECRET\"}<tool_response|>"
        "<|channel>thought\ndone\n<channel|>Changed a.py.<turn|>")


def tiny_model():
    from transformers import Gemma4TextConfig, Gemma4ForCausalLM
    torch.manual_seed(0)
    cfg = Gemma4TextConfig(vocab_size=512, hidden_size=64, intermediate_size=128, num_hidden_layers=6, num_attention_heads=4, num_key_value_heads=2,
                           head_dim=16, global_head_dim=32, num_global_key_value_heads=1, layer_types=["sliding_attention"] * 5 + ["full_attention"],
                           sliding_window=8, final_logit_softcapping=30.0, attention_k_eq_v=True, max_position_embeddings=512,
                           hidden_size_per_layer_input=0, vocab_size_per_layer_input=512)
    return Gemma4ForCausalLM(cfg).to(torch.bfloat16)


def char_tokenizer(text):
    from tokenizers import Tokenizer, models, pre_tokenizers, Regex
    vocab = {c: i for i, c in enumerate(sorted(set(text)))}
    vocab["[UNK]"] = len(vocab)
    tok = Tokenizer(models.WordLevel(vocab, unk_token="[UNK]"))
    tok.pre_tokenizer = pre_tokenizers.Split(Regex(r"[\s\S]"), "isolated")
    return tok


def test_regex_targets_the_right_modules_and_skips_vision():
    rx = M.lora_target_regex(["sliding_attention"] * 5 + ["full_attention"])
    assert re.fullmatch(rx, "model.language_model.layers.3.self_attn.k_proj") and re.fullmatch(rx, "model.layers.5.mlp.down_proj")
    assert not re.fullmatch(rx, "model.language_model.layers.5.self_attn.k_proj")          # global layer: no k LoRA
    assert not re.fullmatch(rx, "model.vision_tower.encoder.layers.0.self_attn.q_proj")    # the vision wrapper
    assert not re.fullmatch(rx, "model.vision_tower.encoder.layers.0.self_attn.q_proj.linear")
    assert re.fullmatch(rx, "base_model.model.model.language_model.layers.59.self_attn.q_proj")


def test_attach_forward_loss_eval_and_export(tmp_path):
    model = tiny_model()
    M.configure_training(model)
    pm, info = M.attach_lora(model, r=4, alpha=8, dropout=0.0)
    assert info["lora_modules"] == 5 * 7 + 1 * 5 and info["trainable_params"] > 0 and info["sliding_layers"] == 5
    tok = char_tokenizer(TEXT)
    spans = [(a, b, 1.0) for a, b in S.supervised_char_spans(TEXT)]
    item = M.prepare_item({"text": TEXT, "spans": spans, "meta": {"task": "t"}}, tok, max_tokens=4096)
    assert item["tokens"] == len(TEXT) and len(item["positions"]) == len(item["targets"]) == len(item["kinds"]) and set(item["kinds"].tolist()) == {0, 1}
    pm.train()
    loss = M.sequence_loss(pm, item, denom=item["wsum"], chunk=16)
    assert torch.isfinite(loss) and loss.item() > 0
    loss.backward()
    lora = [(n, p) for n, p in pm.named_parameters() if p.requires_grad]
    assert lora and all(".lora_" in n for n, _ in lora)
    assert any(p.grad is not None and p.grad.abs().sum() > 0 for n, p in lora if "lora_B" in n)
    ev = M.evaluate(pm, [item], chunk=16)
    assert ev["n_text"] > 0 and ev["n_tool"] > 0 and all(v > 0 for k, v in ev.items() if k.startswith("nll")) and pm.training
    out, rep = M.export_adapter(pm, tmp_path / "adapter", base_name=M.SERVED_BASE)
    cfg = json.loads((out / "adapter_config.json").read_text())
    assert cfg["base_model_name_or_path"] == M.SERVED_BASE and isinstance(cfg["target_modules"], list)
    assert set(cfg["target_modules"]) == {"q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"} and cfg["r"] == 4
    assert rep["dtypes"] == ["torch.bfloat16"] and rep["tensors"] == 2 * info["lora_modules"]
    header, _ = PA.read_header(out / "adapter_model.safetensors")
    keys = [k for k in header if k != "__metadata__"]
    assert keys and all(PA.KEY_RE.match(k) for k in keys), keys[:3]              # the packager's loud/loud2 rewrite applies
    PA.check_config(cfg, header)                                                 # rank within the scorer's limit, no DoRA
    assert not any(".lora_A.weight" in k and "layers.5.self_attn.k_proj" in k for k in keys)
