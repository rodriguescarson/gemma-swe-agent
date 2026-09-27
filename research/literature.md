# Literature review: issue resolution with a ~30B model under a 5-minute, 70-call, 32k budget

Date: 2026-09-27. Scope: which published techniques for SWE-bench-style issue resolution transfer to *this* setting:
Gemma-4-31B W4A16 on 4x L4 (vLLM 0.19.1, TP=4, max_model_len 32768), a declarative Google ADK agent config
(SequentialAgent / ParallelAgent / LoopAgent, prompts, stdlib-only skill scripts), 5 min / 70 tool calls /
150 turns per task, tasks run sequentially, and the whole run must finish in 12 h.

Method: primary sources only. Every arXiv PDF cited was downloaded and converted with `pdftotext -layout`; numbers were
read from the text (local copies: `/private/tmp/claude-501/-Users-carson-Projects/654244a3-b38c-45a0-96af-d7e5f0aac6ce/scratchpad/lit/pdfs/<id>.txt`).
The Konwinski Prize write-ups were pulled through the Kaggle discussions API (topic ids given below; local copies in
the same scratchpad, `kp_*.txt`, `lit/kp2_*.json`). Harness facts were read from the installed wheels under
`/Users/carson/Projects/gemma-swe-agent/.venv/lib/python3.12/site-packages`. Our own numbers come from
`eval/race1/runs/*/task_results.jsonl` and `eval/kaggle/e74_v3/results.jsonl` (commands in section 7).
Anything not checked against a primary source is marked UNVERIFIED.

---

## 0. Bottom line

1. **Almost everything that produced the big published jumps is not available here.** Trained verifiers
   (SWE-Gym 20.6 to 32.0 at 16 rollouts; R2E-Gym 34.4 to 51.0 at 26; DeepSWE 42.2 to 59 at 16), RL (SWE-RL,
   DeepSWE: 64 H100 for 6 days), MCTS (SWE-Search, 100 iterations) and 40-500-sample pipelines (Agentless, SWE-RL,
   Kimi-Dev) all need training or 10-500x our per-task compute. They are listed in section 5 so nobody re-proposes them.
2. **What does transfer is cheap harness hygiene.** Every one of those changes has a published effect that is large for weak models:
   - context management at a 32k window (a 30B model goes from 9.4% to 20.6-23.8%, arXiv 2609.20804);
   - explicit tools rather than bash alone (+15.0 points for the 30B model, same paper; +14.6 for GPT-4.1-mini in Lita);
   - content-anchored, lint-gated edits (SWE-agent +3.0 points; edits addressed by line number silently corrupt 99.1% of files after a one-line shift, arXiv 2609.11957);
   - a mandatory execution check before submitting (Agentless regression filter +1.3 points, reproduction filter +5.0 points).
3. **Speed is score on the hidden set.** sub3 needed about 10.4 h for about 120 hidden tasks, so most hidden tasks
   hit the 5-minute cap. The per-task cap cannot be raised: 120 tasks x 6 min is already the 12-hour ceiling.
   Any added phase has to be paid for from the fixer's own time.
   Our race-1 runs replicate SWE-agent's "succeed quickly, fail slowly": resolved runs had a median of 71-91 s against an
   unresolved p90 of 228-319 s. So the tail of failing runs is the time to reclaim.
4. **Selecting between candidates is the only large lever left, and it depends on one number we have not measured**:
   aggregate decode throughput on 4x L4 at 2-3 concurrent streams. Two comparisons from race 1 show the ceiling.
   - The oracle best pair of arms reaches 24/51, against 21/51 for the best single arm.
   - Picking the shortest non-empty patch across all 6 arms gives 22/51.

   Kimi-Dev shows that 3 patches x 3 tests already beat majority voting over 40 patches.
   Whether any of this fits in 5 minutes depends on vLLM batching on L4 (UNVERIFIED).

---

## 1. Setting facts that decide implementability (verified from source)

| # | Fact | Evidence | Consequence |
|---|---|---|---|
| S1 | No callbacks are available to submissions. `compile_submission` is called without a `callback_registry` | `swegemma/harness/agent_runner.py:334-344` | No programmatic history trimming, observation masking, loop interception or plan injection hooks. Context management must be done by agent-tree structure (`include_contents: none`, `output_key`, `{state}` templating) and by keeping tool outputs small. |
| S2 | Instruction strings are re-rendered with session state on every LLM call | `google/adk/flows/llm_flows/instructions.py:51-56` (`inject_session_state`) | A `{plan}` written by an earlier stage is re-injected every turn, outside the history. v4 already does this (`submissions/v4/prompts/fixer.md:7 {plan?}`, `sub_agents/locator.yaml:8 output_key: plan`). |
| S3 | ParallelAgent branches run as asyncio tasks | `google/adk/agents/parallel_agent.py:71-73` (TaskGroup) | LLM calls from branches overlap, and vLLM batches them. |
| S4 | Sync tools run inline on the event loop. The thread pool is used only if `run_config.tool_thread_pool_config` is set, and the harness builds `RunConfig(max_llm_calls=...)` only | `google/adk/flows/llm_flows/functions.py:973-982`, `google/adk/tools/function_tool.py:236-238`, `agent_runner.py:516`, `swegemma/tools/execution.py:16,131` (`def run_command`) | While one branch runs pytest, every other branch is frozen. Parallel branches get overlapped decode but serialized tool execution. |
| S5 | The loop ends on the first final text after `patch_submitted`, whichever agent emits it | `agent_runner.py:556-579` | In any parallel design only the final selector may call `submit_patch`. If a branch submits, the other branches are killed. |
| S6 | On timeout or no submit, the fallback patch is `git add -N . && git diff` of `/workspace` | `agent_runner.py:760-775` | Whatever state `/workspace` is in at the cap becomes the patch, including a half-finished edit and every untracked scratch file. The best-known state must be kept in `/workspace`, not only in a side file. |
| S7 | Budget is one shared context: 70 calls, 150 turns and 5 minutes cover all sub-agents. `get_budget` and `submit_patch` do not count toward calls. A warning appears only when 10 or fewer calls remain | `data/HARNESS_README.md:371-373, 400, 409` | K parallel branches split 70 calls. There is no built-in time warning, so the agent must poll `get_budget` for free. |
| S8 | `edit_file` is already content-anchored: exact, then whitespace-flexible, then regex match, with a uniqueness check | `data/HARNESS_README.md:453-457` | The built-in editor already has the anchor-and-verify property. Our `helpers_v9/replace.py` addresses edits by line range and has no content anchor (`replace.py:1-6, 20-26`), which is a step backwards (see T1). |
| S9 | `read_file` returns at most 150 lines and 10,000 characters | `data/HARNESS_README.md:436` | This is close to SWE-agent's best viewer window of 100 lines (section 2.1). |
| S10 | The subprocess sandbox rewrites `/tmp` and `/workspace` only in command text | `data/HARNESS_README.md:256` | The v2-v8 helper-path bug. Scripts must resolve `$TMPDIR` themselves. |
| S11 | 12-hour ceiling and sequential tasks | context brief; ledger | The per-task cap is fixed at about 5 minutes, so every added stage costs fixer time. |

