"""Model-facing helpers of the QLoRA trainer (plan ~/.claude/plans/nifty-sleeping-liskov.md, "The real run"): the LoRA target regex per
layer type, attaching PEFT, the inner text-model forward that skips the full-vocabulary lm_head, the per-sequence weighted loss, the
held-out NLL split by span kind, and the bf16 adapter export in the layout train/package_adapter.py accepts. Importable without a GPU
(tests/test_qlora_model.py runs it on a 6-layer Gemma 4 text model on CPU); only load_base_nf4 needs bitsandbytes."""
import json
import re
import shutil
import tempfile
from pathlib import Path

import torch

from train.qlora_lib import chunked_weighted_ce, per_token_nll, token_targets
from train.spans import describe_span

SERVED_BASE = "google/gemma-4-31b-it-qat-w4a16-ct"
BODY = r"self_attn\.(?:q_proj|v_proj|o_proj)|mlp\.(?:gate_proj|up_proj|down_proj)"
NOT_VISION = r"(?!.*(?:vision|audio|embed_vision))"


def sliding_layers(layer_types):
    return [i for i, t in enumerate(layer_types) if t == "sliding_attention"]


def lora_target_regex(layer_types, k_on_sliding=True):
    """A PEFT target_modules regex (fullmatch on module names): q, v, o, gate, up, down on every text layer, k_proj on the sliding
    layers only (on the global layers HF feeds k to K and V, attention_k_eq_v, while vLLM applies a k LoRA to K only: untested
    mismatch, so no k there). The vision tower's q_proj wrappers are excluded by name."""
    pat = rf"^{NOT_VISION}.*\.layers\.\d+\.(?:{BODY})$"
    sl = sliding_layers(layer_types)
    if k_on_sliding and sl:
        pat += rf"|^{NOT_VISION}.*\.layers\.(?:{'|'.join(map(str, sl))})\.self_attn\.k_proj$"
    return pat


def count_matches(model, regex):
    return sum(1 for n, _ in model.named_modules() if re.fullmatch(regex, n))


def layer_types_of(hf_model):
    cfg = hf_model.config
    tc = cfg.get_text_config() if hasattr(cfg, "get_text_config") else cfg
    return list(tc.layer_types)


def softcap_of(hf_model):
    cfg = hf_model.config
    tc = cfg.get_text_config() if hasattr(cfg, "get_text_config") else cfg
    return tc.final_logit_softcapping


def attach_lora(model, r=16, alpha=32, dropout=0.05, k_on_sliding=True):
    """-> (peft_model, info). The number of LoRA-wrapped modules must equal the regex's matches (nothing silently skipped)."""
    from peft import LoraConfig, get_peft_model
    regex = lora_target_regex(layer_types_of(model), k_on_sliding)
    want = count_matches(model, regex)
    pm = get_peft_model(model, LoraConfig(r=r, lora_alpha=alpha, lora_dropout=dropout, bias="none", target_modules=regex, init_lora_weights=True))
    n_lora = sum(1 for _, m in pm.named_modules() if hasattr(m, "lora_A") and "default" in m.lora_A)
    assert n_lora == want, f"PEFT wrapped {n_lora} modules, the regex matches {want}"
    trainable = sum(p.numel() for p in pm.parameters() if p.requires_grad)
    return pm, {"regex": regex, "lora_modules": n_lora, "trainable_params": trainable, "sliding_layers": len(sliding_layers(layer_types_of(model)))}


def base_of(pm):
    return pm.get_base_model() if hasattr(pm, "get_base_model") else pm


def text_model(hf_model):
    inner = hf_model.model
    return getattr(inner, "language_model", inner)


def head_weight(hf_model):
    return hf_model.lm_head.weight


def configure_training(hf_model):
    """Gradient checkpointing (non-reentrant), input grads for the checkpointed embeddings, no KV cache. Nothing is upcast: PEFT's
    prepare_model_for_kbit_training would turn the 2.8 GB tied embeddings into 5.6 GB of fp32."""
    hf_model.config.use_cache = False
    hf_model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    hf_model.enable_input_require_grads()


def forward_hidden(pm, ids):
    """ids LongTensor [T] -> final hidden states [T, H] (after the last norm), without the lm_head."""
    out = text_model(base_of(pm))(input_ids=ids[None], use_cache=False)
    return out.last_hidden_state[0]


