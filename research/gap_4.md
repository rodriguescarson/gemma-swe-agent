# Gap 4: compaction threshold, the "amnesia" cost, root type, and graph tools

Written 2026-09-28 (IST). Read-only. Nothing was submitted, pushed or started. The only network calls were the
Kaggle CLI `competitions files` listing and a one-file download of `HARNESS_README.md`. Scripts are in
`/private/tmp/claude-501/-Users-carson-Projects/654244a3-b38c-45a0-96af-d7e5f0aac6ce/scratchpad/gap4/`:
`pertask.py` (per-task prompt size, compaction, outcome), `pairs.py` (paired tests), `virtual.py`
(uncompacted-prompt reconstruction), `halluc.py` (tool names against declared tools). Each runs in about a second.

## 0. Decisions

| Question | Decision | Why, in one line |
|---|---|---|
| Pod compaction | **ON.** Use the README values: `EventsCompactionConfig(compaction_interval=5, overlap_size=2, token_threshold=14336, event_retention_size=5)` and `ContextCacheConfig(2048, 1800, 10)`. Also log a per-task "virtual max prompt", the uncompacted size, as the loss bound for a 32k scorer. | The official README has said 14,336 since 2026-09-25 and is unchanged today. The 32,768 figure comes from two misquotes and one rival notebook. In paired data, compaction changes 2 vs 3 outcomes out of 60. |
| Per-stage prompt target | **Speed first, no hard 14k cap.** Two hard guards: (a) no single tool result over about 4k tokens, because compaction cannot stop a one-step jump; (b) a static worst case of 26k or less per stage (test_plan R78), as a hedge in case the scorer uses 32,768. | Compaction's measured cost is about 7 s per event, not solves. 8 of the 21 r_v9_eog solves came from stages above 14,336 tokens, and a hard cap would cut those short. |
| Root agent type | **Keep `SequentialAgent`.** | The crash path in config F4 can only fire before the first in-flow compaction of the whole scoring run, because one config object is shared. That window closed at task #3 in e74_v3. Measured: 0 of 74 on Kaggle L4. |
| Graph tools | **Register them only on stage 1, the one that sees the harness task prompt. Drop them from fixer and verifier. Add a one-line ban in the stage-1 prompt.** | 3 of 3 unknown-tool crashes came from the agent holding the harness prompt. Fixer and verifier made 0 graph calls in 21,479 calls. `search_similar_code` output is unbounded: up to 55,164 chars, +14,027 prompt tokens in one step. |

## 1. What the scorer's threshold is (steps 1 and 2)

**README checked against Kaggle today.** `kaggle competitions files gemma-4-developer-agent` (CLI 2.2.4, run
2026-09-27 ~22:20 UTC, all pages, `--page-size 200`) lists 524 files. Every one has a creationDate of 2026-09-25.
`HARNESS_README.md` is 49,356 bytes, created 2026-09-25 18:36:31 UTC (listing saved at `scratchpad/gap4/files.csv`).
I downloaded it again: sha256 `3d6e57a13234cb4e...bbbb`, byte-identical to `data/HARNESS_README.md`,
`data/raw/HARNESS_README.md` and three older scratchpad copies. **The README has not changed since 2026-09-25**, so
section 7.2 did not need a re-read beyond confirming it.

**What §7.2 says** (`data/HARNESS_README.md:553-563`): the harness configures the `App` "(`scripts/inference.py`)" with
`compaction_interval = 5`, `overlap_size = 2`, `token_threshold = 14,336`, `event_retention_size = 5`, and
`ContextCacheConfig(min_tokens=2,048, ttl_seconds=1,800, cache_intervals=10)`. In the whole README, 32,768 appears only
as `max_model_len` (lines 128, 147, 148, 166, 178, 198, 554). The string `scoring.py` does not appear at all
(grep, 0 hits).

**Where 32,768 comes from.**
- Forum 743456 (2026-09-26 04:45 UTC) says "HARNESS_README §7.2 — EventsCompactionConfig sets token_threshold = 32,768".
  Forum 743752 (2026-09-26 19:39 UTC) says "HARNESS_README §7.2 says `metric/scoring.py` uses
  `EventsCompactionConfig(compaction_interval=15, ..., token_threshold=32768, ...)`" (`scratchpad/forum/dump.json`,
  keys 743456 and 743752). Both posts are later than the 09-25 18:36 README, and neither quote matches it.
