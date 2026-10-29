# HARNESS_README diff: the 25 Sep copy against the live 13 Oct file (checked 29 Oct 2026)

Old: `data/HARNESS_README_2026-09-25.md`, the copy `data/HARNESS_README.md` held from 25 Sep to 29 Oct (49,356 bytes,
671 lines; also in git at `e0e924e6`; sha256 `3d6e57a13234cb4e783ba24eaab486459af76e0923ea4c6607cd41cc8961bbbb`).
New: `data/HARNESS_README.md`, the file the competition serves today, fetched with
`kaggle competitions download gemma-4-developer-agent -f HARNESS_README.md` (55,940 bytes, 692 lines, created
13 Oct 2026 17:17:41 IST (11:47:41 UTC); the competition file list still shows that version on 29 Oct; sha256
`445000219b803942c469391ec8b69791a31e9cec2f934738c767e34b5ca0aa1f`). 15 diff hunks. `docs/GAPS_2026-10-06.md` ("The
scorer docs changed on 13 Oct") listed some of them on 14 Oct; this is the full list, plus the check against
`submissions/v12b`, `submissions/v12b_ctx` and `scripts/make_eval_kernel.py`.

Line numbers below are `old/new`. About 40 citations of the form `data/HARNESS_README.md:NNN` in `research/` and `docs/`
(and `scripts/run_eval.py:11`, `scripts/replay_l4.py:44`) point at the old copy. The 25 Sep README is kept in the tree as
`data/HARNESS_README_2026-09-25.md` (byte-identical to `git show e0e924e6:data/HARNESS_README.md`), so **line-number
citations dated before 29 Oct 2026 refer to that copy**, not to `data/HARNESS_README.md`. The compaction block cited as
553-561 is now 568-576.

## 1. Changes that matter to us

### 1.1 Allowed models (2.3, 3.1 table, 3.2, 3.3; old 109, 177-190, new 109, 174-206)
- Old: one competition model, `gemma-4-31b-it-qat-w4a16-ct`, "Required" in the 3.1 table;
  `ALLOWED_MODEL_NAMES = frozenset({'gemma-4-31b-it-qat-w4a16-ct'})`; rule 1 "Single Base Model Per Submission
  (`gemma-4-31b-it-qat-w4a16-ct`)".
- New: four quantized models are "Permitted", still exactly one base model per submission: `gemma-4-31b-it-qat-w4a16-ct`
  (now "Starter Kit Default"), `gemma-4-12b-it-qat-w4a16-ct`, `gemma-4-e4b-it-qat-w4a16-ct`,
  `gemma-4-e2b-it-qat-w4a16-ct`. Footprint across 4 GPUs: 12B about 6-8 GB, E4B 3-4 GB, E2B 2-3 GB. The 12B is served with
  `--hf-overrides '{"architectures": ["Gemma4ForCausalLM"], "model_type": "gemma4"}'` (`MODEL_VLLM_EXTRA_ARGS`). The
  alias registry is now `models.yaml` / `_build_cli_model_registry()` instead of `setup_gemma_model_registry()`. The bf16
  variants stay local-CLI only.

### 1.2 Thinking and sampling (2.4 generation table; old 148-153, new 148-153)
- Unchanged: every `GenerateContentConfig` field is allowed; `max_output_tokens` 1 to 32,768 (default 16,384);
  `thinking_budget` 0 to 32,768 (default 4,096); `temperature >= 0`, `0 <= top_p <= 1`, `top_k >= 1`; the advice to omit
  `thinking_level` on the vLLM `/v1` endpoint.
- `thinking_budget`. Old: "use `0` or `include_thoughts: false` to disable thinking". New: a positive value sets
  `enable_thinking: true` and forwards `extra_body.thinking_token_budget` to vLLM's `ThinkingTokenBudgetLogitsProcessor`
  (the README says only that the value is forwarded, not how strictly the processor enforces it); `0` sets
  `enable_thinking: false`.
- `include_thoughts`. Old: "`true` or `false`", no semantics. New: with a positive budget (or an active `thinking_level`),
  `true` keeps `Part(thought=True)` in the response and in later tool-call context; `false` still reasons on the current
  turn but strips thought parts from the response and from the outgoing history. With neither budget nor level set,
  `include_thoughts` is the fallback switch for `enable_thinking`. So `include_thoughts: false` no longer means "thinking off".
- `seed`. New: forwarded in the request body to LiteLLM/vLLM.
- Server default `default_chat_template_kwargs = {"enable_thinking": True}` (old 168, 198) is gone from both the 3.1 list
  and the 3.3 paragraph.

### 1.3 vLLM server (3.1 list; old 165-170, new 165-170)
- `gpu_memory_utilization`. Old `0.80` (about 19.2 GB per GPU, 76.8 GB total). New `0.90` (about 21.6 GB, 86.4 GB).
- New lines: `scheduler_reserve_full_isl = False`; `reasoning_config = {"reasoning_start_str": "<|channel>",
  "reasoning_end_str": "<channel|>"}`.
- Unchanged: `tensor_parallel_size = 4`, `max_model_len = 32768`, `enable_auto_tool_choice`, `tool_call_parser` and
  `reasoning_parser` both `gemma4`.
- 3.3 binding. Old: `setup_gemma_model_registry` binds the alias to `LiteLlm(..., num_retries=5)`. New: `setup_vllm_server`
  in `scripts/inference.py` binds the declared alias and every adapter name through
  `server_instance.create_model_registry(...)` (fallback `LiteLlm(..., num_retries=3)` when attaching to a running
  endpoint) and installs `install_litellm_reasoning_patch()`.

### 1.4 Compaction (7.2; old 556, new 571)
- `EventsCompactionConfig.compaction_interval`. Old `5`. New `15`.
- Unchanged: `overlap_size = 2`, `token_threshold = 14,336`, `event_retention_size = 5`; `ContextCacheConfig` 2,048 /
  1,800 / 10; `ModelRetryPlugin` 5 retries.

### 1.5 LoRA rules (3.1, 3.4, rule 3; old 169, 179, 204, new 169, 206-208)
- Server flags. Old: fixed `enable_lora = True`, `max_loras = 8`, `max_lora_rank = 128`. New: right-sized from the
  discovered adapters: `enable_lora = bool(adapter_map)`, `max_loras = max(1, len(adapter_map))`,
  `max_lora_rank = max(detected_ranks) if detected_ranks else 128`. No eight-adapter ceiling is stated any more.
- Size rule. Old: adapters must fit "GPU LoRA buffers (`max_loras=8`, `max_lora_rank=128`)". New: "`max_lora_rank <= 128`".
- New: adapter directory names must match `[A-Za-z0-9][A-Za-z0-9._-]*`.
- Unchanged: PEFT directory with `adapter_config.json` and `adapter_model.safetensors`, `.safetensors` only, under 3 GiB
  unpacked in total.

### 1.6 Sandbox (4.1; old 253, new 258)
- Old: `reuse_containers=True` warm pooling (wipe `/workspace`, return the container to an idle pool).
- New: `reuse_containers=False` by default, a fresh container per phase; the wipe-and-pool path applies only if reuse is
  switched on. Limits unchanged (4 GiB, 2 vCPUs, `/workspace`); the subprocess backend is unchanged.

### 1.7 Patch handling (8.1 item 2, 8.2 step 2 and 3; new 591, 599-610)
- Old: protected test and runner-config files touched by `agent_patch` were reset with `git checkout HEAD` and `git clean -f`
  in Phase 2 only.
- New: `strip_protected_files_from_patch` removes diff hunks that touch them (`test_*.py`, `*_test.py`, `.py` under `tests/`,
  `test/`, `testing/`; `conftest.py`, `pytest.ini`, `pyproject.toml`, `tox.ini`, `setup.cfg`, `.pytest.ini`,
  `sitecustomize.py`, `usercustomize.py`, `_swegemma_stubs.py`, `*.pth`) in `submit_patch()`, in the unsubmitted-diff
  fallback and again in Phase 2, before the 4-pass apply. The reset now filters tracked pathspecs through `git ls-tree`.
  The path list itself is the same as the old anti-tamper list.

### 1.8 Time limits and `eval_config.yaml` (2.2, 7.1, 9.1; old 545-546, new 559-561, 654-655)
- Unchanged: the four honoured keys (`evaluation.timeout_seconds`, `max_tool_calls`, `max_time_minutes`, `max_turns`) and
  their defaults (300 s, 100 calls in `inference.py`, 60.0 min, 500 turns), `max_stdout_chars` 5,000, `read_file` 150
  lines and 10,000 chars, the env overrides `SWE_TIMEOUT_SECONDS`, `SWE_MAX_TIME_MINUTES`, `SWE_MAX_TOOL_CALLS`,
  `SWE_MAX_TURNS`. Neither copy states a total run limit (the 12 h figure in `docs/GAPS_2026-10-06.md` S5 is not from
  the README).
- Old: one row, "Single Command Timeout", `evaluation.timeout_seconds`. New: that row is renamed "(Phase 1)" and a new
  row "Verification `pytest` Timeout (Phase 2)" says `config.harness.verification_timeout_seconds`, default 300 s, "fixed
  at 300 sec on scorer", no `eval_config.yaml` key (read from `SWE_TIMEOUT_SECONDS` in `metric.py`). So `timeout_seconds`
  no longer says anything about verification. New local CLI flags `--timeout-seconds` and `--verification-timeout-seconds`.
- "Max Command / Diff Output" is renamed "Max Command / Diff / Graph Output" (same 5,000 chars).

### 1.9 What the model sees and how errors are handled (5.2, 5.3, 6.2, 6.3; old 298-480, new 303-488)
- New `ToolErrorPlugin`: an undeclared or hallucinated tool call, or a tool exception, comes back to the model as
  `{"status": "error", "error_type": ..., "error": ...}` instead of ending the task. String-encoded ints and booleans in tool
  arguments (`"10"`, `"true"`) are coerced.
- The first user message now drops sections for tools the agent does not declare (the `read_file` limits line, the whole
  Code Intelligence block unless graph tools are declared).
- Workspace layout. Old: first 150 entries of `find . -maxdepth 3`, excluding `.git`, `__pycache__`, `*.pyc`. New: up to
  200 breadth-first entries, hidden files and `*.egg-info` excluded, and `docs`, `docs_src`, `tests`, `examples`,
  `benchmarks` pruned below depth 1.
- Graph tools (`get_code_neighbors`, `search_similar_code`, `get_code_subgraph`): outputs capped at 5,000 chars with an
  `is_truncated` field, symbol resolution accepts `;` and dotted paths, edge types are lower case (`calls`).

### Changed but irrelevant to us
Graph-tool details (we declare no graph tools), `read_file` argument coercion, skill-argument coercion (we ship no skills),
Docker container reuse (kernel and host notebook use the subprocess sandbox), removal of code line numbers
("line 306", "lines 503-740") from the text, the two new CLI flags.

## 2. Contradictions with our setup

### 2.1 submissions/v12b and submissions/v12b_ctx: none found
The two bundles share `agent.yaml`, `configs/sampling.yaml` and `eval_config.yaml`; only `prompts/system.md` differs.
Declared: `gemma-4-31b-it-qat-w4a16-ct`; tools `run_command`, `read_file`, `edit_file`, `write_file`, `get_status`,
`submit_patch`; `temperature 0.2`, `top_p 0.95`, `max_output_tokens 8192`, `thinking_budget 4096`,
`include_thoughts true`; eval `timeout_seconds 180`, `max_tool_calls 40`, `max_time_minutes 5`, `max_turns 150`; no
adapters, no skills. Checked against the live text:
- Model: the 31B is still permitted, and it is the only model in both bundles.
- Sampling: every value is inside the documented ranges. A positive budget with `include_thoughts: true` is the combination
  the new text describes as thinking on, budget forwarded to `ThinkingTokenBudgetLogitsProcessor`, thought parts kept in
  context. This agrees with the 10 Oct rule in `docs/GAPS_2026-10-06.md` that `include_thoughts: false` does not turn
  thinking off.
- `eval_config.yaml`: all four keys are still the honoured ones. `timeout_seconds: 180` now applies to Phase 1 commands only;
  the scorer's Phase 2 is a fixed 300 s.
- Protected files: the prompt rule "Never modify, create or delete test files or test configuration ..." matches the
  stripping and reset rules. Its path list is a subset of the harness list (it omits `test/` and `testing/` `.py` files,
  `.pytest.ini`, `sitecustomize.py`, `usercustomize.py`, `*.pth`), which does no harm. Full-population check: the gold
  `patch` of all 129 rows in `data/tasks.jsonl` (278 file paths) touches no protected path, so stripping cannot remove a
  gold-shaped fix on the 129 local tasks (`data/heldout1k` and the other task sets were not checked).
- Tools and prompt: all six declared tools exist; neither prompt mentions graph tools, so the filtered Code Intelligence
  block changes nothing. The wider workspace listing adds up to 50 lines to the first message; neither prompt depends on it.
  `v12b_ctx`'s `{problem_description?}` templating is unchanged in the new text.

### 2.2 scripts/make_eval_kernel.py
Agrees with the live file (these are the items where the 25 Sep copy disagreed with the kernel, so the kernel was right and
the old copy was stale): `gpu_memory_utilization=0.90`, compaction 15 / 2 / 14,336 / 5, `ContextCacheConfig`
2,048 / 1,800 / 10, no `default_chat_template_kwargs`, TP 4, `max_model_len=32768`, parsers `gemma4`, budget defaults
(300 s / 100 calls / 60.0 min), sequential tasks, subprocess sandbox.

Contradictions and gaps:
1. **Phase 2 timeout (possible, depends on the wheelhouse build).** The kernel passes the bundle's `timeout_seconds` (180 for
   v12b) into `EvalConfig`. In swegemma 0.2.11 as saved in `harness/wheels` (the 11 Oct build), `EvalConfig.__post_init__`
   copies it into `harness.command_timeout_seconds` (`config.py` 179-188) and `harness/verification.py:638` runs the
   verification `pytest` with that value. So kernel verification gets 180 s while the live text says the scorer gets a fixed
   300 s. A test run that takes 180 to 300 s counts as unresolved in the kernel and resolved on the scorer, so kernel scores
   can only err low. The 11 Oct build has no `verification_timeout_seconds` field; whether the 12 Oct build has it (the live
   text says it does) is not known, and the kernel does not set it.
