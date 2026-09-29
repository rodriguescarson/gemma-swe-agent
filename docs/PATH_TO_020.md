# Path to 0.20 (12/58) by 2026-12-02

Written 2026-09-30 04:40 IST. This is a plan only: nothing here submits, pushes, starts a pod or spends.
Labels: MEASURED, ESTIMATE, INFERENCE, UNVERIFIED. Odds model: `research/path020/odds.py` (output in `odds.out`).
Revised the same day after an adversarial critique: changes are tagged [C1]-[C18] and listed with evidence in the
**Addendum: critique** at the end; the sensitivity model is `research/path020/odds_critique.py` (`odds_critique.out`).

## 0. Where we stand

- **Target.** 0.20 = 12 of the 58 public-LB tasks (MEASURED, hidden.md §0.1). v4 has scored 7 twice. The leader has 10.
- **sub6 (v10.1)** goes in at 05:31 IST today and scores around 16:00; prediction 0.12-0.14 (speed.md).
- **Fix quality must supply the new tasks.** Speed is capped at +0.5 to +2.8 of 60 (speed.md §6.2) [C18], public gains transfer at about 0.3× (hidden.md §3), and the reachable pool is about 10-12 (ESTIMATE). How many of the 58 are unwinnable is unknown: gold validates at 100% on the scorer (HOST, hidden.md §1.1), so pallets.md's 4.1% harness-trap rate does not carry over; only "within one test case" admissions (hidden.md §2) can be unwinnable, share unknown [C1].
- **Money.** RunPod billed $135.84 for Gemma pods through 29 Sep UTC (`list-pod-billing`, 04:25 IST today), so **about $364 of the $500 cap is left**; v11's $250 is inside it. No Gemma pod is running. The $364 is RunPod billing only (FI §6 counts nothing else); whether OpenRouter spend also counts against the $500 is unstated, and §5 shows both cases [C12].
- **Kaggle GPU.** 30 GPU-h/week, exhausted 29 Sep; reset day UNVERIFIED (Carson reads it on kaggle.com). A 74-task L4 run is about 3.5 GPU-h; queue time may count (743683, UNVERIFIED).
- **Slots.** 64 remain. One read has a run-noise SD of **1.9 tasks** (gap_6 §6).

## 1. Honest odds (ESTIMATE)

| scenario | hidden tasks, mean (p10-p90) | P(true rate ≥ 0.20) | P(mean of 3 reads ≥ 11.5) | P(best of 20 reads ≥ 12) |
|---|---|---|---|---|
| v10.1, nothing more | 7.7 (6.9-8.5) | <1% | <1% | 40% |
| plan without distillation | 9.4 (8.1-10.8) | **2%** | 9% | 85% |
| plan, distillation lands (P ≈ 0.29) | 10.7 (9.2-12.2) | 22% | 30% | 97% |
| plan, distillation pursued | 9.8 (8.3-11.4) | **8%** | 15% | 88% |
| **after critique** (case D): plan without distillation | 9.1 (7.9-10.4) | **0.6%** | 5% | 80% |
| **after critique** (case D): plan, distillation pursued (P ≈ 0.22) | 9.4 (8.0-10.8) | **3%** | 9% | 83% |

Inputs (the four rows above the critique line, kept as written at 04:40): v4 = 7.2 tasks; hidden-task gains v10.1 +0.5, speed +0.35, robustness +0.4, T 0.2 (kept only if better) about +0.3, fix quality +0.6, distillation +1.6 × 0.7 overlap; P(distillation lands) = 0.6 (LoRA works on the scorer) × 0.75 (teacher allowed) × 0.65 (lands by 8 Nov). Gains are assumed to add independently; if not, the odds are lower.

The critique rows change three inputs and nothing else: T 0.2 prior N(0, 0.5) instead of N(0.3, 0.8), because our only direct test found no effect [C2]; robustness N(0.3, 0.35) instead of N(0.4, 0.4), because the T2 trigger never occurs in 605 gold patches [C3]; P(LoRA applied on the scorer) 0.45 instead of 0.6, after the 09-29 re-test [C4]. If the four reliability levers (v10.1, speed, robustness, T) are 20% sub-additive because they harvest the same union of sometimes-solved tasks (hidden.md §3.5), the pursued row falls to 1.7% and 6% (case E) [C16]. The fix-quality lever (+0.6) is the **only** one for S3's flip/sweep and S6 together; the per-step gains in §4 must not add up to more than the model [C8].