- The notebook `gemma-and-the-shape-of-doubt` sets `token_threshold=32768` in **its own** evaluator
  (`scratchpad/nb2/txt/gemma-and-the-shape-of-doubt.txt:1724-1725`, `nb2/out/.../run_gpu_validation.py:524-525`).
- Sources that say 14,336: the host Getting Started notebook, with interval 15
  (`nb2/txt/getting-started-gemma-4-developer-agent.txt:268-275`); graphloc-end-to-end, with interval 5 (`nb2/txt/graphloc-end-to-end-gemma-4-agent-skill.txt:1100`);
  the gemma-4-ast-graph notebook, with interval 15 (`:1148-1150`); and the rishaviitd README mirror (`scratchpad/rivals/rishaviitd_...md:556-558`).
- **Correction to `research/forum.md:95`.** It says "HARNESS_README §7.2 says the scorer uses ... token_threshold=32768".
  That repeats the forum question, not the README.

**Host answers: none.** Every saved fetch shows `commentCount: 0` for both threads, including the newest
(`scratchpad/forum6/all.json`, fetched 2026-09-27 21:55 UTC). A search of all 39 saved threads
(`scratchpad/forum5/msgs.json`) for `compaction|14,?336|32,?768|token_threshold` finds only these two questions.

**Still UNVERIFIED:** the scorer script is private, and I do not have any README version older than 2026-09-25. The
competition data existed from 09-23 (thread 742911), so an earlier README could have said something else. The
documented and only checkable value is 14,336.

## 2. Does compaction cost solves? (step 3)

Kaggle compaction is detected per stage: a call at or above 14,336 tokens followed by a call from the same author
below 70% of it. This reproduces the critique's count: **29 compacted tasks in e74_v3, 56 in e74_v2**, and
154 compaction events in total, which matches `research/time_model.md:152`.

### 2.1 Same bundle, Kaggle (compaction on) against pod (compaction off)

| Pairing | n | Kaggle solved | Pod solved | Kaggle-only | Pod-only | McNemar p |
|---|---|---|---|---|---|---|
| v3: tasks compacted in e74_v3 vs `v3_conc8` (sqlite) | 29 | 3 | 3 | 1 (fastapi_14616) | 1 (rich_2943) | 1.00 |
| v3: tasks not compacted | 45 | 19 | 16 | 6 | 3 | 0.51 |
| v2: tasks compacted in e74_v2 vs `sw1_v2` | 31 | 5 | 6 | 1 (rich_3454) | 2 (rich_2725, rich_3006) | 1.00 |
| v2: compacted on Kaggle **and** at or above 14,336 on the pod | 25 | 2 | 2 | 1 | 1 | 1.00 |
| v2: tasks that overflowed on the pod | 5 | 0 | 0 | 0 | 0 | 1.00 |

Across the 60 compacted same-bundle pairs, compaction wins 2 and loses 3. The paired difference is -1/60, with a
Wald 95% CI of about **-9 to +6 percentage points of the compacted tasks**. That is about -3.5 to +2.2 pp of all
tasks at v3's 39% compaction rate, or up to -5 to +3 pp at the 57% rate across both Kaggle runs. The "3/29 vs 19/45" in H1 reflects task difficulty: without compaction,
the pod solves the same 3 of 29.

Confounds, stated rather than removed: the Kaggle runs used 5 min / 60 calls / 80 turns on L4
(`eval/kaggle/e74_v3/g4-eval74-v3.log:12`). sw1_v2 was a pod dev-47 run with a 6-min cap at concurrency 4
(`eval/ledger.md:12`). v3_conc8's budget and hardware are UNVERIFIED: it exists only as sqlite rows, mean 258.8 s/task.

### 2.2 Cross-bundle: v3 on Kaggle against v4 on the pod (the critique's p_v4 / r_v4 request)

