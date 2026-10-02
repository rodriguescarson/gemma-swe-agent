"""Byte-reproducible test adapters for the Kaggle 4xL4 LoRA probe (docs/v11/PLAN.md P0.6, gate G-A; docs/v11/GA_PROBE.md).

    python scripts/make_test_adapters.py --bundle submissions/v4 --out eval/golden/arms/v4_lora_probe [--seed 20261003]

Writes <out>/ = a copy of the bundle plus adapters/<name>/{adapter_config.json, adapter_model.safetensors} and an
`adapter: zb` line in sub_agents/fixer.yaml, and <out>/adapters/MANIFEST.json with the sha256 of every file.

Adapters (numpy only, float16, PEFT layout, q_proj on layer 0 at r=4 so the whole set stays under 0.5 MB in a notebook):
  zb     lora_B all zero, lora_A random: a working LoRA path must leave outputs unchanged (the Z-slot adapter)
  loud   lora_A and lora_B both N(0,1): a working LoRA path must change outputs on nearly every prompt
  loud2  the same tensors under the alternative key prefix (without the second "model."): tells which prefix vLLM maps

Gemma 4 31B text config (google/gemma-4-31b-it-qat-w4a16-ct config.json, read 2026-10-02): hidden 5376, 32 heads x 256,
60 layers. q_proj: in 5376, out 8192. The adapter name rule from docs/v11/plan_A.md: matches ^[a-zA-Z0-9_.-]+$, no
"gemma4", not starting with o<digit> or gpt-5.
"""
import argparse
import hashlib
import json
import os
import shutil
import struct

import numpy as np

HIDDEN, Q_OUT = 5376, 8192
KEY_A = "base_model.model.model.language_model.layers.{n}.self_attn.q_proj.lora_{ab}.weight"     # plan_A.md:98
KEY_B = "base_model.model.language_model.layers.{n}.self_attn.q_proj.lora_{ab}.weight"           # one "model." fewer
SPECS = {  # name: (layers, rank, random_B, key template)
    "zb": ([0], 4, False, KEY_A),       # r=4, layer 0: the sample submission's own shape
    "loud": ([0], 4, True, KEY_A),
    "loud2": ([0], 4, True, KEY_B),
}


def write_safetensors(path, tensors):
    """Minimal safetensors writer: 8-byte LE header length, JSON header (padded to 8), then the raw tensors."""
    header, offset, blobs = {}, 0, []
    for name in sorted(tensors):
        t = np.ascontiguousarray(tensors[name])
        raw = t.tobytes()
        header[name] = {"dtype": {"float16": "F16", "float32": "F32"}[str(t.dtype)], "shape": list(t.shape),
                        "data_offsets": [offset, offset + len(raw)]}
        blobs.append(raw)
        offset += len(raw)
    header["__metadata__"] = {"format": "pt"}
    h = json.dumps(header, separators=(",", ":"), sort_keys=True).encode()
    h += b" " * (-len(h) % 8)
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", len(h)))
        f.write(h)
        for b in blobs:
            f.write(b)


def read_safetensors_header(path):
    with open(path, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        return json.loads(f.read(n))


def make_adapter(name, seed):
    layers, r, random_b, key = SPECS[name]
    rng = np.random.default_rng(seed + sum(map(ord, name)))
    tensors = {}
    for n in layers:
        a = rng.standard_normal((r, HIDDEN)).astype(np.float16)
        b = rng.standard_normal((Q_OUT, r)).astype(np.float16) if random_b else np.zeros((Q_OUT, r), np.float16)
        tensors[key.format(n=n, ab="A")] = a
        tensors[key.format(n=n, ab="B")] = b
    cfg = {"base_model_name_or_path": "google/gemma-4-31b-it-qat-w4a16-ct", "bias": "none", "inference_mode": True,
           "layers_to_transform": layers, "lora_alpha": 2 * r, "lora_dropout": 0.0, "peft_type": "LORA", "r": r,
           "target_modules": ["q_proj"], "task_type": "CAUSAL_LM", "use_dora": False, "use_rslora": False}
    return cfg, tensors


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def build(bundle, out, seed, adapter_stage="fixer", adapter_name="zb"):
    if os.path.exists(out):
        shutil.rmtree(out)
    shutil.copytree(bundle, out, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "._*", ".DS_Store"))
    manifest = {"seed": seed, "bundle": bundle, "files": {}}
    for name in SPECS:
        d = os.path.join(out, "adapters", name)
        os.makedirs(d)
        cfg, tensors = make_adapter(name, seed)
        with open(os.path.join(d, "adapter_config.json"), "w") as f:
            json.dump(cfg, f, indent=2, sort_keys=True)
        write_safetensors(os.path.join(d, "adapter_model.safetensors"), tensors)
        for fn in ("adapter_config.json", "adapter_model.safetensors"):
            manifest["files"][f"{name}/{fn}"] = sha256(os.path.join(d, fn))
    y = os.path.join(out, "sub_agents", f"{adapter_stage}.yaml")
    text = open(y).read()
    assert "adapter:" not in text, y
    text = text.replace("\nmodel: ", f"\nadapter: {adapter_name}\nmodel: ", 1)
    with open(y, "w") as f:
        f.write(text)
    with open(os.path.join(out, "adapters", "MANIFEST.json"), "w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
    return manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=20261003)
    ap.add_argument("--stage", default="fixer", help="sub-agent that gets `adapter: zb`")
    a = ap.parse_args()
    m = build(a.bundle, a.out, a.seed, a.stage)
    total = sum(os.path.getsize(os.path.join(a.out, "adapters", k)) for k in m["files"])
    print(f"{a.out}: {len(m['files'])} adapter files, {total / 1e6:.2f} MB; sha of zb weights {m['files']['zb/adapter_model.safetensors'][:12]}")


if __name__ == "__main__":
    main()
