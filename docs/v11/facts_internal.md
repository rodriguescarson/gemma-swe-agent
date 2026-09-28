# v11 internal facts: adapter serving, exact prompts, trace data, training code, budget

Written 2026-09-28 (~17:30 IST). Scope: the facts v11 (v10 + a LoRA adapter trained on Gemma-4-31B's own
successful trajectories) has to be planned on. Read-only for the project: nothing was trained, served, pushed or
submitted, and no pod was started. The only paid-service calls were two read-only RunPod billing reads.

Evidence labels:
- **CODE**: read in installed source (file:line given).
- **EXP**: reproduced offline on the Mac (command and output location given).
- **DATA**: counted in our own run artifacts.
- **UNVERIFIED**: inference or docs only.

Paths:
- `SPK` = `/Users/carson/Projects/gemma-swe-agent/.venv/lib/python3.12/site-packages` (swegemma 0.2.7,
  adk_submission 0.2.11, google-adk 1.36.1, litellm 1.102.1).
- `EV` = `/Users/carson/Projects/gemma-swe-agent/docs/v11/evidence/`. Copies of every script, rendered
  sample and table behind this file, including the scorer's June chat template. The session scratchpad is
  temporary, so nothing here depends on it.
- `SP` = the session scratchpad (`/private/tmp/claude-501/-Users-carson-Projects/654244a3-b38c-45a0-96af-d7e5f0aac6ce/scratchpad`).
  Only for large files: the 32 MB tokenizer at `SP/v11cap/hf_w4a16/tokenizer.json` and the vLLM source copies.

---

## 0. Bottom line, ranked by how much each fact changes the v11 plan

1. **The "611 resolved runs across 79 tasks" figure does not hold.** (DATA, §4)
   - What exists: 397 resolved model trajectories, and only 349 are unique. The 48 extra are byte-identical
     copies: `eval/h100b/runs/p_v{4,6}` duplicates `eval/eval3/eval/runs/p_v{4,6}`.
   - The 349 cover **43 distinct tasks** from 4 repos: fastapi 20, rich 18, requests 4, httpx 1.
   - 79 is the number of tasks *attempted*.
   - The other ~200 "resolved" traces under `eval/**/traces` are oracle, rescore and no-patch runs. They
     contain zero agent steps.
   - 7 pod failures pass under the Kaggle environment (`kaggle/rescore_fair`), so the usable ceiling is 356
     trajectories over 44 tasks.
2. **No v10 trajectory exists yet, and the old ones do not match v10's action space.** (DATA, §4.6)
   - All 349 come from bundles v1 to v9.
   - v10 has different stages (setup and submitter are new), different prompts, and a different helper set
     (`edit.py` SEARCH/REPLACE, `view.py`, `verify.py`, `finalize.py`, `status.py`).
   - In old resolved runs, 35-54% of calls are raw `run_command` (grep/sed/cat), 19-35% `read_file` and
     5-18% `edit_file`. v10's prompts steer away from those.
   - Byte-exact v10 SFT data therefore has to be generated, starting with race 2's two `r2_v10` runs.
     Old data could only enter as off-policy text under v10 prompts.
3. **Per-stage adapters work end to end** through the real compile, ADK, LiteLLM and request path. (EXP, §1)
   - A v10 copy with `adapter: v11_loc` on the locator and `adapter: v11_fix` on the fixer sent the locator's
     requests as `model: "v11_loc"` and the fixer's as `model: "v11_fix"`. The other stages used the base
     model.
   - The **compaction summariser inside the fixer also used `v11_fix`**, so an adapter will also write
     compaction summaries.
   - Up to 8 adapters fit without changing the server (`--max-loras max(8, n)`), within the 3 GiB bundle cap.
4. **The exact scorer prompt can be reproduced byte for byte, and the reconstruction is verified against the
   recorded token counts.** (EXP + DATA, §2 and §3)
   - Method: render the OpenAI request with the June template (`EV/chat_template_kaggle_v2_june.jinja`,
     sha256 `94899c0f...`), after vLLM's `openai` content-format wrapping and argument `json.loads`.
   - Check on e74_v3 (Kaggle L4): the rendered increment between consecutive calls of a stage equals the
     recorded `prompt_tokens` delta **exactly in 2,391 of 2,391 continuation pairs**. It is exactly -4 tokens
     in 203 of 216 first-call pairs and in all 53 first calls after a compaction, which is the known
     generation-prompt rule.
   - e74_v2 gives 3,262 of 3,262. race1 gives 4,285 of 4,285.
   - The only gaps are compaction drops (55 in e74_v3), whose summaries are not stored.
5. **The model's raw output is almost always the canonical re-render of its parsed tool call.** (DATA, §3.3)
   - The one addition is an optional **empty thought channel `<|channel>thought\n<channel|>` (4 tokens)**
     that the model emits itself in continuation calls.
   - On e74_v3, `completion_tokens` equals canonical + stop token in 1,423 of 2,923 single calls, and
     canonical + 4 in 1,340. That fixes the raw text for 94.5% of calls.
   - Final text replies carry the empty channel in 183 of 194 cases.
   - **train/sft.py neither adds nor masks this channel correctly** (§5).
