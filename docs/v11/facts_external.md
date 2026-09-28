# v11 external facts: LoRA on the scorer, training recipe, expected gains, more data

Sweep taken 2026-09-28, 17:05-17:30 IST. Read-only throughout: Kaggle API (kaggle 2.2.4 via `uvx`), HF Hub API and HTTP range reads, GitHub/arXiv pages, and files already on disk. Nothing was posted, voted, submitted or pushed. No pod or kernel was started. The only downloads were small text files (a dataset README, a 3.7 MB `tasks.jsonl`, two pipeline scripts, 4 notebook sources) and a few KB of model-weight byte ranges.

Labels used below:
- **VERIFIED**: read from a primary source or measured here, with the path or command.
- **INFERENCE**: my reading of verified facts. Not measured.
- **UNVERIFIED**: stated by a secondary source, or not checked.

Evidence written during this sweep is in `EX = /private/tmp/claude-501/-Users-carson-Projects/654244a3-b38c-45a0-96af-d7e5f0aac6ce/scratchpad/v11ext/`. Earlier sweeps are in `SP/forum7/` (forum dump), `SP/org0928/vsrc/` (patched vLLM sources, v22 and v25) and `SP/lit/pdfs/` (paper texts), where `SP` is the scratchpad root.

---

## 0. Bottom line (ranked by how much each changes the v11 plan)

1. **The LoRA path is fixed on paper, but nobody has shown that an adapter changes outputs on the scorer.** (VERIFIED)
   - Wheelhouse v23 (2026-09-27 16:07 IST) rebuilt vLLM 0.19.1 with the double-registration fix. The host confirmed on 09-28 16:02 IST that he "applied a fix for LoRA loading yesterday".
   - As of 17:10 IST 09-28 there is no new reply in 743508 or 743964, and no public notebook or post with a scored adapter.
   - So step 1 of v11 is still the logprob test in §1.5, run on the v25 wheel.
2. **There is a new train/serve mismatch on 10 of the 60 layers, and it is silent.** (VERIFIED by code reading on both sides; not yet measured)
   - The 10 full-attention layers have no `v_proj` (`attention_k_eq_v: true`). In HF transformers, V on those layers *is* the `k_proj` output, so a LoRA on `k_proj` changes both K and V during training.
   - The scorer's vLLM packs K into the K slot and a copy of the base K weights into the V slot of `qkv_proj`. It fills the V slot's LoRA with `None` when the adapter has no `v_proj` tensor.
   - Result: at serving time, V on those layers gets no LoRA delta.
   - Fix: at export, either duplicate each full-layer `k_proj` LoRA as a `v_proj` LoRA, or leave `k_proj` out of the targets on layers 5, 11, ..., 59. Then check it with the §1.5 parity test.
3. **Train on the weights the scorer actually serves.** (VERIFIED)
   - The served int4 checkpoint is a fresh round-to-nearest quantization of the QAT bf16 weights: group 32, scale = amax/7.5, ints in [-8, 7].
   - It is not the bf16 weights snapped to a grid. On 3 sampled matrices the mean elementwise |int4 - QAT bf16| is 6.7% of mean |W|, and only about 12% of weights match exactly.
   - transformers 5.17 can load the compressed-tensors checkpoint dequantized to bf16 (`CompressedTensorsConfig(dequantize=True)`). That is a 23.3 GB download instead of 62.5 GB, and it matches serving exactly up to kernel arithmetic.
4. **Render the training data with the scorer's June chat template, not the July one.** (VERIFIED)
   - The scorer mounts Kaggle `gemma-4-31b-it-qat-w4a16-ct` version 2. Its `chat_template.jinja` is 16,934 B, dated 2026-06-05.
   - Every current HF repo (the QAT bf16 base that `train/sft.py` loads the tokenizer from, and the w4a16 repo our pod downloads) ships the 18,683 B template of 2026-07-15.
5. **The published evidence says plain rejection-sampling fine-tuning on a ~32B model's own successes gives small gains.** (VERIFIED from papers)
   - SWE-Gym, 32B, MoatlessTools: 19.0 → 19.7 → 19.7 on SWE-bench Lite over two iterations.
   - SWE-Gym, 32B, OpenHands: adding 868 on-policy successes to 491 teacher trajectories dropped Lite from 15.3 to 8.7.
   - The large published SFT gains all come from *teacher* trajectories. Those are not cleared here for non-Gemma models.
   - (INFERENCE) Realistic v11 upside: fewer format errors, loops and wasted calls, which the SFT papers do measure. Our own audit prices those at about 3.5 tasks per 51 plus 18-41% of agent time. Plain RFT will not take 0.12 to 0.30 by itself.
6. **Our own data covers only 4 public repos, and repo diversity is what transfers.** (VERIFIED)
   - The 129 public tasks are fastapi 67, rich 48, requests 13, httpx 1.
   - SWE-smith (7B, 700 trajectories): 4 repos → 10.3%, 100 repos → 15.1% on Verified, roughly logarithmic.
   - Cheapest diverse source: **SWE-Pallets-X v4**, 476 execution-verified tasks from 8 new repos, already in the competition's task format, CC0-1.0, on Kaggle. Its problem statements are PR title + body, the same style as the hidden set.
7. **Adapter dtype and size traps.** (VERIFIED)
   - PEFT upcasts LoRA weights to fp32 by default (`autocast_adapter_dtype=True`).
   - An all-linear r=64 adapter is then 1.96 GB instead of 0.98 GB. r=128 fp32 is 3.9 GB, over the 3 GiB bundle cap.
   - The host's sample adapter is bf16, so cast to bf16 at export.
8. **Open vLLM issue #50059**: rank-32, all-layer LoRA over a compressed-tensors int4 W4A16 g32 base gave weak, non-reproducible outputs at T=0. Rank 8 on the last 8 layers was fine, and slicing to rank 16 restored determinism. (VERIFIED, issue text only)
   - That report is on RTX 5090, vLLM 0.17.1-0.24.0, not on L4 with the patched 0.19.1.
   - Include a determinism-by-rank check in §1.5 before choosing a rank.
