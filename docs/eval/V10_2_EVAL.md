# Pre-registered evaluation: v10.2 against v10.1 on the golden L and F suites

Written 2026-09-30 12:05 IST (06:35 UTC), **before any v10.2 run**. No v10.2 bundle exists yet, no v10.2 trace exists,
and this workflow has spent $0.00 of its $4.00 OpenRouter cap. The design, population, settings, metrics and decision
rule below may not change after the first v10.2 trace (canary included) exists. Any change goes into a dated addendum at
the end with its reason, and the original text stays. The design under test is `docs/v10/SPEC_v10_2.md`.

What this does not do: no Kaggle submission or kernel push, no pod, no golden HOLDOUT run (the 19 holdout tasks are not
read; `eval/golden/holdout_log.jsonl` must show no new entry), no V suite (section 10).

---

## 1. Question

Does v10.2's locator package (SPEC L1-L6) name the gold files more often than v10.1 on the same dev tasks, without the
fixer package (F1-F3) costing the fixer more than 5 points of hidden-test pass rate, and without a new crash class? If
yes, v10.2 goes to the pod ladder (PATH_TO_020 rung 4, S3). If no, it does not, and section 7 says what follows.

---

## 2. Preconditions (all $0; if any fails, no paid run starts)

- **P1. v10.2 built and rung 1 green** (SPEC 12, steps 2-3): `scripts/validate.py submissions/v10_2` OK; the full suite
  green on v10.1 (frozen pins, R148) and with `G4_BUNDLE=submissions/v10_2`; `G4_NIGHTLY=1`; Linux parity on 3.12 and
  3.13; hidden.md probes E, F, I, K pass on the v10.2 helpers.
- **P2. Eval changes built and tested** (SPEC 8, E1-E7), including the router model clock (E1). **Without E1 there is
  no paid L run**: under the retry-driven clock the router capped 5 of 27 v10.1 locators at L4-projected times of
  26-88 s (diag sect. 2), and v10.2's shorter locators would be capped less, so the headline would favour v10.2 for a
  reason that is not the change. `gen_config.py --check` passes.
- **P3. Controls hold for both bundles on the population** (oracle and null, free):
  `run_suite.py controls --suite L --split dev --tasks $T --l4-clock model --bundle submissions/v10_2` and the same for
  `--suite F` and for `--bundle submissions/v10`; each must print "oracle and null expectations hold".
- **P4. Fixed inputs recorded before the first paid call:** the v10.1 tree sha
  `4b8fa33eb41996b29bc81f34290abf8410908600a1a9005e7a300762ec5396fd`; the v10.2 tree sha (written into the addendum
  section at build time, before the canary); the dataset shas of `eval/golden/datasets/L_dev.json` and `F_dev.json`; the
  30 case ids of section 3.

---

## 3. Population

- **Rule:** dev-split tasks that are runnable and gradable in suite F and runnable in suite L (52 eligible: rich 31,
  fastapi 21); within each repo, order by `sha256("v10.2-eval:" + task)` and take the first 15. Both suites use the
  same 30 tasks. Script: `research/v10_2_prereg/cases.py` (output `cases.out`).
- **The 30 tasks** (`T` below):
  `fastapi_13537,fastapi_13920,fastapi_14306,fastapi_14372,fastapi_14448,fastapi_14463,fastapi_14479,fastapi_14487,fastapi_14786,fastapi_14873,fastapi_15280,fastapi_5077,fastapi_9425,fastapi_9555,fastapi_9753,rich_2943,rich_3180,rich_3468,rich_3470,rich_3472,rich_3480,rich_3506,rich_3518,rich_3535,rich_3777,rich_3938,rich_3953,rich_4075,rich_4077,rich_4079`
- Strata (race-2 outcome): rich none 11, one 1, both 3; fastapi none 8, one 3, both 4. Reproducible in the golden sense:
  8 of 30.
