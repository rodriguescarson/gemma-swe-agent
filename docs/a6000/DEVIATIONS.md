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

## P1 speed calibration (2026-10-06; v5h2, first 5 ids of data/kaggle_valid_ids.txt, subprocess sandbox, eval_config budgets, 1 task at a time)
Commands: `scripts/a6000/run_eval.py submissions/v5h2 ~/g4/runs/p1_v5h2 --n 5` (the kernel's run cell), `scripts/a6000/speed_ratio.py RUN`,
`scripts/analyze_helper_reachability.py RUN`. Results rows: eval/a6000/p1_v5h2/results.jsonl. L4 reference = the v4h2g run
(kernel g4-eval74-v4 v6: 34/74, 138.7 s/task, the file keep_rule.py expects: eval/kaggle/g4-l4-v4h2g-p312/results.jsonl).

Solved 1/5 (fastapi_15589) vs 0/5 on L4 (different bundle: v5h2 here, v4h2g there; screening only). Helpers: 0/5 tasks with a can't-open
(locate 5/0, view 21/0, edit 16/0, test 2/0, check 4/0 ok/fail).

Wall seconds per task, A6000 (v5h2) / L4 (v4h2g): 15661 102.7/175.2 = 0.59, 15588 91.5/230.6 = 0.40, 15589 88.0/317.8 = 0.28,
15280 199.7/97.1 = 2.06, 14986 87.3/91.8 = 0.95; median 0.59, sum 0.62. NOT a speed ratio: the two runs are different bundles on different
trajectories (calls 25/22/26/70/31 vs 64/26/57/25/22). Speed on identical work is the next line.

Speed on identical work: each LLM step of a run's traces, measured seconds (difference of cumulative extra.elapsed_s, tool time included)
against the repo's L4 model (router.l4_model_s, 0.102 + 0.02815 x completion + 0.000921 x uncached prompt tokens, or_proxy's uncached rule):
| run | calls | measured s | L4-model s | measured / model |
|---|---|---|---|---|
| A6000, v5h2, 5 tasks | 275 | 541.2 | 487.0 | 1.11 (per task 1.09-1.13) |
| real 4xL4, v4h2g, same 5 tasks | 211 | 810.0 | 779.0 | 1.04 |
| real 4xL4, v4h2g, all 74 | 3027 | 9085.0 | 8494.9 | 1.07 (median per task 1.00) |
So the model reproduces the real L4 to ~4-7%, and the A6000 takes **about 1.04-1.11x the L4 time for the same calls (slightly SLOWER, not
faster)**; per task, A6000 ratio divided by the real-L4 ratio of the same task: 1.14, 1.12, 1.12, 1.08, 0.96 (median 1.12).
Single-stream decode 31.2 tokens/s vs the model's 35.5. Limits: 5 tasks, one task at a time, one bundle, tool time inside both sides.

Pacing (scripts/a6000/pace_proxy.py, tests/test_a6000_pace_proxy.py, 6 tests, mutation-checked): a reverse proxy in front of vLLM that holds every
non-streaming reply until l4_model_s of that call has passed (or_proxy's Pacer), never delays a call that is already slower, logs late_s. Because
the A6000 is not faster, it is a floor, not a slowdown: it only matters when parallel-free short calls come back faster than modelled. Check:
fastapi_14986 through the proxy (port 8001): 34 calls, 0 non-200, 28 calls slower than the model (late_s > 0), 6 held; 99.4 s measured vs 84.3 s
model (1.18), helper reachability 0/1 can't-open. Recommendation for P2-P4: run through the proxy (`run_eval.py ... --port 8001`); with 4
parallel tasks the A6000 gets slower per call, so the 5-minute cap will bite EARLIER than on L4 (more work per task is cut off than on Kaggle),
which no pacing can undo; P2 should measure median task seconds and cap hits and read solve rates with that bias in mind.
