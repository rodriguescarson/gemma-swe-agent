#!/usr/bin/env bash
# vLLM with the scoring server's flags (HARNESS_README s3.1), TP adjusted to the pod's GPU count.
source /root/venv/bin/activate
TP=${TP:-$(nvidia-smi -L | wc -l)}
LORA=${LORA:-}   # e.g. LORA="--enable-lora --max-loras 8 --max-lora-rank 128 --lora-modules main_lora=/path"
nohup vllm serve /root/models/g4 --served-model-name gemma-4-31b-it-qat-w4a16-ct \
  --tensor-parallel-size $TP --gpu-memory-utilization ${GMU:-0.90} --max-model-len 32768 \
  --enable-auto-tool-choice --tool-call-parser gemma4 --reasoning-parser gemma4 \
  --default-chat-template-kwargs '{"enable_thinking": true}' --enable-prefix-caching $LORA \
  --host 127.0.0.1 --port 8100 > /root/vllm.log 2>&1 &
for i in $(seq 1 120); do curl -sf localhost:8100/v1/models >/dev/null && { echo "VLLM UP after $((i*10))s"; exit 0; }; sleep 10; done
echo "VLLM FAILED"; tail -40 /root/vllm.log; exit 1
