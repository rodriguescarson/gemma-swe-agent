# v11 plan A: probe-first, risk-first

Planner A, written 2026-09-28 ~18:00 IST. Read-only planning: nothing was trained, served, pushed or submitted, and no
pod or kernel was started. Inputs: `docs/v11/facts_internal.md`, `docs/v11/facts_external.md`, `docs/v10/SPEC.md`,
`docs/v10/RACE2.md`, `docs/v10/race2_checklist.md`, `research/update_0928.md`, `research/own_data.md`,
`research/time_model.md`, `eval/ledger.md`, and the pod, train and kernel scripts they name.

v11 = the frozen v10 bundle + one LoRA adapter trained on Gemma-4-31B's own successful v10 trajectories. This plan
buys a yes/no on "can an adapter move the score at all" as cheaply as possible, and only spends more when the previous
gate has passed.

## Revision log

| rev | date (IST) | what changed | why |
|---|---|---|---|
| A1 | 2026-09-28 18:00 | first version | facts sweep of 09-28 |

This is a living plan. Section 10 lists the events that force a revision and what each one changes. Every revision adds
a row here; pre-registered thresholds (section 6 and `docs/v11/checklist.md`) never change after their first run, only
via dated addenda.

---

## 0. The plan in one screen

1. **Gate ladder.** Each rung is cheaper than the next and can kill the project:
   - **G1/G2, "is LoRA alive on the scorer stack".** A free Kaggle 4xL4 probe runs first: random adapter vs base, zero
     adapter vs base, LoRA-mode decode speed, and a 5-task agent smoke. A ~$10 pod probe follows: HF-vs-vLLM parity per
     module family, the k_eq_v fix, determinism by rank.
   - **S2, "does training learn anything that survives serving".** Tiny cross-fit adapters are trained on race 2's
     v10 successes. The gate is held-out NLL, measured in HF and in vLLM int4. Cost ~$25.
   - **S3, "does it do harm".** A pod screen of v10 vs v10+smoke adapter on the 74 tasks. Cost ~$18.
   - **S4/S5, "does more own data give a signal".** v10 runs on SWE-Pallets-X (8 repos, CC0) produce adapter P1, then
     P2. Each is screened on the 74 public tasks, which it never saw.
   - **S6, "ship gate".** A pre-registered, paired, faithful Kaggle 4xL4 compacting run: v11 vs v10 on the 74 valid
     tasks, 2 reps each.
2. **Spend profile.**
   - If LoRA is dead on the scorer: at most $0 (G2 fails first) or $10.5 (G1).
   - If training learns nothing transferable: at most ~$53.
   - The hard cap for all of v11 is **$250** (kill criterion K8). That leaves about $120 of the ~$404 for v10 after
     race 2 (~$30-35).
3. **Stage attachment.** One shared adapter, `v11p`, goes on **locator, fixer and verifier**. **Setup and submitter
   stay on the base model.** The final attachment is chosen per stage, from call-level KPIs (S5, section 2.3).
4. **Expected gain (honest).** P(LoRA alive on the v25 wheel) is about 0.7. P(v11 passes the Kaggle ship gate) is
   about 0.2-0.3. If it ships: +0 to +3 of 74 locally (median about +1), and +0.00 to +0.03 on the LB (0-2 of 58).
   Published self-RFT at 32B is flat to slightly positive, and our lever is format and efficiency: malformed spirals,
   repeats, s/task. **v11 alone does not reach 0.30.** The paper track also gets a result either way: first verified
   adapter on the scorer, the k_eq_v train/serve mismatch, and own-trajectory SFT against a held-out-repo control.
5. **Probe-first ordering.** Nothing gets trained before G1.1 or G2.1 passes. Nothing gets scaled before S2 and S3
   pass. The Kaggle quota is only spent on an adapter that passed a pod screen.

---

## 1. State at writing (2026-09-28 17:45 IST, 12:15 UTC)

