# Speed on the hidden set: where v10.1's seconds go, and what v10.2 should cut

Written 2026-09-30 01:50 IST (2026-09-29 20:20 UTC), **before sub6 (v10.1) was submitted** (armed for 05:31 IST,
00:01 UTC). Read-only analysis: no Kaggle submission, kernel push, pod, forum post or OpenRouter call was made, and no file
under `submissions/`, `eval/golden/`, `scripts/golden*` or `tests/` was touched. Every number cites a script output in
`research/speed/` (scripts copied from the session scratchpad `scratchpad/speed/`; all re-run in under a minute, section 11).
Labels: **MEASURED** (read from traces or logs), **ESTIMATE** (a model output; the model is stated), **UNVERIFIED**.

## 0. Answers in one screen

| Question | Answer | Evidence |
|---|---|---|
| Where does v10.1 spend a task? | **143.6 s mean on the L4 clock** (p50 127, p90 255; pod pair p1_v10, 73 tasks). LLM 87.6 %. Setup 2.7 s (1.9 %), locator 57.0 s (39.7 %, 16.3 calls), fixer 60.8 s (42.3 %, 15.3 calls), verifier 23.0 s (16.0 %, 9.3 calls). Decode is the budget: 3,384 output tokens/task = ~95 s; uncached prefill 27.6k tokens = ~22 s; tools ~18 s. race-2 v10 (r2_v10_1) is within 3 s on every stage | `analyze.out`, `crossrun.out`, sect. 2 (MEASURED) |
| When does a solved task's final patch exist? | **v10.x: p50 76 s, p90 141-158 s, max 259 s** (52 solves in p1_v10 + r2_v10_1). v4: p50 41-51 s, p90 107-115 s. v10.1 reaches its final patch **~18-35 s later than v4** (mean time before it: 88-89 s vs 54-70 s), almost all of it in the locator: in solves it spends 44-52 s there (v4: 32-38 s), of which a failing reproduction takes 17.7 s (2.2 calls) and `run.py` probing 12.8 s (3.0 calls) | `crossrun.out`, `prefp.out`, sect. 3 (MEASURED) |
| How much is waste? | **~43 s/task (30 %) in p1_v10**: stage-ending text 13.5, exact repeats with identical output 7.2, failed edits 7.0, same-stage re-reads 6.9, helper "same x3" notes 3.4, setup 2.7, ALREADY TRIED 2.0, SAME AS LAST RUN 1.7, tool calls written as text 1.4. v10 cut failed-call waste from 32-78 s/task (every v4/v9 run) to 9.5-11.5, and runaways (>=1,000 output tokens) from 13-20 calls to 4 per 74 tasks. Before the final patch of a solve, waste is ~27 of 88 s | `analyze.out`, `prefp.out`, sect. 4 (MEASURED) |
| How much slower is the hidden set? | **It depends on how long validation takes, which nobody has measured.** sub3 (v4) took 10.33-10.50 h and **sub4 (v9_eog) 9.99-10.07 h** submit-to-COMPLETE (the sub4 figure is new here, from the gap-5 poll log). Validation V is outside the 12 h. If V is the host's "~2 h IIRC" (1.3-2.1 h), a uniform stretch of **k = 1.4-2.9** fits both runs and 28-64 % of hidden tasks hit the 5-min cap. If V is as fast as our own Kaggle validation kernel (1,501 s for 129 tasks, ~0.4 h), **k = 2.1-4.9** and 53-86 % hit the cap. The brief's "1.9x, nearly all at the cap" mixes the two cases | `sim_calib.out`, sect. 5 (ESTIMATE) |
| How many failing hidden tasks are time-starved? | **v10.1 lands 94 / 90 / 85 / 80 / 72 % of its solvable hidden tasks at k = 1.5 / 1.9 / 2.5 / 3.0 / 4.0** (replay of its 52 solves with the hidden clock and its own LOCATOR footer; per-task k lognormal, sd 0.5). If sub6 scores like v4 (0.12 = 7.2 of 60), that is **0.5 / 0.8 / 1.3 / 1.8 / 2.8 time-starved public-LB tasks**. +30 s would recover 0.09-0.35 of them, +60 s 0.17-0.65 | `replay.out`, `compare.out`, sect. 6 (ESTIMATE) |
| Can speed take 0.12 to 0.20? | **No.** 0.20 needs +4.8 public-LB tasks. The best safe v10.2 speed package buys **+0.2 to +0.5 tasks at k = 1.9-3.0 and +0.8 at k = 4** (+0.004 to +0.014 LB), below the 0.033 run-to-run SD of one LB reading. Speed is worth doing because it is cheap and nearly free of quality risk at the top of the list, but the remaining 4+ tasks have to come from fix quality | sect. 6, 8 |
| Can `max_time_minutes` rise? | **5.5: yes, whatever validation takes** (distribution-free bound 11.52 h even if validation took 0 h; 11.08 h at V = 0.4 h). **6.0: only once V >= ~1 h is measured** (11.33 h at V = 1.0; 12.05 h at V = 0.4 fails). 6.5: no. Cheaper steps do **not** license a higher cap: the bound is set by the cap ratio on the tasks that run to it | `budget.out`, sect. 7 |
| What should v10.2 change for speed? | (1) cap 5.0 to 5.5 with the helper clock rescaled; (2) a hard LOCATOR stop at 60 helper-seconds; (3) a locator diet: one reproduction attempt, no `run.py` probing before the plan; (4) a plan of at most 80 words. Together: **+0.23 / +0.32 / +0.48 / +0.84 hidden public-LB tasks** at k = 1.9 / 2.5 / 3.0 / 4.0, 26 fewer public L4 seconds per task, and 33-36 fewer hidden seconds of locator work | sect. 8 |
| Prediction for sub6 (pre-registered here) | v10.1 lands **1.03-1.18x as many** stretched solves as v4 on the same pod round, so **sub6 ≈ 0.12-0.14 (central 0.13, 7.7 of 60)**: not distinguishable from v4's 0.12 on one reading. Submit-to-COMPLETE **T6 ≈ 9.9-10.8 h** | sect. 6.3, 7.3 (ESTIMATE) |

