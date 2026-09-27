# Declarative submission design space (config_space)

Date: 2026-09-27. Scope: everything a submission bundle can express, and what each construct actually does at runtime.
Versions read and exercised: `adk-submission 0.2.11`, `google-adk 1.36.1`, `swegemma 0.2.7`, `adk-eval-core 0.1.0`, `litellm 1.102.1`
(all under `/Users/carson/Projects/gemma-swe-agent/.venv/lib/python3.12/site-packages`, abbreviated `SP/` below).

Method, in three layers:
1. Read the compiler, schema, builders, resolvers, the swegemma call site and the ADK runtime classes (file:line cited everywhere).
2. Compiled 106 small probe bundles (92 in the main matrix + 14 follow-ups, plus 3 direct compiles bypassing model discovery) through the official path, called exactly as `swegemma/harness/agent_runner.py:334-346`
   does (`validate_single_declared_model` -> `build_submission_limits` -> `discover_adapters` -> `compile_submission` with
   `create_tools(...)`, `setup_gemma_model_registry()`, the adapter resolver). Every PASS/FAIL below comes with the exact exception text.
3. Ran compiled bundles through the same `App` / `Runner` / `RunConfig(max_llm_calls=...)` shape as the harness, against a scripted
   local OpenAI-compatible mock server that logs every request body. That shows which parameters reach vLLM, how agents are
   scheduled, what each stage sees, and how compaction behaves. No GPU, no pod, no Kaggle calls, no spend.

Scripts (session scratchpad, ephemeral):
`/private/tmp/claude-501/-Users-carson-Projects/654244a3-b38c-45a0-96af-d7e5f0aac6ce/scratchpad/cfgspace/`
`probe_compile.py` (compile matrix, results in `compile_results.json`), `mock_openai.py` (scripted server), `probe_runtime.py`
(runtime probes R1-R7, results in `runtime_results.json`). Rerun: `cd <that dir> && env -u OPENAI_BASE_URL /Users/carson/Projects/gemma-swe-agent/.venv/bin/python probe_compile.py`
and `... probe_runtime.py R1 R2 R3 R4 R5 R6 R7`.

---

## 0. Findings ranked for v10