9. **Any adapter switches the scorer's vLLM into LoRA mode for every request.** (VERIFIED in `adk_submission/server.py:716-731`)
   - `--enable-lora --max-lora-rank 128` is passed only when the bundle contains adapters.
   - Startup was about 663 s in the host's adapter run against 383 s in our no-adapter L4 kernels (different runs; UNVERIFIED as a causal delta).
   - LoRA decode overhead on 4×L4 is unmeasured. Decode is 90-97% of our agent time, so measure it before shipping.
10. **No competitor has a working adapter.** (VERIFIED)
    - The only 31B training notebook (denpugovkin) trains QLoRA on Unsloth's bnb-4bit copy of the *non-QAT* bf16 model, on gold patches, and claims no score.
    - The KerasHub "TPU LoRA" notebook exports random placeholder tensors.

---

## 1. LoRA on the scorer

### 1.1 The fix and its status
- **Report, 743508** (Whisper Last, 2026-09-26 11:33 IST). The wheelhouse vLLM registered each Gemma4 decoder layer twice, as `language_model.model.layers.N` and as the YOCO alias `...self_decoder.decoder_layers.N`.
  - `activate_adapter` calls `set_lora` under the first name, then `reset_lora` under the alias, which zeroes the weights.
  - Repro: set every `lora_B` to random values with std 1.0 and serve the adapter with `--enable-lora`. The top logprobs at T=0 for the base name and the adapter name come out identical.
  - `VLLM_LOGGING_LEVEL=DEBUG` shows 240 "Successfully loaded LoRA weights for module language_model.model.layers.N..." lines, then 240 "No LoRA weights found for module ...self_decoder.decoder_layers.N..., skipping." lines. Every `lora_b_stacked` slot is zero afterwards.
  - Source: `SP/forum7/dump.json` key `743508`. https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743508
- **Host answer, 743964 comment 3529469** (Ryan Holbrook, 2026-09-28 16:02 IST):
  - "LoRA: I applied a fix for LoRA loading yesterday. You can see the limits on rank and size in the getting started notebook and also in the `HARNESS_README.md`. There's also a total submission limit of 3GB."
  - "Training data: Training on gemma-4-31b itself is fine. We'll try to have an answer for outputs from other models soon."
  - "Parallel: I we don't support parallel calls."
  - "12h overrun: Not yet. Budget per task using `eval_config.yaml`."
  - https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743964
- **What changed in the wheel** (VERIFIED earlier by per-member CRC diff, `research/org_update_0928.md` §1). Wheelhouse v23 changed exactly `vllm/model_executor/models/gemma4.py` (CRC `ef6fc74f` → `c8cefd56`) and `vllm/lora/model_manager.py` (`79143634` → `e16a1908`). v25 has the same content.
  - `activate_adapter` now tracks loaded modules by `id(module)`.
  - `_create_lora_modules` skips modules that are already wrapped.
  - `Gemma4SelfDecoderLayers` stores `decoder_layers` outside the module tree unless `kv_sharing_fast_prefill` is set.
  - Local copies: `SP/org0928/vsrc/v25_*.py`.
- **Re-check at 17:10 IST 09-28** (EX/`t_*.json`). The 45 main-track topics were re-listed and compared with the 16:07 dump.
  - Only 743683 (reruns) has new comments, and none of them concern LoRA.
  - 743508 still has only "I will address". No re-test has been posted.
- **Upstream context** (VERIFIED from the issue pages):
  - PyPI vLLM 0.19.1 refuses Gemma4 LoRA ("does not support LoRA yet"), and vLLM feature issue #39246 was closed by PR #39291. The host's wheel carries its own `SupportsLoRA` patch.
  - Open vLLM issue #41754 (2026-05-05) reports Unsloth-trained Gemma 4 31B adapters that "load without crashing" but have no effect. No root cause is given. That is the same symptom class as 743508.
  - Links: https://github.com/vllm-project/vllm/issues/39246, https://github.com/vllm-project/vllm/issues/41754

### 1.2 How the harness serves adapters (VERIFIED in `.venv/.../adk_submission/server.py`, `data/raw/HARNESS_README.md`)
- **LoRA mode only with adapters.** `--enable-lora --max-loras max(8, n) --max-lora-rank 128 --lora-modules name=path ...` is added only when `adapters/` holds at least one adapter (`server.py:716-731`).
  - With any adapter present, every request runs in LoRA mode, base-model stages included.
- **Adapter names** must match `^[a-zA-Z0-9_.-]+$`. Any `LlmAgent` can set `adapter: <name>`, so per-stage adapters in the v10 SequentialAgent are allowed (README §3.4).
- **Limits.** Total unpacked bundle < 3 GiB (3,221,225,472 B), `.safetensors` only, rank ≤ 128, ≤ 8 adapters (README lines 128-210).
- **Expected key format** is `base_model.model.model.language_model.layers.N.self_attn.q_proj.lora_A.weight`, stored BF16.
  - This comes from the host's sample adapter, `data/raw/sample_submission/adapters/main_lora`: r=4, alpha 8, q_proj/o_proj, layer 0 only, `base_model_name_or_path: google/gemma-4-31b-it-qat-w4a16-ct`.
  - Shapes: q_proj A [4, 5376], B [8192, 4]; o_proj A [4, 8192], B [5376, 4].
- **Startup.**
  - Our no-adapter L4 kernels: vLLM up in 383 s, 503-509 s before task 1 (`research/time_model.md`:19).
  - Host notebook with the two sample adapters, 09-27 19:50 UTC: vLLM up in about 663 s (`research/org_update_0928.md`:103).
  - Different runs, so the +280 s is UNVERIFIED as the cost of LoRA mode (vLLM config shows `cudagraph_specialize_lora: True`, so extra graph captures are plausible).

### 1.3 Architecture facts that decide target modules (VERIFIED)
From `hf://models/google/gemma-4-31B-it-qat-w4a16-ct/config.json` (identical `text_config` in the QAT bf16 repo):

