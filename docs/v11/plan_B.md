# v11 plan B: data first. LoRA on Gemma-4-31B's own v10 trajectories

Planner B, 2026-09-28 ~18:45 IST. Status: **PLAN, living** (update rules in §3, changelog in §13).
Inputs: `docs/v11/facts_internal.md`, `docs/v11/facts_external.md`, `docs/v10/SPEC.md`, `docs/v10/RACE2.md`,
`docs/v10/race2_checklist.md`, `research/update_0928.md`, `research/time_model.md`, `eval/ledger.md`.

Nothing in this file starts a pod, pushes a kernel or dataset, submits, or spends money. Every such step is marked
**Carson's go**. Times are IST; UTC in brackets only where Kaggle defines the time.

Angle of this plan: get the training data right before anything else. That means clean, deduplicated, short,
passing trajectories, recorded as the exact tokens the scorer's model sees, from more repos than we have now, and
a measured answer to "does more data help".

---

## 0. Bottom line

1. **The trajectories we already have cannot train the v11 we would ship.** I recounted
   `docs/v11/evidence/inventory_rows.jsonl`:

   | filter | trajectories | tasks |
   |---|---|---|
   | model runs scanned | 1,367 | 79 attempted |
   | resolved, at least one agent call | 397 | 43 |
   | unique (task, call-sequence hash) | 349 | 43 (fastapi 20, rich 18, requests 4, httpx 1) |
   | no malformed call, no parallel-call step, no unparsed text | 225 | 40 |
   | same, and every prompt under 14,336 tokens | 165 | 36 |
   | same as row 4, capped at 3 per task, fewest calls first | 107 (2,632 calls, 256,546 completion tokens) | 40 |

   Every one of them has three problems at once. The action space is pre-v10 (35-54% raw `run_command`, no v10
   helpers, no setup or submitter stage). 307 of the 349 came from pods with the July template and no compaction.
   And all of them are on public tasks, so training on them contaminates the 74-task gate that decides shipping.
   **Plan B trains on none of them.** They become fixtures for the data builder's tests (§6.9).
2. **v11's data is generated, not mined.** v10 itself runs on the pod on **SWE-Pallets-X v4**: 476 execution-verified
   tasks from 8 repos outside the public set (pytest 132, sympy 129, click 109, werkzeug 43, flask 29, jinja2 29,
   markupsafe 4, itsdangerous 1). The licence is CC0-1.0, the tasks are already in competition format, 73% of fixes
   touch one source file, the median patch is 18 lines, and 164 tasks (34%) are from 2026, likely after the model's
   training cutoff. Collection uses the scorer's settings (June template, compaction at 14,336, L4 clock, v10's own
   `eval_config.yaml`).
3. **Samples are exact by construction.** A stdlib recording proxy between the harness and vLLM stores every call's
   request body and, if vLLM returns them, its prompt and completion token ids. Training samples are those token ids,
   so there is nothing to reconstruct: system instructions, tool declarations, double-encoded tool results, the
   thought-channel prefix and compaction summaries are all in the recording. The June-template renderer
   (`docs/v11/evidence/render.py`) becomes a cross-check and the fallback.
4. **The gate stays clean.** No public task and no public repo enters training. The 74-task Kaggle L4 gate is
   therefore also a repo-held-out test, which is the generalisation the ~120 hidden private-repo tasks need.
5. **One shared adapter, `v11a` (r16), on locator, fixer and verifier.** Setup and submitter stay on the base model.
   Per-stage adapters cost the same training compute (the data is partitioned, not repeated), but each adapter then
   sees a third of the data. They become an option in iteration 2, once each stage has at least 600 segments.
6. **Free gates first, then two pod sessions, then Kaggle.** Kaggle 4×L4 LoRA check on the v25 wheel (free), tools
   and tests (free), Pallets oracle in Linux Docker (free). Pod session 1: HF-vs-vLLM parity probe, then three data
   rounds ($40-73). Pod session 2: training smoke, D25/D50/D100 training, export parity, pod screen ($50-85). Then
   the paired Kaggle L4 gate against v10 (free quota). Planned pod spend is $90-158. With a conditional iteration 2
   and a reserve, the ceiling is about $290, against about $380 left after race 2.
7. **Expected gain is modest and is priced that way.** Own-output SFT at ~32B is a format and efficiency lever
   (SWE-Gym: 19.0 → 19.7 → 19.7; adding 868 own successes to teacher data dropped 15.3 → 8.7). Central estimate
   **+3 tasks per 74** on the faithful L4 gate, range 0 to +6. P(an adapter passes the ship rule) is about 20%. It will
   not take 0.12 to 0.30 by itself. The data-scaling curve and the parity findings go to the paper track either way.

---

## 1. What changes versus the assumptions in the task

| Assumption | What holds | Consequence here |
|---|---|---|
| 611 resolved runs over 79 tasks | 349 unique over 43 tasks, 4 repos | Generate data (§5 S7-S9) |
| Old runs are usable SFT data | Wrong action space, July template on pods, all on the eval tasks | Fixtures only |
| `train/sft.py` is a starting point | Never trained a step; July template, string contents, no first-call generation prompt, head truncation, full-vocab logits, fp32 export | New `train/v11/sft_v11.py` that trains on token ids (§5 S2) |
| The Kaggle eval kernel can carry an adapter | `scripts/make_eval_kernel.py` base64-embeds every bundle file into the notebook (lines 16-21). A 245 MB adapter cannot ride that way | New `--adapters-dataset` flag that mounts a private Kaggle dataset (§5 S15) |
| The pod serves what the scorer serves | `pod/bootstrap.sh` downloads the HF-main July template (18,683 B); `pod/serve.sh` has no LoRA flags unless `LORA` is set | `pod/serve_v11.sh` installs the June template (sha256 `94899c0f…`) and LoRA flags (§5 S2) |

---

## 2. How v11 sits on v10

### 2.1 The bundle

`submissions/v11` = the frozen base bundle (v10 if race 2 passes, §3) plus exactly:
- `adapters/v11a/adapter_config.json` and `adapters/v11a/adapter_model.safetensors` (bf16, r16, about 250 MB);
- one line `adapter: v11a` in `sub_agents/locator.yaml`, `sub_agents/fixer.yaml` and `sub_agents/verifier.yaml`.