6. **Tool results reach the model JSON-encoded twice**, as
   `response:NAME{value:<|"|>{"result": "{\"status\": ...}"}<|"|>}`. (CODE + EXP)
   - The traces store the inner JSON once, with `ensure_ascii=True`.
   - The model-visible bytes can be rebuilt deterministically (§3.2).
   - `convert_nebius.py` emits single-encoded tool content, so it is **not** in the scorer's format.
7. **train/sft.py has never trained a step, and as written it would train on a different prompt format than
   the scorer's.** (DATA + CODE, §5)
   - The only GPU attempt (train1, 2026-09-26) got 0 examples, then a ZeroDivisionError.
   - It renders with the training base's July template (18,683 B), not the scorer's June one (16,934 B).
   - It passes string contents, which drops the trailing space the scorer's system turn has.
   - It supervises the first call without the generation-prompt thought channel.
   - It computes full-vocabulary logits over up to 16,384 tokens, which risks OOM (UNVERIFIED).
8. **The pod cannot evaluate an adapter today.** (CODE, §5.5)
   - `pod/serve.sh` starts vLLM without `--enable-lora/--lora-modules`.
   - It serves the HF-main July template.
   - The request routing itself needs no change (§1.4).
9. **Enabling any adapter switches the whole scorer vLLM into LoRA mode**, with slots pre-sized for 8 adapters
   at rank 128, whatever rank we ship. (CODE + estimate, §1.6)
   - Base-model stages then also run through the LoRA path.
   - The decode-speed cost on 4×L4 is **UNVERIFIED**. The 12 h cap leaves at most about +15% wall
     (own_data.md §0.7), so this needs one Kaggle L4 timing run before shipping.
10. **Spend is higher than the ledger says.** (DATA, §6)
    - RunPod billing shows **$96.09** on the five gemma GPU pods through 2026-09-28 (UTC days).
    - `eval/ledger.md` stops at 2026-09-26 22:10 IST and adds up to about $51. It misses race 1 ($33.19)
      and part of the v7/v8 chain.
    - Against the $500 cap, **about $404 remains**.

---

## 1. How the harness and vLLM serve an adapter

### 1.1 Bundle layout and discovery (CODE)
- Put the adapter in `adapters/<name>/` with `adapter_config.json` and `adapter_model.safetensors`.
  - Files inside a directory that holds `adapter_config.json` are grouped into one adapter
    (`SPK/adk_submission/discovery.py:374-400`).
  - The adapter's name is the directory path relative to `adapters/`, with `/` replaced by `_`
    (`:399`). Name collisions raise an error (`:421-426`).
- Only `.safetensors` counts as an adapter file on the scorer (`SPK/swegemma/config.py:31`). `.json` is an
  allowed bundle extension (`:20-30`).
  - `training_args`, `optimizer`, `scheduler`, `scaler`, `rng_state` and `trainer_state` are never treated
    as adapters (`discovery.py:307-316`).
  - Pickle weights are rejected (`data/HARNESS_README.md:144-145`).
- Size cap: 3 GiB total unpacked, adapters included (`swegemma/config.py:19`, `adk_submission/limits.py:184`).
- Adapter names must match `^[a-zA-Z0-9_.-]+$`, checked when the vLLM command is built
  (`adk_submission/server.py:58`, `:729-733`).

### 1.2 The `adapter:` YAML key and the single-model rule (CODE)
- `SandboxedLlmAgentConfig.adapter: str | None` (`adk_submission/schema.py:262`, `:278`).
- `resolve_model` requires a base `model:` next to `adapter:` (`adk_submission/resolvers/models.py:46-58`).
  It then calls the harness resolver (`:61-62`).
- The single-model check reads only `model:` (`adk_submission/discovery.py:694-696`, `:731-737`), so an
  `adapter:` key never counts as a second model.
  - EXP: `validate_single_declared_model` on the two-adapter v10 copy returned `gemma-4-31b-it-qat-w4a16-ct`.
  - The scorer requires exactly that model (`HARNESS_README.md:185`).

### 1.3 What the scorer's notebook passes (CODE; host notebook re-run 2026-09-28 01:20 IST)
- Source: `SP/forum7/nb/ryanholbrook_getting-started-gemma-4-developer-agent/flat.txt:162-203`. Our Kaggle
  eval kernel mirrors it (`scripts/make_eval_kernel.py:58-95`).
- `discover_adapters(AGENT_DIR, adapter_extensions=ALLOWED_ADAPTER_EXTENSIONS)`.
- `VllmConfig(model=.../gemma-4-31b-it-qat-w4a16-ct/2, tool_call_parser='gemma4', reasoning_parser='gemma4',
  max_model_len=32768, dtype=bfloat16, gpu_memory_utilization=0.90, enable_auto_tool_choice=True,
  enable_lora=True, max_loras=8, max_lora_rank=128, tensor_parallel_size=4)`.
- `VllmServer(vllm_cfg, adapter_manifest=adapters)`.
- `server.create_model_registry(aliases=[declared_model, TARGET_MODEL_NAME], model_prefix='openai/')`.
- `EvalConfig(..., adapter_manifest=adapters, events_compaction_config=EventsCompactionConfig(15, 2, 14336, 5),
  context_cache_config=ContextCacheConfig(2048, 1800, 10), sandbox='subprocess')`.
