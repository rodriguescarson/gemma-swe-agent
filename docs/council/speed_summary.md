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