**The last column is a warning, not a route.** The LB shows our best read, so enough resubmits of v10.1 alone would eventually print 0.20. The private LB, which pays, scores only the 2 submissions we select. **Success means a mean of at least 11.5/58 over 3 or more reads of one bundle, backed by a faithful paired run.** Finals are chosen on means, never on the maximum.

## 2. Evaluation ladder (climb only after the rung below passes)

| rung | instrument | cost | decides |
|---|---|---|---|
| 1 | Mac CI plus hidden.md §6 tests T1-T15 in `python:3.13-slim --cpus 2 --memory 4g` | $0 | nothing breaks |
| 2 | Golden L/F/V suites on the PROXY (OpenRouter Gemma bf16), dev split | about $2-5 per lever | stage effect by the spec §8 rule; screening only |
| 3 | Pallets hidden-like set: golden L/F on dev (204), pod run of 40-60 via `scripts/pallets/run_eval_pallets.py`; HOLDOUT (103) once per final | $1-3 proxy, about $10 pod | transfer to unseen repos |
| 4 | Pod on 2×H100 ($6.98/h), `G4_L4_SCALE` 1.7 and 3.2, factorial (gap_6 §5) | $20-25 per round | harm guard, lever effects |
| 5 | Kaggle 4×L4 faithful paired run, 74 tasks | 3.5 GPU-h per arm | **ship**, by a pre-registered paired rule (as for sub6) |
| 6 | Daily LB slot | about 10.5 h | catastrophe check (≤ 0.03 or ERROR), hidden-rate reading, submit-to-COMPLETE time T |

## 3. Daily submission policy

- **When.** One slot a day at 05:31 IST (00:01 UTC), from the VPS. Its reading is pre-registered in `eval/ledger.md`.
- **Priority:**
  1. A new candidate that passed rung 4. Its first read is only a catastrophe check; becoming the best needs rung 5.
  2. Replicate reads of the best bundle, up to 3.
  3. The runner-up. Rung-2-only bundles are never submitted.
  - **Exception [C9]:** a bundle whose only changes are hidden-only mechanics (the fixes for hidden.md T1-T3, T13's cap parity, and the 5.5 cap once S1's T6 rule licenses it) may take a slot after rung 1. Rungs 2-5 run on repos that never exercise those paths (no ≥10 s imports, no namespace or `python/` roots, no new root modules: 0 of 605 gold patches add one, `research/path020/newfile_rate.out`), so waiting for them buys no information; the slot itself is the catastrophe check. The sparse base tree (T5/T6) is **not** in this exception: it changes the verify base on every task, public ones included. Carson's call.
- **Timing.** Every slot runs the read-only poller (`research/speed/poll_submission.sh`) for T.
- **Skipping.** Only to open a Kaggle GPU window.
- **Comparing bundles on the LB.** Use means over at least 3 reads each. The SD of a 3-vs-3 difference is 1.6 tasks, so rung 5 decides.
- **No repo-conditional probing** of the private set (hidden.md §7.6).
- **Finals.** Freeze Sat 28 Nov; the last 4 slots are reads of the 2 finalists; select both before Wed 2 Dec 23:59 UTC (Thu 3 Dec 05:29 IST).

## 4. Ranked steps

**S1. Read sub6 (today).**
- **What.** The poller runs from 05:31. The score and T6 come in around 16:00.
- **Gain** 0 (a measurement). **Cost** $0.
- **Gate.** Score ≤ 0.03 or ERROR: v4 stays the base. T6 ≤ 10.70 h: cap 5.5 is allowed; T6 ≤ 9.47 h: consider 6.0 (speed.md).
- **Carson.** Approve v10.1 replicate reads for 1-2 Oct (three reads with sub6), then v10.1.1 (S2) from 3 Oct if rung 1 is green [C9]. The quota is out, so these are free information.

**S2. v10.2: robustness plus speed (Mac, 30 Sep-2 Oct).**
- **What.** A new `submissions/v10_2` (v10.1 stays frozen):
  - Robustness (hidden.md §6): T1 slow-import calibration, T2 prefix separator rule, T3 namespace/non-src import check, T4 3.13 CI job, T5/T6 sparse base tree, T13 cap parity.
  - Speed ranks 1-4: 5.5 cap with `BUDGET_SCALE`, 60 s locator hard stop, one repro attempt and no probes, plan of at most 80 words.
