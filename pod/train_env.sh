#!/usr/bin/env bash
# Training env (separate from vLLM and harness envs) + bf16 QAT base weights. Idempotent.
set -e
export UV_LINK_MODE=copy HF_HUB_ENABLE_HF_TRANSFER=1
[ -d /root/tenv ] || uv venv -q -p 3.12 /root/tenv
source /root/tenv/bin/activate
uv pip install -q torch "transformers==5.13.1" "peft>=0.19" accelerate hf_transfer "huggingface_hub[cli]" sentencepiece
python -c "import torch, transformers, peft; print('tenv', torch.__version__, transformers.__version__, peft.__version__, torch.cuda.is_available())"
hf download google/gemma-4-31B-it-qat-q4_0-unquantized --local-dir /root/models/g4_bf16 > /root/bf16_dl.log 2>&1 && echo BF16_OK