2. **Single hard-coded model.** `MODEL_PATH` and `model_sources` are the 31B, and
   `create_model_registry(aliases=[declared, '...31b...'])` maps every alias to the served model (`adk_submission/server.py`
   397-414), so a bundle that declares the 12B, E4B or E2B is evaluated with 31B weights under that name. The live text makes
   those three legal, and `submissions/v12b_e4b` and `v12b_e4b_card` already declare the E4B. There is no guard in the
   kernel (`scripts/validate.py` accepts all four models). The 12B would also need the `--hf-overrides` flag, which the
   kernel does not pass.
3. **LoRA literals (text only, no behaviour change found).** The kernel sets `enable_lora=True, max_loras=8,
   max_lora_rank=128`, the old fixed values; the live text right-sizes. In the 11 Oct adk_submission 0.2.13 build the server
   adds `--enable-lora` only when adapters exist and sets `--max-loras` to the adapter count (`server.py` 781-791), so the
   effect is the same as the live text for adapter-less bundles such as v12b.
4. **Settings the live text lists for `setup_vllm_server` that the kernel does not set (no behaviour change found).**
   `reasoning_config` and `scheduler_reserve_full_isl=False`: in the 11 Oct build `VllmServer` adds the gemma4
   `--reasoning-config` itself when `reasoning_parser == 'gemma4'` and `scheduler_reserve_full_isl` defaults to `False`
   (`server.py` 719-732, 753-756); `install_litellm_reasoning_patch()` runs at import of the generation resolver.