L4 speed relative to the pod: the median seconds per tool call was 4.15 s for v3 on Kaggle L4 (`eval/kaggle/e74_v3/results.jsonl`, n=74)
against 2.48 s (v4) and 2.58 s (v9_eog) on the race-1 H100 pod. That is a ratio of about 1.6-1.7x, but it compares
different bundles and different pod concurrency, so treat it as UNVERIFIED until the same bundle runs on both.

---

## 2. Technique by technique

Legend for "Here?": **Y** = implementable with prompts + agent tree + stdlib scripts; **P** = partly or with
caveats; **N** = needs training, callbacks, logprobs, internet, or 10x+ compute.

### 2.1 SWE-agent ACI ([arXiv 2405.15793](https://arxiv.org/abs/2405.15793))
- **Measured.** Ablations on SWE-bench Lite with GPT-4 Turbo, full system at 18.0% (pdf text lines 370-372):
  - editing: edit with linting 18.0; without linting 15.0 (-3.0); no edit command 10.3 (-7.7);
  - search: summarized search 18.0; iterative search 12.0 (-6.0); no search 15.7;
  - file viewer: 100-line window 18.0; 30-line window 14.3; full file 12.7 (-5.3);
  - history: last 5 observations kept 18.0; full history 15.0 (-3.0).

  Shell-only reached 11.0 against 18.0 for SWE-agent (Table 1).
- **Edit failures cascade** (lines 595-600). 51.7% of trajectories had at least one failed edit. The chance that an edit
  attempt eventually succeeds is 90.5% from a clean start and falls to 57.2% after a single failed edit.
- **Succeed quickly, fail slowly** (lines 602-608). Resolved runs had a median of 12 steps and $1.21. Unresolved runs
  averaged 21 steps and $2.52. 93.0% of resolved instances were submitted before the budget ran out.
- **Cost.** A lint check or summarized search costs milliseconds and saves calls.
- **Here? Y.** The pieces exist:
  - `read_file` already returns 150 lines (S9);
  - `edit_file` has no lint step, but `replace.py` runs `py_compile` and reverts on failure;
  - summarized search can come from `locate.py` or grep helpers that return a file list with hit counts instead of raw matches.

  Our own data agree. Race-1 resolved runs had a median of 71-91 s against 112-130 s for unresolved runs
  (unresolved p90 228-319 s; section 7).

### 2.2 Agentless ([arXiv 2407.01489](https://arxiv.org/abs/2407.01489))
- **Headline.** 32.00% on Lite with GPT-4o at $0.70 per issue (Table 1).
- **Localization** (Table 2):
  - prompting finds the file in 78.7% of issues, embeddings in 67.7%, and the two combined in 81.7%;
  - a skeleton view (signatures only) keeps the ground truth in 58.3% of issues at about 698 lines of code and $0.02, against 53.7% at 778 lines and $0.15 for complete files.
- **Repair** (Table 3). Greedy location with 40 samples gives 29.33%. Four sampled locations x 10 samples gives 32.00%.
  One greedy sample per location, 4 in total, already reaches 80 fixes out of 300. The curve is flat after about
  40 samples. Oracle selection across all samples would reach 42.0% (126 of 300).
- **Selection** (Table 4). Majority voting alone gives 77 fixes (25.67%). Adding regression tests gives 81 (27.00%, +$0.01).
  Adding reproduction tests gives 96 (32.00%, +$0.25).
- **Reproduction tests** (section 5.1.3). 213 of 300 issues got a test that prints "Issue reproduced" on the original
  code. Only 94 of those also pass with the gold patch. When no patch passes the reproduction test, Agentless falls
  back to the regression tests.
- **Voting normalization** (lines 571-577). Patches are parsed with the stdlib `ast` module and unparsed with
  docstrings removed before counting. That is stdlib-implementable.
- **Regression-test selection** (lines 553-561). Agentless runs all existing tests, then asks the LLM which tests the
  fix is allowed to change.
- **Here? P.** Localize-then-repair and SEARCH/REPLACE editing are already in our design, and regression plus
  reproduction filtering is implementable as a script. The 40-sample budget is not: 40 samples cost roughly
  20-40x our decode budget.

### 2.3 AutoCodeRover ([arXiv 2404.05427](https://arxiv.org/abs/2404.05427))
- **Design.** AST-level code-search APIs (`search_class`, `search_method_in_class`, and so on), a stratified iterative context search, and spectrum-based fault localization (SBFL).
- **Measured** on Lite (table at pdf lines 514-519):

  | Setting | Resolved | Mean time per task | Tokens |
  |---|---|---|---|
  | ACR @1 | 19.0% | 195 s | 37k |
  | ACR @3 | 26.0% | 520 s | 112k |
  | ACR with SBFL | 22.0% | 250 s | 40k |

  Note that pass@1 finishes in 195 s per task, close to our budget.
- **Here? P.** Signature-returning search is what `locate.py` does. SBFL needs a failing test, which at issue time
  exists only if a reproduction test was written. With one, stdlib `sys.settrace` or `trace` can rank the executed
  functions (see T10).

### 2.4 OpenHands CodeAct ([arXiv 2407.16741](https://arxiv.org/abs/2407.16741))
- **Design.** Actions are code or bash. CodeActAgent reached 26.0% on Lite with Claude 3.5 Sonnet (pdf line 525).
- **Here? Principle only.** For weak models, explicit tools beat bash alone: 2609.20804 measures +15.0 points for its
  30B model, and Lita measures +14.6 for GPT-4.1-mini. Keep the structured tools.

### 2.5 Moatless Tools ([github](https://github.com/aorwall/moatless-tools)) and SWE-Search ([arXiv 2410.20285](https://arxiv.org/abs/2410.20285))
- **Moatless** reached 24.67% on Lite with GPT-4o at $0.14 per issue, and 26.67% with Claude 3.5 at $0.17
  (Agentless Table 1, lines 676-677).
