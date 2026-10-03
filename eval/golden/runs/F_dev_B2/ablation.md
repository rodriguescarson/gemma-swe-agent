# Repair ablation: INCONCLUSIVE

Pre-registration: docs/eval/ABLATION_REPAIR.md (addendum 2026-09-30). Arms: A0 F_dev_A0, B2 F_dev_B2, A0' F_dev_A0p (label PROXY, provider pin crusoe/bf16, --l4-scale 0.934, samples 3).

Paired cases: 28 (dropped 1: F__rich_3470: samples A0' 1 of 3).

**Verdict: INCONCLUSIVE** (compliance failed: 12 % of A0 case samples edited after their first verify.py (> 10 %); the arms differ less than designed).
A0 -> B2: wins 2, losses 1, net 1, damage 1, one-sided p 0.5, two-sided p 1.0.
Calibration A0 -> A0': net 2, one-sided p in its direction 0.25: ok.
Compliance: 12 % of A0 case samples edited after their first verify.py: FAILED.
Original 2026-09-29 rule (SUPERSEDED, biased toward CUT): CUT (net 1 against flip total 2).

A0 -> B2 (A0 rows, B2 columns):

| \ | 1 | 0 |
|---|---|---|
| 1 | 20 | 1 |
| 0 | 2 | 5 |

0 -> 1 (2): F__rich_3468, F__rich_3772
1 -> 0 (1): F__rich_3063

A0 -> A0' (noise floor):

| \ | 1 | 0 |
|---|---|---|
| 1 | 21 | 0 |
| 0 | 2 | 5 |

0 -> 1 (2): F__rich_3278, F__rich_3468
1 -> 0 (0): none

A0 -> B2, reproducible True (7 cases):

| \ | 1 | 0 |
|---|---|---|
| 1 | 6 | 0 |
| 0 | 0 | 1 |

0 -> 1 (0): none
1 -> 0 (0): none

A0 -> A0', reproducible True:

| \ | 1 | 0 |
|---|---|---|
| 1 | 6 | 0 |
| 0 | 1 | 0 |

0 -> 1 (1): F__rich_3278
1 -> 0 (0): none

A0 -> B2, reproducible False (21 cases):

| \ | 1 | 0 |
|---|---|---|
| 1 | 14 | 1 |
| 0 | 2 | 4 |

0 -> 1 (2): F__rich_3468, F__rich_3772
1 -> 0 (1): F__rich_3063

A0 -> A0', reproducible False:

| \ | 1 | 0 |
|---|---|---|
| 1 | 15 | 0 |
| 0 | 1 | 5 |

0 -> 1 (1): F__rich_3468
1 -> 0 (0): none

| arm | majority pass | Wilson 95 % | sample pass rate | repair share | tool calls | LLM calls | completion tokens | wall s | L4-projected s |
|---|---|---|---|---|---|---|---|---|---|
| A0 | 21/28 | [0.566, 0.873] | 0.762 | 0.119 | 5.524 | 6.833 | 528.619 | 145.617 | 28.068 |
| B2 | 22/28 | [0.605, 0.898] | 0.762 | 0.250 | 9.381 | 10.643 | 699.571 | 162.186 | 39.385 |
| A0' | 23/28 | [0.644, 0.921] | 0.786 | 0.214 | 7.691 | 8.762 | 684.869 | 142.736 | 36.237 |

- Scope: the fixer's repair loop only; suite F scripts the verifier, whose loop never runs here.
- Damage is measured without finalize: F grades the fixer's raw tree, while the pipeline's finalize.py restores the best checkpoint when the current tree scores worse, so F's damage is an upper bound of the pipeline's.
- Reproducible cases carry a gold-validated reproduction, a better repair signal than a real locator's; read the by_reproducible tables.
- Per-case outcome = majority over its samples; A PROXY verdict is a screen: KEEP or CUT is confirmed with one paired Kaggle-L4 FAITHFUL run before it ships.