`model:` stays `gemma-4-31b-it-qat-w4a16-ct` on every stage (the single-model rule reads only `model:`).
`tests/test_v11_bundle.py` asserts that the tree diff against the frozen base is exactly those files and lines, and
that `scripts/validate.py` prints `OK model=` with unpacked size under 3 GiB.

### 2.2 Which stage gets the adapter

| Stage | Adapter | Why | Training data |
|---|---|---|---|
| setup | base | One or two install calls at T 0.2. Nothing to learn, and every call through an adapter is exposed to LoRA risk. Revisit only if race 2 shows helper availability under 98% | none |
| locator | `v11a` | Most calls (1,069 of 2,632 in the capped old set); exploration loops and malformed calls live here | resolved runs, locator segments |
| fixer | `v11a` | Edit-channel format errors (malformed `edit_file` 52-67% in our thinking-off traces) | resolved runs, fixer segments |
| verifier | `v11a` | Repair rounds, `submit_patch` discipline | resolved runs, verifier segments |
| submitter | base | One `submit_patch` call | none |
| compaction summariser | follows its stage | ADK sends the summariser request to the stage's model, adapter included (`bodies_adapter.json`: `_summarizer` went to `v11_fix`) | summariser calls from resolved runs, as their own samples |

### 2.3 Side effects that apply to every stage

- **LoRA mode is global.** Any adapter in the bundle makes the scorer pass `--enable-lora --max-loras 8
  --max-lora-rank 128` (`adk_submission/server.py:716-734`). Setup and submitter run on the base weights, but inside a
  LoRA-mode server. S4 measures the decode cost of that for base requests and for adapter requests.
- **Time.** Hidden tasks are cap-bound (v4 took about 308 s per task, about 10.4 h for ~120 tasks; SPEC §9.2). A slower
  decode therefore does not lengthen the run: it means fewer calls inside the same 300 s. The startup cost does add to
  the run: the host's adapter run took about 663 s against our 383 s (different runs, UNVERIFIED as a causal delta).
  Worst case for N=130: 663 + 130 × 309.6 s = 11.4 h, under 12 h but closer. S4 measures it; the gate is in §8.
- **Adapter names.** `v11a` (and `v11_loc`, `v11_fix`, `v11_ver` if per-stage) contain no `gemma4`, do not start
  with `o<digit>` or `gpt-5`, and match `^[a-zA-Z0-9_.-]+$`. `tests/test_v11_export.py` pins this.

---

## 3. Inputs this plan waits on, and how it is kept up to date

The plan is updated in place whenever one of these changes. Each update adds a dated line to §13 and never
rewrites a pre-registered threshold (a changed threshold goes into §13 with its reason; the original stays).

| # | Input | Current state (2026-09-28 18:45 IST) | Blocks | What changes when it lands |
|---|---|---|---|---|
| T1 | Race 2 verdict (`docs/v10/race2_checklist.md` §4) | Not run; chain written, Carson's go | S7 onward | Pass: base bundle = `submissions/v10`, sha256 recorded in S1. Fail: base = whatever Carson ships next; S7 waits until it is frozen, because the adapter is trained on that bundle's prompts and tools |
| T2 | Late v10 edits (`timeout_seconds` 120 → 180 is recommended in `research/update_0928.md` §3.1; prompt or helper tweaks) | Open | S7 | Before S7: free, just re-freeze. After S7: prompt-text-only changes are re-rendered into the samples (the builder substitutes the stage instruction and re-tokenises through `render.py`); any change to tool schemas or helper output formats means a new Round A on 30% of tasks before training |
| T3 | Race 2 serves the July template (pod `bootstrap.sh`) | Open, v10's call | val set quality | If race 2 can install the June template before GO, the r2_v10 traces become exact validation data. If it cannot, they are re-rendered with June for validation NLL only, and the difference is noted |
| T4 | Optional: race 2 through the recording proxy | Open, v10's call; only if the proxy tests pass before GO, and it changes no KPI | nothing | Gives exact validation bodies for free |
| T5 | Anyone shows adapter logprobs differing from base on the v25 wheel (743508, 743964) | Nobody as of 17:10 IST | nothing | S4 still runs (our adapter shapes and k_eq_v layers are the point) |
| T6 | Wheelhouse hash change (vLLM or adk_submission rebuilt in place) | v25 current | S4, S15 | Re-run S4 (free) against the new hashes |
| T7 | Host ruling on other models' outputs (742807, 743964) | Pending | iteration 2 | If allowed: add a teacher arm in S17 (the largest published SFT gains come from teacher data: 7.0 → 20.6 with 491 trajectories; SWE-smith 7.0 → 40.2 with 5k). The nebius set would still need re-wrapping into v10's action space |
| T8 | Scorer compaction interval (743752) | Unanswered; kernels use 15, README says 5 | nothing | Paired gate is robust to it; data collection uses v10's race setting (5) |
| T9 | Kaggle model version (template) | v2, June template 16,934 B | S7, S15 | New version: re-render, re-check the sha in `serve_v11.sh` |
| T10 | Ledger | `eval/ledger.md` stops 2026-09-26 22:10 IST; billing says $96.09 spent | every paid step | S0 |

---

## 4. Budget

| Line | USD |
|---|---|
| Cap | 500 |
| RunPod billing to 2026-09-28 (facts_internal) | 96.09 |
| Race 2, v10's (my estimate: 296 task-runs at race 1's 128 task-runs per pod-hour, plus boot and preflight, about 3.3 h at $6.98) | ~25 |
| **Left for v11** | **~380** |
| Pod session 1 (S5-S9) | 40-73 |
| Pod session 2 (S11-S14) | 50-85 |
| Iteration 2, conditional (S17) | 50-90 |
| Reserve (re-runs, one failed chain) | 40 |
| **v11 ceiling** | **~290** |

Rates used: 2×H100 pod at $6.98/h; race 1 ran 51 tasks in 48 min on one GPU at 2 tasks per GPU, so the pod does
about 128 task-runs per hour, about $0.055 each. Kaggle 4×L4 runs cost quota, not money; each 74-task run is about
3.4-3.6 h of it (`time_model.md` §1.2).

