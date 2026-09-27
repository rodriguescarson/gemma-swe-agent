# Pain points for SWE agents on small/open models, and what fixed them

Written 2026-09-27. Scope: problems people report when building coding agents on Gemma 3/4, Qwen 2.5/3 Coder, Devstral and Llama, the fixes they used, and whether each one applies to our Kaggle harness (gemma-4-31b-it-qat-w4a16-ct, vLLM 0.19.1 `gemma4` parsers, google-adk 1.36.1, swegemma 0.2.7). Sources are Reddit (r/LocalLLaMA, r/LLMDevs), Hacker News, GitHub issues (vLLM, llama.cpp, SWE-agent, OpenHands, Aider, Goose, qwen-code, google/adk-python, google-deepmind/gemma), Hugging Face discussions, a rival entry's public experiment notes, and the Kaggle forum.

Every "applies to us" claim is marked either **MEASURED** (I computed it from our traces or code in this repo; the command shape is given) or **REPORTED** (someone else said it and I did not check it here).

Our trace base: the four fair pod runs `eval/eval3/eval/runs/p_v4, p_v6, p_v7, p_v8` (74 tasks each, the Kaggle-valid set in `data/kaggle_valid_ids.txt`).

---

## 0. The six findings that matter most

1. **edit_file is broken at the tool-call parser, not just at string matching (MEASURED, new).** In v4, 502 of 1,030 edit_file calls (49%) came back "mandatory input parameters are not present: old_string". The rate was 70% in v6, 33% in v7 and 74% in v8. The same error hit run_command 1 time in 1,831 calls and write_file 1 time in 109. The mechanism:
   - The Gemma 4 chat template sorts tool parameters alphabetically (`properties | dictsort`), so the model sees and writes `filepath, new_string, old_string`. In v4, 1,029 of 1,030 edit_file calls had new_string first.
   - The model then closes new_string with a backtick instead of the `<|"|>` delimiter token. vLLM 0.19.1's `_parse_gemma4_args` looks for the next `<|"|>`, which is the one that opens old_string. So it swallows `` `,old_string: `` into new_string and parses the old code as garbage `key:value` pairs. Example from `p_v4/traces/trace_fastapi_13537.json`: new_string ends in `` field_info`,old_string: `` and one of the keys is `for field in body_fields`.
   - Of the edit_file calls that did parse, 351 of 528 had literal `\n`, `\"`, `\uXXXX` or `\x1b` escapes in old_string. 338 of those (96%) failed with "old_string not found". Plain old_strings succeeded in 127 of 177 cases (72%).
   - End to end, only 140 of 1,030 edit_file calls in v4 (13.6%) changed a file.
   - Edit retries are most of our "loops": 810 of the 1,387 exact-repeat tool calls in v4 were repeated edit_file calls.
   - Tasks with 3 or more parse or escape failures: 13 to 19 failed tasks per run, against 0 to 2 resolved tasks.

   Fix: stop sending code through edit_file. Edit through run_command, whose single string argument parses cleanly, driving our own helper. The helper should do an exact match, then an unescape-and-retry, then a line-range replace. Add a loop breaker that switches mechanism after 2 identical failures.

2. **The harness's context compaction never shrank a prompt on the pod, and the pod runs it differently from the scorer (MEASURED).**
   - Fair v4 run: 31 of 74 tasks went over the 14,336-token compaction threshold. The prompt later shrank by more than 30% in only 1 of them.
   - Per agent, the prompt shrank in 0 of 16 locator contexts that went over, 1 of 15 fixer contexts and 0 of 10 verifier contexts.
   - Seven v4 tasks ended in `litellm.ContextWindowExceededError`, all near 28.5k prompt tokens.
   - Cause on the pod: `pod/run_eval.sh` calls the swegemma CLI, and `swegemma/config.py:117` defaults `events_compaction_config=None`. Only `harness/agent_runner.py:410` would pass it on, so pod runs had no compaction at all.
   - The official notebook, and our `scripts/make_eval_kernel.py`, pass `EventsCompactionConfig(compaction_interval=15, overlap_size=2, token_threshold=14336, event_retention_size=5)`. A Kaggle thread quotes the README as saying `metric/scoring.py` uses `token_threshold=32768`, which equals `max_model_len`, so compaction could never fire before overflow.
   - Even when compaction is configured, ADK 1.36.1 never compacts past a function call that has no response (`apps/compaction.py`, `_truncate_events_before_pending_function_call`). This is the same bug class as adk-python #7236.
   - An `agent_tool` sub-agent runs in a fresh `Runner` with no `app`, so it has no compaction config at all (`tools/agent_tool.py:241`).

   Fix: budget context ourselves. Keep command output bounded (head/tail/sed ranges, `-q` pytest), start each stage in a fresh context with a short handoff, and cap calls per stage. Treat the harness compaction as absent.

3. **The scorer runs the June chat template; the pod runs the July one (MEASURED).**
   - The scorer mounts Kaggle model `google/gemma-4/Other/gemma-4-31b-it-qat-w4a16-ct/2` (`ref/getting_started/kernel-metadata.json`). Its `chat_template.jinja` is 16,934 bytes, dated 2026-06-05, sha256 `94899c0f…`.
   - `pod/bootstrap.sh` downloads HF `google/gemma-4-31B-it-qat-w4a16-ct` at `main`. Its template is 18,683 bytes: the "canonical" template of 2026-07-15, whose header says "Fixed tool-calling loops, turn closures, and thinking content-ordering".
   - I rendered both templates on agent-shaped histories. When an assistant message carries text and a tool call, the old template emits a stray `<turn|>` inside the model turn: 3 opens against 4 closes, where the new template gives 3 and 3.
   - That trigger is rare in our traces (4 of 3,915 tool-call steps in v4 carry text). So the measured impact is small, but pod numbers were produced under a template the scorer does not use.

   Fix: copy the Kaggle v2 `chat_template.jinja` and `tokenizer_config.json` into `/root/models/g4` in `pod/bootstrap.sh`, and keep prompts that make the model emit tool calls with no prose.

