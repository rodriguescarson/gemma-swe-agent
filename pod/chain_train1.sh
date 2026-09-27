#!/usr/bin/env bash
# After v5: LoRA-serving gate on the scorer's vLLM 0.19.1, SFT smoke run (throughput), serve-test the trained adapter,
# verified backup, stop. HOLD keeps the v5 chain from stopping the pod underneath this one.
cd /root/g4
until grep -q "ALL_DONE v5" eval/progress.log; do sleep 60; done
echo "HOLD train1 $(date -u +%FT%TZ)" >> eval/progress.log
for p in $(pgrep -f "^/root/venv/bin/python.*vllm"); do kill $p; done; sleep 20
gate() {  # $1 name, $2 adapter dir -> LORA_GATE_<name> OK|FAIL
  source /root/venv/bin/activate
  CUDA_VISIBLE_DEVICES=0 timeout 1500 vllm serve /root/models/g4 --served-model-name gemma-4-31b-it-qat-w4a16-ct --tensor-parallel-size 1 \
    --max-model-len 32768 --enable-auto-tool-choice --tool-call-parser gemma4 --reasoning-parser gemma4 \
    --enable-lora --max-loras 8 --max-lora-rank 128 --lora-modules "$1=$2" --port 8010 > /root/gate_$1.log 2>&1 &
  VP=$!; ok=FAIL
  for t in $(seq 1 120); do
    r=$(curl -s -m 60 localhost:8010/v1/chat/completions -H 'Content-Type: application/json' -d "{\"model\":\"$1\",\"messages\":[{\"role\":\"user\",\"content\":\"Say OK\"}],\"max_tokens\":5}")
    echo "$r" | grep -q '"content"' && { ok=OK; break; }; kill -0 $VP 2>/dev/null || break; sleep 10
  done
  kill $VP 2>/dev/null; sleep 15
  echo "LORA_GATE_$1 $ok $(date -u +%FT%TZ) $(grep -iE 'error|not support' /root/gate_$1.log | tail -1 | cut -c1-200)" >> eval/progress.log
}
gate sample_lora data/raw/sample_submission/adapters/main_lora
source /root/tenv/bin/activate
python - <<'PY'
import json, random
rows = [json.loads(l) for l in open("/root/data/nebius_all.jsonl")]
short = sorted(rows, key=lambda r: len(json.dumps(r["messages"])))[:300]   # shortest 300, then sample (a fixed char cutoff kept zero)
random.Random(1).shuffle(short)
assert len(short) >= 30, len(short)
with open("/root/data/smoke30.jsonl", "w") as f:
    for r in short[:30]: f.write(json.dumps(r) + "\n")
print("short pool", len(short))
PY
python train/sft.py --data /root/data/smoke30.jsonl --out /root/train_out/smoke30 --base /root/models/g4_bf16 --epochs 1 --grad_accum 4 --max_len 16384 > /root/train_smoke.log 2>&1 \
  && echo "TRAIN_SMOKE OK $(grep SAVED /root/train_smoke.log)" >> eval/progress.log || echo "TRAIN_SMOKE FAIL $(tail -3 /root/train_smoke.log | tr '\n' ' ' | cut -c1-300)" >> eval/progress.log
[ -f /root/train_out/smoke30/adapter_model.safetensors ] && gate smoke30 /root/train_out/smoke30
echo "ALL_DONE train1 $(date -u +%FT%TZ)" >> eval/progress.log
export $(tr "\0" "\n" < /proc/1/environ | grep -E "^RUNPOD_(POD_ID|API_KEY)=" | xargs)
bash pod/backup.sh train1 && runpodctl stop pod "$RUNPOD_POD_ID"