### 2.3 Other stale items found on the way (outside the three named files, not changed here)
- `scripts/run_eval.py` sets `COMPACTION = {"compaction_interval": 5, ...}` and calls it "the organiser README value". The
  live value is 15, so every pod run through it (`G4_COMPACTION=1` in `pod/chain_pair.sh`, `chain_race2.sh`,
  `chain_pallets.sh`) compacts three times as often as the scorer. `research/gap_4.md`, `research/competitors.md`,
  `research/time_model.md` and `research/harness_runtime.md` repeat the old 5 as the README's value (`time_model.md` also
  the old 0.80). `tests/test_v10_runner.py` pins the same interval together with `scripts/run_eval.py`
  (`test_run_eval_compaction_scale_noeditable` asserts `(5, 2, 14336, 5)`), so the two have to move together; both are
  being moved to 15 on another branch, not in this tree.
- `pod/serve.sh`, `pod/serve2.sh`, `pod/preflight.sh` and `aws/preflight.sh` start vLLM with
  `--default-chat-template-kwargs '{"enable_thinking": true}'`, the default the live 3.1 list no longer has (see 1.2);
  `scripts/make_eval_kernel.py` omits it. `pod/serve.sh` calls its flags "the scoring server's flags (HARNESS_README s3.1)"
  and both preflights call them "exact competition server args". A request that carries no thinking setting gets thinking
  on from these servers; on the scorer it gets the chat template's own default. Bundles with a `thinking_config` set
  `enable_thinking` per request, so the effect on them is probably small; it was not measured.