4. **The hidden test set does not come from Reddit, and there is no evidence that it does (MEASURED from host text and public tasks).**
   - The host data page says the test set was "curated under a similar pipeline" and "curated from a set of private repositories". The pipeline is commit and PR mining, then issue linking, then filtering, then fail-to-pass and pass-to-pass checks, then a frontier-model feasibility check.
   - All 74 of our valid public tasks have `instance_id` equal to an upstream **PR** number (74 of 74 via the GitHub API). In all 74, the first line of the problem statement equals the PR title.
   - None of the 74 statements mentions Reddit. The Kaggle forum and the r/LocalLLaMA competition thread contain nothing that links tasks to Reddit.
   - On 2026-09-27 the host said the test tasks got "much more extensive reviewing and editing" than the training tasks, and that "impossible" tasks were screened out. See section 1.

5. **Temperature and thinking settings change the loop and overflow mix (REPORTED, rival's controlled runs).** A rival entry (happyc0der) found:
   - Temperature 0.2 gave verbatim retry loops: 13.5 identical repeats per task. At 0.7 that fell to 5.1, but more tasks then overflowed the context.
   - Thinking with `include_thoughts: true` removed loops (1.8 repeats per task) but traded them for overflow, because thoughts are re-sent as history.
   - Their best setting was thinking on, `include_thoughts: false`, and a small output cap.

   We already run temperature 1.0 and `include_thoughts: false`. Our v4 exact-repeat rate is 35%, most of it the edit retries from finding 1.

6. **Patch hygiene costs points that are free to recover (MEASURED).**
   - 16 of 61 non-empty v4 patches include scratch files: `reproduce_issue.py`, `repro.py` and ten `test_dataclass_repr_false_N.py` files.
   - 6 to 11 patches per run touch `tests/`. Four rescored runs already failed with "Failed to apply test_patch".

   Fix: before submit, have a script revert every change under tests and delete untracked files outside the package.

---

## 1. Where the hidden test set comes from

**What the hosts say** (Kaggle data page, pulled with the competition PageService API on 2026-09-27, verbatim):
- "Submissions are evaluated against a **test set** curated under a similar pipeline, with identical graph generation methods, and verification standards."
- "Both the training set and test set were produced using an automated curation and two-phase verification harness:
  1. Commit & PR Mining: filtered repository histories for commits that jointly modify core functional logic (`.py`) and corresponding unit tests;
  2. Issue Linking & Prompt Extraction: matched each code change with its original problem description, issue tracker thread, or bug report;
  3. Filtering & De-noising: excluded mechanical refactors, documentation-only changes, large-scale automated changes, and ambiguous issues lacking reproducible acceptance criteria;
  4. Execution Verification: fail-to-pass and pass-to-pass; Near Completion with Frontier Models: for the test set, a larger frontier model must pass the case or get within a single test case of passing."
- "There are about 120 tasks in the test set, evenly divided between the public and private splits. The test set was curated from a set of private repositories."
- `instance_id`: "repository short name and issue or pull request number".

**The host's forum reply** (Ryan Holbrook, ADMIN, thread 743817 "Task Verification Question", 2026-09-27). This answered a report that fastapi_15661 cannot be solved without seeing the test imports:
> "We did much more extensive reviewing and editing of the test tasks than the training tasks. 'Impossible' tasks like you've described are one of the things we checked for. We also checked that a failing test case for the frontier model's patch was something it could have gotten correct with the information given."

**Public-leaderboard size**: forum thread 743506 derives exactly 58 public tasks from the rounding pattern of the scores (0.00, 0.01, 0.03, 0.05, 0.06, 0.08, 0.10, 0.12, 0.13). That fits "about 120, evenly split".

**What I checked myself**
- 74 of 74 public valid ids are PRs, not issues. For all 74, the first line of the statement is the PR title (`gh api repos/<repo>/issues/<n>` gives `pull_request != null`). Only 14 of 74 statements link an issue number. 0 of 74 mention Reddit.
- I searched r/LocalLLaMA, r/LLMDevs, r/ChatGPTCoding, r/MachineLearning and r/kaggle through Reddit RSS search, plus the 39 Kaggle forum topics. Nothing ties the tasks to Reddit.
- The r/LocalLLaMA thread "Gemma 4 Developer Agent Competition" (1wpqyaz, 41 comments) covers distillation, VRAM and the 31B-only rule. Nothing there is about task provenance.

**Verdict**: no evidence for the Reddit hypothesis. What the evidence shows is private repositories, mined PRs and their linked descriptions, and heavier human review of the test tasks.

**What this changes for us**
- Of our 39 never-solved public tasks, 15 are HIDDEN_SPEC (9) or UNDERSPECIFIED_ISSUE (6) (`eval/diagnosis.md`). The admin reply says the test set was filtered for exactly these. Levers aimed at guessing hidden API names are therefore worth less on the hidden set than on the public one.
- Levers that fix mechanics (edit parsing, context, loops, hygiene) and fix quality should carry over.
- The test repos are private, so the model cannot have memorised them, and nothing is gained by retrieving upstream PR text for them.
- "Similar pipeline, identical graph generation" means the code-graph tools behave the same on the hidden set. That includes the empty-graph-file issue in thread 742911, which is still open for the hidden set.

---

## 2. Pain-point catalogue

Format per item: **Problem**, **Where reported**, **Fix people used**, **Applies to us**.

### A. Tool-call format and parsing (vLLM `gemma4` parser, 0.19.1 on the scorer)

**A1. Round-bracket calls `call:name(...)` swallow the rest of the turn.**
- Where: vLLM #53642 (https://github.com/vllm-project/vllm/issues/53642). The fix, PR #53657, measured this bracket slip in 11 to 13% of tool calls across Gemma 4 quantizations.
- Fix: add an `OPEN_PAREN` transition and an escape from `TOOL_NAME` to `CONTENT` in the streaming FSM.
- Applies: **MEASURED, minor.** The scorer's 0.19.1 non-streaming regex is `<\|tool_call>call:([\w\-\.]+)\{(.*?)\}<tool_call\|>`, so a bracket call does not match. If no call in a response matches, the whole response comes back as text, and the harness replies with a "Please continue" nudge; after 3 consecutive nudges it ends the task. In our runs, leaked raw `<|tool_call>` text appeared in 6 of 205 text-only turns (v4), 2 (v6), 4 (v7) and 4 (v8). The forms seen were `call,edit_file{` (comma instead of colon), `call:read_file filepath="..." start_line=150` (no brace) and truncated edit_file calls.

**A2. Bare or malformed openers, `<|tool_call>:name{`, `<|tool_call>-name`, or no brace, are silently dropped.**
- Where: vLLM PR #53444 (https://github.com/vllm-project/vllm/pull/53444) and PR #54778 (https://github.com/vllm-project/vllm/pull/54778). Production impact was about 0.4% of tool-calling requests (386 lost turns in 21 days), "no tool call, no content, no error".
- Fix: widen the parser. Both fixes are in vLLM 0.27.1 and later, not in 0.19.1.
- Applies: we cannot change the scorer's vLLM. The workaround is on our side: short tool calls, and never write prose before a call.

**A3. String arguments with internal quotes get truncated (offline parser path).**
- Where: vLLM #39069 (https://github.com/vllm-project/vllm/issues/39069). The fallback regex `(\w+):\s*"([^"]*)"` stops at the first `"`. Fixed by #45553 and #51307.
- Applies: **MEASURED, not our path.** The API-server parser in 0.19.1 (`vllm/tool_parsers/gemma4_tool_parser.py`) uses `find(STRING_DELIM)`, not that regex. Our real failure is A5.

**A4. Parser shares state across concurrent requests (`<pad>` floods).**
- Where: vLLM #39392 (https://github.com/vllm-project/vllm/issues/39392). Failed 2 of 5 times concurrent, 0 of 5 sequential.
- Fix: serialize requests with a lock.
- Applies: the scorer runs tasks sequentially, so this matters only for our own concurrent pod evals (2 tasks per GPU). Also, #39392 is about streaming state, and LiteLLM calls vLLM non-streaming here.

**A5. The model writes JSON-style quoting or a wrong delimiter inside Gemma's `<|"|>` string format.**
- Where:
  - vLLM #39468 (https://github.com/vllm-project/vllm/issues/39468): `<|"|>` fragments inside argument values, vLLM 0.19.0, Gemma-4-31B-IT.
  - llama.cpp #21680 (https://github.com/ggml-org/llama.cpp/issues/21680) and #21384 (https://github.com/ggml-org/llama.cpp/issues/21384).
  - llama.cpp #25986 (https://github.com/ggml-org/llama.cpp/issues/25986): long multi-line code arguments are "intermittently unparseable" and "most attempts fail when editing files with substantial content".
- Fix people used: grammar-constrained decoding, or parsing the model's native text format directly. A DEV.to write-up (https://dev.to/kuroko1t/what-happens-when-local-llms-fail-at-tool-calling-testing-7-models-with-a-rust-coding-agent-cep) reports a backend rejecting native calls whose JSON contained quotes.
- Applies: **MEASURED, this is finding 1.** The multi-line-string edit_file call is exactly the fragile shape: 49 to 74% rejected. run_command, with one string argument, is almost never rejected.

**A6. Integer arguments arrive as strings (ADK 1.36.1 sends `any_of`/`INTEGER` schemas).**
- Where: rival notes (https://github.com/happyc0der/gemma-swe-agent, `docs/harness-fidelity.md`). On a 12B proxy with vLLM 0.30, 20 of 24 read_file range calls failed with `'>' not supported between 'int' and 'str'`. They later found that the real 31B on vLLM 0.19.1 returns integers.
- Also: the r/LocalLLaMA PSA on Gemma 4 12B templates (1txro73) says the original template "silently dropped" JSON-schema constraints such as `anyOf` and `default`.
- Applies: **MEASURED, not an issue for us.** 552 read_file range calls in v4; 3 had string-typed ranges. `allow_multiple` arrived as a string 0 times.

### B. Edit failures (escapes, whitespace, uniqueness)

**B1. Literal `\n` / `\"` in old_string, so "old_string not found".**
- Where:
  - Qwen3-Coder #531 (https://github.com/QwenLM/Qwen3-Coder/issues/531): files end up with literal `\n`, and repeated rewrites repeat the corruption. Unresolved.
  - qwen-code #797 (https://github.com/QwenLM/qwen-code/issues/797) and #1023 (https://github.com/QwenLM/qwen-code/issues/1023).
  - gufo PR #284 (https://github.com/gufo-org/gufo/pull/284): XML parameter whitespace was trimmed, and the fix accepts Python literals.
  - Rival notes: "rich_3454: 8 identical failed edit_file calls (anchor had backslash-escaped quotes not present in the file)".
- Fix people used: unescape and retry, a line-anchored edit, or telling the model not to escape inside strings.
- Applies: **MEASURED.** 351 of 528 parsed edit_file calls (v4) had escapes, and 96% of those failed. The harness's 3-tier matcher (exact, then whitespace-flexible, then regex-tokenized) never unescapes, and its fallback tiers almost never rescue a call: all 140 v4 successes used the `exact` strategy (v7: 130 of 131). Examples of the escapes in `new_string`: `\\"\\"\\"` docstrings and `\\n` line breaks, visible in `trace_rich_3063.json` and `trace_fastapi_15800.json`.

**B2. Whitespace or indentation mismatch loops the model.**
- Where:
  - bob #143 (https://github.com/tpsdev-ai/bob/issues/143): a local 27B spent 11 minutes and 14 failed edits on a 3-line change.
  - Aider "File editing problems" (https://aider.chat/docs/troubleshooting/edit-errors.html), Aider #3651 (https://github.com/Aider-AI/aider/issues/3651) and #770 (https://github.com/Aider-AI/aider/issues/770).
- Fixes people used:
  - bob: whitespace-normalized retry that reports which normalization matched; a line-range primitive `replace_lines(path, start, end, text)`; a loop breaker after 3 or 4 identical calls.
  - Aider: architect mode (one model proposes, an editor model writes the edit); check for CRLF, tabs and trailing whitespace; make the context big enough that the model actually sees the file.
- Applies: **MEASURED, smaller than B1.** The harness already has a whitespace-flexible tier. Plain old_strings failed as not-found only 19 times in v4, against 338 with escapes.

**B3. The str_replace editor beats generic edit or write tools for open models.**
- Where: Qwen3.6 #179 (https://github.com/QwenLM/Qwen3.6/issues/179). Reproducing Qwen3.6-27B on SWE-bench Pro: bash-only reached about 28%; with SWE-agent's `str_replace_editor` and reliable-test conditioning it reached 50.7% pass@1 and 70.7% pass@8. "qwen-code edit/write_file tools give zero lift".
- Applies: REPORTED. A structured replace is right, but our only native one (edit_file) is crippled by A5 and B1. A replace helper invoked through run_command keeps the structure and avoids the parser.

**B4. The model deletes whole-line text but leaves blank lines, or loses final newlines.**
- Where: qwen-code PR #12244 (https://github.com/QwenLM/qwen-code/pull/12244) and gufo PR #284.
- Applies: REPORTED. Our helper should preserve trailing newlines and whole-line semantics.

### C. Loops and repeated calls

**C1. Identical call repeated N times.**
- Where:
  - Gemma 3 4B loops (https://github.com/gamemaker1/gemma3-function-calling-benchmarks).
  - Llama 3.1 in LangGraph and Ollama (https://github.com/oracle/langchain-oracle/issues/49, https://github.com/openai/openai-agents-python/issues/1544).
  - command-code #936 (https://github.com/CommandCodeAI/command-code/issues/936): about 70 identical calls.
  - HN: "Gemma 4 12b calls same tool's repeatedly" (https://news.ycombinator.com/item?id=48426414); "I discarded using Gemma 4 because it got into weird loops when tool calling" (https://news.ycombinator.com/item?id=49328454).
  - r/LocalLLaMA 1segstx: "every single one always glitches the tool calling, infinite loop"; the fix there was a different quant and temperature 1.0 with top-k 40.
- Fixes people used:
  - OpenHands StuckDetector (https://docs.openhands.dev/sdk/guides/agent-stuck-detector): same action and observation 4 or more times; same action and error 3 or more; 3 or more monologue messages; ping-pong over 6 or more cycles; repeated context-window errors.
  - evalscope PR #1715 (https://github.com/modelscope/evalscope/pull/1715): `max_repeated_tool_calls` turns the repeat into an error that names what is being repeated.
  - SWE-smith (https://arxiv.org/abs/2504.21798): warns after a base command repeats 4 times (str_replace_editor view) or 6 times (any other).
  - Sotis (r/LLMDevs 1tvgsbf): entropy plus exact and semantic loop detection, workspace rollback, then restart with a distilled prompt.
- Applies: **MEASURED.** 35% of v4 tool calls (1,387 of 3,938) exactly repeat an earlier call in the same task; 31% in v7. Of those repeats, 58% are edit_file, 27% run_command and 14% read_file. We cannot change the harness loop, but our own helpers can detect a repeat, for example by hashing the last N commands in `$TMPDIR/swe/state` and returning a switch-mechanism message.

**C2. Deterministic sampling makes a failed call get retried verbatim.**
- Where: rival notes. At temperature 0.2, identical repeats per task were 13.5 and the longest run 13.2. At 0.7 these fell to 5.1 and 4.5, successful edits per task rose from 1.0 to 2.1, and the resolve rate stayed the same (6 of 33).
- Also: the official notebook ships temperature 0.2; Google's recommended sampling is T=1.0, top_p=0.95, top_k=64.
- Applies: we run T=1.0, top_k=64. REPORTED effect, but consistent with ours.

**C3. Degenerate "thought" loops on long agent prompts.**
- Where:
  - HF gemma-4-12B-it discussion 41 (https://huggingface.co/google/gemma-4-12B-it/discussions/41): 35 to 60% at 7.8k to 23k-token prompts, reproduced at F16. The 26B had 0 loops. Google's July template fix cut it from 44% to 35%.
  - google-deepmind/gemma #727 (https://github.com/google-deepmind/gemma/issues/727): infinite thinking, non-adherence above 10k-token system prompts, multi-turn erosion.
- Fixes: repeat-penalty 1.08 over the last 4,096 tokens (partial); the updated template; a thinking budget.
- Applies: REPORTED, for the 12B. Our model is the 31B, and our runs have thinking off. If we turn thinking on, `thinking_budget` is not forwarded (Kaggle thread, and adk_submission `resolvers/generation.py`), so only `max_output_tokens` bounds it.

### D. Context overflow

**D1. The 32k window fills after about 20 full-size tool outputs, and ADK does not compact inside a task.**
- Where: rival notes. 21 of 32 tasks ended in ContextWindowExceededError, "some after only 12-14 calls". Prompts grow about 630 tokens per call (p90 1,135). Context-budget prompt rules cut overflow from 12 to 2 of 33.
- Also: Kaggle thread 743456, which asks whether compaction can fire before the limit when the threshold is 32,768.
- Applies: **MEASURED, finding 2.** On the pod, compaction was never configured. On the scorer, compaction may run, but it truncates before any unanswered call and costs one extra 31B summarization call each time it fires.

**D2. Orphaned function calls silently disable compaction.**
- Where: adk-python #7236 (https://github.com/google/adk-python/issues/7236) and #4740 (https://github.com/google/adk-python/issues/4740).
- Applies: **MEASURED, the same logic is in 1.36.1** (`_pending_function_call_ids` and `_truncate_events_before_pending_function_call`). Any function call with no response anywhere in the session is a permanent barrier for compaction. Whether the scorer produces such calls (from a parse error, or a turn that hits a budget) is unverified.

**D3. Small default contexts make edits impossible (Ollama 2k to 4k).**
- Where: Aider docs, the OpenHands local-LLMs guide (https://docs.openhands.dev/openhands/usage/llms/local-llms; at least 22k, 32k or more when possible), and OpenHands #9573.
- Applies: no; we have 32k.

**D4. Partial reads followed by hallucinated findings.**
- Where: r/LocalLLaMA "Gemma 4 26B fabricated an entire code audit" (1shdhui). The model read 547 of 2,045 lines in 7 overlapping windows, then reported "findings" for lines it never read. Qwen 3.5 read the whole file.
- Applies: REPORTED, for the 26B. It is relevant to our WRONG_SEMANTICS and "claims fixed" cases: the agent must print the lines it edits and verify them by running code.

### E. Thinking and reasoning tokens

**E1. Thinking re-sent as history fills the window.**
- Where: rival notes. With thinking on and `include_thoughts: true`, repeats fell to 1.8 per task, but 18 of 33 tasks overflowed. With `include_thoughts: false` the overflow "mostly disappears".
- Applies: we use `include_thoughts: false` (thinking fully off; the Kaggle thread confirms it maps to `enable_thinking: false`).

**E2. Thinking with no budget can burn the whole task.**
- Where:
  - Rival notes: Ollama ignored `max_tokens`, so one response ran 22,663 tokens with 667 tool calls.
  - r/LocalLLaMA 1sav9wg: Gemma 4 "will happily reason for 10+ minutes if you prompt it to"; the 31B thought for 594 s.
  - vLLM thinking-budget guide (https://yankee.dev/hands-on-vllm-thinking-token-budget).
- Applies: on the scorer, `thinking_budget` is dropped, so the only bound is `max_output_tokens` (our v4 uses 4,096 and v7 uses 2,048). Thinking-on variants should keep a small output cap and a "no long analysis" instruction. The harness's own MAX_TOKENS nudge text says the same.

**E3. Reasoning parser mis-separation leaks thoughts into content.**
- Where: vLLM #38855 (https://github.com/vllm-project/vllm/issues/38855), special tokens stripped before parsing; vLLM #39043 (https://github.com/vllm-project/vllm/issues/39043), reasoning tags leak with thinking on and tool calls leak with thinking off, on 0.19.1rc1.
- Applies: **MEASURED, rare with thinking off.** 205 text-only turns in v4. If thoughts leaked into content next to a tool call, the old template's turn-tag bug (finding 3) would trigger.

### F. Ignoring instructions, laziness, stopping early

**F1. The model stops without a tool call, or answers "please provide the problem".**
- Where:
  - Rival notes: after compaction the model asked for the task, because the prompt never restated it. The fix was to embed `{problem_description}` in the instruction.
  - r/LocalLLaMA "Gemma 4 - lazy model or am I crazy?" (1sjyzmi).
  - The 2026-07-15 Google template update ("fewer truncated/incomplete answers", https://alphasignal.ai/news/google-s-gemma-4-gets-70-faster-prefill-and-fixes-its-laziness-problem).
- Applies: the scorer has the pre-fix template (finding 3). The harness ends a task after 3 consecutive nudges. Keep the issue text restated in every sub-agent's instruction; our Sequential stages already get it.

**F2. System-prompt non-adherence at scale (above about 10k tokens) or late in long sessions.**
- Where: google-deepmind/gemma #727; r/LocalLLaMA "Gemma 4 is terrible with system prompts and tools" (1sh1bwv); ollama #15428 (empty responses on long system prompts, 26B MoE).
- Applies: our first-call prompt is about 3.9k to 6.1k tokens including tool declarations (`usage.prompt_tokens`, v4). Keep the prompt short and put the rules the model must obey in tool error messages, where they arrive at the moment they matter, rather than in the system prompt.

**F3. Schema discipline drifts after 20 to 50 calls.**
- Where: r/LocalLLaMA "North Mini Code scores 67% on SWE bench. Does it survive an actual agent loop?" (1udzj02).
- Fix people used: validate every call against the schema and fail loudly.
- Applies: a fresh context per stage (Sequential locator, fixer, verifier) limits drift.

### G. Test running and verification

**G1. The agent never runs tests.**
- Applies: **MEASURED** (`eval/diagnosis.md`): 78 of the 155 failing never-solved runs have no pytest call at all.
- Fixes: Qwen3.6 #179 ("reliable-test conditioning"); SWE-Doctor (https://arxiv.org/abs/2607.00990), where reproduction-test diagnosis adds 8.0 points; Agentless reproduction tests (https://arxiv.org/abs/2407.01489); SWT-Bench (https://arxiv.org/abs/2406.12952).
- For us: a gate script that runs the repo's nearest test module and the reproduction before submit_patch (our v9 `gate.py` arm).

**G2. Tests or reproductions hang (an infinite-loop bug makes the repro itself hang).**
- Where: agent-mcp-tester #37 (https://github.com/Seretos/agent-mcp-tester/issues/37): no per-test timeout, the whole run hangs. prime-agent #2290 (https://github.com/PrimeIntellect-ai/prime-agent/issues/2290): no execute timeout.
- Fix: an outer wall-clock `timeout`; pytest-timeout alone cannot interrupt interpreter finalization.
- Applies: **MEASURED**: 3 never-solved tasks are HANG_INFINITE_LOOP, and 9 runs hit a verification hang. Wrap every repro and test in `timeout 60` inside our helper. Our `timeout_seconds: 180` is the harness per-command cap, and it also bounds Phase 2 verification (rival notes: verify_task uses `command_timeout_seconds`, so keep it at 180 s or more).

**G3. Environment differences make gold fail locally.**
- Applies: **MEASURED** (`eval/diagnosis.md`): the pod lacked python-multipart and had a mismatched pygments. Now pinned. The rival also found `requests` connect-timeout tests fail under `network_mode=none`.

### H. Patch hygiene

**H1. Scratch files inside the patch.**
- Where: harness README gotcha 3, and rival notes (2 to 9 of 10 to 17 patches per run). Cause: `write_file("/tmp/x")` resolves to `/workspace/tmp/x`.
- Applies: **MEASURED**: 16 of 61 non-empty v4 patches.

**H2. Edits to tests, conftest.py or pytest.ini break test_patch application.**
- Where: harness README gotcha 2; the token-saver PR (https://github.com/elyeshkiri/token-saver/pull/39), which strips agent hunks on files the hidden test patch touches; ImpossibleBench (https://arxiv.org/abs/2510.20270).
- Applies: **MEASURED**: 6 to 11 patches per run touch `tests/`, and 4 rescored runs failed "Failed to apply test_patch". Revert those files automatically before submit (the v10 plan).

### I. Patch selection

**I1. One sample is noisy, and selection needs a verifier.**
- Where:
  - Agentless (https://arxiv.org/abs/2407.01489): normalize the candidates, then take the majority vote, with reproduction tests to break ties.
  - R2E-Gym (https://arxiv.org/abs/2504.07164): a hybrid of an execution-based verifier (generated tests plus a regression filter) and an execution-free one reaches 51%, 7 to 8 points over either alone.
  - SWE-Gym verifiers (https://nlp.cs.berkeley.edu/pubs/Pan-Wang-Neubig-Jaitly-Ji-Suhr-Zhang_2025_SWEGym_paper.pdf).
  - Survey of SWE-bench submitters (https://arxiv.org/abs/2506.17208): open systems reach 22 to 32% "only when rigorous filtering and majority-vote ranking are employed".
- Applies: **MEASURED earlier** (memory, 09-27). Jev as judge: AUROC 0.742, but 0.61 within a task. Shortest patch picked 11 of 14 and consensus 6 of 14. Under a 12 h sequential budget with about 5 min per task, best-of-N is costly. A cheap proxy that stays in budget: 2 candidates only when the first fails the gate.

**I2. Fail fast and restart.**
- Where: FailFast/RestartSmart (https://arxiv.org/abs/2608.03222). A 0.6B monitor spots failing prefixes, then the agent restarts from a fresh context, keeping the repo diff for inspection. Qwen3.6-27B went from 66.6% to 71.8%, with 14.6 to 20.4% fewer tokens.
- Applies: REPORTED. Our Sequential stages can run the same pattern without a monitor: if the fixer fails the gate, a second fixer starts in a fresh context with only the diff and the failure.

### J. Time limits and budget

**J1. Per-task caps against the 12 h sequential cap.**
- Where: rival notes. 5.5 min per task with about 0.5 min or more of overhead went over 12 h ("Notebook Exceeded Allowed Compute"). 3.5 min scored 0.06 in about 7.5 h. A rival's 5-min cap once scored 0.00 (memory).
- Also: Kaggle threads 743162, 743365 and 743663.
- Applies: our v4 bundle is 5 min, 70 calls and 150 turns, and scored 0.12, so it fits. REPORTED: the overhead per task on the scorer is at least 0.5 min.

**J2. Faster decoding matters more than cleverness on slow hardware.**
- Where: rival notes. On T4 at about 12 tokens/s, a 4.5-min task buys about 12 tool calls. On L4 with TP4 we measured about 2.2 s per call.
- Applies: every call we save by fixing edit parsing (810 repeated edit calls in v4) goes back to exploration and verification.

### K. Chat template

**K1. The June template has tool-calling bugs: turn-tag imbalance, thinking dropped, null rendered as nothing, no multimodal aliases.**
- Where:
  - HF gemma-4-31B-it discussion 118 (https://huggingface.co/google/gemma-4-31B-it/discussions/118), merged 07-15.
  - Diff analysis (https://note.com/unco3/n/ne5d382e3287b).
  - r/LocalLLaMA "Google is updating Gemma 4's chat templates, bringing major fixes to tool calling and reducing laziness" (1uxfu4k): "if Gemma 4 refuses to tool call properly it is definitely a template problem".
  - r/LocalLLaMA PSA 1txro73 ("you need a special chat template").
  - Community template (https://gist.github.com/jscott3201/ad69c4ffbd79f18b11a0f6a94c94fadf): null as JSON, thinking on, reject string arguments, preserve reasoning, balanced turn tags.
  - HN: "Gemma4 seriously fails at toolcalls... messed up after 2-3 turns" (April, https://news.ycombinator.com/item?id=47961353); "gemma4 has a specific problem with toolcalls that affects most runtimes" (May, https://news.ycombinator.com/item?id=48027533).
  - SWE-rebench update (r/LocalLLaMA 1uknx14, 2026-07-01, before the template fix): Gemma 4 31B scored 16.5%, against Qwen3.6-27B at 36.5%. A commenter attributes part of the gap to "Gemma 4's chat template is currently quite broken for a test like this" and links discussion 118.
  - r/LocalLLaMA 1sd0be8 and 1sh1bwv: llama.cpp ships an "interleaved" Gemma 4 template that keeps the last reasoning before a tool call, because "the original templates strip this reasoning, contradicting the guide" (https://ai.google.dev/gemma/docs/core/prompt-formatting-gemma4#managing-thought-context). Other common advice there: update the runtime and re-download early quants.
- Applies: **MEASURED, finding 3.** The scorer has the June template, and a submission cannot override it: VllmConfig is fixed in the scoring notebook.
  - The string-arguments issue (P3 in the gist) does not apply, because vLLM 0.19.1's `_postprocess_messages` turns argument JSON strings into dicts before rendering.
  - ADK #5650 (https://github.com/google/adk-python/issues/5650), role `tool` against `tool_responses`, applies to Ollama. It does not apply to vLLM with this template: my render shows role-tool messages rendered as `<|tool_response>` blocks.

**K2. Alphabetical parameter order (`dictsort`) in the tool declarations and in the call history.**
- Where: found here, from the template source (`format_parameters`, `properties | dictsort`).
- Applies: **MEASURED, finding 1.** The model writes new_string before old_string in 1,029 of 1,030 v4 calls. Our own helper takes one command string, so order stops mattering. If we ever add a native-style helper, give its arguments names whose alphabetical order matches the logical order, for example `a_path, b_find, c_replace`.

### L. Tool design and tool count

**L1. Too many tools degrade selection; a code sandbox beats many small tools.**
- Where:
  - r/LocalLLaMA "Local models handle tools way better when you give them a code sandbox instead of individual tools" (1oxb9zp).
  - r/LocalLLaMA "I was backend lead at Manus... I stopped using function calling entirely" (1rrisqn).
  - Goose #6883 (https://github.com/block/goose/issues/6883): Qwen3-coder switches to XML tool calls above about 5 tools.
  - Tool-count studies (https://tianpan.co/blog/2026/04/13/tool-explosion-problem-agent-tool-selection-at-scale).
  - mini-swe-agent's bash-only design (the harness behind Gemma 4 31B's reported 53.92% on SWE-bench Verified, https://www.vals.ai/models/google_gemma-4-31b-it; settings not published).
  - r/LocalLLaMA "I built a coding agent that gets 87% on benchmarks with a 4B parameter model" (SmallCode, 1tgecrq). Its tricks: "compound tools" (find, read, edit and verify in one call, because "small models lose coherence after 3+ sequential calls"), patch-first edits instead of whole-file rewrites (small models "truncate files at 60-120 lines"), and a compile or lint check after every write. Commenters point out that the 87% comes from a private, unverified stress test.
  - A comment in 1oxb9zp puts it this way: avoid "consecutive tool calls where the llm is required to copy and paste data around". That is exactly the shape of an old_string edit.
- Applies: MEASURED indirectly. run_command, one string argument, parses at about 100% while edit_file fails at 33 to 74%. Keep each stage's tool list short: run_command, read_file, submit_patch and run_skill_script, plus the graph tools only for the locator.

**L2. Malformed JSON from local models needs repair before execution.**
- Where: Goose #6688 (https://github.com/block/goose/issues/6688), JSON repair; HN "forge" proxy (https://news.ycombinator.com/item?id=48200153), which validates calls against the tool list and rescue-parses.
- Applies: we cannot put a proxy in front of the scorer's vLLM. The equivalent is to accept sloppy input in our own scripts: tolerate escaped text, accept `--start/--end`, and normalize paths such as the fullwidth-bracket path `「rich/ansi.py」` seen in v7.

### M. Other open-model harness notes (lower relevance)

- SWE-agent #1302 (https://github.com/SWE-agent/SWE-agent/issues/1302): a local model emits multi-line Python where one bash command is expected, and loops on BashIncorrectSyntaxError. Fix: better format error messages and templates. Relevant only to how our helper usage is documented in the prompt.
- OpenHands #10039 (https://github.com/OpenHands/OpenHands/issues/10039): Qwen3 Coder puts parameter tags inside values (`command=str_replace</parameter`) 10 to 20% of the time. Fixed in PR #10539. This is the XML equivalent of A5.
- vLLM #55495 and PR #55497 (https://github.com/vllm-project/vllm/issues/55495): the qwen3_xml parser truncates arguments and leaks tags. The same class of parser fragility on long string values.
- Devstral in OpenHands (HF discussion https://huggingface.co/mistralai/Devstral-Small-2505/discussions/10): self-limited to about 30-line reads, looping, never viewing whole files.
- SWE-agent history processors (https://swe-agent.com/latest/reference/history_processor_config/): collapse all but the last 5 observations to one line each. This is the standard context fix; we cannot configure it, but our helpers can print short outputs.

---

## 3. What to do next, ranked by measured size

1. **Edit through run_command plus our helper, and never through edit_file.** The helper should do an exact match, then an unescape of `\n \t \" \\ \uXXXX \x1b` and retry, then a whitespace-flexible match, then a line-range replace. After every edit it runs py_compile and prints a 3-line diff.
   - Evidence: 49 to 74% parse rejects, 96% escape failures, 58% of repeats. The v9 `replace.py` arm (`eo`) already tests this. Check that its prompt forbids edit_file outright, not just prefers the helper.
2. **Context guard.** Bounded outputs, per-stage call caps, and a fresh context per stage. Assume no compaction.
   - Evidence: 31 of 74 tasks over the threshold and 7 overflows in v4. None of those contexts shrank on the pod.
3. **Make pod evals faithful before trusting another race.**
   - Install the Kaggle v2 chat template on the pod.
   - Pass `EventsCompactionConfig(15, 2, 14336, 5)` through our `scripts/run_eval.py`, since the swegemma CLI leaves it at None.
   - Re-run v4 once under both changes to size the gap.
4. **Pre-submit hygiene script.** Revert changes under `tests/`, `conftest.py` and `pytest.ini`; delete untracked scratch files. Evidence: 16 of 61 patches with scratch files, 6 to 11 touching tests, 4 known "Failed to apply test_patch".
5. **Loop breaker inside the helpers.** Keep a state file of the last command hashes; on the second identical failure, return a message that names the alternative mechanism.
6. **Test gate before submit, with an outer `timeout`.** Evidence: 78 of 155 failing runs never ran pytest, and there are 9 verification hangs.
7. **Stop spending on HIDDEN_SPEC and UNDERSPECIFIED public tasks.** The host says the hidden set was screened for them.

---

## 4. How the numbers were computed (reproducible)

All from `eval/eval3/eval/runs/p_v{4,6,7,8}/traces/trace_*.json` (ATIF steps; `tool_calls[].function_name`, `arguments`, `extra.usage.prompt_tokens`, `observation.content`):
- **Parse rejects**: an edit_file call counts as rejected when its observation contains "mandatory input param".
- **Escapes**: regex `\\n|\\"|\\t|\\u[0-9a-fA-F]{4}|\\x1b` over old_string; success means `status == "ok"` in the observation JSON.
- **Argument order**: the index of `new_string` against `old_string` in the parsed argument dict. vLLM inserts keys in the order the model emits them.
- **Exact repeats**: the pair (function_name, sorted-JSON arguments) already seen earlier in the same task.
- **Compaction**: per author, the first call with `prompt_tokens > 14336`, then whether any later call by the same author has less than 70% of that.
- **Template**: Kaggle file list via `kaggle models instances versions files google/gemma-4/other/gemma-4-31b-it-qat-w4a16-ct/2`; HF history via `huggingface.co/api/models/google/gemma-4-31B-it-qat-w4a16-ct/commits/main`. Rendering used jinja2 on 3 synthetic histories (tool-only, text plus tool, nudge after text).
- **PR mapping**: `gh api repos/<repo>/issues/<n> --jq '[.pull_request!=null,.title]'` for all 74 valid ids.

Coverage gaps:
- Reddit's JSON API returned 403, so I searched and read threads through the RSS feeds (`/search.rss`, `<thread>/.rss`).
- Seven threads never loaded because of rate limits: 1sjyzmi "lazy model", 1v2rqbd "template witchcraft", 1va0cj4 "orchestration techniques on small models", 1rrisqn "Manus", 1vvtu9z "fine-tuned Gemma 4 12B for tool calling", 1sxqa2c and 1sgl3qz. I cite them only by title, where search snippets gave the content.
- Hacker News was read through the Algolia API. The Kaggle forum was read through the competition's internal discussion API; all 39 topics are dumped in the session scratchpad as `kaggle_discussions.md`.

Caveats:
- These are pod runs, which differ from the scorer in template and compaction (finding 3, and finding 2 under "Cause on the pod"). Rates could shift on the scorer.
- The link between edit failures and unsolved tasks is an association, not a controlled result.
- The v9 race arms are the controlled test.

---

## 5. Where the list of 74 lives

- `data/kaggle_valid_ids.txt`: the 74 public tasks whose gold patch passes in the Kaggle environment (fastapi 31, rich 42, requests 1).
- `research/tasks/`: per-task research JSON for 67 of them, written by the parallel workflow. Missing: fastapi_15800, rich_3180, rich_3468, rich_3772, rich_3777, rich_3782, rich_3930.
- Every one of the 74 is an upstream merged PR, with the problem statement taken from the PR title and body. Public upstream solutions exist for all 74, and they are the gold `patch` field. The hidden tasks come from private repositories, so no such public solutions exist for them.
