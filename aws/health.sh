#!/usr/bin/env bash
# Port of pod/health.sh for EC2: the eval role serves ONE vLLM with TP=4 on 4x L4 (the scorer's layout) at 8100, not one
# server per GPU. Every server in SERVE_PORTS must return a real completion; exit 1 otherwise (never evaluate a dead server).
ok=1
for port in ${SERVE_PORTS:-8100}; do
  r=$(curl -s -m 60 "localhost:$port/v1/chat/completions" -H 'Content-Type: application/json' \
      -d '{"model":"gemma-4-31b-it-qat-w4a16-ct","messages":[{"role":"user","content":"Say OK"}],"max_tokens":5}')
  if echo "$r" | grep -q '"content"'; then echo "PORT$port HEALTHY"; else echo "PORT$port DEAD: ${r:0:200}"; ok=0; fi
done
[ $ok = 1 ]
