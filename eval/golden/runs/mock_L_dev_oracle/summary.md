# Golden eval summary: mock_L_dev_oracle

**CONTROL** | suite L, split dev | model - | providers - | bundle 0e33cc60a1b3

Population: L dev: 2 runnable of 2 tasks (rich 2); SUBSET: 2 of 55 dataset tasks selected with --tasks, not a population rate.

Cases: total 2, ok 2; infra_error share 0.0 %; samples per case 1; cost $0; wall 9.200 s.
Mean live-call latency 0 s (Kaggle 4xL4 reference: mean 2.88 s, median 1.511 s over 7076 calls).
Holdout looks: 0 for suite L (0 with this bundle), 0 in total.

agents-cli check (grade/results_20260930_005958.json): 58 scores compared, 0 mismatches.

## Headlines

| metric | n | mean | 95 % CI |
|---|---|---|---|
| l_all_gold_files_named | 2 | 1 | [0.342, 1.000] |
| x_clean | 2 | 1 | [0.342, 1.000] |

## All metrics (applicable cases only)

| metric | kind | better | n | mean | 95 % CI | median | p90 | total |
|---|---|---|---|---|---|---|---|---|
| l_all_gold_files_named | binary | higher | 2 | 1 | [0.342, 1.000] | - | - | - |
| l_gold_files_named | numeric | higher | 2 | 1 |  | 1 | 1 | 2 |
| l_gold_functions_named | numeric | higher | 1 | 1 |  | 1 | 1 | 1 |
| l_plan_format | binary | higher | 2 | 1 | [0.342, 1.000] | - | - | - |
| l_plan_words | numeric | lower | 2 | 54 |  | 54 | 66 | 108 |
| l_plan_within_words | binary | higher | 2 | 1 | [0.342, 1.000] | - | - | - |
| l_repro_fails_on_original | binary | higher | 2 | 0.500 | [0.095, 0.905] | - | - | - |
| l_repro_valid | binary | higher | 2 | 0.500 | [0.095, 0.905] | - | - | - |
| l_ended_by_text | binary | higher | 2 | 1 | [0.342, 1.000] | - | - | - |
| l_t_end | numeric | lower | 1 | 2 |  | 2 | 2 | 2 |
| l_within_time | binary | higher | 1 | 1 | [0.206, 1.000] | - | - | - |
| l_calls | count | lower | 2 | 0.500 |  | 0.500 | 0.900 | 1 |
| l_within_calls | binary | higher | 2 | 1 | [0.342, 1.000] | - | - | - |
| l_llm_calls | count | lower | 2 | 1.500 |  | 1.500 | 1.900 | 3 |
| l_prompt_tokens | count | lower | 2 | 5405 |  | 5405 | 7159.400 | 10810 |
| x_invented_tool_calls | count | lower | 2 | 0 |  | 0 | 0 | 0 |
| x_bare_helper_calls | count | lower | 2 | 0 |  | 0 | 0 | 0 |
| x_malformed_calls | count | lower | 2 | 0 |  | 0 | 0 | 0 |
| x_forbidden_edit_tools | count | lower | 2 | 0 |  | 0 | 0 | 0 |
| x_edit_helper_failures | count | lower | 2 | 0 |  | 0 | 0 | 0 |
| x_text_tool_calls | count | lower | 2 | 0 |  | 0 | 0 | 0 |
| x_compaction_exceedances | count | lower | 2 | 0 |  | 0 | 0 | 0 |
| x_compactions | count | lower | 2 | 0 |  | 0 | 0 | 0 |
| x_runaway_outputs | count | lower | 2 | 0 |  | 0 | 0 | 0 |
| x_cant_open_file | count | lower | 2 | 0 |  | 0 | 0 | 0 |
| x_crash | binary | lower | 2 | 0 | [0.000, 0.658] | - | - | - |
| x_live_restarts | count | lower | 2 | 0 |  | 0 | 0 | 0 |
| x_capped | binary | lower | 2 | 0 | [0.000, 0.658] | - | - | - |
| x_clean | binary | higher | 2 | 1 | [0.342, 1.000] | - | - | - |

## Headlines by repo

| repo | metric | n | mean | 95 % CI |
|---|---|---|---|---|
| rich | l_all_gold_files_named | 2 | 1 | [0.342, 1.000] |
| rich | x_clean | 2 | 1 | [0.342, 1.000] |

## Headlines by stratum

| stratum | metric | n | mean | 95 % CI |
|---|---|---|---|---|
| rich/none | l_all_gold_files_named | 2 | 1 | [0.342, 1.000] |
| rich/none | x_clean | 2 | 1 | [0.342, 1.000] |

## Headlines by reproducible

| reproducible | metric | n | mean | 95 % CI |
|---|---|---|---|---|
| False | l_all_gold_files_named | 1 | 1 | [0.206, 1.000] |
| False | x_clean | 1 | 1 | [0.206, 1.000] |
| True | l_all_gold_files_named | 1 | 1 | [0.206, 1.000] |
| True | x_clean | 1 | 1 | [0.206, 1.000] |

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
