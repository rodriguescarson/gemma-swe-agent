#!/usr/bin/env bash
# MANDATORY gate before any benchmark (Carson 09-26). Cheapest checks first; any failure = no GPU benchmark.
#  1 compileall  2 unit tests  3 env/version (organiser-patched vllm, pins)  4 bundle config validation
#  5 real inference smoke on every server  6 exact patched vllm + exact competition args + one real LoRA request.
set -uo pipefail
cd /root/g4; export PYTHONDONTWRITEBYTECODE=1; fail() { echo "PREFLIGHT_FAIL $1 $(date -u +%FT%TZ)" >> eval/progress.log; echo "FAIL: $1"; exit 1; }
BUNDLE=${1:-submissions/v6}
/root/venv/bin/hf auth whoami >/dev/null 2>&1 || fail "hf auth missing: backup would fail after the run (2026-09-27: 50 min idle pod)"
PYTHONPYCACHEPREFIX=/tmp/pf_pycache /root/hvenv/bin/python -m compileall -q scripts train pod submissions >/dev/null || fail compileall   # never write __pycache__ into bundles
/root/hvenv/bin/python -m pip -q install pytest >/dev/null 2>&1; PYTHONDONTWRITEBYTECODE=1 /root/hvenv/bin/python -m pytest -q -rf -p no:cacheprovider tests -k "not shellcheck and not official_compiler" >eval/preflight_tests.log 2>&1 || fail "unit tests: $(grep -E "^FAILED" eval/preflight_tests.log | head -3 | tr "\n" " ") $(tail -1 eval/preflight_tests.log)"
/root/venv/bin/python - <<'PY' || fail "env/version"
import vllm, transformers, tokenizers, fastapi
import vllm.model_executor.models.gemma4_mm as g
assert vllm.__version__.startswith("0.19.1"), vllm.__version__
assert getattr(g.Gemma4ForConditionalGeneration, "supports_lora", False), "UNPATCHED vllm (not the organiser wheel)"
assert transformers.__version__ == "5.13.1", transformers.__version__
print("env ok", vllm.__version__, transformers.__version__, tokenizers.__version__, fastapi.__version__)
PY
/root/hvenv/bin/python scripts/validate.py "$BUNDLE" 2>&1 | grep -q "^OK model=" || fail "bundle validation $BUNDLE"
bash pod/health.sh >/tmp/pf_health.log 2>&1 || fail "inference smoke: $(tr '\n' ' ' < /tmp/pf_health.log)"
if [ "${LORA_GATE:-1}" = 1 ]; then
  # exact competition server args (HARNESS_README s3.1 / Getting Started notebook), on a free port, TP=1 for the gate
  CUDA_VISIBLE_DEVICES=${GATE_GPU:-0} timeout 1500 /root/venv/bin/vllm serve /root/models/g4 --served-model-name gemma-4-31b-it-qat-w4a16-ct \
    --tensor-parallel-size 1 --gpu-memory-utilization 0.30 --max-model-len 32768 --enable-auto-tool-choice --tool-call-parser gemma4 \
    --reasoning-parser gemma4 --default-chat-template-kwargs '{"enable_thinking": true}' --enable-lora --max-loras 8 --max-lora-rank 128 \
    --lora-modules main_lora=data/raw/sample_submission/adapters/main_lora --port 8020 > /root/pf_lora.log 2>&1 &
  VP=$!; ok=0
  for t in $(seq 1 120); do
    r=$(curl -s -m 60 localhost:8020/v1/chat/completions -H 'Content-Type: application/json' -d '{"model":"main_lora","messages":[{"role":"user","content":"Say OK"}],"max_tokens":5}')
    echo "$r" | grep -q '"content"' && { ok=1; break; }; kill -0 $VP 2>/dev/null || break; sleep 10
  done
  kill $VP 2>/dev/null; sleep 10
  [ $ok = 1 ] || fail "LoRA request on patched vllm: $(grep -iE 'error|not support' /root/pf_lora.log | tail -1 | cut -c1-160)"
fi
echo "PREFLIGHT_OK $BUNDLE $(date -u +%FT%TZ)" >> eval/progress.log; echo "PREFLIGHT_OK"
