#!/usr/bin/env bash
# The A6000 box's TRAINING venv (plan ~/.claude/plans/nifty-sleeping-liskov.md; docs/a6000/TRAIN_LOCAL.md): separate from
# ~/g4/venv, whose transformers is pinned by vLLM 0.19.1. Idempotent. Usage: bash scripts/a6000/train_env.sh [~/g4/train-venv]
# WSL2 rules baked in (docs/a6000/DEVIATIONS.md): never set PYTORCH_CUDA_ALLOC_CONF=expandable_segments (CUDA init fails on this
# box), keep /mnt/* off PATH (nvcc PermissionError kills inductor/triton), everything under ~/g4 (ext4, automount is off).
set -euo pipefail
VENV=${1:-$HOME/g4/train-venv}
PATH=$(echo "$PATH" | tr ':' '\n' | grep -v '^/mnt/' | paste -sd: -); export PATH
unset PYTORCH_CUDA_ALLOC_CONF
# uv when present (the Mac; on the box ~/g4/bin/uv or ~/g4/venv/bin/uv), else python3 -m venv + the venv's own pip
# (2026-10-12: the box had no uv and no `pip --user`; the old fallback could not work there).
UV=$(command -v uv 2>/dev/null || true)
for c in "$HOME/g4/bin/uv" "$HOME/g4/venv/bin/uv"; do [ -z "$UV" ] && [ -x "$c" ] && UV=$c; done
if [ ! -x "$VENV/bin/python" ]; then
  if [ -n "$UV" ]; then "$UV" venv --python 3.12 "$VENV"; else python3 -m venv "$VENV" && "$VENV/bin/python" -m pip install -q --upgrade pip; fi
fi
pipi() { if [ -n "$UV" ]; then "$UV" pip install --python "$VENV/bin/python" "$@"; else "$VENV/bin/python" -m pip install -q "$@"; fi; }
# the same torch build the serving venv runs on this box (proven on the GPU), then the training stack on top
TORCH_SPEC="torch==2.10.0+cu128 torchvision==0.25.0+cu128"
pipi --index-url https://download.pytorch.org/whl/cu128 $TORCH_SPEC
pipi "transformers==5.17.0" "peft==0.21.0" "accelerate==1.15.0" "bitsandbytes>=0.47" \
  "compressed-tensors" "safetensors>=0.5" "tokenizers>=0.21" "numpy" "sentencepiece" "huggingface_hub"
"$VENV/bin/python" - <<'PY'
import torch, transformers, peft, accelerate, bitsandbytes as bnb
print("torch", torch.__version__, "cuda", torch.version.cuda, "available", torch.cuda.is_available())
print("transformers", transformers.__version__, "| peft", peft.__version__, "| accelerate", accelerate.__version__, "| bitsandbytes", bnb.__version__)
if torch.cuda.is_available():
    x = torch.zeros(1).cuda(); print("cuda ok:", x.device, torch.cuda.get_device_name(0))
PY
echo "TRAIN_ENV OK: $VENV"
