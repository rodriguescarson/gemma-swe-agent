# Golden evals: user guide

Score a prompt change on one pipeline stage in minutes, with confidence intervals and a paired comparison, instead
of a 3.5 h faithful 74-task run whose resolved count moves by about +-3 tasks between identical runs. Design and
every definition: `docs/eval/GOLDEN_EVALS_SPEC.md` (v1.1). This page is how to use it and how to read what it says.

## What each suite measures

Every suite runs the real `swegemma` Evaluator on an unmodified copy of the bundle. One stage is LIVE (answered by
the model); the stages before and after it are scripted and drive the real helpers, so the live stage sees the same
system prompt, tools, `[prev] said:` message and helper state as in a real run.

| Suite | Live stage | Question it answers | Headline |
|---|---|---|---|
| L | locator | Given the real issue, does the locator find the code and write a failing reproduction? | `l_all_gold_files_named` |
| F | fixer | Given a PERFECT plan, does the fixer's patch pass the hidden tests? (fixer pass@1, its ceiling) | `f_hidden_pass` |
| V | verifier | Given a gold, a wrong or an empty tree, does the verifier keep it, repair it, or fill it, then finalize and submit? | `v_variant_goal` |
| X | every live stage | Is the tool protocol healthy (no invented tools, malformed calls, compaction-line crossings, runaway outputs)? | `x_clean` |

F is the one to watch while fix quality is the binding constraint: plumbing is fixed (helpers 100 %, malformed
edits 0.05 per task), so a fixer prompt change is judged on `f_hidden_pass` with the X metrics as guard rails.

Metrics are computed on the live stage only: its events inside its first stage-run, and the router's live calls. A
metric that does not apply to a case (a suite it is not for, a non-gradable task for F and V, an exec check that
was not computed, an `infra_error` or `skipped` case) scores 0.0 with `applicable: false` and is left out of every
statistic. `model_error` cases count as failures (`f_hidden_pass` 0, `x_crash` 1).

## Metric reference

Source of truth: `eval/golden/golden_metrics.py` (`METRICS`). The generated files in `eval/golden/metrics/` are that
library pasted whole plus a two-line `evaluate`, because agents-cli cannot import a sibling module (below).