| # | Finding | Evidence | Consequence |
|---|---|---|---|
| 1 | **`seed` never reaches vLLM.** Neither do `response_mime_type` or `thinking_budget`. Forwarded: `temperature`, `top_p`, `top_k` (sent as a float, 64.0), `max_output_tokens` (as `max_completion_tokens`), `stop_sequences` (as `stop`), `presence_penalty`, `frequency_penalty`, plus `chat_template_kwargs.enable_thinking` and `reasoning_effort` from the thinking bridge. | `SP/google/adk/models/lite_llm.py:1946-1967` (whitelist); mock-server capture R1a: body params = `{frequency_penalty, max_completion_tokens, presence_penalty, stop, temperature, top_p, chat_template_kwargs, top_k}`, no `seed`. | The `seed: 42` in v4..v9 `configs/sampling.yaml` does nothing. At temperature 1.0, every run is a fresh sample: the +-3 task single-run noise from race 1 can't be reduced with a seed. Only `temperature` (0 = greedy) can. |
| 2 | **`thinking_budget` is never enforced.** With thinking on, only `max_output_tokens` bounds reasoning length. Thinking turns on whenever `thinking_config` is missing or unrecognised, because the vLLM server default is `enable_thinking: True`. **A typo such as `thinking_level: ULTRA` compiles and silently leaves thinking ON.** | `SP/adk_submission/resolvers/generation.py:61-116` (bridge: `include_thoughts:false` or level `none` -> off; `include_thoughts:true` or `minimal/low/medium/high` -> on; `low/medium/high` also set `reasoning_effort`; anything else -> no change). R1b defaults: body has only `max_completion_tokens: 16384`, no `chat_template_kwargs`. Compile case 78 (`ULTRA`): PASS with `extra_args={}`. | Keep the explicit `include_thoughts: false` on every LlmAgent. Add a build-time lint that rejects any `thinking_level` outside {NONE, MINIMAL, LOW, MEDIUM, HIGH}. If thinking is wanted anywhere, `max_output_tokens` is the only real cap. |
| 3 | **Any uncaught exception inside `runner.run_async` discards the whole task, including the working-tree diff and an already-submitted patch.** Three triggers can be expressed in config: (a) an instruction placeholder `{identifier}` that is not in state; (b) context overflow (`ContextWindowExceededError`); (c) a SequentialAgent/Parallel/Loop root when the last model call of an invocation crosses the compaction threshold (finding 4). | `agent_runner.py:209` (`agent_patch=''`), `:741` catches only `TimeoutError, LlmCallsLimitExceededError`, `:758-796` (fallback diff) is skipped, `:799-801` sets `Sandbox execution error`; `swegemma/evaluate.py:324-346` -> unresolved, empty patch. Runtime R2a: `KeyError: 'Context variable not found: \`undefined_var\`.'`. Result files: 69 `Sandbox execution error: litellm.ContextWindowExceededError` rows across pod runs, 0 in the Kaggle L4 runs `eval/kaggle/e74_v2`/`e74_v3` (0/148). | Treat every exception path as a lost task. Lint all instruction text for `{identifier}` that is not `{x?}`. Keep contexts small. Do not use a workflow agent as the root unless every run ends with `submit_patch` followed by a text reply (see 4). |
| 4 | **Workflow roots crash on the post-invocation compaction path.** When `events_compaction_config` is set (Kaggle scorer: `token_threshold=14336`, `event_retention_size=5`), ADK compacts at two points: in-flow before each model call, using the *current* LlmAgent (works for any root), and at the end of the invocation, using `app.root_agent`. That second path raises `ValueError: No LlmAgent model available for event compaction summarizer.` when the root is not an LlmAgent. It fires only when the run ends naturally (the harness did not break on submit+text) and the last model call's prompt reached 14336 tokens with no in-flow compaction earlier in that invocation. | `SP/google/adk/apps/compaction.py:223-236` (raise), `:475-490` (uses `app.root_agent`), `SP/google/adk/runners.py:598-610` (runs after all events, no try). Runtime C6 (Sequential root, last call at 20000 prompt tokens): `RAISED ValueError: No LlmAgent model available for event compaction summarizer.`; C2 (LlmAgent root, same script): OK, 1 compaction event; C5 (Sequential root, crossing mid-run): OK. | This is a real but narrow hazard for v4-style pipelines. The string never appears in the e74 Kaggle results, so incidence is low today. Designs with long contexts (LoopAgent, `include_contents: default`) raise it. An LlmAgent root (coordinator with `sub_agents`) is immune. |
| 5 | **Compaction does run mid-invocation in ADK 1.36.1.** The plan's claim is wrong for this version. `/Users/carson/.claude/plans/goofy-skipping-hearth.md:110` says "Compaction only runs between ADK invocations ... One long tool loop dies at 32k". In fact `CompactionRequestProcessor` runs before every model call of every LlmAgent. Once the last recorded prompt is >= 14336 tokens, it summarises older events and keeps the last 5 raw events. Every model call made while the prompt stays above the threshold triggers another summariser call, which adds latency. | `SP/google/adk/flows/llm_flows/compaction.py:32-55`, `single_flow.py:49`. Runtime C4/C5: compaction events at session indices [7, 10, 13]; requests with `n_msgs=1` are summariser calls interleaved with agent calls. | The "STATUS line every ~8 calls" prompt trick in the plan is unnecessary for overflow protection on Kaggle. **Pod runs, however, have no compaction at all** (next row). |
| 6 | **Pod races are not faithful on context length.** `scripts/run_eval.py` wraps `swegemma.cli.main`, and `cli.py:141-160` builds `EvalConfig` with no `events_compaction_config`. The Kaggle kernels set `EventsCompactionConfig(compaction_interval=15, overlap_size=2, token_threshold=14336, event_retention_size=5)` (`scripts/make_eval_kernel.py:79,95`). The organisers' README states interval 5 (`data/HARNESS_README.md:553-561`). With only 1 invocation per task, the interval barely matters: `token_threshold` is what acts. | ContextWindowExceeded rows: race1 `r_v4` 2/51, `r_v9_c` 3/51, `r_v9_eg` 4/51, `r_v9_og` 2/51, `r_v9_eo` 1/51, `c_v9_eog` 1/23, `r_v9_eog` 0/51; eval3 `p_v8` 11/74, `p_v4` 7/74, `p_v6` 5/74, `p_v7` 2/74; Kaggle e74_v2/v3 0/148. | Part of the race-1 arm gaps is overflow sensitivity that Kaggle would compact away. Re-running the arms with compaction on the pod would make the race faithful (a change to `scripts/run_eval.py`; not made here, read-only rule). |
| 7 | **ParallelAgent: one sandbox, one budget. LLM calls run concurrently, tool calls do not.** All branches use the same tool closures bound to one `SwegemmaContext` (`agent_runner.py:319`), so they share `/workspace`, the tool-call counter, the turn counter and the 5-minute timer. The 9 harness tools are sync functions. The harness `RunConfig` has no `tool_thread_pool_config`, so they run on the event-loop thread and block every branch. They also hold `ctx.tool_lock`. `run_skill_script` is different: it runs through `asyncio.to_thread`, so skill scripts in different branches run in parallel. | `SP/google/adk/flows/llm_flows/functions.py:973-979` (thread pool only if configured), `swegemma/tools/base.py:69-71` + `swegemma/context.py:68` (RLock), `SP/google/adk/tools/skill_toolset.py:494` (`asyncio.to_thread`). Runtime R3, 2 branches each doing LLM 1 s -> tool 2 s -> LLM 1 s: LLM requests overlapped (in 1.571/1.572 s, out 2.575/2.582 s). The sync tools ran **back to back on MainThread** (2.64-4.65 s, then 4.69-6.69 s). R3b, same work as a skill script: both scripts ran 8.904-10.913 s in threads `asyncio_0`/`asyncio_2`, 4.1 s wall vs 8 s serial. | Parallel best-of-k is expressible. Give each branch its own copy of the repo (skill script `cp -a /workspace $TMPDIR/wK` and edits through `run_command`, because `read_file`/`edit_file` only accept paths under `/workspace`, `swegemma/tools/workspace.py:17-47`). Raise `max_tool_calls` about k-fold in `eval_config.yaml`. Tools are only 6.5-8% of agent wall time (race1 traces: v4 mean 86.9 s model vs 6.1 s tool; v9_eog 101.9 vs 8.8), so the gain depends entirely on vLLM batching throughput on 4x L4, which has not been measured. |
| 8 | **The first branch to finish kills the others.** Once `submit_patch` has run, the first final text event from *any* agent ends the session: the harness breaks out of the event stream and cancels any other branches still running. | `agent_runner.py:556-579` and `:635-637`. | In a parallel design, only the selector (after the ParallelAgent) may hold `submit_patch`. |
| 9 | **LoopAgent cannot exit early through config.** Only `exit_loop` sets `escalate` (`SP/google/adk/tools/exit_loop_tool.py:25`), and it is not in the tool registry: `ToolNotFoundError: Tool 'exit_loop' not found in registry. Available tools: edit_file, get_code_neighbors, get_code_subgraph, get_status, read_file, run_command, search_similar_code, submit_patch, write_file`. Callbacks are ignored (row 11). AgentTool forwards only `state_delta` (`agent_tool.py:272`). The usable exits are: `max_iterations` (1..500, default 500 when omitted); the harness break after `submit_patch` plus a text reply; budget exhaustion. | `SP/google/adk/agents/loop_agent.py:82-116` (checks `event.actions.escalate`); runtime R4: `max_iterations: 3` ran exactly 3 iterations, `escalate=None` every time. | A verify-retry loop works: `LoopAgent[fixer, verifier]`, where the verifier calls `submit_patch` and replies only when the gate is green; otherwise it replies with the failure, and that reply is what the fixer sees next iteration. With `include_contents: none` an agent still keeps its own history across iterations (R4: 2, 4, then 5 messages per request), so the loop does not reset context. |
| 10 | **`agent_tool` with `skip_summarization: true` ends the calling agent's turn.** The tool-response event counts as final, so the caller's LLM loop stops. The harness then sees no patch and sends a "Please continue" nudge. The AgentTool's own agent runs in a separate Runner that has **no compaction** (no App) and a default cap of 500 LLM calls, not the remaining task turns. | `SP/google/adk/events/event.py:91-92`, `base_llm_flow.py:872`, `agent_tool.py:213,241-257` + `runners.py:1429-1430`, `run_config.py:317`. Runtime R5: `true` -> root made 1 call, final=True on the function response. `false` -> root made a 2nd call and replied. The inner agent's request was `[system, user]` with only the `request` string, tools `[]`. | The README tip "use AgentTool (skip_summarization: true)" (`data/HARNESS_README.md:666`) costs a nudge round-trip per call. Prefer `false`, or a SequentialAgent stage. Never give an AgentTool agent open-ended exploration: it can overflow with no compaction and lose the task (row 3). |
| 11 | **Callbacks are silently ignored.** The schema accepts `before/after_{agent,model,tool}_callbacks` on every agent type, but the scorer passes no `callback_registry`, so the resolver returns `{}` and nothing runs. There are no planners, `output_schema`, `input_schema`, `static_instruction`, `global_instruction`, per-agent `code_executor`, or `include_contents` values other than `default`/`none` (all rejected). | `agent_runner.py:334-346` (no `callback_registry=`), `SP/adk_submission/resolvers/callbacks.py:84-85`. Compile case 29: PASS with `callbacks={}`; case 15 (LoopAgent callback): PASS, ignored. Cases 21-27: `Extra inputs are not permitted` / `Input should be 'default' or 'none'`. | Every control mechanism must be a prompt, a tool, a skill script, a workflow class or a budget. |
| 12 | **A SequentialAgent root restarts from stage 1 on every nudge.** Sub-agents of a workflow agent are not "transferable", so `Runner._find_agent_to_run` falls back to the root. An LlmAgent coordinator with `sub_agents` resumes at whichever agent spoke last. | `SP/google/adk/runners.py:1082-1156`; runtime R6: the second `run_async` ("NUDGE") re-ran `locator` then `fixer`, and on the rerun the locator saw only the nudge text. R6b: after `transfer_to_agent(worker)`, the nudge went straight to `worker`. Real incidence: tasks where the locator re-ran = 1/51 (r_v4), 1/51 (r_v9_eog), 3/51 (r_v9_eg), 1/74 (Kaggle e74_v3). | Small effect (1-3/51 tasks). An LlmAgent root also removes the compaction crash in row 4. |
| 13 | **Skill mechanics are fragile and partly unbounded.** Facts: `run_skill_script` counts as a tool call (`AdkSandboxCodeExecutor.execute_code` calls `check_budget`). Its output is not truncated to 5000 chars; the only cap is 10 MB. The script's cwd is a temp dir, not `/workspace`. Every call writes the whole skill directory into that temp dir. `list_skills`, `load_skill` and `load_skill_resource` are free. The skill list is never put into the prompt, but the 1333-char default skill instruction is added to every request. Skill names must be kebab-case and match the directory name. `.sh` scripts are impossible because the extension is banned. `adk_additional_tools` cannot gate tools: a tool must also be in `tools:`, and after `load_skill` it is declared twice. | `SP/adk_eval_core/sandbox/base.py:176-221`, `SP/adk_eval_core/sandbox/subprocess_sandbox.py:99-101`, `skill_toolset.py:571-626` (wrapper `os.chdir(td)`), `:1062-1083`, runtime R8a: tools after load_skill = `[..., 'run_skill_script', 'submit_patch']` with `submit_patch` twice. Race-1 traces: `run_skill_script` got `SKILL_NOT_FOUND` from a quoted skill name (`"\"swe-tools\""`) in 5/30 v4 calls, 1/32 v9_eog, 5/31 v9_og. Kaggle e74_v2: 94/107 calls `INVALID_ARGUMENTS`. | Helpers must truncate their own output, use absolute paths, and survive a failed install. The helper-via-`run_command` pattern in v9 is the right one. Only `install.py` should go through `run_skill_script`, and the prompt should show the exact call. |
| 14 | **Per-request fixed overhead.** v9_eog locator: tool declarations for 12 tools = 7205 JSON chars; system prompt 3868 chars (with a 1000-char problem). Graph tools alone = 1966 chars (neighbors 823, similar 616, subgraph 527). SkillToolset = 2083 chars of declarations + 1333 chars of instruction. ADK also appends `You are an agent. Your internal name is "<name>". The description about you is "<description>".` | Mock-server capture of the compiled `submissions/v9_eog` (copied to the scratchpad). | Drop tools a stage does not use (graph tools, the skill toolset outside the stage that installs). This saves roughly 1-1.5k tokens of prefill per call. The saving is smaller if vLLM prefix caching absorbs it (UNVERIFIED whether prefix caching is on in the scorer). |

