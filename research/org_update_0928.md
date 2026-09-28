# Organiser-side changes: gemma-4-developer-agent + paper track (check of 2026-09-28 16:05-16:25 IST / 10:35-10:55 UTC)

Scope: what the organisers changed between 2026-09-25 and now, and what is new compared with `research/forum.md` and
`research/competitors.md` (both 2026-09-27). Read-only: listings, metadata, small file downloads, HTTP range reads of two
wheels, and the public notebook pull. Nothing was posted, voted on, submitted or pushed. Our running kernels
(`g4-l4-v4`, `g4-l4-v9-eog`) were not touched.

Times are IST, with UTC in brackets because Kaggle stamps UTC. `EV` = `/private/tmp/claude-501/-Users-carson-Projects/654244a3-b38c-45a0-96af-d7e5f0aac6ce/scratchpad/org0928`.

## 0. Bottom line

1. **The LoRA wipe (forum 743508) is fixed in the wheelhouse, and the host has confirmed it.**
   - Wheelhouse v23 (2026-09-27 16:07 IST / 10:37 UTC) rebuilt `vllm-0.19.1` with changes to exactly two source files:
     `vllm/model_executor/models/gemma4.py` and `vllm/lora/model_manager.py`.
   - The diff removes the duplicate `decoder_layers` child registration, and stops `activate_adapter` from resetting a
     module it has just loaded (§1.2).
   - Ryan Holbrook, 2026-09-28 16:02 IST (10:32 UTC): "I applied a fix for LoRA loading yesterday"
     (https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743964, comment 3529469).
   - Checked by code reading only; there has been no GPU logprob A/B yet.
   - Our `g4-lora-test` kernel ran on 2026-09-26 against the pre-fix wheel, so its result is void.
2. **Self-distillation is explicitly allowed**: "Training on gemma-4-31b itself is fine" (same comment).
   Outputs from other models are still unruled ("We'll try to have an answer ... soon").
3. **No concurrency, and a 12 h overrun still errors.** The same comment says:
   - "we don't support parallel calls". ParallelAgent best-of-N gets no concurrency.
   - 12 h overrun fix: "Not yet. Budget per task using eval_config.yaml."
4. **sub3 and sub4 ran on different wheel sets. This is a confounder for the 0.12 → 0.06 drop, not an explanation of it.**
   - sub3 was submitted 2026-09-27 05:31 IST (00:01 UTC), before v23/v24.
   - sub4 was submitted 2026-09-28 05:31 IST (00:01 UTC), after them.
   - By code reading, base-model inference (no adapter, `include_thoughts: false`) should be unchanged (§1.2, §1.3).
   - Whether the scorer installs the public wheelhouse at scoring time is UNVERIFIED. The host's "applied a fix
     yesterday" matching the v23 timing suggests it does.
   - The paired L4 kernels started 2026-09-28 15:59 IST both run on v25, so they de-confound this.
5. **The Getting Started notebook changed again** (re-run 2026-09-28 01:20 IST / 2026-09-27 19:50 UTC), after the
   version `forum.md` read:
   - It no longer sets `default_chat_template_kwargs={'enable_thinking': True}`.
   - It now reads the budget from the bundle's `eval_config.yaml`, with README defaults: 300 s, 100 calls, 60 min, turns
     None.
   - Compaction (15 / 2 / 14,336 / 5), context cache (2048 / 1800 / 10) and `gpu_memory_utilization=0.90` are unchanged
     (§2).
6. **`adk_submission-0.2.11` was rebuilt in v24** (2026-09-27 17:02 IST / 11:32 UTC): `thinking_budget` now switches
   thinking (≤0 → off, >0 → on).
   - Every stage of ours sets `include_thoughts: false`, which still wins, so there is no behaviour change for v4, v9 or v10.
   - Our local `harness/wheels` copy and `.venv` are the pre-v24 build.
7. **Unchanged since 2026-09-25**:
   - Competition data: all 524 files, same sizes. `HARNESS_README.md`, `tasks.jsonl`, `sandbox/setup.py`, `docker/*` and
     `sample_submission/*` are byte-identical to our local copies.
   - All Overview/Rules/Timeline/Data/Evaluation/Prizes/Model-rules pages on both tracks.
   - `swegemma 0.2.7`, `adk_eval_core 0.1.0`, `google_adk 1.36.1` and the other 36 wheels (per-member CRC32 identical,
     v22 vs v25).