---

## 5. Steps

Each step: what, exact commands and scripts, the gate (stated before the run), cost, wall clock, what happens on
failure. Paid steps also state the odds the measurement lands, per the probe-before-paying rule.

### S0. Ledger and budget (free, 0.5 h)
- Add the missing rows to `eval/ledger.md`: race 1 (pod r02i1c2nbk4v6p, $28.18 by timing), v7/v8 at the billed
  $13.00 + $33.19 for 2wyl66nmji13p1, and a "billing reconciliation 2026-09-28" row at $96.09 total.
- Gate: ledger total equals billing within $2. Failure: record the gap as a row; plan against the billing figure.

### S1. Freeze the base (free, 0.2 h; waits on T1)
- `scripts/pack_bundle.py submissions/v10 /tmp/v10.zip` twice; record the sha256 in `docs/v11/base_freeze.txt`
  together with `eval_config.yaml` and the five `configs/gen_*.yaml` contents.
- Gate: two packs identical; `scripts/validate.py submissions/v10` prints `OK model=`. Failure: fix in v10 first.

### S2. Tooling and tests (free, about 10 h of agent time; can start now)

New files (stdlib only where noted; nothing here goes into a bundle except through S15's bundle builder):

| File | What | Tests |
|---|---|---|
| `train/v11/record_proxy.py` (stdlib) | `--listen 127.0.0.1:820N --upstream http://127.0.0.1:810G --log eval/v11/proxy/laneN.jsonl`. Forwards `POST /v1/chat/completions`; adds `"return_token_ids": true` to the body when `--token-ids` is set; logs `{t0, t1, lane, body, response, prompt_token_ids, token_ids}`; strips the added fields from the response so LiteLLM sees what it would have seen; passes `GET /v1/models`, errors and status codes through unchanged; forwards streaming bytes untouched and logs body only | `tests/test_v11_proxy.py`: fake upstream; byte-identical responses minus added fields; 4 concurrent calls; 4xx/5xx passthrough; one log line per call; ≤ 5 ms added per call |
| `train/v11/build_sft.py` | Proxy logs + run dirs + frozen bundle → samples (§6.6). Splits a stage wherever call k's prompt is not call k-1's prompt + completion + tool result (compaction). Fallback path renders bodies with `render.py` and tokenises | `tests/test_v11_builder.py`: renders `bodies_a.json`, `bodies_d.json`, `bodies_adapter.json` byte-exact against `rendered_v10_locator_call4.txt`; reproduces the recon counts (2,391/2,391 continuation pairs on e74_v3); double JSON encoding of swegemma tool results and single encoding of skill tools; the June template's stray `<turn|>` in text+tool-call turns; masks of §6.5; a compaction split |
| `train/v11/pick_trajs.py` (stdlib; not `select.py`, which shadows stdlib) | Trajectory filters, dedupe and caps (§6.4, §6.7); re-times every call with `scripts/replay_l4.py`'s L4 model | `tests/test_v11_pick.py`: each filter on hand-made traces; cap and ordering; deterministic output |
| `train/v11/make_test_adapters.py` (stdlib + numpy) | Writes PEFT-format bf16 safetensors by hand (header + raw bf16 bytes): `zeroB`, `randB_r16` (all 7 projections), `konly_full` (k_proj only, full layers), `konly_full_dupv` (same plus a v_proj copy), `randB_r64`, `qo_l0` (the host sample's shape) | shapes and key names against `submissions/v4_lora_test` header |
| `train/v11/lora_ab.py` | Against any OpenAI-compatible vLLM: prompt logprobs (`/v1/completions`, token-id prompts, `prompt_logprobs`) for base and each adapter; T=0 determinism (5 repeats × 3 prompts × 256 tokens); single-stream decode tok/s at 4k and 12k context | mock server test |
| `scripts/make_lora_ab_kernel.py` | Kaggle 4×L4 notebook: wheelhouse install with a CRC check of `gemma4.py` (c8cefd56) and `lora/model_manager.py` (e16a1908); builds the test adapters inside the kernel (no dataset upload); starts `VllmServer` without adapters, runs `lora_ab.py`, restarts with adapters, runs it again; writes one JSON | notebook compiles; no base64 blobs over 1 MB |
| `train/v11/parity_hf_vllm.py` | Pod: HF model dequantised from the served w4a16 files on GPU1, vLLM TP1 on GPU0, same test adapters; per-position Δlogprob (adapter − base) on both sides; Pearson r and slope per module family | CPU test of the statistics on synthetic arrays |
| `train/v11/sft_v11.py` | Trains on token ids from `build_sft.py`. Base from `/root/models/g4` via `CompressedTensorsConfig(dequantize=True)` (transformers ≥ 5.17; fallback `train/v11/dequant_w4a16.py`). Chunked CE on supervised positions only, with the final logit softcap read from `text_config`. Target modules from S5's decision. r16, α32, lr 1e-4, cosine, 3% warmup, epoch 1 ordered shortest first. Eval NLL every 25 steps on `val_pub` and `pal_val`; keeps the best checkpoint. Logs loss, grad norm, max\|logit\|, tokens/s, peak memory. `--gpu N` single-GPU mode or `device_map=auto` | `tests/test_v11_sft_math.py` (where torch exists; the pod smoke runs it first): chunked CE equals full CE on a tiny random config to 1e-5; labels align with supervised spans |
| `train/v11/export_adapter.py` | PEFT dir → bf16 safetensors with keys `base_model.model.model.language_model.layers.N.{self_attn,mlp}.<mod>.lora_{A,B}.weight`; on layers 5, 11, …, 59 either writes `v_proj` as a copy of `k_proj` (`--kv dupv`) or asserts no `k_proj` (`--kv nok`); rewrites `base_model_name_or_path` | `tests/test_v11_export.py`: key regex, dtype bf16, A is r×in and B is out×r, r/α match config, total ≤ 3 GiB, name rules of §2.3 |
| `scripts/pallets_to_harness.py` | Pallets download → `data/v11/pallets/{tasks.jsonl, snapshots/, graphs/, embeddings/, pins/<id>.txt, wheels/}` in the harness schema; era pins from the dataset's `era_pin.py` logic with cutoff = `created_at` | `tests/test_v11_pallets.py`: schema equals `data/raw/tasks.jsonl` keys; pins parse; no public task id or repo |
| `scripts/run_eval.py` change | New switch `G4_TASK_PINS_DIR`: when set, the sandbox install uses `-c pins/<id>.txt`. Default unset leaves v10 and race 2 byte-for-byte unchanged | regression test: setup script text identical with the switch unset |
| `pod/serve_v11.sh` | One vLLM per GPU (TP1, as race 2), June template and tokenizer config copied in and sha-checked, LoRA flags from `LORA_MODULES`, then one `record_proxy.py` per lane | `tests/test_v11_chains.py` |
| `pod/chain_v11_s1.sh`, `pod/chain_v11_s2.sh` | Sessions 1 and 2 (S5-S9, S11-S14). Every step writes START/DONE lines to `eval/progress.log` and its own `<step>.out`; background steps use `setsid nohup … & disown`; every exit path runs `pod/backup.sh` (extended to `eval/v11`, `data/v11/sft`, `train_out/v11`, sizes in the manifest) and then `runpodctl stop pod` | `tests/test_v11_chains.py`: `bash -n`, `shellcheck`, backup-then-stop on every exit path, no `pkill -f`, gates read the pre-registered numbers from `train/v11/gates.py` |
| `train/v11/gates.py` | Every threshold in this file as constants | a test fails if a constant differs from this document's table (same pattern as `replay_l4.KPI`) |
| `scripts/make_v11_bundle.py` | Frozen base + adapter dir + stage list → `submissions/v11` | `tests/test_v11_bundle.py` |

- Gate: `.venv/bin/python -m pytest -q tests` green (CI tier), plus `bash scripts/linux_test.sh` green, plus
  `bash -n` and `shellcheck` on the new `.sh` files.
- Failure: fix and add a regression test per bug. No paid step starts before this is green.

### S3. Pallets ingest and Linux oracle (free, about 4 h; network for the download is Carson's go)
- `kaggle datasets download takumuhata/swe-pallets-x -p data/v11/pallets_raw` (a download, not a push), then
  `.venv/bin/python scripts/pallets_to_harness.py data/v11/pallets_raw data/v11/pallets`.
- Oracle in Linux Docker on the Mac (python:3.12-slim, `--cpus 2 --memory 4g`, pure-python wheels, which covers
  these repos): `scripts/oracle.py eval --tasks data/v11/pallets/tasks.jsonl …` with gold patches, and the
  no-patch run from the same harness.
- Gate (pre-registered): at least **150** tasks where gold resolves, no-patch fails and gold verification takes
  ≤ 40 s, over at least **5** repos. No single repo above 40% of the passing set after the per-repo cap of §6.7.
- Failure: under 150 → add SWE-rebench (CC-BY-4.0, docker-free venvs) as a second source in S3b (free, about 1 day of
  work) before any data spend. Under 60 even with it → K5 (§9).

### S4. Does an adapter change outputs on the scorer's stack? (free Kaggle quota, 1.5 GPU-h; 2-24 h wall with queues; kernel push is Carson's go)
- `.venv/bin/python scripts/make_lora_ab_kernel.py g4-lora-ab-v25` then `kaggle kernels push` (Carson). Never while
  one of our submissions is scoring, and at most 2 GPU sessions queued.
- Gates (pre-registered in `train/v11/gates.py`):

  | # | Check | Pass |
  |---|---|---|
  | G4.1 | `zeroB` against base, same LoRA-mode server | max \|Δlogprob\| ≤ 1e-3 on every position |
  | G4.2 | `randB_r16` against base | mean \|Δlogprob\| ≥ 0.05 nats and \|Δ\| > 1e-3 on at least 50% of positions |
  | G4.3 | `konly_full_dupv` against `konly_full` | outputs differ (vLLM applies a v_proj LoRA on k_eq_v layers when present) |
  | G4.4 | T=0 determinism, r16 and r64: 5 repeats × 3 prompts + one server restart | divergent generations no more than base's own count + 2 of 15 |
  | G4.5 | Decode tok/s, single stream, 4k and 12k context: LoRA-mode base requests and adapter requests | ≥ 0.90 × the no-LoRA server |
  | G4.6 | Server startup with adapters, gpu_memory_utilization 0.90, 32k context | ≤ 900 s |
  | G4.7 | KV capacity reported by vLLM with 8 × 128 LoRA slots | ≥ one 32k sequence |
- Failure: G4.1/G4.2/G4.6 fail → K1. G4.5 between 0.80 and 0.90 → continue, but S14 must show the adapter pays for it
  (§9 K2). G4.3 fails → training must exclude `k_proj` on the 10 full-attention layers (`--kv nok`). G4.4 fails at r64
  only → stay at r16.

### S5. Pod session 1a: boot and HF-vs-vLLM parity probe ($8, 1.2 h; the pod start is Carson's go)
- `pod/chain_v11_s1.sh` via `pod/chain_boot.sh` (with `serve_v11.sh`). `pod/train_env.sh` gains transformers ≥ 5.17
  and no longer downloads the 62.5 GB QAT bf16 weights: training dequantises the same 23.3 GB w4a16 files vLLM serves.
- `python train/v11/parity_hf_vllm.py --adapters randB_r16,konly_full_dupv --samples 3 --tokens 2048`.
- Gate: Pearson r ≥ 0.9 and slope in [0.8, 1.25] for each family: q/o, k (sliding layers), k with v copy (full
  layers), MLP. Also the HF dequantised weights of 3 sampled matrices equal a manual decode of the checkpoint
  (group 32, scale = amax/7.5, LSB-first nibbles) exactly.
- Odds this lands: about 75%.
- Failure: a failing family is dropped from the targets (decided now, before any training). If both MLP and q/o fail
  → K3; the chain backs up and stops (session cost about $9).

### S6. Pod session 1b: authoritative Pallets oracle ($2, 0.3 h)
- The S3 oracle again on the pod's environment (`G4_TASK_PINS_DIR` set), 8 in parallel, CPU only.
- Gate: agrees with S3 on at least 95% of tasks. The pod list is the one used from here on.
- Failure: under 95% → use the pod list anyway, log the disagreeing ids for diagnosis; under 150 passing → stop the
  chain (backup, stop) and go to S3b.

### S7. Round A: v10 × 1 on every oracle-passing task ($14-22, 2.0-3.1 h for 250-400 tasks)
- Four lanes: 2 processes per GPU (Carson's limit), each at concurrency 1 through its own proxy port, task list sharded
  round-robin by repo. Faithful switches as race 2: `G4_COMPACTION=1 G4_L4_SCALE=1.7 G4_NO_EDITABLE=1 FAITHFUL=1`.
  `OPENAI_BASE_URL=http://127.0.0.1:820N/v1 bash pod/run_eval.sh submissions/<base> v11A_laneN 5 100 200 120 1 $IDS_N`
  (budgets from the frozen base's `eval_config.yaml`).
- Canary first (5 tasks): proxy adds under 5 ms per call; `return_token_ids` is accepted by vLLM 0.19.1 (UNVERIFIED
  until then; without it the builder uses the render path).
- Gates (pre-registered):
  - proxy coverage: calls with a logged response ÷ LLM calls in traces ≥ 99%;
  - render parity: June render of the logged body tokenises to the logged `prompt_token_ids` on ≥ 99% of calls;
  - **yield: at least 60 clean resolved trajectories (§6.4) over at least 4 repos.**
- Odds the yield gate lands: about 70% (public pod resolve rates are 28-41%; Pallets' PR-body statements and sympy
  make it harder; 20% of 300 tasks is 60).
- Failure: coverage or parity under 99% → one in-chain retry after the canary diagnosis is written to the log; still
  under → stop. Yield 40-59 → continue to S8 but drop D25 (§7). Yield under 40 → K5: stop data spend, back up, stop.

### S8. Round B: a second sample on every task ($14-22, 2.0-3.1 h)
- Same command, run id `v11B_laneN`, seed offset. Runs automatically when S7 passes (no idle gap).
- Purpose: a second distinct trajectory on solved tasks (caps allow up to 3) and pass@2 on the rest.
- Gate: none to continue; it reports the pass@1 → pass@2 curve per repo (§7).

### S9. Round C: unsolved tasks only, two collection policies ($0-18, 0-2.4 h)
- Runs only if Round B solved at least 8% of the tasks Round A missed (pre-registered). Otherwise skip to backup.
- Half of the unsolved tasks (random, stratified by repo): plain v10, third sample. Other half: v10 with thinking on
  for locator, fixer and verifier (`include_thoughts: true`, `thinking_budget: 2048`, `max_output_tokens` 6,144
  because the budget is not enforced (DCV measured 6,144 thought tokens in one turn); own outputs, allowed). The
  builder strips the thought text and keeps the actions (a privileged self-teacher; tagged `think` so it can be
  ablated). Their recorded prompts are thinking-mode renderings, so these samples always go through the render
  path with `enable_thinking: false`, and their L4 re-timing counts only the non-thought tokens.
- Report: new tasks solved per dollar for each policy. Pre-registered use: `think` trajectories enter D100 only if
  their per-call masks pass at the same rate as plain ones (±5 points) and their re-timed no-think L4 projection
  fits the cap.
- End of session 1: `pod/backup.sh v11s1` (proxy logs, run dirs, oracle list; sizes named in the manifest), then
  `runpodctl stop pod`. No weights exist yet.

### S10. Build the datasets (free, Mac, about 3 h)
- `.venv/bin/python train/v11/pick_trajs.py --runs eval/v11/rounds --out data/v11/pick.jsonl --cap-per-task 3
  --max-repo-share 0.30 --l4-cap-s 290`
- `.venv/bin/python train/v11/build_sft.py --pick data/v11/pick.jsonl --proxy eval/v11/proxy --bundle
  submissions/<base> --template docs/v11/evidence/chat_template_kaggle_v2_june.jinja --out data/v11/sft`
- Splits (seed 11): `pal_test` = 15% of oracle-passing tasks stratified by repo, plus all of markupsafe and
  itsdangerous; `pal_val` = 10% of the rest; D100 = everything else; D50 ⊂ D100 and D25 ⊂ D50 by task, stratified
  by repo. `val_pub` = v10 on-policy resolved trajectories on public tasks (race 2 r2_v10, or any v10 Kaggle L4 run),
  used only for NLL, never for training.
- Gate (pre-registered): D100 ≥ 150 trajectories, ≥ 90 tasks, ≥ 5 repos, ≥ 300k supervised tokens; `val_pub` ≥ 30
  trajectories; the funnel table (counts after each filter of §6.4 and §6.5) written to
  `data/v11/sft/manifest.json` with file hashes.
- Failure: D100 under 150 → train D50 and D100 only if D100 ≥ 100, else go to S17's data route before training.

### S11. Pod session 2a: boot and training smoke ($6, 0.9 h; pod start is Carson's go)
- `pod/chain_v11_s2.sh`. First `pytest tests/test_v11_sft_math.py` in the train env, then
  `python train/v11/sft_v11.py --data data/v11/sft/D25.jsonl --smoke 30 --gpu 0` and the same with `device_map=auto`.
- Gates: loss on an 8-sample overfit set falls below 30% of its start within 30 steps; no NaN; finite grad norms;
  max\|logit\| ≤ 30.0 (the softcap is live); peak memory ≤ 78 GB per GPU at 16,384 tokens. Measured trained
  tokens/s goes into `eval/v11/cost.txt` with the projected S12 cost.
- Odds: about 85%.
- Failure: OOM at 16,384 → retry at 12,288 (compaction keeps prompts under 14,336 anyway; the few longer samples are
  dropped and counted). Two failed attempts → K6.

### S12. Train D25, D50, D100 ($17-52, 2.5-7.5 h)
- Single-GPU mode if it fit in S11: D100 on GPU0 while D25 then D50 run on GPU1 (0.75 of D100's tokens, so GPU1
  finishes first and takes the export of D50 while GPU0 finishes).
  Otherwise sequential with `device_map=auto`.
- One epoch each. A second epoch of D100 only if its `val_pub` NLL still fell over the last 25% of epoch 1.
- Cost rule (pre-registered): if S11's projection for this step exceeds **$80**, drop D25; if it still exceeds $80,
  train D50 and D100 on `--max-len 12288`.
- Gate: D100's best `val_pub` NLL ≤ 0.97 × base NLL on the same supervised tokens; `pal_val` NLL ≤ 0.90 × base.
- Odds: about 85%.
- Failure: D100 misses the `val_pub` gate but hits `pal_val` → the adapter learned Pallets, not the format: K7.

### S13. Export and serving parity of the trained adapters ($4, 0.6 h)
- `python train/v11/export_adapter.py train_out/v11/D100 adapters_out/v11a --kv <S5 decision>` (and D50).
- Serve with `LORA_MODULES="v11a=… v11a50=…"`; `lora_ab.py --nll data/v11/sft/val_pub.jsonl` gets vLLM's NLL
  from prompt logprobs; determinism check as G4.4.
- Gate: vLLM NLL within 3% of HF NLL on `val_pub` for each adapter; determinism as G4.4.
- Failure: K7 for that adapter.

### S14. Pod screen ($17, about 2.5 h)
- Same session, same servers (base plus both adapters loaded; `max_loras 8`), faithful switches, 2 tasks per GPU.
- Selection on Pallets, not on the gate set: `pal_test` (about 45-60 tasks) × {base bundle, v11 with D50, v11 with
  D100}. Then the public 74 × {base bundle, the selected adapter}, as a kill check only.
- Selection rule: higher resolved on `pal_test`; tie → D100.
- Gates (pre-registered; the pod does not decide shipping):
  - kill if the selected adapter resolves fewer than base − 3 on the public 74, or any crash class > 0;
  - advance only if, on the public 74, malformed calls per task ≤ 0.6 × base, exact-repeat calls per task
    ≤ 0.8 × base, empty patches ≤ 2, and summariser outputs are sane (no tool-call tokens, ≤ 2k tokens) in every
    compaction event.
- Odds of advancing: about 50%.
- End: `pod/backup.sh v11s2` with adapters (name each and its size in the message: about 250 MB per r16 adapter),
  checkpoints, logs and run dirs; also `hf upload` of `adapters_out/` to the private artifacts repo; then
  `runpodctl stop pod`.

### S15. Faithful Kaggle L4 gate (free quota, ~14 GPU-h; 2-3 days wall; uploads and pushes are Carson's go)
- `python scripts/make_v11_bundle.py submissions/<base> adapters_out/v11a submissions/v11 --stages locator,fixer,verifier`
- `kaggle datasets create -p adapters_out/v11a` as a **private** dataset (Carson).
- `scripts/make_eval_kernel.py` gets `--adapters-dataset <owner/slug>`: the kernel copies `adapters/` from
  `/kaggle/input/...` into the bundle dir before `discover_adapters`. Test: the generated notebook embeds no
  `.safetensors` and lists the dataset in `kernel-metadata.json`.
- Four kernels on the 74 valid ids, in ABBA order: `g4-l4-v10-a`, `g4-l4-v11-a`, `g4-l4-v11-b`, `g4-l4-v10-b`.
  Protocol and ship rule in §8.

### S16. Ship decision (free)
- `python train/v11/gate_report.py eval/kaggle/g4-l4-v1{0,1}-{a,b}` prints every row of §8 with PASS/FAIL.
- Submission is Carson's call. Pausing daily submissions during S15 keeps the no-GPU-kernels-while-scoring rule.

### S17. Iteration 2, conditional ($50-90, about 1 week)
Runs only if S14 advanced or S15 was inconclusive, at least $100 of the v11 budget remains, and the date is on or
before 2026-11-10 IST. Pick by §7's verdict:
- **More data** (the scaling rule of §7 says it pays): SWE-rebench subset for new repos (S3b), then v11a itself
  collects on unsolved Pallets and new tasks (on-policy, expert iteration); retrain on the union.
- **Better recipe** (volume saturated): per-stage adapters `v11_loc`, `v11_fix`, `v11_ver` if each stage has ≥ 600
  segments; locator credit (§6.4 last row); stricter repeat masks.
- **Teacher data** if T7 allows it.
Then S13-S16 again.

### S18. Paper-track material (free, before 2026-11-12)
Data funnel, pass@k by repo, NLL vs data size, parity results (including the k_eq_v finding), the gate result
whatever it is. Held until submission per the disclosure rule in §12, except bug reports.

---

## 6. Data recipe (exact)

### 6.1 Sources
- Train: SWE-Pallets-X v4 tasks that pass S6's oracle, minus `pal_test` and `pal_val`. Later, if needed, SWE-rebench
  (CC-BY-4.0).
- Never train: any of the 129 public tasks or their 4 repos; the old 349 trajectories; the nebius/Qwen3-Coder set
  (not cleared, off-format); anything from a model other than gemma-4-31b.

### 6.2 Collection settings
The frozen base bundle, unmodified, with its own `eval_config.yaml`; June template; compaction interval 5,
threshold 14,336, overlap 2, retention 5; `G4_L4_SCALE=1.7`; `G4_NO_EDITABLE=1`; 2 tasks per GPU; vLLM flags as the
scorer notebook's `VllmConfig` except TP1. Graph files ship with Pallets, so the harness prompt includes the
"Code Intelligence Tools" section as it does on the scorer.

### 6.3 What is recorded
Per call: the request body exactly as LiteLLM sent it, the response, prompt and completion token ids (if S7's canary
shows vLLM returns them), timestamps and lane. Per task: `task_results.jsonl`, trace, patch, test output.

### 6.4 Trajectory filters (all must hold)
| # | Filter | Why |
|---|---|---|
| F1 | Resolved by the harness verification | own successes only |
| F2 | Final patch touches no protected file and adds no scratch or vendored file (race-2 KPI 7 and 8 definitions, `replay_l4.is_protected`) | do not teach junk that happened to pass |
| F3 | No crash class of race-2 KPI 3 | |
| F4 | Re-timed with `replay_l4.py`'s L4 model, the task ends at or before 290 s, and no stage exceeds its budget | the trajectory must be one the scorer could have produced |
| F5 | No parallel-call step | the scorer does not support parallel calls |
| F6 | Masked calls (§6.5) are at most 20% of the trajectory's calls | too noisy to learn from |
| F7 | Every call joined to a proxy record (or render-parity exact) | exactness |
| F8 (off by default; S17 option) | Locator credit: a locator segment from an unresolved run counts if its `plan` names a file of the task's gold patch and its repro was reported as failing on the original | more locator data, graded by gold labels on training tasks only |

### 6.5 Per-call loss masks (the call stays in context; only its loss is zeroed)
- The tool call fails the stage's tool schema (extra keys, missing required, literally quoted arguments) or ADK
  rejected it (INVALID_ARGUMENTS, unknown tool).
- The helper answered with a usage error (`usage:` or `ERROR:` on argument parsing).
- An exact repeat of one of the stage's previous 5 calls (same tool, same arguments).
- A completion that ended by length (`finish_reason: length`).
- Everything else is supervised, **including** the empty thought-channel prefix when the model emitted it (visible in
  the token ids; about half of continuation calls in e74_v3), the tool-call tokens and the stop token
  (`<eos>`, `<turn|>` or `<|tool_response>`, ids 1, 106, 50).

### 6.6 Samples
Per stage segment (a segment breaks at compaction):
- (a) first call: its prompt ids + its completion ids, loss on the completion;
- (b) if the segment has at least 2 calls: the last call's prompt ids + its completion ids, loss on the spans of
  completions 2..n inside that prompt plus the last completion. The prefix property makes the spans exact.
- Each compaction-summariser call: its prompt + completion, loss on the completion.
- Setup and submitter segments are not used (§2.2).
Size: about 35k tokens per trajectory (3 stages × (3.3k first-call sample + about 8k final sample)); D100 of
200-300 trajectories is 7-11M tokens per epoch, of which about 0.5-0.75M are supervised.

### 6.7 Dedupe, caps, order
- Unique by (task, normalised call sequence); near-duplicates (same tools and same edited files in the same order)
  keep the shortest.
- At most 3 trajectories per task, fewest calls first, then shortest projected L4 time (SWE-Gym caps 2, SWE-smith 3;
  difficulty had no effect in SWE-smith).
- No repo above 30% of trajectories (sympy and pytest are the risk).
- Epoch 1 in increasing sample length (turn-count curriculum: +2.2 in SWE-Lego); later epochs shuffled.

### 6.8 Splits
By task, never by trajectory (§5 S10). `pal_test` is used once per candidate, for selection in S14.

### 6.9 Tests that pin the recipe
`tests/test_v11_builder.py` and `tests/test_v11_pick.py` use real bytes: the three v10 body captures, the e74_v3
recon, 5 old resolved traces as fixtures, and (once S7 has run) 3 recorded Pallets tasks, one of them with a compaction.

---

## 7. Measuring data scaling

Three curves, all written to `eval/v11/scaling.md`:
1. **Yield.** Unique tasks solved against samples per task (pass@1, @2, @3) per repo, and clean trajectories per
   dollar for each round and collection policy (plain vs `think`).
2. **Fit.** `val_pub` and `pal_val` NLL of D25, D50, D100 at one epoch, against log(trajectories). The `val_pub`
   curve is the one that matters: in-format, out-of-repo.
3. **Behaviour.** `pal_test` resolved, malformed calls and repeats for D50 and D100 in S14.

Pre-registered rule for buying more data in S17: more data is worth buying if
`NLL(D50) − NLL(D100) ≥ 0.5 × (NLL(D25) − NLL(D50))` on `val_pub` (not yet saturating) **and**
`resolved_pal_test(D100) ≥ resolved_pal_test(D50)`. Otherwise volume is saturated at this recipe, and iteration 2
changes the recipe instead. If D25 was dropped (S7 or S12 rules), the rule uses D50 vs D100 and the S14 behaviour
curve only, and says so.

---

## 8. Evaluation protocol (pre-registered; frozen when S15 starts, addenda only)

- **Arms.** `v10` = the frozen base (S1 sha256). `v11` = the same tree plus the adapter and three YAML lines
  (`tests/test_v11_bundle.py`).
- **Tasks.** The 74 ids in `data/kaggle_valid_ids.txt` (fastapi 31, rich 42, requests 1). None of their repos is in
  training.
- **Environment.** The official Getting Started recipe in `scripts/make_eval_kernel.py`: wheelhouse v25 (or the
  current hash, T6), 4×L4 TP4, subprocess sandbox, sequential tasks, compaction 14,336 at the same interval for both
  arms, budgets from the bundle's `eval_config.yaml` (identical in both arms).
- **Runs.** Two per arm, ABBA order, at most 2 GPU sessions at once, none during one of our submissions' scoring.
- **Primary metric.** Resolved tasks summed over the two runs, paired by task.
- **Ship rule: every row must pass.**

  | # | Row | Pass |
  |---|---|---|
  | 1 | Σ resolved v11 vs v10 | v11 ≥ v10 + 6 (over 148 task-runs a side) |
  | 2 | Per run | each v11 run ≥ the same-letter v10 run − 3 |
  | 3 | Crashes (race-2 KPI 3 classes) | 0 |
  | 4 | Empty patches | ≤ 2 per run |
  | 5 | Decode speed from per-call timings | v11 median tokens/s ≥ 0.90 × v10 |
  | 6 | Startup and the 12 h cliff | vLLM up ≤ 900 s, and startup + 130 × 309.6 s ≤ 11.5 h |
  | 7 | Malformed calls per task | v11 ≤ v10 |

- **Inconclusive band.** Row 1 margin +3 to +5 with rows 2-7 passing: one more pair (`-c` runs) if quota and
  calendar allow; ship if the three-run margin is at least +8. Otherwise no ship.
- **If quota allows only one run per arm.** Ship only if v11 ≥ v10 + 5 on the 74 and rows 3-7 pass; otherwise
  inconclusive.
- **Reported, not gating.** Exact sign test on discordant tasks; per-stage calls, repeats and malformed rates;
  compaction events and summary lengths; per-task time. The public LB never decides (a two-run difference has an SD
  of about 2.5-2.7 tasks on 58).
- **Why +6.** Same margin as race 2's pre-registered rule; the SD of a two-run-sum difference on 74 tasks is about 4,
  so +6 is about 1.5 SD one-sided.

---

## 9. Kill criteria for LoRA

| # | When | Condition | Action |
|---|---|---|---|
| K1 | S4 | `randB` leaves logprobs unchanged (G4.2), `zeroB` is not identity (G4.1), or the server cannot start with an adapter (G4.6) | LoRA is dead on the scorer. No pod spend. Re-check only after a new host fix (T6) |
| K2 | S4, S14 | LoRA-mode decode < 0.80 × no-LoRA, or startup > 1,200 s. Between 0.80 and 0.90: kill unless S14 shows mean calls to resolution ≤ (measured ratio) × base's | Stop |
| K3 | S5 | Both MLP and q/o families fail parity after the k_eq_v options | Stop; session 1 ends at about $9 |
| K4 | S4, S13 | r16 adapter less deterministic than base by more than 2 of 15 generations | Stop (rank increases are already excluded by G4.4) |
| K5 | S3, S7 | Under 60 oracle-passing tasks from all sources, or under 40 clean resolved trajectories in Round A, or proxy/render parity under 99% after one retry | Stop data spend |
| K6 | S11 | Two failed smoke attempts | Stop ($12 max) |
| K7 | S12, S13 | D100 `val_pub` NLL above 0.97 × base, or vLLM NLL more than 3% from HF, for both D50 and D100 | Stop this round |
| K8 | S14 | Selected adapter below base − 3 on the public 74, or any crash | No Kaggle quota spent |
| K9 | S15 | Ship rule fails outside the inconclusive band | No ship. One S17 round only under its conditions |
| K10 | any | v11 pod spend reaches $200 without an adapter advancing in S14 | Stop |
| K11 | calendar | No adapter passes S15 by 2026-11-20 IST | Final main-track submission is the best non-LoRA bundle |
| K12 | rules | The host restricts adapters or own-output training | Stop |

---

## 10. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Pallets tasks do not run under the harness (era Python 3.10-3.13 vs our 3.12; pins) | medium | Oracle filter in S3/S6; SWE-rebench fallback |
| Low yield on Pallets (sympy, pytest internals) | medium | Gate at 60; repo cap 30%; Round C only if it pays |
| Pallets repos are in pretraining, so tasks are easier than hidden ones | medium | Repo-held-out gate; 34% of tasks are from 2026 |
| v10 changes after collection | medium | T2 rule: re-render prompt-only changes; new Round A on 30% for tool or helper changes |
| `return_token_ids` not available in the patched 0.19.1 | medium | Render path, already exact on continuation deltas; S7 parity gate covers it |
| The adapter also writes compaction summaries, and they drift | low-medium | Summariser samples in training; S14 sanity row |
| LoRA mode slows cap-bound hidden tasks | medium | G4.5 and §8 row 5 |
| k_eq_v train/serve mismatch on 10 layers | high if ignored | S4 G4.3 and S5 decide `dupv` or `nok` before training |
| vLLM #50059 (rank-32 nondeterminism on int4 g32) | low at r16 | G4.4; r16 only |
| Selection bias on the 74 | low | Adapter chosen on `pal_test`; the 74 see one candidate |
| Overfitting a small set | medium | r16, 1-2 epochs, best checkpoint by `val_pub` |
| SFT narrows exploration on hard tasks | medium | Row 1 of the gate measures net effect; masks keep repeats out of the loss |
| Own-output RFT gains are small in the literature | high | Framed as a format lever; kill rules cap the spend |
| Kaggle queues (4-9 h reported) and quota | high | Calendar slack; one-run fallback rule |
| Training throughput unknown (anchor 486 tok/s on 2×H100 at 4k) | high | S11 measures; S12 cost rule |

---

## 11. Calendar (IST)

| When | Steps |
|---|---|
| 09-28 to 09-30 | S0, S2, S3 (free); S4 kernel as soon as a GPU slot is free outside scoring |
| after race 2 | S1 freeze |
| ~10-01 to 10-03 | Session 1 (S5-S9), if S2-S4 are green |
| ~10-03 to 10-04 | S10 |
| ~10-04 to 10-06 | Session 2 (S11-S14) |
| ~10-06 to 10-10 | S15 gate, S16 decision |
| 10-10 to 11-10 | S17 if its conditions hold |
| by 11-10 | S18 draft for the paper track (deadline 2026-11-12; the exact hour is on the paper-track page, not checked here) |
| by 12-01 | Final main-track choice (deadline 12-03 05:29 IST (12-02 23:59 UTC)) |

---

## 12. Rules, licensing, disclosure

- Own outputs only (host, 743964: "Training on gemma-4-31b itself is fine"). Pallets is CC0-1.0; SWE-rebench is
  CC-BY-4.0 (attribution in the data card).
- Winners must deliver reproducible training and inference code under Apache-2.0: `train/v11/`, the chains and
  `data/v11/sft/manifest.json` (seeds, hashes, counts) are that package.
- Disclosure timing (CLAUDE.md): bug reports publish immediately (for example, if S4/S5 confirm that the patched vLLM
  gives no v_proj delta on k_eq_v layers for adapters trained in HF, that is a bug report affecting everyone). The
  recipe, the dataset and the scaling results are held until submission. Posting is Carson's call.

---

## 13. Changelog

- 2026-09-28 ~18:45 IST: v0. Written against facts_internal and facts_external of 2026-09-28 ~17:30 IST. Race 2 not
  yet run. Recounted the trajectory funnel from `inventory_rows.jsonl` (table in §0), the Pallets repo/year
  distribution from `tasks.jsonl`, the June template sha256 (`94899c0f917d…`), the race-1 throughput (51 tasks in
  48.2 min per GPU at 2 tasks per GPU), and that `make_eval_kernel.py` base64-embeds bundle files.