Two corrections to the brief:
- "Every capped run scored 0 (123/123)" still holds for harness-flagged timeouts (none in any run solved). But two solves finished
  within 3 s of the cap (Kaggle L4 v9_eog `fastapi_14419` at 299 s, `results.jsonl` secs 308.4; r2_v9_eog_1 `fastapi_9555`), and the
  harness grades the working-tree diff at a timeout (`data/HARNESS_README.md` sect. 8.1; `swegemma/harness/agent_runner.py:760-795`).
  So a hidden task that runs to the cap still scores if its patch already exists. That is the mechanism the whole simulation rests on.
- "Hidden tasks ~1.9x slower, nearly all at the cap" are two different claims. A uniform 1.9x stretch puts only 36-43 % of tasks at the cap
  (`sim_calib.out`, last block). "Nearly all" needs k >= 4, which fits only if validation takes well under an hour (sect. 5).

---

## 1. Data, clocks and the cost model

### 1.1 Runs used (all 74 Kaggle-valid ids unless noted)

| key | what | clock to L4 | source |
|---|---|---|---|
| p1_v10, p1_v4 | tonight's pod pair: v10.1 vs v4, one round, faithful compaction, L4 clock (`G4_L4_SCALE=1.7`) | pod wall x 1.7 (what the cap and the helper clock used) | `eval/pair1/eval/runs/` (73 traces each; fastapi_14986 had no snapshot) |
| r2_v10_1, r2_v9_eog_1 | race 2 round 1 (v10.0 helpers), same faithful settings | x 1.7 | `eval/race2/eval/runs/` |
| k_v4, k_v9_eog | Kaggle 4xL4, real scorer stack | real | `eval/kaggle/g4-l4-*/traces.tar.gz` |
| r_* (51 arena ids) | race 1, H100, 5-min real cap, no compaction | x 1.72 (time_model sect. 6) | `eval/race1/runs/` |
| p_v4, p_v6-p_v8 | eval3 fair pod runs, 6-min real cap | x 1.72 | `eval/eval3/eval/runs/` |

Per step: LLM seconds = LLM event time minus the previous observation time; tool seconds = observation time minus LLM time (`extract.py`).
LLM + tool time accounts for 100.0 % of each task's agent wall in every v10 run (`analyze.out`, "attributed share"), so nothing is hidden in gaps.

### 1.2 The per-call cost model, re-checked on the real scorer hardware (MEASURED)
Least squares over 7,066 Kaggle L4 calls (k_v4 + k_v9_eog): **latency = 0.063 s + 28.1 ms x output tokens + 0.81 ms x uncached prompt tokens,
R^2 = 0.98.** This matches `research/time_model.md` sect. 2 (0.085 s + 28.5 ms + 0.65-0.92 ms). The x1.08 version in `scripts/replay_l4.py`
over-predicts real L4 LLM time by 6-7 % (real/model 0.93-0.94). On the pod, real LLM time is 0.54-0.58 of that model, i.e. pod x 1.7 = L4
(re-fit on p1_v10 x 1.7: 29.7 ms per output token). The brief's "~1.4 s + ~35 ms per token" is an older rounding; the numbers above are used here.

### 1.3 Definitions
- **Final-patch time** of a solved task: the end of its last successful source edit (`edit.py` "OK", or a successful `edit_file`/`write_file`
  on a non-test, non-scratch `.py` file), or the time of the checkpoint `finalize.py` restored, whichever is earlier (4 tasks with a restore in p1_v10, 0 in r2_v10_1).
- **First verify**: the first plain `verify.py` (not `--repro-only`). **First edit**: the first successful source edit.
- **Waste** (first match wins per step): failed or malformed calls; failed edits; edit "ALREADY TRIED"; verify "SAME AS LAST RUN";
  helper "same x3" notes; an exact repeat of the same stage's call with identical output (footer and `t=` stripped); a same-stage re-read
  (a `view.py`/`read_file` range 80 %+ covered by an earlier view in the same stage); a tool call written as text; the setup stage;
  stage-ending text replies. Cross-stage re-reads are not counted: stages start with fresh contexts by design.

---

## 2. Where v10.1's seconds go (MEASURED, L4 seconds)

### 2.1 By stage (`analyze.out`)