- HARNESS_README disagrees on two values: `gpu_memory_utilization 0.80` and `default_chat_template_kwargs
  {"enable_thinking": True}` (`data/HARNESS_README.md:165`, `:168`). The notebook dropped the second one on
  2026-09-28.
  - Which values the private scorer uses is **UNVERIFIED**.
  - Neither matters for bundles that set `include_thoughts: false` on every stage, as v10 does.

### 1.4 How a request reaches the adapter (CODE + EXP)
1. vLLM command (`adk_submission/server.py:716-734`).
   - Only when the manifest is non-empty: `--enable-lora --max-loras max(8, n) --max-lora-rank 128
     --lora-modules name=<dir> ...`.
   - **With no adapters, LoRA mode is off.**
2. Registry. `create_model_registry` registers each adapter name, plus `adapter:<name>`, as
   `LiteLlm(model="openai/<name>")` (`server.py:398-421`, `:457-465`).
3. Compile. The harness passes
   `adapter_resolver_fn=lambda base, info: resolve_swegemma_adapter(base, info, config.models)`
   (`swegemma/harness/agent_runner.py:334-346`).
   - That returns the registered adapter model (`swegemma/models/registry.py:44-46`).
   - Otherwise it rewrites the base model to `openai/<adapter_name>` (`:48-58`).
   - The thinking bridge then clones the model per agent, so settings do not leak between stages that share
     an adapter (`adk_submission/resolvers/generation.py:99-106`).
4. LiteLLM strips `openai/`, so the request body carries `"model": "<adapter_name>"`.
   - vLLM routes requests by `--lora-modules` name. **EXP** confirms both the stripping and the routing, see
     below.
5. **EXP** (`EV/capture_adapter.py`, output `EV/bodies_adapter.json`): v10 copy, two dummy PEFT dirs, forced
   compaction in the fixer, real `scripts/run_eval.py` path with a scripted model.

   | request author | `model` field sent |
   |---|---|
   | setup, verifier | `gemma-4-31b-it-qat-w4a16-ct` |
   | locator | `v11_loc` |
   | fixer | `v11_fix` |
   | `_summarizer` (compaction during the fixer) | **`v11_fix`** |

   The task resolved. The vLLM command built from the same manifest was
   `--enable-lora --max-loras 8 --max-lora-rank 128 --lora-modules v11_fix=... v11_loc=...`.

### 1.5 Naming traps in LiteLLM (CODE)
- `google/adk/models/lite_llm.py:814` and `:961` send tool results as `role="tool_responses"` when the model
  string contains `"gemma4"`.
  - The June template has no branch for that role (`EV/chat_template_kaggle_v2_june.jinja:217`, `:263-305`).
    It would render a `<|turn>tool_responses` turn.
  - **An adapter name must not contain `gemma4`.**
- LiteLLM treats `o<digit>...` and `gpt-5...` names as OpenAI reasoning models
  (`litellm/llms/openai/chat/o_series_transformation.py:117-124`, `gpt_5_transformation.py:83-84`).
  - Use plain names such as `v11_fix`.
- The notebook sets `litellm.drop_params = True` (flat.txt:166).

### 1.6 Memory and speed of LoRA mode (estimate, UNVERIFIED)
- Adapter size per rank is exact: 7,651,840 parameters per rank unit over the 7 projections of the 60 text
  layers. The 10 full-attention layers have no `v_proj`.
  - This matches train1's print: `trainable params: 122,429,440` at r=16
    (`backups/backups/20260926T095858Z-train1/train_smoke.log`).
  - bf16 adapter file sizes: r8 122 MB, r16 245 MB, r32 490 MB, r64 979 MB, r128 1.96 GB.
  - Five r16 adapters total 1.2 GB. Three r64 adapters total 2.9 GB, which fits under the 3.22 GB cap.
- vLLM pre-allocates LoRA slots for `max_loras x max_lora_rank`, and those are fixed at 8 x 128 on the scorer.
  - By my arithmetic that is about 3.6 B parameters, about 7.3 GB, per L4 at TP4, whatever rank we train.
  - The host's notebook served the sample adapters on 4×L4 (vLLM up in ~663 s, `research/org_update_0928.md`
    §1.2), so it fits.
- The decode slowdown of a LoRA request, and of base requests while LoRA mode is on, has **not been measured**.
  One Kaggle L4 run of v10 with a dummy adapter answers it.
- Model facts from HF `google/gemma-4-31B-it-qat-w4a16-ct` `config.json`:
  - `Gemma4ForConditionalGeneration`, 60 layers, hidden 5376, MLP 21504, 32 heads.
  - Every 6th layer is full attention with `attention_k_eq_v` and 4 KV heads of dim 512.
  - W4A16 group-32 symmetric int4 on every text Linear except `lm_head`.
- The PEFT key format the host's sample uses is
  `base_model.model.model.language_model.layers.N.self_attn.q_proj.lora_A.weight`
  (`submissions/v4_lora_test/adapters/main_lora/adapter_model.safetensors` header).