---

## 1. How a bundle becomes a running agent

- Call site: `SP/swegemma/harness/agent_runner.py:319-346`. The harness builds the tools once per task (`context.create_tools()`, 9 tools bound to one `SwegemmaContext`) and one code executor, `AdkSandboxCodeExecutor(timeout_seconds=command_timeout, max_time_minutes, budget_check_fn=context.check_budget)`. It then calls `compile_submission(submission_dir, tool_registry=tools, model_registry, code_executor, script_timeout=timeout_seconds, limits, generation_constraints, adapter_manifest, adapter_resolver_fn)`.
  **Not passed:** `callback_registry` and `skill_registry`, so callbacks are no-ops and skills load from the bundle directory.
- Compiler: `SP/adk_submission/compiler.py:59-205`. Order: validate the directory -> discover adapters -> `load_yaml` (sandboxed `!include`) -> `SandboxedAgentConfig.model_validate` -> recursive `_compile_agent` (`:208-242`, max-agent check `:225-229`).
- Organiser limits and constraints: `SP/swegemma/config.py:34-68`. `SubmissionLimits(3 GiB, 50 MiB YAML, 50 MiB/skill, 10k files, 1k YAML, 1M chars/instruction, 10M total, 500 agents, depth 50, 1000 skills, loop <= 500)`. `GenerationConstraints(allowed_fields=None, max_output_tokens=NumericRange(1, 32768), thinking_budget=NumericRange(0, 32768), defaults={'max_output_tokens': 16384, 'thinking_config': {'thinking_budget': 4096}})`.
- Session state at start (`agent_runner.py:392-402`): `problem_description`; `hints` only if non-empty. **All 129 tasks in `data/tasks.jsonl` have empty `hints_text`**, so `{hints}` would crash every task. Use `{hints?}`.
- App: `plugins=[EventDisplayPlugin, ModelRetryPlugin]`, plus `context_cache_config` / `events_compaction_config` if the caller set them (`:403-414`). The submission cannot configure either.
- Outer loop (`:503-739`): `RunConfig(max_llm_calls=remaining_turns)` per `run_async`. It breaks on submit + final text (`:569-579`), after a run if a patch was submitted (`:635-637`), on the time/tool/turn budget, or on 3 consecutive nudges without tool calls (`:677-739`; a turn with any tool call resets the counter). If no patch was submitted, the working-tree diff is taken as a fallback (`:760-785`), **but only when no exception escaped** (row 3).
- eval_config.yaml: only `timeout_seconds`, `max_tool_calls`, `max_time_minutes`, `max_turns`/`max_llm_calls` are read (given; getting-started notebook cell 10 matches). Extra keys are ignored (compile case 112 PASS).

