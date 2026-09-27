# Own-data audit: where the points and the seconds go (input for v10)

Written 2026-09-27. Read-only analysis of every run we have traces for. Nothing on Kaggle or RunPod was touched.

**Data covered (796 run×task rows, 14 runs):**

- Race 1, faithful Kaggle budget (5 min / 70 calls / 150 turns / 180 s, 2 tasks per H100). Arms r_v4, r_v9_c, r_v9_eo, r_v9_eg, r_v9_og and r_v9_eog ran on the 51 arena tasks. c_v9_eg and c_v9_eog ran on the other 23. Path: `eval/race1/runs/*`.
- Fair pod runs p_v4, p_v6, p_v7 and p_v8, on 74 tasks at a looser 6 min / 110 calls / 220 turns / 180 s (`pod/chain_eval3.sh:18-19`). Path: `eval/eval3/eval/runs/*`.
- Kaggle 4×L4 runs e74_v2 and e74_v3, on 74 tasks at 5 min / 60 calls / 80 turns / 180 s, run sequentially. Path: `eval/kaggle/e74_v*`.
- Summary sources: `eval/experiments.sqlite`, `eval/diagnosis*.{md,json}` and `eval/kaggle/rescore_fair/results.jsonl`.

**Scripts** (scratchpad, not in the repo) are in `/private/tmp/claude-501/-Users-carson-Projects/654244a3-b38c-45a0-96af-d7e5f0aac6ce/scratchpad/own/`:

- `extract.py` turns each trace into one row, written to `rows.jsonl`.
- `aggregate.py` builds the tables.
- `regress.py` classifies the test outputs.

**How time was measured.** Every trace step carries `extra.elapsed_s`. I split agent time into two parts:

- **LLM time**: the gap from the previous observation to the tool call.
- **Tool time**: the gap from the tool call to its observation.

Stage attribution uses `extra.author`.

---

## 0. TL;DR, ranked by how many tasks each item explains

1. **"Right file, wrong or partial fix" is the biggest bucket.** It covers 19 of r_v9_eog's 30 losses on the 51 arena tasks, and 16-22 of 51 in every race arm.
   - 13 of those 19 patches have fewer hunks than gold, 9 change less than a third of gold's lines, and 6 skip a gold file entirely.
   - Only 4-7 of 51 unsolved patches per arm break existing tests. The other 70-80% fail only the hidden new tests.
   - So a regression gate can win back only a handful of tasks. What we mostly lose on is patch completeness and spec.
2. **About 15 of the 46 are out of reach from the issue text.** Nine tests expect an exact string or API name that only the test reveals, six issues are underspecified, and four features are too large. No config has ever solved these 19 in 14 runs.
3. **Hitting the time, turn or context cap always scores 0.** 0 solves across 123 capped runs in 14 configs (52 time, 33 turn, 38 context).
   - The main trigger is a **malformed-tool-call death spiral**: the model sends the same broken `edit_file` 60-206 times. It happened in 2-7 of 51 tasks per arm, and none of those tasks was solved.
   - These broken calls never reach our tool budget. ADK rejects them before the budget wrapper (`google/adk/tools/function_tool.py:180-190`), so they burn turns and wall time until the 150-turn or 5-minute cap. In race 1, 19 of the 20 turn-cap endings had 89-141 malformed calls each; the 20th spent 77 calls after the tool-call cap (fastapi_14616 in v9_c).
   - This cost about 3.5 otherwise-solvable tasks per arm. v9_eog lost none this way in race 1; the other five arms lost 2-6 each.
4. **The helper fix only half-shipped.** In every v9 arm the locator skipped `run_skill_script(install.py)` in about 40% of tasks (20-26 of 51). In those tasks every `/tmp/swe/*.py` call still failed with "can't open file". For example, v9_eog had 58 of 66 helper calls failing in its 20 no-install tasks, and 0 failures in the 27 where install worked.
   - So race 1 measured "helpers in about 55% of tasks", not "helpers".
5. **Context overflow is a hard zero and throws away finished work.** 38 runs overflowed across the 14 configs. In every one the patch was discarded: `patch_size` 0, tests never run (exit -1).
   - This happens even when edits had already landed; fastapi_14419 had 11 and rich_3930 had 9. The cause is that the exception path in `swegemma/harness/agent_runner.py:799-801` skips the fallback working-tree diff.
   - What fills the stage context: `read_file` 58%, pytest output 14%, failed-`edit_file` echoes 13%.
6. **The LLM is 90-97% of agent time, and cost is almost all decode.** The fitted per-call cost is 0.39 s + 15 ms per completion token on H100 (conc 2) and 0.99 s + 26.5 ms per token on Kaggle L4 TP4. Prompt length has about zero slope (R² 0.77).
   - Between 18% and 41% of agent time goes to calls that fail: malformed args, failed edits, missing helpers, mangled read paths.
   - 32-44% of calls exactly repeat an earlier call in the same stage.
   - 48 runaway generations of more than 2,048 tokens each cost 30-85 s on H100, which is up to about 110 s on L4.
7. **The hidden set runs about 1.9× longer per task than the public set.** v4 took 10.4 h, about 308 s per task for about 120 tasks. The public set on L4 takes about 163 s per task.
   - On public tasks every solve finishes by 240 s on L4 (e74_v3) and by 167 s on H100 (r_v9_eog). A 6-minute cap added 1 solve out of 26 (p_v4).
   - So hidden tasks are almost certainly saturating the 5-minute cap.
   - **The 12 h limit leaves v10 at most +15% total wall versus v4 (12/10.4).** v9_eog was +22% wall on H100 (135 s vs 111 s) and an estimated +13% of agent time on L4.