- **UNVERIFIED on GPU**:
  - Whether vLLM 0.19.1 loads all-projection adapters on the `k_eq_v` layers. `packed_modules_mapping` is
    `qkv_proj=[q,k,v]`, `gate_up_proj=[gate,up]`, and "k_eq_v layers use separate q_proj + k_proj without
    packing" (`SP/org0928/vsrc/v25_gemma4.py:1461-1473`).
  - Whether adapter outputs differ from base after the 2026-09-27 fix.
  - The host's sample adapters only touch `q_proj`/`o_proj` of layer 0 (`data/sample_submission/adapters/*/adapter_config.json`).

---

## 2. The exact prompt of every LLM call under the harness (v10)

Method (EXP): `EV/capture.py` runs the real v10 bundle through `scripts/run_eval.py` with the mock model of
`tests/v10_support/mock_llm.py` and records every OpenAI request body (`EV/bodies_a.json`, scenario a;
`EV/bodies_d.json`, scenario d with forced compaction). `EV/render.py` then renders each body exactly as vLLM
0.19.1 does for the scorer. `EV/rendered_v10_locator_call4.txt` is one full rendered prompt.

### 2.1 Request body (EXP)
- Messages. Stage 1 sends `[system, user]`. Later calls append `assistant{tool_calls}` / `tool` pairs.
- Params per stage:
  - `max_completion_tokens` is 256, 1536, 2048, 2048 and 1024 for setup, locator, fixer, verifier and
    submitter.
  - `temperature` 0.2 / 1.0 / 1.0 / 1.0 / 0.2, `top_p 0.95`, `top_k 64.0` (sent as a float).
  - `chat_template_kwargs {"enable_thinking": false}`. No seed.
- Tools:
  - Setup, locator and fixer get 12 tools, in YAML order: `run_command, read_file, edit_file, write_file,
    get_status, get_code_neighbors, search_similar_code, get_code_subgraph`, then the skill tools
    `list_skills, load_skill, load_skill_resource, run_skill_script`.
  - Verifier and submitter get 13, with `submit_patch` inserted after the graph tools.
  - The order follows `_process_agent_tools` (`google/adk/flows/llm_flows/base_llm_flow.py:440-467`).

### 2.2 System instruction assembly (CODE, order verified in EXP)
- Request processors run in this order: basic, auth, confirmation, **instructions**, **identity**,
  **compaction**, **contents**, and so on (`google/adk/flows/llm_flows/single_flow.py:41-68`). Tools are
  processed afterwards (`base_llm_flow.py:962-992`).
- Parts are joined with `\n\n` (`google/adk/models/llm_request.py:103-125`):
  1. The stage instruction, with `{problem_description}`, `{plan?}` and `{fix_notes?}` filled from session
     state (`google/adk/flows/llm_flows/instructions.py:56`, `:94`).
     - v10 placeholders: locator `{problem_description}`; fixer `{problem_description}` and `{plan?}`;
       verifier all three; submitter `{plan?}`.
  2. `You are an agent. Your internal name is "<name>". The description about you is "<description>".`
     (`identity.py:37-40`).
  3. The SkillToolset boilerplate, 1,333 chars (research/harness_runtime.md §4).
- Rendered sizes:
  - The system text is 1,898 / 3,880 / 3,890 / 3,810 chars for setup / locator / fixer / verifier.
  - Tool declarations are 6,781 chars, or 7,117 with `submit_patch`.
  - A stage's first prompt is 10.5-11.1 K chars, about 3.1-3.3 K tokens by the mock's estimate.

### 2.3 What each stage sees (`include_contents: none`) (CODE + EXP)
- Stage 1 (setup) gets the harness user prompt from `build_agent_prompt`
  (`swegemma/harness/agent_runner.py:55-190`).
  - It contains the problem, budgets, rules and a 3-level tree.
  - It gets the "Code Intelligence Tools" section only when graph files exist (`:144-183`).
- Stages 2+ get one user message whose content is a list of two text parts: `For context:` and
  `[<previous stage>] said: <its final text>`
  (`google/adk/flows/llm_flows/contents.py:542-582`, `:616-672`).
  - Rendered, the parts join with **no separator**: `For context:[setup] said: READY`.
- After an in-flow compaction:
  - The stage restarts at `[system, user]`, and the user content becomes
    `For context:[model] said: <summary>` (EXP, scenario d).
  - The summariser request is a single user message with no `max_completion_tokens`, sent to the stage's own
    model, adapter included.

### 2.4 How the June template renders it (CODE + EXP)
- Scorer template:
  - Kaggle model `google/gemma-4/other/gemma-4-31b-it-qat-w4a16-ct/2`.
  - `chat_template.jinja` of 16,934 B, sha256 `94899c0f...`, dated 2026-06-05.
  - Copy at `EV/chat_template_kaggle_v2_june.jinja`; tokenizer config at `EV/tokenizer_config_kaggle_v2.json`.
  - Provenance: research/pain_points.md finding 3.
- The pod serves HF main instead (the 2026-07-15 template, 18,683 B), and so does the training base
  `google/gemma-4-31B-it-qat-q4_0-unquantized` (HF sibling listing, 18,683 B).
- **Content format is `openai`.** vLLM's own detector (`vllm/renderers/hf.py:259-276` at v0.19.1, run in
  `EV/detect.py`) finds the `for item in message['content']` loop.
  - Every string content is therefore wrapped as `[{"type":"text","text":...}]`
    (`SP/chat_utils_0191.py:1503-1553`).
  - Consequences:
    - The system turn renders as `trim(system) + ' '`. A trailing space comes before the first `<|tool>`
      (template `:186-193`).
    - Multi-part user content is trimmed and concatenated (`:314-321`).