| item | state | source |
|---|---|---|
| Gemma pods | `2wyl66nmji13p1` (2xH100, $6.98/h) EXITED, `1fs5qx44uhc3m7` (A40) EXITED. `kaggri-watch` RUNNING belongs to kaggriculture and was not touched | `list-pods` (read-only), this session |
| Kaggle L4 kernels | `g4-l4-v4` and `g4-l4-v9-eog` both QUEUED. They occupy both batch-GPU session slots | `kaggle kernels status`, 12:15 UTC |
| Spend | $96.09 through 09-28 (RunPod billing). `eval/ledger.md` shows ~$51 and is missing race 1 ($33.19) | facts_internal §6 |
| v10 | bundle built, gates green, **zero model-in-the-loop runs**. Race 2 (`pod/chain_race2.sh`) is written but not run (Carson's go) | RACE2.md §5, `eval/runs` has no `r2_*` |
| v10 trajectories | 0 | facts_internal §4.2 |
| Usable own data | 349 unique resolved Gemma-4-31B runs over 43 tasks (4 repos), all v1-v9 action space. Not v10 format | facts_internal §4 |
| LoRA on the scorer | wheel fix v23+ confirmed by code reading. **Nobody has shown adapter != base on GPU** | facts_external §1.1 |
| Training code | `train/sft.py` never took a step. Wrong template, content format, generation prompt, truncation and logits memory | facts_internal §5.1 |
| Free probe run for this plan | tiny `Gemma4ForCausalLM` (6 layers, `attention_k_eq_v`, layer 5 full attention) instantiates and runs forward+loss on CPU with the Mac `.venv` (transformers 5.17.0, torch 2.14.0). `layers.5.self_attn` has `k_proj` and **no `v_proj`**. `CompressedTensorsConfig(dequantize=True)` exists in 5.17.0 (`quantization_config.py:1114-1153`) | this session |

Consequences:
- G2 cannot start until both queued L4 kernels finish (limit of 2 queued or running batch GPU sessions,
  `research/notebooks_update_0928.md:267`).
- Carson's rule: no GPU kernel while a submission is scoring.
- Mac unit tests on a tiny Gemma 4 are possible, so every trainer and exporter change can be tested before GPU time.

---

## 2. How v11 sits on v10

### 2.1 Stage map

| stage | model in v11 (default) | why |
|---|---|---|
| setup (256 tok, T 0.2) | base | Install + READY. Short and near-deterministic, with nothing to learn. Keeping it on base limits blast radius |
| locator (1536 tok, T 1.0) | `v11p` | Repeats and grep loops live here: 11 calls median, 32-44% exact repeats (own_data §0.6) |
| fixer (2048 tok, T 1.0) | `v11p` | Edit channel. The malformed-edit spirals cost ~3.5 tasks per 51 per arm (own_data §0.3) |
| verifier (2048 tok, T 1.0) | `v11p` | Repair rounds and edits after `verify.py` verdicts |
| submitter (1024 tok, T 0.2) | base | `finalize` / `submit_patch`. A regression here zeroes a solved task |
| compaction summariser | whatever the stage uses (`v11p` inside locator/fixer/verifier) | facts_internal §1.4 EXP. Training therefore includes the base model's own captured summaries (section 4, S2) |

### 2.2 Mechanics that come with any adapter
- **LoRA mode is global.** The moment `adapters/` is non-empty, the scorer's vLLM runs with `--enable-lora --max-loras 8
  --max-lora-rank 128` for every request, base stages included (`adk_submission/server.py:716-734`). G2 measures that
  cost on 4xL4. Setup and submitter pay it too.
- **Name.** `v11p` matches `^[a-zA-Z0-9_.-]+$`, contains no `gemma4` (which would trigger the `tool_responses` role
  bug) and does not start with `o<digit>` or `gpt-5`.
- **Only two things differ between v10 and v11:** `adapters/v11p/{adapter_config.json,adapter_model.safetensors}` and an
  `adapter: v11p` line in `sub_agents/{locator,fixer,verifier}.yaml`. eval_config, prompts, helpers and sampling stay
  byte-identical. A test pins the diff.
- **Format.** bf16 tensors, keys `base_model.model.model.language_model.layers.N.<mod>.lora_{A,B}.weight`, r16/alpha32,
  about 0.24 GB (7,651,840 params per rank unit). The full-attention layers (5, 11, ..., 59) get their `k_proj` LoRA
  duplicated as `v_proj`, unless G1.2 shows vLLM already applies it to V.
- **v10 freeze rule.** v11 builds on one v10 bundle sha (`V10_FREEZE`, recorded in `data/v11/FREEZE`): the bundle that
  passes race 2, or the one Carson ships.
  - Every training row records the bundle sha that produced it.
  - `train/build_v11_data.py --require-sha` refuses rows from another sha, unless the prompt and helper diff is listed
    as behaviour-neutral in `data/v11/FREEZE` (for example an eval_config-only change such as `timeout_seconds`
    120 -> 180).

### 2.3 Per-stage attachment decision (pre-registered, applied at S5)
- The S5 screen runs `v11p` on all three work stages.
- For each stage s, compute from the body logs (thousands of calls, so precise):
  - malformed-call rate;
  - exact-repeat rate;
  - completion tokens per stage-run.
- Keep `adapter: v11p` on stage s only if:
  - at least one of these improves by ≥ 10% relative to v10;
  - and none worsens by more than 5%.
- If no stage qualifies, K6 applies.
- Separate per-stage adapters (`v11_loc`, `v11_fix`, `v11_ver`) come in only if all of these hold: v11p passed S6,
  every stage has ≥ 150 trajectories, and at least 3 weeks remain before 2026-12-03 05:29 IST (12-02 23:59 UTC).

---

## 3. Gate ladder (overview)

| step | what | pass gate (pre-registered, details in section 4) | cost USD | wall h | on fail |
|---|---|---|---|---|---|
| S0 | Mac tooling, tests, ledger, checklist | all new tests green; `bash -n` + `shellcheck` clean; exactness test on captured v10 bodies = 0 mismatches | 0 | 16 (eng) | fix; nothing is spent |
| S1a G2 | Kaggle 4xL4 LoRA probe | random-B changes top-1 ≥ 18/20; zero-B identical 20/20; decode ≤ 1.10x; startup delta ≤ 600 s; 5-task agent smoke 0 crashes | 0 (quota ~1.5 GPU-h) | 1.5 + queue | K1 or K3; cancel G1 |
| S1b G1 | pod parity probe | per family HF-vs-vLLM Δlogprob r ≥ 0.9 (k_full with dup); r16 deterministic; dequant check | 10.5 (7 if chained on race 2) | 1.5 | K1 / K2; exclude failing families |
| S2a | race 2 v10 data + exactness | 0 prompt-token mismatches; ≥ 20 trajectories per fold | 0 (race 2 is v10's spend) | 0.5 | trace-reconstruction fallback |
| S2b | smoke cross-fit training + served NLL | HF held-out NLL −3% or better; served drop ≥ 0.5x HF drop; export tests on the real adapter | 25 cap | 3 | one retry, then K4 |
| S3 | pod do-no-harm screen, 74 tasks | T ≥ C − 5 resolved; 0 crash classes; routing ≥ 99%; summaries OK ≥ 95%; s/task ≤ 1.10x | 18 (cap 25) | 2.5 | one fix + rerun, then K5 |
| S3b | Kaggle mechanics smoke, 10 tasks | adapter via private dataset; 0 crashes; bundle < 3 GiB | 0 (quota ~1 GPU-h) | 1 + queue | fix delivery path (free) |
| S4a | SWE-Pallets-X envs + oracle (CPU pod) | ≥ 200 valid tasks over ≥ 6 repos | 4 | 4 (+1-2 days eng) | public-only data; re-plan |
| S4b | P1 generation (probe 40, then all valid) | probe solve rate ≥ 10% | 31 | 4.5 | stop at probe; K6 route |
| S4c | train P1 + served NLL | as S2b, held-out repo werkzeug | 35 cap | 4 | one retry, then K4 |
| S4d | screen P1 on public 74 (fully held out) | T ≥ C − 2 and ≥ 1 signal KPI | 11 | 1.6 | K6 |
| S5 | P2 (2nd sample), train, attachment screen | P2 ≥ P1 by rule; stage rule 2.3 | 80 cap | 12 | ship P1 candidate if P1 passed S4d |
| S6 | Kaggle faithful eval, pre-registered, 2 reps | section 5 ship rule | 0 (quota ~15 GPU-h) | 72-120 wall | K7 |
| S7 | ship: adapter dataset, submission kernel, validate, submit | validator OK, < 3 GiB, byte-diff vs v10 = adapter only | 0 (7 optional re-verify) | 14 | stay on v10 |

A contingency of $35 inside the $250 cap covers one pod rerun anywhere. Before S4 starts, S4/S5 costs are re-priced with
the tokens/s measured in S2b; that re-price is a gate of its own (S4 entry).

---

## 4. Steps in detail

Conventions:
- Mac commands run from `/Users/carson/Projects/gemma-swe-agent`.
- Pod chains run from `/root/g4` via the `h100` ssh alias, started as `setsid nohup bash pod/<chain>.sh >
  /root/<chain>.out 2>&1 < /dev/null & disown`.
- Every chain ends with `pod/backup.sh <label>` (verified HF + GitHub copy) and then `runpodctl stop pod
  "$RUNPOD_POD_ID"`, on every exit path.
- Every chain has an outer `timeout` equal to its cost cap. Pod starts, Kaggle pushes, dataset uploads and submissions
  are Carson's.

### S0. Mac tooling and tests (free, ~16 h of engineering, 1-2 days)

Each item is a file to write plus the test that must pass. None needs a GPU.

1. **Ledger catch-up.** Add rows to `eval/ledger.md`: race 1 ($33.19, 2026-09-27), the v7/v8 chain attribution, and the
   09-28 RunPod billing total of $96.09. Add a "v11 spend" column so the $250 cap is checkable.
2. **Pre-registration file.** Write `docs/v11/checklist.md` with every threshold of sections 4-6 as a machine-readable
   block. `tests/test_v11_checklist.py` fails if `scripts/v11_kpis.py:KPI` differs, the way race 2 pins `replay_l4.KPI`.
   The file is frozen before the first paid v11 run.
3. **`pod/body_logger.py`** (stdlib `ThreadingHTTPServer` reverse proxy on 127.0.0.1:8200+i, forwarding to vLLM
   8100+i).
   - It appends one JSONL row per call: time, request body, response body, status, latency.
   - Optionally it injects `"return_token_ids": true` and strips the returned ids from what the client sees
     (enabled only if G1.4 shows vLLM 0.19.1 supports it).
   - It captures what traces lose: the exact system prompt and tools, **compaction-summariser requests and responses**,
     and raw completion tokens.
   - `tests/test_body_logger.py` runs against a mock upstream and checks:
     - byte-identical passthrough of status, headers and body, including vLLM's 400 context-overflow errors, which the
       harness classifies;
     - 4 concurrent clients;
     - 2 MB bodies;
     - the log row count equals the call count;
     - upstream timeout passthrough.
4. **June template on the pod.** `pod/install_june_template.sh` copies
   `docs/v11/evidence/chat_template_kaggle_v2_june.jinja` to `/root/models/g4/chat_template.jinja` and
   `tokenizer_config_kaggle_v2.json` to `tokenizer_config.json`, then checks sha256 `94899c0f...`.
   - `pod/bootstrap.sh` calls it after `MODEL_OK`.
   - `tests/test_pod_scripts.py` gets a static check that bootstrap installs the June template before any `serve*.sh`.
5. **Adapter tools.**
   - `train/make_probe_adapters.py --config /root/models/g4/config.json --out DIR --kind {randB,zeroB,family,rank}
     --families q,k_sliding,k_full_nodup,k_full_dup,v,o,gate_up,down --ranks 16,32,64,128 --scale S --seed N`. It builds
     adapters from `config.json` shapes alone, in bf16 PEFT format.
   - `train/export_adapter.py PEFT_DIR OUT_DIR --dup-kv-full` casts to bf16 and rewrites the prefix to
     `base_model.model.model.language_model.layers.N.`.
     - It duplicates `k_proj` A/B as `v_proj` on full-attention layers and drops vision or embedding keys.
     - It sets `base_model_name_or_path: google/gemma-4-31b-it-qat-w4a16-ct` and checks r and alpha against the
       tensors and the total size against a budget.
   - `tests/test_v11_adapters.py` checks on the tiny Gemma 4 config: key names, shapes per layer type, bf16, the
     duplicated `v_proj` equals `k_proj` on full layers only, no fp32, size arithmetic (r16 = 122,429,440 params, plus
     1,187,840 with the duplicated full-layer V), and that a harness `discover_adapters` + `scripts/validate.py` run on a
     v10 copy with the exported adapter prints `OK`.
6. **Data builder.** `train/v11_render.py` is promoted from `docs/v11/evidence/render.py`. `train/build_v11_data.py`
   takes either `--bodies` (logger JSONL, exact) or `--traces` (SessionTrace + bundle rebuild, the facts_internal §3.2
   rules) and emits pre-tokenised samples `{ids, labels, meta}`.
   - Two sequences per stage segment: call 1 with its own generation prompt `<|turn>model\n<|channel>thought\n<channel|>`,
     then the final prompt with loss on completions 2..n.
   - Supervise the empty thought channel exactly where the model emitted it: the logged token ids, or `completion_tokens`
     +4.
   - Tool results double-encoded as ADK does. `ensure_ascii=False` on the outer layer.
   - **Loss off** on:
     - malformed, quoted-arg and ADK-rejected calls, and their echoes;
     - exact repeats of an earlier call in the same stage;
     - calls whose observation is a tool-level error (`can't open file`, `SKILL_NOT_FOUND`, argument errors). This is
       SWE-Lego error masking.
     - Test failures seen inside a correct repro stay supervised.
   - **Drop** parallel-call steps. Drop post-compaction segments unless the logger captured the summary. Drop stages
     other than those given by `--stages locator,fixer,verifier` (plus their summariser pairs).
   - **Filters:**
     - resolved;
     - patch hygiene: no protected, scratch or vendored files;
     - predicted L4 agent time ≤ 295 s (0.99 s/call + 26.5 ms per completion token);
     - cap 3 per task, fewest calls first;
     - sequence ≤ 16,384 tokens.
   - Writes `manifest.json` with counts per repo, stage and fold, plus bundle shas.
   - `tests/test_v11_data.py` covers:
     - (a) For every call in `EV/bodies_a.json` and `EV/bodies_d.json`, the prompt ids equal `tokens(render(body))` and
       the supervised ids are exactly the completion; **0 mismatches**.
     - (b) The +4 channel case.
     - (c) The June stray `<turn|>` in a text+tool-call turn does not cut a supervised span.
     - (d) Double encoding matches `lite_llm.py` byte for byte.
     - (e) Masked classes.
     - (f) Folds share no repo.
     - (g) `--require-sha` refuses a foreign sha.
7. **Trainer.** `train/sft_v11.py`, a fork; `train/sft.py` is kept as history.
   - Inputs are the pre-tokenised samples; no chat template inside the trainer.
   - The base loads with `CompressedTensorsConfig(dequantize=True)` from `/root/models/g4`, the served int4 weights
     dequantized to bf16, `device_map=auto`, sdpa.
   - LoRA r16/alpha32 on the 7 LM projections, dropout 0.
   - **Chunked CE on supervised positions only.** Hidden states go through `lm_head`, then
     `tanh(x/30)*30` from `text_config`, in chunks of 1,024 positions.
   - Grad clip 1.0. It logs pre-clip grad norm, max |logit|, tokens/s and `max_memory_allocated` per step.
   - Held-out NLL is computed at step 0 and every 25 steps. A checkpoint is saved per epoch, and the best held-out
     epoch is kept.
   - It exports through `export_adapter.py`.
   - `pod/train_env.sh` pins `transformers==5.17.0` (same as the Mac tests) and `peft==0.21.0`, and adds
     `compressed-tensors` and `safetensors`. The 62.5 GB bf16 download is dropped.
   - `tests/test_sft_v11.py` checks on tiny `Gemma4ForCausalLM`, CPU:
     - chunked loss equals the full `model(labels=)` loss within 1e-5;
     - masked positions contribute 0;
     - only LoRA params get gradients;
     - softcap is applied;
     - one optimiser step changes only LoRA tensors.
8. **Probes and evaluators.**
   - `pod/lora_probe.py` (G1).
   - `pod/served_nll.py`: vLLM `prompt_logprobs` on the held-out supervised positions, base vs adapter name.
   - `scripts/make_lora_probe_kernel.py` (G2) writes `kernels/g4-v11-lora-probe`.
   - `scripts/v11_kpis.py`: resolved, crash classes (race-2 row 3 definitions), malformed-call rate, exact-repeat rate,
     per-stage KPIs, adapter routing share, summary validity, replayed L4 s/task, ms/token.
   - Each gets a test on the existing race-1 and e74 fixtures.
9. **Bundle and kernel plumbing.**
   - `scripts/make_variant.py submissions/v10 submissions/v11s --adapter v11s --adapter-dir DIR --adapter-stages
     locator,fixer,verifier`. The test asserts the diff against v10 is exactly the adapter lines + `adapters/`, and that
     `scripts/validate.py` passes.
   - `scripts/make_eval_kernel.py`:
     - add `--adapter-dataset OWNER/SLUG`. It copies adapters from `/kaggle/input/...` into the bundle, because
       inlining a 245 MB adapter as base64 makes a ~330 MB notebook.
     - add `--fold-map ids.json`: one vLLM server with every adapter, and one Evaluator per bundle, for cross-fit.
     - Read the budgets from the bundle's `eval_config.yaml` rather than CLI defaults (60 calls / 80 turns / 180 s ≠
       v10's 100 / 200 / 120).
   - `scripts/make_kernel.py --adapter-dataset` for the submission zip.
   - Tests cover the generated notebook source, the dataset in `kernel-metadata.json`, the budget read from the bundle,
     and the < 3 GiB check.
10. **Chains.**
    - `pod/chain_v11_probe.sh [--no-boot]` (G1, then S2b if `data/v11/smoke/` is present and G1 passed).
    - `pod/chain_v11_screen.sh` (S3, S4d, S5 screens).
    - `pod/chain_v11_gen.sh` (S4b and S5 generation).
    - Each is covered by `tests/test_pod_scripts.py`: `bash -n`, `shellcheck`, backup before stop on every path, an
      outer timeout, no `pkill -f` on the own name, and `setsid nohup` for backgrounded steps.
11. **Optional race-2 add-ons** (Carson decides before race 2 starts; the pre-registered KPIs are unchanged):
    - (a) June template on the pod (more faithful for v10 too).
    - (b) The body logger in front of both servers (`OPENAI_BASE_URL=http://127.0.0.1:820x/v1`).
    - (c) A `pod/after_race2.sh` hook called under `timeout 5400` just before `stop_pod`, running
      `chain_v11_probe.sh --no-boot`. That saves a boot, about $3.5 and half a day.
    - The hook can never block the stop. A test checks that `stop_pod` is reached when the hook fails or hangs.

Commands (Mac):
```
.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_body_logger.py tests/test_v11_data.py tests/test_v11_adapters.py tests/test_sft_v11.py tests/test_v11_checklist.py tests/test_pod_scripts.py
.venv/bin/python -m pytest -q -p no:cacheprovider tests          # whole CI tier stays green
for f in pod/chain_v11_*.sh pod/install_june_template.sh; do bash -n "$f" && shellcheck "$f"; done
GEMMA4_TOKENIZER=<SP>/v11cap/hf_w4a16/tokenizer.json .venv/bin/python train/build_v11_data.py --check-exact docs/v11/evidence/bodies_a.json docs/v11/evidence/bodies_d.json
```
**Gate S0.**
- Every command above is green.
- `--check-exact` prints `mismatches 0`.

**On failure:** fix it on the Mac. No pod start is allowed before S0 passes (standing preflight rule).

### S1a. G2: Kaggle 4xL4 LoRA probe (free; ~1.5 GPU-h plus queue)

This is the only probe on the exact scorer stack: mounted wheelhouse, Kaggle v2 model, 4xL4 TP4, the notebook's
`VllmConfig`.

The kernel, `scripts/make_lora_probe_kernel.py kernels/g4-v11-lora-probe`:
- Generates `zeroB_r16` and `randB_r16` (all 7 projections, `lora_B ~ N(0,1)`, seed 0) in-kernel with torch and
  safetensors, so no dataset is needed.
- Phase A: `VllmServer(cfg, adapter_manifest=...)` in LoRA mode.
- Phase B: server stopped and restarted without adapters.

Measured:

| id | measurement | pass |
|---|---|---|
| G2.1 | top-1 at T=0, max_tokens 1, logprobs 5, on 20 prompts (first-call prompts of v10 stages from `EV/bodies_a.json` + 10 reconstructed e74_v3 calls): `randB_r16` vs base name | differs on ≥ 18/20 |
| G2.2 | `zeroB_r16` vs base | identical top-1 on 20/20; mean |Δ top-1 logprob| ≤ 0.02 |
| G2.3 | decode ms/token at concurrency 1: 10 prompts × 512 tokens, `ignore_eos`, T=0, for (i) base name in LoRA mode, (ii) `zeroB_r16`, (iii) base name with LoRA off | (i) and (ii) ≤ 1.10 × (iii) |
| G2.4 | time to "vLLM up", LoRA mode vs off | delta ≤ 600 s |
| G2.5 | v10 copy with `adapter: v11z` (zero-B) on locator/fixer/verifier, 5 fixed tasks from the 74 valid ids (rich_3006, rich_2725, fastapi_14458, rich_3894, rich_2943; most-solved in our runs, so crashes are not confounded with hard tasks) | 0 crash classes; traces show adapter stages hitting `v11z` |
| G2.6 | sha256 of `/kaggle/input/models/.../2/model.safetensors` | recorded; compared with the pod's HF copy in G1.0 |

Commands:
```
.venv/bin/python scripts/make_lora_probe_kernel.py --slug g4-v11-lora-probe --tasks rich_3006,rich_2725,fastapi_14458,rich_3894,rich_2943
kaggle kernels push -p kernels/g4-v11-lora-probe                        # Carson; only once both queued L4 kernels finish and no submission is scoring
kaggle kernels status carsonrodrigues/g4-v11-lora-probe
kaggle kernels output carsonrodrigues/g4-v11-lora-probe -p eval/kaggle/v11_probe && .venv/bin/python scripts/v11_kpis.py --probe eval/kaggle/v11_probe
```
**Cost:** $0 in dollars. Quota is about 1.5 GPU-h, and queue time reportedly counts too (743683).

**Wall:** about 1.5 h of runtime plus a 4-9 h queue.

**On failure:**
- **G2.1 fail:** the adapter is not applied on the scorer stack. This is K1:
  - cancel G1;
  - stop LoRA work;
  - draft a repro comment for 743508 (random-B, 20 prompts, logs) for Carson to post; bug reports are published
    immediately;
  - re-open only on a new wheelhouse version.
- **G2.2 fail** (zero-B changes outputs): the LoRA path perturbs base numerics. Record it, continue to G1, and treat it
  as a risk for S6 (a v10 + zero-B arm would show it).
- **G2.3:**
  - 1.10-1.25x: continue, but the stage rule may attach to one stage only, and S6's time guardrail binds;
  - above 1.25x: K3.
- **G2.4:** 600-1,200 s is re-priced into the 12 h budget and we continue; above 1,200 s is K3.
- **G2.5 crash:** a harness-level adapter bug. Fix it for free (naming or routing) and re-run the 5 tasks only.

### S1b. G1: pod parity probe ($10.5 standalone or ~$7 chained after race 2; 1.5 h)

Runs after G2.1 passes, or chained after race 2, whichever comes first. If G2.1 has already failed, G1 is cancelled.

Chain `pod/chain_v11_probe.sh`:
1. `pod/bootstrap.sh` (env, v25 wheel, model; data fetch skipped with `NO_DATA=1`).
2. `pod/install_june_template.sh` and `pod/train_env.sh`.
3. `python pod/lora_probe.py --out /root/g4/eval/v11/g1`.
4. Backup, then stop.

GPU0 holds the HF bf16 reference (the w4a16 checkpoint dequantized, 62.5 GB). GPU1 holds vLLM TP1 with the scorer's
flags plus `--enable-lora --max-loras 8 --max-lora-rank 128 --lora-modules ...` (at most 8 per launch, 3 launches).

| id | measurement | pass |
|---|---|---|
| G1.0 | wheel member CRCs `gemma4.py`=`c8cefd56`, `model_manager.py`=`e16a1908`; template sha `94899c0f`; model sha256 vs G2.6; one `q_proj` of layers 0/5/30 dequantized by transformers vs manual LSB-first nibble unpack × amax/7.5 scale | all equal; dequant max rel err ≤ 1e-3 |
| G1.1 | as G2.1 on H100 TP1, plus `VLLM_LOGGING_LEVEL=DEBUG` log | top-1 differs ≥ 18/20; 0 lines `No LoRA weights found for module .*self_decoder`; ≥ 1 "Successfully loaded" per targeted module |
| G1.2 | family adapters q, k_sliding, k_full_nodup, k_full_dup, v, o, gate_up, down. Scale calibrated on HF so RMS Δlogprob ∈ [0.1, 0.5] nats. Pearson r of per-token Δlogprob (adapter − base), HF vs vLLM `prompt_logprobs`, on ≥ 2,000 tokens of 3 reconstructed e74_v3 sequences | r ≥ 0.9 for every family; `k_full_dup` ≥ 0.9 (if `k_full_nodup` is also ≥ 0.9, vLLM already applies K to V and `--dup-kv-full` is switched off) |
| G1.3 | ranks 16/32/64/128 at realistic scale (Δ RMS ~0.3): 5 prompts × 256 greedy tokens × 5 repeats + 1 server restart; the base model measured the same way | mismatches(adapter r) ≤ mismatches(base); r16 must pass |
| G1.4 | one request with `return_token_ids: true` | recorded (enables raw-token logging; not a gate) |
| G1.5 | H100 decode ms/token, base vs LoRA mode | recorded (screen only; L4 decides) |

Outputs:
- `eval/v11/g1/{g1.json, vllm_debug.log.gz, parity_<family>.csv}`, backed up to HF
  `rodriguescarson/gemma4-agent-artifacts/backups/<ts>-v11probe` and GitHub branch `pod/<ts>-v11probe`.
- No weights worth keeping: the probe adapters are seeded and rebuildable.

**Cost:** 1.5 h × $6.98 = $10.5. Chained after race 2 (no boot, model present): about 1.0 h, $7.

**On failure:**
- **G1.1 fail:** K1 (same actions as G2.1). A G2.1 pass with a G1.1 fail means the pod stack is not the scorer's
  (wheel or template). Fix the pod, rerun ($5).
- **G1.2:**
  - A family below 0.9 is dropped from `target_modules`. It is recorded in `docs/v11/checklist.md` addenda.
  - If fewer than 3 families pass: K2.
  - If `k_full_dup` fails while `k_sliding` passes: exclude `k_proj` on layers 5, 11, ..., 59
    (`export_adapter.py --drop-k-full`).
- **G1.3:** r16 fails but r8 passes: train r8. Both fail: K2 (#50059 on our stack). Otherwise cap the rank at the
  largest one that passes; the plan stays at r16 unless S5 needs more capacity.

### S2a. Smoke data from race 2 (free for v11; 0.5 h Mac)

Source: `eval/runs/r2_v10_{1,2}` (traces, patches, results), plus `eval/runs/r2_v10_*/bodies*.jsonl` if add-on (b) ran.

Expected: about 31-35 of 74 resolved per run, so about 60-70 resolved runs, and about 50 trajectories after the cap of 3
per task.

Folds, by repo, so every public task is scored by an adapter that never saw its repo:
- `xr` excludes rich (trained on fastapi + requests + httpx rows) and is used on the 42 rich tasks.
- `xf` excludes fastapi/requests/httpx (trained on rich rows) and is used on the 32 others.

```
.venv/bin/python train/build_v11_data.py --runs eval/runs/r2_v10_1 eval/runs/r2_v10_2 --bodies-glob 'eval/runs/r2_v10_*/bodies*.jsonl' \
  --bundle submissions/v10 --require-sha $(cat data/v11/FREEZE | head -1) --stages locator,fixer,verifier \
  --cap-per-task 3 --max-len 16384 --folds 'xr=rich;xf=fastapi,requests,httpx' --heldout-frac 0.2 --out data/v11/smoke
```

**Gate S2a:**
- With bodies: 0 prompt-id mismatches against logged `prompt_token_ids`, or against `render(body)` if ids are not
  available.
- Without bodies: the trace-reconstruction increments are exact in ≥ 99% of continuation pairs (the facts measured
  100%).
- Each fold has ≥ 20 trajectories and ≥ 100k supervised tokens.

**On failure:**
- Mismatch: fix the builder (free).
- Too few trajectories:
  - add the 42 Kaggle e74 trajectories under their own bundles' prompts. This is pipeline validation only, off-policy.
  - If race 2 has not run within 3 days of S0 passing, run a v10-only data chain instead: 74 tasks × 2 samples, the
    same faithful settings, about $15, a v11 cost.

### S2b. Smoke training, cross-fit, plus served NLL (cap $25; ~3 h)

Chained after G1 in `pod/chain_v11_probe.sh` when `data/v11/smoke/` was synced before start. The auto-gate: G1 JSON must
say PASS, else the chain skips to backup and stop.

```
python train/sft_v11.py --data data/v11/smoke/xr_train.jsonl --heldout data/v11/smoke/xr_heldout.jsonl --base /root/models/g4 \
  --rank 16 --alpha 32 --lr 1e-4 --epochs 2 --grad_accum 8 --max_len 16384 --out /root/train_out/v11s_xr   # then xf
python train/export_adapter.py /root/train_out/v11s_xr/best /root/adapters/v11s_xr --dup-kv-full
python pod/served_nll.py --adapters v11s_xr=/root/adapters/v11s_xr,v11s_xf=/root/adapters/v11s_xf --heldout data/v11/smoke --out eval/v11/s2
```
Held-out split: the other fold's rows, which are a different repo.

**Pre-registered gate S2b:**
- **T1 health.**
  - loss finite at every step;
  - max |logit| ≤ 30.0;
  - median pre-clip grad norm ≤ 10;
  - no OOM at 16,384 tokens;
  - tokens/s and peak memory recorded.
- **T2 learned.** HF held-out NLL on supervised tokens (other repo) drops ≥ 3% relative to step 0, for both folds.
- **T3 survives serving.**
  - The vLLM int4 served held-out NLL drop is ≥ 0.5 × the HF drop.
  - Per-token Δ correlation HF vs vLLM is ≥ 0.8.
- **T4 export.** `tests/test_v11_adapters.py::test_real_adapter` passes on both exports: keys, bf16, `v_proj` duplicate,
  0.24-0.25 GB.

**Artifacts off the box before stop:**
- `/root/adapters/v11s_{xr,xf}` (about 0.25 GB each, bf16) and `/root/train_out/*/train.log`.
- These go to HF `rodriguescarson/gemma4-agent-artifacts/backups/<ts>-v11smoke/train_out_adapters.tgz` via
  `pod/backup.sh`, then `hf download` to `/Users/carson/Projects/gemma-swe-agent/data/v11/adapters/`.
- The final message names both paths and sizes.

**Cost:**
- boot 0.5 h (0 if chained);
- env 0.2 h;
- 2 × (load 0.2 h + train 0.3-1.2 h);
- export + NLL 0.4 h.
- That is 1.5-3.2 h, $10.5-22. The chain timeout is 3.5 h ($25).

**On failure:**
- T1: fix on the Mac with a test (free), rerun (≤ $10).
- T2: one retry at lr 2e-4 and 3 epochs (≤ $10). A second fail is K4.
- T3: re-run G1.2 parity with the real adapter. Mismatch fixable in export: fix and retest; otherwise K4.
- The first S2b also yields the **measured tokens/s** that re-prices S4 and S5.

### S3. Pod do-no-harm screen (≈ $18, cap $25; 2.5 h)

Chain `pod/chain_v11_screen.sh --arms C=v10,T=v11s --fold-map data/v11/smoke/fold_map.json`. Settings:
- The faithful race-2 settings: `G4_COMPACTION=1 G4_L4_SCALE=1.7 G4_NO_EDITABLE=1 FAITHFUL=1`.
- June template, body logger on both GPUs, 2 tasks per GPU.
- GPU0 serves v10 with LoRA off (as the scorer does for a bundle without adapters).
- GPU1 serves LoRA mode with `v11s_xr` and `v11s_xf`.
- T runs `submissions/v11s_xr` on the 42 rich ids and `submissions/v11s_xf` on the other 32.
- Preflight (`LORA_GATE=1`, pointed at `v11s_xr`) and the canary go first.
- The C arm doubles as another v10 data run, with bodies.

**Pre-registered gate S3 (do no harm, 1 run each):**
- resolved T ≥ C − 5;
- 0 crash classes in T (race-2 row 3);
- ≥ 99% of locator/fixer/verifier requests carry an adapter name, and 0% of setup/submitter requests do;
- ≥ 95% of compaction summaries written by adapter stages are non-empty text with no `<|tool_call>`;
- replayed L4 s/task T ≤ 1.10 × C.
- Format deltas (malformed, repeat, calls/task, completion tokens/task, per stage) are recorded and **not gated** here.
  Smoke data is tiny.

**Cost:** boot 0.5 h + preflight 0.3 h + arms 1.75 h = 2.55 h, about $18.

**On failure:** diagnose on the Mac from traces and bodies (free). One fix and rerun of T only is allowed (about $10). A
second fail is K5.

### S3b. Kaggle mechanics smoke (free; ~1 GPU-h plus queue; parallel with S4a)

This proves the real delivery path before S6.
1. Carson uploads `data/v11/adapters/` as a **private** Kaggle dataset (`kaggle datasets create -p data/v11/kaggle_ds`),
   named for example `carsonrodrigues/g4-v11-adapters`.
2. Build the kernel: `scripts/make_eval_kernel.py submissions/v11s_xr g4-v11-mech --ids data/v11/mech10.txt
   --adapter-dataset carsonrodrigues/g4-v11-adapters --fold-map data/v11/smoke/fold_map.json`, with 5 rich and 5 fastapi
   ids.

**Gate S3b:**
- the adapters land in the bundle;
- `validate_single_declared_model` passes;
- the bundle is < 3 GiB;
- 0 crash classes;
- ms/token is within G2.3's bound.

**On failure:** the delivery path is fixed for free before S6. Without it, S6 cannot run.

### S4. Diverse own data from SWE-Pallets-X (entry gate: S1-S3 passed; re-price with measured tokens/s)

**Entry gate (re-price).** Project S4 + S5 cost with the S2b tokens/s. If the projection exceeds $150:
- drop the separate first-call samples (they are about 35% of tokens);
- or cap at 1 epoch.

Then write the re-price into this plan's revision log before starting.

- **S4a. Environments and oracle.** CPU pod, 32 vCPU, $0.96/h, about 4 h, **$4**, plus 1-2 days of Mac engineering.
  - Write `scripts/pallets/fetch.py`: `kaggle datasets download takumuhata/swe-pallets-x`, 10.3 GB; only `tasks.jsonl`
    and snapshots.
  - Write `scripts/pallets/build_envs.py`: a per-instance uv venv with era-matched Python 3.10-3.13, following their
    `verify.py` / `era_pin.py`.
  - Add a `G4_VENV_MAP` hook in `scripts/run_eval.py`, so the swegemma sandbox uses that venv.
  - Tests: `tests/test_pallets_adapter.py` on 3 instances.
  - Oracle: gold passes and the empty patch fails under our harness gives the valid set `data/v11/pallets_valid.txt`.
  - Hold out **werkzeug** (43 tasks) for held-out NLL and format checks.
  - **Gate:** ≥ 200 valid tasks across ≥ 6 repos.
  - **On fail:** re-plan data to public multi-sample only (74 × 4 samples, about $25). Record that the repo-diversity
    lever is lost.
- **S4b. P1 generation** (`pod/chain_v11_gen.sh`; v10 at `V10_FREEZE`; faithful settings so helper footers show
  L4-equivalent clocks; body logger; 2 tasks per GPU; about 4.5 h; **$31**):
  1. Probe: 40 random valid tasks, 1 sample. **Gate:** solve rate ≥ 10%. If not, stop the chain (backup, stop) and
     decide on the Mac. The K6 route is to not scale.
  2. Then every other valid non-werkzeug task gets 1 sample.
  - Expected yield: about 70-120 trajectories at 20-35%.
- **S4c. Train P1 + served NLL** (cap **$35**, about 4 h). Same command as S2b with `--data data/v11/p1/train.jsonl
  --heldout data/v11/p1/werkzeug.jsonl --out /root/train_out/v11p1`, followed by export and `served_nll.py`.
  - **Gate:** T1-T4 of S2b, with T2 measured on werkzeug.
  - **On fail:** one retry, then K4.
  - Weights are backed up as in S2b; the paths go in the message.
- **S4d. Screen P1** on the public 74 (T arm only, split over both GPUs, about 1.6 h, **$11**). P1 has never seen a
  public repo, so this is a clean out-of-repo test. C is the mean of the three v10 runs (race 2 × 2 + S3), allowed only
  if sha, template and wheel are unchanged; otherwise rerun C (+$7).
  - **Pre-registered signal gate:** resolved T ≥ mean(C) − 2, **and** at least one of:
    - malformed-call rate ≤ 0.8 × C;
    - exact-repeat rate ≤ 0.85 × C;
    - replayed L4 s/task ≤ 0.92 × C;
    - resolved ≥ mean(C) + 3.
  - **On fail:** K6. Record it as a negative result for the paper track.

### S5. Scale once, pick attachment (cap $80; ~12 h pod over 1-2 sessions)

1. P2 generation: a second sample on the same valid set (about $27). Optionally, the **privileged self-teacher** on
   tasks unsolved in both samples: same v10 bundle, `thinking_config` on for work stages, 2 samples. Thoughts are
   stripped and only L4-feasible successes kept. This is still gemma-4-31b's own output (743964), and costs about $10.
   It only runs if P2 data has fewer than 150 trajectories.
2. Train P2 on P1+P2 data (the same recipe, re-priced; about $25-35).
3. Screen P2 with the adapter on all three stages (about $11). Choose between P1 and P2 by the rule: higher resolved;
   within ±1, lower malformed+repeat rate; still tied, P1 (cheaper, already screened).
4. Apply the per-stage attachment rule of section 2.3 to the chosen adapter. That produces `submissions/v11` =
   `V10_FREEZE` + `adapters/v11p` + `adapter: v11p` on the qualifying stages.

**Gate S5:**
- the chosen candidate passes S4d's signal gate;
- the stage rule keeps ≥ 1 stage;
- `scripts/validate.py submissions/v11` prints `OK`;
- the diff test against v10 passes.

**On fail:** if P1 passed S4d, it goes to S6 alone. Otherwise K6.

### S6. Kaggle faithful evaluation (section 5; free; ~15 GPU-h; 3-5 days wall because of queues)

### S7. Ship (Carson's calls; ~14 h including scoring)

1. `kaggle datasets version -p data/v11/kaggle_ds -m v11p` (private), holding the exact adapter bytes evaluated in S6.
   The sha256 is recorded in `data/v11/FREEZE`.
2. Build the submission kernel: `scripts/ship.sh submissions/v11 g4agent-sub-v11 submit --adapter-dataset
   carsonrodrigues/g4-v11-adapters`. The kernel copies the adapter into `submission.zip`.
3. Push the kernel (Carson), run `kaggle kernels output`, unzip into a temp dir, then check:
   - `scripts/validate.py` prints `OK`;
   - unpacked size < 3 GiB (3,221,225,472 B);
   - the adapter sha equals the S6 sha;
   - the byte-diff against the v10 submission is the adapter only.
4. Submit with `scripts/submit_at.sh g4agent-sub-v11 0001 "v11p: v10+adapter"` at 00:01 UTC (05:31 IST), when no other
   submission is scoring.
5. Record the LB score in the ledger. The LB is not a gate: at 58 tasks, 1 run has noise of ±2.5 tasks.

Optional: a $7 pod re-verification of the final adapter (G1.1 + served NLL on werkzeug) if the dataset bytes were
re-exported after S6. Normally they were not, and the step is skipped.

---

## 5. Evaluation protocol (the ship gate, pre-registered)

Frozen into `docs/v11/checklist.md` before the first S6 kernel. Changes only by dated addendum.

- **Arms.**
  - C = `V10_FREEZE` (no adapters, so LoRA is off, exactly as v10 would be scored).
  - T = `submissions/v11`: the same sha plus `adapters/v11p` and the `adapter:` lines. `tests/test_v11_bundle.py` pins
    that diff.
  - The adapter bytes are the ones that will ship (the S7 dataset version).
- **Tasks.** The 74 ids in `data/kaggle_valid_ids.txt`: fastapi 31, rich 42, requests 1. P1/P2 never saw these repos,
  so this is out-of-repo, like the hidden set.
- **Environment.**
  - Kaggle 4xL4 via `scripts/make_eval_kernel.py`: host notebook recipe, wheelhouse mounted at run time,
    `VllmConfig(... enable_lora=True, max_loras=8, max_lora_rank=128, tp=4, gpu_memory_utilization=0.90)`.
  - Compaction `EventsCompactionConfig(15, 2, 14336, 5)`, context cache as in the notebook, subprocess sandbox,
    sequential tasks.
  - Budgets read from each bundle's `eval_config.yaml` (v10: 5 min / 120 s / 100 calls / 200 turns, or the freeze's
    values).
  - The wheel CRCs (`gemma4.py`, `model_manager.py`) and `pip freeze` are recorded per kernel. **All 4 kernels must
    show the same wheel CRCs.** If a wheelhouse update lands mid-protocol, the pair is re-run.
- **Order and replication.** C1, T1, then the kill check, then T2, C2. The interleaving spreads time-of-week and platform
  drift. At most 2 GPU kernels are queued at once, and none runs while a submission is scoring.
- **Reuse.** A v10 Kaggle run made for v10's own ship decision can serve as C1 or C2 only if bundle sha, wheel CRCs and
  kernel code are identical.
- **Primary endpoint.** Resolved count summed over 2 reps (148 paired task-runs per arm).
- **Ship rule S1.** The two-run difference has an SD of about 3 tasks per 74, so +6 is about 1.4 SD. This matches race
  2's convention. All must hold:
  - T − C ≥ +6 over 148;
  - no rep with T_k < C_k − 2;
  - exact sign test on per-task wins/losses reported.
- **Ship rule S2, efficiency route: eligible, Carson's call, flagged lower confidence.** Hidden tasks are
  cap-saturated (own_data §0.7), so time saved converts into solves. All must hold:
  - 0 ≤ T − C < +6;
  - T mean agent s/task ≤ 0.85 × C;
  - T malformed-call rate ≤ 0.5 × C.
- **Guardrails** (all required for S1 or S2):
  - 0 crash classes in T;
  - T empty patches ≤ C + 2;
  - T malformed-call rate ≤ C;
  - LoRA-mode startup delta ≤ 600 s;
  - T mean wall s/task ≤ 1.05 × C;
  - projected hidden-set wall for N = 130: startup + 130 × 309.6 s × (T/C wall ratio) must be ≤ 11.5 h. v4 took
    10.4 h, and an overrun errors the whole run.
- **Kill check after rep 1.** T1 < C1 − 4, or any crash class > 0: stop, do not run rep 2, diagnose.
- **Report.** `docs/v11/s6_report.md` covers:
  - per-task paired wins and losses with the exact sign test;
  - s/task and ms/token;
  - per-stage format KPIs;
  - compaction summary validity;
  - the LoRA startup delta;
  - union of solves;
  - the LB transfer estimate (0.34 × local).

---

## 6. Kill criteria for abandoning LoRA

Any one ends LoRA work for the main track. Each is recorded, and the negative result goes to the paper track.

| id | condition | where measured |
|---|---|---|
| K1 | Adapter not applied on the current wheelhouse: random-B top-1 differs on < 18/20 prompts, or any `self_decoder ... skipping` line. Re-open only on a new wheelhouse | G2.1 / G1.1 |
| K2 | Fewer than 3 of the module families reach parity r ≥ 0.9 even with the `v_proj` duplication, or neither r16 nor r8 is deterministic | G1.2 / G1.3 |
| K3 | LoRA mode on 4xL4: decode slowdown > 25%, or startup delta > 1,200 s | G2.3 / G2.4 |
| K4 | Nothing learned that survives serving: held-out NLL drop < 3% after one retry, or served/HF transfer < 0.5 unfixable in export | S2b / S4c |
| K5 | Harm: resolved T < C − 5, or crash/summariser breakage not fixed after one retry | S3 |
| K6 | No signal at Pallets scale: P1 (and P2, if run) fails the S4d signal gate, or the stage rule keeps no stage | S4d / S5 |
| K7 | The Kaggle faithful eval fails both ship rules for the best candidate, and one recipe change (lr, epochs or attachment) also fails | S6 |
| K8 | Budget and calendar: v11 pod spend reaches $250 before a ship decision; no adapter past S3 by 2026-10-12 IST; no S6 decision by 2026-11-15 IST (main deadline 2026-12-03 05:29 IST = 12-02 23:59 UTC) | ledger |
| K9 | Rules: the host restricts adapters or self-training, or changes model/wheel so that G1/G2 must be redone and they fail | forum 743964 / wheelhouse |

After a kill:
- v10 stays the main-track line.
- The pod goes down.
- Weights and logs are already off the box (each chain backs up before stopping).
- A report goes to `docs/v11/` that lists what was measured.

---

## 7. Budget

| bucket | planned | cap |
|---|---|---|
| spent through 09-28 | $96.09 | |
| race 2 (v10's spend, not v11) | ~$30-35 | |
| S1b G1 | $10.5 (or $7 chained) | |
| S2b smoke | $10.5-22 | $25 |
| S3 screen | $18 | $25 |
| S4a CPU pod | $4 | |
| S4b-d P1 | $31 + $11-35 + $11 | $77 |
| S5 P2 | $27 + $25-35 + $11 (+$10 teacher) | $80 |
| S7 optional re-verify | $7 | |
| contingency (one rerun anywhere) | | $35 |
| **v11 total** | **~$160-215 expected** | **$250 hard** |

Worst-case spend if LoRA is dead: $0-10.5. If training learns nothing transferable: about $36-53. Kaggle quota: about
1.5 (G2) + 1 (S3b) + 15 (S6) ≈ 17.5 GPU-h plus queue time.

Before every paid step, the chain's header echoes cost, expected gain and the gate into `eval/progress.log`, and a row is
added to `eval/ledger.md` with a v11-spend column.

---

## 8. Risks (and what in this plan catches each)

1. **The fix works in code but the adapter still does nothing.** Caught by G2.1 on the real stack, before a dollar.
2. **k_eq_v silent mismatch on 10/60 layers:** V gets no delta in vLLM. Caught by G1.2 (`k_full_dup` vs `k_full_nodup`)
   and fixed at export.
3. **Train/serve numeric gap.** QAT bf16 vs RTN int4 is 6.7% elementwise. The fix is to train on dequant(served int4);
   G1.0 checks the dequant, and S2b T3 measures transfer.
4. **LoRA mode slows every stage** (8×128 slots, extra cudagraphs). G2.3/G2.4 measure it; S6's time guardrails and the
   12 h projection bind.
5. **The summariser under an adapter emits tool calls or empty text,** which breaks compaction and zeroes the task. The
   captured base summaries are in the training data; S3 and S6 check summary validity.
6. **Self-RFT gives nothing at 32B** (SWE-Gym 19.0 -> 19.7; OpenHands 15.3 -> 8.7). This is the most likely outcome.
   The S4d signal gate and K6 stop spend early. Pallets adds 8 repos (SWE-smith: diversity transfers).
7. **Overfitting to public repos, and leakage in the eval.** Cross-fit by repo for the smoke; P adapters never see
   public repos; werkzeug is held out inside Pallets. No stored solutions are used as lookup.
8. **v10 changes after data generation** (prompts, helpers). The freeze sha, `--require-sha`, and trigger T2 in
   section 10.
9. **Kaggle capacity.** Queues of 4-9 h, queue time charged to quota, a 2-session limit, no kernels during scoring. So
   G2 goes first while pod steps proceed, S3b runs in parallel with S4a, and S6 is scheduled 3-5 days ahead of the
   decision date.
10. **#50059 rank non-determinism on compressed-tensors int4.** G1.3 checks it. The plan stays at r16.
11. **Pod spend drift** (idle pods, watcher death). Every chain stops the pod itself after a verified backup; no
    watcher-only shutdowns; an outer `timeout` per chain equals its cap.
12. **Delivery path.** A 245 MB adapter cannot be inlined in the kernel notebook the way bundles are today. The private
    dataset route is tested in S3b, before S6 and S7.
13. **Proxy risk in race 2** (add-on b). It is optional and Carson's call. It is tested byte-for-byte against a mock
    upstream, including 400 errors. Without it, S2a falls back to trace reconstruction and drops post-compaction
    segments.

---

## 9. Rules compliance

- **Training data.** Only gemma-4-31b-it-qat-w4a16-ct's own outputs, which is allowed (743964, 09-28). The
  Qwen3-Coder-derived nebius set is excluded until the host rules on other models' outputs.
- **External data.** SWE-Pallets-X is public, free and CC0-1.0. Only its tasks and environments are used; the
  trajectories are ours.
- **Reproducibility (winner obligation, Apache-2.0).** All of these are in the repo:
  - the data builder, trainer, exporter, probe scripts and chains;
  - `data/v11/FREEZE` (bundle sha, adapter sha, wheel CRCs);
  - the dataset manifests.
  Weights are on HF (private until a prize is accepted).
- **Disclosure timing** (CLAUDE.md competition rules):
  - The G1/G2 outcome is a bug-report-class finding, published immediately:
    - a draft comment for 743508 ("fix verified / not verified on v25 with random-B logprobs");
    - if G1.2 confirms it, the k_eq_v `v_proj` gap, as an issue on the harness side.
  - The recipe and data results are held for the paper track (deadline 2026-11-13 05:29 IST, if the track is defined
    at 23:59 UTC; check the page).
  - Carson posts.

---

## 10. Update protocol (living plan)

This plan is revised, with a row in the revision log, on each of these triggers:

| trigger | what changes |
|---|---|
| T1 race 2 finishes | Record r2_v10 yield (resolved, trajectories per fold). If v10 passes, set `V10_FREEZE`. If v10 fails its ship rule, v11's base becomes the revised v10.x: S2a data counts only if the revision is prompt- and helper-neutral, otherwise the smoke uses it as pipeline-only data and S4 generation waits for the new freeze |
| T2 v10 bundle edits (e.g. `timeout_seconds` 120 -> 180, prompt fixes) | eval_config-only: record in `FREEZE` as behaviour-neutral. Prompt or helper edits: new freeze sha; data generated before it is re-rendered only for neutral diffs, otherwise excluded |
| T3 host rules on other models' outputs (742807 / 743964) | If allowed: add a teacher-data branch (re-rendered into v10 format, with the same gates), which is the lever the literature says moves 32B. It does not bypass G1/G2 |
| T4 someone posts a v25 LoRA re-test or a scored adapter | Positive: G2.1 is still run (our wheel and date), but G1 may be shortened to G1.2 + G1.3. Negative with a repro: treat as a probable K1, run G2 only |
| T5 new wheelhouse version (compare CRCs, not names) | Re-run G2.1-G2.4 on it. If mid-S6, re-run the affected pair |
| T6 Kaggle quota or queue facts | Re-schedule S3b/S6. If quota < 20 GPU-h a week, S6 drops to 1 rep plus a pod confirmation, and the ship rule is re-stated before running |
| T7 each gate result | Fill in the measured values, move the stage status, re-price S4/S5 after S2b |
| T8 leaderboard movement (e.g. someone at ≥ 0.20 with an adapter) | Re-read their public work for recipe or rank information; no gate is skipped |

Status board (update in place):

| step | status | measured |
|---|---|---|
| S0 | not started | |
| G2 | blocked: two L4 kernels QUEUED (12:15 UTC 09-28) | |
| G1 | not started (pod EXITED) | |
| S2a | blocked on race 2 | |
| S2b-S7 | not started | |

---

## 11. Open questions and UNVERIFIED items this plan depends on

- Whether the v25 wheel applies adapters (G2.1/G1.1).
- Whether `k_proj` LoRA reaches V on full layers without duplication (G1.2).
- The LoRA-mode decode tax on 4xL4 (G2.3).
- Whether vLLM 0.19.1 honours `return_token_ids` (G1.4). The logger works without it.
- Kaggle v2 vs HF `model.safetensors` byte identity (G2.6 / G1.0).
- Kaggle's size limit for a pushed notebook; this plan avoids it with the dataset route.
- The weekly 4xL4 quota and whether queue time is charged (743683, unanswered).
- The scorer's real `gpu_memory_utilization` (0.80 vs 0.90) and compaction interval (5 vs 15). Neither changes the
  ranking of v10 vs v11, since both arms run under the same kernel.
- SWE-Pallets-X solve rate for v10, and env validity under our harness (S4a/S4b probes).
- Training throughput on 2xH100 with `device_map=auto` at 16k (S2b measures; the band is 486-2,000 tok/s).