8. **Variance is large.** The union of all 14 runs solves 38 of 74; the best single config solves 28.
   - For v9_eog, 8 of the 10 tasks in that gap got a wrong patch (sampling) and 2 ended empty on a cap. In the other arms, the cap spirals and overflows in items 3 and 5 cost about 3.5 tasks per arm.
   - Paired race-1 differences are within noise: v9_eog vs v4 was 5 wins and 2 losses.

---

## 1. Outcome per config

| run | n | solved | empty | time cap | turn cap | calls ≥ cap | ctx overflow | test_patch apply fail | patch touches tests/ |
|---|---|---|---|---|---|---|---|---|---|
| race1/r_v4 | 51 | 18 | 9 | 2 | 1 | 9 | 2 | 0 | 7 |
| race1/r_v9_c | 51 | 15 | 9 | 2 | 5 | 3 | 3 | 1 | 6 |
| race1/r_v9_eo | 51 | 14 | 7 | 2 | 4 | 7 | 1 | 2 | 6 |
| race1/r_v9_eg | 51 | 16 | 15 | 4 | 3 | 5 | 4 | 0 | 4 |
| race1/r_v9_og | 51 | 14 | 9 | 5 | 3 | 3 | 2 | 0 | 6 |
| **race1/r_v9_eog** | 51 | **21** | **4** | 2 | 2 | 4 | **0** | 0 | 7 |
| race1/c_v9_eg | 23 | 7 | 4 | 2 | 0 | 2 | 0 | 1 | 1 |
| race1/c_v9_eog | 23 | 7 | 7 | 2 | 2 | 4 | 1 | 0 | 3 |
| fair/p_v4 (6 min) | 74 | 26 | 13 | 7 | 0 | 1 | 7 | 0 | 11 |
| fair/p_v6 | 74 | 22 | 13 | 3 | 3 | 2 | 5 | 1 | 12 |
| fair/p_v7 | 74 | 24 | 13 | 6 | 0 | 3 | 2 | 0 | 14 |
| fair/p_v8 | 74 | 21 | 16 | 4 | 2 | 1 | 11 | 0 | 16 |
| kaggle/e74_v2 (L4) | 74 | 19 | 23 | 2 | 2 | 5 | 0 | 0 | 3 |
| kaggle/e74_v3 (L4) | 74 | 22 | 14 | 9 | 6 | 11 | 0 | 0 | 8 |

Notes:

- **The 23 "rest" tasks are nearly constant.** Every fair and Kaggle config solves 8 of 23 there; v9_eog solves 7. So on the 74-task set, v9_eog's 21+7=28 compares with about 26 for v4.
- **Environment differences:** 3 fastapi tasks (11194, 13537, 14616) are env-blocked in the fair runs (no python-multipart). The race-1 pod has the pins (`eval/submit_log.txt`: `Pygments==2.20.0 python-multipart==0.0.26`).
- **The Kaggle-env rescore flips 7 pod failures to passes** and never the other way: v4 +1, v6 +3, v7 +2, v8 +1 (`eval/kaggle/rescore_fair/results.jsonl`).
- **fastapi_14851 passes with an empty patch** in the race env (r_v4 and r_v9_eog: `agent_patch_size` 0, exit 0). It is a free point unless the run overflows context (r_v9_c).

### Solve matrix, race 1 (X = solved, e = empty patch)

Of the 51 arena tasks, 24 were solved by no arm, 6 by exactly one arm, and 5 by all 6. The union of the arms is 27 of 51.

- **Solved by v9_eog, not v4 (5):** fastapi_14077, rich_3454, rich_3506, rich_3676, rich_4077.
- **Solved by v4, not v9_eog (2):** fastapi_5077, rich_3521.

---

## 2. Time: what the budget really is

### 2.1 Per-task time distribution (seconds)

| run | wall mean | wall med | wall p90 | wall total (h) | agent mean | agent med | setup+test overhead | LLM share of agent time | wall, solved | wall, unsolved |
|---|---|---|---|---|---|---|---|---|---|---|
| race1/r_v4 | 111.2 | 93.8 | 195.2 | 1.58 | 93.0 | 76.3 | 18.3 | 93% | 76.3 | 130.3 |
| race1/r_v9_c | 116.6 | 97.2 | 227.7 | 1.65 | 99.1 | 85.0 | 17.5 | 92% | 68.1 | 136.8 |
| race1/r_v9_eo | 126.1 | 95.3 | 243.1 | 1.79 | 104.6 | 85.2 | 21.5 | 97% | 79.6 | 143.6 |
| race1/r_v9_eg | 133.3 | 100.5 | 305.4 | 1.89 | 116.2 | 84.6 | 17.1 | 92% | 91.7 | 152.3 |
| race1/r_v9_og | 141.7 | 120.0 | 305.5 | 2.01 | 120.0 | 107.2 | 21.7 | 90% | 88.2 | 162.0 |
| race1/r_v9_eog | 135.3 | 110.4 | 237.6 | 1.92 | 110.7 | 97.8 | 24.7 | 92% | 100.4 | 159.7 |
| fair/p_v4 | 147.3 | 87.9 | 339.1 | 3.03 | 120.2 | 77.5 | 27.0 | 91% | 78.8 | 184.3 |
| kaggle/e74_v2 | 136.1 | 121.7 | 218.2 | 2.80 | 125.4 | 117.7 | 10.8 | 93% | 106.4 | 146.4 |
| kaggle/e74_v3 | 162.8 | 160.2 | 305.1 | 3.35 | 150.5 | 153.6 | 12.3 | 91% | 94.8 | 191.6 |