- Tool-call arguments are `json.loads`-ed back into dicts before rendering (`chat_utils_0191.py:1555-1578`).
  - They are rendered as `<|tool_call>call:NAME{k:v,...}<tool_call|>`.
  - Keys are sorted (`dictsort`), and strings are wrapped as `<|"|>...<|"|>` with no escaping
    (template `:118-147`, `:243-258`).
- Tool results are matched to calls by id (template `:270-305`) and rendered inline in the same model turn:
  `<|tool_response>response:NAME{value:<|"|>CONTENT<|"|>}<tool_response|>` (template `:160-173`).
  - After a tool response nothing closes the turn (`:339-343`).
- CONTENT is the ADK tool message:
  - `json.dumps(response, ensure_ascii=False)` (`lite_llm.py:546-560`, `:803-821`).
  - swegemma tools return `json.dumps(dict)` strings (`swegemma/tools/base.py:11-31`), which ADK wraps as
    `{'result': <string>}` (`google/adk/flows/llm_flows/functions.py:1116-1117`). The result is double
    encoding:
    `{"result": "{\"status\": \"ok\", \"stdout\": \"...\\n\", ...}"}`.
  - Skill tools and ADK's own argument-error replies return dicts, so they are encoded once:
    `{"skill_name": ..., "stdout": ..., "status": "success"}`.
- Generation prompt (template `:347-353`):
  - It is added only when the last message is not a tool response.
  - With `enable_thinking` false it is `<|turn>model\n<|channel>thought\n<channel|>`, which adds 4 tokens.
  - So **only the first call of a stage (or of a post-compaction segment) ends with that string**. Every later
    call's prompt ends in `<tool_response|>`, and the model continues its own open turn.
- Stop tokens: `generation_config.json` `eos_token_id: [1, 106, 50]`, which are `<eos>`, `<turn|>` and
  `<|tool_response>` (tokenizer.json added tokens; `EV/generation_config_hf_w4a16.json`).
  - A tool-call completion ends by emitting `<|tool_response>`.
  - A text reply ends with `<turn|>`.

### 2.5 Prefix structure (EXP, `EV/prefix.py`)
- Within a stage, prompt(k+1) starts with prompt(k) for every k ≥ 2.
- From call 1 to call 2 they diverge only by the 26-char generation prompt.
- Therefore **two token sequences per stage segment reproduce every call exactly**:
  1. The first call's prompt plus completion 1.
  2. The stage's final prompt plus the last completion, with loss on completions 2..n.

  One sequence per stage is exact for calls 2..n. For call 1 it is off by those 4 tokens.

---

## 3. Can a training conversation be rebuilt from the traces?

### 3.1 What a SessionTrace stores (CODE `SPK/adk_eval_core/tracing/trace.py`, `atif_converter.py`; DATA)

| needed for a byte-exact sample | stored? | where / why not |
|---|---|---|
| harness user prompt | yes, full text | `task_prompt` step (`agent_runner.py:463-467`) |
| stage system instruction | **no** | recorded only if the root agent has an `instruction` (`agent_runner.py:446-462`). Roots are SequentialAgents, so 0 of 125 traces checked have it. Rebuild from bundle + state |
| tool declarations | **no** | static per bundle + harness version. Rebuild by compiling, or capture as in §2 |
| model tool calls | parsed name + args dict only | `trace.py:182-205`. Ids are renamed `call_<i>` (`atif_converter.py:44`) |
| raw model text | **no** | only the stripped `text` of text parts (`trace.py:255-279`). Thought parts are stored separately |
| tool results | yes, but re-encoded | `json.dumps(unwrap_tool_response(fr))`: the `{"result": ...}` wrapper is removed and `ensure_ascii=True` (`trace.py:207-231`, `adk_eval_core/utils/utils.py:14-44`) |
| per-call prompt/completion tokens | yes | step `metrics` (`trace.py:123-138`) |
| compaction summary | **no** | in-flow compaction yields no event (`google/adk/flows/llm_flows/compaction.py:44-55`). EXP: scenario d's summary text is absent from its trace |
| stage author per step | yes | `extra.author` |

Sample checked: 51 traces of race1 r_v9_eog and 74 of kaggle e74_v3. Step types:

| trace set | tool-call steps | final | thinking | continuation nudge |
|---|---|---|---|---|
| race1 r_v9_eog | 2,512 | 151 | 5 | 1 |
| kaggle e74_v3 | 2,942 | 192 | 6 | 1 |

Neither set has any `system_instruction` or compaction step.

### 3.2 Rebuilding the model-visible bytes
- For a swegemma tool whose trace result parses to a dict with `status`: the model saw
  `json.dumps({"result": <trace string>}, ensure_ascii=False)`.
- Otherwise it saw `json.dumps(json.loads(<trace string>), ensure_ascii=False)`.
- Tool calls re-render through the template from the parsed args.

