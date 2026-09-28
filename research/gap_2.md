# Gap 2: what candidate selection (best-of-k) is worth offline, and whether to build k=2 or a retry on FAIL

Written 2026-09-28 12:46 IST (07:16 UTC). Read-only: nothing was submitted, pushed, started or spent. The only repo file
changed is this one. Every number below comes from a script output, a file:line or a trace. Anything not measured is
marked UNVERIFIED.

Scripts (scratchpad, the whole set runs in under 5 s):
`/private/tmp/claude-501/-Users-carson-Projects/654244a3-b38c-45a0-96af-d7e5f0aac6ce/scratchpad/gap2/`:

| script | what it does | output |
|---|---|---|
| `load.py` | Builds one record per (arm, task): resolved, duration, patch metrics, and the final gate.py verdict parsed from the trace | `records.json` |
| `replay.py` | Runs the selectors over every k-subset, with paired discordance, bootstrap CIs, named pairs and the sequential variant | `replay.out` |
| `pairwise.py` | Within-task pairwise accuracy of each selection signal | |
| `fair_check.py` | Out-of-sample check on the 4 fair runs (74 tasks) | `fair_check.out` |
| `length_pooled.py` | Value of the length signal over "any non-empty", pooled; why candidates were empty | `length_pooled.out` |
| `helpers_effect.py` | Within-task effect of helper install success | |
| `timefeas.py`, `timefeas2.py`, `discord2.py` | Replay rescored under the 300 s cap on L4 and hidden-set scales, with ParallelAgent's shared-failure semantics | `timefeas*.out` |
| `budget_k2.py` | gap_5's calibrated 12 h model, rerun with the k=2 multipliers | `budget_k2.out` |

The earlier `select.py`, `sim*.py` and `extract.py` in the same folder (03:37-03:44) belong to the critique that produced
the brief's numbers. I did not reuse them. The numbers below were recomputed from scratch.

## 0. Answers in one screen

