#!/usr/bin/env bash
# vLLM on the A6000 with the Kaggle kernel's settings (scripts/make_eval_kernel.py CELL_VLLM), tensor_parallel_size=1
# (deviation recorded in docs/a6000/DEVIATIONS.md). Env: MODEL_DIR (default ~/g4/model), PORT (8000), BUNDLE (a bundle
# dir whose adapters/ are mounted, default none), G4_PY (python of ~/g4/venv), DRY_RUN=1 prints the command only.
# Runs in the foreground; Ctrl-C or kill stops the server.
set -euo pipefail
export G4_PY="${G4_PY:-$HOME/g4/venv/bin/python}"
export MODEL_DIR="${MODEL_DIR:-$HOME/g4/model}"
export PORT="${PORT:-8000}"
export BUNDLE="${BUNDLE:-}"
export KV_DTYPE="${KV_DTYPE:-}"      # P2 addendum 2: fp8 doubles the KV tokens (screen-only deviation); empty = the kernel's default
# 2026-10-17: 0.90 -> 0.88 leaves ~1 GiB of the 48 GiB card for WDDM when the Windows desktop is in use (p4_v16a stalled under
# a foreign python.exe + desktop apps; GAPS "p4_v16a stopped as CONTAMINATED")
export GPU_UTIL="${GPU_UTIL:-0.88}"
# environment of the kernel's install cell
export LITELLM_LOCAL_MODEL_COST_MAP=True TRANSFORMERS_NO_TF=1 VLLM_WORKER_MULTIPROC_METHOD=spawn \
  VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS=1 VLLM_ENGINE_READY_TIMEOUT_S=1200 VLLM_NO_USAGE_STATS=1 \
  OTEL_SDK_DISABLED=true
# the kernel also sets PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True; on WSL2 that makes every CUDA init fail with
# 'CUDA driver error: unknown error', so it is left unset (allocator behaviour only; docs/a6000/DEVIATIONS.md)
unset PYTORCH_CUDA_ALLOC_CONF
# torch._inductor runs `nvcc --version` for a log comment and only tolerates FileNotFoundError; WSL puts Windows
# directories on PATH, where the lookup raises PermissionError and kills the engine core. Drop /mnt/* from PATH.
PATH="$(printf '%s' "$PATH" | tr ':' '\n' | grep -v '^/mnt/' | paste -sd:)"
export PATH
exec "$G4_PY" -I - <<'PY'
import os, subprocess, sys, time
from adk_submission import VllmConfig, VllmServer, discover_adapters
from swegemma.config import ALLOWED_ADAPTER_EXTENSIONS
adapters = discover_adapters(os.environ["BUNDLE"], adapter_extensions=ALLOWED_ADAPTER_EXTENSIONS) if os.environ["BUNDLE"] else None
cfg = VllmConfig(model=os.environ["MODEL_DIR"], port=int(os.environ["PORT"]), host="127.0.0.1", tool_call_parser="gemma4",
    reasoning_parser="gemma4", max_model_len=32768, dtype="bfloat16", gpu_memory_utilization=float(os.environ["GPU_UTIL"]), kv_cache_dtype=(os.environ["KV_DTYPE"] or None), enable_auto_tool_choice=True,
    enable_lora=True, max_loras=8, max_lora_rank=128, tensor_parallel_size=1, startup_timeout=60 * 20,
    # SERVED_ALIAS (opt-in, 2026-10-18 h2g4): a second served name for OpenCode; the model path stays first (ids[0])
    extra_args=(["--served-model-name", os.environ["MODEL_DIR"], os.environ["SERVED_ALIAS"]] if os.environ.get("SERVED_ALIAS") else []))
server = VllmServer(cfg, adapter_manifest=adapters)
if os.environ.get("DRY_RUN") == "1":
    print("DRY_RUN", " ".join(server.build_cmd())); sys.exit(0)
t0 = time.time(); server.start()
print("vLLM up in", round(time.time() - t0), "s at", server.base_url, flush=True)
try:
    while server.is_healthy(): time.sleep(5)
finally:
    server.stop()
PY