- **SWE-Search** (MCTS plus a value function plus a discriminator) improved every base model it was tried on,
  +23% relative on average (Table 1). For example Qwen2.5-72B went from 18.0 to 24.7 and Llama-3.1-70B from 13.6 to 17.7.
  The cost is up to 100 search iterations with at most 3 expansions per node (line 483).
- **Here? N for search** (10-30x compute). **P for the lesson.** Flexible state transitions without a controller
  cause infinite loops (section 4.1.2). That is our exact-repeat problem, and it argues for bounded stages.

### 2.6 SWE-smith ([2504.21798](https://arxiv.org/abs/2504.21798)), SWE-Gym ([2412.21139](https://arxiv.org/abs/2412.21139)), R2E-Gym ([2504.07164](https://arxiv.org/abs/2504.07164)), DeepSWE ([blog](https://www.together.ai/blog/deepswe)), Skywork-SWE ([2506.19290](https://arxiv.org/abs/2506.19290))
- **SWE-smith.** SWE-agent-LM-32B reaches 40.2% on Verified (training data).
- **SWE-Gym.**
  - A trained ORM verifier lifts pass@1 from 20.6% to 29.8% at 8 rollouts and 32.0% at 16 (Figure 3).
  - A LoRA-trained verifier beat full fine-tuning (29.8 against 27.2 at 8 rollouts).
- **R2E-Gym** (lines 386-420):
  - execution-based and execution-free verifiers each plateau around 43.7% and 42.8%, while the hybrid reaches 51.0% at 26 rollouts;
  - for most problems, fewer than 20% of generated tests distinguish correct from incorrect patches;
  - "toxic" tests (pass wrong patches, fail right ones) reach up to 10% for some problems;
  - an execution-free verifier given only the patch falls from 42.8 to 37.6, so it relies on agent thoughts rather than the patch.
- **DeepSWE.** Pass@1 42.2%, pass@16 71.0%, 59% with hybrid test-time scaling, and "K=8 achieves a majority of"
  the gain. Going from 16k to 128k context gains 2% or less beyond 32k, and "scaling the number of output tokens does not seem to be effective".
- **Skywork-SWE.** 38.0% to 47.0% with test-time scaling.
- **Here? N** for the verifiers (training, and adapters are currently wiped) and for the large rollout counts.
  **Y for the lesson:** execution-based selection alone is weak because tests rarely discriminate. Pair it with a
  cheap prior (shortest diff, majority), not with an LLM judge made from the same small model.
  Our Jev probe agrees: AUROC 0.742, but only 0.61 pairwise within a task, and it lost to the shortest patch.

### 2.7 Kimi-Dev ([arXiv 2509.23045](https://arxiv.org/abs/2509.23045))
- **Design.** Agentless training as a skill prior, 72B model, 60.4% on Verified.
- **Test-time self-play** (section 3.4). A BugFixer and a TestWriter each produce 40 candidates.
  - Only tests that fail on the original code are kept.
  - Each patch is scored as `S_i = sum_j FP(i,j)/sum_j F(j) + sum_j PP(i,j)/sum_j P(j)`: the fail-to-pass fraction plus the pass-to-pass fraction.
  - The score rises from 48.0% at 1x1 to 60.4% at 40x40.
  - "3 patches and 3 tests ... already surpassed ... majority voting from 40 BugFixer patches" (lines 398-399).
  - Appendix F reports emergent parallel scaling: the model summarizes the differences between candidates and writes a new patch.
- **Here? Y for the score** (a stdlib script over pytest results in K workspace copies). **P for K>1** (budget; S3-S5).
  The best-evidenced selection rule for small K.

### 2.8 SWE-RL ([arXiv 2502.18449](https://arxiv.org/abs/2502.18449))
- **Results.** Llama3-SWE-RL-70B reaches 41.0% on Verified with Agentless Mini, using 500 repair samples and 30 reproduction tests.
  Twenty samples give 33.6%, 160 give 40.0%, and returns flatten after that (section 3.4).
- **Formatting.** The base Llama-3.3-70B produced correctly formatted edits only 12.2% of the time with greedy decoding,
  and 44.6% under 20-sample majority voting (Table 2).
- **Here? N** (RL, 500 samples). **Lesson:** format reliability is a first-order problem for untuned models. Use a forgiving,
  content-anchored edit tool, which `edit_file` already is.

### 2.9 CodeMonkeys ([arXiv 2501.14723](https://arxiv.org/abs/2501.14723))
- **Setup.** 10 parallel (edit, test) state machines per issue, using Claude 3.5.
- **Results** (section 2.3). Coverage is 69.8%. Random selection among candidates gives 45.8%, and their selector gives 57.4%,
  closing about half of the random-to-oracle gap.
  - Model selection without first filtering to the top 3 by test votes *underperforms* plain voting.
  - Ties are broken by the shorter git diff (line 418).
  - Serial and parallel compute allocations "often lead to similar coverage values".
- **Here? P.** Test-vote filtering then shortest-diff tie-break is implementable. A model-based selection state machine
  costs a stage we cannot afford.

