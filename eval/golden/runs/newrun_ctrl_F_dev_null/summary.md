# Golden eval summary: newrun_ctrl_F_dev_null

**CONTROL** | suite F, split dev | model - | providers - | bundle 0e33cc60a1b3

Population: F dev: 23 gradable of 25 runnable of 25 tasks (fastapi 21, rich 2); SUBSET: 25 of 55 dataset tasks selected with --tasks, not a population rate.

Cases: total 25, ok 23, skipped 2; infra_error share 0.0 %; samples per case 1; cost $0; wall 92 s.
Mean live-call latency 0 s (Kaggle 4xL4 reference: mean 2.88 s, median 1.511 s over 7076 calls).
Holdout looks: 0 for suite F (0 with this bundle), 0 in total.

agents-cli check: no grade/results_*.json in this run.

## Headlines

| metric | n | mean | 95 % CI |
|---|---|---|---|
| f_hidden_pass | 23 | 0 | [-0.000, 0.143] |
| x_clean | 23 | 1 | [0.857, 1.000] |

## All metrics (applicable cases only)

| metric | kind | better | n | mean | 95 % CI | median | p90 | total |
|---|---|---|---|---|---|---|---|---|
| f_hidden_pass | binary | higher | 23 | 0 | [-0.000, 0.143] | - | - | - |
| f_touches_all_gold_files | binary | higher | 23 | 0 | [-0.000, 0.143] | - | - | - |
| f_gold_files_touched | numeric | higher | 23 | 0 |  | 0 | 0 | 0 |
| f_nonempty | binary | higher | 23 | 0 | [-0.000, 0.143] | - | - | - |
| f_applies | binary | higher | 23 | 1 | [0.857, 1.000] | - | - | - |
| f_compiles | binary | higher | 23 | 1 | [0.857, 1.000] | - | - | - |
| f_no_protected | binary | higher | 23 | 1 | [0.857, 1.000] | - | - | - |
| f_no_scratch | binary | higher | 23 | 1 | [0.857, 1.000] | - | - | - |
| f_notes_format | binary | higher | 23 | 0 | [-0.000, 0.143] | - | - | - |
| f_ended_by_text | binary | higher | 23 | 1 | [0.857, 1.000] | - | - | - |
| f_first_edit_t | numeric | lower | 0 | - |  | - | - | 0 |
| f_first_edit_in_time | binary | higher | 0 | - | [0.000, 0.000] | - | - | - |
| f_verify_rounds | count | higher | 23 | 0 |  | 0 | 0 | 0 |
| f_t_end | numeric | lower | 0 | - |  | - | - | 0 |
| f_calls | count | lower | 23 | 0 |  | 0 | 0 | 0 |
| f_llm_calls | count | lower | 23 | 1 |  | 1 | 1 | 23 |
| f_prompt_tokens | count | lower | 23 | 3779.522 |  | 3573 | 4215.600 | 86929 |
| x_invented_tool_calls | count | lower | 23 | 0 |  | 0 | 0 | 0 |
| x_bare_helper_calls | count | lower | 23 | 0 |  | 0 | 0 | 0 |
| x_malformed_calls | count | lower | 23 | 0 |  | 0 | 0 | 0 |
| x_forbidden_edit_tools | count | lower | 23 | 0 |  | 0 | 0 | 0 |
| x_edit_helper_failures | count | lower | 23 | 0 |  | 0 | 0 | 0 |
| x_text_tool_calls | count | lower | 23 | 0 |  | 0 | 0 | 0 |
| x_compaction_exceedances | count | lower | 23 | 0 |  | 0 | 0 | 0 |
| x_compactions | count | lower | 23 | 0 |  | 0 | 0 | 0 |
| x_runaway_outputs | count | lower | 23 | 0 |  | 0 | 0 | 0 |
| x_cant_open_file | count | lower | 23 | 0 |  | 0 | 0 | 0 |
| x_crash | binary | lower | 23 | 0 | [-0.000, 0.143] | - | - | - |
| x_live_restarts | count | lower | 23 | 0 |  | 0 | 0 | 0 |
| x_capped | binary | lower | 23 | 0 | [-0.000, 0.143] | - | - | - |
| x_clean | binary | higher | 23 | 1 | [0.857, 1.000] | - | - | - |

## Headlines by repo

| repo | metric | n | mean | 95 % CI |
|---|---|---|---|---|
| fastapi | f_hidden_pass | 21 | 0 | [0.000, 0.155] |
| fastapi | x_clean | 21 | 1 | [0.845, 1.000] |
| rich | f_hidden_pass | 2 | 0 | [0.000, 0.658] |
| rich | x_clean | 2 | 1 | [0.342, 1.000] |

## Headlines by stratum

| stratum | metric | n | mean | 95 % CI |
|---|---|---|---|---|
| fastapi/both | f_hidden_pass | 7 | 0 | [0.000, 0.354] |
| fastapi/both | x_clean | 7 | 1 | [0.646, 1.000] |
| fastapi/none | f_hidden_pass | 10 | 0 | [-0.000, 0.278] |
| fastapi/none | x_clean | 10 | 1 | [0.723, 1.000] |
| fastapi/one | f_hidden_pass | 4 | 0 | [0.000, 0.490] |
| fastapi/one | x_clean | 4 | 1 | [0.510, 1.000] |
| rich/both | f_hidden_pass | 1 | 0 | [0.000, 0.793] |
| rich/both | x_clean | 1 | 1 | [0.206, 1.000] |
| rich/none | f_hidden_pass | 1 | 0 | [0.000, 0.793] |
| rich/none | x_clean | 1 | 1 | [0.206, 1.000] |

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