## 2. Agent classes

Discriminated union on `agent_class` (`SP/adk_submission/schema.py:373-411`); a missing or null value means `LlmAgent` (`:300-303`, `:388-389`). Every class has `extra="forbid"`.

| Class | Fields accepted (schema.py) | Builder | Notes |
|---|---|---|---|
| `LlmAgent` | name, description, model, adapter, instruction (**required**), output_key, include_contents (`default`/`none`), disallow_transfer_to_parent, disallow_transfer_to_peers, tools, skills, sub_agents, generate_content_config, 6 callback lists (`:256-322`) | `builders/llm.py:33-96` | `model` is effectively required on **every** LlmAgent: the compiler passes `model=None` explicitly, which ADK rejects (case 35: `model.str Input should be a valid string ... model.BaseLlm Input should be a valid dictionary or instance of BaseLlm`). `sub_agents` on an LlmAgent adds the `transfer_to_agent` tool (R6b tools `['transfer_to_agent']`). |
| `SequentialAgent` | name, description, sub_agents (required, may be `[]`), before/after_agent_callbacks (`:325-334`) | `builders/workflows.py:40-68` | No instruction, output_key or generate_content_config (cases 13, 106, 113: `Extra inputs are not permitted`). |
| `ParallelAgent` | same as Sequential (`:337-346`) | `workflows.py:71-99` | Branch ctx `"{parent}.{child}"` (`SP/google/adk/agents/parallel_agent.py:35-47`), `asyncio.TaskGroup` merge (`:71`). Event history is isolated per branch; state, tools, sandbox and budgets are shared. |
| `LoopAgent` | same + `max_iterations` int >= 1 (`:349-365`) | `workflows.py:102-142` | Omitted -> 500 (`:124-126`); > 500 -> `LimitExceededError: Agent 'l': max_iterations=501 exceeds limit of 500`; 0 -> `Input should be greater than or equal to 1`; `2.0` is accepted as 2. |
| Anything else (`Agent`, `CustomAgent`, `BaseAgent`, dotted paths) | - | - | `Input tag 'Agent' found using agent_class_discriminator() does not match any of the expected tags: 'LlmAgent', 'SequentialAgent', 'ParallelAgent', 'LoopAgent'` |

Names: ADK requires a Python identifier and forbids `user` (cases 31, 32, 110: `Found invalid agent name: \`bad-name\`...`, `Agent name cannot be \`user\``). Duplicate sibling names compile with only a warning: `Found duplicate sub-agent names: \`a\`. All sub-agents must have unique names.` (case 33). A parent and child may share a name (case 34). Depth: a cycle stops at `LimitExceededError: Sub-agent nesting too deep: 51 (max 50)` (case 109). `sub_agents[].config_path` resolves relative to the including file's directory first, then the bundle root (`SP/adk_submission/context.py:97-121`; cases 100, 101 PASS).

Arbitrary nesting compiles: `Sequential[LlmAgent, Loop(max 2)[Parallel[f1, f2], judge]]` PASS (case 09).

## 3. LlmAgent field semantics that matter

