# Golden eval summary: mock_V_dev_oracle

**CONTROL** | suite V, split dev | model - | providers - | bundle 0e33cc60a1b3

Population: V dev: 1 gradable of 1 runnable of 1 tasks (rich 1); cases gold 1, wrong 1, empty 1; SUBSET: 1 of 55 dataset tasks selected with --tasks, not a population rate.

Cases: total 3, ok 3; infra_error share 0.0 %; samples per case 1; cost $0; wall 12.600 s.
Mean live-call latency 0 s (Kaggle 4xL4 reference: mean 2.88 s, median 1.511 s over 7076 calls).
Holdout looks: 0 for suite V (0 with this bundle), 0 in total.

agents-cli check (grade/results_20260930_010006.json): 81 scores compared, 0 mismatches.

## Headlines

| metric | n | mean | 95 % CI |
|---|---|---|---|
| v_variant_goal | 3 | 1 | [0.439, 1.000] |
| x_clean | 3 | 1 | [0.439, 1.000] |

## All metrics (applicable cases only)

| metric | kind | better | n | mean | 95 % CI | median | p90 | total |
|---|---|---|---|---|---|---|---|---|
| v_variant_goal | binary | higher | 3 | 1 | [0.439, 1.000] | - | - | - |
| v_hidden_pass | binary | higher | 3 | 1 | [0.439, 1.000] | - | - | - |
| v_not_worse | binary | higher | 3 | 1 | [0.439, 1.000] | - | - | - |
| v_hidden_nodes_delta | numeric | higher | 3 | 0.667 |  | 1 | 1 | 2 |
| v_submitted_by_verifier | binary | higher | 3 | 1 | [0.439, 1.000] | - | - | - |
| v_finalize_before_submit | binary | higher | 3 | 1 | [0.439, 1.000] | - | - | - |
| v_no_protected | binary | higher | 3 | 1 | [0.439, 1.000] | - | - | - |
| v_no_scratch | binary | higher | 3 | 1 | [0.439, 1.000] | - | - | - |
| v_ended_by_text | binary | higher | 3 | 1 | [0.439, 1.000] | - | - | - |
| v_t_end | numeric | lower | 3 | 91.667 |  | 92 | 92 | 275 |
| v_calls | count | lower | 3 | 4.333 |  | 4 | 4.800 | 13 |
| v_llm_calls | count | lower | 3 | 5.333 |  | 5 | 5.800 | 16 |
| v_prompt_tokens | count | lower | 3 | 22176.333 |  | 20857 | 24129.800 | 66529 |
| x_invented_tool_calls | count | lower | 3 | 0 |  | 0 | 0 | 0 |
| x_bare_helper_calls | count | lower | 3 | 0 |  | 0 | 0 | 0 |
| x_malformed_calls | count | lower | 3 | 0 |  | 0 | 0 | 0 |
| x_forbidden_edit_tools | count | lower | 3 | 0 |  | 0 | 0 | 0 |
| x_edit_helper_failures | count | lower | 3 | 0 |  | 0 | 0 | 0 |
| x_text_tool_calls | count | lower | 3 | 0 |  | 0 | 0 | 0 |
| x_compaction_exceedances | count | lower | 3 | 0 |  | 0 | 0 | 0 |
| x_compactions | count | lower | 3 | 0 |  | 0 | 0 | 0 |
| x_runaway_outputs | count | lower | 3 | 0 |  | 0 | 0 | 0 |
| x_cant_open_file | count | lower | 3 | 0 |  | 0 | 0 | 0 |
| x_crash | binary | lower | 3 | 0 | [0.000, 0.561] | - | - | - |
| x_live_restarts | count | lower | 3 | 0 |  | 0 | 0 | 0 |
| x_capped | binary | lower | 3 | 0 | [0.000, 0.561] | - | - | - |
| x_clean | binary | higher | 3 | 1 | [0.439, 1.000] | - | - | - |

## Headlines by repo

| repo | metric | n | mean | 95 % CI |
|---|---|---|---|---|
| rich | v_variant_goal | 3 | 1 | [0.439, 1.000] |
| rich | x_clean | 3 | 1 | [0.439, 1.000] |

## Headlines by stratum

| stratum | metric | n | mean | 95 % CI |
|---|---|---|---|---|
| rich/none | v_variant_goal | 3 | 1 | [0.439, 1.000] |
| rich/none | x_clean | 3 | 1 | [0.439, 1.000] |

## Headlines by variant

| variant | metric | n | mean | 95 % CI |
|---|---|---|---|---|
| empty | v_variant_goal | 1 | 1 | [0.206, 1.000] |
| empty | x_clean | 1 | 1 | [0.206, 1.000] |
| gold | v_variant_goal | 1 | 1 | [0.206, 1.000] |
| gold | x_clean | 1 | 1 | [0.206, 1.000] |
| wrong | v_variant_goal | 1 | 1 | [0.206, 1.000] |
| wrong | x_clean | 1 | 1 | [0.206, 1.000] |

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