| Question | Answer | Evidence |
|---|---|---|
| Does the brief's replay reproduce? | **Yes.** Shortest non-empty patch (non-test .py lines): k=2 **18.63**/51 (brief 18.7) against a 16.33 single-arm mean. k=3 19.63 (brief 19.9), k=6 21.5 (brief 22). Normalized majority at k=6 is **23.0**, longest at k=6 **14.0**, and r_v4+p_v4 gives shortest 20 with a union of 23. The small gaps come from ties, which I split evenly and score as an expectation. | `replay.out` sect. 2, 4 |
| What is the +2.3/51 at k=2 made of? | **+1.33 is the empty-patch fallback that any selector gets** (random among non-empty). Length adds **+0.97, 95% CI [-0.13, +1.97]**, and the gate adds **+0.30** on top of length | `replay.out` sect. 3 |
| Is "shorter is better" a real signal? | **Not established.** Within-task pairwise accuracy is 0.663 on race 1 (89 pairs) but **0.487 on the 4 fair runs (40 pairs)**. On the fair runs the longest patch does as well as the shortest (27.25 vs 27.08 at k=2). Pooled over 129 pairs it is **0.61**, the same as the Jev judge's 0.61 | `pairwise.py`, `fair_check.out`, `length_pooled.out` |
| Is the gate verdict a real signal? | **Only as a veto.** Among non-empty patches a final FAIL resolved **1/15**, PASS 15/48 and no verdict 92/216. On all **17 tasks where two gated candidates both had a verdict, the two candidates had the same outcome**, so the gate never separated two gated candidates. All of its selection value comes from demoting a FAIL against an ungated candidate | `load.py` + `pairwise.py` |
| Execution-aware selector at k=2 (gate, then shortest) | **18.93/51 (+2.60 per pair, CI [+0.77, +4.33])**, of which +1.27 [+0.33, +2.37] is over random-nonempty. Dropping test-touching patches adds +0.00 over gate-then-shortest and +0.07 over shortest at k=2 on race 1, and +0.50 over shortest on the fair runs | `replay.out` sect. 2-3, `fair_check.out` |
| Sequential: run B only when A's final gate is FAIL or A's patch is empty | Fires on **10/51** tasks for A = v9_eog. It changes eog to 21 (with B = eg) or 22 (with B = og). Over the 6 ordered gated pairs the mean gain is **+2.17/51** with unlimited time, **+1.0/51** when B must fit inside A's remaining 300 s, and **+0.67/51** with a 5 s check stage on every task (public-like L4). Wins/losses 6/2 | `replay.out` sect. 5, `timefeas2.out`, `discord2.py` |
| Parallel k=2 in one task, as the scorer would run it | Same-sandbox semantics: branches share the 5-min timer and turns, and a context overflow in either branch kills the task (TaskGroup). Public-like L4: **+0.5 to +1.1/51**. Hidden set under gap_5's uniform-slowdown fit (k=2.9): **-1.0 to -3.7/51**. At k=4.6: -0.5 to -1.0 | `timefeas2.out` |
| TM4's "+7 to +18 s per task" | **An underestimate for k=2.** It assumes identical candidates. Measured slowest-branch penalty: fixer stage +15 to +40 s on H100 (**+19 to +51 s on L4**), whole pipeline +33 s H100 (x1.26) | `timefeas.out` |
| 12 h | **Not the binding constraint at a 5.0-min cap.** The heaviest k=2 design projects to 9.76-10.05 h (A = 8.75-9.40), and every task running to the cap gives 10.49 h. What k=2 does move is the **share of hidden tasks at the cap: 68% for v10 single, 70% (+18 s), 77% (+40 s), 80-82% (whole-pipeline k=2)**. Capped runs score 0 | `budget_k2.out`; `own_data.md` TL;DR 3 |
| Decision | **Neither Parallel k=2 nor a LoopAgent.** A LoopAgent cannot exit early, because the harness registry has no `exit_loop`/escalate tool. At most, build a **conditional second fixer stage** in the existing SequentialAgent. It fires only on final gate FAIL or an empty patch, and only if at least 90 s remain. Expected value is +0.67/51 public-like (about +0.8 of 60) and +0.17/51 on hidden-like tasks. It is never negative in replay, and it ranks below single-run fixes | sect. 8-9 |
| h100b caveat | `eval/h100b/runs/p_v4` **and `p_v6`** are byte-identical to `eval3/eval/runs/p_v4`/`p_v6` (task_results, all patches). own_data's "union of 14 runs = 38" **did not count h100b**: its run list is race1 x 8, fair x 4, kaggle x 2 (`scratchpad/own/extract.py:10-16`). A duplicate cannot change a union anyway. Recomputed: 38/74 (39 with the Kaggle-env rescore of the fair runs). No research file cites h100b | sect. 10 |

## 1. Data and definitions

- **Arms:** race 1, at the faithful Kaggle budget (5 min / 70 calls / 150 turns / 180 s, 2 tasks per H100). r_v4, r_v9_c,
  r_v9_eo, r_v9_eg, r_v9_og and r_v9_eog ran on the 51 arena tasks. c_v9_eg and c_v9_eog ran on the other 23 valid tasks. Also
  the fair runs p_v4, p_v6, p_v7 and p_v8 on 74 tasks (6 min / 110 calls), with `resolved` taken from
  `eval/kaggle/rescore_fair/results.jsonl`. That changes p_v4 on the arena from 18 (pod) to 19 (fastapi_13537).
- **Patch length** is the count of +/- lines in non-test `.py` files. Test files match
  `(^|/)(tests?|testing)/|test_*.py|*_test.py|conftest.py`. "Empty" means 0 such lines. Six patch files differ from the graded
  `agent_patch_size` by 2-127 bytes and one by 40 kB (r_v9_eg fastapi_14448, 9.2 MB). All seven are unresolved, so this does not
  matter.
- **Gate verdict** is the last `gate.py` call in the trace whose output contains `GATE: PASS`, `GATE: FAIL` or `TIMED OUT`
  (`helpers_v9/gate.py:46,52`). Calls that printed "can't open file", "NO SOURCE CHANGE", "No existing test file" or
  BudgetExceeded count as no verdict. 16 of 67 final verdicts were followed by a successful source edit, so they describe an
  earlier state of the patch.
- **Selectors never read the hidden tests.** Ties are split evenly and scored as an expectation.

## 2. Gate verdicts per arm (all runs, including empty patches)