| stage | p1_v10 calls/task | p1_v10 s/task (LLM + tool) | output tok/task (of which text) | r2_v10_1 s/task | k_v4 s/task (for scale) |
|---|---|---|---|---|---|
| setup | 2.0 | 2.7 (2.5 + 0.2) | 37 (6) | 2.7 | - |
| locator | 16.3 | 57.0 (51.9 + 5.1) | 1,478 (276) | 57.7 | 56.5 |
| fixer | 15.3 | 60.8 (50.9 + 9.9) | 1,361 (97) | 59.5 | 58.9 |
| verifier | 9.3 | 23.0 (20.5 + 2.5) | 508 (73) | 25.3 | 29.2 |
| submitter | 0.1 | 0.1 | 1 | 2.0 | - |
| **total** | **43.1** | **143.6** (p50 127, p90 255) | **3,384** | **147.1** | **144.6** |

Solved tasks average 116.9 s, unsolved 159.3 s. One of 73 p1_v10 tasks hit the cap (5 of 74 in r2_v10_1; v4: 9 of 73-74).

### 2.2 Decode, prefill, tools
Per p1_v10 task: 3,384 output tokens x 28.1 ms = **95 s**; 27,618 uncached prompt tokens x 0.81 ms = **22 s**; 43 calls x 0.063 s = 2.7 s;
tools 17.7 s on the L4 clock. Tool output that becomes prompt: `view.py` ~4.2k tokens/task, `read_file` 2.4k, `run.py` 1.1k, `edit.py` 1.0k.
The expensive calls are the ones that write: a `verify.py --repro-only` call writes a median 225 tokens (6.3 s on L4), an `edit.py` call 136,
a `run.py` probe 76; a view or grep writes 34-39 (1.1 s). Tool time itself is small: `verify.py` 0.7 s pod median, p90 3.0 s, max 37 s.

### 2.3 Footers
The locator saw the LOCATOR time footer 14 times in p1_v10 and replied on the next step 7 times (8 of 19 in r2_v10_1): **15 of 33, 45 % per
occurrence** (the replay uses 0.46). The CONTEXT footer fired 223 times in locator steps and was obeyed 49 times (22 %). On public tasks the LOCATOR footer (75 s)
rarely fires because the locator usually ends first. On stretched hidden tasks it fires in most tasks (sect. 6), so it is v10.1's main time
controller there. Compaction: 21 events in p1_v10 and 36 in r2_v10_1 (0.3-0.5 per task, about 5.6 s each on L4, time_model sect. 3).

---

## 3. Solved tasks: when the final patch exists (MEASURED)

### 3.1 Across runs (`crossrun.out`; L4 seconds; race-1 and eval3 caps were looser, so their tails pass 300)

| run | solved | first edit p50 | final patch p50 / p90 / max | after the final patch, p50 | waste s/task: failed / repeat / re-read / text |
|---|---|---|---|---|---|
| **p1_v10** | 27 | 74.1 | **76.2 / 141.0 / 259.1** | 17.4 | 9.5 / 12.2 / 6.9 / 14.8 |
| **r2_v10_1** | 25 | 64.2 | **76.0 / 157.8 / 259.4** | 14.2 | 11.5 / 16.6 / 8.3 / 14.6 |
| p1_v4 | 24 | 38.9 | 41.4 / 107.2 / 145.4 | 28.6 | 36.7 / 14.6 / 4.4 / 20.6 |
| k_v4 (Kaggle L4) | 29 | 47.0 | 50.8 / 114.5 / 275.7 | 23.2 | 32.0 / 7.8 / 3.6 / 24.6 |
| k_v9_eog (Kaggle L4) | 29 | 58.4 | 77.8 / 158.5 / 178.9 | 27.1 | 36.0 / 11.3 / 4.2 / 25.6 |
| r2_v9_eog_1 | 24 | 33.8 | 36.7 / 141.0 / 250.8 | 32.8 | 38.1 / 12.7 / 4.7 / 26.7 |
| r_v4 / r_v9_eog (race 1) | 18 / 21 | 54.8 / 75.4 | 56.4 / 93.7 p50 | 25.7 / 42.8 | 47.5 / 42.7 failed |
| p_v4 (eval3, 6-min cap) | 26 | 37.2 | 45.0 / 102.8 / 527.1 | 25.3 | 62.5 failed |

p_v4's 527 s solve is the one the 6-minute cap added in eval3 (own_data sect. 0.7).

### 3.2 What happens before the final patch (`prefp.out`)
Mean time before the final patch in solved tasks: **p1_v10 87.7 s = setup 2.8 + locator 52.4 + fixer 32.5**; r2_v10_1 89.4 s
(setup 2.7, locator 43.7, fixer 32.6, verifier 8.4, submitter 1.8). v4: p1_v4 54.4 s (locator 31.9 + fixer 22.5), k_v4 69.6 s.
Inside the p1_v10 locator of a solve: `verify.py --repro-only` 2.19 calls / **17.7 s** / 543 tokens, `run.py` probes 3.04 / **12.8 s**, the plan
reply 1.0 / **8.9 s** (272 tokens), views 4.37 / 7.2 s, `locate.py` 0.93 / 2.8 s, `grep.py` 1.44 / 2.3 s.
After the final patch, solves spend p50 17.4 s (mean 29.2 s) on verify, finalize, submit and the last reply. At the cap the harness grades the tree,
so that tail never decides whether a solve lands; it only costs 12 h budget.

