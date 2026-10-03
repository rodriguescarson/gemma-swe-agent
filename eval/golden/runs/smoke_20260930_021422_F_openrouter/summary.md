# Golden eval summary: smoke_20260930_021422_F_openrouter

**PROXY** | suite F, split dev | model google/gemma-4-31b-it | providers Crusoe | bundle 0e33cc60a1b3

Population: F dev: 2 gradable of 2 runnable of 2 tasks (rich 2); SUBSET: 2 of 55 dataset tasks selected with --tasks, not a population rate.

Cases: total 2, infra_error 1, ok 1; infra_error share 50.0 %; samples per case 1; cost $0.014; wall 269 s.
Mean live-call latency 11.164 s (Kaggle 4xL4 reference: mean 2.88 s, median 1.511 s over 7076 calls).
Holdout looks: 0 for suite F (0 with this bundle), 0 in total.

agents-cli check (grade/results_20260930_022534.json): 118 scores compared, 0 mismatches.

## Headlines

| metric | n | mean | 95 % CI |
|---|---|---|---|
| f_hidden_pass | 1 | 1 | [0.206, 1.000] |
| x_clean | 1 | 1 | [0.206, 1.000] |

## All metrics (applicable cases only)

| metric | kind | better | n | mean | 95 % CI | median | p90 | total |
|---|---|---|---|---|---|---|---|---|
| f_hidden_pass | binary | higher | 1 | 1 | [0.206, 1.000] | - | - | - |
| f_touches_all_gold_files | binary | higher | 1 | 1 | [0.206, 1.000] | - | - | - |
| f_gold_files_touched | numeric | higher | 1 | 1 |  | 1 | 1 | 1 |
| f_nonempty | binary | higher | 1 | 1 | [0.206, 1.000] | - | - | - |
| f_applies | binary | higher | 1 | 1 | [0.206, 1.000] | - | - | - |
| f_compiles | binary | higher | 1 | 1 | [0.206, 1.000] | - | - | - |
| f_no_protected | binary | higher | 1 | 1 | [0.206, 1.000] | - | - | - |
| f_no_scratch | binary | higher | 1 | 1 | [0.206, 1.000] | - | - | - |
| f_notes_format | binary | higher | 1 | 1 | [0.206, 1.000] | - | - | - |
| f_ended_by_text | binary | higher | 1 | 1 | [0.206, 1.000] | - | - | - |
| f_first_edit_t | numeric | lower | 1 | 120 |  | 120 | 120 | 120 |
| f_first_edit_in_time | binary | higher | 1 | 1 | [0.206, 1.000] | - | - | - |
| f_verify_rounds | count | higher | 1 | 1 |  | 1 | 1 | 1 |
| f_t_end | numeric | lower | 1 | 125 |  | 125 | 125 | 125 |
| f_calls | count | lower | 1 | 5 |  | 5 | 5 | 5 |
| f_llm_calls | count | lower | 1 | 7 |  | 7 | 7 | 7 |
| f_prompt_tokens | count | lower | 1 | 21886 |  | 21886 | 21886 | 21886 |
| x_invented_tool_calls | count | lower | 1 | 0 |  | 0 | 0 | 0 |
| x_bare_helper_calls | count | lower | 1 | 0 |  | 0 | 0 | 0 |
| x_malformed_calls | count | lower | 1 | 0 |  | 0 | 0 | 0 |
| x_forbidden_edit_tools | count | lower | 1 | 0 |  | 0 | 0 | 0 |
| x_edit_helper_failures | count | lower | 1 | 0 |  | 0 | 0 | 0 |
| x_text_tool_calls | count | lower | 1 | 0 |  | 0 | 0 | 0 |
| x_compaction_exceedances | count | lower | 1 | 0 |  | 0 | 0 | 0 |
| x_compactions | count | lower | 1 | 0 |  | 0 | 0 | 0 |
| x_runaway_outputs | count | lower | 1 | 0 |  | 0 | 0 | 0 |
| x_cant_open_file | count | lower | 1 | 0 |  | 0 | 0 | 0 |
| x_crash | binary | lower | 1 | 0 | [0.000, 0.793] | - | - | - |
| x_live_restarts | count | lower | 1 | 0 |  | 0 | 0 | 0 |
| x_capped | binary | lower | 1 | 0 | [0.000, 0.793] | - | - | - |
| x_clean | binary | higher | 1 | 1 | [0.206, 1.000] | - | - | - |

## Headlines by repo

| repo | metric | n | mean | 95 % CI |
|---|---|---|---|---|
| rich | f_hidden_pass | 1 | 1 | [0.206, 1.000] |
| rich | x_clean | 1 | 1 | [0.206, 1.000] |

## Headlines by stratum

| stratum | metric | n | mean | 95 % CI |
|---|---|---|---|---|
| rich/none | f_hidden_pass | 1 | 1 | [0.206, 1.000] |
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