The "setup+test overhead" column is wall minus agent time. For resolved tasks it is at most 16 s on the pod (median 12.5 s) and at most 4.3 s on Kaggle (median 3.8 s).

**Tool execution is almost free.** On the pod, `run_command` takes 0.03 s at p50, 0.52 s at p90 and 2.1 s at p99. Only 13 of 8,146 race-1 commands ran 20 s or more:

- 9 were bare `python3 repro.py` or `python3 -c` runs on infinite-loop bugs (rich_4006 ×3, rich_3480 ×2, fastapi_14258 ×3, rich_3468 at 66 s); 8 of them hit the 180 s timeout;
- 2 were `curl` on fastapi_13920, with no network available;
- 2 were `gate.py` on requests_6644, 65 s each.

On Kaggle, e74_v3 also lost 180 s twice to `pip install` with no network.

### 2.2 The per-call latency model (least squares over 15.8k calls on the pod and 3.0k on L4)

- H100, conc 2: `secs = 0.39 + 0.003·prompt_k + 0.0151·completion_tokens` (R² 0.77).
- Kaggle 4×L4 TP4 (e74_v3): `secs = 0.99 − 0.023·prompt_k + 0.0265·completion_tokens` (R² 0.77).

So L4 decodes about 1.76× slower per token and adds about 0.6 s of fixed overhead per call. Prompt size does not matter for speed. It matters only for overflow.

The one lever for speed is fewer LLM calls and fewer completion tokens.

Completion tokens per call:

| p50 | p90 | p99 | p99.9 | max |
|---|---|---|---|---|
| 40 | 166 | 731 | 4096 | 4105 |

Out of 33,008 calls, 141 exceed 1,024 tokens and 34 hit the 4,096 cap.

**Runaway generations.** There were 48 generations over 2,048 tokens, listed by task in the scratchpad query. Each cost 57-85 s on H100 and would take about 110 s on L4, which is 37% of the task budget.

- Most are locator plans that ignore "under 250 words": rich_3472, rich_3506, rich_3470 and fastapi_14463.
- The rest are unclosed `<|tool_call>` texts, which trigger the harness nudge.

**Why `max_output_tokens: 4096` hurts twice:**

- It reserves 4,096 of the 32,768 context, so overflow fires at 28,673 prompt tokens (error text in `race1/runs/r_v4/run.out`).
- It lets a single runaway call eat about 110 s on L4.

### 2.3 Solves happen early

Cumulative count of solved tasks by agent time (s):

| run | ≤60 | ≤90 | ≤120 | ≤150 | ≤180 | ≤240 | ≤300 | slowest solve |
|---|---|---|---|---|---|---|---|---|
| r_v4 (H100), 18 solved | 10 | 15 | 17 | 18 | 18 | 18 | 18 | 126 s |
| r_v9_eog (H100), 21 solved | 6 | 14 | 16 | 18 | 21 | 21 | 21 | 167 s |
| e74_v3 (L4), 22 solved | 9 | 13 | 16 | 17 | 20 | 22 | 22 | 232 s |
| p_v4 (6 min cap), 26 solved | 18 | 24 | 24 | 24 | 24 | 24 | 25 | 326 s |

I replayed the race-1 traces through the L4 latency model, which runs about 7% low (139 s vs 150 s actual on e74_v3). By that replay, no public solve by r_v4 or r_v9_eog would pass 300 s on L4.

Estimated L4 agent means are 147 s (r_v4) and 166 s (r_v9_eog). That makes v9_eog +13% of agent time over v4.

**On public tasks, the 5-minute cap removes failures, not solves.**

### 2.4 What the hidden-set 10.4 h implies

- **Startup.** The Kaggle run spends about 500 s before the first task: 74 s wheelhouse, then vLLM "up in 383 s" at t=503 s (`eval/kaggle/e74_v3/g4-eval74-v3.log`).
- **Per-task time.** (37,440 − 500) / ~120 ≈ **308 s per hidden task**. The public set on L4 takes 163 s per task (e74_v3: 12,046 s / 74 tasks), and v4 is about the same by the replay. So hidden tasks take **about 1.9×** as long.
- **Overhead is not the explanation.** Kaggle's per-task setup+verify median is 3.8 s. So 308 s means **nearly every hidden task runs to the 5-minute cap**, plus the occasional 180 s test hang.
- **The alternative (UNVERIFIED).** Hidden repos might instead need far heavier setup or test time. We have no per-task hidden timings.
- **Either way, the budget constraint is simple.** 12 h / 10.4 h = 1.154. **v10's total scoring wall may be at most about 15% more than v4's**, whatever the hidden task count. Keep a margin and target ≤ +8%.
  - If hidden tasks are cap-saturated, a per-call slowdown barely moves wall time.
  - If they are not, v9_eog's +13-22% would put the run at 11.7-12.7 h, which risks **no score at all**.