| arm | EMPTY | final FAIL | final PASS | gate could not open (no install) | no gate call |
|---|---|---|---|---|---|
| r_v9_eg | 0/16 | 0/3 | 3/10 | 11/18 | 1/3 |
| r_v9_og | 1/9 | 0/3 | 4/13 | 9/23 | 0/3 |
| r_v9_eog | 1/5 | 0/5 | 6/17 | 13/19 | 1/3 |
| c_v9_eg | 0/5 | 0/1 | 1/4 | 6/12 | 0/1 |
| c_v9_eog | 0/9 | 1/3 | 1/4 | 5/6 | 0/1 |
| **pooled** | **2/44** | **1/15** | **15/48** | **44/78** | 2/11 |

**Runs where the gate could not open resolved 56%, against 31% for PASS. This is task selection, not a helper effect.**
Each group of runs landed on tasks with a different average solve rate across the 7 race arms: 0.459 for helpers broken,
0.208 for helpers installed (`helpers_effect.py`). Within the 27 tasks that have both an installed and a broken v9 run, the
solve rates are 0.364 (installed) and 0.343 (broken), with 5 tasks going each way. So a cross-task table of gate verdicts
cannot rank candidates. Only within-task comparisons can (sect. 3).

## 3. Selectors on the 51 arena tasks

Mean solved over every k-subset of the 6 race arms (`replay.out` sect. 2):

| selector | k=2 (15 pairs) | k=3 (20) | k=6 | k=2 range |
|---|---|---|---|---|
| oracle (union) | 21.27 | 23.55 | 27.00 | 19-24 |
| gate (PASS > none > FAIL) then shortest | **18.93** | **20.30** | 22.00 | 16-21 |
| gate + drop test-touching, then shortest | 18.93 | 20.40 | 22.00 | 16-21 |
| drop test-touching, then shortest | 18.70 | 19.88 | 22.17 | 17-21 |
| shortest | 18.63 | 19.63 | 21.50 | 17-20.5 |
| normalized-line majority, then shortest | 18.63 | 19.73 | **23.00** | 17-20.5 |
| gate, random tie-break | 18.17 | 19.18 | 20.55 | 16-20.5 |
| random among non-empty | 17.67 | 18.37 | 19.42 | 15-20 |
| first non-empty in arm order | 17.53 | 18.85 | 22.00 | 15-19 |
| longest | 16.70 | 16.46 | 14.00 | 12-19.5 |
| single arm (mean) | 16.33 | | | |

Paired discordance at k=2 is pooled over 15 pairs x 2 constituent arms. The 95% CI is a bootstrap over tasks of the mean
over pairs of (selector minus the mean of its 2 arms) (`replay.out` sect. 3):

| selector | wins | losses | net per pair | 95% CI | over random-nonempty |
|---|---|---|---|---|---|
| oracle | 148 | 0 | +4.93 | [+3.33, +6.67] | +3.60 [+1.97, +5.50] |
| gate then shortest | 119 | 41 | **+2.60** | [+0.77, +4.33] | **+1.27 [+0.33, +2.37]** |
| shortest | 114.5 | 45.5 | +2.30 | [+0.43, +4.07] | +0.97 [-0.10, +1.97] |
| gate, random tie | 107.5 | 52.5 | +1.83 | [+0.10, +3.47] | +0.50 [-0.13, +1.33] |
| random non-empty | 100 | 60 | +1.33 | [-0.23, +2.80] | 0 |
| longest | 85.5 | 74.5 | +0.37 | [-1.47, +2.20] | -0.97 [-1.97, +0.10] |

Why a candidate was empty, over the 60 events (30 ordered pairs) where A was empty and B was non-empty and resolved
(`length_pooled.out`): **turn cap 18, time cap 17, context overflow 10, clean finish with no source edit 15.** 45 of the 60
come from caps or exceptions. Inside one task those are shared by both branches or kill both (sect. 7).

Within-task pairwise accuracy: over pairs of non-empty candidates on the same task where exactly one resolved, how often
the signal prefers the resolved one (`pairwise.py`):

| signal | pairs | accuracy | decisive pairs only |
|---|---|---|---|
| shorter non-test .py | 89 | 0.663 | 0.671 (85) |
| shorter, all files | 89 | 0.685 | 0.690 (87) |
| gate rank | 89 | 0.579 | 0.733 (30) |
| does not touch tests | 89 | 0.567 | **0.929 (13 of 14)** |
| gate rank, both candidates gated | **0** | n/a | n/a |