- **Build it in two steps [C9].** v10.1.1 = T1-T3 fixes, T13 cap parity and speed rank 1 (the 5.5 cap with `BUDGET_SCALE`, once S1's T6 rule allows it): no behaviour change on public tasks, eligible for an LB slot after rung 1 (§3 exception). v10.2 = v10.1.1 + T5/T6 + speed ranks 2-4, which carry quality risk and go through rungs 2-4.
- **Gain.** Central about **+0.65 hidden tasks** (was +0.75):
  - speed: +0.23 to +0.84 (about 0 under the mixture model);
  - robustness: 0 to +1, central +0.3 (ESTIMATE, unsourced: hidden.md §5 finds the defects but puts no number on them; T2's trigger, a new root module with a scratch-like prefix, occurs in 0 of 129 competition and 0 of 476 Pallets gold patches, `research/path020/newfile_rate.out`, so T2 is insurance worth about 0) [C3].
- **Cost.** About 1.5 days of Claude work, plus about $2 for golden L at the hidden clock. Rung 2 needs the golden build, which is still running in another workflow; if it has not landed by 2 Oct, ranks 2-4 wait and v10.1.1 goes alone.
- **Gate.** Rung 1 green. On rung 2, speed.md §9.2's rule in full [C17]: `l_all_gold_files_named` not worse (paired, at most 1 net loss over about 30 cases × 3 samples); valid reproduction rate not down by more than 3 cases (the main risk of rank 3: 9 of 52 solves got their valid reproduction only on a retry); locator output tokens down ≥ 20%; L4-modelled locator seconds down ≥ 15 s at the hidden clock; and one F-suite run with 80-word golden plans not worse on `f_hidden_pass` (rank 4).
- **Tension.** Speed ranks 2-3 cut repro time, while diag_5's lever A (`v10_1_flip`) adds it. S3 measures both.
- **Carson.** $2 of OpenRouter.

**S3. Pod session A (4-5 Oct): one boot; the chain backs up and then runs `runpodctl stop`.**
- **What.**
  - (a) v4 vs v10.1 on the 40 packed Pallets dev tasks, after the pre-flight; or, cheaper for the same question, v10.1 alone on 80 (see Gain) [C5].
  - (b) A 2^(4-1) factorial (gap_6 §5) over the v10.2 base, flip, sweep (`v10_1_sweep`) and T 0.2 (`v10_1_t02`): 8 bundles × 2 replicates × 51 arena tasks, plus a v4 anchor, at scale 1.7. Only levers that were not "worse" on rung 2 go in.
  - (c) v10.2 vs v10.1 at scale 3.2.
  - (d) The assembled winner, 2 passes on the 74 tasks.
- **Gain.** 0 directly.
  - (a) sets direction, read against a size-adjusted bar, not 36% vs 12% [C5]. At the public per-stratum rates (hidden.md §2, pooled over 12 runs), dev40's gold churn alone predicts about **27%** and its longer PR-style statements alone about **42%** (`research/path020/pallets_expect.out`; the same method gives 34% on the public 74, which matches). Clearly below 27% means a loss beyond patch size (overfit to fastapi/rich tuning, or layout); near or above it means size and fix quality explain the gap. Click, Flask, Jinja2, Werkzeug and sympy are famous public repos, so (a) does **not** test the private-repo unfamiliarity of hidden.md §3.3 item 2.
  - (a) cheaper form: at n = 40 the 95% band around 27% is about ±14 points. The same task-runs spent on **v10.1 alone over 80 dev tasks** give about ±10. Graphs for 40 more tasks are a free download (about 1.1 GB), then `pack.py` and the CPU pre-flight (pallets.md §7). Keep the v4 arm only if the v4-vs-v10.1 transfer question is wanted, which pallets.md §7.3 says needs the 131 or 204.
  - (b) has 0.70 power per lever for +3 public tasks at one-sided α = 0.05 (gap_6 §5.2). The levers' own catalog sizes after halving are smaller, about +0.7 (sweep; the arm carries only the mechanical part, AB_L4 §1) to +1.6 (flip) public tasks, where power is well below 0.70 (gap_6 simulated only +3 and +5) [C7].
  - Flip + sweep ≈ +0.6 hidden (catalog flips × 0.3 × 58/74, halved). These are catalog priors (0.7 likely, 0.35 possible per task), not measurements (gap_6 §7).
  - T 0.2: about 0 (was −1 to +2). Our only direct test found no effect (pod sweep1, 47 tasks, all paired p > 0.45, update_0928 §1.3); the field correlation is among forks of one baseline [C2].
- **Cost.** About 12 pod-h, **about $85 (cap $95)**, checked against gap_6 §5.4 (10.5 pod-h for (b) and (d) with start-up) plus (a) and (c). **+7.4 pod-h (+$52) if the interaction check triggers the fold-over** (gap_6 §5.2). Budget for it: the flip lever adds reproduction work that speed ranks 2-3 remove (the Tension in S2), a known two-way interaction that the 2^(4-1) design aliases [C12].
- **Gate.** gap_6 §5.2's pre-registered rule [C7]: INCLUDE a lever at one-sided p < 0.05 and every round d ≥ −2; FLAG HARMFUL at reverse p < 0.05. The 0.70 power and the 0-of-800 harmful-inclusion figure belong to that α. (The draft's p ≤ 0.10 roughly doubles the false-include rate per null lever, to about 1 in 4 for at least one of three null levers.) Speed also needs p75 at least 15 s earlier at 3.2. The v4 anchor band (14-22/51) still applies at scale 1.7: p1_v4 solved 18 of the 51 arena tasks (`eval/pair1/eval/runs/p1_v4/task_results.jsonl`).
- **Carson.** Pod approval (batched approval A1, Sat 3 Oct).

**S4. The forum post now; LoRA gate G-A after free pre-checks (first day after the quota resets) [C10].**
- **What.**
  - **The post goes out now (30 Sep or 1 Oct), not at the quota reset.** It needs no GPU, it gates S7's teacher choice, and the host took 5 days from "soon" (09-24) to the answer (09-29, distill.md §2.1). Post `docs/v11/forum_question_distillation.md` under comment 3530102.
  - **Free pre-checks before G-A spends 2 GPU-h.** (1) Read 743508 for Abdul Muiz's promised re-test with both A and B randomised, and for a host fix (Ryan Holbrook, 09-26: "I will address"). (2) Compare the wheelhouse dataset version with the one he tested (vLLM 0.19.1). PLAN K1 already says to reopen only when the wheelhouse CRCs change: if they have not changed and his re-test is negative, skip G-A and drop S7. His unanswered question ("is the zeroing fix meant to be in the current Wheelhouse, or only on the scorer?") can be bumped in 743508 at no cost (draft only; Carson posts).
  - Otherwise G-A as planned: PLAN §6 row 1 on Kaggle 4×L4 with **both** `lora_A` and `lora_B` randomised (distill.md).
- **P(LoRA applied on the scorer): 0.45, not 0.6** (ESTIMATE) [C4]. PLAN's 0.6 predates the 09-29 re-test, in which the harness's own server path (`adk_submission.VllmServer`, `enable_lora=True`, adapter via `adapter_manifest`) listed no adapter in `/v1/models` and runtime loading returned 404 (`research/distill_evidence/t743508.json`). The `lora_A` caveat explains only his second, direct-vLLM test.
- **Gain** 0 (unlocks S7). **Cost** 0 for the post and the pre-checks; 2 GPU-h for G-A. **Gate** K1. **Carson** the push and the post.

**S5. Faithful pair and ship (6-9 Oct).**
- **What.**
  - The 6 Oct slot carries S3's winner (v10.3-rc), armed only if S3's rule passes.
  - Then a Kaggle L4 pair: v10.3-rc vs v10.1.
- **Gain.** Ships S2 + S3: about **+1.4 hidden tasks** (was +1.5; S2 +0.65, flip + sweep +0.6, T about +0.16 after C2-C3; range 0 to +3). **Cost** 7 GPU-h.
  - Rung 5 runs public tasks, where S2's levers are invisible: speed only matters at k ≥ 1.9, and T1-T3 never fire. For S2 the pair is a non-inferiority guard, not a measurement of the gain. Only flip and sweep can show on it, and even their catalog sizes are below what one pair resolves (AB_L4 §0: a real +3 lever reaches +4 about 40-50% of the time) [C6].
- **Gate.** Rung 5; if it passes, 2 more reads follow. **Plus the 12 h guard [C11]:** the 5.5 cap stays licensed only if the candidate's rung-5 mean agent time is at most 1.1 × v4's, i.e. **≤ 159 L4 s/task** (v4 144.6). speed.md §7.1's bound multiplies the in-clock time by max(m, 330/300), and its "5.5 is safe in every case" used v10.1's m = 1.01. At m = 1.15 the V = 0 bound is 12.03 h; at m = 1.2 the V = 0.4 h bound is 12.05 h (same formula as `research/speed/budget.py`). The flip lever (+8 to +14 s), the second fixer (S6) and a LoRA decode tax (S7) all raise m. Above 159 s: ship at 5.0. **Carson** pushes and arming.

**S6. Fix quality on unseen repos (6-15 Oct).**
- **What.**
  - After the golden build lands, add Pallets as a golden source (catalog labels for 204, `venv` field, `src/` `.pth`). The catalog labels (`root_cause`, `one_line_solution`; pallets.md §8, a labelling job with no OpenRouter) do not depend on the golden build and can start now [C10].
  - Run `ABLATION_REPAIR.md`.
  - Target what S3(a) fails on: multi-site and multi-file fixes, and statements under 25 words (0.09 solve rate on public).
  - Add a second fixer that fires on gate FAIL or an empty patch when at least 90 s remain (gap_2).
  - Pod session B covers Pallets-60 plus the 74.
- **Gain.** **+0.2 to +0.4 hidden beyond S3** (ESTIMATE; was +0.3 to +1) [C8]. The second fixer is worth +0.17 per 51 hidden-like tasks at k = 2.9 and 0 at k = 4.6 (gap_2 §8-9); the prompt parts of lever B that the sweep arm left out (AB_L4 §1.1) are about 1.05 catalog flips, +0.1 hidden after the same discounts. Multi-site completeness is lever B's target and is already in S3's +0.6; the odds model carries one +0.6 fix-quality lever for S3 and S6 together. "Right file, wrong or partial fix" is the largest loss bucket (19 of 30 v9_eog losses), which is why S6 stays, but its measured value so far is small.
- **12 h.** The second fixer raises m on failing tasks; the S5 guard (≤ 159 L4 s/task for the 5.5 cap) applies [C11].
- **Cost.** $5-10 OpenRouter, ≤ $50 pod, 7 GPU-h.
- **Gate.** Rungs 2 to 5.
- **Carson.** Approval A2 on Thu 8 Oct. Arm the reads for the 16-20 Oct Italy trip before leaving.

**S7. Distillation, v11-b (12 Oct-8 Nov), only if G-A passes and Q1 = yes.**
- **What.** Swap self-RFT (PLAN §4) for teacher trajectories run through v10.x, then PLAN P0, G-B, train, screen, Z and P4.
  - Order: a 40-task Pallets pilot (Qwen3-Coder-480B or DeepSeek-V4.1-Flash), then all of Pallets, then SWE-rebench up to 1k kept.
  - **The Pallets HOLDOUT never enters training.**
  - **Also out of training [C13]:** fastapi, rich, requests and httpx (distill.md §4.4: the public set is our only faithful yardstick; SWE-rebench must be filtered for them), werkzeug (PLAN's held-out repo), and a fixed eval-only slice of Pallets DEV that includes the tasks S3(a) and S6 measured on. "All of Pallets" otherwise consumes the whole 204-task dev split, and every later Pallets comparison of an adapter bundle is contaminated. Fix the slice before the pilot generates data.
  - **Provider [C14]:** calling an open-weight teacher through OpenRouter also brings in the host provider's and OpenRouter's terms. Pin one provider (`--or-provider`, `allow_fallbacks: false`) and read its terms once (distill.md §2.3).
- **Gain.** +1.6 (range +0.7 to +3.5) if it lands. With P ≈ 0.22 (was 0.29, after C4), that is about **+0.3 expected** (0.22 × 1.24, the model's mean gain after the 0.7 overlap; was +0.4).
- **12 h.** The LoRA-mode decode tax is unmeasured (distill.md §5.2); the adapter bundle needs the S5 guard (≤ 159 L4 s/task) to keep the 5.5 cap [C11].
- **Cost.** Data $1-3 (pilot), $25-157 (1k); about 27 h of tooling; pod about $105 (cap $160); about 15 GPU-h (P4).
- **Gate.** PLAN §1 (D ≥ +6 over 148 task-runs) and K1-K10. **Kill date: Sun 8 Nov.**
- **Carson.** Up to $160 of OpenRouter, the pod cap, the upload and pushes.

**S8. Integration and finals (9 Nov-2 Dec).**
- **What.**
  - The paper track closes Thu 12 Nov 23:59 UTC; the Resource entry is Pallets transfer plus the LoRA findings.
  - **Disclosure timing [C15]:** that is 20 days before the main deadline. Whether paper-track writeups are visible before 2 Dec is UNVERIFIED (743255 is unanswered, forum_update_0928 §4). Under CLAUDE.md's rule (publish bug reports at once; hold derived analysis and anything a rival could run with until submission), the Pallets harness fixes (`run_eval_pallets.py`, the `src/` `.pth` ordering, the httpbin stub) and the transfer numbers are the part to hold back or delay. The LoRA bug reports go out at once (PLAN §8). Carson decides what the entry contains; it credits takumuhata's CC0 dataset either way.
  - Run a confirmation pair of the assembled best vs the current best.
  - Freeze Sat 28 Nov, take reads, select.
- **Gain** 0 new (guards against a regression). **Cost** 7-14 GPU-h, about $25. **Carson** the final selection.

## 5. Budget

**Kaggle GPU per quota week** (reset UNVERIFIED):

- About 3 Oct: 9 (G-A 2, S5 pair 7).
- About 10 Oct: 7 (S6). About 17 Oct: 0-7 (Italy).
- 24 Oct-7 Nov: 15-22 (S7, plus one inconclusive round). 9-28 Nov: 7-14 per week (S8).

Every week fits in 30 h unless charged queue time is longer than the runs.

**Money.**
- Pods: $85 + $50 + $105 + $25 = **about $265 expected, $330 at the caps**, against $364 left. **Plus $52 if S3's fold-over triggers [C12]: $382 at the caps, over the $364.** If it triggers, S7's pod cap shrinks by the overrun, or S8's confirmation runs on Kaggle GPU only.
- OpenRouter: about $12 for screens, plus $25-157 if S7 runs.
- **If the $500 cap covers OpenRouter too [C12]:** expected about $265 + $12 + 0.34 × (about $90 of S7 data; spent only if G-A passes and Q1 = yes, 0.45 × 0.75) ≈ $307, inside $364; at the caps $330 + $52 + $12 + $157 = **$551**, $187 over. Then S7's data comes from DeepSeek-V4.1-Flash ($25-70 per 1k kept, distill.md §4.3) rather than Qwen3-Coder-480B ($67-157). Carson states which case applies.

## 6. What changes this plan

- **sub6 ≤ 0.03.** Stop and diagnose from T6 before using another slot.
- **Pallets clearly below the 27% size-adjusted bar (S3(a), C5).** Point S6 at locating and environment robustness; weight Pallets over the 74. (Was "near 12% for both bundles"; 12% vs 36% is not a clean test, see C5.)
- **G-A fails or Q1 = no.** Drop S7; the odds become the no-distillation row.
- **Wheelhouse unchanged and the 743508 A+B re-test negative.** Skip G-A as well (PLAN K1) and drop S7 [C10].
- **A candidate's rung-5 mean agent time above 159 L4 s/task.** It ships at the 5.0 cap, or loses levers until it fits [C11].
- **sub6 read.** Every gain in §4 scales with the base: speed.md's gains scale by sub6/0.12, and the odds model's base of 7.2 is 0.12 × 60, not the measured 7/58 (the difference, 0.2 tasks, is inside v10.1's lever and does not move the table) [C18].
- **Host opens the 26B-A4B MoE.** In-cap best-of-N becomes affordable (forum.md item 11); re-plan.

## Addendum: critique (2026-09-30, IST)

An adversarial read of this plan against `research/pallets.md`, `speed.md`, `distill.md` and `hidden.md` (and the
files they cite). Every change is tagged in the text above; old values are quoted here so the original stays readable.
No submission, push, pod, forum post or OpenRouter call was made. New evidence files, all re-runnable in seconds from
the repo root: `research/path020/odds_critique.py` (case A reproduces `odds.out` to within 0.001), `pallets_expect.py`,
`newfile_rate.py`, each with its `.out`.

### Unsupported gain claims

| tag | where | was | now | evidence |
|---|---|---|---|---|
| C1 | §0 | "2-3 of the 58 are unwinnable (ESTIMATE)" | unknown; only "within one test case" admissions can be unwinnable | The only source for a rate is pallets.md's 4.1% of tasks whose **gold** fails under harness semantics. The host validated gold at 100% on the scorer (hidden.md §1.1, 742882), so such tasks cannot be in the hidden set |
| C2 | §1, S3 | T 0.2 prior N(0.3, 0.8), about +0.39 expected after selection, more than the whole speed package; "T 0.2: −1 to +2" | N(0, 0.5), about +0.16; "about 0" | Our only direct test: pod sweep1, 47 tasks, all paired p > 0.45 (update_0928 §1.3, diag_5 lever D). The field's "every bundle ≥ 0.12 runs T 0.2" is a correlation among forks of one baseline |
| C3 | §1, S2 | robustness 0 to +2 "(hidden.md §5)", model N(0.4, 0.4) | 0 to +1, central +0.3, labelled unsourced; model N(0.3, 0.35) | hidden.md §5-§7 find defects E, F/I, K but give no gain. T2's trigger (a new root module with a scratch-like prefix) occurs in 0 of 129 competition and 0 of 476 Pallets gold patches; only 1 of 605 adds any file (`newfile_rate.out`) |
| C4 | §1, S4, S7 | P(LoRA applied on the scorer) 0.6 | 0.45 (ESTIMATE); P(distillation lands) 0.29 → 0.22; S7 expected +0.4 → +0.3 | distill.md §5.2 notes PLAN's 0.6 predates the 09-29 re-test. In that re-test the harness server path listed no adapter in `/v1/models` and `load_lora_adapter` returned 404, which the `lora_A` caveat does not explain (`research/distill_evidence/t743508.json`) |
| C5 | S3(a) | "about 36% means fix quality; about 12% means unfamiliar code" | a size-adjusted bar: churn predicts 27%, statement length 42%; not a test of private-repo unfamiliarity | Pallets gold patches are 2.7× larger at the median (pallets.md §5.2); public churn strata solve at 0.48 / 0.26 / 0.05 (hidden.md §2). `pallets_expect.out`: dev40 27% (churn) and 42% (words); the same method gives 34% on the public 74, matching the pooled rate. Click/Flask/Jinja2/Werkzeug/sympy are well-known public repos |
| C6 | S5 | "Realises S2 + S3: about +1.5" | "Ships S2 + S3: about +1.4"; rung 5 is only a non-inferiority guard for S2 | speed.md §6 (speed gains exist only at k ≥ 1.9); hidden.md §5 (T1-T3 fire on layouts the public 74 lack); AB_L4 §0 (one paired run confirms only large levers) |
| C7 | S3(b) | "0.70 power per lever for +3"; gate "p ≤ 0.10" | power stated at its α and for the levers' own sizes; gate restored to gap_6 §5.2 (one-sided p < 0.05, FLAG HARMFUL) | gap_6 §5.2's 0.70 and 0-of-800 harmful inclusions are for α = 0.05. At 0.10, P(at least one of three null levers included) ≈ 1 − 0.9³ = 0.27 against 0.14. The sweep arm carries only 2 likely flips (AB_L4 §1), about +0.7 public after halving |
| C17 | S2 gate | two of speed.md §9.2's conditions | all four, plus the F-suite check for rank 4 | speed.md §9.2. The dropped condition (valid reproduction rate) is the named risk of rank 3: 9 of 52 solves got their valid reproduction only on a retry (speed.md §3.3) |

### Double counting

| tag | where | was | now | evidence |
|---|---|---|---|---|
| C8 | S3 vs S6, §1 | S3 "flip + sweep ≈ +0.6" and S6 "+0.3 to +1" on the same target (multi-site completeness), while the odds model has one +0.6 fix-quality lever built from the completeness sweep's 2.45 catalog flips (`odds.py`) | S6 = +0.2 to +0.4 beyond S3 (second fixer about +0.19 of 58; B's left-out prompt parts about +0.1); the model's single lever covers both | `research/task_catalog.md:321` (sweep, 2.45 flips); AB_L4 §1.1 (the sweep arm omits B's prompt parts); gap_2 §8-9 (second fixer +0.17/51 at k = 2.9, 0 at k = 4.6). Per-step text gains had summed to about 0.3-1.0 tasks more than the model |
| C16 | §1 | v10.1, speed, robustness and T added independently | sensitivity row: 20% sub-additive | All four harvest the same union of sometimes-solved tasks (hidden.md §3.5, reachable pool 10-12). `odds_critique.out` case E: pursued P(true ≥ 0.20) 1.7%, P(mean of 3 ≥ 11.5) 6% |

### Rules and the 12 h budget

No step as written breaks a competition rule. Four guards were missing:

| tag | where | issue | fix | evidence |
|---|---|---|---|---|
| C11 | S5, S6, S7, §6 | "5.5 is safe in every case" was derived for v10.1 (m = 1.01). The bound is S + N·ovh + max(m, 330/300)·(A − S − N·ovh); levers that slow uncapped tasks raise m | the 5.5 cap stays only if the candidate's rung-5 mean agent time ≤ 1.1 × v4 = 159 L4 s/task; otherwise 5.0 | Same formula as `research/speed/budget.py`: sub3, V = 0: m = 1.15 gives 12.03 h; V = 0.4 h: m = 1.2 gives 12.05 h. Flip +8 to +14 s (AB_L4 §1); diag_5's full A-D package was 1.21-1.31 × r_v4; LoRA decode tax unmeasured (distill.md §5.2) |
| C13 | S7 | training plan named only the Pallets HOLDOUT as excluded | also exclude fastapi/rich/requests/httpx, werkzeug, and a fixed eval-only DEV slice | distill.md §4.4; PLAN's werkzeug hold-out; otherwise "all of Pallets" consumes the 204-task dev split that S3(a)/S6/S8 measure on |
| C14 | S7 | teacher via OpenRouter | pin one provider and read its terms | distill.md §2.3 (the host's ruling is "in accordance with their model license terms"; routing adds provider and OpenRouter terms) |
| C15 | S8 | paper-track Resource entry on 12 Nov | Carson decides what to hold back; credit the dataset | Deadlines (forum_update_0928 §1): paper 12 Nov, main 2 Dec. 743255 (publishing derived data) unanswered. CLAUDE.md "Time the disclosure": hold what a rival could run with until submission |

### Money

| tag | where | issue | fix | evidence |
|---|---|---|---|---|
| C12 | §0, S3, §5 | S3's cost omitted the conditional fold-over; §5 never summed pods and OpenRouter | +$52 (7.4 pod-h) budgeted; both cap readings shown: pods alone $382 at the caps (over $364); with OpenRouter $551 at the caps | gap_6 §5.2/§5.4 (fold-over 7.42 pod-h, $52); FI §6 computes the $404/$364 from RunPod billing only. The flip × speed-diet antagonism named in S2 is exactly a two-way interaction the 2^(4-1) design aliases |

### Missing cheaper alternatives and wrong ordering

| tag | where | was | now | why |
|---|---|---|---|---|
| C9 | §3, S1, S2 | every new bundle waits for rung 4 (pod, 4-5 Oct) before its first LB read; v10.1 replicates fill 1-5 Oct | v10.1.1 (T1-T3, T13, rank-1 cap) may take a slot after rung 1, from about 3 Oct; v10.1 gets 3 reads first | Rungs 2-5 cannot exercise these paths (public and Pallets repos have no ≥10 s imports, no namespace or `python/` roots, no new root modules), so waiting buys nothing; the 12 h bound for v10.1's m holds. T5/T6 (sparse base tree) excluded: it changes verify on every task |
| C10 | S4, S6, §6 | forum post tied to the quota reset; G-A run unconditionally; Pallets catalog after the golden build | post now; free pre-checks (743508 re-test, wheelhouse version, PLAN K1) before 2 GPU-h; catalog labels now | The post needs no GPU and the host's last answer took 5 days (distill.md §2.1). The catalog is a labelling job with no dependency on the golden build (pallets.md §8) |
| C5 | S3(a) | v4 vs v10.1 on 40 tasks | v10.1 alone on 80 tasks, same task-runs | The direction question is a level, not a paired delta; ±14 points at n = 40 against ±10 at n = 80 around 27%. pallets.md §7.3: paired deltas need 131-204 tasks |
| C18 | §0, §6 | "speed.md §6.1"; base 7.2 | §6.2, "of 60"; note that 7.2 = 0.12 × 60, not the measured 7/58 | speed.md §6.2 table; hidden.md §1.3. The 0.2-task difference sits inside the v10.1 lever and does not move the table |

### Checked and left unchanged
- Weekdays: Sat 3 Oct, Thu 8 Oct, Sun 8 Nov, Thu 12 Nov, Sat 28 Nov, Wed 2 Dec 2026 are correct (`date`).
- S3's $85 matches gap_6 §5.4 (10.5 pod-h for the factorial, anchor, confirmation and start-up) plus (a) and (c).
- The v4 anchor band 14-22/51 still holds at `G4_L4_SCALE` 1.7 (p1_v4: 18 of the 51 arena tasks).
- The 5.5 cap for v10.1 itself: speed.md §7 (bound 11.52 h even at V = 0).
- `odds.py` reproduces: `odds_critique.py` case A gives the same means and probabilities as `odds.out` (to within 0.001).
- Rules: no step submits repo-conditional behaviour, uses a non-Gemma model in the scored bundle, runs parallel calls,
  or exceeds the 12 h clock once C11 is applied.