def prepare_item(seq, tok, max_tokens):
    """One stitched sequence -> tensors on CPU: ids, positions, targets, weights, kinds (0 text, 1 tool), wsum, tokens."""
    text, spans = seq["text"], sorted(tuple(s) for s in seq["spans"])
    ids, pos, tgt, w, idx = token_targets(text, spans, tok, max_tokens=max_tokens, with_index=True)
    kind_of_span = [0 if describe_span(text, a, b)["kind"] == "text" else 1 for a, b, _ in spans]
    return {"ids": torch.tensor(ids, dtype=torch.long), "positions": torch.tensor(pos, dtype=torch.long), "targets": torch.tensor(tgt, dtype=torch.long),
            "weights": torch.tensor(w, dtype=torch.float32), "kinds": torch.tensor([kind_of_span[i] for i in idx], dtype=torch.int8),
            "wsum": float(sum(w)), "tokens": len(ids), "meta": seq.get("meta", {})}


def to_device(item, device):
    return {k: (v.to(device) if torch.is_tensor(v) else v) for k, v in item.items()}


def sequence_loss(pm, item, denom, chunk=1024):
    """sum(w * nll) / denom over the item's supervised positions (grad-carrying)."""
    base = base_of(pm)
    hs = forward_hidden(pm, item["ids"])
    g = hs[item["positions"]]
    return chunked_weighted_ce(g, head_weight(base), item["targets"], item["weights"], softcap=softcap_of(base), chunk=chunk, denom=denom)


def evaluate(pm, items, chunk=1024, device=None):
    """Held-out NLL over EVERY model span (weights ignored), split by kind. -> {nll_text, nll_tool, nll_all, n_text, n_tool}."""
    base = base_of(pm)
    was_training = pm.training
    pm.eval()
    s_text = s_tool = 0.0
    n_text = n_tool = 0
    with torch.no_grad():
        for it in items:
            it = to_device(it, device) if device is not None else it
            hs = forward_hidden(pm, it["ids"])
            nll = per_token_nll(hs[it["positions"]], head_weight(base), it["targets"], softcap=softcap_of(base), chunk=chunk)
            k = it["kinds"].to(nll.device)
            s_text += float(nll[k == 0].sum()); n_text += int((k == 0).sum())
            s_tool += float(nll[k == 1].sum()); n_tool += int((k == 1).sum())
    if was_training:
        pm.train()
    n = n_text + n_tool
    return {"nll_text": s_text / max(1, n_text), "nll_tool": s_tool / max(1, n_tool), "nll_all": (s_text + s_tool) / max(1, n),
            "n_text": n_text, "n_tool": n_tool}


def export_adapter(pm, out_dir, base_name=SERVED_BASE):
    """PEFT layout, weights cast to bf16, adapter_config.json with the served base name and target_modules as a plain list of leaf
    names (vLLM reads the weights' keys; the regex is only PEFT's business). -> (out_dir, report)."""
    from safetensors.torch import load_file, save_file
    out_dir = Path(out_dir)
    tmp = Path(tempfile.mkdtemp(prefix="adapter_"))
    pm.save_pretrained(str(tmp))
    sd = load_file(str(tmp / "adapter_model.safetensors"))
    sd = {k: v.to(torch.bfloat16).contiguous() for k, v in sd.items()}
    out_dir.mkdir(parents=True, exist_ok=True)
    save_file(sd, str(out_dir / "adapter_model.safetensors"), metadata={"format": "pt"})
    cfg = json.loads((tmp / "adapter_config.json").read_text())
    cfg["base_model_name_or_path"] = base_name
    cfg["target_modules"] = sorted({k.split(".lora_")[0].rsplit(".", 1)[-1] for k in sd})
    cfg["inference_mode"] = True
    (out_dir / "adapter_config.json").write_text(json.dumps(cfg, indent=2))
    shutil.rmtree(tmp, ignore_errors=True)
    rep = {"tensors": len(sd), "params": sum(v.numel() for v in sd.values()), "bytes": sum(v.numel() * 2 for v in sd.values()),
           "dtypes": sorted({str(v.dtype) for v in sd.values()}), "target_modules": cfg["target_modules"], "r": cfg.get("r")}
    (out_dir / "EXPORT.json").write_text(json.dumps(rep, indent=1))
    return out_dir, rep


def load_base_nf4(base_dir, attn="sdpa", device=0):
    """The dequantised bf16 checkpoint (train/dequant_ct.py) loaded as NF4 with double quantisation and bf16 compute; lm_head (tied
    embeddings) and the vision tower stay bf16."""
    from transformers import BitsAndBytesConfig
    try:
        from transformers import Gemma4ForConditionalGeneration as Cls
    except ImportError:  # pragma: no cover
        from transformers import AutoModelForImageTextToText as Cls
    q = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16,
                           llm_int8_skip_modules=["lm_head", "vision_tower", "embed_vision"])
    model = Cls.from_pretrained(str(base_dir), quantization_config=q, dtype=torch.bfloat16, device_map={"": device}, attn_implementation=attn)
    model.config.use_cache = False
    return model