### 3.3 The locator, in detail (`detail.out`)
- Locator calls: p50 14, p90 27 (p1_v10); solves p50 12, failures p50 17. Time: solves 52.4 s mean, failures 59.7 s; in r2_v10_1 43.7 vs 64.8 s.
- **Localization is fast; the reproduction is slow.** In the 52 v10.x solves, the locator had viewed a file of the final patch within 15 s of
  locator time in 42 and within 30 s in 46; 5 never viewed it (the fixer found it). A valid failing reproduction existed within 30 s in 25 and within
  60 s in 31 (`early.out`).
- Reproduction attempts in solves: valid on the first try 25, valid only on a retry **9**, never valid 5, none written 13 (`early.out`).
- `run.py` probes: 35 of 52 solves made none, 11 made 4 or more; among the 95 failures, 32 made 4 or more (`early.out`).
- Stage-ending replies (tokens): locator p50 188, p90 761, max 768 (the cap); fixer p50 39; verifier p50 54. **11 (p1) and 14 (r2) locator
  endings ran to 600+ tokens**, 3.7-3.9 s/task. In p1_v10, 7 of the 11 are over-long plans and 2 are tool calls written as text; in
  r2_v10_1 (before the v10.1 prompt fix), 6 of 14 are tool calls written as text and none starts with the `FILES:` line.
- Time-cap arithmetic on the recorded runs (public clock): stopping the locator after 60 s of locator time removes 12.6-15.0 s/task, touching
  30-32 tasks (4-11 of them solves); after 10 calls removes 27-30 s/task but touches 55-57 tasks including 13-19 solves.

---

## 4. Waste inventory (MEASURED, `analyze.out`)

| category | p1_v10 calls/task | p1_v10 L4 s/task | r2_v10_1 s/task | k_v4 s/task | lever |
|---|---|---|---|---|---|
| stage-ending text replies | 3.00 | 13.5 | 11.9 | 24.6 | plan length (sect. 8 R4); the verifier's post-submit sentence (12 h only) |
| exact repeat, identical output | 2.14 | 7.2 | 12.4 | 7.8 | model behaviour; v11 LoRA target |
| failed edits | 0.99 | 7.0 | 13.9 | 13.9 | already cut by edit.py; residual is quality |
| same-stage re-reads | 3.89 | 6.9 | 8.3 | 3.6 | model behaviour; a helper dedupe trims only prefill |
| helper "same x3" NOTE | 1.10 | 3.4 | 2.8 | - | already answered by the helper |
| setup stage | 2.00 | 2.7 | 2.7 | - | keep (sect. 8, rejected) |
| edit ALREADY TRIED | 0.56 | 2.0 | 0.8 | - | already answered by edit.py |
| verify SAME AS LAST RUN | 1.22 | 1.7 | 1.4 | - | cheap: the helper returns at once |
| tool call written as text | 0.08 | 1.4 | 2.8 | - | v10.1 prompt fix worked (r2 0.49/task, p1 0.08) |
| malformed / can't open / after budget | 0.15 | 0.5 | 0.3 | 18.0 | fixed in v10 |
| runaway calls >= 1,000 tokens | 4 per 73 tasks | 2.1 | 2.0 | 14.5 | fixed in v10 |

---

## 5. How slow is the hidden set?

### 5.1 Facts
- sub3 (v4, 5 min / 70 calls / 150 turns): submitted 05:31:12 IST (00:01:12 UTC) 27 Sep, COMPLETE between 15:50:50 and 16:01:05 IST:
  **T3 = 10.33-10.50 h** (`research/gap_5.md` sect. 1.1).
- sub4 (v9_eog): submitted 05:31:06 IST (00:01:06 UTC) 28 Sep; PENDING at 15:30:24 IST, COMPLETE at 15:35:25 IST:
  **T4 = 9.99-10.07 h** (`scratchpad/gap5c/sub4_poll.log`, last two lines). Not used in any earlier report.
