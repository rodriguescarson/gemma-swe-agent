# Gap 6: how many replicates the v10 race needs, and a race plan that can detect +3 to +5

Written 2026-09-28 about 13:00 IST. Read-only: nothing was submitted, pushed, started or spent, and no repo file was changed
except this one. Every number cites a file or a script output. Anything not measured is marked UNVERIFIED.

Scripts and outputs (scratchpad, Python 3.9 + numpy 2.0.2 + scipy 1.13.1, each runs in under 15 s unless noted):
`/private/tmp/claude-501/-Users-carson-Projects/654244a3-b38c-45a0-96af-d7e5f0aac6ce/scratchpad/gap6/`.
The folder also holds files from an earlier, unfinished gap-6 attempt (timestamps 03:36-04:13 IST). The ones written for this
report are: `load.py` → `outcomes.json`, `verify.py` → `sets.json`, `model.py` → `model.json`, `ppc.py`, `cost.py`,
`optset.py` → `optset.json`, `sim.py` → `sim.out`/`power.json`, `table.py`, `factorial.py` → `factorial.out`, `sens.py` →
`sens.out`/`sens2.out`, `decide.py` → `decide.out`, `probe.py` → `probe.out`, `probe2.py` → `probe2.out`, `race1_factorial.py`
→ `race1_factorial.out`, `e4.py` → `e4.out`, `hybrid.py` → `hybrid.out` (10 min), `final_design.py` → `final_design.out`
(1 min). The earlier attempt's `power_eog.txt` and `power2.txt` were used only as an independent cross-check (sect. 2.4).

## 0. Answers in one screen

| Question | Answer | Evidence |
|---|---|---|
| Are the critique's measurements right? | **Yes.** Race-1 arms disagree on 9.87 of 51 tasks per pair (min 5, max 13). r_v4 and p_v4 both score 18/51 with 10 discordant (5 each way). Of the 51 tasks, 24 were solved by no arm, 5 by all 6 and 22 by some. One caveat: p_v4 ran a looser budget (6 min/110 calls), so it is not a pure replicate | `verify.py` |
| Was "all paired p > 0.14" right? | **Only against v4** (smallest two-sided p 0.34). Among all 15 arm pairs, v9_eog beat v9_eo 7-0 (p = 0.016) and v9_og 8-1 (p = 0.039). Neither survives Holm correction over 15 pairs (0.23) | `verify.py` |
| What does "±3 tasks" mean? | It is **one** SD of the difference between two single runs on 51 tasks (model: 3.07). The 95% band is about **±6** | `ppc.py` |
| Per-task model | A two-way logistic model, logit p = task difficulty + bundle offset. The difficulty distribution is nonparametric, fitted to **1,112 task-runs from 20 independent runs**. It reproduces race 1: 24.0 zero-solve tasks predicted vs 24 observed, 10.2 vs 9.9 pairwise discordance, 22.0 vs 22 mixed tasks, and 9.8 vs 10 for r_v4 vs p_v4 | sect. 1 |
| Power of the race as designed (1 run per arm) | **8-18 %** for a +3 lever, **16-49 %** for +5 (one-sided α 0.05). With α split over 4 levers, 2-6 % and 5-21 %. This confirms the critique's "about 9 %" | `table.py` |
| Replicates per arm for 80 % power, +3 | If +3 is measured on the raced set: **5** (mixed22), **8** (51), **8** (74). If +3 is the lever's effect on the 74 and spread evenly (logit scale), mixed22 sees only 1.9 of it: **13** (mixed22), **10** (51), **8** (74) | sect. 2, table 2a |
| Same for +5 | 2 / 3 / 3 on the raced set; 5 / 4 / 3 for a lever defined on the 74 | table 2a |
| Pod-hours per arm-replicate (2×H100, measured) | mixed22 **0.18**, R30 0.22, 51 **0.46**, 74 **0.67**. v9_eog spent 60 % of its arena time on the 24 never-solved tasks | `cost.py`, `table.py` |
| Should the race drop the never-solved tasks? | **No.** For uniform levers the contested tasks give about 10 % more power per pod-hour. But when a lever's gains land on hard tasks and its losses on easy ones, a contested-only race has 12-21 % power where the full arena has 51-76 %. The 3x-harder hidden set rewards exactly that kind of gain | `hybrid.out`, sect. 4.1 |
| The bigger lever | **A fractional-factorial design instead of one lever per arm.** At equal pod-hours, per-lever power for +3 rises from 0.70 to 0.88 (R30, 40 runs/task) and from about 0.37 to 0.70 on the arena. The type-I rate holds at 0.04-0.05 | `factorial.out`, `hybrid.out`, `sens2.out` |
| Does race 1's rule ship regressions? | Race 1's "keep every lever whose count beats control" rule **includes a harmful lever 16-32 % of the time** in simulation. The recommended rules included one in 0 of 3,000 simulations (uniform levers) and 0 of 800 for the final design, including a lever whose hidden gains offset larger losses (net −2) | `decide.out`, `final_design.out` |
| Plan | Stage 1: 2^(4-1) factorial, 8 bundles × 2 replicates × 51 arena tasks, plus one v4 anchor (**7.9 pod-h**). Stage 2: the assembled v10, 2 passes on the 74 plus 1 extra pass on the 25 rare tasks (**1.6 pod-h**). Total with start-up about **10.5 pod-h ≈ $73** at $6.98/h, against $16 for the race as designed | sect. 5 |
| Leaderboard noise | One public-LB score (60 tasks at 0.12) has a run-noise SD of **0.033**. The leader's 0.15 against our 0.12 is about 1 SD. A Kaggle submission cannot rank levers either | `probe.out`, sect. 6 |

