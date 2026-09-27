#!/usr/bin/env bash
# Gate for eval chains: every vLLM server must return a real completion. Exit 1 otherwise (never evaluate against a dead server).
N=$(nvidia-smi -L | wc -l); ok=1
for i in $(seq 0 $((N-1))); do
  r=$(curl -s -m 60 localhost:$((8100+i))/v1/chat/completions -H 'Content-Type: application/json' \
      -d '{"model":"gemma-4-31b-it-qat-w4a16-ct","messages":[{"role":"user","content":"Say OK"}],"max_tokens":5}')
  echo "$r" | grep -q '"content"' && echo "GPU$i HEALTHY" || { echo "GPU$i DEAD: ${r:0:200}"; ok=0; }
done
[ $ok = 1 ]