The last row is exact. On all 17 tasks where two or more gated arms had a verdict, the gated candidates all resolved or all
failed. Examples: fastapi_9425, 3/3 PASS, all resolved. rich_3777: eg PASS, og PASS, eog FAIL, none resolved. So the
replay says nothing about whether the gate separates two candidates of the same gated config, which is exactly what a v10
k=2 would face.

## 4. Out-of-sample check: the 4 fair runs on 74 tasks

The fair runs (`fair_check.out`) are a different population: looser budget, broken helpers, no gate. Singles 27/25/26/22,
mean 25.0:

| selector, k=2 over 6 pairs | mean | net | 95% CI |
|---|---|---|---|
| union | 30.50 | +5.50 | [+3.50, +7.67] |
| drop test-touching, then shortest | 27.58 | +2.58 | [+0.83, +4.50] |
| longest | 27.25 | +2.25 | [+0.33, +4.17] |
| random non-empty | 27.17 | +2.17 | [+1.00, +3.50] |
| shortest | 27.08 | +2.08 | [+0.33, +4.00] |

"Shorter" has pairwise accuracy **0.487 over 40 pairs** here. Shortest minus random-nonempty (`length_pooled.out`) is
+1.90 pp [-0.13, +3.79] on race 1, -0.11 pp [-2.14, +1.80] on the fair runs, and **+0.71 pp [-0.71, +2.08] pooled**.
**The robust part of the k=2 gain is the empty-patch fallback. The length rule is at best a weak tie-break**, the same
strength as the Jev judge (within-task 0.61, from the brief). At k=6 on race 1, longest (14) is far below shortest (21.5),
but with 6 candidates the longest is usually a runaway. That does not carry down to k=2.

## 5. Named pairs, including the same-config pair

`replay.out` sect. 4. Each cell gives solved /51, then (W-L against A, sign p / W-L against B, sign p):

| pair | A | B | union | shortest | gate then shortest | random |
|---|---|---|---|---|---|---|
| eog + eg | 21 | 16 | 21 | 20.5 (0-0 / 4-0 p=.12) | **21.0** (0-0 / 5-0 p=.06) | 20.0 |
| eog + og | 21 | 14 | 22 | 19.0 (1-3 p=.62 / 6-1 p=.12) | 20.0 (1-2 p=1 / 7-1 p=.07) | 18.5 |
| eg + og | 16 | 14 | 20 | 17.5 | 18.0 (4-2 p=.69 / 4-0 p=.12) | 18.0 |
| eog + v4 | 21 | 18 | 23 | 19.5 | 21.0 (1-1 / 5-2 p=.45) | 19.0 |
| r_v4 + p_v4 (same config) | 18 | 19 | 23 | 20.0 (5-3 p=.73 / 1-0) | 20.0 | 19.0 |

- **Other 23 tasks, c_v9_eg + c_v9_eog (7 and 7):** union 8, shortest 7.5, gate then shortest 7.0, gate + drop tests 8.0,
  random 7.5.
- **eog-family over all 74** (eog+eg on 51, c-pair on 23): gate then shortest 28.0, against singles of 28 (eog) and 23 (eg).
- **No selector beats the best arm (v9_eog, 21) on any pair.** The gain appears only against the mean arm. Measuring
  against the mean is the right estimator if the arms are exchangeable draws (race-1 paired tests p > 0.14). Measuring
  against the best arm is biased low, because 21 is the maximum of 6 noisy runs.
- No second run of the same config at the same budget exists. r_v4 + p_v4 differ in budget (5 min/70 calls vs 6 min/110
  calls).

## 6. Sequential variant: take B only when A's final gate is FAIL or A's patch is empty

`replay.out` sect. 5. Time is H100 seconds.

| A to B | A | fired | takes B | re-selects between A and B | union | B-time added, s/task | A's mean duration on fired tasks |
|---|---|---|---|---|---|---|---|
| eog to eg | 21 | 10 | 21 | 21.0 | 21 | 25.7 | 128 |
| eog to og | 21 | 10 | 22 | 21.0 | 22 | 25.8 | 128 |
| eg to eog | 16 | 19 | 19 | 19.0 | 21 | 48.5 | 169 |
| eg to og | 16 | 19 | 19 | 19.0 | 20 | 48.1 | 169 |
| og to eog | 14 | 12 | 17 | 16.0 | 22 | 33.1 | 188 |
| og to eg | 14 | 12 | 17 | 17.0 | 20 | 24.2 | 188 |

