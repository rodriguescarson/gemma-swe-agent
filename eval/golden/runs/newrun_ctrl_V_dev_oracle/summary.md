# Golden eval summary: newrun_ctrl_V_dev_oracle

**CONTROL** | suite V, split dev | model - | providers - | bundle 0e33cc60a1b3

Population: V dev: 23 gradable of 25 runnable of 25 tasks (fastapi 21, rich 2); cases gold 23, wrong 13, empty 23; SUBSET: 25 of 55 dataset tasks selected with --tasks, not a population rate.

Cases: total 63, ok 59, skipped 4; infra_error share 0.0 %; samples per case 1; cost $0; wall 322.200 s.
Mean live-call latency 0 s (Kaggle 4xL4 reference: mean 2.88 s, median 1.511 s over 7076 calls).
Holdout looks: 0 for suite V (0 with this bundle), 0 in total.

agents-cli check: no grade/results_*.json in this run.

## Headlines

| metric | n | mean | 95 % CI |
|---|---|---|---|
| v_variant_goal | 59 | 1 | [0.939, 1.000] |
| x_clean | 59 | 1 | [0.939, 1.000] |

## All metrics (applicable cases only)

| metric | kind | better | n | mean | 95 % CI | median | p90 | total |
|---|---|---|---|---|---|---|---|---|
| v_variant_goal | binary | higher | 59 | 1 | [0.939, 1.000] | - | - | - |
| v_hidden_pass | binary | higher | 59 | 1 | [0.939, 1.000] | - | - | - |
| v_not_worse | binary | higher | 59 | 1 | [0.939, 1.000] | - | - | - |
| v_hidden_nodes_delta | numeric | higher | 59 | 1.153 |  | 1 | 2.400 | 68 |
| v_submitted_by_verifier | binary | higher | 59 | 1 | [0.939, 1.000] | - | - | - |
| v_finalize_before_submit | binary | higher | 59 | 1 | [0.939, 1.000] | - | - | - |
| v_no_protected | binary | higher | 59 | 1 | [0.939, 1.000] | - | - | - |
| v_no_scratch | binary | higher | 59 | 1 | [0.939, 1.000] | - | - | - |
| v_ended_by_text | binary | higher | 59 | 1 | [0.939, 1.000] | - | - | - |
| v_t_end | numeric | lower | 59 | 92.610 |  | 93 | 94 | 5464 |
| v_calls | count | lower | 59 | 5.271 |  | 4 | 7 | 311 |
| v_llm_calls | count | lower | 59 | 6.271 |  | 5 | 8 | 370 |
| v_prompt_tokens | count | lower | 59 | 32224.746 |  | 23995 | 43466.600 | 1901260 |
| x_invented_tool_calls | count | lower | 59 | 0 |  | 0 | 0 | 0 |
| x_bare_helper_calls | count | lower | 59 | 0 |  | 0 | 0 | 0 |
| x_malformed_calls | count | lower | 59 | 0 |  | 0 | 0 | 0 |
| x_forbidden_edit_tools | count | lower | 59 | 0 |  | 0 | 0 | 0 |
| x_edit_helper_failures | count | lower | 59 | 0 |  | 0 | 0 | 0 |
| x_text_tool_calls | count | lower | 59 | 0 |  | 0 | 0 | 0 |
| x_compaction_exceedances | count | lower | 59 | 0 |  | 0 | 0 | 0 |
| x_compactions | count | lower | 59 | 0 |  | 0 | 0 | 0 |
| x_runaway_outputs | count | lower | 59 | 0 |  | 0 | 0 | 0 |
| x_cant_open_file | count | lower | 59 | 0 |  | 0 | 0 | 0 |
| x_crash | binary | lower | 59 | 0 | [0.000, 0.061] | - | - | - |
| x_live_restarts | count | lower | 59 | 0 |  | 0 | 0 | 0 |
| x_capped | binary | lower | 59 | 0 | [0.000, 0.061] | - | - | - |
| x_clean | binary | higher | 59 | 1 | [0.939, 1.000] | - | - | - |

## Headlines by repo

| repo | metric | n | mean | 95 % CI |
|---|---|---|---|---|
| fastapi | v_variant_goal | 53 | 1 | [0.932, 1.000] |
| fastapi | x_clean | 53 | 1 | [0.932, 1.000] |
| rich | v_variant_goal | 6 | 1 | [0.610, 1.000] |
| rich | x_clean | 6 | 1 | [0.610, 1.000] |

## Headlines by stratum

| stratum | metric | n | mean | 95 % CI |
|---|---|---|---|---|
| fastapi/both | v_variant_goal | 14 | 1 | [0.785, 1.000] |
| fastapi/both | x_clean | 14 | 1 | [0.785, 1.000] |
| fastapi/none | v_variant_goal | 29 | 1 | [0.883, 1.000] |
| fastapi/none | x_clean | 29 | 1 | [0.883, 1.000] |
| fastapi/one | v_variant_goal | 10 | 1 | [0.723, 1.000] |
| fastapi/one | x_clean | 10 | 1 | [0.723, 1.000] |
| rich/both | v_variant_goal | 3 | 1 | [0.439, 1.000] |
| rich/both | x_clean | 3 | 1 | [0.439, 1.000] |
| rich/none | v_variant_goal | 3 | 1 | [0.439, 1.000] |
| rich/none | x_clean | 3 | 1 | [0.439, 1.000] |

## Headlines by variant

| variant | metric | n | mean | 95 % CI |
|---|---|---|---|---|
| empty | v_variant_goal | 23 | 1 | [0.857, 1.000] |
| empty | x_clean | 23 | 1 | [0.857, 1.000] |
| gold | v_variant_goal | 23 | 1 | [0.857, 1.000] |
| gold | x_clean | 23 | 1 | [0.857, 1.000] |
| wrong | v_variant_goal | 13 | 1 | [0.772, 1.000] |
| wrong | x_clean | 13 | 1 | [0.772, 1.000] |

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