- Population sentence to quote with every rate: "L dev and F dev: 30 of 52 eligible dev tasks (rich 15, fastapi 15),
  selected by hash, not a population rate for the dev split".
- **Known in-sample bias.** The diagnosis read all 54 dev traces (L and P), and 11 of these 30 tasks carry a named
  failure mode (fastapi_14487, rich_3470, rich_3472, fastapi_13920, fastapi_9425, fastapi_9753, fastapi_14372,
  fastapi_14448, fastapi_14873, rich_3953, rich_2943). The design was shaped on them, so a dev gain is optimistic.

---

## 4. Arms and fixed settings

| setting | value | note |
|---|---|---|
| endpoint | `--endpoint openrouter --or-provider crusoe/bf16` (fallbacks off) | as the repair ablation |
| extra body | `--upstream-extra '{}'` | as the ablation (`run.json` of F_dev_A0/B2/A0p, L_dev_v101) |
| seed | `--seed-mode off` | temperature 1.0 as shipped |
| samples | `--samples 2` | per case; per-case means are compared |
| concurrency | `-j 2` | the pinned provider rate-limits (router retry settings unchanged) |
| clock | `--l4-clock model --l4-scale 1.0` | **the one deliberate difference from the ablation's settings** (it used `wall` and 0.934): the helper clock and the t=300 cap run on the L4 latency model plus tool wall time (SPEC E1) |
| budgets | the runner's defaults (`budgets` in run.json) | identical in both arms |
| agent env | `kpar` | the Kaggle-freeze venvs for rich and fastapi |

Arms: **A = v10.1** (`--bundle submissions/v10`), **B = v10.2** (`--bundle submissions/v10_2`). Same tasks, same settings,
run back to back on the same day.

```bash
cd /Users/carson/Projects/gemma-swe-agent
T=fastapi_13537,fastapi_13920,fastapi_14306,fastapi_14372,fastapi_14448,fastapi_14463,fastapi_14479,fastapi_14487,fastapi_14786,fastapi_14873,fastapi_15280,fastapi_5077,fastapi_9425,fastapi_9555,fastapi_9753,rich_2943,rich_3180,rich_3468,rich_3470,rich_3472,rich_3480,rich_3506,rich_3518,rich_3535,rich_3777,rich_3938,rich_3953,rich_4075,rich_4077,rich_4079
S=".venv/bin/python scripts/golden/run_suite.py run --split dev --endpoint openrouter --or-provider crusoe/bf16 \
   --upstream-extra {} --seed-mode off -j 2 --l4-clock model --l4-scale 1.0 --grade"
# 0. canaries (v10.2 only; never analysed, only checked against section 5's stop conditions)
$S --suite L --samples 1 --tasks fastapi_13537,rich_2943 --bundle submissions/v10_2 --run-id L_dev_v102_canary --max-usd 0.05
$S --suite F --samples 1 --tasks fastapi_13537,rich_2943 --bundle submissions/v10_2 --run-id F_dev_v102_canary --max-usd 0.05
# 1-4. the four gating runs
$S --suite L --samples 2 --tasks $T --bundle submissions/v10   --run-id L_dev_v101_c9 --max-usd 0.95
$S --suite L --samples 2 --tasks $T --bundle submissions/v10_2 --run-id L_dev_v102_c9 --max-usd 0.95
$S --suite F --samples 2 --tasks $T --bundle submissions/v10   --run-id F_dev_v101_c9 --max-usd 1.07
$S --suite F --samples 2 --tasks $T --bundle submissions/v10_2 --run-id F_dev_v102_c9 --max-usd 1.07
# 5-6. the end-to-end chain (only if section 5's spend check allows it)
.venv/bin/python scripts/golden/chain_plans.py --l-run eval/golden/runs/L_dev_v101_c9 --sample 0 --out eval/golden/datasets/F_dev_chain_v101.json
.venv/bin/python scripts/golden/chain_plans.py --l-run eval/golden/runs/L_dev_v102_c9 --sample 0 --out eval/golden/datasets/F_dev_chain_v102.json
$S --suite F --samples 1 --dataset eval/golden/datasets/F_dev_chain_v101.json --bundle submissions/v10   --run-id F_chain_v101 --max-usd 0.54
$S --suite F --samples 1 --dataset eval/golden/datasets/F_dev_chain_v102.json --bundle submissions/v10_2 --run-id F_chain_v102 --max-usd 0.54
# 7. analysis ($0)
.venv/bin/python scripts/golden/summary.py compare eval/golden/runs/L_dev_v101_c9 eval/golden/runs/L_dev_v102_c9
.venv/bin/python scripts/golden/summary.py compare eval/golden/runs/F_dev_v101_c9 eval/golden/runs/F_dev_v102_c9
.venv/bin/python scripts/golden/summary.py compare --pair-by-task eval/golden/runs/F_chain_v101 eval/golden/runs/F_chain_v102
.venv/bin/python scripts/golden/v102_gate.py eval/golden/runs/L_dev_v101_c9 eval/golden/runs/L_dev_v102_c9 \
    eval/golden/runs/F_dev_v101_c9 eval/golden/runs/F_dev_v102_c9 [eval/golden/runs/F_chain_v101 eval/golden/runs/F_chain_v102]
```

