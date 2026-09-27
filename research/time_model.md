# Time and throughput model for the 12 h scoring run (v10 planning)

Written 2026-09-27. Read-only analysis; nothing was run on Kaggle or a pod. All numbers below come from
files in this repo, the installed harness source, or a public competitor notebook, and each one names its source.
Anything not measured by us is marked UNVERIFIED.

Analysis scripts (scratchpad, re-runnable in seconds):
`/private/tmp/claude-501/-Users-carson-Projects/654244a3-b38c-45a0-96af-d7e5f0aac6ce/scratchpad/tm/{extract.py,analyze.py,project.py}`
(outputs `analyze.out`, `project.out` beside them).

## 0. Answers in one screen

| Question | Answer | Evidence |
|---|---|---|
| Decode speed, 4x L4 TP4, 1 stream | **35-36 tok/s at <8k context, 33 tok/s at 12-16k** (27.6-29.9 ms/token) | 6,730 LLM calls in Kaggle L4 runs e74_v2 + e74_v3 (sect. 2) |
| Prefill speed (uncached tokens) | **~1,400-1,700 tok/s** (0.65 ms/token binned; 0.92 ms/token in the joint regression) | fresh stage-start calls, sect. 2 |
| Fixed cost per LLM call | **0.085-0.10 s** | regression intercept + residual of tiny calls |
| Per-task overhead outside the agent cap | setup **3.6 s mean** (max 17.6), teardown + patch <1 s, verification **3.7 s median / 11-12 s mean** (hang tail = `timeout_seconds`) | sect. 1 |
| Startup before task 1 | **503-509 s** in our L4 kernels (wheel install 74-77 s + vLLM 383 s); a competitor measured 562 s | kernel logs |
| Where agent time goes on L4 | **91-93 % LLM**, 7-9 % tools; output tokens are ~75 % of LLM time | sect. 3 |
| Safe per-task ceiling for 120 tasks in 12 h | **~320 s all-in per task at 10 % margin**, so `max_time_minutes: 5.0` is the right cap; 5.25 fails at N=130 | sect. 5 |
| Are 2-3 parallel fixer candidates free? | **No, but cheap in decode:** 3 candidates cost ~1.3x (correlated, alpha=0.08) to ~2x (straggler + contention) the wall of one fixer, i.e. **+15 to +60 s per task on L4**; they fit under a 300 s cap only with per-candidate budgets, and there are four hard harness constraints (sect. 4) | sect. 4 |
| Is the H100 race faithful for L4 time? | For solves, yes: projected onto L4, **0 of 105 race-1 solves** would have their last edit after 295 s; L4 is 1.63-1.75x slower than the H100 lanes | sect. 6 |

Two side findings that change v10 more than any timing knob (sect. 7):
1. **In race 1, the helpers were still unreachable in 19-25 of 51 tasks per arm**, because the model never called the
   install step (at least 33 of 40 checked tasks) or called it with malformed arguments. "Race 1 = working helpers" holds for only ~55 % of tasks.
2. **Pod runs never compact context; the scorer (and our L4 kernels) compact at 14,336 tokens.** 49 % of race-1 tasks
   exceeded that threshold, so pod trajectories are not faithful to the scorer's context behaviour in half the tasks.

## 1. The scoring-run clock

### 1.1 Startup (measured on Kaggle 4x L4)
From the notebook logs (`time` field of each stdout line):

| run | "wheelhouse ok" | tasks loaded | "vLLM up" | first task starts | source |
|---|---|---|---|---|---|
| e74_v2 | 77.3 s | 117.5 s | 509.1 s (vLLM 383 s) | 509 s | `eval/kaggle/e74_v2/g4-eval74-v2.log` |
| e74_v3 | 74.0 s | 111.7 s | 503.4 s (vLLM 383 s) | 503 s | `eval/kaggle/e74_v3/g4-eval74-v3.log` |
| competitor busyaprime | 120.17 s install | | 442.14 s engine | 562.31 s | notebook `119-of-129-sound-the-gemma-4-grader-rebuilt` cell 28 (UNVERIFIED, vLLM version differs) |