| Field | Value | Consequence |
|---|---|---|
| layers | 60: 50 `sliding_attention` (window 1024) + 10 `full_attention` (indices 5, 11, ..., 59) | two layer shapes |
| sliding layers | head_dim 256, 32 q heads, 16 kv heads: q_proj 5376→8192, k/v_proj 5376→4096 | |
| full layers | global_head_dim 512, 4 kv heads, **`attention_k_eq_v: true`**: q_proj 5376→16384, k_proj 5376→2048, **no v_proj** | see below |
| MLP | 5376→21504→5376 (gate/up/down), GELU-tanh | |
| `num_kv_shared_layers` | 0 | the E2B/E4B KV-sharing bugs do not apply to 31B |
| vocab | 262,144, `final_logit_softcapping` 30.0 (inside `text_config`) | logits memory, softcap pitfall (§2.3) |
| quantization | compressed-tensors `pack-quantized`, int4 symmetric, group 32, observer `memoryless_minmax`; `ignore` = vision tower (27 layers), `embed_vision.embedding_projection`, `lm_head` | all language-model Linear layers are int4 |

- **Trainable-parameter check.** Our 09-26 SFT smoke printed `trainable params: 122,429,440` for r=16 on q/k/v/o/gate/up/down of the language model. Source: `backups/backups/20260926T095858Z-train1/train_smoke.log`, transformers 5.13.1, peft 0.21.0, torch 2.14.0+cu130.
  - That equals exactly 50 sliding layers with v_proj plus 10 full layers without v_proj. With v_proj on the full layers it would be 123,617,280.
  - The same checkpoint check shows no `layers.5.self_attn.v_proj` tensor in either the int4 or the bf16 checkpoint.
- **HF side** (`transformers/models/gemma4/modeling_gemma4.py:1175-1250`, v5.17.0): `v_proj = None` when `attention_k_eq_v and not is_sliding`, and then `value_states = ... if self.v_proj is not None else key_states`, with `v_norm` applied afterwards.
  - So a LoRA on `k_proj` shifts both K and V in training.
- **vLLM side**, patched wheel (`SP/org0928/vsrc/v25_gemma4.py:296-307, 1460-1471, 1577-1585` and `v25_model_manager.py:632-667`):
  - k_eq_v layers still use a packed `qkv_proj`. The weight loader duplicates `k_proj` into the V slot.
  - `_create_merged_loras_inplace` packs `[q_proj, k_proj, v_proj]` LoRAs and fills a missing one with `None`.
  - So an adapter without `v_proj` on layer 5 gets no delta on V there.