### 3.3 Verification against recorded token counts (EXP + DATA, `EV/recon.py`, `EV/recon2.py`; Gemma 4 tokenizer from HF `google/gemma-4-31B-it-qat-w4a16-ct`)
"Increment" means: tokens(rendered call + response block) compared with the delta of `prompt_tokens` between
consecutive calls of the same stage.

| trace set | continuation increments exact | first-call increments at -4 | compaction drops | raw completion = canonical (+0) | = canonical + empty thought channel (+4) | other |
|---|---|---|---|---|---|---|
| kaggle e74_v3 (June tmpl) | 2,391 / 2,391 (+53 at -4: all 53 are the first call after a compaction, e.g. fastapi_14301 14,340 → 1,236 tokens, which reopens the turn with a generation prompt) | 203 / 216 | 55 | 1,423 | 1,340 | 158 (5.4%) |
| kaggle e74_v2 | 3,262 / 3,262 | 77 / 77 | 95 | 2,082 | 1,168 | 263 (7.5%) |
| race1 r_v4 + r_v9_eog (July tmpl) | 4,285 / 4,285 | 294 / 303 | 0 | 2,844 | 1,793 | 254 (5.2%) |

- "Other" completions are calls whose raw text differs from the canonical render. They are mostly the
  malformed calls counted in §4.5.
- Final text replies carry the empty thought channel in 183 of 194 cases (e74_v3) and 142 of 151 (race1).
- **Conclusion:** exact reconstruction is possible for every call except:
  - post-compaction segments, because the summary is lost;
  - about 5-7% of calls whose raw text is unknown;
  - stage system prompts, which must be regenerated from the exact bundle version that produced the run.
- The empty-channel prefix can be recovered per call from `completion_tokens` (a +4 difference).
- Pod traces were generated under the July template. Their steady-state call/response bytes are identical under
  June rendering, as the 4,285 exact increments show.

---

## 4. Inventory of our Gemma-4-31B trajectories (DATA, `EV/inventory.py`, `EV/tables.py`, rows in `EV/inventory_rows.jsonl`)

Scope:
- 1,367 model-run traces: `eval/**/traces` plus the 4 `h_*` runs in `backups/backups/20260926T095858Z-train1`.
- Excluded, because they have 0 agent steps: `oracle*`, `nopatch_all`, `rescore_fair`.
- Model name: `gemma-4-31b-it-qat-w4a16-ct` in 1,216 traces, the Kaggle model path in 151. **All are
  Gemma-4-31B's own outputs.**

### 4.1 Per source

| source | runs | traces | resolved | tasks resolved |
|---|---|---|---|---|
| race1 (pod H100, July tmpl, no compaction) | 10 | 354 | 114 | 35 |
| eval3 fair (pod H100, 6 min cap) | 6 | 298 | 95 | 32 |
| h100b (**byte-identical copy of eval3 p_v4/p_v6**) | 2 | 148 | 48 | 27 |
| backup train1 h_v3_g1, h_v4, h_v5a, h_v5b (pod) | 4 | 222 | 57 | 29 |
| kaggle e74_v2, e74_v3, v2_smoke (4×L4, June tmpl, compaction) | 3 | 151 | 42 | 27 |
| runs sw1_*, smoke_* (pod, early) | 6 | 194 | 41 | 16 |
| **total / unique** | | 1,367 | **397 / 349** | **43** |

- Kaggle-env rescore (`kaggle/rescore_fair/results.jsonl`) flips 7 eval3 failures to passes and none the
  other way: p_v4 fastapi_13537, p_v6 rich_4079, fastapi_13537, fastapi_11194, p_v7 rich_4079, fastapi_11194,
  p_v8 fastapi_13537.
- With those: 356 trajectories, 44 tasks.
- Only the 42 Kaggle trajectories were produced under the scorer's template and compaction. 15 of them
  compacted at least once.

### 4.2 Per bundle version (unique resolved)
v9 family 96 (v9_eog 29, v9_eg 23, v9_c 16, v9_eo 14, v9_og 14), v4 65, v2 31, v7 25, v6 22, v8 22, v3 22,
v3_g1 19, v1 variants 30, v5a 9, v5b 8. **v10: 0.**

### 4.3 Per task (397 resolved, before dedup)
- Resolved runs per task range from 1 to 23. Histogram as {runs: tasks}: 1:3, 2:5, 3:2, 4:3, 5:1, 6:2, 8:4,
  9:2, 10:2, 12:5, 13:1, 14:5, 15:2, 16:2, 17:3, 23:1.
- Top: rich_3006 23, rich_2725 17, rich_2943 17, rich_3905 17, fastapi_14458 16, rich_3894 16.
- Only once: fastapi_14616, rich_3470, rich_3278.
- Runs by repo: rich 189, fastapi 183, requests 22, httpx 3.
- These are public tasks. The hidden repos differ, so hold out by task, or better by repo, when measuring
  training gains.

### 4.4 Stage structure and tokens (resolved)
- Stage patterns:
  - `locator/fixer/verifier`: 317.
  - Single agent `swe_fixer` (v1/v2): 61.
  - v5 loop runs `fixer_a/b/c`: 19, with up to 70 stage switches.
  - Restarted pipelines: 2.
- Median calls per segment: locator 11 (p90 26), fixer 4 (13), verifier 8 (16).
- Per run:
  - LLM calls: median 28, p90 58, max 115.
  - Completion tokens: median 2,349, p90 5,171.
  - Max prompt: median 11,777, p90 19,271, max 28,268.
