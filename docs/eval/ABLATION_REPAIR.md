# Pre-registered experiment: does v10.1's repair loop create solves?

Written 2026-09-29, before any run. The design, metrics and decision rule below may not change after the first
trace exists; changes go into a dated addendum with the reason, and the original text stays.

## Question

Does spending budget on repair (verify -> diagnose -> fix, up to 2 rounds in the fixer and 2 in the verifier)
produce more hidden-test-passing patches than stopping after the first attempt?

Why it is open: in race 2 round 1 (eval/race2/round1_kpis.txt) only 78% of v10 tasks produced a VERIFY verdict,
checkpoint restores fired 0 times, and the fixer obeyed EDIT NOW in 2 of 7 cases. The loop exists; its effect is
unmeasured.

## Design

- Suite: golden-eval suite F (fixer given a golden plan), DEV split only (the HOLDOUT slice is not touched).
- Arms, identical except for the repair budget:
  - A0: v10.1 with repair rounds = 0 (verify runs once for its verdict line; no repair round follows).
  - B2: v10.1 as shipped (repair rounds = 2).
  - A0' : A0 repeated with a different run index, to measure the noise floor at temperature 1.0.
- Same tasks, same golden plans, same model endpoint, same budgets, same concurrency.
- Endpoint: OpenRouter google/gemma-4-31b-it (PROXY; bf16, different tool-call parser than the scorer).
  A PROXY result is a screening result only; any ship decision still needs a Kaggle-L4 faithful run.
- The A0 variant is built with scripts/make_variant.py (a --repair-rounds 0 lever, one exact text patch, tested
  like the other levers: changes only its own files, compiles with scripts/validate.py).

## Metrics (per task, graded by hidden tests after the stage)

1. Pass rate per arm with a Wilson 95% CI.
2. Transition matrix A0 -> B2, the headline:
   - pass -> pass: repair unnecessary
   - fail -> pass: repair created a solve
   - pass -> fail: repair damaged a correct patch
   - fail -> fail: repair spent budget for nothing
3. Noise floor: the same matrix for A0 -> A0'. Its off-diagonal counts are what sampling alone produces.
4. Cost per task per arm: tool calls, output tokens, wall seconds, and the L4-projected seconds
   (research/time_model.md: about 1.4 s per step plus 35 ms per output token).
5. Exact two-sided sign test on the A0 -> B2 discordant pairs.

## Decision rule

- KEEP repair (and consider raising its reliability) if fail->pass minus pass->fail in A0->B2 exceeds the
  A0->A0' off-diagonal total by at least 3, AND pass->fail in A0->B2 is at most 1.
- CUT repair to 0 rounds (and give its time to the first attempt) if fail->pass minus pass->fail in A0->B2 is at
  most the A0->A0' off-diagonal total.
- Otherwise INCONCLUSIVE: run one more A0/B2 pair before deciding.
- Either KEEP or CUT is then confirmed with one paired Kaggle-L4 faithful run before it ships.

## Cost

About $2 per arm on OpenRouter for the DEV split of suite F, about $6 for the three arms, stated before running.

## Addendum 2026-09-30 (written before any A0, A0' or B2 trace exists)

On 2026-09-30 `eval/golden/runs` held only the `mock_*` control runs and `eval/golden/holdout_log.jsonl` did not exist.
The original text above stays as written. This addendum replaces its "Decision rule" and narrows its "Question", for
the reasons below. `summary.py ablation` computes both rules and prints the original one marked SUPERSEDED, so anyone
can see what the original rule would have said.

### 1. Why the decision rule changes