| X metric | kind | better | definition |
|---|---|---|---|
| `x_invented_tool_calls` | count | lower | parsed calls to a name outside TOOLS plus text replies whose `<\|tool_call>` name is outside TOOLS (replay_l4 parsed_invented + unparsed_invented) |
| `x_bare_helper_calls` | count | lower | invented calls named like a helper (install, locate, ... status, optional .py or call:) plus run_command lines starting with a bare helper (replay_l4 helper_shell) |
| `x_malformed_calls` | count | lower | tool results containing 'mandatory input parameters are not present' |
| `x_forbidden_edit_tools` | count | lower | edit_file or write_file calls (the prompts forbid them) |
| `x_edit_helper_failures` | count | lower | edit.py results whose verdict line is REFUSED, NO MATCH or REVERTED |
| `x_text_tool_calls` | count | lower | text replies containing `<\|tool_call>` (replay_l4 stage_text_calls) |
| `x_compaction_exceedances` | count | lower | live calls with prompt_tokens >= 14336 (the scorer's compaction line) |
| `x_compactions` | count | lower | _summarizer calls made for a live request of the live agent's first stage-run |
| `x_runaway_outputs` | count | lower | live calls with finish_reason length or completion_tokens >= 95 % of the agent's max_output_tokens |
| `x_cant_open_file` | count | lower | run_command calls mentioning /tmp/swe/ whose result says can't open file (replay_l4 run_kpis cant_open) |
| `x_crash` | binary | lower | golden.crash_class is set (or status model_error) |
| `x_live_restarts` | count | lower | llm_calls served done_after_end for a live agent (a harness restart of the stage) |
| `x_capped` | binary | lower | the router capped the live stage at helper t=300 (served cap); a pacing result, not in x_clean |
| `x_clean` (headline) | binary | higher | every X metric except x_capped is 0 |

| L metric | kind | better | definition |
|---|---|---|---|
| `l_all_gold_files_named` (headline) | binary | higher | the plan names every gold file (exact relative path; ./ or /workspace/ prefix tolerated) |
| `l_gold_files_named` | numeric | higher | fraction of gold files the plan names |
| `l_gold_functions_named` | numeric | higher | fraction of gold functions whose name occurs as a whole word in the plan; inapplicable when every gold change is module level |
| `l_plan_format` | binary | higher | reply starts with FILES: and has lines starting CAUSE, FIX, REPRO and TESTS |
| `l_plan_words` | numeric | lower | whitespace tokens of the plan (inapplicable when there is no reply) |
| `l_plan_within_words` | binary | higher | plan has at most 120 words (inapplicable when there is no reply) |
| `l_repro_fails_on_original` | binary | higher | the locator's last verify.py --repro-only result has a REPRO: line saying fails or hangs on original |
| `l_repro_valid` | binary | higher | exec checks: the locator's reproduction fails on the original tree and passes on the gold tree (0 when it wrote none) |
| `l_ended_by_text` | binary | higher | the stage-run's last event is a text reply without `<\|tool_call>` |
| `l_t_end` | numeric | lower | last [t=Ns] helper footer of the stage-run |
| `l_within_time` | binary | higher | last helper footer <= 90 s |
| `l_calls` | count | lower | tool calls in the stage-run |
| `l_within_calls` | binary | higher | at most 12 tool calls |
| `l_llm_calls` | count | lower | live LLM calls of the locator |
| `l_prompt_tokens` | count | lower | sum of prompt tokens over the live calls |
| `l_l4_s` | numeric | lower | modelled L4 seconds of the live stage-run: sum over its answered live calls of 0.102 + 0.02815 c + 0.000921 u (u uncached prompt tokens) plus the tool gaps between them |
| `l_files_named_n` | count | lower | distinct .py/.pyi path tokens in the plan (descriptive; guards the headline against file lists; inapplicable when there is no reply) |
| `l_gold_files_in_files_line` | binary | higher | every gold file is named in the plan's FILES: section (up to the next ALSO, CAUSE, FIX, REPRO or TESTS line; ALSO excluded) |

| F metric | kind | better | definition |
|---|---|---|---|
| `f_hidden_pass` (headline) | binary | higher | the fixer's patch passes the hidden tests (pass@1 given a perfect plan) |
| `f_touches_all_gold_files` | binary | higher | the patch touches every gold file |
| `f_gold_files_touched` | numeric | higher | fraction of gold files the patch touches |
| `f_nonempty` | binary | higher | the patch changes a .py/.pyi file that is neither protected nor scratch |
| `f_applies` | binary | higher | exec check: the patch applies to the snapshot through the harness pipeline |
| `f_compiles` | binary | higher | exec check: every changed .py compiles |
| `f_no_protected` | binary | higher | no protected file (tests, conftest.py, pyproject.toml, ...) in the patch |
| `f_no_scratch` | binary | higher | no new scratch or vendored file in the patch (replay_l4 scratch_files) |
| `f_notes_format` | binary | higher | reply has a CHANGED: line and a VERIFY: line and at most 60 words |
| `f_ended_by_text` | binary | higher | the stage-run's last event is a text reply without `<\|tool_call>` |
| `f_first_edit_t` | numeric | lower | helper footer of the first edit.py result starting OK (inapplicable without one) |
| `f_first_edit_in_time` | binary | higher | first successful edit at helper t <= 150 s |
| `f_verify_rounds` | count | higher | verify.py runs without --repro-only (descriptive; the prompt asks for 1 or 2) |
| `f_t_end` | numeric | lower | last [t=Ns] helper footer of the stage-run |
| `f_calls` | count | lower | tool calls in the stage-run |
| `f_llm_calls` | count | lower | live LLM calls of the fixer |
| `f_prompt_tokens` | count | lower | sum of prompt tokens over the live calls |
| `f_l4_s` | numeric | lower | modelled L4 seconds of the live stage-run (l_l4_s rule) |

| V metric | kind | better | definition |
|---|---|---|---|
| `v_variant_goal` (headline) | binary | higher | gold and wrong: the final patch passes the hidden tests; empty: it is non-empty (f_nonempty rule) |
| `v_hidden_pass` | binary | higher | the final patch passes the hidden tests |
| `v_not_worse` | binary | higher | hidden nodes passing did not drop from the pre-state, and the patch applies and compiles |
| `v_hidden_nodes_delta` | numeric | higher | hidden nodes passing minus the pre-state's |
| `v_submitted_by_verifier` | binary | higher | a submit_patch call in the verifier's first stage-run |
| `v_finalize_before_submit` | binary | higher | a finalize.py run precedes the verifier's first submit_patch (inapplicable when it never submitted) |
| `v_no_protected` | binary | higher | no protected file in the final patch |
| `v_no_scratch` | binary | higher | no new scratch or vendored file in the final patch |
| `v_ended_by_text` | binary | higher | the stage-run's last event is a text reply without `<\|tool_call>` |
| `v_t_end` | numeric | lower | last [t=Ns] helper footer of the stage-run |
| `v_calls` | count | lower | tool calls in the stage-run |
| `v_llm_calls` | count | lower | live LLM calls of the verifier |
| `v_prompt_tokens` | count | lower | sum of prompt tokens over the live calls |
| `v_l4_s` | numeric | lower | modelled L4 seconds of the live stage-run (l_l4_s rule) |

Where the library is stricter than a one-line reading of spec 7.2, on purpose:

- `l_repro_fails_on_original` reads the `REPRO:` line only. verify.py can also print `IMPORT: ... fails on original
  too` (verify.py:308), which is not a failing reproduction.
- `x_edit_helper_failures` matches REFUSED, NO MATCH or REVERTED at the start of a line. edit.py prints its verdict
  first, and the code it shows after an OK is prefixed `  870| `, so file contents cannot trigger it.
- `x_compactions` gives each summariser call to the next request after it. ADK compacts in a request processor
  before the call that triggers it (`google/adk/flows/llm_flows/compaction.py`), so a summary made just before the
  live stage's first request belongs to the live stage.
- `f_nonempty` (and V's empty-tree goal) counts `.py`/`.pyi` files only; a README-only patch is not a source change.
- A metric that raises never breaks grading: `_score` turns it into `applicable: false` with an `error` detail, and
  `summary.py` lists it and exits 3.

## Commands

```bash
cd /Users/carson/Projects/gemma-swe-agent
# 0. once: all 74 snapshots are local and the three kpar venvs exist (2026-09-30). On a fresh machine:
#    snapshots: tasks.fetch_cmd(tid) (one downloader at a time: FETCH_THREADS=1); venvs: scripts/build_kpar.sh, and
#    fastapi once with the network: G4_KPAR_ONLINE=1 scripts/build_kpar.sh fastapi (offline afterwards, from ~/.cache/uv)
# 1. fixtures (cold about 10 min at -j 6, warm seconds), then prove they are reproducible
.venv/bin/python scripts/golden/build_fixtures.py -j 6
.venv/bin/python scripts/golden/build_fixtures.py --check
.venv/bin/python scripts/golden/gen_config.py && .venv/bin/python scripts/golden/gen_config.py --check
# 2. free controls (must pass before any paid run)
.venv/bin/python scripts/golden/run_suite.py controls --suite F --split dev -j 6
#    two-case end-to-end check of one suite in about 10 s (runner -> traces -> grade -> summary; see "Smoke results")
.venv/bin/python scripts/golden/run_suite.py controls --suite F --split dev --tasks rich_3278,rich_3471 -j 4 --run-id mock
# 3. a paid PROXY run
.venv/bin/python scripts/golden/run_suite.py run --suite F --split dev --endpoint openrouter -j 6 --max-usd 1.00 \
    --bundle submissions/v10 --run-id F_dev_v10_or_s1
# 4. grade (run_suite --grade does 4 and 5), summary, compare
agents-cli eval grade --traces eval/golden/runs/F_dev_v10_or_s1/traces --config eval/golden/eval_config_F.yaml \
    --output eval/golden/runs/F_dev_v10_or_s1/grade --qps 500
.venv/bin/python scripts/golden/summary.py eval/golden/runs/F_dev_v10_or_s1
.venv/bin/python scripts/golden/summary.py compare eval/golden/runs/F_dev_v10_or_s1 eval/golden/runs/F_dev_cand_or_s1
agents-cli eval compare eval/golden/runs/F_dev_v10_or_s1/grade/results_<ts>.json eval/golden/runs/F_dev_cand_or_s1/grade/results_<ts>.json
# holdout, once per final candidate
.venv/bin/python scripts/golden/run_suite.py run --suite F --split holdout --endpoint openrouter --holdout-reason "v11 final"
```

- `-j 6` is the default: each case is a harness child process (ADK, LiteLLM, about 350 MB) plus sandbox helpers and
  pytest, on a 10-core, 16 GB Mac.
- `--qps 500`: agents-cli's default of 15 metric computations per second would take over 2 minutes for 2,000 local
  metric computations. Local metrics are cheap.
- Use the suite's own config (`eval_config_L.yaml`, `_F`, `_V`). `eval_config.yaml` runs every metric and is only
  for a traces directory that mixes suites.
- After editing `golden_metrics.py`, run `gen_config.py`. `gen_config.py --check` (and
  `tests/test_golden_metrics.py`) fails while any generated file is out of date.
- `summary.py` exit codes: 0 ok, 2 refused or unreadable input, 3 a metric raised on some case, 4 agents-cli's
  scores differ from the library's.

## Reading a summary

`summary.py RUN_DIR` writes `summary.json` and `summary.md` next to the run. The header states the label (PROXY,
FAITHFUL or CONTROL), model, providers, bundle sha, cost, wall time, the mean live-call latency next to the Kaggle
4xL4 reference, the number of holdout looks, and the population, for example:

> F dev: 52 gradable of 55 runnable of 55 tasks (rich 31, fastapi 21)

(This guide's example before fastapi became runnable on 2026-09-30: `F dev: 29 gradable of 30 runnable of 55 tasks
(rich 28, requests 1); fastapi 0 of 24 runnable: snapshots missing`.)

Always quote that sentence with the number: a rate without its population is not a result.

A run made with `--tasks` (or `--variants` for V) records the filter and the dataset's task count in `run.json`
(`task_filter`, `variant_filter`, `dataset_tasks`), and the sentence ends with, for example, `SUBSET: 2 of 55
dataset tasks selected with --tasks, not a population rate`. A `--tasks` id or `--variants` value that is not in the
dataset is refused (exit 2) instead of being dropped.

- Each metric is computed over applicable cases only: n, mean, a Wilson 95 % interval for binary metrics (z 1.96,
  the `eval/compare.py` formula), and median and p90 for numeric and count metrics.
- With `--samples > 1` each case's samples are averaged first. The interval is then a case-cluster bootstrap
  (2,000 resamples, `random.Random(20260929)`, so it is identical on every rerun).
- Slices: repo and stratum always, variant for V, and `reproducible` for L (read `l_repro_fails_on_original` on
  `reproducible == True`).
- When `grade/results_*.json` exists, the summary checks agents-cli's score for every case and metric against the
  library and exits 4 on any difference.
- agents-cli's own table averages the inapplicable zeros too, so its `mean_score` is not a rate. Read
  `summary.md`.

## Comparing two runs, and the decision rule

`summary.py compare BASE CAND` pairs cases by `dataset_case_id`. For each metric it reports paired n, the mean
difference, wins, losses and ties (by the metric's `better` direction), and the exact sign test with ties dropped:
one-sided `P(W >= wins)` (the `ab_l4_decide.sign_p` formula) and two-sided `min(1, 2 x smaller tail)`. The verdict is
`better` or `worse` at two-sided p <= 0.05, else `no evidence`.

It refuses (exit 2) when:

- the two runs are from different suites or splits;
- their labels, models or providers seen differ, unless you pass `--allow-mixed` (two PROXY runs served by
  different OpenRouter providers can be different quantizations);
- either run was interrupted (finish it with `--resume` first);
- either run has more than 5 % `infra_error` cases.

Cases whose `fixture_sha` changed between the runs are dropped and listed.

**Transition table.** For a binary metric, read the 2x2 table before the aggregate rate. `compare.json` gives it as
`metrics.<name>.transitions` (`counts` for `1->1`, `0->1`, `1->0`, `0->0`, and `flips` with the case ids of
`0->1` and `1->0`), and `compare.md` prints it for the headline. For `f_hidden_pass`, `0->1` is a case the candidate
newly solves and `1->0` is a correct patch the candidate broke. Wins and losses are the same two cells; ties lump
`1->1` and `0->0` together, which the table keeps apart. A pass rate can rise while the candidate breaks good
patches, and only the `1->0` cell shows that. The table exists only when every paired case has one sample on each
side. With `--samples > 1` the per-case means are not 0 or 1, so read wins, losses and the bootstrap interval.

Temperature is 1.0, so two runs of the SAME bundle also flip cases. Measure that noise floor with a repeat run
before crediting a change with its flips, and read it as a net (up minus down), never as a flip total: a total is
never negative, so comparing a change's net against it is biased against the change.

The pre-registered repair ablation (`docs/eval/ABLATION_REPAIR.md`, read its addendum of 2026-09-30) has its own
command. It pairs the three F dev arms on the cases all three have, takes each case's majority over its samples, and
applies the addendum's rule:

```bash
# writes ablation.json and ablation.md into the B2 run dir
.venv/bin/python scripts/golden/summary.py ablation eval/golden/runs/F_dev_A0 eval/golden/runs/F_dev_B2 \
    eval/golden/runs/F_dev_A0p
```

| quantity | where it comes from |
|---|---|
| net repair solves | A0 -> B2 `f_hidden_pass` transitions: `0->1` minus `1->0`, with the exact one-sided sign test |
| damage | A0 -> B2 `1->0` (measured without finalize: F grades the fixer's raw tree) |
| calibration | A0 -> A0' net: identical arms must not show a KEEP-sized effect (net 3 or more at one-sided p <= 0.10) |
| compliance | share of A0 case samples that edit after their first verify.py (verify.py's RED lines ask for a fix) |

Rule (addendum 2026-09-30): INCONCLUSIVE if calibration fails or more than 10 % of A0 case samples repair anyway;
KEEP if one-sided p <= 0.10, net >= 3 and damage <= 1; CUT if net <= 0; otherwise INCONCLUSIVE (one more A0/B2 pair,
read alone; a second INCONCLUSIVE keeps v10.1 as shipped). The output also prints the superseded original rule's
verdict, both transition tables sliced by `golden.reproducible`, and per-arm pass rates and costs. It refuses arms
whose endpoint, model, provider pin, providers seen, `--upstream-extra`, `--l4-scale`, seed mode, samples, dataset or
filter differ, A0' with another bundle than A0, B2 with A0's bundle, a PROXY arm without a provider pin, and a PROXY
arm at `--l4-scale 1.0` unless `--allow-unscaled`. Either verdict is confirmed with one paired Kaggle-L4 FAITHFUL run
before it ships.

`agents-cli eval compare` is still part of the skill workflow, but it is a key-level JSON diff: it pairs nothing and
tests nothing. Decisions use `summary.py compare`.

**Pre-registered decision rule.** Adopt a prompt change on PROXY evidence only if, on the dev split:

1. the target suite's headline improves with one-sided sign-test p <= 0.10 and wins - losses >= 3;
2. no X count metric has a higher total;
3. the other suites' headlines have no `worse` verdict.

Then confirm once on the holdout (and on FAITHFUL when an L4 is available) before shipping. `compare.json` evaluates
points 1 and 2 for its own suite (`decision_rule.eligible_on_this_suite`). Point 3 needs the other suites' compares.

Power, so the rule is read correctly: with about 29 paired dev cases at 1 sample, calling a change takes at least 5
wins and 0 losses (one-sided p = 0.031) or 8 wins to 1 loss (p = 0.020). A single-sample binary headline on 29 cases
has a Wilson interval about +-0.17 wide at 0.5. The stages run at temperature 1.0, so use `--samples 3` for decisions
(3x the cost: about $1.54 per F dev run at the pinned provider's prices; pass `--max-usd 2.00`).

## PROXY, FAITHFUL, CONTROL

| Label | Endpoint | What it is good for |
|---|---|---|
| PROXY | `openrouter`: `google/gemma-4-31b-it`, pinned by default to the `crusoe/bf16` endpoint with fallbacks off (`--or-provider NAME` pins another, `--or-provider any` lifts the pin), OpenRouter's tool-call parser; cost is OpenRouter's billed `usage.cost` | Fast, cheap iteration. Fix-quality and plan metrics transfer best. X metrics are indicative only: the scorer uses the QAT w4a16 model and vLLM's gemma4 tool parser, so protocol failures can differ. Time metrics are comparable to L4 only with `--l4-scale` set to the measured latency ratio (the header prints both latencies). |
| FAITHFUL | `vllm` on a pod or a Kaggle L4 with `gemma-4-31b-it-qat-w4a16-ct` | The confirmation run before shipping. Not exercised in this workflow (no pods, no Kaggle pushes). |
| CONTROL | `oracle` (scripted golden answer) or `null` (every live request answered "done") | Free checks that the runner and grader work: oracle F and V pass 100 %, null F passes 0 %, and so on (spec 5.9). A control that misses its expectation means the harness or grader is wrong, never the model. |

Never compare across labels without `--allow-mixed`, and never read a mixed comparison as a model result.

## Budget, resume and interrupts

- **PROXY is pinned.** On 2026-09-30 OpenRouter listed 15 endpoints for `google/gemma-4-31b-it` across fp4, fp8,
  bf16 and unknown quantizations, from $0.08 to $0.75 per M input tokens. Unpinned, two arms of one comparison can be
  served by different quantizations. Every openrouter run is therefore pinned to `crusoe/bf16` (bf16, tools,
  tool_choice, reasoning and seed supported, $0.14/$0.40 per M) with `allow_fallbacks: false` unless `--or-provider`
  says otherwise. `run.json` records the pin (`or_provider`) and the providers that answered (`providers_seen`).
- **Cost is what OpenRouter bills.** OpenRouter includes `usage.cost` in every reply (usage accounting is on by
  default; the old `usage: {include: true}` flag is deprecated). The router budgets on that figure
  (`cost_source: billed` in `router.jsonl`) and falls back to tokens x `--price-in/--price-out` (default the pinned
  endpoint's $0.14/$0.40) only when a reply lacks it (`cost_source: estimate`).
- **Caps.** `--max-usd` caps openrouter runs (default $1.00). vllm (FAITHFUL) costs nothing per token: it is uncapped
  unless you pass `--max-usd`, its `spent_usd` is 0, and the token-price figure is recorded as
  `est_usd_at_proxy_prices`. Controls are never capped.
- **Refused before start.** A capped run first estimates its cost (race-2 tokens per live stage x the endpoint's
  prices x the case samples it will actually run) and refuses (exit 2, nothing launched) when the estimate plus what
  the run already spent exceeds `--max-usd`, printing the value to pass (the estimate plus 25 %). Estimates at the
  pinned prices, dev split:

  | run | cases | estimate at 1 sample | `--max-usd` for 1 sample | estimate at `--samples 3` | `--max-usd` for 3 samples |
  |---|---|---|---|---|---|
  | L | 30 | $0.47 | 0.60 | $1.41 | 1.78 |
  | F | 29 | $0.51 | 0.66 | $1.54 | 1.94 |
  | V | 82 | $0.89 | 1.12 (above the $1.00 default) | $2.66 | 3.34 |
  | each repair-ablation arm (F, `--samples 3`) | 29 | | | $1.54 | 2.00 |

- **Resume.** `--resume` refuses (exit 2) when the endpoint, upstream base or model, provider pin, `--upstream-extra`,
  seed mode, samples, `--l4-scale`, dataset, `--tasks`/`--variants` filter, agent environment, `--faithful-env` or
  `--harness-verify` differ from the run.json it continues: the cases would be mixed and relabelled. A case that is
  re-run keeps its earlier attempt under `<run>/attempts/<case>.attempt<N>/` (logs, router log, flat record);
  `spent_usd` sums every attempt, the budget starts at what the run already spent (so `--max-usd` caps the run's
  total), and `wall_s` counts active time only, not the gap between invocations. Each case's `meta.json` records the
  endpoint, label, model and pin that served it, and the flat record and trace read them from there.
- **Ctrl-C or SIGTERM** stops launching, cancels the queued cases, kills the live children's process groups, writes
  the partial run (exec checks, flat records, traces) with `status: interrupted`, and exits 130. Killed cases are
  `infra_error: interrupted`; queued ones have no record yet. `summary.py compare` and `ablation` refuse an
  interrupted run; continue it with the same command plus `--resume`.

## Holdout protocol

- The split is per task and shared by all suites: 19 of 74 tasks are holdout, stratified by repo and race-2
  outcome, chosen by `sha256("golden-v1:<tid>")` order (spec section 2). A holdout task never appears in a dev suite.
- Tune on dev only. Grade the holdout once, when a candidate is final.
- `run_suite.py` refuses `--split holdout` without `--holdout-reason TEXT` and appends every holdout run to
  `eval/golden/holdout_log.jsonl`.
- Every summary prints how many holdout looks the suite has had, in total and for the bundle being scored. If that
  number grows while you are still tuning, the holdout is turning into a dev set.

## Cost and time

ESTIMATES, until the smoke step (`run_suite.py smoke --endpoint openrouter`, cap $0.40) measures per-call latency
and cost. Replace this table with the smoke's numbers. Cost per case = r2_v10_1 per-stage tokens x the pinned
endpoint's prices ($0.14/M in, $0.40/M out; the first version of this table used $0.09/$0.34, a fp4 endpoint without
tools that never serves these requests): locator mean $0.0157, fixer $0.0177, verifier $0.0108.

| run (dev, runnable today, 1 sample) | cases | OpenRouter cost | OpenRouter wall at -j 6 | L4 FAITHFUL wall at -j 4 (projection) |
|---|---|---|---|---|
| L | 30 | about $0.47 | 8-10 min | 12-15 min |
| F | 29 gradable | about $0.51 | 8-10 min | 12-15 min |
| V (3 variants) | 82 | about $0.89 (pass `--max-usd 1.12`) | 15-20 min | 35-45 min |
| controls (oracle + null, one suite) | 2 x n | $0 | 6-10 min | n/a |
| holdout (any suite) | about 1/3 of dev (10 of 30 runnable) | about 1/3 of dev | about 1/3 of dev | |

Grading was measured on 2026-09-29. One `agents-cli eval grade` of a synthetic 8-case set with all 59 metrics took
about 7 s warm (21 s on the first run after install, which is Python import time). Most of it is agents-cli start-up
(about 3.6 s of imports), not the metrics. `summary.py` on a run takes well under a second.

## Smoke results (2026-09-30)

### Mock end to end (free, scripted model): PASS

Each suite ran on 2 dev tasks through the real `swegemma` Evaluator. The oracle and null arms stood in for the model,
then `agents-cli eval grade`, `summary.py` and, for F, `summary.py compare` ran on the output:

```bash
.venv/bin/python scripts/golden/run_suite.py controls --suite F --split dev --tasks rich_3278,rich_3471 -j 4 --run-id mock
.venv/bin/python scripts/golden/run_suite.py controls --suite L --split dev --tasks rich_3278,rich_3471 -j 4 --run-id mock
.venv/bin/python scripts/golden/run_suite.py controls --suite V --split dev --tasks rich_3278 -j 6 --run-id mock
for r in eval/golden/runs/mock_*_dev_*; do s=$(basename $r | cut -d_ -f2)
  agents-cli eval grade --traces $r/traces --config eval/golden/eval_config_$s.yaml --output $r/grade --qps 500
  .venv/bin/python scripts/golden/summary.py $r; done
.venv/bin/python scripts/golden/summary.py compare eval/golden/runs/mock_F_dev_oracle eval/golden/runs/mock_F_dev_null
```

| suite | cases | oracle headline | null headline | wall per arm | agents-cli vs library |
|---|---|---|---|---|---|
| L | rich_3278, rich_3471 | `l_all_gold_files_named` 2/2 | 0/2 | 9 s | 58 scores per arm, 0 mismatches |
| F | rich_3278, rich_3471 | `f_hidden_pass` 2/2 | 0/2 | 8-9 s | 62 per arm, 0 mismatches |
| V | rich_3278 gold, wrong, empty | `v_variant_goal` 3/3 | 1/3 (gold kept) | 13 s | 81 per arm, 0 mismatches |

- Every case finished with status `ok`: 0 infra errors, 0 metric errors, `x_clean` 1 on every case, $0 spent.
  `controls` reported "oracle and null expectations hold" for all three suites.
- Grading took 3.5 to 4.5 s per run, most of it agents-cli start-up. `summary.py` exited 0, so agents-cli and the
  library agreed on all 402 scores.
- The compare of oracle to null gave the transition table the repair ablation reads: `f_hidden_pass` `1->0` = 2
  (F__rich_3278, F__rich_3471), every other cell 0. It returned "NOT ELIGIBLE" as it should.
- One bug was found and fixed, with regression tests. A `--tasks` run kept no record of its filter, so its summary
  said "F dev: 2 gradable of 2 runnable of 2 tasks", which reads as the dev population. A mistyped task id was also
  dropped without a word. The fix records the filter in run.json and names the subset in the population sentence
  (see "Reading a summary"). Tests: `tests/test_golden_runner.py::test_task_filter_is_validated_and_recorded`
  and `tests/test_golden_summary.py::test_population_names_a_task_or_variant_subset`.
- Full repo suite after the fix, `.venv/bin/python -m pytest -q -p no:cacheprovider tests`:
  `1692 passed, 564 skipped, 7 xfailed in 539.47s (0:08:59)`.

### Live PROXY smoke (OpenRouter): NOT RUN, waiting for Carson's go

No OpenRouter call was made, and $0 was spent. The request in hand was a question ("did we do this?"). It did not
approve spending, so this pass stopped at the free checks. The router's openrouter and vllm forwarding (key
handling, retries on 429/502/503, budget refusal, usage-based cost) is covered by tests against a local fake
upstream. What only a paid call can show is OpenRouter's real auth, tool-call parsing, reasoning tokens and price.

To run it, with suite F at concurrency 1 as specified (estimate from r2_v10_1 per-stage tokens at the pinned
$0.14/$0.40: F 2 x $0.0177, L 2 x $0.0157, about $0.067 in total):

```bash
.venv/bin/python scripts/golden/run_suite.py run --suite F --split dev --endpoint openrouter \
    --tasks rich_3278,rich_3471 -j 1 --max-usd 0.25 --run-id smoke_F_or --grade
.venv/bin/python scripts/golden/run_suite.py run --suite L --split dev --endpoint openrouter \
    --tasks rich_3278,rich_3471 -j 2 --max-usd 0.20 --run-id smoke_L_or --grade
# or the packaged smoke: controls first, then paid L, F and V (1 task x 3 variants), estimate $0.099, cap $0.40
.venv/bin/python scripts/golden/run_suite.py smoke --endpoint openrouter
```

Read `run.json` `spent_usd` (OpenRouter's billed `usage.cost`; `cost_source` in each router log line says whether a
call was billed or estimated), `providers_seen` (it must be the pinned provider only) and `mean_live_latency_s`. If
any router log shows `reasoning_tokens` > 0, pass `--upstream-extra '{"reasoning": {"enabled": false}}'` on every
later PROXY run. The ratio of the summary header's Kaggle 4xL4 reference latency to `mean_live_latency_s` is the
`--l4-scale` the repair ablation's arms use. Then replace the estimates in "Cost and time" with the measured numbers.

### Repair ablation (docs/eval/ABLATION_REPAIR.md): pre-registered, NOT RUN

`eval/golden/runs` held no A0, A0' or B2 run before this smoke, and it holds none now. After the review of
2026-09-30:

1. The A0 arm can be built: `python scripts/make_variant.py submissions/v10 eval/golden/arms/v10_1_r0
   --repair-rounds 0` (fixer step 3 runs verify once and does not edit after it; the verifier's RED and REGRESSIONS go
   to finalize). Tests: `tests/test_make_variant_v10.py -k repair`.
2. The scope is narrowed to the fixer's loop by the dated addendum (suite F scripts the verifier), which also
   replaces the decision rule (the original one was biased toward CUT) and pins the arms' settings.
3. `summary.py ablation A0 B2 A0P` computes the verdict; nothing has to be assembled by hand.
4. Still blocking: no PROXY run exists yet. The smoke above comes first, because it measures the `--l4-scale` ratio
   and the reasoning setting all three arms must use.

Re-checked 2026-09-30, second pass, still $0 spent (the request was again "did we do this?", not a go):

- The A0 bundle is built at `eval/golden/arms/v10_1_r0`. `scripts/validate.py` says OK, and `diff -r` against
  `submissions/v10` shows exactly the fixer step 3 line and the verifier RED and REGRESSIONS lines. `submissions/v10`
  is unchanged. No helper constant caps repair rounds, so the addendum's compliance check is still the only guard
  against verify.py's "Fix the code" nudges.
- `tests/test_make_variant_v10.py` and `tests/test_golden_summary.py`: 74 passed.
- The runner's own estimates (it refuses before creating a run dir when the cap is too low, so these cost nothing):
  smoke $0.099 (`smoke --dry-run`), and $1.540 per arm for 87 case samples (29 F-dev cases x 3) at $0.0177 each.
  With the smoke, that is $4.72 for all three arms. The addendum's `--max-usd 2.00` per arm clears it (the runner
  asks for at least 1.94), so the pre-registered commands run as written.
- `eval/golden/holdout_log.jsonl` does not exist: the holdout has had 0 looks.

## Known deviations (also printed in every summary)

1. PROXY runs use another quantization and tool-call parser: X metrics are indicative, time metrics are comparable
   to L4 only with `--l4-scale` set to the measured latency ratio.
2. Journal times of scripted steps are compressed; only the handoff clock is exact.
3. Scripted stages use fewer of the 100 tool calls / 200 turns than real ones.
4. The baseline commit is dated one day back (visible only through `git log`).
5. A compaction during the live stage summarises scripted events, not a real stage's.
6. The golden plan is better than a real locator's: F measures the fixer's ceiling, not the pipeline.
7. Race-2 repros came from v10.0 helpers and are re-validated with the v10.1 helpers.
8. fastapi is runnable since 2026-09-30 (all 74 snapshots local; its kpar venv is the 41-package Kaggle-freeze closure, built online once). Runs made before that date cover rich and requests only: compare them on the cases both have (summary.py compare pairs by case id).
9. The live stage ends at helper t=300 by the router's cap; the scripted submit then includes new files (a real
   timeout's fallback diff would not).
10. Hidden tests run in the kpar venv (Kaggle pip freeze), not the full Kaggle image; `requests_6644` differs.

## agents-cli facts this depends on (1.7.0, re-probed 2026-09-29)

- A `custom_function_file` is read and exec'd into a fresh dict: no `__file__`, `__name__ == "builtins"`,
  `sys.path[0]` is the agents-cli bin dir. A metric file cannot import anything next to it, so each generated file
  carries the whole library. `tests/test_golden_metrics.py` execs every file that way, and again in an isolated
  interpreter (`python -I -S`) in an empty directory.
- The instance holds `agent_data`, `eval_case_id`, `response` (singular: `responses[0].response`), `reference` and
  every extra case field, which is how the `golden` block reaches the metrics. A case without `responses` errors.
- Several trace files in `--traces DIR` are merged into one `evaluation_dataset[0]` in `glob.glob` order. That is
  directory-enumeration order, NOT file-name order: on APFS, `a.json` came before `0first.json`. Spec gotcha 5 says
  "sorted by file name"; the measured behaviour is different. `summary.py` never assumes an order: it maps each
  `eval_case_index` through the results file's own `evaluation_dataset[0].eval_cases`.
- `agents-cli eval compare` diffs JSON keys (`baseline_keys`, `candidate_keys`, `differences`, `changed_keys`,
  `unchanged_keys`); there are no pairs and no p-values.
- Local metrics make no network calls: the tests run agents-cli with dead proxy and metadata endpoints and it
  grades normally.

## Files

| Path | What |
|---|---|
| `eval/golden/golden_metrics.py` | the metric library (stdlib only, Python 3.8 syntax) |
| `eval/golden/metrics/<name>.py` | generated, one per metric; do not edit |
| `eval/golden/eval_config_{L,F,V}.yaml`, `eval/golden/eval_config.yaml` | generated agents-cli configs; do not edit |
| `scripts/golden/gen_config.py` | writes the two rows above; `--check` for drift |
| `scripts/golden/summary.py` | summary, paired compare, and the repair ablation (`ablation`) |
| `tests/test_golden_metrics.py`, `tests/test_golden_summary.py` | metric, generator, summary and agents-cli tests |
| `eval/golden/runs/<run_id>/` | one run: `run.json`, `traces/`, `cases/`, `attempts/` (earlier attempts of re-run cases), `grade/`, `summary.*`, `compare.*`, `ablation.*` |