The ledger's "vLLM TP4 up in ~348 s" (`eval/ledger.md:13`, 3-task smoke) is the fast end; use **600 s** as the planning value.
Our kernels used `gpu_memory_utilization=0.90` and `compaction_interval=15` (`scripts/make_eval_kernel.py:70,95`), while
`data/HARNESS_README.md:165` says the scorer uses **0.80** and `:556` says `compaction_interval = 5`. Speed is unaffected by
gmu; KV capacity is (sect. 4.4).

### 1.2 Per-task overhead (148 L4 tasks, trace timestamps)
The trace clock starts at sandbox creation (`adk_eval_core/tracing/trace.py:96-98`, `swegemma/harness/agent_runner.py:214-215`);
the `task_prompt` event marks the end of container setup, and the harness starts the agent budget only then
(`swegemma/context.py:183-187`; `data/HARNESS_README.md:551`).

| component | e74_v2 | e74_v3 | notes |
|---|---|---|---|
| setup (wheels, snapshot, editable install, test deps, baseline commit) | mean 3.59 s, p90 5.60, max 9.45 | mean 3.66 s, p90 5.57, max 17.56 | outside `max_time_minutes` |
| agent loop | mean 121.8 s, med 113.5 | mean 146.8 s, med 150.6 | capped at 300 s |
| post (teardown + patch + Phase-2 verification) | mean 10.78 s, **med 3.73** | mean 12.32 s, **med 3.76** | tail = verification pytest hangs |
| total `secs` per task | mean 136.1 s | mean 162.8 s | `results.jsonl` |
| run total for 74 tasks | 10,074 s | 12,046 s | log "TOTAL" line |

Verification alone (Kaggle CPU kernels, no agent): gold patches that pass take **median 6.55 s, p90 9.0, max 12.6 s**
(74 tasks, `eval/kaggle/oracle_all/results.jsonl`); rescored agent patches that pass: median 4.45 s, max 11.5 s (100 of 241,
`eval/kaggle/rescore_fair/results.jsonl`). **9 of 241 rescored patches hung until the 180 s timeout**, all unresolved.
The verification pytest uses `config.harness.command_timeout_seconds`, i.e. our `timeout_seconds`
(`swegemma/harness/verification.py:492-503`), in the local harness. Whether the Kaggle metric does the same is UNVERIFIED.

Overshoot past the cap is small: `run_command` clamps each command to the remaining session time with a 5 s floor
(`swegemma/tools/execution.py:26-42`), so a task that hits the cap costs about 300 s + setup + verification
(e.g. e74_v3 `fastapi_14306`: 308.2 s total).

### 1.3 Is verification inside the 12 h?
Two public notebooks state "12 hours for all tasks, sandbox setup included, verification excluded", citing the Evaluation
page and host post 743063 (`gemma-4-the-complete-guide-expanded`, `gemma-4-repair-quality-under-a-fixed-budget`). I could
not render the Kaggle pages (WebFetch returns only the title). **UNVERIFIED**; this report budgets both ways.

### 1.4 The sub3 datapoint (10.4 h)
The orchestrator's figure: sub3 (v4 bundle, 5 min cap) took ~10.4 h for ~120 hidden tasks. The Kaggle API exposes only the
submit time (`2026-09-27 00:01:12`), not the completion time, so I could not re-derive it.

- If all 120 tasks hit the 5 min cap: 600 s startup + 120 x (300 + 3.6 + ~1) s = **10.3 h** (verification excluded) or
  10.6 h (included). That matches 10.4 h almost exactly.
- If hidden tasks behaved like public ones: bootstrap of 120 tasks drawn from e74_v3 per-task `secs` gives
  **5.57 h median (p99 6.25 h)**; v4 projected from race 1 gives 5.32 h.
- So either hidden tasks run about 2x longer than public ones, with most at the cap, or the 10.4 h includes queueing and
  Stage-2 time. The data cannot tell these apart. **Plan for the first case**: it is the only one where exceeding 12 h
  costs the whole score. A rival's 12-minute cap did fail with "Notebook Exceeded Allowed Compute"
  (`gemma-4-walkthrough-first-submission`).

## 2. Per-call cost model on 4x L4 TP4 (the real hardware)

