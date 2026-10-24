#!/usr/bin/env bash
# Port of pod/preflight.sh (MANDATORY gate before any benchmark, Carson 09-26) for the EC2 eval role. Cheapest checks first;
# any failure = no benchmark. Changes from the pod: S3 replaces HF as the artifact store (bootstrap.sh already proved it
# writable at boot), aws/health.sh checks the one TP=4 server, and the LoRA gate shares the box with that server.
#  1 compileall  2 unit tests  3 env/version (organiser-patched vllm, pins)  4 bundle config validation
#  5 real inference smoke  6 exact patched vllm + exact competition args + one real LoRA request
set -uo pipefail
cd /root/g4 || exit 1; export PYTHONDONTWRITEBYTECODE=1; fail() { echo "PREFLIGHT_FAIL $1 $(date -u +%FT%TZ)" >> eval/progress.log; echo "FAIL: $1"; exit 1; }
BUNDLE=${1:-submissions/v12b}
[ -s /opt/g4/out/BOOT ] || fail "no /opt/g4/out/BOOT: this box was not booted by aws/bootstrap.sh (it writes BOOT to S3 before any work)"
PYTHONPYCACHEPREFIX=/tmp/pf_pycache /root/hvenv/bin/python -m compileall -q scripts train pod aws submissions >/dev/null || fail compileall   # never write __pycache__ into bundles
read -r -a PF_TESTS <<< "${PF_TESTS:-tests/test_bundles.py tests/test_v10_bundle.py tests/test_v10_sandbox.py tests/test_sandbox_tmp_paths.py tests/test_gate_false_pass.py tests/test_pod_scripts.py tests/test_aws_launch.py}"
/root/hvenv/bin/python -m pip -q install pytest >/dev/null 2>&1; PYTHONDONTWRITEBYTECODE=1 /root/hvenv/bin/python -m pytest -q -rfE -p no:cacheprovider "${PF_TESTS[@]}" -k "not shellcheck and not official_compiler and not live" >eval/preflight_tests.log 2>&1 || fail "unit tests: $(grep -E "^(FAILED|ERROR)" eval/preflight_tests.log | head -3 | tr "\n" " ") $(tail -1 eval/preflight_tests.log)"
/root/venv/bin/python - <<'PY' || fail "env/version"
import vllm, transformers, tokenizers, fastapi
import vllm.model_executor.models.gemma4_mm as g
assert vllm.__version__.startswith("0.19.1"), vllm.__version__
assert getattr(g.Gemma4ForConditionalGeneration, "supports_lora", False), "UNPATCHED vllm (not the organiser wheel)"
assert transformers.__version__ == "5.13.1", transformers.__version__
print("env ok", vllm.__version__, transformers.__version__, tokenizers.__version__, fastapi.__version__)
PY
/root/hvenv/bin/python scripts/validate.py "$BUNDLE" 2>&1 | grep -q "^OK model=" || fail "bundle validation $BUNDLE"
bash aws/health.sh >/tmp/pf_health.log 2>&1 || fail "inference smoke: $(tr '\n' ' ' < /tmp/pf_health.log)"
if [ "${LORA_GATE:-1}" = 1 ]; then
  # exact competition server args (HARNESS_README s3.1 / Getting Started notebook) with a LoRA module, on a free port;
  # run it BEFORE serve.sh takes the GPUs (GATE_GPU picks the card), or with LORA_GATE=0 once the main server is up
  CUDA_VISIBLE_DEVICES=${GATE_GPU:-0} timeout 1500 /root/venv/bin/vllm serve /root/models/g4 --served-model-name gemma-4-31b-it-qat-w4a16-ct \
    --tensor-parallel-size 1 --gpu-memory-utilization 0.30 --max-model-len 32768 --enable-auto-tool-choice --tool-call-parser gemma4 \
    --reasoning-parser gemma4 --default-chat-template-kwargs '{"enable_thinking": true}' --enable-lora --max-loras 8 --max-lora-rank 128 \
    --lora-modules main_lora=data/raw/sample_submission/adapters/main_lora --port 8020 > /root/pf_lora.log 2>&1 &
  VP=$!; ok=0
  for _ in $(seq 1 120); do
    r=$(curl -s -m 60 localhost:8020/v1/chat/completions -H 'Content-Type: application/json' -d '{"model":"main_lora","messages":[{"role":"user","content":"Say OK"}],"max_tokens":5}')
    echo "$r" | grep -q '"content"' && { ok=1; break; }; kill -0 $VP 2>/dev/null || break; sleep 10
  done
  kill $VP 2>/dev/null; sleep 10
  [ $ok = 1 ] || fail "LoRA request on patched vllm: $(grep -iE 'error|not support' /root/pf_lora.log | tail -1 | cut -c1-160)"
fi
echo "PREFLIGHT_OK $BUNDLE $(date -u +%FT%TZ)" >> eval/progress.log; echo "PREFLIGHT_OK"
