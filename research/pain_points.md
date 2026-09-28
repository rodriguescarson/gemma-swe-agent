# Pain points for SWE agents on small/open models, and what fixed them

Written 2026-09-27, revised 2026-09-28 (second sweep: the seven Reddit threads that did not load the first time, new vLLM/opencode/ADK/mini-swe-agent/llama.cpp issues, the four forum threads that changed, rival repos as of 2026-09-27, and a full-population re-check of the hidden-set question over all 129 public tasks). Third sweep later on 2026-09-28: vLLM, ADK, Goose (now `aaif-goose/goose`), SWE-agent, mini-swe-agent, OpenHands, Aider and opencode issues filed since 09-12; the Gemma 4 31B Hugging Face discussions; r/LLMDevs, r/ChatGPTCoding and r/MachineLearning, which the first two sweeps barely covered; the Kaggle forum again (still 40 topics); a second, independent run of the 129-task provenance check, extended to linked issues; and five new trace or source measurements (section 0, finding 8). Scope: problems people report when building coding agents on Gemma 3/4, Qwen 2.5/3 Coder, Devstral and Llama, the fixes they used, and whether each one applies to our Kaggle harness (gemma-4-31b-it-qat-w4a16-ct, vLLM 0.19.1 `gemma4` parsers, google-adk 1.36.1, swegemma 0.2.7).

Every "applies to us" claim is marked either **MEASURED** (computed from our traces or code in this repo; the command shape is in section 4) or **REPORTED** (someone else said it and it was not checked here).

Our trace base: the four fair pod runs `eval/eval3/eval/runs/p_v4, p_v6, p_v7, p_v8` (74 tasks each, the Kaggle-valid set in `data/kaggle_valid_ids.txt`). The headline counts below were recomputed on 2026-09-28 and match the 09-27 numbers exactly.

---

## 0. The findings that matter most

1. **edit_file is broken at the tool-call parser, not just at string matching (MEASURED; now also confirmed by a vLLM maintainer on the same model and parser).** In v4, 502 of 1,030 edit_file calls (49%) came back "mandatory input parameters are not present: old_string". The rate was 70% in v6 (972/1,393), 33% in v7 (328/983) and 74% in v8 (987/1,328). run_command was rejected 1 time in 1,831 calls (v4) and 0 times in v7/v8; write_file 1 time in 109. The mechanism:
   - The Gemma 4 chat template sorts tool parameters alphabetically (`properties | dictsort`), so the model sees and writes `filepath, new_string, old_string`. In v4, 527 of the 528 parsed edit_file calls had new_string before old_string; the 502 rejected calls have no old_string key at all.
   - The model then closes new_string with a backtick (or nothing) instead of the `<|"|>` delimiter token. vLLM 0.19.1's `_parse_gemma4_args` (`vllm/tool_parsers/gemma4_tool_parser.py`, line 145: `end_pos = args_str.find(STRING_DELIM, i)`) takes the next `<|"|>` it finds, which is the one that opens old_string. So new_string swallows `` `,old_string: `` and the old code is parsed as garbage `key:value` pairs (the key scan on line 120 is `while args_str[i] != ":"`). Example from `p_v4/traces/trace_fastapi_13537.json`: new_string ends in `` field_info`,old_string: `` and one of the keys is `for field in body_fields`.
   - **Upstream corroboration (new):** vLLM #39072 (https://github.com/vllm-project/vllm/issues/39072, gemma-4-31B-IT, `--tool-call-parser gemma4`, Pi's `edit` tool) shows the identical symptom: `,path:` inside `oldText`, and the tool then rejects the call for a missing required property. The maintainer (bbrowning, 2026-04-09): "the only way I'm able to reproduce this is if the model forgets the closing `<|"|>` string delimiter token ... `oldText:<|"|>bar,path:<|"|>file.md<|"|>`". His fix, PR #39440 (https://github.com/vllm-project/vllm/pull/39440, "Fix Gemma4 parser delimiter over-consumption bug": accept a `<|"|>` as a closing delimiter only when it is followed by `,`, `}` or `]`), was closed unmerged on 2026-05-14 and superseded by the engine-based parser (#45588, June), which is not in 0.19.1 (released 2026-04-18). So the scorer runs the parser with the bug and no recovery.
   - Of the edit_file calls that did parse, 351 of 528 (v4) had literal `\n`, `\"`, `\uXXXX` or `\x1b` escapes in old_string. 338 of those (96%) failed with "old_string not found". Plain old_strings succeeded in 127 of 177 cases (72%). Same shape in every run: v6 95%/60%, v7 98%/53%, v8 95%/82%.
   - End to end, only 140 of 1,030 edit_file calls in v4 (13.6%) changed a file; v6 8.7%, v7 13.3%, v8 8.9%. Every success used the `exact` matcher (v7: 130 exact, 1 regex).
   - Edit retries are most of our "loops": 810 of the 1,387 exact-repeat tool calls in v4 were repeated edit_file calls.
   - Tasks with 3 or more parse or escape failures: 13 to 19 failed tasks per run, against 0 to 2 resolved tasks.

   Fix: stop sending code through edit_file. Edit through run_command, whose single string argument parses cleanly, driving our own helper. The helper should do an exact match, then an unescape-and-retry, then a line-range replace. Add a loop breaker that switches mechanism after 2 identical failures. Design rule that follows from the parser code: **one code-bearing string argument per call, and it must sort last alphabetically.** If the model drops the closing delimiter on the last argument, 0.19.1 falls into its "Unterminated string, take rest" branch (line 146-149) and the only damage is a trailing backtick, which a helper can strip. A dropped delimiter on any earlier argument destroys every argument after it.

2. **The harness's context compaction never shrank a prompt on the pod, and the pod runs it differently from the scorer (MEASURED).**
   - Fair v4 run: 31 of 74 tasks went over the 14,336-token compaction threshold. The prompt later shrank by more than 30% in only 1 of them.
   - Per agent, the prompt shrank in 0 of 16 locator contexts that went over, 1 of 15 fixer contexts and 0 of 10 verifier contexts.
   - Seven v4 tasks ended in `litellm.ContextWindowExceededError`, all near 28.5k prompt tokens.
   - Cause on the pod: `pod/run_eval.sh` calls the swegemma CLI, and `swegemma/config.py:117` defaults `events_compaction_config=None`. Only `harness/agent_runner.py:410` would pass it on, so pod runs had no compaction at all.
   - The official notebook, and our `scripts/make_eval_kernel.py`, pass `EventsCompactionConfig(compaction_interval=15, overlap_size=2, token_threshold=14336, event_retention_size=5)`. A Kaggle thread quotes the README as saying `metric/scoring.py` uses `token_threshold=32768`, which equals `max_model_len`, so compaction could never fire before overflow.
   - Even when compaction is configured, ADK 1.36.1 never compacts past a function call that has no response (`apps/compaction.py`, `_truncate_events_before_pending_function_call`). This is the same bug class as adk-python #7236 (still open 2026-09-22).
   - An `agent_tool` sub-agent runs in a fresh `Runner` with no `app`, so it has no compaction config at all (`tools/agent_tool.py:241`).

   Fix: budget context ourselves. Keep command output bounded (head/tail/sed ranges, `-q` pytest), start each stage in a fresh context with a short handoff, and cap calls per stage. Treat the harness compaction as absent.

3. **The scorer runs the June chat template; the pod runs the July one (MEASURED).**
   - The scorer mounts Kaggle model `google/gemma-4/Other/gemma-4-31b-it-qat-w4a16-ct/2` (`ref/getting_started/kernel-metadata.json`). Its `chat_template.jinja` is 16,934 bytes, dated 2026-06-05, sha256 `94899c0f…`.
   - `pod/bootstrap.sh` downloads HF `google/gemma-4-31B-it-qat-w4a16-ct` at `main`. Its template is 18,683 bytes: the "canonical" template of 2026-07-15, whose header says "Fixed tool-calling loops, turn closures, and thinking content-ordering".
   - Rendering both templates on agent-shaped histories: when an assistant message carries text and a tool call, the old template emits a stray `<turn|>` inside the model turn: 3 opens against 4 closes, where the new template gives 3 and 3.
   - That trigger is rare in our traces (4 of 3,915 tool-call steps in v4 carry text). So the measured impact is small, but pod numbers were produced under a template the scorer does not use.
   - The old template does handle `role: tool` messages natively (lines 217-275 render them as `<|tool_response>` blocks; render in scratchpad `tmpl/render_old_tool_only.txt`), so the ADK "tool_responses" role bugs in section F4 do not apply to us.

   Fix: copy the Kaggle v2 `chat_template.jinja` and `tokenizer_config.json` into `/root/models/g4` in `pod/bootstrap.sh`, and keep prompts that make the model emit tool calls with no prose.

4. **The hidden test set does not come from Reddit, and there is no evidence that it does (MEASURED from host text and all 129 public tasks).** All 129 public `instance_id`s are merged upstream PRs; the first line of every problem statement is the PR title (129/129); the PR body is reproduced verbatim in the statement (128/129, the 129th PR has an empty body); `created_at` equals the PR's `merged_at` to the second (129/129); 0 of 129 statements mention Reddit; `hints_text` is empty in all 129. The host says the test set was built with the same pipeline from private repositories. Section 1 has the details.

