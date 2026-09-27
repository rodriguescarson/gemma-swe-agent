#!/usr/bin/env bash
# One-shot pod setup: env, model, competition data. Idempotent. Logs to /root/boot.log.
set -euo pipefail
exec > >(tee -a /root/boot.log) 2>&1
echo "START $(date -u)"
cd /root/g4
export UV_LINK_MODE=copy HF_HUB_ENABLE_HF_TRANSFER=1
[ -d /root/venv ] || uv venv -q -p 3.12 /root/venv
source /root/venv/bin/activate
uv pip install -q "vllm==0.19.1" hf_transfer "huggingface_hub[cli]" kaggle pyyaml
# The scorer uses a PATCHED vllm 0.19.1 (adds SupportsLoRA to Gemma4) from the competition wheelhouse; PyPI's build refuses LoRA.
mkdir -p /root/wheelhouse && kaggle datasets download metric/gemma-4-developer-agent-wheelhouse -f vllm-0.19.1-cp38-abi3-manylinux_2_31_x86_64.whl -p /root/wheelhouse --force
[ -f /root/wheelhouse/vllm-0.19.1-cp38-abi3-manylinux_2_31_x86_64.whl.zip ] && (cd /root/wheelhouse && python -m zipfile -e vllm-0.19.1-cp38-abi3-manylinux_2_31_x86_64.whl.zip . )
uv pip install -q --no-deps --reinstall /root/wheelhouse/vllm-0.19.1-cp38-abi3-manylinux_2_31_x86_64.whl
python -c "import vllm.model_executor.models.gemma4_mm as g; assert getattr(g.Gemma4ForConditionalGeneration, 'supports_lora', False), 'UNPATCHED vllm'; print('patched vllm OK')"
uv pip install -q --no-deps "transformers==5.13.1" "tokenizers==0.22.1" "fastapi==0.118.0" "starlette==0.48.0"
python -c "import vllm; print('vllm', vllm.__version__)"
echo "ENV DONE $(date -u)"
# model (Apache-2.0, not gated) in background while data downloads
( hf download google/gemma-4-31B-it-qat-w4a16-ct --local-dir /root/models/g4 > /root/model_dl.log 2>&1 && echo MODEL_OK >> /root/model_dl.log ) &
MPID=$!
python scripts/fetch_data.py > /root/data_dl.log 2>&1 || true
python scripts/fetch_data.py wheels/ >> /root/data_dl.log 2>&1 || true
ln -sfn /root/g4/data/raw/wheels /wheels
ln -sfn /root/g4/data/raw/graphs /root/g4/data/graphs
ln -sfn /root/g4/data/raw/embeddings /root/g4/data/embeddings
wait $MPID
grep -q MODEL_OK /root/model_dl.log && echo "MODEL DONE" || echo "MODEL FAILED"
grep -c " ok$" /root/data_dl.log || true; grep BAD /root/data_dl.log || echo "no BAD files"
echo "BOOT DONE $(date -u)"