## 1. Wheelhouse `metric/gemma-4-developer-agent-wheelhouse`

https://www.kaggle.com/datasets/metric/gemma-4-developer-agent-wheelhouse

- Current version is still **v25** (2026-09-27 17:19 IST / 11:49 UTC, notes "Update 2026-09-27"), with 41 files and
  880,829,403 B. There is no v26. Evidence: `EV/wh_dataset_now.json`, `EV/wh_files_now.csv`.
- **Method.** Kaggle's signed GCS URLs accept `Range`. For every wheel in v22 and v25, I read only the ZIP central
  directory and compared per-member CRC32 and size. I then range-fetched just the changed members and checked each CRC
  after decompression.
  - Evidence: `EV/wh_v22_v25_crcdiff.json`, `EV/vllm_cd.json`, `EV/vsrc/v{22,25}_{gemma4,model_manager}.py`.
  - Total download was a few MB instead of 433 MB.

### 1.1 What changed, by version (member CRC32)

| wheel (version string unchanged) | v21 | v22 (09-25 19:04 IST) | v23 (09-27 16:07 IST) | v24 (09-27 17:02 IST) | v25 (09-27 17:19 IST) |
|---|---|---|---|---|---|
| `vllm-0.19.1` `models/gemma4.py` | ef6fc74f | ef6fc74f | **c8cefd56** | c8cefd56 | c8cefd56 |
| `vllm-0.19.1` `lora/model_manager.py` | 79143634 | 79143634 | **e16a1908** | e16a1908 | e16a1908 |
| `adk_submission-0.2.11` `resolvers/generation.py` | a3638a55 | a3638a55 | a3638a55 | **a69632bf** | a69632bf |

Every other member of every other wheel is identical between v22 and v25. That includes `swegemma-0.2.7` (111,548 B),
`adk_eval_core-0.1.0` (89,306 B), `google_adk-1.36.1` (2,877,731 B), transformers, flashinfer and xgrammar. v25 has the
same content as v24.

**Version strings are not identifiers here.** vLLM and adk_submission were rebuilt in place under the same version.
Compare hashes, not names.

### 1.2 vLLM 0.19.1 rebuild = the LoRA double-registration fix (743508)
`diff -u EV/vsrc/v22_model_manager.py EV/vsrc/v25_model_manager.py`:

- **`activate_adapter`:**
  - It tracks `loaded_modules` by `id(module)`.
  - A module that already received LoRA weights under one name is **not** `reset_lora`'d when it is met again under
    its alias.
  - This is exactly the wipe Whisper Last described.
- **`_create_lora_modules`:** it now skips modules that are already `BaseLayerWithLoRA`, so already-wrapped modules are
  not wrapped a second time via the alias path.

`diff -u EV/vsrc/v22_gemma4.py EV/vsrc/v25_gemma4.py`:

- **`Gemma4SelfDecoderLayers` and `Gemma4CrossDecoderLayers`:** they store `decoder_layers` in `self.__dict__` instead
  of as a child module, unless `kv_sharing_fast_prefill` is on. `named_modules(remove_duplicate=False)` therefore no
  longer yields `self_decoder.decoder_layers.N`.
- **`Gemma4Model.embed_input_ids` / `get_per_layer_inputs`:**
  - They are now computed on the model itself.
  - The body is a verbatim copy of the old `self_decoder` methods, run on the same shared modules (the attributes
    exist at `v25_gemma4.py:874-963`).
  - So base-model numerics should be unchanged. That is a code-reading claim; there was no GPU A/B.

Runtime evidence that it loads:
- The host notebook's 2026-09-27 19:50 UTC run served the sample `main_lora`/`tool_lora` adapters on the v25 wheels
  with `enable_lora=True`.
- vLLM came up in about 663 s (log t=121 s → 784 s), and both tasks ran tool calls.
- Evidence: `EV/gs_out/getting-started-gemma-4-developer-agent.log`.
- That shows loading works. It does not show that adapter outputs differ from base; the sample adapters are tiny.