The chain arms feed each bundle's fixer its own arm's L plans (sample 0) and reproductions: v10.1's fixer on v10.1's
plans against v10.2's fixer on v10.2's plans. That is the end-to-end proxy the runner can give without a pipeline mode.

---

## 5. Order, spend and stop conditions

- **Order:** canaries, L v10.1, L v10.2, F v10.1, F v10.2, then the chain pair. No run starts before the previous one has
  finished and been graded.
- **Spend check before every run** (billed `spent_usd` from each run.json; OpenRouter's `usage.cost`): billed total so far
  plus the next run's `--max-usd` must be at most **$4.00**. Each run's spend is bounded by its cap, so the total can
  never pass $4.00. If the check fails for the chain pair, the chain is skipped and reported as "not run (budget)"; the
  decision then uses G1-G6 only. If it fails for a gating run (only possible after an unexpected overspend), that run is
  made on the largest hash-ordered prefix of `T` that fits, and both arms of that suite are compared on those cases only
  (an addendum records it).
- **Expected spend (ESTIMATE from measured rates):** L $0.0147 per case-sample (L_dev_v101: $0.426 / 29), F $0.0099
  (F_dev_B2: $0.857 / 87). Canaries about $0.05; L v10.1 about $0.88, L v10.2 about $0.75 (fewer calls); F v10.1 and
  v10.2 about $0.59 each; subtotal about $2.86; the chain pair about $0.59 if its check (subtotal at most $2.92) passes.
  Total about $3.45. The runner's own estimates (race-2 token rates, $0.0157 L and $0.0177 F per case-sample) set the caps.
- **Canary stop conditions** (any one stops the workflow before run 1; fix, rebuild, and restart from P1 with a dated
  addendum): a crash class; `x_invented_tool_calls` or `x_bare_helper_calls` above 0; a live stage that received 5 or
  more LOCATOR CLOSED refusals; the F canary's fixer starting with `python3 /tmp/swe/status.py` in neither case; an
  `infra_error` that is not an upstream failure.
- **Infra errors:** a run with more than 5 % `infra_error` case-samples (summary.py compare refuses it) is completed once
  with `--resume` at the same settings. If it is still above 5 %, the verdict is **INCONCLUSIVE (instrument)**, never a
  pass or a fail.
- **No second looks.** No added samples, no reruns of a finished arm, no change of population after a trace exists,
  except the `--resume` completion above.

---

## 6. Metrics

Every comparison is paired by case over the 30 tasks. A case's value in an arm is the mean over its counted samples
(`status` ok or model_error). A case with no counted sample in either arm is dropped from that metric, and the drop is
listed; more than 3 dropped cases in a suite means INCONCLUSIVE (instrument). `diff` below is `summary.py compare`'s
`mean_diff` (v10.2 minus v10.1, averaged over paired cases).

### 6.1 Gating metrics

| gate | metric (suite) | pass condition | source of the threshold |
|---|---|---|---|
| **G1** | `l_all_gold_files_named` (L) | diff >= **+0.10** | the brief's ship-to-pod rule |
| **G2** | `f_hidden_pass` (F), the sample pass rate | diff >= **-0.05** (a regression of more than 5 points fails) | the brief |
| **G3** | `crash_class` over every v10.2 run (canaries, L, F, chain) | no class that no v10.1 run of this evaluation shows, and `x_crash` totals not higher, per suite | the brief ("no new crash class") |
| **G4** | `l_files_named_n` (L) | diff <= **+1.0** | added here: SPEC L6's ALSO line names a runner-up, and the headline counts any gold path anywhere in the reply, so a plan that lists more files wins G1 mechanically. One extra file per plan is the ALSO line's design; more is a file dump |
| **G5** | `x_invented_tool_calls`, `x_bare_helper_calls`, `x_malformed_calls`, `x_text_tool_calls`, `x_compaction_exceedances`, `x_runaway_outputs` (L and F, per suite) | v10.2 total <= v10.1 total + 1, for each | added here: v10.1's guarantees (no invented tools, bounded outputs under 14,336). The +1 allows one event of sampling at the tail over 60 case-samples |
| **G6** | `l_repro_valid` (L) | diff x n >= **-3** over the n paired cases (not down by more than 3 case-equivalents) | PATH_TO_020 S2 gate (C17) and speed.md 9.2: the named risk of SPEC L3 |
| **veto** | chain `f_hidden_pass` (F on chained plans), only if the chain ran | diff <= **-0.10** (3 or more net losses of 30) vetoes | added here: the only check that sees mechanism errors (diag M8) and whether ALSO distracts the fixer |

### 6.2 Primary reported metrics (with pre-registered expectations, not gates)

| metric | expectation (v10.2 minus v10.1) | falsified if |
|---|---|---|
| `l_l4_s` (L4-modelled locator seconds, SPEC E2) | -10 to -20 s (diag capsim bound: -23.3 on L, -20.7 on P, upper bound on removal) | diff > -8 s: the time claim of SPEC L2-L4 is falsified at k = 1 (reported; the 3.2-scale pod round is then the only speed test) |
| `l_t_end` (last helper footer, model clock) | -8 to -20 s | same as above |
| `l_within_time` (<= 90 s) | +5 to +15 points (v10.1 about 85 % on the L4 model, diag sect. 2) | diff < 0 |
| `x_capped` | about 0 in both arms under the model clock | any v10.2 cap where v10.1 has none |
| `l_calls`, `l_within_calls` | mean 15.5 -> 10-12; within 12 calls about 45 % -> 75 % | mean calls not lower |
| chain `f_hidden_pass` | -1 to +2 net cases of 30 | (the veto above) |

### 6.3 Secondary (reported, never gating)

`l_gold_files_in_files_line` (the FILES line alone, ALSO excluded; expected +0 to +5 points), `l_gold_files_named`,
`l_gold_functions_named`, `l_plan_format`, `l_plan_words`, `l_ended_by_text`, `l_repro_fails_on_original` (also on the 8
reproducible cases), `f_l4_s` (expected -5 to -10 s), `f_calls`, `f_verify_rounds`, `f_first_edit_t`, `f_touches_all_gold_files`,
fixer compliance with its budget (share of v10.2 F samples that edit after their second full verify; expected about 0),
the per-repo slices (rich, fastapi), and the diag's essential-files reading of the headline (M7: gold files whose hunks
are all docstring, comment, blank, formatting or type-hint changes dropped; computed offline with the diag's `lines.py`
rule). The transition tables of the headline, of `f_hidden_pass` and of the chain are printed with case ids. Named cases
to read in them: fastapi_14487 and rich_3470 (gold first shown after call 14 in P, the known risk of SPEC L2).

