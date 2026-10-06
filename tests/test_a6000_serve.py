"""scripts/a6000/serve.sh: vLLM on the A6000 through adk_submission's VllmServer with the Kaggle kernel's settings
(scripts/make_eval_kernel.py CELL_VLLM) except tensor_parallel_size=1. Written before the script; DRY_RUN=1 prints the
command and starts nothing."""
import os, pathlib, subprocess, sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
S = ROOT / "scripts" / "a6000" / "serve.sh"
PY = os.environ.get("G4_PY", str(pathlib.Path.home() / "g4" / "venv" / "bin" / "python"))


def _dry(tmp_path, **env_extra):
    env = dict(os.environ, DRY_RUN="1", G4_PY=PY, MODEL_DIR=str(tmp_path), **env_extra)
    return subprocess.run(["bash", str(S)], capture_output=True, text=True, env=env, timeout=120)


def test_syntax_and_strict_mode():
    assert subprocess.run(["bash", "-n", str(S)]).returncode == 0
    assert "set -euo pipefail" in S.read_text()


def _need_adk():
    if subprocess.run([PY, "-c", "import adk_submission"], capture_output=True).returncode:
        pytest.skip("adk_submission not installed in " + PY)


def test_dry_run_matches_kernel_settings_with_tp1(tmp_path):
    _need_adk()
    r = _dry(tmp_path)
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "vllm.entrypoints.openai.api_server" in out
    for flag in ("--tool-call-parser gemma4", "--reasoning-parser gemma4", "--max-model-len 32768", "--dtype bfloat16",
                 "--gpu-memory-utilization 0.9", "--enable-auto-tool-choice", "--port 8000", "--host 127.0.0.1"):
        assert flag in out, flag
    assert "--tensor-parallel-size" not in out          # tp=1: the builder omits the flag
    assert "--default-chat-template-kwargs" not in out  # kernel passes none
    assert "--model " + str(tmp_path) in out


def test_dry_run_starts_nothing(tmp_path):
    _need_adk()
    r = _dry(tmp_path)
    assert "DRY_RUN" in r.stdout
    assert subprocess.run(["pgrep", "-f", "vllm.entrypoints"], capture_output=True).returncode != 0


def test_port_override(tmp_path):
    _need_adk()
    assert "--port 8123" in _dry(tmp_path, PORT="8123").stdout


def test_expandable_segments_not_set_on_wsl():
    t = S.read_text()
    assert "unset PYTORCH_CUDA_ALLOC_CONF" in t and "expandable_segments:True\n" not in t.split("unset")[0].split("OTEL_SDK_DISABLED")[1]


def test_windows_dirs_removed_from_path():
    t = S.read_text()
    assert "grep -v '^/mnt/'" in t
    r = subprocess.run(["bash", "-c", "PATH=/mnt/c/Windows:/usr/bin:/bin:/mnt/c/x; " + t.split("PATH=", 1)[1].split("export PATH")[0].join(["PATH=", ""]) + " echo $PATH"],
                       capture_output=True, text=True)
    assert "/mnt/" not in r.stdout and "/usr/bin" in r.stdout


def test_kv_dtype_and_utilisation_knobs(tmp_path):
    _need_adk()
    out = _dry(tmp_path, KV_DTYPE="fp8", GPU_UTIL="0.95").stdout
    assert "--kv-cache-dtype fp8" in out and "--gpu-memory-utilization 0.95" in out
    default = _dry(tmp_path).stdout
    assert "--kv-cache-dtype" not in default and "--gpu-memory-utilization 0.9" in default