| Field | Runtime meaning (verified) |
|---|---|
| `instruction` | The system prompt. Templated on every call (section 10). Can be `!include`d from `.md`/`.txt` only. |
| `include_contents: none` | History starts at the latest event authored by `user` **or by another agent** (`SP/google/adk/flows/llm_flows/contents.py:542-582`). In a Sequential pipeline, stage 2 sees only stage 1's **last** event, as `For context: [locator] said: <text>` (R6), not the harness prompt. Stage 1 sees the harness prompt (or, after a nudge, only the nudge text). Inside a LoopAgent, the same agent keeps its own previous iterations (R4). |
| `include_contents: default` | Full session history filtered by branch. Other agents' text, tool calls and tool results are rendered as user-role `For context:` lines (`contents.py:616-676`); R7 judge saw `start`, `[fa] said: ANSWER_A`, `[fb] said: ANSWER_B`. |
| `output_key` | Written only from a final **text** response of that agent (`SP/google/adk/agents/llm_agent.py:842-871`). A stage that ends on a tool call or a budget stop leaves the key unset, so downstream templates must use `{key?}`. Parallel branches need distinct keys; state is shared (R7 `{'out_a': 'ANSWER_A', 'out_b': 'ANSWER_B'}`). |
| `description` | Added to the system prompt (identity processor, `flows/llm_flows/identity.py:37`) and used as the AgentTool / transfer description. |
| `disallow_transfer_to_parent/peers` | Passed through (`builders/llm.py:90-93`). Controls the `transfer_to_agent` targets and whether the agent resumes after a nudge. |
| `adapter` | Needs `model` too (`Agent 'a' specifies adapter 'lo' without a base model alias.`) and an adapter found under `adapters/` (`Adapter 'nope' not found in discovered adapters. Available adapters: none`). Routed as `openai/<adapter_name>` (`swegemma/models/registry.py:36-65`). |

## 4. Tools

- Registry (closed): `run_command, read_file, write_file, edit_file, submit_patch, get_status, get_code_neighbors, search_similar_code, get_code_subgraph` (`SP/swegemma/tools/__init__.py:34-46`). Nothing else resolves (`exit_loop`, `google_search`: `ToolNotFoundError`, cases 41, 42).
- Allowed list-entry forms: a plain string, or `agent_tool: {config_path, skip_summarization}` (`schema.py:84-137`). **Inline agent dicts are rejected**, even though the README says they are allowed (`data/HARNESS_README.md:113`); case 45: `LlmAgent.tools.0.AgentToolEntry.agent_tool Field required`. `include_plugins` is rejected (case 46). `{name: run_command}` is rejected (case 47). Duplicate names compile (cases 48, 49), which declares the tool twice.
- Budget accounting: `budget_gated` tools count 1 tool call each. `submit_patch` and `get_status` are free (`count_tool_call=False`, `swegemma/tools/execution.py:71,101`). `run_skill_script` counts 1 through the executor's `check_budget`. `list_skills`, `load_skill`, `load_skill_resource`, `transfer_to_agent` and the AgentTool call itself are free as tool calls. Every model response is 1 turn (`swegemma/context.py:276-300`, record at :298), including AgentTool inner agents, because plugins are inherited.
- `submit_patch` can be called repeatedly; the last diff wins (`execution.py:70-96`). Once called, it arms the harness termination (row 8).
- File tools accept only paths under `/workspace` (`swegemma/tools/workspace.py:17-47`).
- The submission cannot declare any per-agent tool budget, turn budget or time budget. The only per-agent bounds are `max_output_tokens` (per response) and `LoopAgent.max_iterations`. ADK's own `RunConfig.max_llm_calls` is per invocation and shared by all sub-agents (`SP/google/adk/agents/invocation_context.py:71-98`).

## 5. Skills

- Declared with `skills: [relative/dir]` on an LlmAgent. Loaded with `google.adk.skills.load_skill_from_dir`. Name rules: kebab-case, at most 64 chars, equal to the directory name (case 51: `Skill name 'other' does not match directory name 'sk'.`; case 53: `name must be lowercase kebab-case (a-z, 0-9, hyphens)...`). Missing dir: `Skill directory not found: skills/nope`. `../x`: `PathTraversalError`.
- Compiles to a `SkillToolset(skills, code_executor=<harness executor>, script_timeout=timeout_seconds, additional_tools=<the agent's tools>)` appended after the agent's tools (`resolvers/tools.py:129-264`). Tools exposed: `list_skills, load_skill, load_skill_resource, run_skill_script` (`skill_toolset.py:938-943`). Two agents can share one skill directory (case 56).
- Script execution: only `.py` in practice, since `.sh`/`.bash` are banned by the extension whitelist (case 52). The wrapper embeds every file of the skill, chdirs into a fresh temp dir, sets `sys.argv`, and `runpy`s the script (`skill_toolset.py:571-626`). The harness writes that wrapper as `<sandbox work_dir>/.adk_exec_<8hex>.py`, runs `python3` on it with timeout `min(timeout_seconds, remaining)`, and deletes it (`adk_eval_core/sandbox/base.py:176-221`). The output is returned unmodified.
- Parallelism: `asyncio.to_thread` (`skill_toolset.py:494`). This is the only way two agents can execute in the sandbox at the same time (R3b).
- UNVERIFIED edge: if one branch calls `submit_patch` while another branch's wrapper file exists in the work dir, `git add -N .` could pick it up. Nothing was found in any patch (`grep adk_exec_` over race1/eval3 patches: 0 hits).

## 6. generate_content_config: schema, constraints, and what reaches vLLM

Schema (`schema.py:155-226`): `temperature >= 0`, `0 <= top_p <= 1`, `top_k >= 1`, `max_output_tokens >= 1`, `stop_sequences: list[str]`, `presence_penalty`, `frequency_penalty`, `response_mime_type`, `seed: int`, `thinking_config {thinking_budget >= 1, include_thoughts, thinking_level: str}`. Booleans, NaN and inf are rejected. Constraints (`limits.py:309-440` + `swegemma/config.py:59-67`): max_output_tokens <= 32768; no other ranges; unlimited stop sequences (26 PASS, case 79); temperature 5.0 PASS (case 67).
Defaults are merged when a field is omitted: `max_output_tokens: 16384`, `thinking_config.thinking_budget: 4096` (case 75/76). Neither default constrains thinking.

