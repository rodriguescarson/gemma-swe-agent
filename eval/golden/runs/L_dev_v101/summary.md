# Golden eval summary: L_dev_v101

**PROXY** | suite L, split dev | model google/gemma-4-31b-it | providers Crusoe | bundle 0e33cc60a1b3

Population: L dev: 30 runnable of 55 tasks (rich 29, requests 1); fastapi 0 of 23 runnable: snapshot missing: data/raw/snapshots/fastapi_13537.tgz; rich 29 of 31 runnable: snapshot missing: data/raw/snapshots/rich_4077.tgz.

Cases: total 55, skipped 26, ok 27, infra_error 2; infra_error share 6.9 %; samples per case 1; cost $0.426; wall 2670.800 s.
Mean live-call latency 10.908 s (Kaggle 4xL4 reference: mean 2.88 s, median 1.511 s over 7076 calls).
Holdout looks: 0 for suite L (0 with this bundle), 0 in total.

agents-cli check (grade/results_20260930_094650.json): 1595 scores compared, 0 mismatches.

## Headlines

| metric | n | mean | 95 % CI |
|---|---|---|---|
| l_all_gold_files_named | 27 | 0.556 | [0.373, 0.724] |
| x_clean | 27 | 0.778 | [0.592, 0.894] |

## All metrics (applicable cases only)

| metric | kind | better | n | mean | 95 % CI | median | p90 | total |
|---|---|---|---|---|---|---|---|---|
| l_all_gold_files_named | binary | higher | 27 | 0.556 | [0.373, 0.724] | - | - | - |
| l_gold_files_named | numeric | higher | 27 | 0.648 |  | 1 | 1 | 17.500 |
| l_gold_functions_named | numeric | higher | 24 | 0.516 |  | 0.500 | 1 | 12.383 |
| l_plan_format | binary | higher | 27 | 0.667 | [0.478, 0.814] | - | - | - |
| l_plan_words | numeric | lower | 27 | 91.963 |  | 68 | 163.200 | 2483 |
| l_plan_within_words | binary | higher | 27 | 0.741 | [0.553, 0.868] | - | - | - |
| l_repro_fails_on_original | binary | higher | 27 | 0.481 | [0.307, 0.660] | - | - | - |
| l_repro_valid | binary | higher | 27 | 0.407 | [0.245, 0.593] | - | - | - |
| l_ended_by_text | binary | higher | 27 | 1 | [0.875, 1.000] | - | - | - |
| l_t_end | numeric | lower | 27 | 129.185 |  | 85 | 302.600 | 3488 |
| l_within_time | binary | higher | 27 | 0.556 | [0.373, 0.724] | - | - | - |
| l_calls | count | lower | 27 | 15.815 |  | 13 | 29.400 | 427 |
| l_within_calls | binary | higher | 27 | 0.444 | [0.276, 0.627] | - | - | - |
| l_llm_calls | count | lower | 27 | 16.778 |  | 14 | 29.800 | 453 |
| l_prompt_tokens | count | lower | 27 | 105650.259 |  | 79086 | 204824.400 | 2852557 |
| x_invented_tool_calls | count | lower | 27 | 0 |  | 0 | 0 | 0 |
| x_bare_helper_calls | count | lower | 27 | 0 |  | 0 | 0 | 0 |
| x_malformed_calls | count | lower | 27 | 0.630 |  | 0 | 0.800 | 17 |
| x_forbidden_edit_tools | count | lower | 27 | 0 |  | 0 | 0 | 0 |
| x_edit_helper_failures | count | lower | 27 | 0 |  | 0 | 0 | 0 |
| x_text_tool_calls | count | lower | 27 | 0 |  | 0 | 0 | 0 |
| x_compaction_exceedances | count | lower | 27 | 0.074 |  | 0 | 0 | 2 |
| x_compactions | count | lower | 27 | 0.037 |  | 0 | 0 | 1 |
| x_runaway_outputs | count | lower | 27 | 0.222 |  | 0 | 1 | 6 |
| x_cant_open_file | count | lower | 27 | 0 |  | 0 | 0 | 0 |
| x_crash | binary | lower | 27 | 0 | [0.000, 0.125] | - | - | - |
| x_live_restarts | count | lower | 27 | 0 |  | 0 | 0 | 0 |
| x_capped | binary | lower | 27 | 0.185 | [0.082, 0.367] | - | - | - |
| x_clean | binary | higher | 27 | 0.778 | [0.592, 0.894] | - | - | - |

## Headlines by repo

| repo | metric | n | mean | 95 % CI |
|---|---|---|---|---|
| rich | l_all_gold_files_named | 27 | 0.556 | [0.373, 0.724] |
| rich | x_clean | 27 | 0.778 | [0.592, 0.894] |

## Headlines by stratum

| stratum | metric | n | mean | 95 % CI |
|---|---|---|---|---|
| rich/both | l_all_gold_files_named | 6 | 0.667 | [0.300, 0.903] |
| rich/both | x_clean | 6 | 0.833 | [0.436, 0.970] |
| rich/none | l_all_gold_files_named | 18 | 0.556 | [0.337, 0.754] |
| rich/none | x_clean | 18 | 0.833 | [0.608, 0.942] |
| rich/one | l_all_gold_files_named | 3 | 0.333 | [0.061, 0.792] |
| rich/one | x_clean | 3 | 0.333 | [0.061, 0.792] |

## Headlines by reproducible

| reproducible | metric | n | mean | 95 % CI |
|---|---|---|---|---|
| False | l_all_gold_files_named | 21 | 0.524 | [0.324, 0.717] |
| False | x_clean | 21 | 0.714 | [0.500, 0.862] |
| True | l_all_gold_files_named | 6 | 0.667 | [0.300, 0.903] |
| True | x_clean | 6 | 1 | [0.610, 1.000] |

## Reading this

Statistics cover applicable cases only; agents-cli's own mean_score also averages the inapplicable zeros, so decisions read this file and `summary.py compare`, never agents-cli's table.

Pre-registered decision rule (spec section 8): adopt a prompt change on PROXY evidence only if, on the dev split, the target suite's headline improves with one-sided sign-test p <= 0.10 and wins - losses >= 3, no X count metric has a higher total, and the other suites' headlines have no 'worse' verdict; then confirm once on the holdout (and FAITHFUL when an L4 is available) before shipping.

## Known deviations

1. PROXY runs use another quantization and tool-call parser: X metrics are indicative, time metrics are comparable to L4 only with --l4-scale set to the measured latency ratio.
2. Journal times of scripted steps are compressed; only the handoff clock is exact.
3. Scripted stages use fewer of the 100 tool calls / 200 turns than real ones.
4. The baseline commit is dated one day back (visible only through git log).
5. A compaction during the live stage summarises scripted events, not a real stage's.
6. The golden plan is better than a real locator's: F measures the fixer's ceiling, not the pipeline.
7. Race-2 repros came from v10.0 helpers and were re-validated with the v10.1 helpers.
8. fastapi (31 tasks) is not runnable until its snapshots and venv exist; every number states its population.
9. The live stage ends at helper t=300 by the router cap; the scripted submit then includes new files (a real timeout's fallback diff would not).
10. Hidden tests run in the kpar venv (Kaggle pip freeze), not the full Kaggle image; requests_6644 differs.