| Pairing | n | e74_v3 | pod | Kaggle-only | Pod-only | p |
|---|---|---|---|---|---|---|
| compacted in e74_v3, vs p_v4 | 29 | 3 | 7 | 1 | 5 | 0.22 |
| not compacted, vs p_v4 | 45 | 19 | 19 | 3 | 3 | 1.00 |
| compacted, vs r_v4 (race 1, faithful budget) | 19 | 1 | 4 | 1 | 4 | 0.38 |
| not compacted, vs r_v4 | 32 | 13 | 14 | 2 | 3 | 1.00 |
| compacted, vs v4_conc8 (sqlite) | 29 | 3 | 3 | 1 | 1 | 1.00 |
| overflowed on p_v4 (7 tasks) | 7 | 2 (fastapi_5077, rich_3454) | 0 | 2 | 0 | 0.50 |
| overflowed on r_v4 (rich_3468, rich_3772) | 2 | 0 | 0 | 0 | 0 | 1.00 |

This comparison leans against compaction: 1 vs 5 and 1 vs 4. It is confounded exactly where compaction acts. p_v4
had 6 min / 110 calls and r_v4 had 150 turns on H100, which is 1.63-1.75x faster than L4
(`research/time_model.md:23`); Kaggle v3 had 60 calls and 80 turns. The effect of long budgets falls on long tasks.
Of the 5 p_v4 pod-only wins, 2 never went long on the pod (rich_3506 at 5,366 max prompt, rich_2943 at 11,186), so
compaction cannot explain them. fastapi_15589 hit the 5-min cap on L4 (307 s, 64 calls). **Upper bound on cross-bundle harm: 3 of 29.**

### 2.3 What compaction measurably does

- **Prevents gradual overflow.** Kaggle L4: 0 `ContextWindowExceeded` and 0 `No LlmAgent` errors in 148 task-runs
  (err tally of `e74_v2`/`e74_v3/results.jsonl`, plus grep of both logs). Pod: **57 overflow task-runs** in 836 across 16
  pod runs (38 of them in v4+). In **55 of 57**, the overflowing stage had already made two or more calls at or above
  14,336, so compaction would have fired first (`pertask.py` data). Summing each task's solve rate in other runs,
  those 57 overflows cost about **10.4 solves**, or 18% of the overflowed runs.