- **How hangs make it worse.** A task that hits an infinite-loop bug can cost 300 s (agent) + 180 s (hidden-test timeout) + setup. For example, rich_3772 in r_v9_eog took 494 s wall and rich_4006 took 416 s.
  - `timeout_seconds` in `eval_config.yaml` sets both the per-command timeout and the **hidden pytest timeout** (`swegemma/config.py:178-190`, `swegemma/harness/verification.py:498-503`).
- **What changing it would do.** Lowering `timeout_seconds` from 180 to 60 caps each hang at 60 s. Every resolved-task verification in our data took ≤ 16 s, but hidden suites might be slower (UNVERIFIED).

---

## 3. Context window

- **How often it overflows.** Overflow (`ContextWindowExceededError`, prompt ≥ 28,673) hit 0-4 of 51 tasks per race arm, 2-11 of 74 per fair run, and 0 on Kaggle v2/v3. Those Kaggle bundles kept prompts smaller: p90 of the per-task max prompt was 16-17k, versus 20-28k on the pod.
- **Overflow always scores 0 (38 of 38 runs).** The patch is dropped even when edits had been made: fastapi_14419 (11 edits), rich_3930 (9), fastapi_5077 in p_v4 (5), rich_3043 in r_v9_og (5).
  - Cause: the exception reaches the `except Exception` at `agent_runner.py:799`, which skips the fallback `git diff` capture (lines 758-790).
- **Which stage overflows.** Locator 12, fixer 20, verifier 6. Each stage starts fresh (`include_contents: none`), so every overflow is a single stage reading about 25 calls' worth of output.
- **What filled the overflowing stage** (chars, all 38 runs):

| source | chars | share |
|---|---|---|
| read_file | 1.52M | 58% |
| pytest output | 376k | 14% |
| failed edit_file echoes | 350k | 13% |
| python -c output | 71k | |
| search | 69k | |
| search_similar_code | 55k | one call in fastapi_14258 |
| cat/sed/head views | 36k | |
| git diff | 31k | |

- **Why read_file is so heavy:**
  - 23-51% of `read_file` calls have no `end_line`, so they return the default 5-7k-char window. Many of those had the key mangled, for example `"end_line\\\""`.
  - About 5-17% of read chars are exact repeats within the same stage.
  - About 44% of successful reads (r_v9_eog; 37% in r_v4) re-read a file an earlier stage already read. That is the `include_contents: none` tax: about 4.5 extra calls per task.
  - A single untruncated test-file read can be 25 kB (rich_3518, `tests/test_table.py`).
- **Tokens per turn.** Prompts average 8.8-10.8k tokens per call. The per-task max prompt averages 12-18k, with p90 20-28k. Completion averages 74-105 tokens (median 40). There are 38-61 LLM calls per task.

---

## 4. Tool calls and their failures

### 4.1 Per-task means (error rate in brackets)

| run | run_command | read_file | edit_file | write_file | run_skill_script | submit_patch | malformed calls per task |
|---|---|---|---|---|---|---|---|
| r_v4 | 19.6 (34%) | 11.7 (26%) | 13.0 (88%) | 1.4 (26%) | 0.6 (30%) | 46/51 | 6.7 |
| r_v9_c | 19.7 (37%) | 8.8 (11%) | 18.3 (92%) | 1.3 | 0.5 | 40/51 | 13.0 |
| r_v9_eo | 25.8 (34%) | 9.7 (21%) | 17.2 (90%) | 1.1 | 0.6 | 45/51 | 11.9 |
| r_v9_eg | 21.5 (31%) | 9.1 (6%) | 21.7 (93%) | 1.1 | 0.6 | 39/51 | 17.1 |
| r_v9_og | 22.8 (29%) | 10.2 (5%) | 16.9 (88%) | 1.7 | 0.6 | 41/51 | 12.0 |
| r_v9_eog | 28.2 (30%) | 10.3 (16%) | 8.1 (77%) | 1.5 (37%) | 0.6 (12%) | 49/51 | 5.6 |
| p_v4 | 24.7 (35%) | 11.4 (21%) | 13.9 (87%) | 1.5 | 0.6 | 61/74 | 6.8 |
| e74_v3 | 16.9 (34%) | 11.5 (11%) | 9.4 (81%) | 0.5 | 0.6 | 58/74 | 4.9 |

### 4.2 `edit_file` failures by class

| class | r_v4 (n=665 calls) | r_v9_eog (n=411) | p_v4 (n=1030) | e74_v3 (n=698) |
|---|---|---|---|---|
| MALFORMED_ARGS (ADK: `old_string` missing) | 51% | 39% | 49% | 52% |
| old_string not found | 35% | 35% | 35% | 28% |
| not unique | 0% | 2% | 3% | 1% |
| identical | 2% | 0% | 0% | 1% |
| **succeeded** | **12%** | **23%** | **13%** | **18%** |

Leaving malformed calls out, first-class `edit_file` success is about 38% in r_v9_eog.

`replace.py`, when it was installed, went: 18 OK, 9 safely reverted on a syntax error, 1 usage error, out of 29. That is 62% success, and none of the failures corrupted a file.

### 4.3 The malformed-argument mechanism (tool-call parser)

**What the parser receives.** The model writes backticks, or `\"`, as string delimiters inside the gemma4 `<|"|>` format. The parser then cuts `new_string` at the first `,old_string:`. A typical result is `{"filepath":…, "new_string":"…\`,old_string:", "if convert_underscores": "…"}` (r_v4/fastapi_15589 step 32).