- For v9_eog the trigger fired on 4 clean empty finishes, 1 turn-cap empty and 5 gate FAILs.
- Widening the trigger to "not PASS" fires on 34/51, costs 81-91 s per task, and gives 17 by taking B or 20-21 by
  re-selecting. That is worse than the narrow trigger, as expected from the 44/78 solve rate of the no-verdict group.
- The trigger costs time only where A already scores ~0 (FAIL 1/15, empty 2/44), which is why it never goes negative.

## 7. What a ParallelAgent in one task actually does (verified in source)

The replay above treats the arms as independent full runs. The scorer would run the two branches inside one task:

1. **Shared failure.** `_merge_agent_run` runs the branches in one `asyncio.TaskGroup`
   (`google/adk/agents/parallel_agent.py:71-73`). An exception in one branch cancels the other. A context overflow is such an
   exception, and it reaches the runner's `except Exception` (`swegemma/harness/agent_runner.py:799-801`), which discards the
   patch (`own_data.md` TL;DR 5). Race 1 had 0-4 overflows per arm, and 3.93/51 tasks overflow in at least one arm of a pair.
2. **Shared budgets.** The 5-min timer, the tool-call counter and `max_llm_calls` are per task (`config_space.md` F7). A
   branch caught in a malformed-edit spiral (`own_data.md` TL;DR 3) burns the other branch's turns and time.
3. **Wall time is the slowest branch.** `_merge_agent_run` waits for every sentinel (`parallel_agent.py:75-84`).
4. **Branch B cannot use `read_file`/`edit_file`**, which accept only `/workspace` paths (`config_space.md` F7). No race-1 arm
   worked like that, so the replay's B is not the B that would run.

**No early-exit loop is possible.** The tool registry is exactly 9 tools (`swegemma/tools/__init__.py:34-46`). Neither
swegemma nor adk_submission mentions `exit_loop` or escalate (grep). A declarative `LoopAgent`
(`adk_submission/schema.py:349-360`) therefore always runs `max_iterations` passes. "Retry only on FAIL" has to be a
conditional stage whose instruction tells it to stop at once when the first attempt passed.

## 8. Time-feasible replay

`timefeas2.out`, all ordered pairs (both choices of primary branch). A run counts only if `duration x s` is at most 300 s.

- **Scales.** s = 1.27 for public-like tasks on L4, from v9_eog's 135 s H100 wall against its 171 s projected L4 agent time
  (`gap_5.md:108`, `time_model.md:193`). This is a projection: UNVERIFIED on L4 for these exact runs.
  s = 1.27 x 2.9 and 1.27 x 4.6 for the hidden set under gap_5's uniform-slowdown fit (`gap_5.md:95`).
- **Contention.** alpha = 0.08 (competitor L4 figure, UNVERIFIED) and 0.20 (H100 measured) (`time_model.md` sect. 4.1).
- **Parallel.** If both branches finish, the selector runs. Otherwise the primary's `/workspace` result is graded if it
  finished (`time_model.md` sect. 4.3 point 3).
- **Sequential.** B must fit in what A left minus a 5 s check. The check costs 5 s on every task. That figure comes from
  2 calls at the fitted L4 cost of 0.99 s + 26.5 ms/token (`own_data.md` TL;DR 6).

| regime | s | single, 6 arms | parallel, independent failure (a=.08/.20) | parallel, shared failure | single, 3 gated arms | parallel, shared, gated pairs | sequential conditional stage, gated |
|---|---|---|---|---|---|---|---|
| H100 as run | 1.00 | 16.17 | 18.13 / 18.13 | 17.47 / 17.47 | 16.67 | 17.67 / 17.67 | 17.33 |
| public-like on L4 | 1.27 | 16.17 | 17.90 / 17.67 | **17.23 / 17.00** | 16.67 | **17.33 / 17.17** | **17.33** |
| L4 x1.5 | 1.91 | 15.67 | 15.87 / 14.60 | 15.33 / 14.07 | 15.67 | 15.17 / 14.17 | 15.83 |
| hidden, k=2.9 | 3.68 | 9.50 | 8.50 / 6.23 | **8.03 / 5.83** | 8.00 | **6.50 / 4.83** | **8.17** |
| hidden, k=4.6 | 5.84 | 2.17 | 1.53 / 1.53 | 1.13 / 1.13 | 1.33 | 0.83 / 0.83 | 1.33 |