### 1.3 adk_submission 0.2.11 rebuild = thinking_budget now controls enable_thinking
`EV/whl_new/x/adk_submission/resolvers/generation.py:94-107` (the old version is in `EV/whl_old/...`):

| thinking_config | before (≤ v23) | after (v24+) |
|---|---|---|
| `include_thoughts: false` (ours, every stage of v4/v9/v10) | enable_thinking False | **False (unchanged)** |
| `thinking_budget: 0` alone | nothing sent, so the server default applies (True in README) | **False** |
| `thinking_budget: N>0` alone | nothing sent, so the server default applies | **True** |
| `include_thoughts: true` | True | True |

- `include_thoughts: false` is checked first, so our bundles are unaffected.
- Before v24, the README's "use `0` ... to disable thinking" (`HARNESS_README.md:148`) did not actually work on its own.
- This matters for reading competitor configs dated before 09-27.

### 1.4 Our copies are stale
- `harness/wheels/adk_submission-0.2.11-py3-none-any.whl` is 62,356 B, the pre-v24 build.
  `.venv/.../adk_submission/resolvers/generation.py` has sha256 prefix `b07a510d`, identical to the old wheel (new
  prefix: `e54d0995`).
- `pod/bootstrap.sh:12-14` pulls the vLLM wheel from the dataset at bootstrap time. A pod bootstrapped before
  2026-09-27 16:07 IST has the pre-fix vLLM. Pod state was not checked here.
- The swegemma, adk_eval_core and google_adk copies match v25.

## 2. Getting Started notebook vs our `scripts/make_eval_kernel.py`

https://www.kaggle.com/code/ryanholbrook/getting-started-gemma-4-developer-agent

- `lastRunTime` is 2026-09-27 19:50:58 UTC (`kaggle kernels list --user ryanholbrook`).
- `forum.md` read the 10:39 UTC run, pulled at 11:24 UTC. `kernel-metadata.json` is identical, including the docker
  image digest `sha256:37c64f7d...`.
- Cell diff: `diff -u EV/gs_old.txt EV/gs_new.txt`.

### 2.1 What the host changed
1. **Removed** `default_chat_template_kwargs={'enable_thinking': True}` from `VllmConfig`. The `VllmConfig` default is
   `None` (`adk_submission/server.py:131`), so the template default applies unless the request sets it.
2. **Budget now comes from the bundle's `eval_config.yaml`**, with defaults of `timeout_seconds` 300,
   `max_tool_calls` 100, `max_time_minutes` 60.0 and `max_turns` None.
   - The old version hardcoded 100 calls / 5.0 min and said "The only enforced constraint in this competition is a 12
     hour inference runtime"; that markdown cell is gone.
   - The new defaults match the `HARNESS_README.md` §7.1 table ("100 in `inference.py`", 60 min, 300 s, 500 turns).
   - In 743063 (2026-09-24) the host said "The default is no limit". The two statements conflict. It does not matter
     for us, because we set all four keys, but it does matter for reading competitors without an eval_config (Rozen).
3. Only a title cell was added. Install, env vars, data paths, compaction, cache, gpu_mem and LoRA settings are unchanged.

### 2.2 Parity table (what a faithful eval must match)