**How often each variant appears.** In r_v9_eog:

- 89 edit_file calls with a backtick delimiter plus escaped quotes;
- 47 with a backtick delimiter only;
- 123 `run_command` calls wrapped as `{"description":…, "parameters":{"command":…}}`, all in one task (rich_3472).

**The same failure family shows up elsewhere:**

- **READ_MANGLED_PATH**: 9-24% of `read_file` calls. The filepath swallows the rest of the call, e.g. ``rich/ansi.py`, start_line: 151``.
- **Quoted skill name**: `Skill '"swe-tools"' not found`.
- **Silently dropped `end_line`.**
- **Scale:** parser-caused failures are **11-32% of all tool calls** (7.1 per task in r_v9_eog, 17.5 in r_v9_eg).

**Loops.** 75-100% of all malformed calls in each arm come from a few tasks with 50 or more. The model sends the *same* broken call again and again: rich_3882 in r_v9_c had 140 copies of one malformed call, with 2 distinct argument strings in total.

- Loop tasks per arm: r_v4 3, v9_c 5, eo 4, eg 7, og 6, eog 2, p_v4 4, p_v6 6, p_v8 7, e74_v3 4.
- **Tasks solved among them: 0.**

**Loops are task-specific and repeat across configs.** Tasks that loop in several configs:

| task | configs |
|---|---|
| rich_3052 | 7 |
| rich_3454 | 4 |
| rich_3934 | 4 |
| fastapi_14463 | 3 |
| rich_3882 | 3 |
| fastapi_14077 | 2 |
| rich_4075 | 2 |
| fastapi_5624 | 2 |
| rich_2943 | 2 |
| fastapi_15800 | 2 |

These loops are almost always in the **fixer**. They never count against `max_tool_calls` (70), so they run until 150 turns or 5 minutes. Across race-1 arms, 20 turn-cap endings had 89-141 malformed calls each.

### 4.4 Other waste

- **Exact-repeat calls** (same stage, same tool, same args) are 32-44% of all calls: 15.7 per task in r_v9_eog, 24.1 in r_v9_eg.
- **`write_file` to `/tmp/...`** is rejected with "Path traversal … escapes workspace root": 29 times in r_v9_eog and 17-43 per run elsewhere. The fixer prompt says "Scratch files go in /tmp", but `write_file` is workspace-only.
- **Post-cap calls**, which hit `BudgetExceeded` after 70 calls: 3-7 tasks per arm and up to 87 calls per arm (r_v9_eo). Each one still costs a full LLM turn.
- **Share of agent time spent on failed calls** (malformed + failed edits + post-cap + helper-missing + mangled reads): r_v4 32%, v9_c 36%, eo 35%, eg 36%, og 27%, **eog 23%**, p_v4 31%, p_v6 41%, p_v7 37%, p_v8 32%, e74_v2 18%, e74_v3 23%.

---

## 5. The v9 helpers in race 1: how they were actually used

**Install was skipped in about 40% of tasks, so the helpers were dead there.**

| arm | install OK | skipped | install failed | helper calls failing in skipped tasks | failing where install OK |
|---|---|---|---|---|---|
| v9_c | 22 | 26 | 3 | 36/39 | 1/60 |
| v9_eo | 22 | 21 | 8 | 45/47 | 0/186 |
| v9_eg | 25 | 23 | 3 | 51/57 | 3/129 |
| v9_og | 25 | 21 | 5 | 57/60 | 0/179 |
| v9_eog | 27 | 20 | 4 | 58/66 | 0/309 |

- **Where install is skipped.** The skip clusters on fastapi, where the issue is a long PR template: v9_eog skipped or failed install on 13 of 19 fastapi tasks and on 11 of 32 rich tasks.
- **Why the skip cannot be recovered.** `locator.yaml` is the only stage with `skills:`, so the fixer and verifier have no way to install.
- **Install failures** come from quoted or missing `skill_name`, e.g. `Script '":"' not found`.
- **Solve rate by install status is confounded by task.** Install-OK tasks solved 23/121 across the v9 arms, and skipped ones 49/111. The same split in r_v4, where helpers never worked, is 2/21 vs 15/23. Within-task pairs on 16 tasks show no helper effect (0.31 vs 0.27).
- **Treat race 1 as "no measured helper effect", neither positive nor negative.**

### Helper call statistics (r_v9_eog)

Share = LLM plus execution time as a share of all agent time (5,644 s).

| helper | calls | tasks | LLM s | exec s | completion tokens per call | share | outcome |
|---|---|---|---|---|---|---|---|
| locate.py | 55 | 50 | 147 | 37 | 35 | 3.3% | 23 missing |
| run.py | 174 | 18 | 371 | 17 | 53 | 6.9% | 162 OK, 7 errors, 4 truncated, 0 timeouts, up to 52 calls in one task |
| gate.py | 79 | 46 | 57 | 82 | 34 | 2.5% | 20 missing, 22 PASS, 12 FAIL, 23 "NO SOURCE CHANGE" |
| replace.py | 36 | 15 | 79 | 1 | 120 | 1.4% | 18 OK, 9 reverted, 7 missing |
| install (run_skill_script) | 32 | 31 | 170 | 1 | 31 | 3.0% | first call, pays the about 6 s first-call cost |

**locate.py recall**, on the first working call in each task (124 tasks across the v9 arms):

| R@1 | R@3 | R@10 | miss |
|---|---|---|---|
| 54% | 73% | 81% | 19% |

- On fastapi it ranks `docs_src/*` tutorial files above `fastapi/`; see the example output in the scratchpad query.
- A top-1 hit does not imply a solve: 14 of 67 were solved, against 9 of 57 misses.

**What gate.py's verdict predicts** (all arms, last verdict per task):

| last verdict | tasks | resolved | note |
|---|---|---|---|
| FAIL | 15 | 1 | a strong negative signal |
| FAIL then PASS | 9 | 2 | both in v9_eog: the repair loop worked twice |
| PASS | 38 | 12 | 32%, because gate only runs existing tests and hidden tests are new |

**run.py** mostly wraps `grep` (98 of 174) and `python -c` (61). It is not being used for the risky commands. None of the 13 race-1 commands that took 20 s or more went through run.py; 9 were bare `python3 repro.py` or `python3 -c`.

---

## 6. Stages

| run | stage | reached | calls, mean / median | over prompt limit* | secs mean | share of agent time | max prompt mean | malformed per task |
|---|---|---|---|---|---|---|---|---|
| r_v4 | locator | 51/51 | 19.1 / 16 | 43 | 23.5 | 25% | 12.6k | 0.1 |
| r_v4 | fixer | 49/51 | 20.6 / 10 | 22 | 43.5 | 45% | 9.0k | 6.9 |
| r_v4 | verifier | 46/51 | 9.5 / 7 | – | 13.4 | 13% | 6.1k | 0 |
| r_v9_eog | locator | 51/51 | 19.4 / 17 | 40 | 36.9 | 33% | 11.8k | 0 |
| r_v9_eog | fixer | 51/51 | 16.2 / 10 | 22 | 30.1 | 27% | 8.6k | 3.1 |
| r_v9_eog | verifier | 50/51 | 14.4 / 10.5 | – | 25.2 | 22% | 7.4k | 2.5 |
| e74_v3 | locator | 74/74 | 13.7 / 9 | 44 | 29.1 | 19% | 9.2k | 0 |
| e74_v3 | fixer | 71/74 | 17.8 / 8 | 29 | 62.0 | 40% | 7.7k | 4.2 |
| e74_v3 | verifier | 63/74 | 11.0 / 6 | – | 42.7 | 24% | 6.3k | 1.0 |

\*The prompt limits are "at most 8 tool calls" for the locator and "at most 12" for the fixer. The **locator ignores its limit in about 80% of tasks**, the fixer in about 43%. No per-stage hard cap exists in the declarative config (UNVERIFIED: `adk_submission/schema.py` has only callbacks, which have no registered entries, plus `max_iterations` for loop agents).

**Where the caps landed** (race-1 r_ arms):

| cap | stage that hit it | runs | resolved |
|---|---|---|---|
| tool-call cap | verifier | 21 | 6 |
| tool-call cap | fixer | 8 | – |
| turn cap | fixer | 15 | 0 |
| turn cap | verifier | 3 | 0 |
| time cap | fixer | 13 | 0 |
| time cap | verifier / locator | 4 | 0 |
| context overflow | locator / fixer / verifier | 7 / 3 / 2 | 0 |

The six call-cap solves come from the harness capturing the working-tree diff as a fallback.

**The verifier never ran in 39 race-1 runs.** The causes: 15 turn cap, 13 time cap, 10 context overflow, 1 other. None of these runs was solved.

**Nudges re-run the whole pipeline.** After a "continuation nudge", SequentialAgent starts again from the locator. This happened in 16 pod runs, and 2 of them were solved.

---

## 7. Patches: empty, broken, hung

### 7.1 Why patches were empty

| cause | race1 r_ arms (53) | race1 c_ (11) | fair (55) | kaggle (37) |
|---|---|---|---|---|
| context overflow (patch discarded) | 12 | 1 | 25 | 0 |
| time cap before any edit | 10 | 2 | 9 | 5 |
| malformed-arg loop → turn cap | 9 | 2 | 3 | 4 |
| tool-call cap, no edit landed | 8 | 3 | 4 | 0 |
| edited but diff empty (reverted or other) | 9 | 1 | 2 | 1 |
| every edit_file attempt failed | 4 | 2 | 5 | 10 |
| never attempted an edit | 1 | 0 | 7 | 17 |

### 7.2 Failing non-empty patches, classified by test output (`regress.py`)

| run | unsolved with a patch | fails only new or modified tests | breaks existing tests | collection error | hang (exit 124) | test_patch did not apply |
|---|---|---|---|---|---|---|
| r_v4 | 25 | 18 | 2 | 3 | 2 | 0 |
| r_v9_c | 27 | 21 | 3 | 1 | 1 | 1 |
| r_v9_eo | 31 | 18 | 7 | 1 | 3 | 2 |
| r_v9_eg | 20 | 14 | 2 | 2 | 2 | 0 |
| r_v9_og | 29 | 21 | 5 | 1 | 2 | 0 |
| r_v9_eog | 27 | 20 | 4 | 0 | 3 | 0 |
| p_v4 | 35 | 21 | 4 | 6 | 4 | 0 |
| p_v8 | 37 | 24 | 5 | 6 | 2 | 0 |

- **One "regression" is a false positive.** rich_4076's test fails on the no-patch baseline too (`eval/runs/nopatch_all`).
- **The confirmed regressions in r_v9_eog** are rich_3934, rich_3953 (8 tests) and rich_3468 (58 tests). The gate had flagged FAIL on the first two, and the fixer failed to repair them.
- **Every test_patch apply failure has the same cause** (5 runs). The agent had edited the exact test file that test_patch modifies, which produced "No file to patch" (fastapi_14077 ×2, fastapi_15588, fastapi_14492, rich_3454).

### 7.3 The gold-file failures are mostly partial

In r_v9_eog there are 19 failing patches that touched a gold file:

- 13 have fewer hunks than gold;
- 9 have less than a third of gold's changed lines;
- 6 miss a gold file entirely.

r_v4 shows the same shape: 11, 6 and 6 of 17.

Failure labels in the style of `eval/expdb.py`:

| label | r_v9_eog | r_v4 |
|---|---|---|
| GOLD_EDIT_FAILED | 19 | 17 |
| LOCATE_MISS | 5 | 5 |
| WRONG_FILE_EDIT | 3 | 3 |
| empty | 3 | 8 |

---

## 8. v9_eog vs v4, task by task, and what the winners did differently

**Wins over race1 r_v4.** These are the first-10-call comparisons for the tasks some race arm solved and v4 did not (full dump in scratchpad `first10.txt`):

| task | winner | what the winner did in its first 10 calls | what v4 did |
|---|---|---|---|
| fastapi_14077 | v9_eog | install OK → `locate.py` → 2 greps → 3 reads of the gold files. Locator done in 7 calls / 16 s. Fixer's first `edit_file` succeeded. | install failed (quoted arg), locate missing. Locator took 14 calls, fixer 56, hit the 70-call cap. |
| fastapi_5624 | v9_c | `locate.py` found `security_scopes` → read the gold lines 230-308. Fixer made 2 calls. | helper missing, then read the wrong regions (`solve_dependencies` 565-700). Fixer took 20 calls. |
| rich_3278 | v9_og | helper missing, but plain `grep from_ansi` → `rich/ansi.py`. 10 locator calls. | 3 READ_MANGLED reads, repeated identical `python -c` regex prints. 70-call cap, empty patch. |
| rich_3454 | v9_eog | `git grep ReprHighlighter` → gold read. The fixer's edits went through. | the fixer spent 290 s in a malformed `edit_file` loop (1 counted call) → time cap. |
| rich_3470 | v9_c | `locate.py "record capture"` → `console.py:334`. | helper missing, a 380-1200-line test read, verifier 38 calls, empty patch. |
| rich_3506 | v9_eog | `locate.py` + `run.py` grep for tests. Repro, then edit. | 134 malformed edits → 150-turn cap. |
| rich_3676 | v9_eog | `locate.py "__notes__"` → `traceback.py:299-527`. | helper missing, then 3 READ_MANGLED reads. |
| rich_3777 | v9_c | `locate.py` → `TTY_COMPATIBLE` in `console.py`. | read `progress.py` five times in slices. Empty patch at 69 calls. |
| rich_4077 | v9_eog | `locate.py "isatty proxy"` → `rich/file_proxy.py` (gold) on call 3. 1 edit. | `grep isatty` → edited `rich/console.py` (the wrong file). |

**The common pattern.** In 7 of the 9 winners, a working `locate.py` put the gold file among the first 3 calls. None of the winners hit a malformed loop or a mangled read. Winners converged in 15-46 calls; v4 took 44-70.

**v4-only wins:**

- **fastapi_5077.** v9_eog's install was skipped, so `run.py` was missing. It then also edited `tests/…`.
- **rich_3521.** v9_eog read the right code but made a smaller edit (2 lines vs 35 in gold).

**The fair-run 6-minute comparisons against Kaggle show the same thing.** Contested tasks flip with sampling: rich_3063, rich_3718 and fastapi_14301 are solved by the fair runs but lost by v9_eog to caps and empties.

---

## 9. Ranked loss buckets, in tasks

For v9_eog on the 74 local tasks: 28 solved, 46 lost. Each task is counted once, by primary cause; the per-task table is in the scratchpad query output.

| # | bucket | tasks | never solved by any run? | reachable for v10? |
|---|---|---|---|---|
| 1 | Hidden spec or underspecified issue (exact string, API or name only in the test; title-only issues) | 15 (HIDDEN_SPEC 9, UNDERSPEC 6) | yes, all 15 | mostly no. Maybe 2-3 via the "title-to-identifier grep" and "copy the exact names from the issue" levers in diagnosis.md |
| 2 | Wrong or partial semantics on the right file (multi-hunk fixes cut short) | 8 (rich_3180, 3934, 3953, 4075, 3470, fastapi_14986, 14448, 14419) | 7 of 8 | partly: a completeness check ("every call site or hunk?"), gate FAIL → repair. About 2-3 |
| 3 | Contested: solved by some other run, lost here to sampling, caps or empties | 7 (fastapi_14301, 5077, 14616, rich_3718, 3777, 3521, 3063), plus 3 more listed in buckets 2, 4 and 7 (rich_3470, rich_3278, fastapi_5624) | no | partly. In other arms, caps and overflows cost about 3.5 of these per arm. For v9_eog, 8 of the 10 were plain wrong patches (sampling), so expect about 2-4 |
| 4 | Edit-tool failure (right idea, edits never landed or were corrupted) | 5 (rich_3043, fastapi_15588, rich_3535, 3052, 3278) | 4 of 5 | yes: `replace.py` everywhere and no `edit_file` in the fixer. About 2-3 |
| 5 | Feature too large | 4 (fastapi_15661, 15800, 14306, rich_3930) | yes | no |
| 6 | Infinite-loop bug: repro or test hangs (exit 124) | 3 (rich_4006, 3772, 3480) | yes | maybe 1-2 (timeouts on repros, "TIMEOUT = still looping") |
| 7 | Wrong location | 2 (fastapi_13920, 5624) | 1 | 1 |
| 8 | Env-blocked locally (probably already passing in the Kaggle env) | 2 (rich_4079, 3782) | – | measurement only |

**Cross-cutting mechanisms.** These overlap the buckets above and are counted per arm, on 51 tasks:

- Hitting a cap (time, turn or context) on a task another arm solved: **about 3.5 per arm** (v9_c 5, eo 5, og 6, eg 3, v4 2, eog 0). Turn-cap cases: 11 over 6 arms, all malformed loops.
- Context overflow discarding the patch: **0-4 per arm**, 38 runs in total.
- Helpers dead because install was skipped: **about 40% of tasks per v9 arm**.

**Ceiling arithmetic.** The union over all runs is 38/74, so removing variance alone caps us at about 38 locally. Beyond that it takes capability: buckets 1, 2 and 5 hold 27 tasks never solved.

**Transfer.** v4 is about 26/74 locally (35%) and 0.12 on the public LB, so the transfer ratio is about 0.34. Local task gains therefore need to be large, **and** they must not add wall time (section 2.4).

---

## 10. Concrete v10 consequences

1. **Remove `edit_file` from the fixer and verifier tool lists** and edit only through `run_command` + `replace.py` (heredoc). This removes the parser failures (39-52% of all `edit_file` calls) and the death spirals. `run_command` had 1 malformed call per arm apart from the rich_3472 anomaly.
   - Keep `write_file` for new files, but correct the prompt: `/tmp` is not writable through it.
2. **Make helper install impossible to skip:**
   - add `skills: [skills/swe-tools]` to every stage;
   - have the stage prompts start with the install call;
   - or put a tiny first "setup" sub-agent in the SequentialAgent, with only `run_skill_script`.

   Also make the error text say "run install.py" when `/tmp/swe/x.py` is missing: the prompt can describe the "can't open file" symptom. Measure install-OK rate as a gate metric; the target is ≥ 95%.
3. **Set `max_output_tokens` to about 1,536** (p99 of completion tokens is 731, and 141 of 33k calls exceed 1,024):
   - it bounds a runaway call on L4 at about 40 s instead of about 110 s;
   - it frees about 2.5k tokens of context before overflow.
4. **Context guard.** Every overflow is a guaranteed 0 and discards landed edits.
   - Forbid `read_file` without `end_line`, or wrap reads in a helper that caps output at about 3k chars.
   - Pass the located code snippets in `plan` so the fixer does not re-read them (about 44% of reads).
   - Route pytest through `run.py`, or gate.py-style summaries only.
   - The exception path cannot be fixed from the bundle.
5. **Lower `timeout_seconds` to about 60.** No legitimate command or public verification took more than 16 s. The saving is up to 120 s per hang task on the agent side and on the hidden-test side. The risk is hidden test suites that take longer than 60 s (UNVERIFIED).
6. **Time budget rule.** Before shipping, v10's replayed L4 time must be ≤ 1.08× v4's, using this report's latency model or a Kaggle L4 run. The hard ceiling is 1.15× (12/10.4).
   - The main speed levers are fewer calls (repeats, malformed calls, re-reads) and fewer completion tokens.
   - Prompt length is free for speed.
7. **Enforce stage budgets with structure, not prompt text.** The locator ignores "≤ 8 calls" in about 80% of tasks. Each stage needs a concrete deliverable, and the nudge rerun of the whole pipeline should be avoided.
8. **Gate verdicts are a usable signal.** A final FAIL resolved 1 of 15. A FAIL→PASS repair resolved 2 of 3 in v9_eog. PASS is weak (32%). Keep the gate, but put the effort into completeness: the partial multi-hunk fixes are the main loss.
9. **Never touch `tests/`.** Revert edits to test files before submit: 5 runs lost to test_patch conflicts, and 4-16 patches per run touch tests/.

---

## 11. Open questions / UNVERIFIED

- **Hidden per-task timing.** The 308 s per task assumes ~120 hidden tasks and about 500 s of startup. Whether hidden tasks are cap-saturated or setup-heavy cannot be told apart from our data. A Kaggle kernel that logs per-task wall on a private-like repo would settle it.
- **Hidden test-suite durations.** These decide whether `timeout_seconds: 60` is safe.
- **Whether the gemma4 parser failure rate is the same on the Kaggle scorer's patched vLLM.** e74_v3 shows 52% malformed `edit_file` calls on L4, so probably yes.
- **Whether declarative callbacks have any registered entries on the scorer.** Locally none are registered (`adk_submission/registry.py` has only docstring examples). Without them no per-stage hard cap is possible.
- **The latency model underestimates actual L4 time by about 7%** (e74_v3 check). Apply a 1.08 factor.
- **The pod ran 2 tasks per GPU**, so its latency includes contention. The Kaggle scorer is sequential on 4×L4.