| Param | Accepted by compiler | Reaches vLLM (mock capture R1) |
|---|---|---|
| temperature | yes | yes |
| top_p | yes | yes |
| top_k | yes | yes, as float (`40.0`, `64.0`); vLLM accepted it in all Kaggle runs of v4 |
| max_output_tokens | 1..32768 (`Agent 'a': max_output_tokens=32769 is outside allowed range [1, 32768]`) | yes, as `max_completion_tokens` |
| stop_sequences | yes, any count | yes, as `stop` |
| presence_penalty / frequency_penalty | yes, unbounded | yes |
| seed | int only (`1.5` -> `int_from_float`) | **no** |
| response_mime_type | any string | **no** (LiteLlm builds `response_format` only from `response_schema`, which is banned) |
| thinking_config.thinking_budget | >= 1 (**0 is rejected**: `Input should be greater than or equal to 1`, even though the README says 0 disables thinking) | **no** |
| thinking_config.include_thoughts | bool | via bridge -> `chat_template_kwargs.enable_thinking` |
| thinking_config.thinking_level | any string compiles | NONE -> enable_thinking false; MINIMAL -> true; LOW/MEDIUM/HIGH -> true + `reasoning_effort`; anything else -> nothing (server default = thinking ON). `include_thoughts:false` beats a level (case 82). The Gemma 4 template may ignore `reasoning_effort`: UNVERIFIED. |
| safety_settings, candidate_count, response_schema, logprobs, http_options | rejected: `Extra inputs are not permitted` (cases 69-74) | - |

## 7. Callbacks, code executors, planners