The original rule compares a signed quantity with an unsigned one. The net (fail->pass minus pass->fail in A0->B2) is
centred on 0 when repair does nothing, but the noise floor (the A0->A0' off-diagonal total) is never negative, and its
mean is the number of cases that sampling flips. So CUT fires whenever the net is below the flip count, and a real
repair benefit smaller than that count is cut.

Simulation: 29 F-dev cases, 10 that always pass, U that pass with p = 0.5 in every arm (sampling flips), S that repair
solves for certain (A0 never, B2 always), the rest never pass; 20,000 trials per row, one sample per case. The code is
`sim_rules` in `tests/test_golden_summary.py`; the test asserts the same pattern on 4,000 trials.

| U | S (real repair solves) | original: KEEP / CUT / INCONCLUSIVE | this addendum: KEEP / CUT / INCONCLUSIVE |
|---|---|---|---|
| 5 | 0 (null) | 0 / 94 / 6 % | 1 / 60 / 39 % |
| 5 | 3 | 15 / 49 / 36 % | 25 / 5 / 70 % |
| 5 | 4 | 29 / 30 / 41 % | 39 / 1 / 60 % |
| 10 | 0 (null) | 0 / 98 / 2 % | 3 / 54 / 43 % |
| 10 | 4 | 7 / 70 / 22 % | 20 / 5 / 75 % |
| 0 | 3 | 100 / 0 / 0 % | 0 / 0 / 100 % |

The original rule cut a repair loop that adds 4 certain solves 30 to 70 % of the time. Under the null, CUT is the right
call (repair costs time and adds nothing), so a high null CUT rate is not the defect. The defect is CUT on real
benefit. The last row is the price of the replacement: 3 wins and 0 losses is one-sided p = 0.125, which is not
evidence at 0.10, so it reads INCONCLUSIVE and asks for the second pair.

### 2. Replacement decision rule

Per case, the outcome of an arm is `f_hidden_pass`. With `--samples 3` (preferred, see 5) it is the majority of the
three samples. Paired cases are those with status ok or model_error, an applicable `f_hidden_pass`, every sample
present and the same fixture in all three arms. `summary.py ablation` lists every case it drops and why.

- A0 -> B2: w = fail->pass, l = pass->fail, net = w - l, damage = l, and the exact one-sided sign test
  p = P(W >= w | w + l discordant pairs, 1/2). One-sided because the question has a direction (does repair add
  solves); metric 5's two-sided p is still reported.
- Calibration, A0 -> A0' (two runs of the same bundle): w', l', net' = w' - l'. It FAILS when |net'| >= 3 and the
  one-sided sign test in the direction of net' is <= 0.10, which means identical arms show what the KEEP rule would
  call an effect. The noise arm is read as a net against the same band, never as a flip total.
- Compliance: verify.py's RED lines say "Fix the code, then run verify.py again" whatever the fixer's prompt says, so
  the A0 prompt alone may not stop repair. An A0 case "repairs" when its fixer calls edit.py after its first verify.py
  run without `--repro-only` (counted per case sample, edit_file and write_file included). Compliance FAILS when more
  than 10 % of the A0 case samples on the paired cases repair: the arms then differ less than designed, and the lever
  needs a helper-side change before a rerun.

Verdict, in this order:

1. INCONCLUSIVE if calibration or compliance fails (check the pins in section 4, then rerun all three arms).
2. KEEP repair if one-sided p <= 0.10 AND net >= 3 AND damage <= 1.
3. CUT repair to 0 rounds (and give its time to the first attempt) if net <= 0.
4. Otherwise INCONCLUSIVE: run one more A0/B2 pair at the same settings and read that pair alone by this rule. A
   second INCONCLUSIVE keeps v10.1 as shipped (no change without evidence).

The thresholds (one-sided 0.10, net 3) are the golden-eval decision rule's (`docs/eval/GOLDEN_EVALS.md`). Either KEEP
or CUT is still confirmed with one paired Kaggle-L4 FAITHFUL run before it ships.

### 3. Scope: the fixer's repair loop only

Suite F makes only the fixer live. Its verifier is scripted as `[submit(), text("Submitted.")]`
(`scripts/golden/stage_scripts.py`, `neighbour_scripts`), so the verifier's "at most 2 repair rounds"
(`prompts/verifier.md` step 3) never runs in F. This experiment answers: does the FIXER's loop
(`prompts/fixer.md` step 3, "act on it, at most 2 rounds") create solves? The `--repair-rounds 0` lever also rewrites
verifier.md step 3, so a later V-suite ablation can use the same A0 bundle, but nothing here measures the verifier loop.

Two consequences for reading the result:

- Damage is measured without finalize. F grades the fixer's raw tree; in the pipeline, finalize.py restores the best
  checkpoint when the current tree scores worse (finalize.py:150-181), which can undo repair damage. F's damage count
  is an upper bound of the pipeline's.
- The repair signal in F is better than a real locator's on some cases. 7 of the 29 runnable gradable F-dev cases
  (rich_2943, 3067, 3278, 3472, 3480, 3718, 3894) carry a golden reproduction validated to fail on the original and
  pass on gold; in race 2, 52 of 121 real locator `--repro-only` runs said "passes on original". `summary.py ablation`
  therefore also prints both transition tables sliced by `golden.reproducible`.

### 4. Settings pinned for all three arms

The original design said "same model endpoint" without pinning what makes it the same. The number of repair rounds
that fit before EDIT NOW, FINISH and the t=300 cap is set by the helper clock, which runs on the proxy's wall time
unless `--l4-scale` is set. So all three arms use:

- `--endpoint openrouter --or-provider crusoe/bf16` (the default pin since 2026-09-30: bf16, tools and seed
  supported, $0.14/$0.40 per M on the public endpoint listing of that day);
- the same `--upstream-extra` (the reasoning setting the smoke decides);
- `--l4-scale R`, where R is the smoke's measured L4/proxy per-call latency ratio (the Kaggle 4xL4 reference printed
  in every summary header, divided by the smoke's `mean_live_latency_s`);
- `--seed-mode off`, `--samples 3`, the same dataset and `-j`.

`summary.py ablation` refuses (exit 2) arms that differ in endpoint, model, provider pin, providers seen,
`--upstream-extra`, `--l4-scale`, seed mode, samples, dataset or task filter; A0 and A0' with different bundles; B2 with
A0's bundle; a PROXY arm without a provider pin; and a PROXY arm at `--l4-scale 1.0` unless `--allow-unscaled` is
given (and then the output says so).

### 5. Samples and cost

`--samples 3` with the majority per case: a case whose pass rate is away from 0.5 flips less often, while a case at
0.5 stays a coin flip. In the simulation with partial effects (10 always pass, 6 noise cases at p 0.3 or 0.7, 4 cases
that repair lifts from 0.3 to 0.7, 9 never pass), the replacement rule's KEEP / CUT went from 10 / 27 % at one
sample to 17 / 16 % at three; under the null it stayed at 2 % false KEEP.

Cost at `--samples 3`: 29 runnable gradable F-dev cases x 3 samples x about $0.0177 per fixer run (race-2 fixer tokens
at the pinned $0.14/$0.40) = about $1.54 per arm, about $4.60 for the three arms. Pass `--max-usd 2.00` per arm; the
runner refuses to start a run whose estimate exceeds its cap.

### 6. Commands

```bash
python scripts/make_variant.py submissions/v10 eval/golden/arms/v10_1_r0 --repair-rounds 0
P="--suite F --split dev --endpoint openrouter --or-provider crusoe/bf16 --samples 3 -j 6 --max-usd 2.00 \
   --l4-scale R --upstream-extra JSON_FROM_SMOKE"
.venv/bin/python scripts/golden/run_suite.py run $P --bundle eval/golden/arms/v10_1_r0 --run-id F_dev_A0 --grade
.venv/bin/python scripts/golden/run_suite.py run $P --bundle submissions/v10 --run-id F_dev_B2 --grade
.venv/bin/python scripts/golden/run_suite.py run $P --bundle eval/golden/arms/v10_1_r0 --run-id F_dev_A0p --grade
.venv/bin/python scripts/golden/summary.py ablation eval/golden/runs/F_dev_A0 eval/golden/runs/F_dev_B2 \
    eval/golden/runs/F_dev_A0p
```
