# Golden eval summary: F_dev_A0p

**PROXY** | suite F, split dev | model google/gemma-4-31b-it | providers Crusoe | bundle 11f56bebb13b

Population: F dev: 29 gradable of 30 runnable of 55 tasks (rich 29); fastapi 0 of 23 runnable: snapshot missing: data/raw/snapshots/fastapi_13537.tgz; rich 29 of 31 runnable: snapshot missing: data/raw/snapshots/rich_4077.tgz.

Cases: total 165, skipped 78, ok 85, infra_error 2; infra_error share 2.3 %; samples per case 3; cost $0.672; wall 7039.800 s.
Mean live-call latency 15.376 s (Kaggle 4xL4 reference: mean 2.88 s, median 1.511 s over 7076 calls).
Holdout looks: 0 for suite F (0 with this bundle), 0 in total.

agents-cli check (grade/results_20260930_080452.json): 5115 scores compared, 0 mismatches.

## Headlines

| metric | n | mean | 95 % CI |
|---|---|---|---|
| f_hidden_pass | 29 | 0.793 | [0.655, 0.908] boot |
| x_clean | 29 | 0.862 | [0.747, 0.954] boot |

## All metrics (applicable cases only)

| metric | kind | better | n | mean | 95 % CI | median | p90 | total |
|---|---|---|---|---|---|---|---|---|
| f_hidden_pass | binary | higher | 29 | 0.793 | [0.655, 0.908] boot | - | - | - |
| f_touches_all_gold_files | binary | higher | 29 | 0.793 | [0.655, 0.919] boot | - | - | - |
| f_gold_files_touched | numeric | higher | 29 | 0.879 | [0.799, 0.948] boot | 1 | 1 | 25.500 |
| f_nonempty | binary | higher | 29 | 0.966 | [0.931, 1.000] boot | - | - | - |
| f_applies | binary | higher | 29 | 1 | [1.000, 1.000] boot | - | - | - |
| f_compiles | binary | higher | 29 | 1 | [1.000, 1.000] boot | - | - | - |
| f_no_protected | binary | higher | 29 | 1 | [1.000, 1.000] boot | - | - | - |
| f_no_scratch | binary | higher | 29 | 1 | [1.000, 1.000] boot | - | - | - |
| f_notes_format | binary | higher | 29 | 0.862 | [0.770, 0.943] boot | - | - | - |
| f_ended_by_text | binary | higher | 29 | 1 | [1.000, 1.000] boot | - | - | - |
| f_first_edit_t | numeric | lower | 29 | 110.954 | [94.452, 128.084] boot | 87.667 | 165.400 | 3217.667 |
| f_first_edit_in_time | binary | higher | 29 | 0.753 | [0.632, 0.862] boot | - | - | - |
| f_verify_rounds | count | higher | 29 | 1.115 | [0.943, 1.310] boot | 1 | 1.733 | 32.333 |
| f_t_end | numeric | lower | 29 | 165.644 | [141.791, 190.484] boot | 156 | 263.867 | 4803.667 |
| f_calls | count | lower | 29 | 7.563 | [5.149, 10.644] boot | 4.667 | 15.333 | 219.333 |
| f_llm_calls | count | lower | 29 | 8.667 | [6.299, 11.701] boot | 5.667 | 16.400 | 251.333 |
| f_prompt_tokens | count | lower | 29 | 47098.494 | [27291.714, 71807.284] boot | 21173.667 | 119271.267 | 1365856.333 |
| x_invented_tool_calls | count | lower | 29 | 0 | [0.000, 0.000] boot | 0 | 0 | 0 |
| x_bare_helper_calls | count | lower | 29 | 0 | [0.000, 0.000] boot | 0 | 0 | 0 |
| x_malformed_calls | count | lower | 29 | 0.011 | [0.000, 0.035] boot | 0 | 0 | 0.333 |
| x_forbidden_edit_tools | count | lower | 29 | 0 | [0.000, 0.000] boot | 0 | 0 | 0 |
| x_edit_helper_failures | count | lower | 29 | 0.276 | [0.058, 0.540] boot | 0 | 0.933 | 8 |
| x_text_tool_calls | count | lower | 29 | 0 | [0.000, 0.000] boot | 0 | 0 | 0 |
| x_compaction_exceedances | count | lower | 29 | 0.046 | [0.000, 0.126] boot | 0 | 0 | 1.333 |
| x_compactions | count | lower | 29 | 0.046 | [0.000, 0.126] boot | 0 | 0 | 1.333 |
| x_runaway_outputs | count | lower | 29 | 0 | [0.000, 0.000] boot | 0 | 0 | 0 |
| x_cant_open_file | count | lower | 29 | 0 | [0.000, 0.000] boot | 0 | 0 | 0 |
| x_crash | binary | lower | 29 | 0 | [0.000, 0.000] boot | - | - | - |
| x_live_restarts | count | lower | 29 | 0 | [0.000, 0.000] boot | 0 | 0 | 0 |
| x_capped | binary | lower | 29 | 0.138 | [0.058, 0.230] boot | - | - | - |
| x_clean | binary | higher | 29 | 0.862 | [0.747, 0.954] boot | - | - | - |

## Headlines by repo

| repo | metric | n | mean | 95 % CI |
|---|---|---|---|---|
| rich | f_hidden_pass | 29 | 0.793 | [0.655, 0.908] boot |
| rich | x_clean | 29 | 0.862 | [0.747, 0.954] boot |

## Headlines by stratum

| stratum | metric | n | mean | 95 % CI |
|---|---|---|---|---|
| rich/both | f_hidden_pass | 6 | 1 | [1.000, 1.000] boot |
| rich/both | x_clean | 6 | 0.889 | [0.778, 1.000] boot |
| rich/none | f_hidden_pass | 20 | 0.767 | [0.583, 0.917] boot |
| rich/none | x_clean | 20 | 0.833 | [0.667, 0.967] boot |
| rich/one | f_hidden_pass | 3 | 0.556 | [0.000, 1.000] boot |
| rich/one | x_clean | 3 | 1 | [1.000, 1.000] boot |

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
