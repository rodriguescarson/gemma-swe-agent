# Golden eval summary: F_dev_B2

**PROXY** | suite F, split dev | model google/gemma-4-31b-it | providers Crusoe | bundle 0e33cc60a1b3

Population: F dev: 29 gradable of 30 runnable of 55 tasks (rich 29); fastapi 0 of 23 runnable: snapshot missing: data/raw/snapshots/fastapi_13537.tgz; rich 29 of 31 runnable: snapshot missing: data/raw/snapshots/rich_4077.tgz.

Cases: total 165, skipped 78, ok 87; infra_error share 0.0 %; samples per case 3; cost $0.857; wall 10820 s.
Mean live-call latency 14.053 s (Kaggle 4xL4 reference: mean 2.88 s, median 1.511 s over 7076 calls).
Holdout looks: 0 for suite F (0 with this bundle), 0 in total.

agents-cli check (grade/results_20260930_083032.json): 5115 scores compared, 0 mismatches.

## Headlines

| metric | n | mean | 95 % CI |
|---|---|---|---|
| f_hidden_pass | 29 | 0.759 | [0.632, 0.885] boot |
| x_clean | 29 | 0.816 | [0.701, 0.919] boot |

## All metrics (applicable cases only)

| metric | kind | better | n | mean | 95 % CI | median | p90 | total |
|---|---|---|---|---|---|---|---|---|
| f_hidden_pass | binary | higher | 29 | 0.759 | [0.632, 0.885] boot | - | - | - |
| f_touches_all_gold_files | binary | higher | 29 | 0.759 | [0.621, 0.885] boot | - | - | - |
| f_gold_files_touched | numeric | higher | 29 | 0.851 | [0.770, 0.925] boot | 1 | 1 | 24.667 |
| f_nonempty | binary | higher | 29 | 0.943 | [0.885, 0.989] boot | - | - | - |
| f_applies | binary | higher | 29 | 1 | [1.000, 1.000] boot | - | - | - |
| f_compiles | binary | higher | 29 | 1 | [1.000, 1.000] boot | - | - | - |
| f_no_protected | binary | higher | 29 | 1 | [1.000, 1.000] boot | - | - | - |
| f_no_scratch | binary | higher | 29 | 1 | [1.000, 1.000] boot | - | - | - |
| f_notes_format | binary | higher | 29 | 0.828 | [0.747, 0.908] boot | - | - | - |
| f_ended_by_text | binary | higher | 29 | 1 | [1.000, 1.000] boot | - | - | - |
| f_first_edit_t | numeric | lower | 29 | 116.305 | [96.957, 137.570] boot | 92 | 218 | 3372.833 |
| f_first_edit_in_time | binary | higher | 29 | 0.736 | [0.615, 0.851] boot | - | - | - |
| f_verify_rounds | count | higher | 29 | 1.207 | [1.000, 1.471] boot | 1 | 1.733 | 35 |
| f_t_end | numeric | lower | 29 | 175.506 | [150.258, 200.667] boot | 179.333 | 267.200 | 5089.667 |
| f_calls | count | lower | 29 | 9.540 | [5.609, 16.116] boot | 5.667 | 14.267 | 276.667 |
| f_llm_calls | count | lower | 29 | 10.816 | [6.931, 17.347] boot | 6.667 | 15.800 | 313.667 |
| f_prompt_tokens | count | lower | 29 | 65721.954 | [31056.080, 123725.376] boot | 25991 | 112893.067 | 1905936.667 |
| x_invented_tool_calls | count | lower | 29 | 0 | [0.000, 0.000] boot | 0 | 0 | 0 |
| x_bare_helper_calls | count | lower | 29 | 0 | [0.000, 0.000] boot | 0 | 0 | 0 |
| x_malformed_calls | count | lower | 29 | 0.023 | [0.000, 0.069] boot | 0 | 0 | 0.667 |
| x_forbidden_edit_tools | count | lower | 29 | 0 | [0.000, 0.000] boot | 0 | 0 | 0 |
| x_edit_helper_failures | count | lower | 29 | 0.184 | [0.046, 0.356] boot | 0 | 0.667 | 5.333 |
| x_text_tool_calls | count | lower | 29 | 0 | [0.000, 0.000] boot | 0 | 0 | 0 |
| x_compaction_exceedances | count | lower | 29 | 0.023 | [0.000, 0.058] boot | 0 | 0 | 0.667 |
| x_compactions | count | lower | 29 | 0 | [0.000, 0.000] boot | 0 | 0 | 0 |
| x_runaway_outputs | count | lower | 29 | 0 | [0.000, 0.000] boot | 0 | 0 | 0 |
| x_cant_open_file | count | lower | 29 | 0.011 | [0.000, 0.035] boot | 0 | 0 | 0.333 |
| x_crash | binary | lower | 29 | 0 | [0.000, 0.000] boot | - | - | - |
| x_live_restarts | count | lower | 29 | 0 | [0.000, 0.000] boot | 0 | 0 | 0 |
| x_capped | binary | lower | 29 | 0.149 | [0.069, 0.230] boot | - | - | - |
| x_clean | binary | higher | 29 | 0.816 | [0.701, 0.919] boot | - | - | - |

## Headlines by repo

| repo | metric | n | mean | 95 % CI |
|---|---|---|---|---|
| rich | f_hidden_pass | 29 | 0.759 | [0.632, 0.885] boot |
| rich | x_clean | 29 | 0.816 | [0.701, 0.919] boot |

## Headlines by stratum

| stratum | metric | n | mean | 95 % CI |
|---|---|---|---|---|
| rich/both | f_hidden_pass | 6 | 0.944 | [0.833, 1.000] boot |
| rich/both | x_clean | 6 | 0.889 | [0.667, 1.000] boot |
| rich/none | f_hidden_pass | 20 | 0.733 | [0.567, 0.883] boot |
| rich/none | x_clean | 20 | 0.783 | [0.617, 0.917] boot |
| rich/one | f_hidden_pass | 3 | 0.556 | [0.000, 1.000] boot |
| rich/one | x_clean | 3 | 0.889 | [0.667, 1.000] boot |

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