- Training volume for the 349 unique runs, one sequence per stage segment (1,421 segments):
  - 11.3 M tokens, of which 1.0 M are supervised completion tokens (8.9%).
  - Exact first-call samples add 6.5 M tokens.
  - Segment length: median 6.7 K, p90 14.9 K, max 31.9 K.

### 4.5 Tool-call validity inside successful runs
- 110 of 397 resolved runs contain at least one malformed call: 334 of 12,540 calls.
  - Extra keys: 212. Missing required: 113. ADK rejection text: 9.
  - 14 runs have 5 or more.
- 54 calls in 23 runs pass literally quoted strings, e.g. `file_path: "\"install.py\""`, which fails with
  `SKILL_NOT_FOUND`.
- 96 steps carry more than one tool call (the scorer does not support parallel calls, 743964). 11 steps are
  unparsed text.
- Across all 1,367 runs, 11,132 of 68,511 calls (16%) are malformed. Successful runs are much cleaner (2.7%).
  Malformed calls and their echoes still have to be masked or cut, not trained on.

### 4.6 Action-space mismatch with v10 (share of calls in resolved runs)
- `run_command` other than helpers or pytest: v4 42%, v9 44%, v1/v2 54%.
- `read_file`: 20-35%.
- `edit_file`: 5-18%.
- `/tmp/swe/*` helpers: 3-10%.
- v10 teaches `locate/grep/view/edit/run/verify/finalize/status` through `run_command`, plus a setup stage
  and a submitter stage. So none of the 349 matches v10's prompts or helpers.

### 4.7 Duplicates
- 48 byte-identical tool-call sequences among resolved runs: all 26 + 22 h100b copies of eval3 p_v4 and p_v6.
- 148 duplicates across all runs, the same two copies (74 + 74).
- No other exact duplicates. Same-task repeats (up to 23 per task) are near duplicates and should be capped
  per task.

---

## 5. State of the training code and what own-trajectory SFT needs

### 5.1 `train/sft.py` (94 lines)
Works as intended:
- LoRA with r16 / alpha 32 on the language model's q/k/v/o/gate/up/down (`:73-74`). This gives 122,429,440
  parameters, consistent with §1.6.
- `device_map="auto"` on the bf16 QAT base `google/gemma-4-31B-it-qat-q4_0-unquantized` (`:11`, `:70`).
- Span masking on the final rendering (`:24-46`) supervises model turns up to and including `<|tool_response>`
  and `<turn|>`.
- `mm_token_type_ids=0` (`:86`).
- It writes a PEFT dir and repoints `base_model_name_or_path` to the served model (`:91-93`).
- Refuses empty data (`:64-65`).
- 6 masking tests pass (`tests/test_sft_masking.py`, run 2026-09-28).

Must change for byte-exact own-trajectory SFT:
1. **Template.** `tok.apply_chat_template` (`:19-22`, `:49`) uses the base repo's July template. Pass
   `chat_template=open(EV/chat_template_kaggle_v2_june.jinja).read()`, or render with `EV/render.py`.
2. **Content format.** Wrap every string content as `[{"type":"text","text":...}]` before rendering, as vLLM
   does. Otherwise:
   - the system turn loses its trailing space;
   - `For context:`/`[x] said:` parts are not concatenated the way the scorer concatenates them.
3. **Generation prompt and thought channel.**
   - Render each stage segment as two sequences (§2.5).
   - Supervise the empty-channel prefix exactly where the model emitted it (`completion_tokens` +4), or drop
     it everywhere and accept a known distribution shift.
   - Today span 1 starts at `<|turn>model\n` with no channel, a context the model never sees at call 1.
4. **Double-encoded tool results.** Build tool contents as in §3.2. `ensure_ascii` matters: ADK sends
   `ensure_ascii=False` on the outer layer.
5. **Masking of bad calls.** Take malformed or quoted-arg calls and their responses out of the loss (§4.5).
   Cut post-compaction segments, because their summary is unknown (§3.1).
6. **Truncation.** Sequences are cut to 16,384 tokens from the head (`:56`), which drops the end of a long
   segment. Use segment-level samples instead (p90 14.9 K).
7. **Memory (UNVERIFIED).**
   - Full-vocabulary logits at 16 K tokens × 262,144 vocab come to about 17 GB in fp32, before the gradient.
   - Compute the loss only on supervised positions, or chunked.
   - The smoke run never reached a step.
8. **Speed.** `device_map="auto"` keeps one GPU busy at a time, and there is no packing, batching or held-out
   evaluation.
   - Rough band (UNVERIFIED): 8 FLOP/param/token × 31.4 B ≈ 2.5e11 per token, at 300-500 TFLOP/s effective.
     11.3 M tokens then take about 1.6-2.6 h, about $11-18 per epoch at $6.98/h.
   - Measure it with a 10-minute probe before quoting a price.
9. **Base mismatch (known, accepted).** Training runs on the bf16 QAT (q4_0-unquantized) weights. Serving runs
   the int4 W4A16 group-32 compressed-tensors checkpoint, so an adapter's effect on the served model is
   **UNVERIFIED** until the GPU A/B in §7.