- `--generation-config`: the README does not mention it, and none of those four scripts (nor the kernel) sets it, so the
  pod servers take vLLM's default `auto` (sampling defaults from the model's `generation_config.json` when a request omits
  them; `docs/OPTIMISE_RANKING_2026-10-29.md` A6 and item 6 record the same). Whether the scorer's `setup_vllm_server` sets
  it is not stated.
- Bundles that set `include_thoughts: false` to mean "thinking off" (80 yaml files under `submissions/`, for example `v0`
  with a 4,096 budget, `v1_t05_low` and `v1_t10_high` with a `thinking_level`, `sub2` and `v1` with neither) match the old
  README line "use `0` or `include_thoughts: false` to disable thinking". The live text says a positive budget or an active
  level means thinking on whatever `include_thoughts` says, and the scorer merges the default 4,096 budget into a
  `thinking_config` that sets none (`adk_submission/limits.py`, 11 Oct build), so they think. The 10 Oct `-t0` rule in
  `docs/GAPS_2026-10-06.md` already covers this; its line 751 ("v0 scored 0.10 ... with thinking off") should be read with it.

## 3. Caveat on the scorer stack
Every stack check above used `harness/wheels` (swegemma 0.2.11, adk_submission 0.2.13), the builds the runs up to 11 Oct
used (sha256 `63f054a3...` and `69642a13...`). The live wheelhouse dataset `metric/gemma-4-developer-agent-wheelhouse`
lists its files as created 13 Oct 2026 01:21 IST (12 Oct 2026 19:51 UTC; this doc calls it the 12 Oct build, by the UTC
date), with swegemma at 119,670 bytes and adk_eval_core at 90,060, against 119,520 and 89,306 for the saved copies; the
28 Oct kernel (`eval/kaggle/g4-l4-v12b-garble-p312/wheelhouse_sha256.txt`) records different
sha256 values for swegemma, adk_submission, adk_eval_core and vllm than the 11 Oct runs. So the 14 Oct note in
`docs/GAPS_2026-10-06.md` that the wheelhouse is "byte for byte" the v12 run's does not hold for the build the 28 Oct run
used, and the "nothing we measured is invalidated" conclusion rests on the older build. Reading the 12 Oct wheels needs a
dataset download, which this task did not include. Items 1, 3 and 4 of 2.2 are the ones that depend on it.