- **SGLang hit the same architecture** (issue #40966): "10 full-attention layers with attention_k_eq_v where the v_proj module is entirely absent". The reporter's fix note: "k_proj LoRA should apply to the fused k=v projection". https://github.com/sgl-project/sglang/issues/40966
- **Adapter size for all 7 language-model projections** (VERIFIED arithmetic, matches the count above):

  | rank | params | bf16 | fp32 (PEFT default) |
  |---|---|---|---|
  | 8 | 61.2 M | 0.12 GB | 0.24 GB |
  | 16 | 122.4 M | 0.24 GB | 0.49 GB |
  | 32 | 244.9 M | 0.49 GB | 0.98 GB |
  | 64 | 489.7 M | 0.98 GB | 1.96 GB |
  | 128 | 979.4 M | 1.96 GB | 3.92 GB (over the cap) |

  The HARNESS_README guide (lines 207-210) gives r16 110-220 MB up to r128 0.9-1.8 GB, consistent with bf16.

### 1.4 Other known vLLM LoRA risks
- **#50059 (open, 2026-07-28).** "LoRA on a compressed-tensors int4 (W4A16) model: rank-32 all-layer adapters produce weak, non-reproducible outputs; rank-8 partial-coverage adapters work fine."
  - Setup: OLMo-3.1-32B W4A16 g32 on RTX 5090, vLLM 0.17.1 and 0.24.0, `--max-lora-rank 32`.
  - Outputs differ across identical T=0 runs and after a restart. The same adapter on llama.cpp (GGUF) was byte-deterministic.
  - Slicing to rank 16 restored determinism. No maintainer reply.
  - The docs' LoRA × quantization matrix lists QLoRA/GPTQ/AWQ, not compressed-tensors.
  - https://github.com/vllm-project/vllm/issues/50059
- **#10062 (closed as stale).** "Up to a 50% drop in maximum throughput" with a single LoRA, Llama-2-7B on A100, `--max-lora-rank 64`. No numbers at batch 1, and it is old vLLM. https://github.com/vllm-project/vllm/issues/10062
- (INFERENCE) Our regime is one sequence at a time, decode-bound, TP4 on L4, with buffers sized for rank 128. Overhead there has to be measured, not assumed.

### 1.5 Minimal verification protocol (to run before any training spend)
Pass/fail conditions are stated here, before the run. All requests go at T=0, one at a time.

0. **Environment**
   - Install the v25 wheelhouse vLLM wheel. Check `gemma4.py` CRC `c8cefd56` and `model_manager.py` CRC `e16a1908`.
   - Serve the **Kaggle v2** model files, or HF weights plus the Kaggle v2 `chat_template.jinja` and `tokenizer_config.json`.
   - Use `--enable-lora --max-loras 8 --max-lora-rank 128`, exactly as the scorer does.
1. **Applied (Whisper Last's repro).** Take an r=16 all-linear adapter and set `lora_B` ~ N(0, 1).
   - PASS: the top-1 token at T=0 differs from base on ≥ 18 of 20 prompts, and the DEBUG log has 0 "No LoRA weights found ... self_decoder" lines.
2. **Correct mapping (parity against HF).** Build small random adapters, one per module family: q, k (sliding layers only), k (full layers only), v, o, gate+up, down.
   - Scale each so that the HF bf16 Δlogprob (adapter − base) has an RMS of about 0.1-0.5 nats on 2k tokens of a real trace.
   - PASS: Pearson r ≥ 0.9 between the vLLM Δlogprob and the HF Δlogprob on the same tokens, for every family.
   - Expected FAIL on "k, full layers" unless the export also writes the duplicated `v_proj` tensors. Run that family both ways; it tests fact 0.2.
   - The HF reference must load the same weights (dequantized w4a16, §2.1) so that only the adapter differs.
3. **Determinism by rank (#50059).**
   - Run 5 repeats plus 1 server restart for r ∈ {16, 32, 64, 128}.
   - PASS: identical token sequences, 256 tokens each, on 5 prompts.
   - Cap the rank at the largest one that passes.
4. **Speed and startup, on Kaggle 4×L4 only** (pod numbers are not predictive).
   - Measure decode tokens/s at concurrency 1 with no adapter directory, and again with one r=16 adapter referenced by the agent. Also record the time to "vLLM up".
   - PASS: decode slowdown ≤ 10%. If it is 10-25%, re-price the whole v11 gain against the per-task time cap.
- **Cost** (INFERENCE):
  - Steps 1-3 fit on the 2×H100 pod in about 1-1.5 h, roughly $7-10 at $6.98/h. The bf16 HF reference goes on GPU 0 and vLLM TP1 int4 on GPU 1.
  - Step 4 is one Kaggle kernel run, which costs Kaggle GPU quota, not dollars.
  - It needs Carson's approval for the 433 MB wheel download and the pod start.

---

## 2. Training recipe that transfers to the W4A16 serving base

### 2.1 Which weights to train on
| Candidate | What it is | Size | Weights date | Fit to the served int4 |
|---|---|---|---|---|
| Kaggle `google/gemma-4/other/gemma-4-31b-it-qat-w4a16-ct/2` (**what the scorer mounts**) | compressed-tensors int4 g32 | 23,265,352,448 B | files dated 2026-06-05 | itself |
| HF `google/gemma-4-31B-it-qat-w4a16-ct` | same format; `base_model: google/gemma-4-31B-it-qat-q4_0-unquantized` | 23,265,352,448 B (same size as Kaggle v2) | weights commit `ca9d5250d0` 2026-06-05; later commits change only the template, README and tokenizer_config | same bytes very likely (size match; hash not compared) |
| HF `google/gemma-4-31B-it-qat-q4_0-unquantized` (current `pod/train_env.sh` choice) | "Half-precision weights extracted from the QAT pipeline" (model card) | 62.5 GB in 2 shards | commit `4f92690356` 2026-06-05 | mean elementwise error to the served int4 = 6.7% of mean \|W\| (measured below) |
| HF `google/gemma-4-31B-it` | original bf16, before QAT | 62.5 GB | April 2026 lineage | further away (different training) |
| `unsloth/gemma-4-31B-it-unsloth-bnb-4bit` (competitor's choice) | bnb NF4 of the non-QAT model | 19.1 GB | 2026-07-17 | different base and a different quantizer |

- **Measurement** (EX/`cmp_rows.py`, `grid2.py`). Byte-range reads of 4-8 rows each of layer-0 `q_proj`, layer-5 `k_proj` and layer-30 `down_proj`, from both repos.
  - Unpacking: nibble i of each int32 is element i (LSB first), value = nibble − 8. This order gives the small error; the strided order gives about 100% error.
  - Scale per 32-group = amax/7.5 (median of amax/scale = 7.500, range 7.47-7.53).
  - Mean |dequant(int4) − QAT bf16| / mean |W| = 0.067, 0.067, 0.067 on the three matrices. Weights exactly equal: 12.4%, 11.5%, 11.6%.
  - The QAT bf16 weights sit closer to a llama.cpp Q4_0 grid (scale = signed max / −8): 3.35% mean relative error, against 6.66% to the CT grid.
  - Reading: QAT targeted Q4_0, and the w4a16-ct file is a separate RTN at amax/7.5.
- **Dequantized load** (VERIFIED in transformers 5.17.0 `utils/quantization_config.py:1095-1190` and the HF docs):
  - `CompressedTensorsConfig(dequantize=True)` "dequantized to the model dtype (e.g. BF16) ... the model can be fine-tuned or saved in that dtype".
  - `run_compressed=False` is the deprecated alias.
  - Our `pod/train_env.sh` pins transformers 5.13.1, so check that version has `dequantize`, or pin 5.17.
  - https://huggingface.co/docs/transformers/en/quantization/compressed_tensors
  - Unsloth added the same path (decompress packed INT4 on 16-bit load "so LoRA can attach"): https://github.com/unslothai/unsloth/pull/12134
- (INFERENCE) Recommendation: train on dequant(Kaggle v2 int4) in bf16. The parity test in §1.5 step 2 then compares like with like.
  - A cheap A/B: evaluate held-out trace NLL for an adapter trained on each base, served on vLLM int4. If the gap is < 1% NLL, the choice does not matter.

### 2.2 Chat template (VERIFIED)
- Kaggle v2 files: `chat_template.jinja` 16,934 B, `tokenizer_config.json` 2,741 B, both 2026-06-05 (`kaggle models instances versions files google/gemma-4/other/gemma-4-31b-it-qat-w4a16-ct/2`).
- HF `main` of both QAT repos: `chat_template.jinja` 18,683 B ("Update to canonical Gemma 4 chat template", 2026-07-15) and `tokenizer_config.json` 3,728-3,729 B ("Add response_template", 2026-07-20).
- Already measured in `research/pain_points.md` §3: the June template emits a stray `<turn|>` when an assistant message carries both text and a tool call.
- Consequences for `train/sft.py`:
  - It loads the tokenizer from the HF bf16 repo, so it renders with the July template.
  - Its `supervised_char_spans` keys on `<|turn>model\n`, `<turn|>` and `<|tool_response>`/`<tool_response|>`. The stray `<turn|>` would cut a supervised span early.
  - Fix: load the June template explicitly and add a test for the text-plus-tool-call case.

### 2.3 Library versions and Gemma 4 gotchas
| Gotcha | Evidence | Status for us |
|---|---|---|
| FlashAttention-2 rejects head_dim 512 (the full layers): "FlashAttention forward only supports head dimension at most 256" | https://huggingface.co/google/gemma-4-31B-it/discussions/30, https://github.com/Dao-AILab/flash-attention/issues/2427, transformers issue #45201 (per-layer FA2 for sliding, SDPA for global) | `sft.py` uses `sdpa`: OK |
| Softcapping silently lost when code reads `config.final_logit_softcapping` at top level (it lives in `text_config`). Logits reached ±122 instead of ±30 | prime-rl #2362 https://github.com/PrimeIntellect-ai/prime-rl/issues/2362 | Native HF path uses `get_text_config().final_logit_softcapping` (`modeling_gemma4.py:2582`): OK. Add an assert max \|logit\| ≤ 30 in the smoke run |
| Pre-clip grad norms 1-2 orders of magnitude above vanilla HF+PEFT in prime-rl (unsolved; concentrated in layers 5-17) | same issue; reference setup r16/α32, lr 1e-4, max_norm 1.0, 16k seq | Log grad norm per step. Our path is vanilla HF+PEFT |
| `mm_token_type_ids` required for text-only batches; fixed in transformers ≥ 5.5.2 | https://ghost.oxen.ai/writing-a-fine-tuning-and-deployment-pipeline-isnt-as-easy-as-it-looks-gemma-4-version/ | `sft.py` passes zeros: OK |
| KV-sharing garbage with `use_cache=False` (E2B/E4B) | same post; Unsloth docs | N/A: 31B has `num_kv_shared_layers: 0` |
| PEFT rejects `Gemma4ClippableLinear` (vision/audio towers only) | same post; PEFT ≥ 0.19 regex defaults | our regex targets `language_model` only: OK |
| DeepSpeed ZeRO-3 writes empty (shape [0]) LoRA tensors on save | TRL #4416 https://github.com/huggingface/trl/issues/4416; oxen post | avoid ZeRO-3, or gather before save; always check tensor shapes after save |
| PEFT `autocast_adapter_dtype=True` stores adapters in fp32 | https://huggingface.co/docs/peft/developer_guides/troubleshooting | cast to bf16 at export (sample adapter is bf16; §1.3 sizes) |
| Logits memory: 16k tokens × 262,144 vocab is 8.6 GB bf16, 17.2 GB fp32, plus softcap intermediates, on the last GPU | arithmetic from config; the Nemotron LoRA thread shows the same term dominating (687961) | (INFERENCE) compute CE only on supervised positions, or chunk/fuse (Liger or Unsloth fused CE); otherwise OOM risk at 16k on 80 GB |
| SWE-Gym-style training reports and Unsloth docs: loss 1-3 is normal for 31B; Unsloth recommends `gemma-4-thinking` template for 31B and markers `<\|turn>user\n` / `<\|turn>model\n` | https://unsloth.ai/docs/models/gemma-4/train | our spans already use these markers |
| Unsloth doc claims "not supported by vLLM" for Gemma 4 | same page | outdated relative to the host's patched wheel |

- **Versions seen in the wild** (VERIFIED):
  - Ours (loaded the model and built the LoRA; crashed afterwards on a schedule bug): torch 2.14.0+cu130, transformers 5.13.1, peft 0.21.0.
  - Competitor denpugovkin: `unsloth==2026.9.11`, `transformers==5.5.0`, trl.
  - Oxen post minimums: transformers ≥ 5.5.2, peft ≥ 0.19.0.
- **Our own smoke run never took a step.**
  - `train_smoke.log` ends in `ZeroDivisionError` in the LR lambda (`steps` was 0 with 30 rows at grad_accum 4 after filtering; "examples 0"). The repo has since been fixed and tested per the ledger.
  - So training throughput on our pod is **unmeasured**.

### 2.4 Target modules, rank, adapters per stage
- The scorer serves ranks up to 128, but see §1.4 #50059. Start at r=16 on all 7 projections: 0.24 GB bf16, 8 of them fit in 3 GiB.
  - Handle `k_proj` on full layers per fact 0.2.
  - Raise the rank only if step 3 of §1.5 passes.
- Published SWE recipes:
  - SWE-Gym 32B LoRA: r=64, lr 5e-4, 5 epochs, batch 8, 1×H100, Unsloth (`SP/lit/pdfs/2412.21139.txt`:954-955).
  - prime-rl Gemma 4 31B: r16/α32, lr 1e-4.
  - Nemotron 1st place: r32/α32, lr 2e-4, 1 epoch.
  - Nemotron lesson (topic 697491): at lr 2e-4, oversampling a hard subset 14× wiped other skills (LB 0.85 → 0.73). The fix was ≤ 3× oversampling, lr 5e-5 and grad-accum 64. https://www.kaggle.com/competitions/nvidia-nemotron-model-reasoning-challenge/discussion/697491
- **Per-stage adapters** are allowed (§1.2). (INFERENCE) They split the data further (each stage sees only its own turns) and multiply the parity tests. One shared adapter trained on all stages' turns is the cheaper first step.

### 2.5 Hardware and time on 2×H100
- **Measured anchor**: Gemma 4 31B LoRA r64/α64 on **2×H100 80 GB** with TRL SFTTrainer + FSDP: **486 tokens/s**, 10k samples, seq ≤ 4,096, effective batch 8, 5.39 h, $119 at $22.12/h. https://arxiv.org/html/2605.25645v1
- **Other anchors**:
  - Skywork-SWE: 8,209 trajectories, 3 epochs, full FT on 8×H800 for 12 h (`SP/lit/pdfs/2506.19290.txt`:785-788).
  - SWE-smith: full FT, lr 5e-5, 3 epochs, 32k context, 2-8 H100.
  - SWE-Lego: full FT, lr 5e-5 (32B), 4 epochs, 128k context.
- **(INFERENCE) Budget table.**
  - Throughput bounds: 486 tok/s measured; about 2,000 tok/s is the naive-pipeline FLOP ceiling at 40% MFU (6 × 31e9 FLOP/token, one GPU busy at a time).
  - Our trajectories run 10-25k tokens. The scorer compacts at 14,336 prompt tokens, so cap training sequences at about 16k.

  | trajectories × avg tokens | tokens/epoch | hours/epoch at 486-2,000 tok/s | $/epoch at $6.98/h |
  |---|---|---|---|
  | 300 × 12k | 3.6 M | 0.5-2.1 h | $4-15 |
  | 1,000 × 15k | 15 M | 2.1-8.6 h | $15-60 |
  | 5,000 × 15k | 75 M | 10-43 h | $73-300 |

  Budget cap is about $500 with roughly $60-80 spent (task brief). 5k trajectories × multiple epochs does not fit. 0.5-1.5k does.
- **Memory** (INFERENCE):
  - bf16 weights of 62.5 GB split over 2×80 GB leave about 48 GB of headroom per GPU.
  - Checkpointed layer inputs at 16k tokens: 60 × 16k × 5376 × 2 B ≈ 10.6 GB.
  - The logits term (§2.3) is the risk, not the weights.

---

## 3. What gains to expect from fine-tuning on own successful trajectories

| Work | Base, scaffold | Training data | Result | Source |
|---|---|---|---|---|
| SWE-Gym (teacher SFT) | Qwen2.5-Coder-32B, OpenHands | 491 successes from gpt-4o + claude-3.5, avg ~19 turns, ~19k tokens | Verified 7.0 → 20.6, Lite 3.0 → 15.3; stuck-in-loop −5.6 (Verified); empty patch +4.3 on 32B Verified | `2412.21139.txt`:284-360 |
| SWE-Gym **self-improvement**, OpenHands | the fine-tuned 32B | +868 own successes (6 samples/task, T=0.5) mixed with the 491 | Lite **15.3 → 8.7** ("self-improvement is not yet working") | same:326-366 |
| SWE-Gym **self-improvement**, MoatlessTools | 7B / 32B, LoRA r64 lr 5e-4 5 ep (32B) | iterative RFT, high-T rollouts on SWE-Gym Lite, ≤ 2 per task, fewer rounds preferred | 7B 7.0 → 9.0 → 10.0; **32B 19.0 → 19.7 → 19.7**; 32B empty patch 24.3% → 9.7% | same:362-392, Table 4 |
| SWE-smith | Qwen2.5-Coder-32B, SWE-agent | 5,016 Claude 3.7 trajectories, ≤ 3 per instance | Verified 7.0 → 40.2; 500 trajectories → 28.2 | `2504.21798.txt`:130-380 |
| SWE-smith repo diversity | 7B, 700 trajectories | 4 / 25 / 50 / 100 repos | 10.3 / 11.5 / 12.9 / 15.1, about log-linear | same:497-502, Fig. 5 |
| SWE-smith difficulty | 7B, 500 each | difficulty 2/4/6/8 | 12.4 / 10.8 / 13.6 / 12.2: no trend | same:429-444 |
| SWE-smith task source | 7B | LM Modify / LM Rewrite / Procedural / PR Mirror | 5.7 / 8.8 / 8.6 / 9.2; LM-written issue text ≈ real issue text (7.7 vs 7.8) | same:400-428 |
| Skywork-SWE | 32B, OpenHands | 8,209 trajectories | 38.0, "no signs of saturation" | `2506.19290.txt` |
| SWE-Lego | Qwen3-32B | 18k from Qwen3-Coder-480B | 52.6; **error masking +2.2** (loss off on turns whose observation is a tool/test error); turn-count curriculum +2.2; recycling semi-resolved +1.2 (8B) | https://arxiv.org/html/2601.01426v2 |
| On-policy expert corrections | 7B / 32B | student starts, teacher finishes | +14% / +13% relative over imitation | https://arxiv.org/abs/2512.14895 |
| DAgger revisited | 4B / 8B | turn-level student/teacher mix | +3.9 / +3.6 points over the strongest post-training baseline | https://arxiv.org/abs/2605.12913 |
| ReST-EM | PaLM-2 on MATH/APPS | own correct samples, a few iterations | beats SFT on human data; scales with model size | https://arxiv.org/abs/2312.06585 |

**Filtering rules with evidence:**
- Keep resolved trajectories only (all works).
- Cap per task: 2 in SWE-Gym, 3 in SWE-smith, "slightly outperforming the full dataset" in SWE-Gym. Prefer fewer rounds.
- Drop trajectories that edit tests (SWE-Lego). Our scorer resets test edits anyway.
- Mask error turns rather than dropping whole trajectories (SWE-Lego).
- Fix malformed tool arguments post hoc, e.g. string → int and clipping ranges (SWE-Lego).
- Leaking the fail-to-pass test into the issue text made the student skip reproduction (−66% repro attempts; SWE-smith Table 5).

**Risks with evidence:**
1. **Self-training at 32B can regress.** SWE-Gym OpenHands went 15.3 → 8.7.
2. **Repo overfitting.** Only 4 public repos; the diversity curve is above.
3. **Tool-format drift.** Trajectories from v2-v9 bundles use other prompts and tool schemas than v10. (INFERENCE) Train only on v10-format turns, or re-render older ones into the v10 format.
4. **Catastrophic forgetting at high lr or with oversampling** (Nemotron 697491).
5. **Own-output data is by construction high-likelihood** (Nemotron 697491 "lower logprob data tends to be easier to learn"). (INFERENCE) It carries little new information, which is consistent with the flat 32B curves above.

**(INFERENCE) What this means for v11.** Plain RFT is a format and efficiency lever, not a capability lever. The failure modes it can plausibly shrink are exactly our measured losses:
- malformed `edit_file` spirals, about 3.5 tasks per 51 per arm;
- exact-repeat calls, 32-44% of calls;
- 18-41% of agent time on failed calls (`research/own_data.md` §0).

Since hidden tasks saturate the 5-minute cap, time saved converts into solved tasks. Set the pre-registered success bar in those units: malformed-call rate, repeat rate, s/task on L4, and tasks solved on held-out repos.

---

## 4. Cheap ways to get more own-trajectory data

| Source | Size | Repos | Licence | Env | Problem text | Notes |
|---|---|---|---|---|---|---|
| **SWE-Pallets-X v4** (Kaggle `takumuhata/swe-pallets-x`, updated 2026-09-27) | **476 tasks**; 10.3 GB | pytest 132, sympy 129, click 109, werkzeug 43, flask 29, jinja2 29, markupsafe 4, itsdangerous 1 | **CC0-1.0** | per-instance `uv venv` with era-matched Python 3.10-3.13 and era-pinned deps from PyPI (`pipeline/pipeline/verify.py`, `era_pin.py`); no wheels shipped | PR title + body (same style as hidden set); no FAIL_TO_PASS, test functions come from `test_patch` | Already in competition format: `tasks.jsonl`, snapshots, graphs, embeddings. Baseline Qwen2.5-Coder-7B 4/181 on the pallets subset. "commit-level disjoint from the competition's public training repositories". https://www.kaggle.com/datasets/takumuhata/swe-pallets-x, https://github.com/taku629/swe-pallets-x |
| SWE-Gym | 2,438 | 11 | MIT | Docker images | real issues | https://huggingface.co/datasets/SWE-Gym/SWE-Gym |
| SWE-smith-py | 50,908 | 131 | MIT | Docker image per repo (`image_name`) | LM-written issues | https://huggingface.co/datasets/SWE-bench/SWE-smith-py |
| SWE-rebench | 21.3k test + 6.5k filtered | many | CC-BY-4.0 (per-task `license_name`) | `install_config` (python, pip_packages, install, test_cmd) makes a docker-free venv feasible; Docker images too | real issues; FAIL_TO_PASS/PASS_TO_PASS | https://huggingface.co/datasets/nebius/SWE-rebench |
| R2E-Gym-Subset | 4.6k | ~10 | Apache-2.0 | Docker images | synthetic | https://huggingface.co/datasets/R2E-Gym/R2E-Gym-Subset |
| Bug injection on repos we already run (SWE-smith procedural / LM-rewrite style) | unbounded | any repo with a working env | our own | our env | issue text written by gemma-4-31b itself (own outputs: allowed) | SWE-smith Table 4: procedural 8.6 and LM-rewrite 8.8, against PR mirror 9.2 (7B) |

- **Rules** (VERIFIED, competition rules page text in `SP/kaggle_pages.md`:190-198):
  - External data is allowed if "publicly available and equally accessible to use by all Participants ... at no cost".
  - Winners license the submission and its generating code under an OSI-approved licence (Apache 2.0 per the page header).
  - All datasets above are public and free.
- **Environment work is the real cost** (VERIFIED from harness docs). The scorer sandbox installs from `/wheels` offline and runs `/sandbox/setup.py --fast-path <repo>` (`HARNESS_README.md`:254-278).
  - (INFERENCE) On the pod we control the network, so a per-repo `uv` venv, as SWE-Pallets-X's `verify.py` does, is the shortest path.
  - It still needs a harness adapter so that swegemma uses that venv. Budget engineering time, not GPU time, for this.
- **Generation cost (INFERENCE from `eval/ledger.md`).**
  - The ledger row of 2026-09-26 16:40 UTC lists 4 configs × 74 tasks for about $14 (about 2 h at $6.98/h, 2 tasks per H100). If all four arms ran inside that $14 (UNVERIFIED from the ledger alone), that is about $0.05 per task-run, with 21-26 of 74 solved (28-35%).
  - At a 15-30% solve rate on new repos, that is about $0.16-0.31 per success, so $160-310 per 1,000 successes at race concurrency.
  - Data generation does not need latency-faithful timing. Running 8+ tasks per H100 should cut this 2-3× (UNVERIFIED).
  - Then filter by **L4-feasibility**: keep a trajectory only if its predicted L4 agent time, 0.99 s per call + 26.5 ms per completion token (the fitted L4 cost in `research/own_data.md` §0.6), fits the per-task cap.
- **Privileged self-teacher** (INFERENCE; check with the host if used).
  - "Training on gemma-4-31b itself is fine" covers outputs of the same model run with a larger budget, thinking on, or best-of-N. Filtered into the fast v10 format, that is the DAgger/OEC pattern with no outside teacher.
  - If the teacher runs on a *different* checkpoint (bf16 non-QAT `gemma-4-31B-it`), that is arguably still "gemma-4-31b", but ask in 743964 first.

---

## 5. Competitor evidence on LoRA (VERIFIED; sources in EX/`nb/`)
- **denpugovkin, "Can Gemma 4 Fix an Unseen Repo? | 31B QLoRA Study"** (last run 2026-09-26).
  - Setup: Unsloth `FastModel` on `unsloth/gemma-4-31B-it-unsloth-bnb-4bit`, split over T4×2, `max_seq_length=1024`, r=8, α=8, lr 8e-5, 1 epoch, `adamw_8bit`, template `gemma-4-thinking`, `train_on_responses_only` with the `<|turn>user\n` / `<|turn>model\n` markers.
  - Data: gold patches of the public tasks, with all Rich tasks held out.
  - It says the training base differs from the QAT serving base, and it claims no score.
  - https://www.kaggle.com/code/denpugovkin/can-gemma-4-fix-an-unseen-repo-31b-qlora-study
- **nursrijan, "KerasHub LoRA Training on TPU"** (2026-09-25). Loads Gemma 2 presets.
  - The "SafeTensors bridge" writes `np.random.randn(LORA_RANK, 64)` placeholders.
  - Not a usable Gemma 4 adapter.
- **hitarthjain0, "What Moves the Leaderboard"**: advises a rank-8 end-to-end smoke test before investing.
- **yash1425**: toy r=8 q/k/v on SWE-bench_Lite prompts (`research/forum_update_0928.md`).
- **Forum**
  - No scored adapter anywhere. Leaderboard team "DoRA" (0.13) is only a name.
  - 743186 asked how to post-train on limited VRAM and got no host answer.
  - 742807 (distillation from other models, 38 votes) is still unruled.
- **Related Kaggle precedent**: NVIDIA Nemotron Reasoning Challenge, where LoRA adapters were served by vLLM.
  - 1st place: r32/α32 including `lm_head`, lr 2e-4, Unsloth, about 170 GPU-hours, synthetic solver traces.
  - Topic 697491 documents the oversampling and learning-rate forgetting trap.
  - https://www.kaggle.com/competitions/nvidia-nemotron-model-reasoning-challenge/discussion/709231

---

## 6. Implications for the v11 plan (INFERENCE, ranked)
1. **Gate everything on §1.5.** About $10 of pod time plus one Kaggle kernel. If step 1 or 2 fails, v11 stays prompt-only and the report goes to 743508.
2. **Export rules**, each with a unit test:
   - duplicate full-layer `k_proj` LoRA as `v_proj` (or exclude it);
   - bf16 tensors;
   - key prefix `base_model.model.model.language_model.layers.N...`;
   - no vision tensors;
   - `base_model_name_or_path` set to the served name;
   - total size < 3 GiB;
   - `r` and `lora_alpha` in the config match the tensors.
3. **Training base** is dequant(Kaggle v2 int4) in bf16. Render with the June template. Cap sequences at about 16k (scorer compaction at 14,336). Use chunked CE on supervised positions only. Log grad norms and max |logit|.
4. **Data**: v10-format turns only.
   - Sources: our resolved runs on the 4 public repos (cap 2-3 per task, fewest calls first), plus v10 runs on SWE-Pallets-X (8 repos, CC0).
   - Hold out one whole repo for evaluation (the competitor held out Rich). Error-mask failed turns. Filter by L4-feasible time.
5. **Pre-register the bar before training.** Examples: malformed-call rate halves; s/task on L4 drops ≥ 10%; held-out-repo solves are not worse than v10 at p < 0.2 paired.
   - Faithful Kaggle-L4 evaluation decides shipping (standing rule). Pod numbers only screen.
6. **Do not plan on RFT closing 0.12 → 0.30.** The literature puts plain self-RFT at 32B at about 0-1 point. Per-stage adapters and the privileged self-teacher are the next levers, after a single shared adapter shows any effect.

## 7. Still open
- Does an adapter change outputs on the v25 wheel? (§1.5 step 1; nobody has posted a re-test.)
- Is the scorer's decode speed with `--enable-lora` within 10% of base on 4×L4?
- Does #50059-style rank non-determinism reproduce on L4 with the patched 0.19.1?
- Is the Kaggle v2 `model.safetensors` byte-identical to HF `ca9d5250d0`? Same size; hash not compared.
- Does transformers 5.13.1 have `CompressedTensorsConfig(dequantize=True)`, or does the train env need 5.17?
- Host ruling on outputs from other models (742807 / 743964).

## 8. Links
- Forum: 743508 https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743508 · 743964 https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743964 · 742807 https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/742807 · 743383 https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743383 · 743213 https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743213
- Wheelhouse: https://www.kaggle.com/datasets/metric/gemma-4-developer-agent-wheelhouse · Getting Started: https://www.kaggle.com/code/ryanholbrook/getting-started-gemma-4-developer-agent
- Models: https://huggingface.co/google/gemma-4-31B-it-qat-w4a16-ct · https://huggingface.co/google/gemma-4-31B-it-qat-q4_0-unquantized · https://huggingface.co/google/gemma-4-31B-it · https://huggingface.co/unsloth/gemma-4-31B-it-unsloth-bnb-4bit
- vLLM / SGLang: #50059 https://github.com/vllm-project/vllm/issues/50059 · #41754 https://github.com/vllm-project/vllm/issues/41754 · #39246 https://github.com/vllm-project/vllm/issues/39246 · #10062 https://github.com/vllm-project/vllm/issues/10062 · SGLang #40966 https://github.com/sgl-project/sglang/issues/40966
- Training: transformers compressed-tensors https://huggingface.co/docs/transformers/en/quantization/compressed_tensors · Unsloth Gemma 4 https://unsloth.ai/docs/models/gemma-4/train · prime-rl #2362 https://github.com/PrimeIntellect-ai/prime-rl/issues/2362 · Oxen Gemma 4 pipeline https://ghost.oxen.ai/writing-a-fine-tuning-and-deployment-pipeline-isnt-as-easy-as-it-looks-gemma-4-version/ · TRL #4416 https://github.com/huggingface/trl/issues/4416 · FA2 head_dim https://github.com/Dao-AILab/flash-attention/issues/2427 · 2×H100 anchor https://arxiv.org/html/2605.25645v1
- Papers: SWE-Gym https://arxiv.org/abs/2412.21139 · SWE-smith https://arxiv.org/abs/2504.21798 · Skywork-SWE https://arxiv.org/abs/2506.19290 · SWE-Lego https://arxiv.org/abs/2601.01426 · R2E-Gym https://arxiv.org/abs/2504.07164 · OEC https://arxiv.org/abs/2512.14895 · DAgger https://arxiv.org/abs/2605.12913 · ReST-EM https://arxiv.org/abs/2312.06585 · Kimi-Dev https://arxiv.org/abs/2509.23045
- Data: SWE-Pallets-X https://www.kaggle.com/datasets/takumuhata/swe-pallets-x · SWE-Gym https://huggingface.co/datasets/SWE-Gym/SWE-Gym · SWE-smith-py https://huggingface.co/datasets/SWE-bench/SWE-smith-py · SWE-rebench https://huggingface.co/datasets/nebius/SWE-rebench · R2E-Gym https://huggingface.co/datasets/R2E-Gym/R2E-Gym-Subset
- Competitor notebooks: https://www.kaggle.com/code/denpugovkin/can-gemma-4-fix-an-unseen-repo-31b-qlora-study · https://www.kaggle.com/code/nursrijan/gemma-4-devagent-kerashub-lora-training-on-tpu · https://www.kaggle.com/code/hitarthjain0/gemma-4-dev-agent-what-moves-the-leaderboard