## 1. Data and per-task solve probabilities

### 1.1 Runs used
Loader: `load.py` (outputs per run below). Independent runs only. The Kaggle-env rescore (`eval/kaggle/rescore_fair`) re-tests the
same eval3 patches, so it is listed but not fitted.

| family | runs | budget / env | tasks | solved (valid tasks) | source |
|---|---|---|---|---|---|
| race1 | r_v4, r_v9_c, r_v9_eo, r_v9_eg, r_v9_og, r_v9_eog | 5 min/70 calls/150 turns/180 s, 2×H100, pod env | 51 arena | 18, 15, 14, 16, 14, 21 | `eval/race1/runs/*/task_results.jsonl` |
| race1 | c_v9_eg, c_v9_eog | same | 23 other valid | 7, 7 | same |
| eval3 | p_v4, p_v6, p_v7, p_v8 | 6 min/110 calls (looser), H100, helpers broken | 74 | 26, 22, 24, 21 | `eval/eval3/eval/runs/p_v*/task_results.jsonl` (`eval/h100b/runs/p_v4` is byte-identical) |
| Kaggle L4 | e74_v2, e74_v3 | 5 min/60 calls/80 turns, L4×4 | 74 | 19, 22 | `eval/kaggle/e74_v*/results.jsonl` |
| H100 conc 8 | v3_conc8, v4_conc8 | 4 tasks/GPU | 74 | 19, 21 | `eval/experiments.sqlite` table `runs` |
| sw1 | sw1_v1, _t10, _t10_low, sw1_v2 | 6 min, A40, older single-agent configs, dev47 | 42 of the 74 | 5, 5, 9, 10 | `eval/runs/sw1_*/task_results.jsonl` |

Total: 1,112 task-runs on the 74 valid tasks (fit B) and 352 in race 1 alone (fit A).

### 1.2 Model
`model.py`: logit p(task i solved by run j) = θ_i + α_j. θ follows a nonparametric distribution on an 81-point grid over
[-9, 7], fitted by EM (Kiefer-Wolfowitz NPMLE). α_j is a fixed offset per bundle-run, with c_v9_eg/c_v9_eog tied to
r_v9_eg/r_v9_eog and α(v9_eog) = 0. Each task gets a posterior over θ, and every simulation below draws θ_i from it.
Using those draws rather than plug-in rates is the bootstrap: it carries both run noise and our uncertainty about each task.

Fitted offsets in fit B (logit, vs v9_eog): r_v4 −0.34, p_v4 −0.30, p_v7 −0.65, r_v9_eg −0.82, r_v9_c −0.94, e74_v3 −0.99,
r_v9_eo/og −1.15, sw1_v1 −2.94. Cochran's Q across the six race-1 arms is 7.57 (df 5, p = 0.18), so arm differences in race 1
alone are not significant.

### 1.3 Posterior predictive checks (`ppc.py`, 4,000 draws)