- Callback fields exist in the schema (`schema.py:252-253, 295-298`) and compile, but they are dropped (`resolvers/callbacks.py:84-85`), because the scorer passes no registry (`agent_runner.py:334-346`).
- There is no per-agent `code_executor` (case 27 rejected). The single executor is the harness's `AdkSandboxCodeExecutor`, reachable only through skills.
- No `planner` (case 24), no structured output or input (cases 25, 26), no `static_instruction` / `global_instruction` (cases 22, 23; the README's mention of `global_instruction` at `:100` is wrong for this schema).

## 8. Files, sizes, layout

- Extensions allowed by the scorer: `.yaml .yml .md .txt .py .json .safetensors` (`swegemma/config.py:20-31`). The empty extension is **not** allowed. Every file is checked (`discovery.py:122-127`):
  `.DS_Store` -> `File has disallowed extension '': .DS_Store`; `LICENSE` -> same; `__pycache__/*.pyc` -> `File has disallowed extension '.pyc'`; `notes.sh` -> `'.sh'`. Upper-case `Run.PY` passes (lower-cased check, case 111).
  Build step: strip `__pycache__`, dotfiles and extensionless files before zipping.
- Symlinks are rejected anywhere. Total size is 3 GiB including adapters; 10k files; 1k YAML; 50 MiB per YAML and per skill dir.
- Root discovery (`discovery.py:180-250`): `agent.yaml` wins over `root_agent.yaml` **silently** (case 94 compiled the `agent.yaml` tree; the README's `MultipleRootConfigsError` does not exist in this code). With neither present, exactly one root-level YAML is required, so `agent.yml` + `eval_config.yaml` fails: `Ambiguous root config: found 2 YAML files at the root level (agent.yml, eval_config.yaml)` (case 95).
- `!include` accepts only `.md/.txt` (raw text) and `.yaml/.yml` (parsed, depth <= 10), resolved relative to the including file (`yaml_loader.py:20-24, 109-120`). `.py` -> `!include does not support '.py' files (allowed: .md, .txt, .yaml, .yml)`; `.json` likewise. YAML anchors work (case 99). Unknown top-level keys are rejected (case 104, `LlmAgent.evaluation Extra inputs are not permitted`).
- Gotcha in `validate_single_declared_model`: YAML that fails to load is skipped silently. A bad `!include` therefore surfaces as `No model declared in agent configuration`, not as the real error (cases 97, 98 vs 97b).

## 9. Model validation

`validate_single_declared_model` (`swegemma/models/discovery.py:96-122` -> `adk_submission/discovery.py:592-750`) walks root, sub_agents, agent_tool refs, and any stray YAML that has `model` plus an agent-ish key. It requires exactly one normalised model name (case 37: `Ambiguous model declaration: multiple distinct models declared ... (['gemma-4-31b-it', 'gemma-4-31b-it-qat-w4a16-ct'])`). The competition scorer also requires that name to be `gemma-4-31b-it-qat-w4a16-ct` (README section 3.2). An unregistered alias fails at compile time: `Model alias 'gpt-4o' not found in registry. Available models: ...` (case 38).

## 10. State and templating

Implementation: `SP/google/adk/utils/instructions_utils.py:81-149`. Regex `{+[^{}]*}+` over the instruction, one pass; substituted values are not re-scanned, so problem statements containing braces are safe (9/129 tasks contain `{...}`; direct test: `'value with {x} and {plan} braces'` survived intact).

| Placeholder | Result |
|---|---|
| `{name}` present in state | `str(value)`; a `None` value -> `''` |
| `{name}` absent | **`KeyError: 'Context variable not found: \`name\`.'` -> task lost** (R2a; also `f'{x}'` inside a code sample, R2c; also `{ x }` with spaces) |
| `{name?}` absent | `''` (R2b) |
| `{app:x?}`, `{user:x?}`, `{temp:x?}` | `''` if absent (R2e) |
| `{{name}}` | **not an escape**; substituted like `{name}` (R2f) |
| `{x.y}`, `{0}`, `{x!r}`, `{a:b}`, `{"k": 1}`, `{}` | left verbatim (not identifiers). These are the only safe ways to show braces. |
| `{artifact.f?}` | `ValueError: Artifact service is not initialized.` even with `?` (no artifact service in the harness) |

SKILL.md bodies and tool results are not templated. Suggested v10 lint over every instruction file: `re.findall(r'{+([^{}]*)}+', text)`, then fail on any capture that, after `strip()`, is an identifier or `prefix:identifier` and does not end in `?` (unless it is `problem_description`).

## 11. Control-flow facts for design (all runtime-verified with the mock unless noted)

1. The harness prompt goes only to the first agent to run. Downstream stages depend on `{problem_description}` and `output_key`s (R6).
2. Sequential + nudge = restart from stage 1 (R6). An LlmAgent root with `sub_agents` resumes the last speaker (R6b).
3. LoopAgent: no early exit except `max_iterations`, submit+text, budgets or exceptions (R4, finding 9).
4. ParallelAgent: model calls run concurrently; harness tools serialize and block the event loop; skill scripts run concurrently; everything is shared (R3/R3b, finding 7). The first submit + text anywhere ends the task (finding 8).
5. AgentTool: separate session seeded with a copy of state (minus `_adk*`), the `request` string as the only user message, state deltas forwarded back, no compaction, 500-call default cap; `skip_summarization: true` ends the caller's turn (R5, finding 10).
6. Compaction (Kaggle only): in-flow before each call at a last prompt >= 14336 tokens, keeping 5 raw events (C4/C5); the post-invocation path crashes workflow roots (C6).
7. Budgets: one global tool counter, turn counter and timer per task. Nothing per agent.

## 12. Compile probe matrix (106 cases)

PASS: 01, 02 (agent_class null), 03 Sequential, 04 Parallel, 05 Loop max 3, 06 Loop default -> 500, 09 nested Seq/Loop/Par, 10 LlmAgent + transfer sub-agent, 12b explicit `LlmAgent`, 14 Sequential with `sub_agents: []`, 15 Loop + callback (ignored), 20 output_key + include none, 29 model/tool callbacks (ignored), 30 5000-char description, 33 duplicate sibling names (warning), 34 parent/child same name, 40 all 9 tools, 43 agent_tool skip_summarization, 44 agent_tool wrapping a SequentialAgent, 48/49 duplicate tools, 50 skill, 54 skill with references/assets, 55 skill `adk_additional_tools`, 56 shared skill, 60 all gen fields, 61 level HIGH, 62 level NONE, 65 max_output 32768, 67 temperature 5, 72 response_mime_type json, 75/76 defaults merge, 77 include_thoughts true, 78 bogus level (silent), 79 26 stop sequences, 82 LOW + include_thoughts false, 94 agent.yaml + root_agent.yaml, 96 `!include` md + yaml, 99 anchors, 100/101 nested relative paths, 105 braces in instruction (compile-time only), 107 max_iterations 2.0, 108 parallel agents sharing tools, 111 `.PY`, 112 eval_config extra keys.

FAIL (exact text, abbreviated only where the pydantic URL line was dropped):
- 07 `LimitExceededError: Agent 'l': max_iterations=501 exceeds limit of 500`
- 08 `LoopAgent.max_iterations Input should be greater than or equal to 1`
- 11b/12c `Input tag 'CustomAgent'|'Agent' found using agent_class_discriminator() does not match any of the expected tags: 'LlmAgent', 'SequentialAgent', 'ParallelAgent', 'LoopAgent'`
- 13/106/113 `SequentialAgent.instruction|generate_content_config|output_key Extra inputs are not permitted`
- 21 `LlmAgent.include_contents Input should be 'default' or 'none'`
- 22-27 `LlmAgent.global_instruction|static_instruction|planner|output_schema|input_schema|code_executor Extra inputs are not permitted`
- 28 `LlmAgent.instruction Field required`
- 31/110 `Found invalid agent name: \`bad-name\`|\`a.b\`. Agent name must be a valid identifier...`; 32 `Agent name cannot be \`user\`. \`user\` is reserved for end-user's input.`
- 35 child without model: `2 validation errors for LlmAgent model.str Input should be a valid string ... model.BaseLlm Input should be a valid dictionary or instance of BaseLlm`
- 36 `No model declared in agent configuration. Expected exactly one model to be declared (e.g. 'gemma-4-31b-it').`
- 37 `Ambiguous model declaration: multiple distinct models declared across agent configuration (['gemma-4-31b-it', 'gemma-4-31b-it-qat-w4a16-ct']). This competition requires all agents in a submission to share exactly one model.`
- 38 `ModelNotFoundError: Model alias 'gpt-4o' not found in registry.`
- 41/42 `ToolNotFoundError: Tool 'exit_loop'|'google_search' not found in registry. Available tools: edit_file, get_code_neighbors, get_code_subgraph, get_status, read_file, run_command, search_similar_code, submit_patch, write_file`
- 45/47 `LlmAgent.tools.0.str Input should be a valid string ... LlmAgent.tools.0.AgentToolEntry.agent_tool Field required`; 46 `LlmAgent.tools.0.AgentToolEntry.agent_tool.include_plugins Extra inputs are not permitted`
- 51 `Failed to load skill 'skills/sk': Skill name 'other' does not match directory name 'sk'.`; 52 `File has disallowed extension '.sh': skills/sk/scripts/x.sh`; 53 `Failed to load skill 'skills/my_sk': ... name must be lowercase kebab-case (a-z, 0-9, hyphens), with no leading, trailing, or consecutive delimiters`; 57 `Skill directory not found: skills/nope`; 58 `PathTraversalError: Path traversal attempted in config: Path traversal attempted in skill: ../x`
- 63 `thinking_config.thinking_budget Input should be greater than or equal to 1`; 64 `Agent 'a': max_output_tokens=32769 is outside allowed range [1, 32768]`; 66 `temperature Input should be greater than or equal to 0`; 68 `top_p Input should be less than or equal to 1`; 69-71, 73, 74 `generate_content_config.safety_settings|candidate_count|response_schema|logprobs|http_options Extra inputs are not permitted`; 80 `temperature cannot be a boolean`; 81 `seed Input should be a valid integer, got a number with a fractional part`
- 90-93 `File has disallowed extension '.sh'|''|'.pyc'|'': ...`
- 95 `Ambiguous root config: found 2 YAML files at the root level (agent.yml, eval_config.yaml). Please name the root config 'agent.yaml' or 'root_agent.yaml'.`
- 97b/98b `!include does not support '.py'|'.json' files (allowed: .md, .txt, .yaml, .yml)` (surfaces as "No model declared" through `validate_single_declared_model`)
- 102 `Adapter 'nope' not found in discovered adapters. Available adapters: none`; 103b `Agent 'a' specifies adapter 'lo' without a base model alias.`
- 104 `LlmAgent.evaluation Extra inputs are not permitted`
- 109 `LimitExceededError: Sub-agent nesting too deep: 51 (max 50)`

## 13. Runtime probe log (mock OpenAI server)

- R1a all gen fields -> body params `frequency_penalty 0.2, max_completion_tokens 8192, presence_penalty 0.1, stop ['<END>'], temperature 0.7, top_p 0.9, chat_template_kwargs {enable_thinking: true}, top_k 40.0`. No seed or response format.
- R1b no config -> `max_completion_tokens 16384` only. R1c level HIGH -> `+ reasoning_effort 'high', enable_thinking true`. R1d (v4 sampling.yaml) -> `max_completion_tokens 4096, temperature 1.0, top_p 0.95, enable_thinking false, top_k 64.0`. `seed: 42` absent.
- R2 templating: see section 10.
- R3 parallel with sync tools: 6.2 s of branch work vs 8 s serial and 4 s ideal. The tools serialized on MainThread. R3b skill scripts: 4.1 s, truly parallel.
- R4 LoopAgent 3/3 iterations, no escalate.
- R5 AgentTool: skip true -> 1 root call; skip false -> 2 root calls.
- R6 Sequential nudge -> full restart; R6b transfer -> resume at worker.
- R7 Parallel -> judge: the judge sees both branch answers (include default) and gets `{out_a?}`/`{out_b?}` templated.
- R8 `adk_additional_tools` duplicates the declaration.
- C2/C4/C5/C6 compaction: see findings 4 and 5.
- (Artifact, not a finding: an early C3 run looped because the mock chose steps by counting tool messages, which compaction removes. Fixed with server-side step counters.)

## 14. Concrete v10 consequences

1. Root: prefer an **LlmAgent coordinator** with `sub_agents`, or keep the Sequential root and guarantee that the final stage always ends with `submit_patch` and then a text reply. The first option removes the compaction crash (finding 4) and the nudge restart (finding 12).
2. Every instruction goes through a brace lint (section 10). Only `{problem_description}` and `{key?}` forms are allowed. Never `{hints}`.
3. Sampling: drop `seed` (dead). Pick temperature deliberately. For low-noise dev races, consider a `temperature: 0` control arm to separate config effects from sampling noise (vLLM batching still adds some nondeterminism: UNVERIFIED size).
4. Thinking: `include_thoughts: false` on every LlmAgent. If any stage enables thinking, set `max_output_tokens` to the reasoning budget you actually want. Reject unknown `thinking_level` strings at build time.
5. Parallel candidates are expressible. Design: `Sequential[setup, Parallel[k fixers working in $TMPDIR copies through run_command/helpers], selector with submit_patch]`, with `max_tool_calls` raised about k-fold. Expected gain has an upper bound from race 1's union: 27/51 vs a best single arm of 21/51, so an oracle selector would give +6/51. A realistic test-based selector gives less. **The decisive unknown is vLLM batch-k throughput on 4x L4 TP=4**, because the agent is 92-94% model time.
6. Verify-retry loop: `LoopAgent(max_iterations 2-3)[fixer(include none), verifier(submit_patch only when green)]`. The verifier's failure reply is exactly what the next fixer iteration sees. Bound the iteration count, because the 12 h cliff sits at about 6 min/task all-in.
7. AgentTool: `skip_summarization: false`, short read-only tasks only (no compaction inside).
8. Skills: keep `run_skill_script` for `install.py` only. The prompt shows the literal call `run_skill_script(skill_name="swe-tools", file_path="install.py")` and a fallback if it errors. Helpers truncate their own output. Drop the skill toolset and graph tools from stages that don't use them.
9. Measurement: add `events_compaction_config` (and optionally `context_cache_config`) to the pod runner so pod races match Kaggle (finding 6).
10. Packaging: strip `__pycache__`, dotfiles and extensionless files. Use the name `agent.yaml`. No `.sh`.

## 15. Open questions / UNVERIFIED

- Does vLLM 0.19.1 with the Gemma 4 chat template do anything with `reasoning_effort`? Not tested; no chat template locally.
- Batch throughput scaling on 4x L4 TP=4 for k=2..4 concurrent 32k-context streams (needed for finding 7). Not measured; requires a GPU.
- Which compaction interval the actual scorer uses (README says 5, getting-started and our kernels say 15). It barely matters with 1 invocation per task; `token_threshold` 14336 is shared by both sources.
- Whether vLLM prefix caching is enabled in the scorer (affects how much the tool-declaration overhead costs).
- Whether the SessionTrace records compaction events. A grep of the Kaggle traces found only false positives, so actual compaction frequency on Kaggle is unmeasured.
- The skill-wrapper temp file appearing in a concurrent `submit_patch` diff (section 5) is theoretical; 0 observed.