Data: every agent step in `eval/kaggle/e74_v{2,3}/results/traces/*.json` (ATIF v1.7; each step carries a wall timestamp,
`prompt_tokens`, `completion_tokens`). LLM latency = LLM event timestamp minus the previous observation timestamp.
Uncached tokens = `prompt_i - prompt_{i-1} - completion_{i-1}` within a stage (vLLM V1 prefix caching is on by default;
the trace field `cached_tokens` is always 0 and is not reported by the server). A stage change or compaction counts as a full prefill.

**Joint fit, n = 6,730 calls, R^2 = 0.966:**
`latency = 0.102 s + 28.15 ms x output_tokens + 0.921 ms x uncached_prompt_tokens - 0.008 ms x context_tokens`

Binned (more robust):

| quantity | value | n |
|---|---|---|
| decode, calls with <200 new prompt tokens and >=100 output tokens: context 0-4k / 4-8k / 8-12k / 12-16k | **27.6 / 28.1 / 29.3 / 29.9 ms per token** (36.2 / 35.6 / 34.1 / 33.4 tok/s) | 61 / 210 / 264 / 160 |
| single-call decode rate, >=150 output tokens | median 34.7 tok/s, max 37.5 | 403 |
| prefill, fresh stage starts with 2-4k / 4-6k new tokens | 1,557 / 1,706 tok/s (1.99 s / 2.89 s) | 166 / 113 |
| prefill, 9-14k fresh | 1,376 tok/s (only 10 calls) | 10 |
| prefill, in-stage calls with >1,500 new tokens (big tool outputs) | 1,380 tok/s | 504 |
| fixed overhead per call (calls with <100 new tokens) | 0.085 s | |

The ledger's "~2.2 s per tool call" matches e74_v2 (2.32 s of LLM time per call); e74_v3 averaged 3.16 s per call
because its fixer writes longer edits.

**Published / competitor numbers (all consistent with ours):**
- busyaprime, 4x L4: completion throughput **34.1 tok/s at concurrency 1, 243.0 tok/s at concurrency 16**; KV cache
  4.77 GiB/GPU = 87,985 tokens (notebook `119-of-129-sound...` cell 28; UNVERIFIED, their vLLM 0.30.0 vs scorer 0.19.1).
