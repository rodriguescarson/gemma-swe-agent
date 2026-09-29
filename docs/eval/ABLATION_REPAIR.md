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