| setting | HARNESS_README (unchanged) | host notebook now | `make_eval_kernel.py` | verdict |
|---|---|---|---|---|
| wheel install (cutlass .pth removal, `+cu128` rename, `--no-deps --force-reinstall`) | n/a | same | same (lines 25-42) | match |
| env vars (spawn, `ENGINE_READY_TIMEOUT_S=1200`, `expandable_segments`, ...) | n/a | same | same (27-29) | match |
| `EventsCompactionConfig` | interval **5**, overlap 2, threshold 14,336, retention 5 (§7.2, l.555-559) | interval **15**, 2, 14,336, 5 | 15, 2, 14,336, 5 (l.95) | matches notebook; interval vs README unresolved (743752 still unanswered) |
| `ContextCacheConfig` | 2048 / 1800 s / 10 | same | same (l.94) | match |
| `gpu_memory_utilization` | **0.80** (l.165) | 0.90 | 0.90 (l.70) | README vs notebook conflict, unchanged; affects KV-cache size only, so negligible for sequential single-stream serving (UNVERIFIED which the scorer uses) |
| `max_model_len` / parsers / TP / LoRA (8, rank 128) | 32768 / gemma4 / 4 / yes | same | same | match |
| `default_chat_template_kwargs` | `{"enable_thinking": True}` (l.168, 198) | **removed** | `{'enable_thinking': True}` (l.69) | no effect on our bundles (see note below); for bundles with no thinking_config it flips thinking on/off |
| budget source | eval_config, defaults 60 min / 100 / 500 / 300 s | **reads bundle `eval_config.yaml`**, same defaults | CLI flags (`--min 6 --calls 60 --turns 80 --timeout 180` defaults) | **gap**: recent L4 kernels passed matching values (5/70/150/180 for v4 and v9_eog), but the defaults do not match v9 or v10 (v10 is 5/100/200/120). Read `eval_config.yaml` instead |
| sandbox | Docker in the private scorer (host, 742882) | subprocess | subprocess | cannot replicate on Kaggle; known |
| wheelhouse version | n/a | latest | attached unpinned (`dataset_sources`), so v25 | OK, but a run's wheel version depends on its date |

**Why the thinking flag does not touch us:**
- Every LLM stage in v4, v9_eog and v10 sets `include_thoughts: false`. The resolver writes
  `extra_body.chat_template_kwargs.enable_thinking=False` into the stage's LiteLlm clone (`builders/llm.py:75`).
- In-flow compaction builds its summariser from `invocation_context.agent.canonical_model`, which is that same clone
  (`google/adk/flows/llm_flows/compaction.py:44-51`, `google/adk/apps/compaction.py:236`). Summaries are therefore
  also generated with thinking off.

**Side note, code-level lead only (UNVERIFIED at runtime).** The post-invocation token-threshold path passes
`app.root_agent` (`apps/compaction.py:475-491`).
- For our `SequentialAgent` root, `_ensure_compaction_summarizer` raises `ValueError('No LlmAgent model available ...')`
  if no in-flow compaction has set the shared summariser first.
- Zero hits for that string in `eval/`, `experiments/`, `kernels/` or `pod/`.
- Worth a grep of the v9 Kaggle traces if overflow or empty-patch counts look odd.

## 3. Competition data and HARNESS_README

https://www.kaggle.com/competitions/gemma-4-developer-agent/data

- `kaggle competitions files` (3 pages) lists 524 files, all stamped 2026-09-25 18:36-18:40 UTC (the known re-issue).
  - There are no additions or removals, and every size equals the 14:21 UTC listing (`scratchpad/files_page{1,2,3}.txt`).
  - Evidence: `EV/comp_files_all.json`.
- 13 small files were downloaded to `EV/compdl/` and hashed against our copies.
  - `HARNESS_README.md` sha256 `3d6e57a1...` is identical to `data/HARNESS_README.md` and `data/raw/HARNESS_README.md`.
    **HARNESS_README has not changed since the 09-25 re-issue.**
  - `tasks.jsonl` `e4b3fd60...` is identical.
  - `sandbox/setup.py`, all 4 `docker/*` files and all 7 `sample_submission` text files are identical.
- The `sample_submission` fix the host promised on 09-25 has **not** shipped:
  - `eval_config.yaml` is still 60 s / 10 calls / 1 min / 50 turns.
  - The adapters are still the 217,672 B stubs.

## 4. Overview / Rules / Timeline / Data / Evaluation pages (both tracks)

Pulled with `api.competition_list_pages` (the same call as `scratchpad/forum/pages.json`). Evidence:
`EV/pages_now.json`, `EV/pages_paper_now.json`.

- **Main track, 9 pages:**
  - Byte-identical to the 2026-09-27 17:09 IST snapshot.
  - Line-level identical to the 2026-09-25 20:08 IST browser snapshot (`scratchpad/gemma/web/main_*.md`) after
    normalising markdown. The only residue is link-rendering artefacts.
  - Timeline unchanged: entry and merger deadline 2026-11-25; final 2026-12-02 23:59 UTC; optional paper 2026-11-12.