### 2.10 Patch selection by behaviour: clustering, majority, medoid
- **Agentless.** AST-normalized majority vote (2.2).
- **Trae Agent** ([2507.23370](https://arxiv.org/abs/2507.23370)). Deduplication, regression-test pruning, then a selector agent.
  Without pruning, the worst-case ensemble drops 27.01% as it grows (lines 160-206).
- **Co-PatcheR** ([2505.18955](https://arxiv.org/abs/2505.18955)). Three 14B models reach 46% on Verified. Majority vote was the
  best selector with 60 candidates.
- **Konwinski public 4th place** (topic 568799). "Edit Distance Selection": pick the candidate with the smallest total
  edit distance to the others, a medoid. It turned an LB of -1 into a valid score.
- **"Are Solved Issues Really Solved?"** ([2503.15223](https://arxiv.org/abs/2503.15223)). 29.6% of plausible patches behave
  differently from gold. 7.8% of patches pass the SWE-bench tests but fail the developer's full suite.
- **Here? Y as code** (`ast.unparse` plus `difflib` medoid). It only pays with 3 or more candidates.

### 2.11 Reproduction-test generation
- **Otter** ([2502.05368](https://arxiv.org/abs/2502.05368)) produces fail-to-pass tests for 31.4% of issues with GPT-4o, and
  37.0% as a 5-way ensemble. It localizes existing test files first and uses them as templates. Filtering by its
  tests raises precision from 60.8% to 91.9% while cutting recall to 33%.
- **SWT-Bench** ([2406.12952](https://arxiv.org/abs/2406.12952)): SWE-Agent+ produces a fail-to-pass test in 19.2% of cases.
- **SWE-Tester** ([2601.13713](https://arxiv.org/abs/2601.13713)), 2026: fine-tuned open models gain up to +10% success and
  +21% change coverage (training; N here).
- **CoHarden** ([2607.19843](https://arxiv.org/abs/2607.19843)), 2026: write the test first, then harden test and fix against
  mutations. It reaches 69.4% resolved on Verified, +9.6 points over the best fix-only baseline.
  - Fail-to-pass alone is insufficient: lax tests admit wrong patches.
  - Co-generating test and fix causes "test-fix error coupling", where the in-trajectory fail-to-pass check passes with both the test and the fix wrong.
- **Dynamic cogeneration** ([2601.19066](https://arxiv.org/abs/2601.19066), Google, FSE'26): writing the reproduction test inside
  the same agent trajectory produces as many reproduction tests as a dedicated agent without lowering the plausible-fix rate.
- **Konwinski 1st place** is the key small-model result (section 3). A 32B model "would most of the time have the correct idea for
  the tests but fail on importing modules or using the classes". Giving it the imports and skeletons of related test files fixed that.
- **Here? Y.** A `testctx.py` stdlib script can print imports, fixtures and the skeleton of the best-matching test file,
  reusing the `gate.py` scoring (`helpers_v9/gate.py:17-26`).
  **Caveat:** with K=1 patch a test only guides and gates. It cannot pick between patches.

### 2.12 Regression testing and test selection
- **Agentless regression filter:** +4 fixes on 300 (2.2).
- **SWE-Fixer** ([2501.05040](https://arxiv.org/abs/2501.05040)): an open 72B model goes from 30.2% to 32.8% on Verified with
  pass-to-pass filtering.
- **TestPrune** ([2510.18270](https://arxiv.org/abs/2510.18270), FSE'26). The LLM names suspicious functions, coverage maps tests
  to them, and a greedy hitting set picks a minimal regression subset. Resolution rises 8.0-12.9% relative in Agentless,
  SWE-agent and Trae. Reproduction rate rises 6.2-9.0% relative in Otter. Overhead is $0.02-0.05 per instance.
- **Konwinski 2nd place:** "Running all unit tests before and after applying patches didn't help ... too slow and risky".
- **Here? Y.** `gate.py` already does name-grep test selection (top 3 files), then runs them on the original and edited trees.
  A coverage-based refinement is possible with `sys.settrace`, but it costs runtime (T11).

### 2.13 Localization: LocAgent ([2503.09089](https://arxiv.org/abs/2503.09089)), CoSIL ([2503.22424](https://arxiv.org/abs/2503.22424)), KGCompass ([2503.21710](https://arxiv.org/abs/2503.21710))
- **LocAgent** (Table 4, Lite). File Acc@5 is 61.68 for BM25, 84.67 for CodeRankEmbed, 79.56-86.13 for Agentless and
  Moatless with Claude, and 92.70 for LocAgent with a fine-tuned Qwen2.5-32B.
- **CoSIL.** Call-graph iterative search with Qwen2.5-Coder-32B reaches 43.3-44.6% Top-1 at function level.
  Plugged into Agentless it raises resolution 2.98-30.5% relative.
- **KGCompass** reaches 58.3% on Lite at $0.2 per issue, but it needs the issue and PR history graph, which is not available offline.
- **Here? P, and low priority.** Our diagnosis attributes only 2 of 39 never-solved tasks to wrong location
  (`eval/diagnosis.md`). Localization is not our bottleneck.

### 2.14 Test-time scaling for agents in general
- **OPPO** ([2506.12928](https://arxiv.org/abs/2506.12928), GAIA-style tasks, not SWE). Plain best-of-N beat beam and tree
  search, and list-wise verification was the best merge.
- **EGSS** ([2602.05242](https://arxiv.org/abs/2602.05242)): entropy-guided stepwise scaling. It needs logprobs, which ADK YAML
  does not expose, so N.
- **Satori-SWE** ([2505.23604](https://arxiv.org/abs/2505.23604)): evolutionary refinement that requires an RL-trained
  self-evolving model, so N.
- **Second Thought** ([2608.13667](https://arxiv.org/abs/2608.13667), 2026). Parallel reasoning branches decoded while tools
  run cut turns in 9 of 9 settings and median latency by 10.9%. It needs harness-level forking, so N as designed.
  It supports the idea that idle decode capacity during tool calls is real.

### 2.15 Budget awareness and early stopping
- **BATS** ([2511.17006](https://arxiv.org/abs/2511.17006), Google, web agents). A budget-status block injected every turn
  matched accuracy with 40.4% fewer search calls and 31.3% lower cost.
- **BAGEN** ([2606.00198](https://arxiv.org/abs/2606.00198)). Agents are over-optimistic about their remaining budget.
  Stopping early saves 28-64% of tokens on runs that fail anyway.
- **Here? Y by prompt.** `get_budget` is free (S7). The harness warns about remaining calls but never about time.

### 2.16 Reasoning and output length
- **Danger of Overthinking** ([2502.08235](https://arxiv.org/abs/2502.08235)). More overthinking correlates with lower resolution.
  Choosing the lower-overthinking solution raised performance "by almost 30%" and cut compute 43% (lines 53-54).
- **Konwinski 1st and 2nd place** both found reasoning models no better than Qwen2.5-Coder-32B.
- **DeepSWE:** more output tokens did not help.
- **Here?** Keep thinking off, which is our current operating point.

### 2.17 Context limits
- **"Limits of long-context reasoning"** ([2602.16069](https://arxiv.org/abs/2602.16069), ICLR'26 workshop). Successful agentic
  trajectories stay under 20-30k tokens, and longer context correlates with lower success. Qwen3-Coder-30B-A3B solves 7% at 64k single-shot.
- **Complexity Trap** ([2508.21433](https://arxiv.org/abs/2508.21433)). Keeping only recent observations matches LLM
  summarization at about half the cost. With Qwen3-Coder-480B it is 52% cheaper and +2.6 points better than the raw agent.

---

## 3. Konwinski Prize: the closest precedent (same 4x L4 class, offline, open 32B models)

Setting: the rules gave "L4x4 machines", a 9-hour notebook for about 70 public issues, 24 hours for the forecasting
phase, and 30 minutes per issue (competition overview, via `lit/kprize_pages.txt`). That is roughly 7.7-12 minutes per
issue, 1.5-2.5x our budget. Scoring penalized wrong patches, so every top team skipped most issues. That part does not
transfer: here a wrong patch costs nothing.

- **1st place, Eduardo Rocha de Andrade** ([writeup, topic 568884](https://www.kaggle.com/competitions/konwinski-prize/writeups/eduardo-rocha-de-andrade-1st-place-solution-write-)).
  Private result: 9 correct, 2 wrong, 109 skipped (7.5%). Public LB ranged 0.056-0.098 across seeds.
  - Pipeline: Agentless 1.5 with Qwen2.5-Coder-32B.
  - Reproduction tests: 5 candidates, with a second batch of 5 at higher temperature if none reproduce. The skip rule
    applied when all 10 failed.
    - Context for the tests: find the relevant test files, show the skeletons of their functions and classes, and let
      the model choose members to inspect. Always extract the import statements.
    - Context diversity: 1 of 5 samples got imports plus members, 1 got imports only, and 3 got no context. One sample used greedy decoding.
    - A test was kept only if it printed "Issue reproduced" and nothing else.
  - Localization: 3 stages, sampling 2 edit locations. Repair: 4 samples per location, 8 candidates in total.
  - Edit format: SEARCH/REPLACE, "the amount of valid patches increased a LOT" compared with raw diffs.
  - Filtering and selection:
    - `git apply --check`;
    - keep candidates that fix at least one fail-to-pass test;
    - compare the model-selected pass-to-pass tests against the unpatched reference, and submit if results are equal or better.
  - Speed: all tests ran in parallel with timeouts. The repo structure was built once instead of at every step, which
    saved 5-20 s per step. Global and per-task time guards; about 3-10 minutes per issue.
  - What did not work: an agent loop (test, run, feed back; tried late) and reasoning models.
- **Public 2nd place, Camaro** ([writeup, topic 568888](https://www.kaggle.com/competitions/konwinski-prize/writeups/camaro-public-2nd-place-solution)).
  - Agentless-style pipeline: localize 5 files, then extract the relevant spans rather than a yes/no, which keeps context short.
  - Reproduction tests with few-shot examples of good tests "significantly boosted performance", but more examples stopped helping.
  - Test-syntax errors were fed back for repair.
  - Repair used a function-call style (path, old string, new string), with feedback on apply failure and up to 5 attempts.
    "More tries can sometimes lead to a higher failure rate."
  - Qwen2.5-Coder-32B beat 72B, QwQ and R1 as the most "stable and fast". 14B was much worse than 32B. vLLM JSON-schema
    structured output was used for stability.
  - Running the full unit test suite was too slow and risky.
- **Public 4th / private 15th, ISAKA** (topic 568799): edit-distance medoid selection (2.10), and skip rules tuned to the leaderboard.
- **Private 3rd, 4th, 5th, 8th** (topics 597207, 596181, 596375, 590920):
  - 3rd place used a LoRA difficulty classifier to skip issues, plus 6x6 patches with LLM, format and dry-run checks.
  - 4th place used tree-sitter context, a generated pytest file with `test_before_patch` and `test_after_patch`, and "early stopping".
    Rule-based diff fixes had random effects. AST checks and reusing existing pytest functions had minimal impact.
  - 5th place mapped tracebacks to files and lines with a regex before falling back to LLM search, and generated git
    conflict-marker style edits, then `git diff`. Issues with no traceback were skipped.

**Transferable here:**
- reproduction tests built from related-test context (imports and skeletons);
- content-anchored edits;
- execution-based filtering compared against an unpatched baseline;
- build indexes once and run tests with timeouts;
- traceback-to-location mapping.

**Not transferable:** skipping, and anything that assumed 8-12 minutes per issue.

---

## 4. 2026 papers on harness design for weak models

- **"An Empirical Study of Harness Design for Coding Agents"** ([arXiv 2609.20804](https://arxiv.org/abs/2609.20804), 17 Sep 2026).
  176 configurations, 4 models, SWE-bench Verified and Terminal-Bench 2.1, 300-step cap, tool output truncated at 24k
  characters, stuck detection (a reminder after 5 identical calls, termination after 8 failing ones).
  Results for Nemotron-3 30B (Table 3, pdf lines 357-380):
  - At 32k, success is 9.40% with no context management (T0), 20.60% with elision (T1), 23.80% with summarization (T3), and 21.20% with the staged T4.
  - The model-averaged T0 overflow rate at 32k is 78.7%. All managed tiers have zero overflows.
  - At 128k with T4, success is 25.2%. Without planning it is 13.60%. Bash-only is 10.20%.

  For weak models, planning and explicit tools are accuracy scaffolds. Recall tools were rarely used and gained nothing
  (0.54 calls per task at 32k).
  **For us:** our 32k window is exactly the regime where context management matters most. We cannot trim history
  programmatically (S1), so the equivalent is: stages with `include_contents: none` (already present), tool outputs
  kept small, and a plan re-injected every turn via `{plan}` (already present, S2).
- **AIDE²** ([arXiv 2609.26457](https://arxiv.org/abs/2609.26457), 22 Sep 2026). Across 8 days, 99 rewrite proposals and 7
  accepted improvements, the agent optimized its own code. The discovered mechanisms (pdf lines 320-340, 543-600) include:
  - "demands a root-cause diagnosis before any fix";
  - "compresses log spam before reading it";
  - forking the champion to escape plateaus;
  - bandit selection over draft strategies;
  - bounded, role-specific prompts that read a compact summary rather than the full history, making prompts 7-50x smaller;
  - a failure memory that injects up to 3 recurring error signatures when the bug rate is at least 15%.

  Reward hacking fell from 55% to 32%.
  **For us:** each of these maps onto a prompt or script change (T2, T7, T8). The paper is also the framing for our
  budget-constrained ablation loop.
- **Pre-Action Verification** ([arXiv 2609.11957](https://arxiv.org/abs/2609.11957), Aug 2026).
  - Location-anchored edits fail silently: line-number edits corrupt 99.1% of files after a one-line shift, and edits
    addressed by function name hit the wrong function 12.7% of the time.
  - Content-anchored edits (search/replace, unified diff) fail cleanly.
  - An anchor-and-verify applier (exact match, then whitespace-normalized, then fuzzy top-2 with a margin, refusing when ambiguous)
    had 1 silent misapplication in 8,320 trials (0.01%).

  **For us:** `helpers_v9/replace.py` is purely line-range (S8). After any earlier edit in the same file, a stale line
  number silently overwrites the wrong lines. The `py_compile` revert catches only syntax errors.
- **Coherence Collapse** ([arXiv 2603.24631](https://arxiv.org/abs/2603.24631), AWS).
  - 60-69% of failures by capable models reach and edit the correct functions yet still produce wrong patches.
  - In 5 cases a bit-identical gold patch appeared mid-trajectory and was later destroyed. An edit-commit checkpoint recovered all 5.
  - A consensus variant gave +3.0 points pass@1 on GPT-5 (p=0.08, directional).
- **CoHarden** and **TestPrune** (2.11, 2.12).
- **BATS / BAGEN** (2.15), **Second Thought** (2.14), and **Limits of long context** (2.17).
- **Lita** ([arXiv 2509.25873](https://arxiv.org/abs/2509.25873)). On Verified, GPT-4.1-mini scores 26.4 with Lita against 11.8
  with terminal-only Lita-mini; GPT-4.1 scores 35.6 against 19.6. String replacement beats diff editing "especially for smaller models".
- **Harness Engineering, 11 systems** ([arXiv 2609.00006](https://arxiv.org/abs/2609.00006)). No production harness retrieves
  code with embeddings. All use ripgrep, tree-sitter, glob and similar tools. That supports deterministic stdlib retrieval in skills.
- **Capability ceiling.** Gemma 4 31B IT scores 53.92% on SWE-bench Verified per [Vals AI](https://www.vals.ai/models/google_gemma-4-31b-it)
  (evaluated 9 Apr 2026; harness, budget and precision not stated, so partly UNVERIFIED). The model card lists
  LiveCodeBench v6 at 80.0% and recommends temperature 1.0, top_p 0.95, top_k 64 ([HF card](https://huggingface.co/google/gemma-4-31B-it)).
  With a generous harness the model is several times stronger than our 0.12. The gap is budget and harness, not raw capability.

---

## 5. What to stop considering (constraints, each with its reason)

| Technique | Published gain | Why not here |
|---|---|---|
| Trained verifiers (SWE-Gym ORM, R2E-Gym hybrid, DeepSWE, Skywork) | +9 to +17 points at 8-26 rollouts | Needs a trained model (adapters are wiped by the scorer's vLLM) and 8-26 full rollouts |
| RL agents (SWE-RL, DeepSWE, Kimi-Dev RL) | 36.2 to 41.0; 42.2 | Training compute; the fixed model is the base Gemma |
| MCTS (SWE-Search) | +23% relative | Up to 100 iterations per issue |
| 40-500 sample Agentless pipelines | 29 to 41% | 20-500x our decode budget |
| Execution-free judging by the same model | R2E: patch-only EF verifier 37.6 against 42.8 with trajectory | Our Jev probe: pairwise 0.61 within a task, lost to the shortest patch; a same-model judge is weaker still |
| Skipping low-confidence tasks (Konwinski) | decisive under a penalty | No penalty here: always submit |
| Longer thinking or reasoning mode | negative (overthinking; Konwinski; DeepSWE) | Already off; keep off |
| Bash-only action space | -15.0 points (30B), -14.6 (GPT-4.1-mini) | Keep explicit tools |
| Raising the per-task time cap | none | The 12-hour ceiling is already hit at about 5.2 min per hidden task (sub3 10.4 h for about 120 tasks) |
| KGCompass issue/PR graph; embeddings | +50.8% relative (Claude 4) | No issue/PR history offline; no embeddings runtime in stdlib |
| Logprob-guided search (EGSS) | "5-10%" across models; Kimi-K2 63.2 to 72.2 | ADK YAML exposes no logprobs; ensembles of 4-8 |

---

## 6. Ranked top 12 by expected gain per minute of the L4 budget in THIS setting

How the estimates were made:
- Gains are per ~60 hidden tasks at our current level of about 7-9 solved. Each estimate combines the literature delta,
  scaled down for a weaker model, with our own race-1 and diagnosis numbers.
- They are not additive, and they are well inside single-run noise (±3 tasks on 51). Each needs a paired run with a
  pre-stated pass condition.
- "Added L4 time" is fixer time given up per task; negative means the change saves time. "Gain per minute" uses a
  0.25-minute floor, because every change costs a few calls.

| Rank | Technique | Literature evidence (measured) | Our-setting evidence | Added L4 time/task | Here? | Est. tasks /60 (range) | Gain/min | Confidence |
|---|---|---|---|---|---|---|---|---|
| 1 | **T1. Content-anchored, syntax-gated edits.** Make `edit_file` the only editor, or give `replace.py` a required anchor (`--expect-first "<line text>"`, whitespace-normalized) and refuse on mismatch. Keep the `py_compile` auto-revert on every edit path, and print the edited region after each edit | SWE-agent lint guard +3.0 points; after one failed edit, eventual success drops from 90.5% to 57.2%. Line-number edits corrupt 99.1% of files after a 1-line shift; anchor-and-verify 0.01% silent. Lita and Konwinski: string replacement beats diffs for weaker models | Diagnosis: edit-tool failure in 5/39 never-solved. `replace.py` is line-range only (S8). Race 1: the arms with the edit helper were mixed (eog 21, eg 16, eo 14 against c 15, og 14) | about 0 (saves retries) | Y | +1.0 (0.5-2) | ≥4 | medium |
| 2 | **T2. Context and output hygiene within 32k.** Every helper prints at most about 1,500 characters: head and tail truncation, ANSI stripped, repeated lines collapsed, "N more lines in $TMPDIR/swe/last.log". Summarized search (files and counts), a skeleton view before full reads, and bounded stage prompts passing only `{plan}`/`{fix_notes}` | At 32k a 30B model goes from 9.4% (T0) to 20.6-23.8% (managed), and the T0 overflow rate is 78.7%. Keeping recent observations matches summarization at half the cost. AIDE² bounded prompts are 7-50x smaller. Successful trajectories stay under 20-30k tokens. Summarized search +6 points over iterative; skeleton +4.7 points of localization at a fraction of the tokens | 13 context overflows in the diagnosis. No callbacks, so this is the only lever (S1) | negative (less prefill) | Y | +1.0 (0.5-2) | ≥4 | medium |
| 3 | **T3. Checkpoint when green, then a time-boxed commit.** `checkpoint.py save` whenever the reproduction test or related tests pass (stores the diff and the pass count). Poll the free `get_budget` about every 10 turns. With about 45 s left, or after any later edit that breaks green, restore the best checkpoint *into /workspace*, run the guard (T4) and submit | Coherence Collapse: 5/5 gold-then-destroyed cases recovered; +3.0 points directional. SWE-agent: 93% of resolved runs submitted before the budget ran out. BAGEN: early stop saves 28-64% of tokens on failing runs. BATS: budget tracker -31% cost at equal accuracy | 18 session timeouts in the diagnosis. The fallback patch is the live `/workspace` diff at the cap (S6). Resolved runs finish fast (median 71-91 s on H100), unresolved runs slowly (p90 228-319 s) | about +5 s | Y | +1.0 (0-2) | ≥4 | medium |
| 4 | **T4. Always-execute, fail-open verify-and-guard stage** before `submit_patch`. Revert any edits to test, conftest or pytest config files, and delete untracked scratch files from `/workspace`. Run `py_compile` on edited files, then `gate.py` (related tests, original against edited), then the reproduction test if one exists. Never block submission: if checks fail, submit the best checkpoint or the current diff | Agentless: +regression 77 to 81, +reproduction 81 to 96 fixes on 300. SWE-Fixer pass-to-pass filter 30.2 to 32.8. TestPrune +8-12.9% relative | 78/155 failing runs never ran pytest. 4 rescored runs failed with "Failed to apply test_patch" after a test-file edit. Empty patches: 9 (v4) and 4 (v9_eog) of 51. `git add -N .` pulls scratch files into the patch (S6) | +15-40 s | Y | +1.5 (0.5-2.5) | about 3 | medium-high |
| 5 | **T5. Reproduction test built from related-test context.** `testctx.py` prints imports, fixtures and the skeleton of the best test file, plus one example test. The TestWriter writes `$TMPDIR/swe/repro_test.py` and confirms it fails on the original code. Run it as a **ParallelAgent branch beside the locator or fixer** if L4 batching allows, else as the fixer's first action. Use it in T3 and T4 | Konwinski 1st place's main change over Agentless: small models get imports and classes wrong without context. Otter reaches 31-37% fail-to-pass tests. TestPrune +6-9% relative reproduction rate. CoHarden test-first +9.6 points. Camaro: few-shot good tests "significantly boosted" results | Hidden spec, wrong semantics and underspecified issues account for 22/39 never-solved tasks. A good test helps only where the issue text pins down the behaviour. Parallel branches overlap decode but block during tools (S4). Only the final stage may submit (S5) | +10-20 s in parallel (UNVERIFIED); +45-80 s serial | P | +1.0 (0-2) | about 2.5 (parallel), about 1 (serial) | low-medium |
| 6 | **T6. Repeat and loop guard in helpers.** `run.py` hashes each command and its output. On the 3rd identical pair it prints "UNCHANGED: same command, same output N times; change approach". Use a bounded `LoopAgent` (`max_iterations` 2-3) for the fixer-verifier cycle rather than one open loop | 2609.20804 harness: reminder after 5 identical calls, stop after 8. SWE-Search: flexible transitions produce infinite loops. Rival pilkwang: 55 identical malformed `read_file` calls until context death | sweep1: 17-25 exact-repeat calls out of about 45 per task. Only script-routed commands can be intercepted (S1) | about 0 | Y | +0.5 (0-1) | 2 | medium |
| 7 | **T7. Serial restart with failure memory instead of thrashing.** If nothing is green by about 55-60% of the time budget, end the fixer turn with a STATUS line. A fresh-context second attempt then receives `{fix_notes}` with up to 3 deduplicated error signatures and the rejected approach | AIDE²: fork the champion and failure memory, both accepted improvements. CodeMonkeys: serial and parallel allocation give similar coverage. SWE-agent: failing runs burn the tail of the budget | Race 1: 6 tasks were solved by exactly one of 6 arms and 5 by all. Diversity is real, so a second draw has value | about 0 (reallocates) | P (the model decides when to stop) | +0.5 (0-1.5) | 2 | low |
| 8 | **T8. Root-cause-first plan.** Make the locator emit hypotheses, the target symbol, the expected behaviour and the test command, all re-injected via `{plan}`. Require a one-line root-cause statement before the first edit | 2609.20804: planning takes the 30B model from 13.6 to 25.2 points at 128k. AIDE² improvement #6 "demands a root-cause diagnosis before any fix" | Already partly in v4 (S2): the marginal gain is small. Wrong semantics account for 7/39 | about +5 s | Y | +0.3 (0-1) | 1.2 | medium |
| 9 | **T9. K=2 isolated candidates plus execution-based selection.** A ParallelAgent of 2 fixers, each editing its own copy under `$TMPDIR/wK` with anchored scripts. A selector runs the reproduction test and related tests in each copy, scores with Kimi-Dev `S_i`, breaks ties by the shortest normalized diff, copies the winner into `/workspace`, then T4 | Kimi-Dev 1x1 48.0 to 40x40 60.4; 3x3 beats 40-patch majority. Agentless 4 locations x 10 gives 32.0 against 29.3 greedy location. CodeMonkeys closes half the random-to-oracle gap and breaks ties by shorter diff | Race 1 oracle: best single arm 21/51, best pair 24/51, all 6 arms 27/51. Shortest non-empty patch across 6 arms: 22/51. Random pick of v4 or v9_eog: 19.5 | +0.5 to +2.5 min effective, depending on L4 batch scaling (UNVERIFIED) | P (built-in `edit_file` works only in `/workspace`; calls split 2 ways) | +1.5 (-1 to +3) | about 1 | low |
| 10 | **T10. Traceback-to-location mapping and SBFL from the reproduction test.** A regex maps traceback frames to repo files and lines. If a failing reproduction test exists, trace executed functions with `sys.settrace` and rank them | Konwinski 5th place: traceback mapping was the key to its search. ACR with SBFL: 19 to 22% at +55 s. PatchPilot localizes via reproduction-test coverage | Wrong location in only 2/39. `locate.py` R@3 0.55-0.77 | +5-30 s | Y | +0.3 (0-1) | about 1 | medium |
| 11 | **T11. TestPrune-style regression subset for `gate.py`.** Select tests whose execution covers the edited functions (trace once on the original), instead of the top 3 files by name-grep. Run only those node ids | TestPrune +8-12.9% relative resolution; overhead $0.02-0.05 | `gate.py:17-26` uses name-grep, top 3 whole files, up to 60 s. Could cut gate time and false alarms | ±10 s | Y | +0.3 (0-1) | about 1 | low |
| 12 | **T12. Normalized majority or medoid vote among 3 or more candidates.** `ast.unparse`-normalized diffs, then majority, else `difflib` medoid. Use only if T9 proves K≥3 affordable | Agentless: majority alone 25.67%. Konwinski medoid rescued an LB of -1. Co-PatcheR: majority best with 60 candidates. Trae: prune before voting | Only meaningful at K≥3, which our budget probably forbids | 0 beyond T9 | Y (code) / P (budget) | +0.3 conditional | <1 | low |

**Suggested order of work:**
1. T1, T2, T4 and T6: pure harness hygiene, one bundle, paired race against v9_eog.
2. T3 and T7: time management.
3. Measure L4 throughput at 1, 2 and 3 concurrent streams.
4. Only then decide between T5-parallel and T9.

T8, T10 and T11 are small follow-ups.

---

## 7. Our own numbers used above (reproducible)

```
# race1 durations and unions (eval/race1/runs/*/task_results.jsonl)
r_v4 18/51, mean 111.2 s; r_v9_c 15, 116.6 s; r_v9_eo 14, 126.1 s; r_v9_eg 16, 133.3 s; r_v9_og 14, 141.7 s; r_v9_eog 21, 135.3 s
best pair union 24 (v9_c + v9_eog); all-6 union 27; shortest-non-empty-patch pick over 6 arms 22
solved-by-k histogram {0:24, 1:6, 2:1, 3:5, 4:5, 5:5, 6:5}
resolved median / p90 s: v4 71/128, v9_eog 91/166, v9_eg 74/138; unresolved median / p90: v4 112/228, v9_eog 124/319, v9_eg 130/306
median s per tool call: H100 race1 v4 2.48, v9_eog 2.58; Kaggle L4 e74_v3 4.15 (different bundle; ratio UNVERIFIED)
```

The first three lines are from an inline Python script over `task_results.jsonl`, reading the fields `resolved`,
`agent_patch_size`, `duration_seconds` and `tool_calls`. The last line uses `secs/calls` from `eval/kaggle/e74_v3/results.jsonl`.

---

## 8. Open questions (measure before building T5-parallel or T9)

1. **Aggregate decode throughput on 4x L4 (TP=4, 31B W4A16, vLLM 0.19.1) at 1, 2 and 3 concurrent streams with 8-20k-token
   prompts.** If it is below about 1.6x at 2 streams, T9 is net negative under the binding 5-minute cap and T5 must stay serial.
2. **Tool-blocking fraction.** Under a ParallelAgent, how much of each branch's wall time is frozen by the other branch's
   sync tool calls (S4)? This decides whether test-running branches can overlap at all.
3. **Hidden-set test runtime.** sub3's roughly 5.2 min per task suggests hidden repos run slower tests. The gate and
   reproduction timeouts (T4, T5) should be set from the pod's median test runtime, capped at about 20 s per run.
4. **Same-bundle L4 against H100 per-call time**, to convert pod timings into Kaggle timings.
5. **Does `edit_file`'s regex tier ever misapply silently?** A quick adversarial check in the style of 2609.11957 would settle it.
6. **The OpenAI SWE-bench Verified annotation numbers** (38.3% underspecified, 61.1% overly specific tests, 68.3%
   filtered) came via search. The page returned 403 to direct fetch (UNVERIFIED). They suggest many of our "hidden spec" failures are unwinnable by any harness.

---

## References (all opened for this review)

- SWE-agent: https://arxiv.org/abs/2405.15793
- Agentless: https://arxiv.org/abs/2407.01489
- AutoCodeRover: https://arxiv.org/abs/2404.05427
- OpenHands: https://arxiv.org/abs/2407.16741
- Moatless Tools: https://github.com/aorwall/moatless-tools
- SWE-Search: https://arxiv.org/abs/2410.20285
- SWE-smith: https://arxiv.org/abs/2504.21798
- SWE-Gym: https://arxiv.org/abs/2412.21139
- R2E-Gym: https://arxiv.org/abs/2504.07164
- DeepSWE: https://www.together.ai/blog/deepswe
- Kimi-Dev: https://arxiv.org/abs/2509.23045
- SWE-RL: https://arxiv.org/abs/2502.18449
- CodeMonkeys: https://arxiv.org/abs/2501.14723
- Trae Agent: https://arxiv.org/abs/2507.23370
- Co-PatcheR: https://arxiv.org/abs/2505.18955
- Satori-SWE: https://arxiv.org/abs/2505.23604
- SWE-Fixer: https://arxiv.org/abs/2501.05040
- PatchPilot: https://arxiv.org/abs/2502.02747
- Skywork-SWE: https://arxiv.org/abs/2506.19290
- LocAgent: https://arxiv.org/abs/2503.09089
- CoSIL: https://arxiv.org/abs/2503.22424
- KGCompass: https://arxiv.org/abs/2503.21710
- Otter: https://arxiv.org/abs/2502.05368
- SWT-Bench: https://arxiv.org/abs/2406.12952
- SWE-Tester: https://arxiv.org/abs/2601.13713
- CoHarden: https://arxiv.org/abs/2607.19843
- Dynamic cogeneration: https://arxiv.org/abs/2601.19066
- TestPrune ("Can Old Tests Do New Tricks"): https://arxiv.org/abs/2510.18270
- Are Solved Issues Really Solved: https://arxiv.org/abs/2503.15223
- Harness design study: https://arxiv.org/abs/2609.20804
- AIDE²: https://arxiv.org/abs/2609.26457
- Pre-Action Verification: https://arxiv.org/abs/2609.11957
- Coherence Collapse: https://arxiv.org/abs/2603.24631
- Complexity Trap: https://arxiv.org/abs/2508.21433
- Limits of long-context bug fixing: https://arxiv.org/abs/2602.16069
- Danger of Overthinking: https://arxiv.org/abs/2502.08235
- BATS: https://arxiv.org/abs/2511.17006
- BAGEN: https://arxiv.org/abs/2606.00198
- Second Thought: https://arxiv.org/abs/2608.13667
- EGSS: https://arxiv.org/abs/2602.05242
- Scaling test-time compute for agents: https://arxiv.org/abs/2506.12928
- Lita: https://arxiv.org/abs/2509.25873
- Harness Engineering (11 systems): https://arxiv.org/abs/2609.00006
- Konwinski Prize:
  - overview: https://www.kaggle.com/competitions/konwinski-prize
  - 1st place: https://www.kaggle.com/competitions/konwinski-prize/writeups/eduardo-rocha-de-andrade-1st-place-solution-write-
  - public 2nd place: https://www.kaggle.com/competitions/konwinski-prize/writeups/camaro-public-2nd-place-solution
  - discussion topics 568799, 597207, 596181, 596375, 590920: https://www.kaggle.com/competitions/konwinski-prize/discussion/<id>
- Gemma 4 31B:
  - Vals AI: https://www.vals.ai/models/google_gemma-4-31b-it
  - model card: https://huggingface.co/google/gemma-4-31B-it