| statistic (race 1, 51 tasks, 6 arms) | observed | fit B predicted (90 % band) | fit A (race 1 only) |
|---|---|---|---|
| solve-count histogram 0..6 | 24, 6, 1, 5, 5, 5, 5 | 24.0, 4.4, 4.4, 4.4, 3.9, 4.8, 5.0 | 24.8, 5.0, 1.7, 3.7, 5.6, 5.0, 5.1 |
| mean pairwise discordance | 9.87 | 10.17 (8.5-11.9) | 9.45 (7.5-11.5) |
| mixed tasks | 22 | 22.0 (18-26) | 21.0 (17-26) |
| r_v4 vs p_v4 discordance | 10 | 9.8 (6-14) | n/a |

The only miss is the "solved by 2 of 6" bin (1 observed, 5th percentile 2). Fit B is primary. Fit A has only 2 runs on the
23 non-arena tasks, which leaves their posteriors wide, so it is a pessimistic sensitivity case.

### 1.4 What the model says per task set (v9_eog level, fit B)

| set | tasks | expected solves per run | Σ p(1−p) | discordant tasks between two runs of the SAME bundle | SD of one run's total |
|---|---|---|---|---|---|
| mixed22 | 22 | 13.9 | 3.51 | 7.0 | 1.87 |
| all-solved 5 | 5 | 4.4 | 0.44 | 0.9 | 0.66 |
| never-solved 24 | 24 | 1.25 | 0.77 | 1.5 | 0.88 |
| arena 51 | 51 | 19.6 | 4.72 | 9.4 | 2.17 |
| valid 74 | 74 | 27.6 | 5.39 | 10.8 | 2.32 |

**Race 1's 6 runs misclassify some tasks** (`optset.py`, "other" = solves in the 12-14 non-race runs):
- rich_3718 is 0/6 in race 1 but 8/12 elsewhere (p ≈ 0.64). The r_v4 failure is a real partial fix: the subtitle style
  assertion fails (`eval/race1/runs/r_v4/test_outputs/rich_3718.log`).
- fastapi_13537 is 6/6 in race 1 but 2/8 elsewhere (p ≈ 0.66).
- rich_3278 and rich_3470 are 1/6 in race 1 and 0/12 elsewhere (p ≈ 0.05).
- The 23 non-arena valid tasks split cleanly: 8 are solved in ~every run (p ≈ 0.94-0.99), and 15 are solved in none (0/10-0/14).

**R30**, the pre-registered contested set: every valid task with posterior p(1−p) ≥ 0.05 at v9_eog level (`optset.json`
`prac`). That is mixed22 minus {rich_3278, rich_3470}, plus the 5 all-solved tasks, rich_3718, and fastapi_14301, fastapi_14492,
requests_6644 and rich_3067. It holds 80 % of the 74-task information Σ p(1−p), against 65 % for mixed22. The 25 arena tasks
outside R30 are the **rare25** (sect. 5.3).

## 2. Power: replicates per arm for 80 %