- "Gemma and the Shape of Doubt": median 31.4 tok/s with CUDA graphs vs 12.2 tok/s eager, vLLM 0.19.1 on 4x L4 (interval stats).
- HF discussion: bf16 gemma-4-31B on 4x L4 "max 15 tok/s" (https://huggingface.co/google/gemma-4-31B-it/discussions/102).
- Physics check: int4 weights are ~16-18 GB (`HARNESS_README.md:173`), ~4.5 GB per GPU at ~300 GB/s, so the bandwidth floor
  is ~15 ms per token; we measure 28 ms. The remaining ~13 ms is consistent with 120 PCIe all-reduces per token (60 layers x 2).
  **Decode is latency-bound**, which is why extra concurrent streams are cheap in decode (sect. 4).

**Cheat sheet (L4, one stream):** each output token costs 28.5 ms; each new prompt token 0.65-0.92 ms; each call 0.09 s;
a typical call (38 output tokens, ~400 new) ~1.5 s; the mean call (75 output, ~660 new) ~2.9 s.
A full fresh prefill of 10k tokens takes ~6.5-7.3 s; 25k takes ~16-18 s.

## 3. Where the time goes inside a task (L4)

| | e74_v2 (single agent) | e74_v3 (locate/fix/verify) | source |
|---|---|---|---|
| LLM share of agent time | 92.6 % | 91.3 % | analyze.out |
| tool share | 7.4 % | 8.7 % | |
| LLM calls / task | 48.5 | 42.4 | |
| output tokens / task | 3,003 | 3,847 | |
| uncached prompt tokens / task | 26,350 | 28,242 | |
| max prompt per task (p90) | 15,883 | 16,878 | |

So for e74_v3: 3,847 x 28.5 ms = 110 s of decode, 28k x 0.65-0.92 ms = 18-26 s of prefill, 42 x 0.09 = 4 s of overhead,
~13 s of tools. **Output tokens are the budget.**

Stage split (e74_v3, L4 seconds per task, modelled): fixer 65 s (17.5 calls, 1,922 output tokens), locator 40 s
(14.7 calls, 1,026), verifier 39 s (10.1 calls, 899). Race-1 v9_eog projected: locator 64 s, fixer 58 s, verifier 49 s.

Four measurable time sinks:
1. **Stage-final text replies are 22-24 % of all output tokens** (tool=None steps; average 336 tokens in e74_v3,
   400 in r_v9_eog). About 880 tokens per task, **~25 s per task on L4**.
2. **Runaway replies to the 4,096-token cap.** Every call over 2,048 output tokens in the L4 runs (7 of 6,730) and
   in race 1 r_* (24 of 16,581) was a text-only reply. Each one costs **~117 s on L4, 39 % of the cap.**
   Across the 148 L4 tasks, output beyond 2,048 tokens totalled 409 L4-seconds. No tool call in those runs exceeded 2,048 tokens
   (two did in c_* runs: one edit_file, one run_command).
3. **Command hangs.** In the L4 runs, 99 % of `run_command` calls take <5 s (3,250 of 3,440 under 1 s), but **4 calls hit the 180 s
   timeout, and those 4 are 47 % of all command time**; 4 of 148 tasks lost 60 % of their budget to one command.
   The H100 race shows the same pattern (5 of 306 tasks, 51 % of command time).
4. **Compaction.** The L4 kernels compacted 154 times in 85 of 148 tasks (prompt falls from ~14.4k to 3-5k tokens).
   The call after a compaction costs a median 5.6 s extra (9.0 s total), about 5.6 s per task on average.
   Pod runs never compact (sect. 7.2).

## 4. Batching and within-task parallel candidates

### 4.1 What was measured
- **No L4 batching measurement exists.** `kernels/g4-batch-probe` was written but never pushed: `kaggle kernels status
  carsonrodrigues/g4-batch-probe` returns 404, and there is no `batch_probe.json` anywhere on disk.
- **H100, TP1, two concurrent tasks per server (race 1).** Using absolute timestamps, each decode-dominated call was classed as
  alone (<10 % overlap with the other task's LLM calls) or overlapped (>90 %). Per-stream decode, controlled for context:

| context | alone ms/token (n) | overlapped ms/token (n) | slowdown |
|---|---|---|---|
| 0-6k | 13.2 (247) | 16.0 (692) | 1.22x |
| 6-10k | 14.3 (317) | 16.3 (884) | 1.14x |
| 10-16k | 15.4 (386) | 17.4 (1,074) | 1.13x |
| 16-32k | 17.6 (213) | 19.7 (1,134) | 1.12x |

  Fresh prefill: alone 4,924 tok/s vs overlapped 4,367 tok/s. Two streams gave **~1.65-1.8x aggregate throughput** on H100.
- **4x L4, competitor:** 34.1 tok/s at c=1 and 243 tok/s at c=16 means 15.2 tok/s per stream: step time 29 ms rises to 66 ms,
  about **+8.5 % per extra stream** (UNVERIFIED; includes their prefill mix).

### 4.2 Model for k parallel fixers on L4
`wall_k = calls x 0.085 + out x 28.5 ms x (1 + alpha(k-1)) + sum of all candidates' uncached prefill x 0.65 ms (prefill is compute-bound and serialises; the shared prefix is cached once) + sum of all candidates' tool time (serialised, see 4.3)`,
with alpha = 0.08 (L4 competitor) to 0.20 (H100 measured, worst bin). Inputs are v9_eog's fixer stage (16.8 calls, 1,779 output
tokens, 7.5k new prompt tokens; 57.7 s alone on L4):

| k | alpha=0.08 | alpha=0.20 |
|---|---|---|
| 1 | 57.7 s | 57.7 s |
| 2 | 65.1 s (1.13x, +7 s) | 71.2 s (1.23x, +14 s) |
| 3 | 72.5 s (1.26x, +15 s) | 84.6 s (1.47x, +27 s) |
| 4 | 79.9 s (1.38x, +22 s) | 98.1 s (1.70x, +40 s) |

That table assumes identical candidates. A `ParallelAgent` waits for **every** branch (`google/adk/agents/parallel_agent.py:51-86`,
TaskGroup), so wall time is set by the slowest candidate. Sampling fixer-stage lengths across tasks gives E[max of 3] = 98 s
(v9_eog) to 127 s (e74_v3), against a single-candidate mean of 58-68 s. Real candidates on the same task are correlated, so the truth
lies between the two tables: **k=3 costs ~1.3x to ~2x one fixer, +15 to +60 s per task on L4.** A per-candidate budget of about 60 s
brings E[max of 3] down to ~55 s before contention, about the same wall as today's single uncapped fixer.

On public-like tasks, v9_eog is projected at 171 s mean agent time on L4 (sect. 6). Adding 3 fixers gives ~186-231 s, and the number of
tasks at the cap rises from 3/51 to ~6-7/51 (+30 s and +45 s scenarios in the projection). On hidden tasks, if they already run to
the cap (sect. 1.4), parallel candidates do not add wall time. They replace sequential work and give **~2.2-2.7x more decode per
second** within the same 300 s. That is the only lever that increases the work done per task under a fixed cap.

### 4.3 Four harness constraints that decide whether parallel candidates work (verified in source)
1. **`run_command` blocks the event loop.** It is a plain `def` (`swegemma/tools/execution.py:16,131`). ADK calls sync tools
   directly on the loop (`google/adk/tools/function_tool.py:231-238`) unless `RunConfig.tool_thread_pool_config` is set
   (`google/adk/flows/llm_flows/functions.py:973-984`). The harness builds `RunConfig(max_llm_calls=...)` without it
   (`swegemma/harness/agent_runner.py:516`). So while one branch runs pytest, other branches cannot dispatch LLM requests;
   requests already in flight keep generating on the server. Tool time adds across branches.
   `run_skill_script` is async (`google/adk/tools/skill_toolset.py:494`, `asyncio.to_thread`), so heavy test runs in parallel
   branches should go through a skill script, not `run_command`.
2. **Budgets are per task, not per branch.** `tool_calls_used` and `llm_calls_used` live on the single `SwegemmaContext`,
   and `max_llm_calls` is global. Three candidates share the 70-call and 150-turn budget. There is no declarative per-sub-agent
   call cap, so per-candidate limits come only from prompts, `get_status`, and helper-enforced deadlines.
3. **One sandbox, one `/workspace`.** Branches edit the same tree. Candidates need isolated copies (for example a git worktree under
   `$TMPDIR` edited through `replace.py --root`). `read_file`/`edit_file` reject paths outside `/workspace` ("Path traversal detected",
   race-1 log `r_v9_eog/logs/fastapi_11194.log`). The winner must be written back to `/workspace` well before the cap: at timeout
   the harness grades only the `/workspace` diff (`HARNESS_README.md` sect. 8.1).
4. **KV capacity at the scorer's gmu 0.80 is not measured.** busyaprime reports 87,985 tokens (gmu unknown). Gemma-4-31B
   (`google/gemma-4-31b-it` config: 10 full-attention layers x 4 KV heads x 512 dim, 50 sliding layers x 16 x 256, window 1024)
   costs ~80 KiB per token on full layers plus ~0.8 GiB fixed per sequence for the sliding window, if vLLM frees out-of-window blocks.
   Compaction at 14,336 tokens keeps each stream near 16k or below. **3 streams fit (~48k tokens); 5 streams are at risk of preemption.**
   The move from gmu 0.90 to 0.80 could roughly halve the free KV: UNVERIFIED.

## 5. The 12 h budget: what cap is safe

Worst case, every task at the cap, 600 s startup, 3.6 s setup, plus verification (11 s mean if it counts, ~1 s if not):

| `max_time_minutes` | N=120, verify counted | N=120, verify excluded | N=130, verify counted |
|---|---|---|---|
| 4.5 | 9.63 h (+2.37 h) | ~9.3 h | 10.42 h (+1.58 h) |
| **5.0** | **10.63 h (+1.37 h)** | **10.29 h (+1.71 h)** | **11.50 h (+0.50 h)** |
| 5.25 | 11.13 h (+0.87 h) | ~10.8 h | 12.04 h (**fails**) |
| 5.5 | 11.63 h (+0.37 h) | ~11.3 h | 12.58 h (**fails**) |
| 6.0 | 12.63 h (**fails**) | ~12.3 h (**fails**) | 13.67 h (**fails**) |

(Totals from project.py. 43,200 s = 12 h. The public LB granularity of 0.10/0.12/0.13/0.15 fits 6/7/8/9 of 60, so
N=120 total is plausible but not certain.)

**Safe maximum mean all-in time per task:** (43,200 x 0.9 - 600) / 120 = **319 s** at a 10 % margin. That leaves about 300 s for the agent after
setup and verification. `max_time_minutes` is the only knob that bounds the worst case. `max_tool_calls` and `max_turns` do not
affect 12 h safety, because the wall cap already bounds every task. They only act as loop brakes.

Expected (not worst-case) totals for 120 public-like tasks (bootstrap, project.py): v4 5.32 h; v9_eog 6.08 h; v9_eog with 3 fixers
6.98-7.43 h (p99 7.45-7.87 h).

## 6. Translating H100 pod results to L4

Each race-1 trajectory was re-timed call by call with the L4 model (0.085 s + 28.5 ms/output token + 0.65 ms/new token,
plus the measured tool time) (`project.py`):

| arm | solved | median L4/H100 time ratio | projected L4 agent time, mean / median | tasks projected >300 s | solves whose last edit would land after 295 s on L4 |
|---|---|---|---|---|---|
| r_v4 | 18 | 1.75 | 145 / 124 s | 3/51 | 0 |
| r_v9_c | 15 | 1.72 | 155 / 138 s | 4/51 | 0 |
| r_v9_eg | 16 | 1.73 | 176 / 123 s | 8/51 | 0 |
| r_v9_eo | 14 | 1.74 | 173 / 140 s | 6/51 | 0 |
| r_v9_eog | 21 | 1.72 | 171 / 150 s | 3/51 | 0 |
| r_v9_og | 14 | 1.69 | 178 / 170 s | 5/51 | 0 |
| c_v9_eg / c_v9_eog | 7 / 7 | 1.67 / 1.63 | 136 / 154 s | 2/23 each | 0 |

On real L4 runs, solved tasks made their last edit by median 62-64 s and at most 184 s (v2) or 218 s (v3). Solves are fast, and
failures are what run long. **Rule of thumb: one H100-lane second (TP1, 2 tasks per GPU) equals 1.7 L4 seconds.** A pod run under a
5-minute cap therefore gives each task about 1.7x the thinking time the scorer gives it. That did not change any race-1 solve,
but it will matter for heavier designs (parallel candidates, gates). **For faithful pod runs, set the pod cap to 300/1.7 = ~175 s,
or scale by this ratio.**

## 7. Side findings that affect v10 design

### 7.1 Helpers were missing in ~40 % of race-1 tasks
In each arm, a task counts as helpers-missing when every `run_command` that calls `swe/*.py` returned "can't open file":

| arm | helpers worked | helpers missing | no helper calls |
|---|---|---|---|
| r_v9_c | 26 (8 solved) | 21 (7 solved) | 4 |
| r_v9_eo | 26 (4) | 25 (10) | 0 |
| r_v9_eg | 31 (6) | 20 (10) | 0 |
| r_v9_og | 28 (6) | 23 (8) | 0 |
| r_v9_eog | 32 (7) | 19 (14) | 0 |
| c_v9_eg / c_v9_eog | 9 (1) / 12 (3) | 14 (6) / 11 (4) | 0 |

In r_v9_c and r_v9_eog, at least **33 of the 40 helpers-missing tasks never called `run_skill_script(... install.py)`**. Others
called it with quoted names (`"\"swe-tools\""`, SKILL_NOT_FOUND) or empty arguments. Two consequences:
(a) race-1 lever effects are diluted and confounded, and the helpers-missing tasks solved more often, which is a selection
effect, not a helper effect; (b) the startup fix is cheap. Make installation a forced first stage (a one-tool `LlmAgent` whose only tool is
`run_skill_script`), costing ~2-3 s on L4 (one ~1.5k-token prefill plus ~30 output tokens).

Helper runtimes on the H100 pod CPU (Kaggle CPU UNVERIFIED): locate.py median 0.86 s, p99 1.56 s; run.py 0.07 / 1.03 s;
gate.py 0.05 s median, p90 2.5, p99 6.7, max 65.5 s; check.py 0.05 s; replace.py 0.04 s.
**gate.py's tail is the only helper that needs a hard internal timeout** (suggest 30 s, then report "gate timed out").

### 7.2 Pod runs are unfaithful on context management
The pod CLI builds `EvalConfig` with no `events_compaction_config`, so pod contexts grow up to 28.7k tokens.
**149 of 306 race-1 r_* tasks (49 %) exceeded 14,336 prompt tokens**, the point at which the scorer compacts
(`HARNESS_README.md:553-560`). Compaction costs little time (~5.6 s per task on L4) but destroys context.
v10 should keep each stage under ~14k, and pod runs should enable the scorer's compaction config.

## 8. Recommendations for v10

### eval_config.yaml
```yaml
evaluation:
  max_time_minutes: 5.0     # hard; the only 12 h safety knob. Never above 5.25 (fails at N=130).
  timeout_seconds: 90       # was 180. 99% of commands <5 s; the 180 s hangs are 47% of command time; passing
                            # verifications take <=12.6 s, so 90 keeps a 7x margin if the scorer reuses it for verification.
  max_tool_calls: 120       # single-candidate v10; 160 if 3 parallel fixers (shared counter). Not a time-safety knob.
  max_turns: 220            # LLM calls, shared; >= ~1.6 x tool calls (nudges, text replies, budget-exceeded retries).
```
Caveat on `timeout_seconds`: if a hidden repo has a legitimately slow targeted test (>90 s), the agent's own test run will time out;
90-120 is the defensible range. On the public set no passing verification exceeded 12.6 s.

### Output-token budget (the dominant cost)
- A 300 s L4 task affords about **8,000 output tokens plus ~60 calls with ~30k new prompt tokens**
  (5 + 228 + 20 s, plus ~15 s of tools). Today's designs use 3.0-5.0k output tokens (v9_eog projected: 4.9k tokens, 52 calls, 171 s).
- `max_output_tokens`: **2,048 for locator and verifier, 3,072 for the fixer**. This caps a runaway reply at 58-88 s instead of 117 s.
- Cap stage-final replies at about 120 tokens (fixed FILES/CHANGE/TEST lines). Today they average 336-400 tokens: saves ~15-20 s per task.

### Per-stage time plan on L4 (single stream, 300 s cap)
| stage | calls | output tokens | L4 seconds |
|---|---|---|---|
| 0 install (forced, one tool) | 1 | ~30 | 2-3 |
| locator | <=10 | <=800 | <=45 |
| fixer (1 candidate) or 3 parallel candidates with a ~60 s / ~12-call budget each | <=15 (or 3x12) | <=1,800 each | 60 single / 70-90 wall for 3 |
| gate + select (via run_skill_script so the event loop stays free) | <=8 | <=500 | <=40 |
| verifier + submit | <=6 | <=400 | <=25 |
| reserve for hidden-repo slowness | | | >=60 |
| **total planned** | | | **~230-250** |

The model can see elapsed and remaining time through `get_status` (free) or a helper that stamps a start time. Use it to make the
per-stage budgets bind, because ADK has no per-sub-agent call cap.

### Parallel candidates: go, with conditions
Go for **k=2-3 fixer candidates** only if all of these hold: per-candidate budgets (~60 s), isolated worktrees, the winner written back
to `/workspace` by about 240 s, gates run through `run_skill_script`, and each candidate context under ~14k.
Do not go to k>=4 before the KV cache at gmu 0.80 is measured.

### Measurements that would remove the UNVERIFIED items (all free, one short L4 kernel, when no submission is scoring)
1. Run `kernels/g4-batch-probe` with `gpu_memory_utilization=0.80` (scorer value), and log vLLM's "GPU KV cache size" line.
   Add a tool-call-sized case (~40 output tokens) and a "one stream prefilling 8k while others decode" case. This replaces alpha.
2. Re-run the L4 eval kernel with the README's `compaction_interval=5` and gmu 0.80, to confirm speed and compaction frequency.
3. Confirm with the organisers whether Stage-2 verification counts toward the 12 h. It moves the cap ceiling by only ~0.3 h.

## 9. Open questions
- Does the 10.4 h for sub3 include queueing or Stage-2? It determines whether hidden tasks really run to the cap (sect. 1.4).
- The scorer's real `gpu_memory_utilization` (0.80 in README vs 0.90 in the official getting-started recipe we cloned) and
  `compaction_interval` (5 vs 15).
- Hidden-repo setup and verification times (larger repos could raise the 3.6 s setup and the verification tail).
- Kaggle-CPU runtime of locate.py and gate.py on large private repos (only H100-pod CPU timings exist).