### 5.2 `train/convert_nebius.py` (139 lines; 8 tests in `tests/test_convert.py` pass)
- Converts SWE-rebench OpenHands trajectories. The teacher is Qwen3-Coder-480B (docstring `:1`).
- **Not cleared.** The ruling on other models' outputs is still pending (743964).
- Its format is also off-scorer:
  - single-encoded tool results (`:119`);
  - `ensure_ascii=True`;
  - a generic system prompt (`train/sft_system.md`) instead of the v10 stage prompts;
  - the pre-v10 tool set (`train/harness_tools.json`, 9 tools, no skill tools).
- On train1 it kept 6,395 of 67,074 rows (`backups/.../convert_all.log`).
- Reuse its message-building skeleton only.

### 5.3 `pod/train_env.sh` (9 lines)
- Separate venv `/root/tenv`: torch 2.14.0+cu130, transformers 5.13.1, peft 0.21.0.
- Downloads the bf16 base to `/root/models/g4_bf16`. On train1 it printed `tenv ... True` and `BF16_OK`.
- Needs:
  - the June template file next to the data;
  - the Gemma tokenizer from the served checkpoint's repo. `tokenizer.json` is 32,169,626 B in both repos;
    byte identity to the Kaggle v2 tokenizer is not checked. The token-exact increments in §3.3 suggest
    they match.

### 5.4 `pod/chain_train1.sh`
- The only GPU attempt: 2026-09-26 15:27 IST (09:57 UTC).
- LoRA gate: FAIL. "Gemma4ForConditionalGeneration does not support LoRA yet", because PyPI vLLM was installed.
- `smoke30.jsonl` was empty, so there were 0 examples and then a ZeroDivisionError
  (`backups/.../train_smoke.log`).
- Both causes are fixed:
  - `pod/bootstrap.sh:11-15` now installs and asserts the wheelhouse vLLM with `supports_lora`;
  - `sft.py:64-65` and the tests guard the empty-data case.
- The wheelhouse wheel is unpinned (latest is v25, post-fix).

### 5.5 Evaluation path for an adapter bundle
- Routing needs no code change (§1.4 EXP).
- `pod/serve.sh` and `serve2.sh` must add
  `--enable-lora --max-loras 8 --max-lora-rank 128 --lora-modules <name>=<dir>`.
- `pod/bootstrap.sh:20` must install the June template (Kaggle v2 `chat_template.jinja`) instead of HF main.
- `pod/preflight.sh:21-33` already checks one LoRA request on the patched wheel.
- The Kaggle eval kernel (`scripts/make_eval_kernel.py:58-95`) already passes adapters, and it is the faithful
  path.

---

## 6. Budget

- **RunPod billing** (read-only `list-pod-billing`, 2026-09-20 to 2026-09-29 UTC days), gemma GPU pods only:

  | pod | spend |
  |---|---|
  | A40 1fs5qx44uhc3m7 | $2.81 |
  | 87kqp9osz3gn6o | $18.91 |
  | r02i1c2nbk4v6p | $28.18 |
  | 2wyl66nmji13p1, 09-26 | $13.00 |
  | 2wyl66nmji13p1, 09-27 (race 1) | $33.19 |
  | **total** | **$96.09** |

  - r02i1c2nbk4v6p is attributed by timing: it is the only other GPU pod on 09-26, and it matches the
    ledger's v7/v8 chain.
  - The CPU `kaggri-*` pods, `hcwe3jfr9da4vg`, `gp1ezbuukle7m5`, `fige2o2lcjjvgn`, `1fvk1129myatyv`,
    `ur9t9gswxfdl9d` and the $0.58/day network storage belong to other projects and are excluded.
    `kaggri-watch` (4feotin5nfg7yu) is RUNNING at $0.12/h; I did not touch it.
- **Ledger** (`eval/ledger.md`, last row 2026-09-26 22:10 IST (16:40 UTC)): about $2.7 + $20 + $14 + $14 ≈ $51.
  It has no race 1 row.
- **Remaining against the $500 cap: about $404.**
- Pod 2wyl66nmji13p1 is EXITED at $6.98/h. Its container disk is wiped on stop, so a restart needs the
  bootstrap. Kaggle L4 quota is separate and free, but queue-bound (743901).

---

## 7. Unverified, and the probe that settles each

| question | probe | cost |
|---|---|---|
| Does a trained all-projection adapter change outputs on the scorer's vLLM (post-fix wheel, k_eq_v layers)? | random `lora_B`, base vs adapter logprobs at T=0 (Whisper Last's repro) on the pod with the wheelhouse wheel | ~0.5 h pod (~$3.50), or one Kaggle L4 kernel (free quota) |
| LoRA-mode slowdown on 4×L4 (base stages and adapter stages) | v10 + dummy r16 adapter on 10 tasks in the Kaggle eval kernel, paired with plain v10 | free quota, ~1.5 GPU-h |
| sft.py memory and throughput on 2×H100 at 16 K tokens | 10-minute smoke on 20 v10-format samples | ~$2 |
| Scorer's real `gpu_memory_utilization`, compaction interval, enable_thinking default | none available (host unanswered 743752) | n/a |
| vLLM 0.19.1 accepts `return_token_ids` to log raw completions exactly | one request on the pod | part of the first probe |
