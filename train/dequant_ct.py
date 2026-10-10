"""Dequantise the served compressed-tensors W4A16 checkpoint (pack-quantized int4, symmetric, group 32 along the input dim) into a
plain bf16 HF checkpoint, streamed tensor by tensor (plan ~/.claude/plans/nifty-sleeping-liskov.md, "Base checkpoint"): the NF4 base
of the QLoRA run is then the closest thing to what vLLM serves, with no 63 GB download.

    python train/dequant_ct.py ~/g4/model --out ~/g4/model-bf16 [--shard-gb 5] [--check 3]

Layout read from the served file's header (2026-10-11): every quantised Linear is a triple `<m>.weight_packed` (int32 [out, in/8]),
`<m>.weight_scale` (bf16 [out, in/32]), `<m>.weight_shape` (int64 [out, in]); lm_head, embeddings, norms and the vision tower are plain
bf16 (the config's `ignore` list). Packing (compressed_tensors.compressors.pack_quantized.helpers.pack_to_int32): element i of a row
sits at bit 4*i of the little-endian int32 stream, stored as int4 + 8. --check N compares this file's unpack with the library's on
the first N packed tensors (when compressed-tensors is importable) and refuses to write on any mismatch."""
import argparse
import json
import shutil
import sys
from pathlib import Path

import torch
from safetensors import safe_open
from safetensors.torch import save_file

COPY_FILES = ("tokenizer.json", "tokenizer_config.json", "chat_template.jinja", "generation_config.json", "processor_config.json", "special_tokens_map.json")
PACKED, SCALE, SHAPE = ".weight_packed", ".weight_scale", ".weight_shape"


def unpack_int4(packed, shape):
    """int32 [rows, ceil(cols/8)] -> int8 [rows, cols] in [-8, 7] (packed_dim 1, num_bits 4, offset 8)."""
    rows, cols = int(shape[0]), int(shape[1])
    nib = torch.stack([(packed >> (4 * j)) & 0xF for j in range(8)], dim=-1).reshape(packed.shape[0], -1)
    return (nib[:, :cols] - 8).to(torch.int8)


def dequant(packed, scale, shape, group=32):
    q = unpack_int4(packed, shape)
    rows, cols = q.shape
    s = scale.to(torch.float32).repeat_interleave(group, dim=1)[:, :cols]
    return (q.to(torch.float32) * s).to(torch.bfloat16)


def check_quant_config(cfg):
    qc = cfg.get("quantization_config") or {}
    g = (qc.get("config_groups") or {}).get("group_0", {}).get("weights", {})
    assert qc.get("format") == "pack-quantized", f"format {qc.get('format')!r}: this script knows pack-quantized only"
    assert g.get("num_bits") == 4 and g.get("group_size") == 32 and g.get("symmetric") is True and g.get("strategy") == "group", g
    return g


def library_unpack(packed, shape):
    try:
        from compressed_tensors.compressors.pack_quantized.helpers import unpack_from_int32
    except Exception:  # noqa: BLE001
        return None
    return unpack_from_int32(packed, 4, torch.Size([int(shape[0]), int(shape[1])]), packed_dim=1).to(torch.int8)


def convert(src, out, shard_gb=5.0, check=3, log=print):
    src, out = Path(src), Path(out)
    cfg = json.loads((src / "config.json").read_text())
    group = check_quant_config(cfg)["group_size"]
    files = sorted(src.glob("*.safetensors"))
    assert files, f"no .safetensors under {src}"
    out.mkdir(parents=True, exist_ok=True)
    shard, shard_bytes, shard_no, weight_map, total, checked, n_deq = {}, 0, 0, {}, 0, 0, 0
    limit = int(shard_gb * 1024 ** 3)

    def flush():
        nonlocal shard, shard_bytes, shard_no
        if not shard:
            return
        shard_no += 1
        name = f"model-{shard_no:05d}.safetensors"
        save_file(shard, str(out / name), metadata={"format": "pt"})
        for k in shard:
            weight_map[k] = name
        log(f"  wrote {name}: {len(shard)} tensors, {shard_bytes / 1024 ** 3:.2f} GB")
        shard, shard_bytes = {}, 0

    for f in files:
        with safe_open(str(f), framework="pt") as sf:
            keys = list(sf.keys())
            packed_keys = [k for k in keys if k.endswith(PACKED)]
            for k in keys:
                if k.endswith(SCALE) or k.endswith(SHAPE):
                    continue
                if k.endswith(PACKED):
                    base = k[:-len(PACKED)]
                    packed, scale, shape = sf.get_tensor(k), sf.get_tensor(base + SCALE), sf.get_tensor(base + SHAPE)
                    if checked < check:
                        ref = library_unpack(packed, shape)
                        if ref is not None:
                            mine = unpack_int4(packed, shape)
                            assert torch.equal(mine, ref), f"unpack mismatch on {k}: refusing to write"
                            checked += 1
                    t, name = dequant(packed, scale, shape, group), base + ".weight"
                    n_deq += 1
                else:
                    t, name = sf.get_tensor(k), k
                t = t.contiguous()
                nbytes = t.numel() * t.element_size()
                if shard and shard_bytes + nbytes > limit:         # keep shards under the limit when a tensor fits in a fresh one
                    flush()
                shard[name] = t
                shard_bytes += nbytes
                total += nbytes
    flush()
    (out / "model.safetensors.index.json").write_text(json.dumps({"metadata": {"total_size": total}, "weight_map": weight_map}, indent=1))
    cfg.pop("quantization_config", None)
    cfg["dtype"] = "bfloat16"
    (out / "config.json").write_text(json.dumps(cfg, indent=2))
    for name in COPY_FILES:
        if (src / name).exists():
            shutil.copy2(src / name, out / name)
    rep = {"tensors": len(weight_map), "dequantised": n_deq, "checked_against_library": checked, "shards": shard_no, "bytes": total, "out": str(out)}
    (out / "DEQUANT.json").write_text(json.dumps(rep, indent=1))
    log(json.dumps(rep))
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("src"); ap.add_argument("--out", required=True); ap.add_argument("--shard-gb", type=float, default=5.0); ap.add_argument("--check", type=int, default=3)
    a = ap.parse_args(argv)
    convert(a.src, a.out, a.shard_gb, a.check)
    return 0


if __name__ == "__main__":
    sys.exit(main())
