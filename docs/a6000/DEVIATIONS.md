# A6000 evaluator: deviations from the Kaggle notebook (P0, 2026-10-06)

Box: RTX A6000 48 GB, WSL2 Ubuntu 24.04, Python 3.12.3, 94 GB RAM, 1 TB disk.

| Item | Kaggle kernel | A6000 box | Effect |
|---|---|---|---|
| GPUs | 4x L4, tensor_parallel_size=4 | 1x A6000, tensor_parallel_size=1 | Different speed (P1 measures the ratio). Numerics may differ slightly (TP reduction order). |
| Base environment | Colab image (968 packages, torch 2.10.0+cu128, Python 3.12 at the time) | fresh venv; torch/torchvision/torchaudio 2.10.0/0.25.0/2.10.0 +cu128 from download.pytorch.org; PyPI for the rest | Transitive deps are not byte-identical. Pinned to the Kaggle freeze (eval/kaggle/g4-l4-v4/pip_freeze.txt) where it names them: litellm 1.82.4, numpy 2.0.2, openai 2.32.0, ray 2.55.1, triton 3.6.0, uvicorn 0.46.0, fastapi 0.136.1, starlette 0.52.1. Differs: numba 0.61.2 (vllm needs ==0.61.2; Kaggle has 0.60.0), pydantic 2.13.5 (Kaggle 2.12.3), aiohttp 3.14.4 (3.13.5), opentelemetry-sdk 1.41.1 (1.38.0). |
| Wheelhouse | metric/gemma-4-developer-agent-wheelhouse | same 41 wheels, installed with the kernel's own step (`--no-deps --force-reinstall`, cutlass .pth skipped) | none |
| vLLM settings | kernel CELL_VLLM | scripts/a6000/serve.sh, identical except TP | none |
| Docker | n/a | not installed; the SUBPROCESS sandbox (Kaggle scoring backend) needs none | none |
| Competition token | n/a | Kaggle CLI 2.2.4 needs KAGGLE_API_TOKEN (= the KGAT_ key) for competition endpoints | none |
| PYTORCH_CUDA_ALLOC_CONF | expandable_segments:True | unset | On WSL2 expandable_segments makes every CUDA init fail (`CUDA driver error: unknown error`, verified with a 1-line torch test). Allocator behaviour only; peak memory may differ a little. |
| PATH | Linux, no Windows dirs | /mnt/* entries removed inside serve.sh | torch._inductor's `nvcc --version` probe raises PermissionError on WSL's Windows PATH entries and aborts engine start. No effect on results. |
| System package | Colab image has Python headers | `apt install python3.12-dev` in this distro | Triton compiles a small C helper at engine start and needs Python.h. No effect on results. |

## P0 measurements (scripts/a6000/smoke_chat.py)
- vLLM 0.19.1, torch 2.10.0+cu128, transformers 5.13.1, google-adk 1.36.1, adk_submission 0.2.12, swegemma 0.2.7.
- Model: google/gemma-4/Other/gemma-4-31b-it-qat-w4a16-ct/2, tarball sha256 38f582f7f2c80323add914ccda760502c9464ca41ea158f44f66db8b9856f482 (19,348,664,473 bytes), model.safetensors 23,265,352,448 bytes. Kaggle's CLI reports no checksum for models, so integrity rests on the byte size matching the listing (18.0 GiB) and the gzip/tar stream extracting to the end.
- Server up in 95 s. One tool call parsed correctly (get_weather, city Lisbon). One stream, 1000 tokens: 31.2 tokens/s (32.0 s). GPU memory 46.2 GB used at gpu_memory_utilization 0.90.