### 2.1 Method (`sim.py`)
Each simulation draws θ_i from its posterior, simulates r runs of the control and r runs of the treatment, and applies a
one-sided exact sign test to the discordant (task, replicate) cells, pairing replicate k with replicate k. Runs are independent
because the seed never reaches vLLM (`research/config_space.md:28`). The control is v9_eog level, with 4,000 simulations per
cell. The effect models are:
- **E0 local**: +Δ expected solves on the raced set itself (the critique's framing).
- **E1 lever74**: one logit shift for every task, calibrated to +Δ over the 74. A lever's effect belongs to the lever, not
  to the subset raced.
- **E2 heterogeneous**: E1 plus per-task noise of SD 1 logit, so some tasks get worse, with the net held at Δ.
- **E3 catalog11**: the shift applies only to the 11 "likely" tasks of `research/task_catalog.md:451`.
- **E4 gains and losses** (`e4.py`): +(Δ+2) spread over a random half of the 74 and −2 over the other half.

### 2.2 Table 2a: fit B, one-sided α = 0.05 (one lever vs control)
Cell = replicates per arm for 80 % power (pod-h per arm) [effect realised on the raced set]. Source `table.py` over `power.json`.

| Δ | model | mixed22 | R30 | arena51 | valid74 |
|---|---|---|---|---|---|
| +3 | E0 local | 5 (0.9 h) [3.0] | 6 (1.3 h) [3.0] | 8 (3.7 h) [3.0] | 8 (5.3 h) [3.0] |
| +3 | E1 lever74 | 13 (2.3 h) [1.9] | 11 (2.5 h) [2.2] | 10 (4.6 h) [2.6] | 8 (5.3 h) [3.0] |
| +3 | E2 heterogeneous | 14 (2.5 h) [1.8] | 12 (2.7 h) [2.1] | 10 (4.6 h) [2.6] | 9 (6.0 h) [3.0] |
| +3 | E3 catalog11 | 9 (1.6 h) [2.3] | 13 (2.9 h) [2.1] | 9 (4.2 h) [2.8] | 9 (6.0 h) [3.0] |
| +3 | E4 gains+losses | >16 [1.0] | >16 [1.1] | 14 (6.5 h) [2.3] | 10 (6.7 h) [3.0] |
| +5 | E0 local | 2 (0.4 h) | 2 (0.4 h) | 3 (1.4 h) | 3 (2.0 h) |
| +5 | E1 lever74 | 5 (0.9 h) [3.0] | 5 (1.1 h) [3.5] | 4 (1.9 h) [4.3] | 3 (2.0 h) [5.0] |
| +5 | E3 catalog11 | 6 (1.1 h) [3.1] | 9 (2.0 h) [2.5] | 4 (1.9 h) [4.5] | 4 (2.7 h) [5.0] |
| +5 | E4 gains+losses | >16 [1.7] | >16 [1.2] | 6 (2.8 h) [3.8] | 4 (2.7 h) [5.0] |
| +1, +2 | any | >16 almost everywhere (+2 local on mixed22: 12) | | | |

### 2.3 Table 2b: with α split over 4 levers (one-sided 0.0125)
+3: E0 needs 8 / 9 / 11 / 12 replicates (mixed22 / R30 / 51 / 74). E1 needs >16 / 16 / 14 / 12. +5: E0 3 / 3 / 4 / 5, E1
8 / 7 / 5 / 5. Five one-lever-per-arm arms at 12 replicates on the 74 would cost 5 × 8.0 = 40 pod-h (≈ $280).

Power at r = 1 (the race as designed), α = 0.05: +3 E0 0.14-0.18, E1 0.08-0.15; +5 E0 0.33-0.49, E1 0.16-0.32 (`table.py`).

Fit A (race 1 only) is harsher under E1: +3 needs >16 replicates on mixed22 and R30, 13 on 51 and 9 on 74. The difference comes
from fit A's wide posteriors on tasks it saw only twice (sect. 1.3).

### 2.4 Cross-check against the earlier attempt
That attempt used its own code (`power_eog.txt`, 03:43 IST). For E0 +3 it found 80 % power at about 6 replicates (mixed22), 8 (51)
and 8-9 (74). Mine are 5 / 8 / 8. For E1 +3, mixed22 realised 1.95 of the 3 (mine 1.87) and needed about 13 replicates (mine 13).
Its null checks show that the pooled sign test runs conservative (0.013-0.037 at nominal 0.05) and a normal-approximation z
test anti-conservative (0.055-0.067) (`power2.txt`). The plan therefore uses exact or permutation tests only.

## 3. Pod-hours

Throughput (`cost.py`): race 1 ran 306 task-runs in 2.78 h wall (11:30:13-14:17:04 UTC, `eval/race1/progress.log`). Summed
agent seconds were 38,975, so effective concurrency was **3.89** (2 arms at a time, each at 1.95-1.99 of 2 slots). That is
110 task-runs/h per 2×H100 pod.

Mean seconds per task (race 1, 6 arms): mixed22 111.7, all5 92.2, never24 **149.0**, arena51 127.4. For v9_eog: 99.3 / 117.1 /
**172.1** / 135.3. The never-solved tasks run longest because they hit caps, so they took 55 % (pooled) to 60 % (v9_eog) of arena
pod time.

| pod-h per arm-replicate | mixed22 | core27 | R30 | arena51 | valid74 |
|---|---|---|---|---|---|
| measured per-task seconds, concurrency 3.89 | 0.176 | 0.208 | 0.224 | 0.464 | 0.666 |
| flat 135 s, concurrency 4 (brief's figure) | 0.206 | 0.253 | 0.281 | 0.478 | 0.694 |

Pod price: $6.98/h for 2×H100 SXM (`eval/ledger.md`, 2026-09-26 07:20 and 14:50). Start-up before the first arm was about 30 min
in race 1: the first alert is at 11:08:35 UTC ("GPUs at 0% for 10 min"), and the first arm START is at 11:30:13
(`eval/race1/alerts.log`, `progress.log`). Exact boot time is UNVERIFIED.

## 4. Two design changes worth more than extra replicates

### 4.1 Keep the never-solved tasks in the race, but spend more on the contested ones
Information per task scales with p(1−p) and cost with its seconds (sect. 1.4, 3). Seconds per unit of information: mixed22 699,
core27 739, R30 726, arena51 1,376, valid74 1,728 (`optset.py`). For a uniform lever (E1), a contested-only race is therefore
about twice as pod-efficient per replicate, as the critique says.

But a contested-only race is blind to levers whose gains land on hard tasks. At equal cost, per-lever power in a 2^(4-1)
factorial (`hybrid.py`, 600 simulations, sign-flip permutation test):

| design (8 bundles) | pod-h | E1 +3 | E1 +5 | E4 +3 | E4 +5 |
|---|---|---|---|---|---|
| R30 only, r = 3 | 5.4 | 0.69 | 0.92 | 0.14 | 0.21 |
| R30 only, r = 4 | 7.2 | 0.78 | 0.97 | 0.12 | 0.21 |
| **arena51, r = 2** | **7.4** | **0.70** | **1.00** | **0.51** | **0.76** |
| R30 r = 3 + rare25 r = 1 (stratified) | 7.5 | 0.68 | 0.96 | 0.49 | 0.71 |

Null false-positive rate for the stratified design: 0.042. The E4 shape is a lever that unlocks hard tasks while breaking a few
easy ones, for example a gate that reverts some correct fixes. That is plausible, and the hidden set is about 3x harder than
the public one (0.12 vs 0.36, `research/task_catalog.md:5`), so gains on hard tasks are likely the ones that carry over
(UNVERIFIED). The uniform arena51 × r = 2 design is as good as the stratified one and simpler.

### 4.2 Fractional factorial instead of one lever per arm
With K = 4 levers, one-lever-at-a-time (OFAT) gives each lever only its own arm and the control arm. A 2^(4-1) resolution-IV
design (8 bundles, D = A⊕B⊕C) uses every run for every lever: each main effect compares 4 bundles with the lever on against 4
with it off. At equal task-runs (`factorial.out`, fit B, additive logit levers):

| set, runs/task | α | OFAT per-lever power (+3) | factorial per-lever power (+3) | null rate OFAT / factorial |
|---|---|---|---|---|
| R30, 40 | 0.05 | 0.70 | 0.88 | 0.04 / 0.05 |
| R30, 40 | 0.0125 | 0.45 | 0.66 | 0.01 / 0.01 |
| R30, 80 | 0.0125 | 0.81 | 0.94 | 0.01 / 0.01 |
| mixed22, 40 | 0.05 | 0.60 | 0.84 | 0.04 / 0.05 |

By replicate count on R30 (`sens2.out`, α 0.05), factorial vs OFAT: 8 runs/task 0.36 vs 0.10, 16 runs 0.56 vs 0.32, 24 runs
0.70 vs 0.41 (+3). For +5: 0.58 vs 0.21, 0.83 vs 0.65, 0.94 vs 0.78. Fit A gives 0.55 at 24 runs for +3 and 0.85 for +5.

Caveat: this assumes levers add on the logit scale. The catalog expects at least one interaction ("the gate's feedback is
useless if the fixer cannot land the follow-up edit", `research/task_catalog.md:319`). Resolution IV keeps main effects clear of
two-way interactions but aliases those interactions in pairs (AB=CD, AC=BD, AD=BC). The plan checks them and, when triggered,
folds over to the full 2^4 (sect. 5.2).

### 4.3 What each rule ships (`decide.py`, 3,000 simulations; value = sum of the true Δ74 of the levers shipped)

| scenario (true Δ74 of 4 levers) | rule | pod-h | E[shipped Δ74] | P(harmful lever included) | P(null lever included) |
|---|---|---|---|---|---|
| S1 (+5, +3, 0, −2) | race 1: 1 run on 51, ship top arm | 2.3 | +4.11 | 0.00 | 0.03 |
| | race 1: keep levers whose count beats control | 2.3 | +6.25 | **0.23** | 0.44 |
| | OFAT r = 8 on R30, sign test α 0.0125 | 9.0 | +5.93 | 0.00 | 0.01 |
| | factorial r = 3 on R30, α 0.05 | 5.4 | +7.40 | 0.00 | 0.05 |
| S2 (+3, +3, −2, −3) | race 1, top arm | 2.3 | +2.54 | 0.01 | n/a |
| | race 1, beats control | 2.3 | +3.61 | **0.32** | n/a |
| | factorial r = 3 on R30, α 0.05 | 5.4 | +5.17 | 0.00 | n/a |
| S3 (0, 0, 0, −3) | race 1, top arm | 2.3 | −0.07 | 0.02 | 0.66 |
| | race 1, beats control | 2.3 | **−0.49** | **0.16** | 0.69 |
| | factorial r = 3 on R30, α 0.05 | 5.4 | 0.00 | 0.00 | 0.15 |

For the recommended design (factorial, arena51, r = 2, permutation p < 0.05), `final_design.out` gives:

| scenario (true Δ74 of 4 levers) | inclusion rate per lever | E[shipped Δ74] | P(shipped net < 0) |
|---|---|---|---|
| S1 E1 (+5, +3, 0, −2) | 0.98, 0.69, 0.04, **0.00** | +6.98 | 0.000 |
| S3 E1 (0, 0, 0, −3) | 0.05, 0.04, 0.04, **0.00** | 0.00 | 0.000 |
| S4 E4: (+5/−2 net +3), (+5/−2 net +3), (+2/−2 net 0), (+2/−4 net −2) | 0.56, 0.53, 0.02, **0.00** | +3.28 | 0.000 |

(800 simulations per scenario, 400-flip permutation p-values.) The harmful lever was never included, including the E4-shaped one
whose +2 gains are hidden among its −4 losses.

The costly error is shipping a harmful lever. A null lever costs about nothing unless it adds time, and the time gate in
sect. 5.3 catches that. A one-sided test at 0.05 per lever is therefore the right threshold. Bonferroni gives up power to guard
against a harmless error.

### 4.4 Race 1 read as a factorial (`race1_factorial.py`)
The v9 arms form a partial 2^3 design over edit, output and gate (c = 000, eo = 110, eg = 101, og = 011, eog = 111). Main
effects on the 51 tasks:

| factor | effect | one-sided p | 90 % task-bootstrap CI |
|---|---|---|---|
| edit | +2.50 | 0.13 | −1.0 to +6.2 |
| gate | +2.50 | 0.11 | −0.8 to +5.8 |
| output | +0.83 | 0.36 | −2.8 to +4.8 |

eog − c is +6 (9 wins, 3 losses). The design is unbalanced, and helpers were missing in 24 of the 51 v9_eog tasks
(`research/test_plan.md:51-55`, F2), so these are diluted, confounded estimates. Their direction supports edit and gate.

**Winner's curse** (`probe.py`): six identical arms at race 1's mean level have an expected max of 18.9 and an expected lead of
the max over the other five of **3.36 tasks**. v9_eog's lead was 5.6 (21 vs 15.4), with P = 0.07 under "all arms equal". Against
v4 it went +5/−2 (one-sided p = 0.23). v9_eog is a reasonable base, but its true advantage is probably nearer +2 than +5
(rough, UNVERIFIED).

## 5. Race plan (pre-registered: every threshold below is fixed before any run)

### 5.0 Scope
- **Base = v9_eog plus correctness fixes that cannot plausibly hurt.** These are not raced: the helper path (`$TMPDIR/swe`), the
  hang-safe `run.py` (gap 5 sect. 6.4), the protected-file and test-file guard (4 rescore runs failed because the agent edited a
  test file, `eval/kaggle/rescore_fair`; 10 of 47 v9_eog patches touched protected files, `research/test_plan.md:50`), and the
  non-empty-patch rule.
- **Factors A-D = the four behavioural levers whose sign is uncertain** (for example REPRO, GATE, CONTEXT/SIBLING, RETRY from
  `research/task_catalog.md:304-317`; the choice is Carson's, UNVERIFIED). With 3 levers, use the full 2^3 (8 bundles, same cost).
  With 5-7, use a 16-bundle resolution-IV fraction at r = 1 on the 51.
- Budget: faithful 5 min / 70 calls / 150 turns / 180 s (race 1 `BUDGET` lines). Temperature stays at the shipped value.
  Temperature 0 would cut noise but measure a different policy, and vLLM batch nondeterminism is UNVERIFIED
  (`research/config_space.md:213`).

### 5.1 Stage 0 (free, before any GPU)
1. `make_variant.py` generates the 8 bundles (A, B, C on/off; D = A xor B xor C). Record each bundle's sha256.
2. The analysis script (`analyze_factorial.py`, to be written) is frozen and tested offline on race 1's partial design. It must
   reproduce sect. 4.4 and a null check on r_v4 vs itself.
3. Test-plan CI gates green (`research/test_plan.md` sect. 6), plus the 1-3 task canary per bundle, as race 1 did (about 2 min each).

### 5.2 Stage 1: factorial ranking race (7.9 pod-h, about $55)
- Runs: the 8 bundles × **2 replicates** × the **51 arena tasks** (`data/arena_ids.txt`) = 816 task-runs (7.42 pod-h). Add one
  **v4 anchor** pass on the 51 (0.46 pod-h).
- Order: replicate 1 of all 8 bundles, then replicate 2, two bundles at a time (one per GPU, 2 tasks per GPU). Pairings are
  shuffled so no bundle always shares the pod with the same partner.
- **Validity**
  - The v4 anchor must score 14-22/51 (model 5-95 % band; `r_v4` predictive mean 18.0). Otherwise the environment has drifted
    since race 1: stop and diagnose before reading any lever.
  - A bundle-replicate is rerun if more than 2 tasks end with harness or sandbox errors. ContextWindow crashes and agent
    timeouts count as agent failures, not harness errors.
- **Statistic per lever j**: T_j = Σ over the 51 tasks of (mean solved with j on − mean solved with j off), over 4 bundles × 2
  replicates on each side. p-value from a sign-flip permutation (100,000 flips, one-sided).
- **Decision per lever**
  - INCLUDE if p_j < 0.05.
  - FLAG HARMFUL if the reverse one-sided p < 0.05.
  - Otherwise EXCLUDE.
  - Also report T_j with a 90 % task-bootstrap CI, and T_j split into R30 and rare25 (descriptive).
- **Interaction check**: compute the 3 aliased two-way contrasts (AB+CD, AC+BD, AD+BC) on the same scale. If any has p < 0.05
  (two-sided), run the 8 fold-over bundles to complete the 2^4 (another 7.42 pod-h) before assembling.
- **Operating characteristics** (sect. 4.1, 4.3): per-lever power +3: 0.70 (E1) / 0.51 (E4); +5: 1.00 / 0.76. Null false-include
  rate 0.04-0.05 per lever. Harmful-lever inclusion: 0 of 800 in every scenario (`final_design.out`, sect. 4.3).

### 5.3 Stage 2: confirm the assembled v10 (1.6 pod-h, about $11)
v10 = base + INCLUDED levers. If that combination is one of the 8 bundles, its Stage-1 runs are reported alongside, but Stage 2
still runs.
- Runs: **2 full passes on the 74** (1.33 pod-h) plus **1 extra pass on the rare25** (0.27 pod-h), so rare25 gets 3 passes.

| gate | rule | calibration (fit B) |
|---|---|---|
| G1 integration | FAIL if the two-pass total on the 74 is **< 50** | P(fail) = 0.047 if v10 is only v9_eog-level; 0.53 if v10 is 3 worse. If v10 is +3, P(total ≥ 60) = 0.70 (`race1_factorial.out`) |
| G2 easy sentinel | FAIL if either pass misses **≥ 2** of fastapi_14794, fastapi_14786, fastapi_14372, rich_3905 | P = 0.005 per pass at v9_eog level (`probe.out`) |
| G3 test files | FAIL if any Stage-2 patch touches a file in its task's test_patch | 4 such failures in the rescore |
| G4 wall time | FAIL if the projected Kaggle wall exceeds 11 h (`research/test_plan.md:415`, R74, L4/H100 factor 163/135) or `max_time_minutes` > 5.5 | gap 5 sect. 4 |
| C1 capability (informational, not a ship gate) | CLAIM a capability gain if the 3 passes over rare25 total **≥ 6 solves** | H0 (v9_eog level) mean 2.1, P(≥ 6) = 0.030. Detection: 0.36 if the lever unlocks 2 rare tasks at p = 0.5, 0.65 for 3, 0.83 for 5 at 0.4, 0.90 for 8 at 0.3 (`probe2.out`) |

Probe notes (the rare25 are the 25 arena tasks outside R30, 3,737 s per pass):
- A single pass is only a screen. With threshold ≥ 3 (H0 0.032), detection is 0.19-0.58.
- Two-stage "confirm what pass 1 solved" with 4 replicates each was weaker still (0.08-0.22, `probe.out`), so it is not used.

**Ship rule**: submit v10 only if G1-G4 all pass. If G1 or G2 fails, submit the best-scoring Stage-1 bundle that passes G2-G4
on its own two full passes (a new 1.3 pod-h run). If no lever is INCLUDED, v10 = base, and Stage 2 still runs.

### 5.4 Cost and stopping
| item | pod-h | $ at 6.98/h |
|---|---|---|
| Stage 1 (8 bundles × 2 × 51) | 7.42 | 52 |
| v4 anchor | 0.46 | 3 |
| Stage 2 (2 × 74 + rare25) | 1.60 | 11 |
| start-up and canaries (about 0.5 h per session, 2 sessions) | ~1.0 | 7 |
| **total** | **~10.5** | **~73** |
| conditional fold-over | +7.42 | +52 |
| for comparison: race as designed (5 arms × 1 × 51) | 2.32 | 16, at 8-18 % power per lever |

Pod rules from CLAUDE.md apply. The chain's last step stops the pod itself (`runpodctl`), traces and results are copied off first,
and there is no idle gap between Stage 1 and Stage 2. The Stage-2 bundle is assembled by a script from the Stage-1 decisions,
so it can be chained. Stage 1 can be split over two pods to halve wall time at the same cost.

## 6. Leaderboard noise (`probe.py`)
Hidden tasks are modelled as the public posterior shifted on the logit scale to mean 0.12. That shape is UNVERIFIED.

| scenario | SD of score from run noise | SD including task sampling |
|---|---|---|
| 60 tasks at 0.12 (public LB) | 0.033 | 0.043 |
| 120 tasks at 0.12 | 0.023 | 0.031 |
| 60 tasks at 0.30 | 0.036 | 0.060 |

Two submissions of the same bundle differ by about ±0.047 (1 SD). The leader's 0.15 against our 0.12 is within 1 SD, and a 0.03
change between our own submissions is not evidence. The target of ≥ 0.30 has to come from a real shift that the pod race
measured, not from LB comparisons.

## 7. Caveats
- **Additive logit levers** are an assumption, and E4 shows how much the answer depends on where a lever's gains land. The design
  was chosen to stay reasonable under both E1 and E4.
- **Labels are pod-env.** Some tasks score differently in the Kaggle env (rescore v4 27/74 vs pod 26/74; disputed rich_3782 in
  `research/task_catalog.md:7`). Stage 2 could be rescored in the Kaggle env for free (UNVERIFIED capacity).
- **H100 is faster than L4** (135 vs 163 s/task, R74), so the pod race gives the agent more steps per 5 min than the scorer
  does. Differences between levers probably carry over, absolute rates less so (UNVERIFIED).
- **R30 and rare25 were chosen from the same data** the model was fitted on. That is fine for designing a race and wrong for
  quoting absolute rates. The Stage-1 decision uses all 51 tasks, so the choice of R30 does not affect it.
- **Catalog effect sizes are priors**, not measurements (0.7 / 0.35 per task, `research/task_catalog.md:302, 577`). The race is
  the measurement.
- **Fit B mixes budgets and env versions** through one offset per run. Fit A (race 1 only) is harsher (sect. 2.3). Under fit A the
  recommended Stage 1 still has 0.55 per-lever power for E1 +3 on R30 at 24 runs (`sens2.out`). Arena51 × r = 2 under fit A was
  not simulated separately (UNVERIFIED).

## 8. Reproduce
```
cd /private/tmp/claude-501/-Users-carson-Projects/654244a3-b38c-45a0-96af-d7e5f0aac6ce/scratchpad/gap6
python3 load.py && python3 verify.py && python3 model.py && python3 ppc.py && python3 cost.py && python3 optset.py
python3 sim.py 4000 > sim.out && python3 table.py
python3 factorial.py; python3 sens.py; python3 decide.py; python3 probe.py; python3 probe2.py
python3 race1_factorial.py; python3 e4.py; python3 hybrid.py; python3 final_design.py   # hybrid.py takes about 10 min
```