- **Calibration check.** The single-arm hidden rows give 18.6% (k=2.9) and 4.3% (k=4.6) of 51. sub3 scored 12% on the hidden
  set, which falls between the two, so the regime is plausible.
- **Paired wins/losses on public-like L4** (`discord2.py`, pooled pairs are not independent):
  - Sequential, gated: 6 / 2, +0.67/51.
  - Parallel with shared failure, all pairs: 80 / 48, +1.07/51.
  - Parallel with shared failure, gated pairs: 10 / 6, +0.67/51.
- **Why parallel loses on the hidden set.** Contention slows the primary branch, so the few near-cap solves that a single
  run lands are lost. The second branch rarely finishes in time to replace them.

## 9. TM4's cost and gap_5's 12 h arithmetic

- **Stage durations** (`timefeas.out`; fixer stage = last fixer event minus last locator event, H100):
  - v9_eog: mean 33 s, E[max of 2] 48 s (+15).
  - v9_og: 49 to 78 s (+29).
  - v9_eg: 65 to 105 s (+40).
  - v4: 45 to 71 s (+26).
  - Whole pipeline: E[max(dA, dB)] 161 s against E[d] 127 s (+33 s, x1.26).
  - On L4 (x1.27) that is **+19 to +51 s for a fixer-only k=2**, before contention. TM4's +7 s (alpha .08) and +14 s (alpha .20)
    (`time_model.md:183`) assume identical candidates. Its own caveat says real candidates fall between the identical and the
    independent tables.
- **12 h**, from gap_5's calibrated model unchanged (`budget_k2.out`; N = 120, 5 s overhead, S = 560 s). Hours inside the
  clock, with the share of tasks at the cap in brackets:

| design | m vs v4 | A=8.75: cap 5.0 | cap 5.5 | A=9.40: cap 5.0 | cap 5.5 |
|---|---|---|---|---|---|
| v10 single (gap_5) | 1.20 | 9.13 (68%) | 9.78 (64%) | 9.65 (80%) | 10.43 (77%) |
| + parallel k=2 fixer, +7 s | 1.25 | 9.21 (68%) | 9.88 (65%) | 9.70 (81%) | 10.49 (78%) |
| + parallel k=2 fixer, +18 s | 1.33 | 9.33 (70%) | 10.01 (68%) | 9.77 (82%) | 10.58 (80%) |
| + parallel k=2 fixer, +40 s (measured slowest branch) | 1.48 | 9.50 (77%) | 10.25 (70%) | 9.88 (86%) | 10.72 (82%) |
| + parallel k=2 whole pipeline (x1.26 x1.20) | 1.81 | 9.76 (82%) | 10.57 (80%) | 10.05 (88%) | 10.92 (86%) |
| + sequential retry, 20% of uncapped tasks to the cap | 1.20 | 9.40 | 10.12 | 9.82 | 10.64 |
| + sequential retry, 40% | 1.20 | 9.67 | 10.46 | 9.99 | 10.85 |

- **At a 5.0-min cap no design can break 12 h.** Every task at the cap gives 10.49 h (11.60 h at N = 130 with 12 s
  overhead).
- **At 5.5 min, parallel k=2 leaves 1.1-2.1 h below 12 h.** The worst case is 1.1 h (whole pipeline, A = 9.4, 10.92 h), only
  0.4 h more than gap_5's 0.7 h margin (`gap_5.md:124`). It spends the slack gap_5 wanted for 5.5-6.0 min
  (`gap_5.md:134-138`: m = 1.3 already breaks the 6.0 case).
- **So the real cost is not the clock, it is the capped share.** v10 single already has 68-80% of hidden tasks at the cap,
  and parallel k=2 pushes that to 68-88% (+0 to +14 points: fixer-only at the measured +40 s slowest branch adds +6 to +9, whole-pipeline k=2 adds +8 to +14).

## 10. Data caveat: h100b

- `cmp` confirms `eval/h100b/runs/p_v4/task_results.jsonl` = `eval/eval3/eval/runs/p_v4/task_results.jsonl`. The same holds for
  **p_v6**, and every p_v4 patch file is identical.