5. **Temperature and thinking settings change the loop and overflow mix (REPORTED, rival's controlled runs).** A rival entry (happyc0der) found:
   - Temperature 0.2 gave verbatim retry loops: 13.5 identical repeats per task. At 0.7 that fell to 5.1, but more tasks then overflowed the context.
   - Thinking with `include_thoughts: true` removed loops (1.8 repeats per task) but traded them for overflow, because thoughts are re-sent as history.
   - Their best setting was thinking on, `include_thoughts: false`, and a small output cap.

   We already run temperature 1.0 and `include_thoughts: false`. Our v4 exact-repeat rate is 35% (v6 46%, v7 31%, v8 41%), most of it the edit retries from finding 1.

6. **Patch hygiene costs points that are free to recover (MEASURED).**
   - 16 of 61 non-empty v4 patches include scratch files: `reproduce_issue.py`, `repro.py` and ten `test_dataclass_repr_false_N.py` files.
   - 6 to 11 patches per run touch `tests/`. Four rescored runs already failed with "Failed to apply test_patch".
   - The rival's notes add a detail we should use: "the official harness keeps the working-tree diff as the patch when submit_patch is never called, so unfinished edits still get verified on the scorer". Cleanup therefore has to happen before the time budget ends, not only inside a submit step.

   Fix: before submit, and on a timer before the per-task cap, have a script revert every change under tests and delete untracked files outside the package.

7. **What is new since 09-27, in one paragraph.** Nothing in the second sweep contradicts findings 1 to 6. The additions are: the vLLM maintainer's confirmation of the delimiter mechanism (finding 1); two further Gemma 4 emission variants that the 0.19.1 parser cannot read (`=` as the key separator and plain JSON quoting inside arrays or objects, vLLM #51284); opencode's experience that Gemma 4 31B repeats a hallucinated `oldString` 10+ times and that a line-number edit tool removes the problem (#21850), and that it passes an empty `oldString` to append and wipes the file (#23517); mini-swe-agent's three format-error bugs, which are a checklist for our own loop breaker (show the real error, keep the malformed output in history, count the failed turn against the budget); the ADK "tool_responses" role issues, which do not apply to vLLM with the scorer's template; and a Reddit thread on a long-running SWE-bench harness whose numbers drifted because of unpinned installs inside task images, which is the same class of problem as our pod-vs-scorer gap.

8. **What the third sweep (later on 09-28) added.** Again nothing contradicts findings 1 to 6, and the hidden-set verdict is unchanged (section 1 now also shows that none of the 40 linked issues' text reached a public statement). Two corrections to the morning text: vLLM #51307 is open, not a fix for #39069 (A3), and the harness shows only the first of mini-swe-agent's two format-error faults (C3). New measurements from our own traces and the installed packages:
   - **AgentTool returns `""` when the sub-agent ends on a tool call or tool response** (adk-python #7246; the same extraction is in 1.36.1, `agent_tool.py` lines 44-52 and 281-284). This matters only if we adopt the README's AgentTool analyzer pattern; such a stage must end with a text summary (L3).
   - **Empty patches are mostly overflow and timeout, but 3 to 7 per run are normal finishes with no change** (G4). A gate that refuses `submit_patch` without a non-test source change targets those.
   - **Patches touching an existing non-gold source file**: 8% of resolved against 21% of unresolved; **patches touching no gold file**: 4% against 29% (H3). The second number is a localization miss.
   - **Truncation at the output cap and parallel calls are not problems for us**: at most 9 capped responses per run, 0 to 18 multi-call steps per run, and no duplicate call inside one response (A9, A10, C1).
   - **The scorer's edit_file rewrites the whole file after a lossy UTF-8 decode** (the pattern of adk-python #7314), but 0 of 9,295 `.py` files in the 59 local snapshots are invalid UTF-8 (B7).
   New reports worth knowing: Pi #2865 shows the dropped delimiter on llama.cpp and the 26B too, so it is a model behaviour (A5); Rapid-MLX #1996 shows constrained decoding in the wrong surface format silently truncates code (A7); OpenHands SDK still ends a run on a prose turn and closed the fix "not planned" (C5); HF discussions on the 31B about thinking failing to start at 29k to 31k tokens and `<turn|>` leaks during long thoughts (E4), and about hallucinated tool calls with invented results when no tool schema is attached (F6).

---

## 1. Where the hidden test set comes from

**What the hosts say** (Kaggle data page, pulled with the competition PageService API on 2026-09-27, verbatim; re-read from the saved copy on 2026-09-28):
- "Submissions are evaluated against a **test set** curated under a similar pipeline, with identical graph generation methods, and verification standards."
- "Both the training set and test set were produced using an automated curation and two-phase verification harness:
  1. Commit & PR Mining: filtered repository histories for commits that jointly modify core functional logic (`.py`) and corresponding unit tests;
  2. Issue Linking & Prompt Extraction: matched each code change with its original problem description, issue tracker thread, or bug report;
  3. Filtering & De-noising: excluded mechanical refactors, documentation-only changes, large-scale automated changes, and ambiguous issues lacking reproducible acceptance criteria;
  4. Execution Verification: fail-to-pass and pass-to-pass; Near Completion with Frontier Models: for the test set, a larger frontier model must pass the case or get within a single test case of passing."
- "There are about 120 tasks in the test set, evenly divided between the public and private splits. The test set was curated from a set of private repositories."
- `instance_id`: "unique identifier for the benchmark task combining the repository short name and issue or pull request number (for example, `fastapi_11194` or `rich_3454`)".

**The host's forum reply** (Ryan Holbrook, ADMIN, thread 743817 "Task Verification Question", 2026-09-27). This answered a report that fastapi_15661 cannot be solved without seeing the test imports:
> "We did much more extensive reviewing and editing of the test tasks than the training tasks. 'Impossible' tasks like you've described are one of the things we checked for. We also checked that a failing test case for the frontier model's patch was something it could have gotten correct with the information given. Unfortunately, time and resource constraints meant that we weren't able to do the same kind of review for the training set."

**Public-leaderboard size**: forum thread 743506 derives exactly 58 public tasks from the rounding pattern of the scores (0.00, 0.01, 0.03, 0.05, 0.06, 0.08, 0.10, 0.12, 0.13). That fits "about 120, evenly split".

**What was checked here (full population, 2026-09-28)**
- `gh api repos/<repo>/pulls/<n>` for all 129 rows of `data/tasks.jsonl` (fastapi 67, rich 48, requests 13, httpx 1): 129 of 129 are pull requests, all merged.
- First line of `problem_statement` equals the PR title: 129 of 129.
- The first 200 characters of the PR body (whitespace-normalized) appear verbatim in the statement: 128 of 129. The exception is `requests_7502`, whose PR body is empty, so its statement is the title alone.
- `created_at` equals the PR `merged_at` timestamp to the second: 129 of 129. Task dates run 2023-07-29 to 2026-06-20.
- `hints_text` is empty in all 129 rows.
- "reddit" appears in 0 of 129 statements.
- Kaggle forum: 40 topics as of 2026-09-28 (one new since 09-27, 743901 "L4 x4 sessions stuck in Queued"; comments added on 743683, 743007 and 742807 are about queue times, submission errors and distillation). Nothing links tasks to Reddit or to any public source.
- r/LocalLLaMA "Gemma 4 Developer Agent Competition" (1wpqyaz, re-read 2026-09-28) contains no comment mentioning the test set, hidden tasks, private repos or Reddit.
- Web search for "Gemma 4 Developer Agent" test set provenance returns only the data page text and entrants' repos repeating it.

**Third sweep (later on 2026-09-28): an independent re-run, plus a test for linked-issue text**
- Re-ran the PR comparison from scratch (new script, scratchpad `prcheck.py`) over all 129 rows: 129/129 merged PRs; first line equals the PR title 129/129; PR body (first 200 normalized characters) inside the statement 128/129, plus `requests_7502` with an empty body; `created_at` equals `merged_at` 129/129; `hints_text` empty 129/129; "reddit" 0/129. Same numbers as the morning run.
- `created_at` equals the PR's own `created_at` in **0 of 129**. The data page describes the field as "ISO-8601 timestamp indicating when the issue or pull request was created"; in the public data it is always the merge time.
- **Linked issues are not pulled in.** 40 of the 129 PR bodies close an issue (`fixes/closes/resolves #N` or a full issue URL; 17 rich statements carry a line like "Fixes https://github.com/Textualize/rich/issues/..."). For each of those 40, the linked issue's body (first 150 normalized characters, via `gh api repos/<repo>/issues/<N>`) appears in the statement **0 times**. After removing the PR title and body, **0 of 129** statements have more than 40 characters left over. So the statement is exactly "PR title, blank line, PR body". The pipeline's step 2 ("matched each code change with its original problem description, issue tracker thread, or bug report") contributed nothing beyond the PR itself on the public set, and the field meant for issue comments (`hints_text`, "optional issue comments or maintainer hints providing additional context (may be empty)") is empty everywhere.
- Other data-page lines that bear on the hidden set (from the saved PageService dump): `patch` is "excluded from the hidden `rerun/tasks.jsonl` test set" and `test_patch` is "kept in the private `secret/solution.parquet` archive during competition scoring".
- Kaggle forum again: still 40 topics (`kaggle competitions topics list gemma-4-developer-agent -p 1/-p 2`). Twelve threads re-read, including 743817, 743800, 743751, 743752 and 742911. The only hidden-set mentions are the ones already quoted: the host's reply in 743817, and 742911 asking whether the hidden set shares the empty graph files ("still a question for the hosts").
- Other sources checked for any link between the tasks and Reddit or public issue threads, with none found: Reddit RSS searches (r/LocalLLaMA "kaggle gemma" 0 hits in the past month; "gemma 4 agent" 25 hits, the only competition thread being 1wpqyaz); Hacker News Algolia since 2026-09-10; the five entrant repos that web search now returns (rishaviitd, Rudrapratapsinh-Chauhan1507, biswalprince, ennydev-2026, happyc0der; `dp-web4/SWE-SAGE` from the search results returns 404). rishaviitd's `context/data.md` and `context/harness.md` restate the data page.

**Verdict**: no evidence for the Reddit hypothesis. What the evidence shows is: public tasks are merged PRs whose title and body become the problem statement and whose merge time becomes `created_at`; the hosts say the hidden tasks were built the same way from private repositories, with heavier human review. Nothing in the public statements is issue-thread text (the `hints_text` field the pipeline reserves for it is empty everywhere, and none of the 40 linked issues' text made it into a statement). The third sweep found nothing that changes this verdict.

**What this changes for us**
- Of our 39 never-solved public tasks, 15 are HIDDEN_SPEC (9) or UNDERSPECIFIED_ISSUE (6) (`eval/diagnosis.md`). The admin reply says the test set was filtered for exactly these. Levers aimed at guessing hidden API names are therefore worth less on the hidden set than on the public one.
- Levers that fix mechanics (edit parsing, context, loops, hygiene) and fix quality should carry over.
- The test repos are private, so the model cannot have memorised them, and nothing is gained by retrieving upstream PR text for them.
- Hidden problem statements are PR descriptions, not bug reports. A PR description tends to say what changed and why, sometimes names the function, and rarely gives a reproduction. Prompts should ask the model to derive the reproduction from the description plus the code, and not wait for a traceback.
- "Similar pipeline, identical graph generation" means the code-graph tools behave the same on the hidden set. That includes the empty-graph-file issue in thread 742911, which is still open for the hidden set.

---

## 2. Pain-point catalogue

Format per item: **Problem**, **Where reported**, **Fix people used**, **Applies to us**.

### A. Tool-call format and parsing (vLLM `gemma4` parser, 0.19.1 on the scorer)

**A1. Round-bracket calls `call:name(...)` swallow the rest of the turn.**
- Where: vLLM #53642 (https://github.com/vllm-project/vllm/issues/53642). The fix, PR #53657, measured this bracket slip in 11 to 13% of tool calls across Gemma 4 quantizations.
- Fix: add an `OPEN_PAREN` transition and an escape from `TOOL_NAME` to `CONTENT` in the streaming FSM.
- Applies: **MEASURED, minor.** The scorer's 0.19.1 non-streaming regex is `<\|tool_call>call:([\w\-\.]+)\{(.*?)\}<tool_call\|>`, so a bracket call does not match. If no call in a response matches, `extract_tool_calls` returns the whole response as content (`gemma4_tool_parser.py` lines 419-422), and the harness replies with a "Please continue" nudge; after 3 consecutive nudges it ends the task. In our runs, leaked raw `<|tool_call>` text appeared in 6 of 205 text-only turns (v4), 2 (v6), 4 (v7) and 4 (v8). The forms seen were `call,edit_file{` (comma instead of colon), `call:read_file filepath="..." start_line=150` (no brace, `=` separators) and truncated edit_file calls.

**A2. Bare or malformed openers, `<|tool_call>:name{`, `<|tool_call>-name`, or no brace, are silently dropped.**
- Where: vLLM #53431 (https://github.com/vllm-project/vllm/issues/53431, closed 2026-09-15), PR #53444 (https://github.com/vllm-project/vllm/pull/53444, merged) and PR #54778 (https://github.com/vllm-project/vllm/pull/54778, open). Production impact was about 0.4% of tool-calling requests (386 lost turns in 21 days), "no tool call, no content, no error".
- Fix: widen the parser. These fixes are in vLLM 0.27.1 and later, not in 0.19.1.
- Applies: we cannot change the scorer's vLLM. The workaround is on our side: short tool calls, and never write prose before a call.

**A3. String arguments with internal quotes get truncated (offline parser path).**
- Where: vLLM #39069 (https://github.com/vllm-project/vllm/issues/39069). The fallback regex `(\w+):\s*"([^"]*)"` stops at the first `"`. Fixed by PR #45553 (merged 2026-06-16). (Correction, third sweep: the 09-28 morning text also listed #51307 as a fix; #51307 is still open and targets the related container case in #51284, see A5.)
- Applies: **MEASURED, not our path.** The API-server parser in 0.19.1 uses `find(STRING_DELIM)`, not that regex. Our real failure is A5.

**A4. Parser shares state across concurrent requests (`<pad>` floods), and non-streaming calls can vanish under load.**
- Where: vLLM #39392 (https://github.com/vllm-project/vllm/issues/39392, still open). Failed 2 of 5 times concurrent, 0 of 5 sequential. vLLM #50889 (https://github.com/vllm-project/vllm/issues/50889, open): on `gemma-4-31B-it-qat-w4a16-ct`, non-streaming, `finish_reason="tool_calls"` with `tool_calls == []` and empty content, about 5 times in 2 days of agentic traffic; a retry usually succeeds.
- Fix: serialize requests with a lock; a client-side typed retry.
- Applies: the scorer runs tasks sequentially, so this matters only for our own concurrent pod evals (2 tasks per GPU). #39392 is streaming state; LiteLLM calls vLLM non-streaming here. #50889 is the shape the harness would see as an empty model turn followed by a nudge; it is rare and we cannot retry from inside the agent.

**A5. The model writes JSON-style quoting, a wrong delimiter, or no delimiter inside Gemma's `<|"|>` string format.**
- Where:
  - vLLM #39072 (https://github.com/vllm-project/vllm/issues/39072): gemma-4-31B-IT, Pi `edit` tool, `,path:` swallowed into `oldText`; the maintainer reproduced it only when the model forgets the closing delimiter. PR #39440 (unmerged) is the recovery.
  - vLLM #39468 (https://github.com/vllm-project/vllm/issues/39468): `<|"|>` fragments inside argument values, vLLM 0.19.0, Gemma-4-31B-IT.
  - vLLM #44715 (https://github.com/vllm-project/vllm/issues/44715, reproduces on 0.19.1): the model wraps a string-typed dict key in `<|"|>` and the key parser keeps the delimiter bytes inside the key. Closed as fixed in the engine parser.
  - vLLM #51284 (https://github.com/vllm-project/vllm/issues/51284, open) and PR #51307: for values inside arrays or objects the model "regularly falls back to writing plain JSON / Python source syntax" (`data_refs:["ds_..."]`, `opts:{"mode": "fast"}`), so the parsed string carries the quote characters, the lookup fails silently, and "the model cannot see the difference, so it retries the identical call". On longer calls it also switches to `=` as the key separator, and the `:` key scan then drops every remaining argument.
  - PR #48678 (https://github.com/vllm-project/vllm/pull/48678, closed) is worth reading for method: the author claimed `<|"|>` appears inside values for literal quotes, was challenged, captured the raw wire output through `/v1/completions` with `skip_special_tokens: false`, found 0 of 12 samples did that (triple-quoted Python docstrings render fine), and retracted. The real defect was the `=` form above.
  - llama.cpp #21680, #21384 and #25986 (https://github.com/ggml-org/llama.cpp/issues/25986): long multi-line code arguments "intermittently unparseable"; "most attempts fail when editing files with substantial content".
  - Pi #2865 (https://github.com/earendil-works/pi/issues/2865, April; third sweep): the Pi-side report of the same `edit` failure behind vLLM #39072 ("Validation failed for tool "edit": - path: must have required property 'path'"). A commenter (2026-04-08) sees the identical symptom with `unsloth/gemma-4-26B-A4B-it-GGUF:UD-Q4_K_XL` on llama.cpp. llama.cpp has its own parser, so a second runtime and a second model size failing the same way points at the model dropping the delimiter, not at one parser. Parser fixes can only recover from it; they cannot stop it.
- Fix people used: grammar-constrained decoding (llama.cpp; vLLM has none for Gemma 4 yet, see A7), or parsing the model's native text format directly. A DEV.to write-up (https://dev.to/kuroko1t/what-happens-when-local-llms-fail-at-tool-calling-testing-7-models-with-a-rust-coding-agent-cep) reports a backend rejecting native calls whose JSON contained quotes.
- Applies: **MEASURED, this is finding 1.** The multi-line-string edit_file call is exactly the fragile shape: 33 to 74% rejected. run_command, with one string argument, is almost never rejected. Our tools take no array or object arguments except `get_code_subgraph`'s list, which we do not use.

**A6. Integer arguments arrive as strings (ADK 1.36.1 sends `any_of`/`INTEGER` schemas).**
- Where: rival notes (https://github.com/happyc0der/gemma-swe-agent, `docs/harness-fidelity.md` and `experiments/2026-09-27-day4/notes.md`). On a 12B proxy with vLLM 0.30, 20 of 24 read_file range calls failed with `'>' not supported between 'int' and 'str'`. Their correction of 2026-09-26 14:10 UTC: on a scorer replica (vLLM 0.19.1, real 31B, ADK 1.36.1) the server returns `"start_line": 300` as a JSON integer; the strings were a vLLM 0.30 artifact.
- Also: the r/LocalLLaMA PSA on Gemma 4 12B templates (1txro73) says the original template "silently dropped" JSON-schema constraints such as `anyOf` and `default`.
- Applies: **MEASURED, not an issue for us.** 552 read_file range calls in v4; 3 had string-typed ranges. `allow_multiple` arrived as a string 0 times.

**A7. No constrained decoding for Gemma 4 tool calls; `tool_choice="required"` is not enforced.**
- Where: vLLM #53363 (https://github.com/vllm-project/vllm/issues/53363, open): prose-only response labelled `finish_reason="tool_calls"` with an empty list; the fix waits on XGrammar #684. llama.cpp #29089 (https://github.com/ggml-org/llama.cpp/issues/29089, 2026-09-18): even llama.cpp's grammar had a gap that let `]` close a list with an unclosed dict.
- Also (third sweep), a warning that constrained decoding is not free: Rapid-MLX #1996 (https://github.com/raullenchai/Rapid-MLX/issues/1996, closed 2026-08-17). Its default grammar forced Qwen3-Coder's free-form string arguments into a quoted JSON surface the model was not trained to emit. `write_file` content came back as `"import time"` (11 bytes) instead of a 710-byte file, and `Tokyo` came back as `Toyo`: "The truncation is the severe one and it is **silent** — `finish_reason` is `tool_calls`, the arguments are valid JSON, and the file the agent writes is simply cut off at the first newline." A grammar has to match the model's native wire format, or it corrupts code-bearing arguments in a new way.
- Applies: REPORTED. The scorer's ADK path uses `tool_choice="auto"`, so nothing constrains the call text. This is why the fix has to be on the tool-design side (one string argument) rather than the decoding side.

**A8. Thinking-on parser gaps (only if we turn thinking on).**
- Where: vLLM #54256 (https://github.com/vllm-project/vllm/issues/54256, open): Gemma 4 "frequently" goes from `<channel|>` straight into `call:func{...}` without re-emitting `<|tool_call>`; the parser stays in CONTENT and drops the call, returning `finish_reason="tool_calls"` with 0 calls. vLLM #57231 and #57232 (2026-09-16) are about the engine parser's synthetic `<|channel>` leaking into content when no reasoning parser is configured; not our version.
- Applies: REPORTED. Our runs have thinking off. A thinking-on arm needs its traces checked for empty tool-call turns after a thought block.

**A9. A tool call cut off by the output-token cap is dropped or executed truncated (third sweep).**
- Where: Goose #10950 (https://github.com/aaif-goose/goose/issues/10950, open, 2026-08-05): "Detect Google MAX_TOKENS responses and reject truncated tool calls ... Preserve partial responses and prevent truncated tool calls from executing." Goose #11838 (https://github.com/aaif-goose/goose/issues/11838, open): on Bedrock Converse, "max_tokens truncation is never reported and a cut-off tool call is dropped".
- Fix people used: read the provider's stop reason, keep the partial text, and never execute an incomplete call.
- Applies: **MEASURED, rare for us.** The harness already handles this case: an unclosed `<|tool_call>` gets the "reached the token limit before the tool call finished closing ... split the change into smaller incremental edits" nudge (`data/HARNESS_README.md` section 5.3). Model responses that reached the cap: 6 of 4,117 (v4, cap 4,096), 1 of 3,965 (v6, cap 2,048), 8 of 3,788 (v7, cap 2,048) and 9 of 4,533 (v8, cap 4,096). A parsed tool call survived in only 2 of those. Median completion is about 40 tokens and p99 is 612 to 773. Raw `<|tool_call>` text with no closing tag appeared 4 times in each of v4, v7 and v8. The cap is not what breaks edit_file; the delimiter is (finding 1).

**A10. Several tool calls in one response (parallel calls) break single-call agent loops (third sweep).**
- Where: AMD GAIA #944 (https://github.com/amd/gaia/issues/944, closed 2026-05-03): Gemma-4-E4B "routinely emit[s] multiple `tool_calls` in a single response"; the loop raised `NotImplementedError`, retried with an unrelated "malformed arguments" prompt, and gave up after 3 tries with zero tools run. GAIA #3596 (https://github.com/amd/gaia/issues/3596, closed 2026-09-10): the E4B once returned an unclosed fence (```` ```json} ````) instead of a call, and the loop returned it to the user as the answer; the fix routes a reply that is nothing but fenced tool-call JSON into the malformed-call retry.
- Applies: **MEASURED, not an issue.** ADK runs every call in a multi-call response. Multi-call responses are rare: 18 of 3,915 tool-call steps in v4, 15 of 3,761 in v6, 7 of 3,576 in v7 and 0 of 4,344 in v8. None of them held two identical calls, so there is no within-response repetition of the kind in C1's oh-my-pi report. The 31B does not produce GAIA's fenced-JSON form in our traces; its malformed calls leak as raw `<|tool_call>` text (A1).

### B. Edit failures (escapes, whitespace, uniqueness, hallucinated anchors)

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
- Applies: **MEASURED, smaller than B1.** The harness already has a whitespace-flexible tier. Plain old_strings failed as not-found only 19 times in v4 (50 in v4 counting all plain failures), against 338 with escapes.

**B3. Gemma 4 31B repeats a hallucinated `oldString` 10+ times; a line-number edit tool removes the failure class.**
- Where: opencode #21850 (https://github.com/anomalyco/opencode/issues/21850, gemma4-31b on local vLLM): the model reads the file, then writes an `oldString` that differs from what it just read (`<<<` for `<<`), gets "Could not find oldString", and "repeats the exact same incorrect edit call multiple times (10+ times)". A commenter (nateonguitar, 2026-06-11) replaced the edit tool with one that takes `startLine`/`endLine` plus `newContent` only: "Small/local models constantly get that snippet slightly wrong (whitespace, picking a snippet that isn't unique, typos when retranscribing context) and burn a retry every time. Addressing by line number instead ... avoids both problems, since the model never has to transcribe lines it isn't changing." It also halves generation, since only the new text is produced.
- Also: opencode #21034 (https://github.com/anomalyco/opencode/issues/21034): 26B/31B "not usable" in April on llama.cpp and vLLM 0.19.0 ("command repetition on tool success (model not seeing responses?)"); improved with llama.cpp v2.12 and a community chat template that handles empty content blocks; the official template update of late April folded those fixes in.
- Applies: **MEASURED indirectly.** Our repeated edit_file calls (810 of 1,387 repeats in v4) are this pattern with a parser failure in front of it. The line-range primitive in our helper is the same fix; the helper should print the numbered lines it will replace before it replaces them, so the model verifies the range rather than retranscribing code.

**B4. Empty `old_string` as "append" overwrites the file.**
- Where: opencode #23517 (https://github.com/anomalyco/opencode/issues/23517): Gemma 4 31B "gets confused on the Edit tool when it wants to append contents to the end of a file. It will use `oldString: ""`", the tool overwrote the file, and the model then tried to restore ~300 lines from memory. Seen 3 times in one session.
- Applies: REPORTED. The harness's edit_file rejects empty old_string ("mandatory input parameters"), which is safe. Our helper must refuse an empty anchor and offer an explicit `--append`/`--insert-after LINE` instead.

**B5. The str_replace editor beats generic edit or write tools for open models.**
- Where: Qwen3.6 #179 (https://github.com/QwenLM/Qwen3.6/issues/179). Reproducing Qwen3.6-27B on SWE-bench Pro: bash-only reached about 28%; with SWE-agent's `str_replace_editor` and reliable-test conditioning it reached 50.7% pass@1 and 70.7% pass@8. "qwen-code edit/write_file tools give zero lift".
- Applies: REPORTED. A structured replace is right, but our only native one (edit_file) is crippled by A5 and B1. A replace helper invoked through run_command keeps the structure and avoids the parser.

**B6. The model deletes whole-line text but leaves blank lines, or loses final newlines.**
- Where: qwen-code PR #12244 (https://github.com/QwenLM/qwen-code/pull/12244) and gufo PR #284.
- Applies: REPORTED. Our helper should preserve trailing newlines and whole-line semantics.

**B7. An edit tool that decodes with `errors='replace'` and writes the whole file back corrupts bytes it never touched (third sweep).**
- Where: adk-python #7314 (https://github.com/google/adk-python/issues/7314, open, 2026-09-27), on ADK 2.10's `EditFileTool`: every non-UTF-8 byte in the file becomes U+FFFD on disk while the tool reports `status: ok`. And "if `new_string` cannot be encoded, `open(path, 'w')` truncates the file before the encode raises, and the file is left empty."
- Applies: **MEASURED: the scorer's edit_file has the same pattern, and our repos do not trigger it.** swegemma 0.2.7 `tools/workspace.py` reads with `open(local_file, encoding='utf-8', errors='replace', newline='')` (line 212), then writes `res.new_content` back with `open(local_file, 'w', encoding='utf-8', newline='')` (line 229). In the 59 task snapshots stored locally (httpx, requests, rich; the fastapi snapshots are not on disk), 0 of 9,295 `.py` files are invalid UTF-8. The hidden repositories are private, so their encodings are unknown. It costs nothing to make our own edit helper read and write bytes and refuse a file that does not decode.

**B8. How far our edit success is from what other harnesses see (third sweep, context).**
- Where: r/ChatGPTCoding "GLM-4.6 and other models tested on diff edits - data from millions of Cline operations" (1nwj7zq, 2025-10-02, Cline's own telemetry, June to October 2025). The top models on their chart succeed on 91 to 96% of diff edits, and "most models would be far below this threshold". A commenter names the effect that makes low rates compound: "the compounding effect from gaslighting the model, i.e. having the model pattern matching and replicating the behavior of failing."
- Applies: context only. End to end, 8.7 to 13.6% of our edit_file calls changed a file (finding 1). The comment is one more argument for keeping failed attempts short in the history: a helper error should be one line naming the fix, not a dump of the failed arguments.

### C. Loops and repeated calls

**C1. Identical call repeated N times.**
- Where:
  - Gemma 3 4B loops (https://github.com/gamemaker1/gemma3-function-calling-benchmarks).
  - Llama 3.1 in LangGraph and Ollama (https://github.com/oracle/langchain-oracle/issues/49, https://github.com/openai/openai-agents-python/issues/1544).
  - command-code #936 (https://github.com/CommandCodeAI/command-code/issues/936): about 70 identical calls.
  - HN: "Gemma 4 12b calls same tool's repeatedly" (https://news.ycombinator.com/item?id=48426414); "I discarded using Gemma 4 because it got into weird loops when tool calling" (https://news.ycombinator.com/item?id=49328454, 2026-08-17); "Gemma 4 26BA4B would ... sometimes even get stuck in loops despite a repeat penalty. Do not use any newer updated templates or Unsloth fixes. Use older official templates" (https://news.ycombinator.com/item?id=49308155, 2026-08-15; a minority view, but note the scorer does use the older template).
  - r/LocalLLaMA 1segstx: "every single one always glitches the tool calling, infinite loop"; the fix there was a different quant and temperature 1.0 with top-k 40.
  - HF forum "Gemma 4 bug fixes and Research Request" (https://discuss.huggingface.co/t/gemma-4-bug-fixes-and-research-request/176979, June 2026): "under real load it malforms its own tool calls and then loops on the broken output", across vLLM, llama.cpp, Ollama, MLX, SGLang; the reply frames it as a protocol-boundary problem and lists "agent-loop safeguards (deduplication, retry caps, malformed-turn suppression)" as the last of seven layers.
  - opencode #21850 (above): 10+ identical edit calls from the 31B.
  - QwenPaw (CoPaw) #2947 (https://github.com/agentscope-ai/QwenPaw/issues/2947, April, third sweep): with `google/gemma-4-31b`, "the agent enters an infinite tool call loop ... continuously invokes tools like `execute_shell_command` and `glob_search` without completing". Closed with no fix posted.
  - HF gemma-4-31B-it discussion 139 "Same tool call infinite loop" (https://huggingface.co/google/gemma-4-31B-it/discussions/139, 2026-07-30, llama-server, Unsloth GGUF, 262k context): reproduced 3 times, then did not recur in a clear chat; the reporter blamed leftover content from earlier attempts in the prompt. Qwen 3.5-122B and Qwen 3.6-27B finished the same task in the same setup.
  - oh-my-pi #12784 (https://github.com/can1357/oh-my-pi/issues/12784, closed 2026-09-22, MiMo-V2.6 on vLLM; a different model, but the mechanism is general): the harness sent no sampling parameters, so vLLM used its request defaults (`temperature=1.0`, `top_p=1.0`, `repetition_penalty=1.0`), and the model repeated one call *inside a single response* until `max_tokens`: "single turns with 148 and 446 identical `grep` calls". Fix: `--generation-config auto` plus `--override-generation-config '{"repetition_penalty": 1.05}'` on the server. "Loop guards fire too late": a cross-turn detector cannot reclaim tokens burned inside one completion.
- Fixes people used:
  - OpenHands StuckDetector (https://docs.openhands.dev/sdk/guides/agent-stuck-detector): same action and observation 4 or more times; same action and error 3 or more; 3 or more monologue messages; ping-pong over 6 or more cycles; repeated context-window errors.
  - evalscope PR #1715 (https://github.com/modelscope/evalscope/pull/1715): `max_repeated_tool_calls` turns the repeat into an error that names what is being repeated.
  - SWE-smith (https://arxiv.org/abs/2504.21798): warns after a base command repeats 4 times (str_replace_editor view) or 6 times (any other).
  - Sotis (r/LLMDevs 1tvgsbf): entropy plus exact and semantic loop detection, workspace rollback, then restart with a distilled prompt.
  - forge proxy (https://github.com/antoinezambelli/forge, recommended in r/LocalLLaMA 1vvtu9z): "automatically nudges LLMs that have tool call failures".
- Applies: **MEASURED.** 35% of v4 tool calls (1,387 of 3,938) exactly repeat an earlier call in the same task; 46% in v6, 31% in v7, 41% in v8. Of the v4 repeats, 58% are edit_file, 27% run_command and 14% read_file. We cannot change the harness loop, but our own helpers can detect a repeat, for example by hashing the last N commands in `$TMPDIR/swe/state` and returning a switch-mechanism message.
  - Third sweep, **MEASURED**: the within-response form from oh-my-pi #12784 does not occur for us. Across the four runs, 40 responses carried more than one call and none held two identical calls; the largest held 5 calls. We do send sampling parameters (T=1.0, top_p 0.95, top_k 64). ADK forwards `presence_penalty` and `frequency_penalty` but has no field for `repetition_penalty` (`research/config_space.md`, row 1), so the MiMo fix is not available through a submission anyway.

**C2. Deterministic sampling makes a failed call get retried verbatim.**
- Where: rival notes. At temperature 0.2, identical repeats per task were 13.5 and the longest run 13.2. At 0.7 these fell to 5.1 and 4.5, successful edits per task rose from 1.0 to 2.1, and the resolve rate stayed the same (6 of 33).
- Also: the official notebook ships temperature 0.2; Google's recommended sampling is T=1.0, top_p=0.95, top_k=64. Another entrant (hemantadil, `SUBMISSION_SUMMARY.md`) ships temperature 0.1 "for syntax-accurate code edits", which is the setting the rival measured as loop-prone.
- Applies: we run T=1.0, top_k=64. REPORTED effect, but consistent with ours.

**C3. Format errors handled badly make loops worse (harness-side lessons).**
- Where: mini-swe-agent #894 (https://github.com/SWE-agent/mini-swe-agent/issues/894): a malformed tool call was answered with the "output truncated" template, so "the real error (e.g. `Unknown tool 'shell'.`) is never shown to the model" and it retried in the wrong direction until `max_consecutive_format_errors`. #897 (https://github.com/SWE-agent/mini-swe-agent/issues/897): the malformed assistant turn was dropped from history, so the model "never sees its own malformed output on the next attempt". #914 (https://github.com/SWE-agent/mini-swe-agent/issues/914): format-error turns were billed but not counted, so the agent ran past its budget.
- Applies: REPORTED, but the harness we run under has the first property. When the parser rejects an edit_file call, the model sees "mandatory input parameters are not present: old_string", which does not say what it did wrong. (Unlike #897, ADK does keep the garbage-keyed call in history, so the model can see its own broken output; it just is not told what is broken.) Our helper messages should state the mechanism ("your code argument was cut at a stray quote; use the line-range form") because that is the only channel we control. (Third-sweep correction: the 09-28 morning text said the harness had "the first two properties"; it has only the first.)

**C5. A prose turn with no tool call is treated as "done" and ends the run (third sweep).**
- Where: OpenHands software-agent-sdk #3992 (https://github.com/OpenHands/software-agent-sdk/issues/3992, closed 2026-07). An empty response gets a corrective nudge, but "a model that emits a normal planning/status message without a tool call ('Let me now check X before I proceed...') is silently treated as finished, even mid-task with zero deliverables. Models that are weaker or smaller ... hit this constantly." A controlled 2x2 (OpenHands SDK vs mini-swe-agent 2.4.4, qwen3.6-coder vs devstral) found that `tool_choice: "required"` made the same model finish normally. An opt-in `content_response_policy="nudge"` (PR #3997) was closed unmerged, and the issue was closed "not planned" on 2026-09-08, so OpenHands still ends the run on a prose turn.
- Applies: **MEASURED earlier, partly handled by the harness.** swegemma nudges on a text-only turn rather than finishing ("Please continue"), but ends the task after 3 consecutive nudges (`data/HARNESS_README.md` section 5.3), and `tool_choice="required"` is not enforced by the 0.19.1 `gemma4` parser anyway (A7). v4 has 205 text-only turns over 74 tasks. The prompt rule we already use, "every turn is a tool call; no prose before a call", is the only lever.

**C4. Degenerate "thought" loops on long agent prompts.**
- Where:
  - HF gemma-4-12B-it discussion 41 (https://huggingface.co/google/gemma-4-12B-it/discussions/41): 35 to 60% at 7.8k to 23k-token prompts, reproduced at F16. The 26B had 0 loops. Google's July template fix cut it from 44% to 35%.
  - google-deepmind/gemma #727 (https://github.com/google-deepmind/gemma/issues/727): infinite thinking, non-adherence above 10k-token system prompts, multi-turn erosion.
  - r/LocalLLaMA 1v2rqbd (2026-07): even with the new template, one user's overnight 26B job "barely follows instructions, and in the morning when the context reaches 160k, it got into a dead loop"; another: "losing coherence after 60k context pretty fast".
- Fixes: repeat-penalty 1.08 over the last 4,096 tokens (partial); the updated template; a thinking budget.
- Applies: REPORTED, for the 12B and 26B. Our model is the 31B at 32k, and our runs have thinking off. If we turn thinking on, `thinking_budget` is not forwarded (Kaggle thread, and adk_submission `resolvers/generation.py`), so only `max_output_tokens` bounds it.

### D. Context overflow

**D1. The 32k window fills after about 20 full-size tool outputs, and ADK does not compact inside a task.**
- Where: rival notes. 21 of 32 tasks ended in ContextWindowExceededError, "some after only 12-14 calls". Prompts grow about 630 tokens per call (p90 1,135). Context-budget prompt rules cut overflow from 12 to 2 of 33.
- Also: Kaggle thread 743456, which asks whether compaction can fire before the limit when the threshold is 32,768.
- Applies: **MEASURED, finding 2.** On the pod, compaction was never configured. On the scorer, compaction may run, but it truncates before any unanswered call and costs one extra 31B summarization call each time it fires.

**D2. Orphaned function calls silently disable compaction.**
- Where: adk-python #7236 (https://github.com/google/adk-python/issues/7236, open) and #4740 (https://github.com/google/adk-python/issues/4740). Related closed issues in the same area: #6397 (interval 0 compacts every invocation), #6273 (compaction summary switches language), #6691 (compaction breaks a session when not on the last agent), #7102 (resolved tool responses persisted per checkpoint, O(N²) growth).
- Applies: **MEASURED, the same logic is in 1.36.1** (`_pending_function_call_ids` and `_truncate_events_before_pending_function_call`). Any function call with no response anywhere in the session is a permanent barrier for compaction. Whether the scorer produces such calls (from a parse error, or a turn that hits a budget) is unverified.
- Related (third sweep): adk-python #7269 (https://github.com/google/adk-python/issues/7269, open, 2026-09-24): when two calls in a session share an id, `_rearrange_events_for_latest_function_response` attaches the newest response to the *oldest* call with that id and silently drops every event in between. It needs a provider that reuses call ids (the report names Gemini 3.x through LiteLLM). **Not our case:** vLLM 0.19.1's `gemma4` parser gives every call a fresh random id (`make_tool_call_id()`, `gemma4_tool_parser.py` line 608). Goose #12521 (https://github.com/aaif-goose/goose/issues/12521, open, 2026-09-25, Qwen 3.8 27B) is another compaction failure mode worth knowing: after compaction fired, new user messages were left out of the request and the model "re-answers the pre-compaction state"; the tell is identical `inputTokens` on consecutive turns. On our side, the same check (identical prompt_tokens on consecutive calls after a compaction) would show it if the scorer's compaction ever fires.

**D3. Small default contexts make edits impossible (Ollama 2k to 4k).**
- Where: Aider docs, the OpenHands local-LLMs guide (https://docs.openhands.dev/openhands/usage/llms/local-llms; at least 22k, 32k or more when possible), OpenHands #9573, opencode #21034 (a commenter's fix was `/set parameter num_ctx 65536` because opencode's context setting does not reach Ollama).
- Applies: no; we have 32k.

**D4. Partial reads followed by hallucinated findings.**
- Where: r/LocalLLaMA "Gemma 4 26B fabricated an entire code audit" (1shdhui). The model read 547 of 2,045 lines in 7 overlapping windows, then reported "findings" for lines it never read. Qwen 3.5 read the whole file.
- Applies: REPORTED, for the 26B. It is relevant to our WRONG_SEMANTICS and "claims fixed" cases: the agent must print the lines it edits and verify them by running code.

### E. Thinking and reasoning tokens

**E1. Thinking re-sent as history fills the window.**
- Where: rival notes. With thinking on and `include_thoughts: true`, repeats fell to 1.8 per task, but 18 of 33 tasks overflowed. With `include_thoughts: false` the overflow "mostly disappears". Their thinking-on preview at 5.5 min / 30 calls gave 7/33 against 5/33 thinking-off on the 12B proxy, inside their stated ±3 noise band.
- Applies: we use `include_thoughts: false` (thinking fully off; the Kaggle thread confirms it maps to `enable_thinking: false`).

**E2. Thinking with no budget can burn the whole task.**
- Where:
  - Rival notes: Ollama ignored `max_tokens`, so one response ran 22,663 tokens with 667 tool calls.
  - r/LocalLLaMA 1sav9wg: Gemma 4 "will happily reason for 10+ minutes if you prompt it to"; the 31B thought for 594 s.
  - HN 49729865 (2026-09-16): a Gemma 4 agent "wasted over half the token budget, each time, on internal debates over the current date" and refused to call its search tool because it did not believe the qualification rounds were over.
  - r/LocalLLaMA 1wopeqg (2026-09-24, MiMo 2.6 Pro): a 9-rule prompt block cut reasoning tokens 28% over 214 runs with a pre-set pass/fail gate; a critic's point stands for any model: write "do Y instead of X", not lists of prohibitions, because the model anchors on the forbidden words.
  - vLLM thinking-budget guide (https://yankee.dev/hands-on-vllm-thinking-token-budget).
- Applies: on the scorer, `thinking_budget` is dropped, so the only bound is `max_output_tokens` (our v4 uses 4,096 and v7 uses 2,048). Thinking-on variants should keep a small output cap and a "no long analysis" instruction. The harness's own MAX_TOKENS nudge text says the same. Put the current date and the fact that files may be newer than the model in the system prompt; it costs nothing and removes one known thought loop.

**E3. Reasoning parser mis-separation leaks thoughts into content.**
- Where: vLLM #38855 (https://github.com/vllm-project/vllm/issues/38855), special tokens stripped before parsing; vLLM #39043 (https://github.com/vllm-project/vllm/issues/39043), reasoning tags leak with thinking on and tool calls leak with thinking off, on 0.19.1rc1; r/LocalLLaMA 1v2rqbd: Gemma 4 in Hermes "leaking reasoning into messages, and destroying tool calls" while the same model works in Pi.
- Applies: **MEASURED, rare with thinking off.** 205 text-only turns in v4. If thoughts leaked into content next to a tool call, the old template's turn-tag bug (finding 3) would trigger.

**E4. Thinking changes behaviour near the end of the window, and long thoughts leak turn tags (third sweep; thinking-on arms only).**
- Where:
  - HF gemma-4-31B-it discussion 143 (https://huggingface.co/google/gemma-4-31B-it/discussions/143, closed 2026-08-16, llama.cpp; Q4_K_M, Q6, Q8 and the official QAT): at 29,000 to 31,000 tokens deep, with a 10k to 20k-token system prompt, the model "starts to fail at reasoning, outputting the final answer immediately instead", about 80% of the time once triggered. No cause was found; the reporter closed it.
  - HF discussion 138 (https://huggingface.co/google/gemma-4-31B-it/discussions/138, open): the 31B on vLLM 0.25.1 "occasionally emits `<turn|>`", and a client then reports no response. A reply (2026-08-18): "usually the parser missing the turn-end token when a thinking block runs long"; the advice was to upgrade vLLM. vLLM #49955 (https://github.com/vllm-project/vllm/issues/49955, open) tracks a trailing `<turn|>` in 0.26.0.
- Applies: REPORTED, and only if a stage turns thinking on. Our contexts do reach this depth: the seven v4 overflows all happened near 28.5k prompt tokens. Two config facts from our own reading make thinking easy to turn on by accident: the scorer's vLLM server default is `enable_thinking: True`, and a `thinking_config` that is missing or has an unknown level leaves it on (`research/config_space.md`, row 2). vLLM #52410 (https://github.com/vllm-project/vllm/issues/52410, closed 2026-08-18) is the same kind of default mismatch in a later parser.

### F. Ignoring instructions, laziness, stopping early

**F1. The model stops without a tool call, or answers "please provide the problem".**
- Where:
  - Rival notes: after compaction the model asked for the task, because the prompt never restated it. The fix was to embed `{problem_description}` in the instruction.
  - r/LocalLLaMA "Gemma 4 - lazy model or am I crazy?" (1sjyzmi, 26B): answers from memory instead of using tools, "a single web search" then stops; asks for confirmation before "three consecutive calls"; "it's also really sensitive to system prompts more than qwen 3.5 ... you have to guide it really strictly in the system prompt or it wont do what you want it to do and it does only that ... takes it a bit too literally". The fix reported by several commenters was the updated official template ("it fixed every issue for me, previously it was lazy"), with a caveat that some Unsloth re-uploads regressed.
  - The 2026-07-15 Google template update ("fewer truncated/incomplete answers", https://alphasignal.ai/news/google-s-gemma-4-gets-70-faster-prefill-and-fixes-its-laziness-problem).
- Applies: the scorer has the pre-fix template (finding 3). The harness ends a task after 3 consecutive nudges. Keep the issue text restated in every sub-agent's instruction; our Sequential stages already get it. Write the workflow as explicit ordered steps; the model follows them literally.

**F2. System-prompt non-adherence at scale (above about 10k tokens) or late in long sessions.**
- Where: google-deepmind/gemma #727; r/LocalLLaMA "Gemma 4 is terrible with system prompts and tools" (1sh1bwv); ollama #15428 (empty responses on long system prompts, 26B MoE).
- Applies: our first-call prompt is about 3.9k to 6.1k tokens including tool declarations (`usage.prompt_tokens`, v4). Keep the prompt short and put the rules the model must obey in tool error messages, where they arrive at the moment they matter, rather than in the system prompt.

**F3. Schema discipline drifts after 20 to 50 calls.**
- Where: r/LocalLLaMA "North Mini Code scores 67% on SWE bench. Does it survive an actual agent loop?" (1udzj02).
- Fix people used: validate every call against the schema and fail loudly.
- Applies: a fresh context per stage (Sequential locator, fixer, verifier) limits drift.

**F4. The model does not believe tool results (wrong tool role) and loops.**
- Where: adk-python #5650 (https://github.com/google/adk-python/issues/5650), #6334 (https://github.com/google/adk-python/issues/6334) and #6482 (https://github.com/google/adk-python/issues/6482); LiteLLM #28530. ADK's LiteLLM adapter sends tool results as `role="tool"`; Ollama's Gemma template expects `tool_responses`, so the model "hallucinates that the tool was never executed" and loops. ADK 1.36.1 switches to `tool_responses` only when the model name contains `gemma4` (`lite_llm.py:814`); later versions match `gemma-4` too, which then breaks LM Studio.
- Applies: **MEASURED, not an issue.** The scorer's model name is `gemma-4-31b-it-qat-w4a16-ct` (trace `model_name`), so ADK 1.36.1 sends `role="tool"`, and the scorer's June template renders `role: tool` messages as `<|tool_response>` blocks (`tmpl/render_old_tool_only.txt`). Nothing to change.

**F5. The model prefers its training-time beliefs to evidence in context.**
- Where: r/LocalLLaMA 1sjyzmi: "it will prefer its internal trained knowledge of the current date over a statement in the system prompt"; "questioning if a bug wasn't actually a system issue since source code files were timestamped 'in the future'"; a commenter cites a paper finding agents ignore tool output when they think they know the answer. HN 49729865 (above).
- Applies: REPORTED. Relevant to our "claims fixed without running" cases. The verifier stage must run the code and quote the output; and the prompt should state the date once.

**F6. Without a real tool schema, the model writes tool-call text and then believes the invented result (third sweep).**
- Where: HF gemma-4-31B-it discussion 136 (https://huggingface.co/google/gemma-4-31B-it/discussions/136, open, 2026-07-23, several hosted providers): "the model can emit tool-shaped text and later claim the unexecuted action succeeded: including invented command output." The reply of 2026-07-24 traced it to the client not attaching the `tools` array while the prompt told the model it was an execution agent, and gave two fixes: send the tools, and replace directives like "You MUST use tools" with plainer wording so a model without tools falls back to ordinary text.
- Applies: REPORTED; a design rule for multi-agent configs. Any LlmAgent in our tree that has `tools: []` (a planner or summarizer stage) but sees earlier tool calls in its history, or is told to act, is the shape that produces fake calls and fake results. Such a stage should get `include_contents: none` plus a handoff through `output_key`, and an instruction that asks for text only. The other half of F6 is F5: the verifier must quote real command output, never a remembered one.

### G. Test running and verification

**G1. The agent never runs tests.**
- Applies: **MEASURED** (`eval/diagnosis.md`): 78 of the 155 failing never-solved runs have no pytest call at all.
- Fixes: Qwen3.6 #179 ("reliable-test conditioning"); SWE-Doctor (https://arxiv.org/abs/2607.00990), where reproduction-test diagnosis adds 8.0 points; Agentless reproduction tests (https://arxiv.org/abs/2407.01489); SWT-Bench (https://arxiv.org/abs/2406.12952). Another entrant (hemantadil) went the other way with an "Immediate Edit Rule (max 1 reproduction step)" to stop diagnostic loops; unmeasured.
- For us: a gate script that runs the repo's nearest test module and the reproduction before submit_patch (our v9 `gate.py` arm).

**G2. Tests or reproductions hang (an infinite-loop bug makes the repro itself hang), and long commands derail the agent.**
- Where: agent-mcp-tester #37 (https://github.com/Seretos/agent-mcp-tester/issues/37): no per-test timeout, the whole run hangs. prime-agent #2290 (https://github.com/PrimeIntellect-ai/prime-agent/issues/2290): no execute timeout. r/LocalLLaMA 1sxqa2c: "a 'docker build' that takes longer than the default timeout ... sends them on unrelated follow-ups (as if the task ...)"; a timed-out command reads to a small model like a failure to fix.
- Fix: an outer wall-clock `timeout`; pytest-timeout alone cannot interrupt interpreter finalization; make the timeout message say "the command was cut off, not failed".
- Applies: **MEASURED**: 3 never-solved tasks are HANG_INFINITE_LOOP, and 9 runs hit a verification hang. Wrap every repro and test in `timeout 60` inside our helper. Our `timeout_seconds: 180` is the harness per-command cap, and it also bounds Phase 2 verification (rival notes: verify_task uses `command_timeout_seconds`, so keep it at 180 s or more; hemantadil ships 45 s, which risks failing a correct patch at verification).

**G3. Environment differences make gold fail locally, and long-running benchmarks drift.**
- Where: `eval/diagnosis.md` (pod lacked python-multipart, mismatched pygments; now pinned); the rival found `requests` connect-timeout tests fail under `network_mode=none`; r/LocalLLaMA 1woxw7s (2026-09-24, a 100-task SWE-bench-Verified django benchmark of local models): the author re-ran every result after finding the evaluation "was unfortunately not stable during the weeks/months of me using it"; a commenter: "unpinned installs inside the task env: the image builds fine in march, then pulls a newer pytest or setuptools in june ... freeze and hash the built images, and rerun one known-good task as a canary at the start of every batch". ns-0437/gemma4-agent-lab `docs/LESSONS.md`: "Runtime imported a host package instead of checkout"; "Negative grading sentinel mistaken for execution: reject test_exit_code = -1".
- Applies: **MEASURED in part.** Our pod differs from the scorer in template and compaction (finding 3 and 2); the canary idea is cheap: run one known-pass task at the start of every pod batch.
- Also (third sweep): mini-swe-agent #964 (https://github.com/SWE-agent/mini-swe-agent/issues/964, open, 2026-09-19), on harness-side false negatives: the model produced a correct patch but "shell startup noise on stdout", a crash with no resume, or tool-boundary mishandling made the harness record a failure. SWE-agent #1560 (https://github.com/SWE-agent/SWE-agent/issues/1560, open) asks for trace labels that separate interface (ACI) failures from model failures, because "resolved% moves more when the **interface** changes (edit format, history condensation, submit contract) than when the model alone changes". Finding 1 is a case of exactly that; our diagnosis labels should keep "parser rejected the call" apart from "model chose a wrong edit".

**G4. The agent reports success after changing nothing, or after changing only tests (third sweep).**
- Where: r/ChatGPTCoding "The agent exited cleanly with status 0, did nothing, and reported success" (1wnbpb4, 2026-09-22; frontier agents in an automated loop): "It exited with return code 0, touched zero files in the repository, and generated a detailed 40-line markdown summary describing all the functions it allegedly refactored." The fixes in the thread: hash or diff the working tree before and after and fail when nothing but reports changed; rerun the declared test command outside the agent in a clean shell; put test files on a deny list enforced per tool call; and (from a commenter) "a whitespace-only or comment-only edit still produces a non-empty diff. Worth grepping the diff for actual changed logic lines".
- Applies: the scorer already does the out-of-band part: Phase 2 applies the hidden tests in a clean container, so a claim never scores. What we lose is the task: a stage that "finishes" with no source change ends it with an empty or test-only patch. **MEASURED** from `task_results.jsonl` and `patches/`: v4 had 13 empty patches out of 74, of which 7 were context overflows, 2 session timeouts, and 4 ended normally with no error and no change (v6: 3 of 13, v7: 7 of 13, v8: 3 of 16 ended that way). Patches that touch no file outside tests: 2 (v4), 1, 1 and 2. Our pre-submit gate should refuse `submit_patch` when `git diff` has no changed non-blank, non-comment line outside `tests/`, and should say so in one line so the model goes back to editing.

### H. Patch hygiene

**H1. Scratch files inside the patch.**
- Where: harness README gotcha 3, and rival notes (2 to 9 of 10 to 17 patches per run; "in the day-3 thinking-on run 9/15 did, 3 of them containing nothing else"). Cause: `write_file("/tmp/x")` resolves to `/workspace/tmp/x`. ns-0437 LESSONS: "Scratch write tool rejected /tmp paths: use shell-created scratch files".
- Applies: **MEASURED**: 16 of 61 non-empty v4 patches.

**H2. Edits to tests, conftest.py or pytest.ini break test_patch application.**
- Where: harness README gotcha 2; the token-saver PR (https://github.com/elyeshkiri/token-saver/pull/39), which strips agent hunks on files the hidden test patch touches; ImpossibleBench (https://arxiv.org/abs/2510.20270). Aider #5681 (https://github.com/Aider-AI/aider/issues/5681, open, 2026-09-05) shows why `conftest.py` belongs on the list: Aider's own benchmark restores test files but not runner config, so "a four line `conftest.py` makes pytest exit 0 while every test fails". r/ChatGPTCoding 1wkvupp (2026-09-19, "Tired of coding agents modifying your unit tests just to fake a 'pass'?"): the agent "quietly comments out the assertion, slaps .skip, or loosens the validation boundary just to return an exit code 0". The fixes commenters gave are all outside the model: snapshot test hashes before the run and treat "tests changed" as a stop state; make the test directory read-only to the agent; and accept "here is the failing assertion and why it could not be satisfied" as a valid way to finish, so exit 0 is not the only way out.
- Applies: **MEASURED**: 6 to 11 patches per run touch `tests/`, and 4 rescored runs failed "Failed to apply test_patch". Revert those files automatically before submit (the v10 plan), and also on a timer, because the scorer keeps the working-tree diff when submit_patch is never called (rival notes, `experiments/2026-09-26-kaggle-31b-v10-v43/notes.md`).

**H3. Padded diffs: the fix plus reformatting, "while I was here" refactors and edits to unrelated files (third sweep).**
- Where: r/ChatGPTCoding "Coding agents pad their diffs to look thorough, and the padding is where the bugs hide" (1wdbmoy, 2026-09-11). The rule that did the work: "Before returning the diff, list every changed file and, for each hunk, the task requirement it serves. A hunk with no requirement gets reverted." The thread then improved it: ask for that list *before* writing (a plan the diff has to fit, rather than a story told afterwards), add "tests are read-only unless the task is the tests", and give the diff to a second, cold reviewer, because "the author cannot grade its own padding".
- Applies: **MEASURED, as an association.** Across the four runs, a patch modified an existing non-test source file that the gold patch does not touch in 7 of 93 resolved tasks (8%) against 31 of 148 unresolved (21%). A different signal is larger: 43 of the 148 unresolved patches (29%) touch none of the gold files, against 4 of 93 resolved; that is a localization miss, not padding. For the gate, a cheap version of the thread's rule is to print `git diff --stat` and ask the verifier to name, per file, the line of the problem statement it serves, before `submit_patch`.

### I. Patch selection

**I1. One sample is noisy, and selection needs a verifier.**
- Where:
  - Agentless (https://arxiv.org/abs/2407.01489): normalize the candidates, then take the majority vote, with reproduction tests to break ties.
  - R2E-Gym (https://arxiv.org/abs/2504.07164): a hybrid of an execution-based verifier (generated tests plus a regression filter) and an execution-free one reaches 51%, 7 to 8 points over either alone.
  - SWE-Gym verifiers (https://nlp.cs.berkeley.edu/pubs/Pan-Wang-Neubig-Jaitly-Ji-Suhr-Zhang_2025_SWEGym_paper.pdf).
  - Survey of SWE-bench submitters (https://arxiv.org/abs/2506.17208): open systems reach 22 to 32% "only when rigorous filtering and majority-vote ranking are employed".
  - Two open SWE-agent bugs (third sweep) that are a checklist for any selector we write: #1527 (https://github.com/SWE-agent/SWE-agent/issues/1527), the "shortest submission wins ties" rule keys on `api_calls or float("inf")`, so a candidate with 0 calls sorts last; and #1566 (https://github.com/SWE-agent/SWE-agent/issues/1566), `Reviewer.review()` averages only the judge samples that parsed, so failed judge calls shrink the denominator and one sample can stand in for all of them. Count failed judgements as failures, and write tie-breaks that treat 0 as a value.
- Applies: **MEASURED earlier** (memory, 09-27). Jev as judge: AUROC 0.742, but 0.61 within a task. Shortest patch picked 11 of 14 and consensus 6 of 14. Under a 12 h sequential budget with about 5 min per task, best-of-N is costly. A cheap proxy that stays in budget: 2 candidates only when the first fails the gate.

**I2. Fail fast and restart.**
- Where: FailFast/RestartSmart (https://arxiv.org/abs/2608.03222). A 0.6B monitor spots failing prefixes, then the agent restarts from a fresh context, keeping the repo diff for inspection. Qwen3.6-27B went from 66.6% to 71.8%, with 14.6 to 20.4% fewer tokens.
- Applies: REPORTED. Our Sequential stages can run the same pattern without a monitor: if the fixer fails the gate, a second fixer starts in a fresh context with only the diff and the failure.

### J. Time limits and budget

**J1. Per-task caps against the 12 h sequential cap.**
- Where: rival notes. 5.5 min per task with about 0.5 min or more of overhead went over 12 h ("Notebook Exceeded Allowed Compute"). 3.5 min scored 0.06 in about 7.5 h (their day 4, rank 284/543). Their real-31B runs on Kaggle T4x2 via llama.cpp: 3/33 at 5.5 min, 1/33 at 4.5 min ("32 of 33 tasks ended on the time budget ... on T4 (~12 tok/s) 4.5 min buys ~12 tool calls").
- Also: Kaggle threads 743162, 743365 and 743663.
- Applies: our v4 bundle is 5 min, 70 calls and 150 turns, and scored 0.12, so it fits. REPORTED: the overhead per task on the scorer is at least 0.5 min.

**J2. Faster decoding matters more than cleverness on slow hardware.**
- Where: rival notes (above). On L4 with TP4 we measured about 2.2 s per call.
- Applies: every call we save by fixing edit parsing (810 repeated edit calls in v4) goes back to exploration and verification.

**J3. Exploration spends the shared call budget before the dependent call happens (third sweep).**
- Where: r/LLMDevs "Our agent kept searching, but never opened the source" (1wo6fl5, 2026-09-23): the agent needed a search and then a read of the result, and "In four recorded runs, the second call never happened. Broad searches used up the available calls, sometimes on near-duplicates of the same question." Fixes from the thread: split the budget (for example at most 2 broad searches, then only reads until something is opened), and refuse to finish without the dependent artifact ("made the final answer require a fetched doc id").
- Applies: **MEASURED, a small minority of tasks.** Tasks with no edit_file or write_file call at all: 6 of 48 unresolved in v4 and 3 of 50 in v7, against 0 resolved. The median position of the first edit call is about half-way through the task's calls in both groups (v4: 0.57 of calls resolved, 0.49 unresolved), so exploration length does not separate wins from losses. The per-stage call caps in our Sequential design are the budget split; G4's "no source change, no submit" gate is the "require the artifact" half.

### K. Chat template

**K1. The June template has tool-calling bugs: turn-tag imbalance, thinking dropped, null rendered as nothing, no multimodal aliases.**
- Where:
  - HF gemma-4-31B-it discussion 118 (https://huggingface.co/google/gemma-4-31B-it/discussions/118), merged 07-15.
  - Diff analysis (https://note.com/unco3/n/ne5d382e3287b).
  - r/LocalLLaMA "Google is updating Gemma 4's chat templates, bringing major fixes to tool calling and reducing laziness" (1uxfu4k): "if Gemma 4 refuses to tool call properly it is definitely a template problem".
  - r/LocalLLaMA "Updated Gemma-4 chat template witchcraft" (1v2rqbd, July): re-quantizing the 26B with the new template and tokenizer moved it ahead of Qwen3.6-MoE on the author's single-shot coding set; "I did not realize how much of the deficit was just formatting errors"; but "Qwen3.6 still does better in Hermes ... less tool calling errors usually".
  - r/LocalLLaMA PSA 1txro73 ("you need a special chat template").
  - r/LocalLLaMA "Gemma 4 on Llama.cpp should be stable now" (1sgl3qz): after llama.cpp PR #21534 "all of the fixes to known Gemma 4 issues ... have been resolved"; run with the interleaved template via `--chat-template-file`; do not build with CUDA 13.2 ("start repeating fragments once context got longer, especially with quantized KV").
  - Community template (https://gist.github.com/jscott3201/ad69c4ffbd79f18b11a0f6a94c94fadf): null as JSON, thinking on, reject string arguments, preserve reasoning, balanced turn tags. Another (https://gist.github.com/bbrowning/c584eb2dbd79e4cc9ecedf92eee2d135, from opencode #21034): handles list-typed system content and empty content blocks that "were tripping up the Gemma 4 chat template's insertion of the end turn (`<turn|>`)".
  - HN: "Gemma4 seriously fails at toolcalls... messed up after 2-3 turns" (April, https://news.ycombinator.com/item?id=47961353); "gemma4 has a specific problem with toolcalls that affects most runtimes" (May, https://news.ycombinator.com/item?id=48027533); after July: "Gemma 4's tool calling was recently fixed; that was the main issue with agentic use" (https://news.ycombinator.com/item?id=49100241).
  - SWE-rebench update (r/LocalLLaMA 1uknx14, 2026-07-01, before the template fix): Gemma 4 31B scored 16.5%, against Qwen3.6-27B at 36.5%. A commenter attributes part of the gap to "Gemma 4's chat template is currently quite broken for a test like this" and links discussion 118.
  - r/LocalLLaMA 1sd0be8 and 1sh1bwv: llama.cpp ships an "interleaved" Gemma 4 template that keeps the last reasoning before a tool call, because "the original templates strip this reasoning, contradicting the guide" (https://ai.google.dev/gemma/docs/core/prompt-formatting-gemma4#managing-thought-context). Other common advice there: update the runtime and re-download early quants.
- Applies: **MEASURED, finding 3.** The scorer has the June template, and a submission cannot override it: VllmConfig is fixed in the scoring notebook.
  - The string-arguments issue (P3 in the gist) does not apply, because vLLM 0.19.1's `_postprocess_messages` turns argument JSON strings into dicts before rendering.
  - ADK #5650 / #6334 (role `tool` against `tool_responses`) do not apply, see F4.

**K2. Alphabetical parameter order (`dictsort`) in the tool declarations and in the call history.**
- Where: found here, from the template source (`format_parameters`, `properties | dictsort`).
- Applies: **MEASURED, finding 1.** The model writes new_string before old_string in 527 of 528 parsed v4 calls. Our own helper takes one command string, so order stops mattering. If we ever add a native-style helper, give its arguments names whose alphabetical order matches the logical order and puts the code last, for example `a_path, b_line_start, c_line_end, d_text`.

### L. Tool design and tool count

**L1. Too many tools degrade selection; a code sandbox or a single `run(command)` beats many small tools.**
- Where:
  - r/LocalLLaMA "Local models handle tools way better when you give them a code sandbox instead of individual tools" (1oxb9zp). A comment there: avoid "consecutive tool calls where the llm is required to copy and paste data around". That is exactly the shape of an old_string edit.
  - r/LocalLLaMA "I was backend lead at Manus... I stopped using function calling entirely" (1rrisqn, read in full on 09-28): "A single `run(command="...")` tool with Unix-style commands outperforms a catalog of typed function calls"; discoverability through `--help`; "agents need failure information more than success information" (they had dropped stderr and the agents "thrashed around blindly"); most "commands" are a parsed router to native functions, not a shell, so the interface is CLI syntax with typed-function safety.
  - r/LocalLLaMA 1va0cj4 (small local models, orchestration): "simply providing tools creates the most uplift, and orchestration gives a modest increase"; most orchestration tricks ported from large models "failed".
  - r/LocalLLaMA 1vvtu9z: QLoRA SFT (rank 16, 3 epochs, 5,211 examples from glaive-function-calling-v2 plus AgentInstruct, formatted in Gemma 4's own template) gave a 12B "2.7x improvement on tool calling"; a commenter with end-to-end constrained decoding in llama.cpp gets "perfect tool calls" without training but the model "doesn't know how to explore repos properly ... too focused on following the strict definition of its instructions rather than assuming that it can gather richer context". (LoRA is blocked for us: adapters are wiped, forum 743508.)
  - Goose #6883 (https://github.com/block/goose/issues/6883): Qwen3-coder switches to XML tool calls above about 5 tools.
  - Tool-count studies (https://tianpan.co/blog/2026/04/13/tool-explosion-problem-agent-tool-selection-at-scale).
  - mini-swe-agent's bash-only design (the harness behind Gemma 4 31B's reported 53.92% on SWE-bench Verified, https://www.vals.ai/models/google_gemma-4-31b-it; settings not published).
  - r/LocalLLaMA "I built a coding agent that gets 87% on benchmarks with a 4B parameter model" (SmallCode, 1tgecrq). Its tricks: "compound tools" (find, read, edit and verify in one call, because "small models lose coherence after 3+ sequential calls"), patch-first edits instead of whole-file rewrites (small models "truncate files at 60-120 lines"), and a compile or lint check after every write. Commenters point out that the 87% comes from a private, unverified stress test.
  - Rival day 4 (`experiments/2026-09-27-day4/notes.md`): removing read_file altogether and reading with `sed -n 'A,Bp'` through run_command gave "0 read errors, 17 clean endings and 34 submit calls vs 9/18" on the 12B proxy; resolve rate unchanged within noise (5/33).
- Applies: MEASURED indirectly. run_command, one string argument, parses at about 100% while edit_file fails at 33 to 74%. Keep each stage's tool list short: run_command, read_file, submit_patch and run_skill_script, plus the graph tools only for the locator. Make the helper's error text carry the instruction for the next step.

**L2. Malformed JSON from local models needs repair before execution.**
- Where: Goose #6688 (https://github.com/block/goose/issues/6688; the repo now lives at `aaif-goose/goose`), JSON repair; HN "forge" proxy (https://news.ycombinator.com/item?id=48200153), which validates calls against the tool list and rescue-parses. "Local Agent Bench" (https://mikeveerman.be/blog/github-2026-02-06-tool-calling-benchmark/, 21 open-weight models, third sweep): "Five models needed fallback parsers for non-standard output formats", and one "jumped from rank 13 to #1 after adding a parser for its bracket-notation output format". The same post warns that a lenient parser also exposes calls the model should not have made: two models scored lower once their calls were parsed.
- Applies: we cannot put a proxy in front of the scorer's vLLM. The equivalent is to accept sloppy input in our own scripts: tolerate escaped text, accept `--start/--end`, and normalize paths such as the fullwidth-bracket path `「rich/ansi.py」` seen in v7.

**L3. An AgentTool sub-agent whose last event is a function call or response hands its caller an empty string (third sweep).**
- Where: adk-python #7246 (https://github.com/google/adk-python/issues/7246, open, 2026-09-23, on ADK 2.9.2): `AgentTool` "builds the tool result from the text parts of the last nested event that has content. If the wrapped agent's run ends on an event that carries only function call/response parts, the result is `""`". One of the three reproductions is a chat LlmAgent whose last tool sets `skip_summarization`. The workaround given in the thread is a plugin on the caller's runner that copies the final output into a text part (AgentTool passes plugins down to the inner runner).
- Applies: **MEASURED in the 1.36.1 source; it matters only if we use AgentTool.** `google/adk/tools/agent_tool.py` keeps `last_content` from the last event with content (lines 262-274), then joins `_part_to_text(p)` over its parts (lines 281-284). `_part_to_text` (lines 44-52) returns text, code-execution output or executable code, and `''` for function-call and function-response parts. So an analyzer AgentTool that stops on a tool call (its own call cap, the task clock, or a response with no closing summary) returns `{"result": ""}` to the root, and the root spent that analyzer's calls for nothing. The harness README recommends exactly this pattern (gotcha 4, "Use `AgentTool` (`skip_summarization: true`) to Isolate Context Window Usage"), and the starter kit ships `sub_agents/code_analyzer.yaml`. Any AgentTool stage should be instructed to end with a plain-text summary, and our pod traces should count AgentTool results that come back empty. Two other AgentTool facts from our own reading are already in `research/harness_runtime.md`: inner runners get no compaction, and `skip_summarization: true` ends the calling agent's turn right after the sub-agent returns.

### M. Other open-model harness notes (lower relevance)

- SWE-agent #1302 (https://github.com/SWE-agent/SWE-agent/issues/1302): a local model emits multi-line Python where one bash command is expected, and loops on BashIncorrectSyntaxError. Fix: better format error messages and templates. Relevant only to how our helper usage is documented in the prompt.
- mini-swe-agent #549 (agent gets stuck for some SWE-bench instances; re-running unsticks it) and #303 ("better support for local models"; the fix was capping consecutive format errors).
- OpenHands #10039 (https://github.com/OpenHands/OpenHands/issues/10039): Qwen3 Coder puts parameter tags inside values (`command=str_replace</parameter`) 10 to 20% of the time. Fixed in PR #10539. This is the XML equivalent of A5. Qwen3-Coder #475 (https://github.com/QwenLM/Qwen3-Coder/issues/475): the 30B "would frequently omit the initial `<tool_call>` tag ... especially when the tool call was attempted after a textual response"; fixed by a template instruction block, including "Do NOT omit the initial <tool_call> tag" and "reasoning ... BEFORE the function call, but NOT after". The same "no prose after a call" rule is in our prompts.
- vLLM #55495 and PR #55497 (https://github.com/vllm-project/vllm/issues/55495): the qwen3_xml parser truncates arguments and leaks tags. The same class of parser fragility on long string values.
- Devstral in OpenHands (HF discussion https://huggingface.co/mistralai/Devstral-Small-2505/discussions/10): self-limited to about 30-line reads, looping, never viewing whole files.
- SWE-agent history processors (https://swe-agent.com/latest/reference/history_processor_config/): collapse all but the last 5 observations to one line each. This is the standard context fix; we cannot configure it, but our helpers can print short outputs.
- llama.cpp #22786 (May): a well-formed Gemma 4 tool call returned as content; #21384: array parameters serialized as a JSON string when values contain braces. Both fixed in llama.cpp; listed because the same two symptoms exist in vLLM 0.19.1 (A1, A5).
- nazarcoder123's paper-track write-up claims "93.1%" token reduction from graph compaction and AST guardrails against "malformed diffs and indentation drift"; the write-up gives no per-task results and no run logs, so it is unverified.

---

## 3. What to do next, ranked by measured size

1. **Edit through run_command plus our helper, and never through edit_file.** The helper should do an exact match, then an unescape of `\n \t \" \\ \uXXXX \x1b` and retry, then a whitespace-flexible match, then a line-range replace. After every edit it runs py_compile and prints a 3-line diff. Refuse an empty anchor (B4); print the numbered lines before replacing (B3); make every error message say what to do instead (C3).
   - Evidence: 33 to 74% parse rejects, 95 to 98% escape failures, 58% of repeats; vLLM #39072 and PR #39440 confirm the mechanism on this model and parser. The v9 `replace.py` arm (`eo`) already tests this. Check that its prompt forbids edit_file outright, not just prefers the helper.
2. **Context guard.** Bounded outputs, per-stage call caps, and a fresh context per stage. Assume no compaction.
   - Evidence: 31 of 74 tasks over the threshold and 7 overflows in v4. None of those contexts shrank on the pod.
3. **Make pod evals faithful before trusting another race.**
   - Install the Kaggle v2 chat template on the pod.
   - Pass `EventsCompactionConfig(15, 2, 14336, 5)` through our `scripts/run_eval.py`, since the swegemma CLI leaves it at None.
   - Re-run v4 once under both changes to size the gap. Run one known-pass task as a canary at the start of every batch (G3).
4. **Pre-submit hygiene script, also on a timer.** Revert changes under `tests/`, `conftest.py` and `pytest.ini`; delete untracked scratch files. Evidence: 16 of 61 patches with scratch files, 6 to 11 touching tests, 4 known "Failed to apply test_patch"; the scorer keeps the working-tree diff when submit_patch never runs.
5. **Loop breaker inside the helpers.** Keep a state file of the last command hashes; on the second identical failure, return a message that names the alternative mechanism.
6. **Test gate before submit, with an outer `timeout`.** Evidence: 78 of 155 failing runs never ran pytest, and there are 9 verification hangs. Timeout text must say "cut off", not "failed" (G2).
7. **Stop spending on HIDDEN_SPEC and UNDERSPECIFIED public tasks.** The host says the hidden set was screened for them. Treat hidden statements as PR descriptions (section 1).
8. **Add one line to the system prompt with the date and "files may be newer than your training data".** Cheap, and it removes a documented thought loop (E2, F5).

Third-sweep additions; small, and folded into items 1, 4 and 6 rather than ranked on their own:
- In item 6's gate: refuse `submit_patch` when the diff has no changed non-blank, non-comment line outside `tests/`, and print `git diff --stat` with a request to tie each file to the problem statement (G4, H3). Evidence: 3 to 7 no-error empty patches per run; 21% of unresolved patches edit a non-gold source file.
- In item 1's helper: read and write bytes, and refuse a file that does not decode as UTF-8, rather than inherit edit_file's lossy rewrite (B7).
- If any design uses AgentTool: the wrapped agent's instruction must end with "finish with a plain-text summary of what you found", and pod traces should count empty AgentTool results (L3). Any stage with no tools gets `include_contents: none` and a text-only instruction (F6).
- If any stage turns thinking on: set `include_thoughts` explicitly on every LlmAgent, keep `max_output_tokens` small, and check its traces for early-answer and `<turn|>` symptoms near 29k tokens (E4, A8).

---

## 4. How the numbers were computed (reproducible)

All from `eval/eval3/eval/runs/p_v{4,6,7,8}/traces/trace_*.json` (ATIF steps; `tool_calls[].function_name`, `arguments`, `extra.usage.prompt_tokens`, `observation.content`). Recomputed 2026-09-28 with an inline Python pass; values matched the 09-27 numbers.
- **Parse rejects**: an edit_file call counts as rejected when `observation.content` contains "mandatory input param".
- **Escapes**: regex `\\n|\\"|\\t|\\u[0-9a-fA-F]{4}|\\x1b` over `old_string`; success means `json.loads(observation.content)["status"] == "ok"`; the matcher tier is that JSON's `strategy` field.
- **Argument order**: the index of `new_string` against `old_string` in the parsed argument dict (vLLM inserts keys in the order the model emits them); rejected calls have no `old_string` key.
- **Exact repeats**: the pair (function_name, sorted-JSON arguments) already seen earlier in the same task.
- **Compaction**: per author, the first call with `prompt_tokens > 14336`, then whether any later call by the same author has less than 70% of that.
- **Template**: Kaggle file list via `kaggle models instances versions files google/gemma-4/other/gemma-4-31b-it-qat-w4a16-ct/2`; HF history via `huggingface.co/api/models/google/gemma-4-31B-it-qat-w4a16-ct/commits/main`. Rendering used jinja2 on 3 synthetic histories (tool-only, text plus tool, nudge after text); outputs in the session scratchpad `tmpl/`.
- **Parser code**: `gh api repos/vllm-project/vllm/contents/vllm/tool_parsers/gemma4_tool_parser.py?ref=v0.19.1` (758 lines; `_parse_gemma4_args` at line 85, key scan line 120, string branch lines 141-151). v0.19.1 was published 2026-04-18.
- **PR mapping**: `gh api repos/<repo>/pulls/<n>` for all 129 rows of `data/tasks.jsonl`; compared `.title` to the statement's first line, the normalized first 200 characters of `.body` to the normalized statement, and `.merged_at` to `created_at`.
- **Forum**: `kaggle competitions topics list gemma-4-developer-agent -p {1,2} --format json` (40 topics) diffed against the 09-27 snapshot; changed threads read with `topics show <id> --format json` (kaggriculture venv's kaggle CLI).
- **Reddit**: `https://www.reddit.com/r/LocalLLaMA/comments/<id>/.rss` with a browser user agent and 15-30 s spacing (429 otherwise); search via `/r/LocalLLaMA/search.rss?q=...&restrict_sr=1&sort=new&t=month`. old.reddit.com and `.json` are blocked from this machine. Threads read on 09-28: 1sjyzmi, 1v2rqbd, 1va0cj4, 1rrisqn, 1vvtu9z, 1sxqa2c, 1sgl3qz, 1woxw7s, 1wopeqg, 1wpqyaz, 1wrfp50.
- **Hacker News**: Algolia `search_by_date` on comments since 2026-07-01 for "gemma 4 tool", "gemma 4 agent", "gemma4 tool calls", "gemma 4 loop".
- **GitHub**: `gh search issues --repo <repo> "<terms>" --sort created` on vllm-project/vllm, google/adk-python, anomalyco/opencode, SWE-agent/mini-swe-agent, SWE-agent/SWE-agent, OpenHands/OpenHands, QwenLM/Qwen3-Coder, ggml-org/llama.cpp; `gh issue view` / `gh pr view` for bodies and comments (saved under scratchpad `gh3/`). The GitHub search API rejected `block/goose` in the morning sweeps because the repo has moved: `gh api repos/block/goose` now resolves to `aaif-goose/goose`, and the third sweep searched that.
- **Third sweep, sources**: `gh search issues --repo <repo> --created ">=2026-09-01"` (and `">=2026-09-12"` for vLLM) on the repos above plus aaif-goose/goose, Aider-AI/aider, OpenHands/software-agent-sdk; issue status re-checked with `gh api repos/<repo>/issues/<n>` for every vLLM item cited in A1 to A8. HF discussions via `https://huggingface.co/api/models/google/gemma-4-31B-it/discussions` (listing) and the discussion pages. HN Algolia `search_by_date` with `created_at_i > 2026-09-10`, ten queries: nothing new on point beyond HN 49729865, which was already cited. Reddit RSS search over 15 queries in r/LocalLLaMA, r/LLMDevs, r/ChatGPTCoding and r/MachineLearning (scratchpad `reddit/search.json`), then thread RSS for the threads cited below.
- **Third sweep, measurements** (all inline Python over the same four runs):
  - Parallel calls: per ATIF step, `len(tool_calls) > 1`, and whether two of them share (function_name, sorted-JSON arguments).
  - Output cap: `metrics.completion_tokens >= cap - 5` per agent step (cap 4,096 for v4/v8 and 2,048 for v6/v7), and whether that step has a parsed tool call; raw `<|tool_call>` without `<tool_call|>` anywhere in the step JSON.
  - Empty patches: `task_results.jsonl` rows with `agent_patch_size` 0, grouped by `error`; test-only patches from `patches/*.patch` (`diff --git` paths all under tests, `test_*` or `conftest.py`).
  - Gold overlap: gold files are the `--- a/` and `+++ b/` paths of the task's `patch` field; an agent patch "edits a non-gold source file" when it modifies (not creates) a non-test file outside that set.
  - First edit: the index of the first edit_file or write_file call divided by the task's call count.
  - UTF-8: every `.py` member of `data/raw/snapshots/*.tgz` (59 archives; no fastapi) decoded with `bytes.decode('utf-8')`.
  - Provenance: scratchpad `prcheck.py` (PR fields against all 129 rows) and `issuecheck.py` (closing references parsed from the PR body, linked issue body fetched, leftover text after removing title and body).

Coverage gaps:
- Reddit's JSON API and old.reddit.com return 403; some search queries returned 429 even with spacing ("gemma 4 developer agent", "gemma 4 edit tool").
- The Medium article "I Built a Gemma 4 AI Agent, Fix Infinite Tool Loops Fast" returned 403; its search snippet says the fix was llama.cpp's `--jinja` flag, which is a llama.cpp-only item.
- The Kaggle data page is client-rendered; quotes are from the PageService dump saved on 09-27 (`scratchpad/kaggle_pages.md`).

Caveats:
- These are pod runs, which differ from the scorer in template and compaction (finding 3, and finding 2 under "Cause on the pod"). Rates could shift on the scorer.
- The link between edit failures and unsolved tasks is an association, not a controlled result.
- The v9 race arms are the controlled test.

---

## 5. Where the list of 74 lives

- `data/kaggle_valid_ids.txt`: the 74 public tasks whose gold patch passes in the Kaggle environment (fastapi 31, rich 42, requests 1). `data/tasks.jsonl` holds all 129 public tasks.
- `research/tasks/`: per-task research JSON for 67 of them, written by the parallel workflow. Missing: fastapi_15800, rich_3180, rich_3468, rich_3772, rich_3777, rich_3782, rich_3930.
- Every one of the 129 is an upstream merged PR, with the problem statement taken from the PR title and body and `created_at` from the merge time. Public upstream solutions exist for all 129, and they are the gold `patch` field. The hidden tasks come from private repositories, so no such public solutions exist for them.