- sub5 (v4 again): 0.12; its completion time was not logged.
- T = queue + start-up + all tasks + validation. The 12 h covers start-up + tasks ("inclusive of sandbox setup time, but excluding time for
  patch validation", gap_5 sect. 2). Validation V has never been observed. Two anchors disagree by 5x:
  the host's "~2 h IIRC" for an all-patched run (forum 743663), and our own Kaggle CPU validation kernel, which set up and verified 129 public
  tasks in **1,501 s** (`eval/kaggle/oracle_all/g4-oracle-all.log`, TOTAL line), about 0.4 h per 120. Hidden test suites may be heavier.

### 5.2 Calibration (`sim_calib.out`; start-up 600 s, 5 s per-task overhead, capped public tasks stay capped)
Uniform stretch k such that `600 + N x mean(5 + min(k x public agent time, 305))` equals T - V, using each bundle's own Kaggle L4 run:

| V (h) | sub3 k, N=120 / 130 | sub4 k, N=120 / 130 | share of hidden tasks at the 5-min cap |
|---|---|---|---|
| 0.25 | 4.93 / 3.20 | 3.42 / 2.30 | 64-86 % |
| 0.4 (our kernel's speed) | 4.47 / 3.00 | 3.10 / 2.19 | 57-80 % |
| 1.0 | 3.23 / 2.43 | 2.29 / 1.84 | 43-69 % |
| 1.3-1.7 (host's figure x non-empty rate) | 2.44-2.83 / 2.01-2.23 | 1.83-2.07 / 1.55-1.70 | 32-64 % |
| 2.0 | 2.22 / 1.87 | 1.69 / 1.45 | 28-49 % |

Reading: k spans **1.5-5**; this report uses **k = 1.9, 2.5, 3.0, 4.0** as the scenarios, with 2.5 as a central value. A per-task lognormal k
(sd 0.5 and 1.0, same mean) is the main sensitivity, because hidden tasks are unlikely to stretch uniformly. The mixture model (some tasks
public-like, the rest hopeless and capped) fits too (p = 0.06-0.71 public-like); under it speed buys nothing, and it is the null case.

---

## 6. Time-starved hidden tasks (simulation)

### 6.1 Method (`replay.py`)
Each of the 52 v10.x solves is replayed call by call with every step's L4 duration multiplied by k. v10.1's own LOCATOR footer is applied:
once a locator helper call ends past 75 helper-seconds, the next step is the plan with probability 0.46 (measured, sect. 2.3); if so, the
remaining locator tool calls are skipped and the recorded plan is kept. A solve **lands** if its final patch exists by the cap. v4 has no clock,
so its solves are stretched plainly (`land.py`). **Assumption (optimistic for every cut):** removing or truncating steps does not change what
later stages do. The quality side of each cut is what sect. 9 measures.

### 6.2 Landing and starvation for v10.1 as shipped (`replay.out`, `compare.out`)

| k | landed share (lognormal sd 0.5) | landed (uniform) | naive stretch without the footer | time-starved public-LB tasks if sub6 = 7.2/60 | recovered by +30 s / +60 s / +120 s |
|---|---|---|---|---|---|
| 1.5 | 0.937 | 0.942 | 0.921 | 0.48 | 0.09 / 0.17 / 0.28 |
| 1.9 | 0.898 | 0.899 | 0.867 | 0.82 | 0.15 / 0.27 / 0.43 |
| 2.5 | 0.849 | 0.841 | 0.772 | 1.28 | 0.20 / 0.35 / 0.56 |
| 3.0 | 0.803 | 0.801 | 0.692 | 1.77 | 0.27 / 0.48 / 0.77 |
| 4.0 | 0.720 | 0.737 | 0.547 | 2.80 | 0.35 / 0.65 / 1.08 |

Scale these by 2 for the full ~120-task hidden set. The footer column shows that v10.1's time footers are already worth +0.25 to +1.7
public-LB tasks over the same trajectories with no clock (k = 1.9 to 4.0). The ceiling of all speed work is the "time-starved" column; nothing in sect. 8 can exceed it.

### 6.3 v4, v9_eog and v10.1 under the same stretch (`compare.out`, landed solves in public-equivalent counts)

| run (solves) | k = 1.9 uniform / lognormal | k = 2.5 | k = 3.0 | k = 4.0 |
|---|---|---|---|---|
| p1_v4 (24) | 24.0 / 22.9 | 22.0 / 21.9 | 21.0 / 20.9 | 18.0 / 18.9 |
| p1_v10 (27) | 24.7 / 24.7 | 22.7 / 23.4 | 21.9 / 22.4 | 21.3 / 20.2 |
| k_v4 (29) | 27.0 / 26.5 | 27.0 / 25.0 | 23.0 / 23.8 | 22.0 / 21.2 |
| k_v9_eog (29) | 26.0 / 25.2 | 20.0 / 22.5 | 20.0 / 20.3 | 14.0 / 16.6 |

- **The pod pair's +3 shrinks to +0.7 to +3.3 under the stretch**: v10.1 lands 1.03-1.18x v4's count. Prediction for sub6 (written before it
  was submitted): **0.12 x (1.03 to 1.18) = 0.124-0.142, central 0.13**, with one-reading SD about 0.033 (gap_6), so P(sub6 >= 0.15) is about 0.3
  (ESTIMATE, normal approximation).
- **sub4 check.** On the same Kaggle L4 hardware v4 and v9_eog both solved 29 of 74, but v9_eog's solves land later (p50 78 s vs 51 s).
  The stretch predicts v9_eog at 0.74-0.90x v4 at k = 2.5 and 0.64-0.78x at k = 4, i.e. 0.08-0.11 against the observed 0.06. The direction agrees,
  and the higher-k end fits better, but it is a single reading one to two SD away. Weak support for "time matters on hidden", not proof.

---

## 7. The 12 h budget

### 7.1 Distribution-free bound (gap_5 sect. 4 method; `budget.out`)
`T(c1) <= S + N x ovh + max(m, c1/300) x (A - S - N x ovh)`, with A = T - V the observed in-clock time, S = 600 s, and m the v10.x per-task
slowdown against the calibrating bundle on public tasks (m = 1.01 vs v4, 0.88 vs v9_eog: 145.4 vs 144.6 / 165.3 s). Queue time is taken as 0
(conservative). Hours inside the 12 h clock:

| source, V | cap 5.0 | **5.5** | 6.0 | 6.5 |
|---|---|---|---|---|
| sub3, V = 0 (impossible floor) | 10.55 | **11.52** | 12.53 | 13.55 |
| sub3, V = 0.4 h (our validation kernel) | 10.15 | **11.08** | 12.05 | 13.03 |
| sub3, V = 1.0 h | 9.55 | **10.42** | 11.33 | 12.25 |
| sub3, V = 1.7 h (host's figure) | 8.85 | **9.65** | 10.49 | 11.34 |
| sub4, V = 0 | 10.07 | **11.04** | 12.02 | 12.99 |
| sub4, V = 0.4 h | 9.67 | **10.60** | 11.54 | 12.47 |
| sub4, V = 1.7 h | 8.37 | **9.17** | 9.98 | 10.78 |

(N = 120, ovh 5 s; N = 130 with 12 s overhead moves each cell by 0.03-0.08 h.) The model projection (calibrated k, v10.x public times, all-patched validation 1.5-2.5 h) is lower everywhere: worst
10.19 h at 5.5 and 10.72 h at 6.0 (`budget.out`, "worst projected").

### 7.2 Answers
- **5.5 min is safe in every case**, including the impossible V = 0 floor (0.48 h left). At the 0.4 h our own kernel measured, 0.92 h is left.
- **6.0 min needs V >= ~1.0 h** for the usual 0.7 h margin. That is the host's word against our own measurement, so 6.0 waits for a measurement.
- **6.5: no** (needs V >= 1.7 h and still leaves only 0.66 h).
- **Do cheaper steps make room for more?** In the model, the sect. 8 package saves 9-17 s of wall per hidden task (about 0.3-0.6 h over 120), but
  the bound, which is the guard against a zero score, does not move: capped tasks cost the full cap whatever each step costs, and the calibration
  says 28-86 % of tasks are capped. Cheaper steps buy solves, not cap headroom.

### 7.3 A free measurement that settles it: time sub6 (Carson or any session, read-only)
Start `bash research/speed/poll_submission.sh "sub6:"` after 05:31 IST (00:01 UTC). It logs the Kaggle status every 5 minutes until
COMPLETE/ERROR (16 h stop), written for this report and **not started** (other workflows are already running local waiters).
Pre-registered use of T6 (submit-to-COMPLETE):
- **T6 <= 10.70 h: ship v10.2 with 5.5** (bound <= 11.3 h, taking V >= 0.4 h as our kernel measured; with V = 0 the line is 10.30 h).
- 10.70 < T6 <= 11.0 h: 5.5 still has >= 0.4 h; Carson's call. T6 > 11.0 h or ERROR: stay at 5.0 and find the missing time.
- 6.0 only if T6 <= 9.47 h (safe even at V = 0), or if the Stage-1 to Stage-2 transition is seen in the Submissions page (gap_5 sect. 10.2),
  which measures V directly, and shows V >= 1.0 h.
- Expected: T6 about 9.9-10.8 h (v10.1's in-clock time is close to v4's, and its validation is longer because it leaves 2 empty patches
  where v4 left 12).

---

## 8. Ranked v10.2 speed changes

Gains are ESTIMATES from `replay.py` (lognormal sd 0.5 central; uniform in `replay.out`), in **hidden public-LB tasks out of ~60**, assuming
sub6 lands near 7.2 of 60 (scale by sub6/0.12 once it is known; double for the full hidden set). "Public s" is L4 seconds removed per task on
the recorded public runs (all tasks, `allsave.out`). "Hidden s" is locator/tool work removed per hidden task at k = 1.9 / 2.5 (same file).

| rank | change (v10.2) | public s | hidden s (k 1.9 / 2.5) | gain at k = 1.9 / 2.5 / 3.0 / 4.0 | quality risk | cheapest check |
|---|---|---|---|---|---|---|
| **1** | **`max_time_minutes` 5 to 5.5, helper clock rescaled.** `eval_config.yaml`; in `_swe_common.clock_scale()` multiply the pod file scale by a new `BUDGET_SCALE = 300 / 330`, so every threshold (LOCATOR, EDIT NOW, FINISH 210, TIME 250, finalize/submit 285, cap 300) keeps its meaning in helper time and the prompts stay unchanged. Pod runs compose (1.7 x 0.909). Pin `BUDGET_SCALE x 60 x max_time_minutes = 300` in a test so the two never drift, and restate R81/R85 (`test_fits_12h`) as the sect. 7.1 bound | +30 s budget on every capped task | +30 s | **+0.15 / +0.18 / +0.26 / +0.30** | none on quality; 12 h bounded in sect. 7 | unit tests of the thresholds at 330 s and `real_budget`; the T6 rule (sect. 7.3) |
| **2** | **Hard LOCATOR stop at 60 helper-seconds.** `T_LOCATOR` 75 to 60 (SPEC sect. 9.2 already pre-registered this as knob 2), and after `T_LOCATOR + 10` while the context meter's phase is still `locator`, `locate.py`, `grep.py`, `run.py` and `verify.py --repro-only` print only the LOCATOR line. `view.py`, `edit.py` and `status.py` are never refused. The context meter flips the phase to `fixer` only at the first `edit.py`, so the fixer prompt's step 1 becomes `python3 /tmp/swe/status.py --fixer` (sets the phase; about 1.5 s) and the refusal text tells any stage that is not the locator to view and edit instead | 3.8 | 13.8 / 18.0 | **+0.09 / +0.14 / +0.26 / +0.50** | plans cut short: on hidden tasks it fires in most locators. In the 52 solves the patched file was viewed by 30 public-s in 46, but a valid reproduction existed by then in only 25 | golden L suite at the hidden clock (sect. 9.2) |
| **3** | **Locator diet (prompt only):** one reproduction attempt ("if a claim passes on original, reply REPRO: none" instead of "rewrite it once"), and no `run.py` probes before the plan unless the reproduction cannot import the code | 22.8 | 26.5 / 24.8 | **+0.10 / +0.10 / +0.16 / +0.25** | 9 of 52 solves got their valid reproduction only on a retry; 11 of 52 solves made 4+ probes | golden L suite (repro validity, gold files named) |
| **4** | **Plan of at most 80 words; drop the REPRO and TESTS lines** (`status.py` already carries both) | 2.8 | 5.5 / 7.5 | **+0.04 / +0.06 / +0.10 / +0.21** | less detail for the fixer; 7 plans of 600+ tokens in p1_v10 show the current 120-word limit is ignored in about 1 plan in 10, so the wording must be firmer, not just shorter | golden L (plan metrics) + F with an 80-word golden plan |
| | **Package 1-4** | 25.9 | 33.3 / 35.5 | **+0.23 / +0.32 / +0.48 / +0.84** | as above | sect. 9 |
| (5) | Cap 6.0 instead of 5.5 in the package, **only after** V >= 1 h is measured | - | +60 s | +0.31 / +0.41 / +0.56 / n.a. (k = 4 implies V is small, where 6.0 is unsafe) | 12 h | sect. 7.3 |

Net wall of the package: it saves 13.4 s (k = 1.9) and 9.3 s (k = 2.5) per hidden task even with the longer cap, because the cheaper locator
outweighs the extra 30 s on capped tasks (`allsave.out`), so it also lowers the 12 h projection.

### 8.1 Evaluated and not recommended

| idea | measured | why not |
|---|---|---|
| Drop or merge the setup stage | 2.7 s/task, 2 calls | +/-0.06 tasks (noise). When install was optional, helpers were missing in ~40 % of race-1 tasks (time_model sect. 7.1); the forced stage made availability 1.00 (race 2 KPI). Keep it |
| Cap the locator at N calls | 10 calls removes 27-30 s/task | touches 55-57 tasks including 13-19 of 52 solves; a time stop (rank 2) targets the stretched hidden locators and spares fast solves |
| Smaller `max_output_tokens` | fixer tool calls max 1,294 tokens (0 above 1,536); 4 runaways per 73 tasks cost 2.1 s/task | fixer 2048 to 1536 saves ~0.2 s/task; locator 768 to 512 would truncate 7-13 reproduction calls per 74 tasks (a truncated call is a malformed call); verifier 2048 to 1024 cuts 1-2 edits. Not worth a test cycle |
| Fewer verify rounds | SAME AS LAST RUN 1.2 calls = 1.7 s/task; edits after the first verify in 6 of 27 and 8 of 25 solves | the rounds come before those solves' final patches, so cutting them changes the patch, not the clock. It is a quality question, already pre-registered in `docs/eval/ABLATION_REPAIR.md` (A0 vs B2) |
| Earlier EDIT NOW (150 to 120 s) | fires before 4 % of solves' first edits at k = 1, but 40 to 60 % at k = 1.9 and 63 to 75 % at k = 2.5 | it pushes "smallest plausible change now" into the window where stretched solves edit anyway; the fixer's first edit already comes 9-12 s after it starts. No landing gain, some quality risk |
| Cheaper helper outputs | prefill 22 s/task (27.6k uncached tokens); view 4.2k + read_file 2.4k tool tokens/task; 0.3-0.5 compactions/task | halving view output saves ~2 s/task plus a share of compactions (5.6 s each): +0.02-0.05 tasks (ESTIMATE). Only worth it bundled with a context fix |
| Removing repeats, re-reads, NOTE, SAME calls | 12.7 s/task if all went | upper bound +0.08 to +0.20 tasks, but no declarative lever removes the model's call; a helper dedupe trims prefill only. It is the v11 LoRA's stated target (`docs/v11/PLAN.md` sect. 1) |
| `timeout_seconds` 180 to 120 | 1 raw hang in 147 v10 task-runs (r2_v10_1, 107 s pod = ~182 L4 s) | keep 180: commit 31ddc6a raised it because it may also cap the Stage-2 hidden-test pytest, where a false negative on a correct patch is the costliest error |

---

## 9. How to verify each change cheaply

### 9.1 Free (Mac)
1. Unit tests for rank 1: with `BUDGET_SCALE = 300/330`, the helper clock reads 300 at 330 real seconds; FINISH / TIME / finalize fire at
   231 / 275 / 313.5 real seconds; `real_budget` never exceeds the real time left; the pod scale composes (1.7 x 0.909). Restate `test_fits_12h`
   as the sect. 7.1 bound with its V assumption written into the test.
2. Re-run these scripts on every new trace set (add it to `RUNS` in `extract.py`): the headline metrics are **solve final-patch p50/p75/p90,
   locator seconds in solves, and the landed share at k = 2.5** from `replay.py`. They are continuous and far less noisy than resolved counts.
3. `scripts/replay_l4.py --run` cliff check with `CAP = 330`.

### 9.2 Golden evals on the proxy (after the running golden build lands; OpenRouter spend needs Carson's go)
- **L suite, DEV split, `--samples 3`, arms v10.1 vs v10.2-locator (ranks 2-4)**, run with the runner's clock scale (`--l4-scale`, GOLDEN_EVALS_SPEC
  sect. 5.4) set to (proxy-to-L4 per-call latency ratio measured by the smoke) x 2.5, so the 60-second stop fires where it would on a hidden task.
- Pre-registered pass: `l_all_gold_files_named` not worse (paired sign test, no more than 1 net loss over ~30 cases x 3 samples); valid
  reproduction rate not down by more than 3 cases; locator output tokens down >= 20 %; L4-modelled locator seconds
  (sum of 0.063 + 0.0281 x output + 0.00081 x uncached tokens) down >= 15 s at the hidden clock.
- **F suite** once, with golden plans rewritten to the 80-word format (rank 4), to check the fixer does not lose `f_hidden_pass`.
- Cost about $0.30 per L dev run (spec sect. 9), so about $2 for both arms at 3 samples.

### 9.3 One pod pair round, only if 9.2 passes (Carson's go; about $20-25 at $6.98/h)
- Arms v10.1 and v10.2 (ranks 1-4) on the 74 ids, `pod/chain_pair.sh`, **two clock settings**: the usual `G4_L4_SCALE=1.7` (harm guard) and a
  **hidden-emulation round at `G4_L4_SCALE=3.2`** (1.7 x 1.9; the helpers accept 0.2-5, so the cap becomes 330/3.2 = 103 s real for v10.2 and
  94 s for v10.1). The second round tests the uniform-stretch hypothesis directly on public tasks.
- Pre-registered: at 1.7, v10.2 resolved >= v10.1 - 2 and 0 crashes; at 3.2, v10.2 resolved >= v10.1, and v10.2's solve final-patch p75
  (helper clock) at least 15 s earlier. A single round cannot resolve a +1 task effect (race noise is about +-3), which is why the continuous
  time metric is primary and the resolved count only a guard.

---

## 10. Caveats and UNVERIFIED items
- **The stretch model is the load-bearing assumption.** Uniform or lognormal k applied to public solves assumes the hidden solvable tasks look
  like public solves played slower. Under the mixture model (some tasks public-like, the rest hopeless) speed buys ~0. The sub4 check (sect. 6.3)
  leans toward the stretch model but is one reading.
- **Quality under truncation is not modelled.** Every gain in sect. 8 assumes the later stages behave as recorded. Ranks 2-4 must pass 9.2.
- Validation time V is unmeasured (sect. 5.1); it decides k, the capped share and whether 6.0 is safe.
- H = 7.2 is v4's score; sub6's own score rescales every gain linearly.
- 52 solves is a small population: the uniform columns move in steps of 1/52 (0.02). Pod timings are scaled by 1.7; the scale was re-checked
  in sect. 1.2 but tool time on the Kaggle CPU for private repos is UNVERIFIED (hidden test suites may make `verify.py` slower, which would make
  rank 1 worth more and ranks 2-4 less).
- r2_v10_1 ran v10.0 helpers (its install banner says v10.0); p1_v10 is v10.1. They are pooled as v10.x where noted.
- Replay obedience to the LOCATOR footer is modelled as 0.46 per occurrence from 33 occurrences.

## 11. Reproduce
```bash
cd /Users/carson/Projects/gemma-swe-agent/research/speed
PYTHONHASHSEED=0 python3 extract.py          # unpacks the two Kaggle L4 tarballs on first run; writes steps.jsonl, tasks.jsonl (gitignored)
python3 analyze.py > analyze.out             # sect. 2, 4 (per run: stages, first edit/verify, final patch, waste, runaways)
python3 detail.py > detail.out               # sect. 3.3 (locator, repair)
python3 prefp.py > prefp.out                 # sect. 3.2 (time before the final patch)
python3 crossrun.py > crossrun.out           # sect. 3.1
python3 sim.py > sim_calib.out               # sect. 5.2
python3 replay.py 1.5 1.9 2.5 3.0 4.0 > replay.out   # sect. 6, 8 (about 10 s)
python3 compare.py > compare.out             # sect. 6.2-6.3
python3 allsave.py > allsave.out             # sect. 8 seconds
python3 budget.py > budget.out               # sect. 7
python3 early.py > early.out                 # sect. 3.3 (file viewed by X s, reproduction attempts, probes)
```
`poll_submission.sh` (sect. 7.3) is the only script that talks to Kaggle; it only reads the submissions list.