- **Paper track, 10 pages:**
  - Line-level identical to the 2026-09-25 snapshot.
  - `tracks-and-awards` and `judges` are hidden placeholders ("This will not be displayed").
  - Rules in brief: 3,000 words max, non-archival, 5 criteria scored 0-5 and averaged, top 3 papers. Deadline
    2026-11-12 23:59 UTC. It lists no data file except `NOTE.md` (55 B, 2026-08-27).
- **Counts from `kaggle competitions list -s gemma-4`, as of this check:** main 733 teams (607 on 09-27), our rank 55;
  paper 61 teams.

## 5. Host statements since the 2026-09-27 21:45 IST (16:15 UTC) sweep

I fetched all 52 topics (45 main, 7 paper; the paper forum had never been swept) with full comments. Evidence:
`EV/threads_now.json`, `EV/topics_all_now.json`.

There is exactly **one** new host comment across both forums:

- **743964, Ryan Holbrook, 2026-09-28 16:02 IST (10:32 UTC)**, answering Tarun Singhal:
  - 12 h overrun scoring: "Not yet. Budget per task using `eval_config.yaml`."
  - ParallelAgent: "I we don't support parallel calls."
  - LoRA: "I applied a fix for LoRA loading yesterday. You can see the limits on rank and size in the getting started
    notebook and also in the `HARNESS_README.md`. There's also a total submission limit of 3GB."
  - Training data: "Training on gemma-4-31b itself is fine. We'll try to have an answer for outputs from other models
    soon."

Still no host answer on:
- 742807 (distillation from proprietary models; now 38 votes).
- 743752 and 743456 (scorer compaction interval, Docker vs subprocess).
- 743508 itself (the fix was announced in 743964, not there).
- 742911 (async graph nodes).
- The new 743973 (gold patches failing offline; see §6).

The paper forum has no host replies except Elan Markowitz's welcome (743012, 2026-09-24). That post names the paper
awards as Best Paper, Best New Resource and Best New Application from a $35,000 pool.

**Monday reruns (743683):**
- There is no host post saying the reruns ran.
- Our sub2 `56563379` still has no score (`kaggle competitions submissions`, checked about 16:10 IST).
- Daily submission quota confirmed as used: `submission-limits` shows 1 today, 0 remaining.

## 6. Other organiser-adjacent facts

- **Model menu.** `kaggle models get google/gemma-4` lists `OTHER` (compressed-tensors) W4A16 instances for 31B, 12B,
  E4B and E2B, all at version 2. There is **no** 26B-A4B W4A16 instance.
  - The competition allow-list exists only in the private `scripts/inference.py` (`HARNESS_README.md` §3.2); it is not
    in any wheel.
  - The host has made no post opening the smaller variants, so the allow-list is still 31B-only as far as public
    evidence goes (UNVERIFIED).
  - Instance publish dates could not be read, because the versions CLI ignores the instance argument.
- **swegemma 0.2.7 unpacked-wheel cache bug** (participant report 744029, Francesco Simone, 2026-09-28 15:53 IST).
  Verified in our install: `swegemma/harness/container_setup.py:244-248` caches at
  `$TMPDIR/swegemma_sp_cache_v8/{cache_name}.tar`, and `cache_name` does not depend on the wheel set.
  - Kaggle kernels are fresh VMs, so they are unaffected.
  - On the pod or a Mac, changing `wheels_dir` between runs silently reuses the old tar. Clear that directory, or set a
    per-run `TMPDIR`.
- **743973 (wrath333\*, 2026-09-28 09:32 IST): gold patches fail offline for most FastAPI and requests tasks.**
  - Replies:
    - Bharat reproduces it with the Getting Started kernel.
    - JohnParkerson says 8 `requests` tasks cannot pass on py3.13 because `VERIFY_X509_STRICT` rejects the pytest-httpbin
      certificate.
    - JohnParkerson also reports 3 version-gated tasks.
  - All of this is on the **public** subprocess path. The host has said the private Docker sandbox installs different
    dependencies (742882).
  - Not verified here. The public-arena ceiling claims in our docs should exclude these tasks.