---

## 7. Decision rule

Computed by `scripts/golden/v102_gate.py` (SPEC E7) from the compare and run files, never by hand.

1. **INCONCLUSIVE (instrument)** if a precondition was skipped, a run stayed above 5 % infra errors after one resume, more
   than 3 cases were dropped in a suite, the arms' settings differ in anything but the bundle, or the holdout log grew.
2. **SHIP-TO-POD** if G1, G2, G3, G4, G5 and G6 all pass and the chain (if it ran) does not veto.
3. **NOT READY** otherwise, naming every failing gate.

What each outcome triggers (fixed now):

| outcome | next step |
|---|---|
| SHIP-TO-POD | v10.2 becomes the base of pod session A (PATH_TO_020 S3: v10.2 vs v10.1 at `G4_L4_SCALE` 1.7 and 3.2, then the factorial), subject to Carson's pod approval. The golden holdout is not read until a final candidate exists |
| NOT READY, G1 only | the locator package does not ship as an accuracy change. The robustness carve-out `v10.1.1` (SPEC 12.5: R1-R7 on v10.1) may take its rung-1 path (PATH_TO_020 C9 exception, Carson's call). The headline's transition table and the section 6.2 time readings go into a v10.3 design note. The same comparison is not re-run to rescue G1 |
| NOT READY, G2 | SPEC F1 (one repair round, status first) is the suspect: the next candidate reverts F1 alone; no new F run in this workflow |
| NOT READY, G3 or G5 | a protocol regression: read the traces of every event before anything else ships |
| NOT READY, G4 | the headline gain is not credible (plans turned into file lists); read `l_gold_files_in_files_line` |
| NOT READY, G6 | SPEC L3's budget is too tight: the next candidate uses `LOC_MAX_REPROS = 3` |
| chain veto | the L gain does not reach the fixer: read the chain's 1->0 cases for ALSO and lost-plan handling before any pod time |

A PROXY verdict is a screen. Whatever it says, shipping to the leaderboard still needs rung 5 (a faithful paired
Kaggle-L4 run, PATH_TO_020).

---

## 8. Noise and power (MEASURED inputs, simulated; `research/v10_2_prereg/`)

- **G1 (L headline), n = 30, 2 samples, threshold +0.10.** There is only one two-run L measurement: L_dev_v101 against
  the pod's p1_v10 on the 22 common rich dev tasks the proxy did not cap, with 3 discordant (13.6 %). Modelling a share
  u of cases as coin flips (u = 0.27 from that discordance, and 0.40 as a pessimistic case) and the rest as fixed
  (`lpower.py`): under no real change G1 passes with probability **0.027 (u 0.27) to 0.056 (u 0.40)**. With a real gain of
  +2 / +3 / +4 / +5 cases (6.7 / 10 / 13.3 / 16.7 points) it passes with probability **0.28-0.32 / 0.57-0.58 / 0.79-0.84 /
  0.92-0.96**. At the central expectation (+7 points, about +2 cases) G1 more likely fails than passes.
- **G2 (F guard), n = 30, 2 samples, threshold -0.05.** Per-case pass rates pooled over the three F runs of the repair
  ablation (29 rich cases, 9 samples each; 12 of 29 cases had mixed outcomes, `fnoise.py`): with no real change the guard
  fails with probability **0.107**. A regression of more than 5 points needs at least 4 net sample losses of 60 here. The
  pooled rates come from rich cases only; fastapi's are unmeasured.
- **Chain veto, n = 30, 1 sample, threshold -0.10.** Same pooled rates (`chainveto.py`): with no real change the veto fires
  with probability **0.103** (0.026 at 2 samples, which the budget does not fund).
- **Combined.** A v10.2 that truly changes nothing passes G1 about 3-6 % of the time; a v10.2 with a real +4-case
  locator gain and a neutral fixer passes G1 and G2 about 0.71-0.75 of the time (0.79-0.84 x 0.89), and about 0.63-0.67
  with the chain veto also run.

---

## 9. Pre-registered predictions (ESTIMATE; written before the runs, so they can be wrong)

| quantity | v10.1 arm | v10.2 arm |
|---|---|---|
| `l_all_gold_files_named` | 0.55-0.70 (L_dev_v101 55.6 % on 27 rich under the old clock; P 65 % on 54) | +0.05 to +0.10 over v10.1 (central +0.07) |
| `l_gold_files_in_files_line` | about equal to its headline | +0 to +0.05 |
| `l_files_named_n` | about 1.5-2.0 | +0.5 to +1.2 |
| `l_l4_s` | 50-60 s | 35-45 s |
| `l_calls` | 15-16 | 10-12 |
| `l_repro_valid` | about 0.40 (L_dev_v101 40.7 %) | -0 to -2 cases |
| `f_hidden_pass` | 0.75-0.80 on rich; fastapi unmeasured | within +-0.03 of v10.1 |
| `f_l4_s` | about 35-40 s (B2 39.4 L4-projected s) | 5-10 s lower |
| chain `f_hidden_pass` | 0.35-0.50 (P resolved 19 of 54 dev tasks end to end, `research/locator_diag/stats.out`) | -1 to +2 cases |
| verdict | | NOT READY on G1 more likely than SHIP-TO-POD (P(G1) about 0.3 at the central expectation of about +2 cases) |

---

## 10. Limitations and deviations

- **PROXY:** bf16 Gemma on OpenRouter with its tool parser, not the scorer's QAT w4a16 model and vLLM parser. X metrics
  are indicative; plan and fix metrics transfer best (GOLDEN_EVALS.md).
- **Model clock:** tool time is Mac wall time, not Kaggle CPU time; LLM time is the time_model latency formula, not a
  measured L4 call. Both arms get the same clock, so differences are comparable; absolute seconds are approximate.
- **k = 1 only.** The 90 s close binds mostly on stretched hidden tasks (k >= 1.9). Its effect there is measured on the pod
  at `G4_L4_SCALE` 3.2 (PATH_TO_020 S3(c)), not here.
- **In-sample dev** (section 3); the holdout is kept for one look at a final candidate, outside this workflow.
- **The chain is partial:** in F the scripted locator runs `locate.py` on the title words and the reproduction, so v10.2's
  LOCATOR DIGEST shows that state, not the L run's views. This biases the chain against v10.2 (conservative).
- **No V suite.** The verifier's prompt is unchanged; its NEXT lines change (SPEC F2). V dev's wrong variant alone would
  cost about $1.60 for two arms at 2 samples, which the $4 cap cannot hold next to L and F. The verifier is covered by
  rung 1 (R137, R147) and by the pod.
- **Temperature 1.0 and 2 samples** leave single-case outcomes noisy; section 8 states the resulting error rates.
- **Fastapi F noise is unmeasured**; the G2 and veto rates in section 8 use rich cases only.

---

## 11. Reproduce the numbers in this file ($0)

```bash
cd /Users/carson/Projects/gemma-swe-agent
D=research/v10_2_prereg; PY=.venv/bin/python
$PY $D/cases.py > $D/cases.out            # the 30 tasks and their fixture shas
$PY $D/fnoise.py > $D/fnoise.out          # F noise floor, G2 null rates, B2 verify-round use
$PY $D/lpower.py > $D/lpower.out          # G1 null rate and power
$PY $D/chainveto.py > $D/chainveto.out    # chain veto null rate
$PY $D/firstround.py > $D/firstround.out  # fixer first-round call mix (SPEC section 6)
$PY $D/margins.py                          # R94/R95 margins of the bundle G4_BUNDLE points at (margins.out: v10.1 and the draft)
```

---

## Addenda

(None yet. Record here, dated and before the canary: the v10.2 tree sha at build time; any change to this file and its
reason.)
