#!/usr/bin/env bash
# One vLLM per GPU (TP1) on ports 8100.. (8001 is RunPod nginx); same parser/template flags as the scorer.
source /root/venv/bin/activate
N=$(nvidia-smi -L | wc -l)
for i in $(seq 0 $((N-1))); do
  CUDA_VISIBLE_DEVICES=$i nohup vllm serve /root/models/g4 --served-model-name gemma-4-31b-it-qat-w4a16-ct \
    --tensor-parallel-size 1 --gpu-memory-utilization 0.90 --max-model-len 32768 \
    --enable-auto-tool-choice --tool-call-parser gemma4 --reasoning-parser gemma4 \
    --default-chat-template-kwargs '{"enable_thinking": true}' --enable-prefix-caching ${LORA:-} \
    --host 127.0.0.1 --port $((8100+i)) > /root/vllm_$i.log 2>&1 &
done
for i in $(seq 0 $((N-1))); do
  for t in $(seq 1 90); do curl -sf localhost:$((8100+i))/v1/models >/dev/null && { echo "GPU$i UP"; break; }; sleep 10; done
done