## 7. What this means for us (ranked)

1. **Treat the sub3 (0.12) vs sub4 (0.06) gap as confounded by a scorer wheel change.**
   - It should be neutral for no-adapter, thinking-off bundles by code reading, but it is still a confounder.
   - The running paired kernels `g4-l4-v4` and `g4-l4-v9-eog` (both started 2026-09-28 15:59 IST, so both on v25) are the
     clean comparison. Do not attribute the LB drop to compaction or helpers until they finish.
   - Remember the LB noise floor: 7 vs 4 tasks out of 58.
2. **LoRA is unblocked on paper.**
   - Before any training spend, run a single short L4 probe on v25: Whisper Last's repro (random `lora_B`, base vs
     adapter logprobs at T=0) plus our `v4_lora_test` bundle.
   - `g4-lora-test` (2026-09-26 12:55 IST) predates the fix.
   - Self-generated Gemma-31B trajectories are allowed. Rows distilled from Claude or other models stay out until a
     ruling.
   - Size limits: rank ≤128, ≤8 adapters, <3 GiB total (README §3.1).
3. **Drop ParallelAgent best-of-N as a speed play** ("we don't support parallel calls"). Any multi-candidate scheme must
   fit sequentially inside the per-task budget.
4. **Keep the 12 h fail-safe conservative.** Overrun still errors the whole run ("Not yet").
5. **Fix `make_eval_kernel.py` parity:**
   - Read `max_time_minutes`, `max_tool_calls`, `max_turns` and `timeout_seconds` from the bundle's `eval_config.yaml`,
     as the host notebook now does.
   - Log the wheelhouse version into the results.
   - Leave `enable_thinking` and `gpu_memory_utilization` as they are; neither changes our bundles.
6. **Re-sync local wheels.** Refresh `harness/wheels/adk_submission` (62,404 B) and re-bootstrap any pod vLLM from v25.
   Clear `$TMPDIR/swegemma_sp_cache_v8` on the pod whenever the wheel set changes.
7. When reading competitor configs dated before 2026-09-27 17:02 IST, remember that `thinking_budget: 0` did **not**
   turn thinking off then.

## 8. Commands (all read-only)
```
source /Users/carson/Projects/kaggriculture/.venv/bin/activate
kaggle datasets files metric/gemma-4-developer-agent-wheelhouse --page-size 200 --csv
python: ApiGetDatasetRequest(owner_slug='metric', dataset_slug='gemma-4-developer-agent-wheelhouse') -> versions
python: ApiDownloadDatasetRequest(version=N, file_name=W) -> response.request.url (closed unread) -> HTTP Range reads of ZIP EOCD + central directory + changed members
kaggle datasets download metric/gemma-4-developer-agent-wheelhouse -f adk_submission-0.2.11-py3-none-any.whl
kaggle competitions files gemma-4-developer-agent --page-size 200 --csv (+ page tokens)
kaggle competitions download gemma-4-developer-agent -f <13 small files>
kaggle kernels list --user ryanholbrook ; kaggle kernels pull ryanholbrook/getting-started-gemma-4-developer-agent -m ; kaggle kernels output ryanholbrook/getting-started-gemma-4-developer-agent
python: api.competition_list_pages(<both comps>) ; api.competition_list_topics(sort x page) ; api.forums_topic_show(id)
kaggle competitions submissions / submission-limits / list -s gemma-4 ; kaggle models get google/gemma-4
```

## 9. Open questions
- Does the scorer install the public wheelhouse per submission, i.e. did sub4 run on v25? The host's wording implies
  yes. UNVERIFIED.
- Does the scorer use compaction interval 5 (README) or 15 (notebook)? And `gpu_memory_utilization` 0.80 or 0.90? Is
  `enable_thinking` still defaulted True server-side?
- Is the "default is no limit" answer (743063) superseded by the README defaults of 60 min / 100 calls that the
  notebook now mirrors?
- When will the rerun of failed 09-25/26 submissions (sub2) happen? When will the ruling on outputs from other models
  arrive? When will the "unfinished = 0" scoring ship?