- **Uncompacted reconstruction on Kaggle** (`virtual.py`: add back each compaction's drop). Without compaction,
  **11 of 74 (e74_v3) and 15 of 74 (e74_v2)** trajectories would have reached the 28,672-token ceiling. Of those,
  1 (fastapi_14616) and 3 (fastapi_15589, 14851, 14873) were Kaggle solves. fastapi_14616 is also the lone Kaggle-only
  win in the v3 pair; it was solved in 1 of 12 runs overall. This is the estimated **32k-scenario loss** for those
  bundles. It overstates slightly, because some post-compaction growth is re-reading.
- **Costs time.** The gap between calls across a compaction has a median of 9.5 s (v2, n=98) and 8.3 s (v3, n=56),
  against 1.5 / 1.7 s for ordinary calls. That is about 7 s per event and about 1.04 events per task on L4, or 2-2.5%
  of a 300 s cap. `time_model.md:152-153` measured 5.6 s by another method.
- **Can do nothing about one-step jumps.** Over 48,037 same-stage call pairs, the median prompt growth is 177 tokens,
  p99 is 2,986 and p99.9 is 6,617. There were 3 jumps of 10k or more:
  - +19,387 from one `read_file` of `tests/test_table.py` lines 1-200 (8,881 to 28,268 tokens; `eval/eval3/eval/runs/p_v6/traces/trace_rich_3518.json`).
  - +14,027 twice from `search_similar_code(query='include_router')`, which returned 55,164 chars (`p_v7`, `p_v8` `trace_fastapi_14258.json`).

  Both non-gradual pod overflows (p_v8 and r_v9_eo, rich_3518) were that same read, starting at 10,686 and
  13,904 tokens. Rich test files are full of box-drawing characters. About 10.4k chars of content became about 19k
  tokens, roughly 2 tokens per char. `read_file`'s 10,000-char cap (`HARNESS_README.md` §7.1) therefore does not bound
  tokens. (ADK sends tool results with `ensure_ascii=False`, `google/adk/models/lite_llm.py:546-558`, so the model sees
  raw UTF-8. The `\u` escapes appear only in the trace files.) With compaction at 14,336, the largest safe single step is 28,672 - 14,336 = 14,336 tokens.

### 2.4 Why "amnesia" is total in our stages, and what survives (code-verified, ADK 1.36.1 = scorer's wheel)

- The summarizer formats **only text parts**: `llm_event_summarizer.py:73-81` appends `f'{event.author}: {part.text}'`.
  Function calls and tool results never reach it.
- The compaction event is appended with `author='user'` (`llm_event_summarizer.py:134`). With `include_contents: none`,
  the current turn starts at the latest user or other-agent event (`flows/llm_flows/contents.py:542-582`), and that is
  now the compaction event. The stage then sees its instruction plus the summary. It loses the 5 "retained" raw
  events and the harness task prompt.
- Measured post-compaction prompt medians in e74_v3: locator 1,703 tokens against 3,620 on its first call, fixer
  1,959 against 1,686, verifier 1,488 against 1,704. In e74_v2 (`include_contents: default`) the figures are 4,156
  against 4,060.
- What survives: instruction placeholders. v3, v4 and v9_eog inject `{problem_description}`, `{plan?}` and `{fix_notes?}` (grep of
  `submissions/*/prompts/*.md`). Keep every stage handoff in `output_key` state. As an UNVERIFIED option, one-line
  text findings in a stage would survive compaction, because text is the only thing the summarizer reads.
- **Compaction at stage boundaries.** `_latest_prompt_token_count` reads the last event in the session from any
  author (`apps/compaction.py:156-173`). A stage that ends at or above 14,336 therefore compacts at the next stage's
  first call. This happened in 5 of 74 e74_v3 tasks. It cost about 7.5 s each (gap median 9.3 s against 1.8 s), and
  the next stage lost the previous stage's final message, which the `{plan?}` / `{fix_notes?}` state carries anyway.

## 3. Root agent type (config F4)

- The raise needs `config.summarizer is None` (`apps/compaction.py:223-236`). The in-flow path sets
  `config.summarizer` on first use with the current LlmAgent (`:425-469`, set at `:458`). The same `EventsCompactionConfig` object is
  used by every task's `App`: `swegemma/harness/agent_runner.py:403-414` takes it from the single `EvalConfig`, the host
  notebook builds one `EvalConfig` for all tasks (`getting-started...txt:254-281`), and `runners.py:1429-1430` passes the app's object through.
- Local check with the project venv (ADK 1.36.1): two `App`s built with one config keep the **same object**. The
  workflow-root call raises before any in-flow compaction. After one in-flow compaction on an LlmAgent, the same call
  on a *different* SequentialAgent root does not raise.
- So a SequentialAgent root can only crash on a task before the first in-flow compaction of the whole scoring run,
  and only if that task's invocation ends naturally with its last prompt at or above 14,336. In e74_v3, the first
  in-flow compaction came at task #3 (fastapi_15589), and no task showed the exposure pattern. The incidence is
  0 of 74 on Kaggle L4, and sub3 (Sequential root) scored 0.12 on the real scorer.
- An LlmAgent coordinator would put the harness prompt, which advertises the graph tools, in front of one more
  agent. That is more unknown-tool exposure (section 4) plus an extra LLM hop per transfer. It is not worth it for a
  window that closes in the first few tasks. The nudge restart (config F12, 1-3 of 51 tasks) is a separate and small issue.
- UNVERIFIED: that the private `scripts/inference.py` also builds one config for all tasks. If it builds one per task,
  the exposure is still 0 of 74 in e74_v3.

## 4. Graph tools: registered, dropped, or banned (step 4)

`halluc.py` checked all 984 traced task-runs (48,452 tool calls in 18 runs: 16 pod runs plus e74_v2 and e74_v3) against
each stage's declared tools, including the skill toolset names from `google/adk/tools/skill_toolset.py:97-719`:

| Where | Undeclared calls | Result |
|---|---|---|
| e74_v3 locator (no graph tools declared) | `search_similar_code` x2 (fastapi_14419, rich_4076) | both tasks lost: "Sandbox execution error: Tool 'search_similar_code' not found" |
| e74_v2 single agent | `git_grep` x1 (rich_3676) | task lost |
| every other run (v1, v2 pod, v4, v6, v7, v8, all v9 arms) | 0 | |

- ADK raises `ValueError` for an unknown tool unless an `on_tool_error` callback answers
  (`flows/llm_flows/functions.py:720-735`, `:988-1003`). Submissions cannot declare callbacks (config_space).
- The harness task prompt advertises `search_similar_code`, `get_code_neighbors` and `get_code_subgraph` whenever
  graph data is supplied. That was 74/74 prompts in e74_v3, p_v4, r_v4 and r_v9_eog, and 0/74 in e74_v2 and 0/47 in
  sw1 (graph dir not set). With `include_contents: none`, only stage 1 ever sees that prompt.
- In v4+, graph tools were declared on every stage. The fixer made 0 graph calls in 13,640 calls and the verifier 0
  in 7,839. The locator made 101 in 12,126 (0.8%). `search_similar_code` observations had a median of 84 chars and a
  max of 55,164, and 2 calls added 14,027 tokens each.
- **Resolution of H2 vs config F14:** both are right about different stages. Register the three graph tools only on
  the agent(s) whose context contains the harness prompt: stage 1, plus any agent with `include_contents: default` or
  an LlmAgent root. Drop them elsewhere, which saves 1,966 declaration chars (config_space row 14) on the roughly 64%
  of calls made by fixer and verifier. With vLLM prefix caching on, which time_model assumes, the real saving is
  mostly on each stage's fresh prefill, about 1-1.5 s per task on L4 (UNVERIFIED size). Add a one-line ban in stage 1
  ("do not call search_similar_code / get_code_neighbors / get_code_subgraph"), because their output is unbounded.
  Keep them registered so a slip cannot crash the task. The ban's effect on the 0.8% call rate is UNVERIFIED; count graph calls in the canary.
- Residual risk: a name no registration can cover (`git_grep`) happened 1 time in 984 task-runs.

## 5. Consequences for v10 and the pod runner (not applied: read-only)

1. `scripts/run_eval.py:70-71` calls `swegemma.cli.main`, and that builds `EvalConfig` with no compaction or cache
   config (`swegemma/cli.py:141-160`). Build `EvalConfig` directly with the README values.
   `scripts/make_eval_kernel.py:95` uses interval 15; the README says 5. With 1 invocation per task plus nudges, the
   interval barely matters.
2. Add three per-task KPIs from traces: compaction count, virtual (uncompacted) max prompt, and the largest one-step
   jump. Report "solved" and "solved with virtual-overflow tasks counted as failures" for each arm, so a 32k scorer is
   covered without a separate run.
3. Cap helper output by estimated tokens, not chars. Count non-ASCII as about 2 tokens per char, from the one
   rich_3518 measurement (UNVERIFIED as a general ratio). Steer reads of rich test files through the capped helper
   (`sed -n` ranges) instead of `read_file`.
4. For the current candidate, the stakes are small. r_v9_eog overflowed 0 of 51 on the pod and c_v9_eog 1 of 23, so
   even a 32k scorer would cost about 1.4% x 18% x 120, or roughly 0.3 tasks. Bundles that grow context, like p_v8 with
   11 of 74 overflows, are where the threshold question matters.
5. If harm is still suspected, the only clean test is the **same bundle and budget on the pod, with compaction on vs
   off**. It needs change 1. A worthwhile threshold is a loss of 2 or more tasks out of 51; single-run noise is ±3.

## 6. Numbers quick reference

- Pod solve rate by per-task max prompt (p_v4): below 10k: 10/15; 10-14k: 9/25; 14-20k: 4/18; 20-26k: 2/7; 26k and up: 1/9. For r_v9_eog: 3/9, 10/18, 6/17, 2/7, 0/0.
  Long tasks are hard with or without compaction.
- Kaggle solve rate by compaction count (e74_v3): 0: 19/45; 1: 2/16; 2: 0/5; 3 or more: 1/8. By pairing (section 2.1), this reflects task difficulty.
- Stage maxima at or above 14,336. r_v9_eog: locator 16/51 (median max 11,988), fixer 10/51, verifier 4/50. e74_v3: locator 10/74, fixer 19/71, verifier 8/63.
- Overflow ceiling: 32,768 - 4,096 = 28,672 prompt tokens (`research/own_data.md:142`).