- own_data's extractor lists 14 runs (race1 x 8, fair x 4, kaggle e74_v2/e74_v3; `scratchpad/own/extract.py:10-16`) and
  **does not include h100b**.
- Recomputed union over those 14 runs on the 74 valid tasks: **38**. It is 39 if the fair runs use the Kaggle-env rescore.
  Adding the h100b copies leaves 38, since a union ignores duplicates.
- `grep h100b research/*.md eval/ledger.md` returns nothing. **No reported replicate count, variance or union is
  contaminated.** Anything that counts runs (e.g. "solved by k of n runs") must still exclude h100b.

## 11. Decision

**Neither Parallel k=2 nor a LoopAgent retry. At most, a conditional second fixer stage, and only after the single-run fixes.**

1. **Parallel k=2: no.**
   - Its offline value (+2.6/51 against the mean arm) needs independent budgets and independent failure. Inside one task it
     shrinks to +0.5 to +1.1/51 on public-like tasks and turns negative (-1.0 to -3.7/51) under the hidden-set fit that
     brackets sub3.
   - It also needs a branch that works without `read_file`/`edit_file`, doubles exposure to the overflow that discards the
     patch, and raises the capped share by up to 14 points (+6 to +14 at the measured slowest-branch costs, sect. 9).
   - The gate never separated two gated candidates (0 informative pairs), and the length rule did not replicate (0.487). So
     for a v10 x2, the selector adds nothing measurable beyond "take the non-empty one".
2. **LoopAgent retry: not buildable as described.** There is no escalate tool, so `max_iterations: 2` always runs 2 passes.
3. **Conditional second fixer stage: optional, small, low risk.**
   - Appended to the existing SequentialAgent.
   - It first reads a verdict file that gate.py writes. It stops with no tool call when the final gate PASSed and the patch is
     non-empty. It runs a fresh fixer only on FAIL or an empty patch, and only if `get_status` shows 90 s or more left.
   - Replay: +0.67/51 on public-like L4 (6 wins / 2 losses), +0.17/51 at hidden k=2.9, 0 at k=4.6. It costs about 5 s per
     task where it does not fire, and fits the 12 h at 5.0 min.
   - Two refinements, both untested:
     - own_data sect. 8 (`own_data.md:498`) reports that FAIL-then-PASS repairs inside v9_eog resolved 2 of 3. Continuing
       from A's patch with the regression list may beat a fresh B.
     - The 15 clean empty finishes suggest the cheaper fix is a "never finish without a source edit" rule in the fixer prompt.
4. **Take instead the parts of the replay that work in a single run:**
   - Treat a final gate FAIL as "keep fixing", not "submit" (FAIL resolves 1/15).
   - Strip test-file hunks before `submit_patch`. Not touching tests was right in 13 of 14 decisive pairs. "Failed to apply
     test_patch" ended 4 of 380 race-1 runs (r_v9_c 1, r_v9_eo 2, c_v9_eg 1: fastapi_14077 x2, fastapi_14492, fastapi_15588)
     and 1 of 296 fair runs (p_v6, in both `eval3` and `rescore_fair`). The brief says 4 fair rescores failed this way, but
     the other 3 `rescore_fair` errors read "Evaluation error: 'utf-8' codec can't encode" (p_v7 x1, p_v8 x2), so that
     cause is UNVERIFIED. This is not replayable offline: the gain is UNVERIFIED and bounded by about 1% of runs.
   - Attack the empty-patch causes directly: turn-cap spirals, context overflow, clean no-edit finishes. They are where 45 of
     the 60 selection wins came from.

## 12. What would change the decision

- **A replicate race of v9_eog x2 at the Kaggle budget**, same config twice, independently seeded. This is the only data
  that measures same-config k=2 value and whether the gate separates same-config candidates. It needs pod time, so it was not
  run here.
- **An L4 batch probe** (`time_model.md` sect. 8, measurement 1). If alpha is at most 0.05 and per-branch budgets hold the
  slowest branch to about 60 s, the public-like parallel gain rises toward +1.1/51. It still does not fix shared failure.
- **sub4's submit-to-score time** (`gap_5.md` sect. 7). It sets how much cap headroom a retry stage may use.
