# Gap 5: what sub3's "10.4 h" measures, and how to set `max_time_minutes` and `timeout_seconds`

Written 2026-09-28 04:10 IST (2026-09-27 22:40 UTC). Read-only: nothing was submitted, pushed, started or spent, and no repo file
was changed except this one. Every number below cites a file, a log line, a transcript timestamp or a script output.
Anything not measured is marked UNVERIFIED. Timestamps from logs are UTC, and IST (UTC+5:30) is added where it helps.

Scripts (scratchpad, each runs in under 75 s):
`/private/tmp/claude-501/-Users-carson-Projects/654244a3-b38c-45a0-96af-d7e5f0aac6ce/scratchpad/gap5o/`
`budget5.py` (12 h table, output `budget5.out`), `timeouts.py` (step 4, output `timeouts.out`),
`solvegain.py` (value of the extra minute, output `solvegain.out`), and `run.py`/`_ws.py` (copies used only for the orphan test in sect. 6.4).

## 0. Answers in one screen

| Question | Answer | Evidence |
|---|---|---|
| Where does "10.4 h" come from? | **Submit-to-COMPLETE of sub3, from a 10-minute poller.** It includes queueing, start-up, the agent phase **and validation**. It is not a displayed runtime and not the agent phase | `eval/submit_log.txt:3-4`, `scripts/push_after_scoring.sh:7-12`; the figure first appears in the session at 2026-09-27T10:47:47Z, 25 s after that log was read (sect. 1) |
| sub3 bracket | 00:01:12 UTC submit, COMPLETE first seen 10:31:05 UTC: **10.33-10.50 h** (10.50 is a hard upper bound) | same |
| sub1 (uncapped v0) | **Not "at most 10.6 h".** It was still PENDING at 04:26:16 UTC, 10.51 h after submission. The ledger's "04:30 scored" was written at 06:42 UTC as an estimate. **sub1 took 10.51-12.74 h** | session transcript 2026-09-26T04:26:16Z and 06:40:13Z; `eval/ledger.md:17` |
| Validation share of sub3 | ≈ **1.65 h** (host's ~2 h × v4's 82 % non-empty patch rate), range 1.24-2.06 h | forum 743663 [3528731]; p_v4 61/74, r_v4 42/51 non-empty |
| In-clock time of sub3 (start-up + all tasks) | **A ≈ 8.75 h, range 8.3-9.3 h**, i.e. about **258 s per task** at N=120 | sect. 2 |
| Did every hidden task hit the 5-min cap? | **No.** All-capped needs ≥ 10.49 h in-clock (N=120), which leaves ≤ 0.01 h for validation. But **~55-75 % of hidden tasks still hit the cap** under both shape models | sect. 3; `budget5.out` A |
| Safe `max_time_minutes` for v10 | **5.5 is safe in every scenario** (worst row 10.5 h projected, 11.2 h distribution-free bound). **6.0 is safe only if A ≤ ~9.0 h**, i.e. if validation + queue took ≥ 1.5 h of sub3's 10.5 h. The central estimate says yes, but it rests on one "IIRC" host sentence | sect. 4 |
| What the extra minute buys | If hidden tasks are uniformly slower (calibrated k = 2.9-4.6), 6.0 min captures **+0 to +45 %** more solves (≈ +0 to +3 of 60 public tasks, central about +1). If instead some tasks are hopeless and the rest behave like public ones, it buys ~0 | `solvegain.out` |
| `timeout_seconds` | **120.** Raw 180 s hangs cost 4.5 s per task across 500 task-runs (14 hangs); 90 would save 2.0 s per task, 120 saves 1.3 s. That is ≤ 0.07 h per 120-task run, and the only legitimate commands a lower value kills are `gate.py` runs at 65 s (killed by 60). The hang lever is `run.py`, not this key | `timeouts.out` |
| New defect | **`run.py`'s timeout leaves the real command running** for compound or piped commands (`cd x && pytest ...`, `... \| tail`). Verified locally. Fix: new session + `killpg` | sect. 6.4 |

## 1. Step 1: provenance of the 10.4 h figure

### 1.1 sub3 (v4 bundle, 5 min / 70 calls / 150 turns / 180 s)
| event | UTC | IST | source |
|---|---|---|---|
| submitted | 2026-09-27 00:01:12.837 | 05:31:13 | Kaggle API `competition_submissions` (read today) |
| PENDING seen | 01:37:47, 02:04:24, 07:32:36 | 07:07, 07:34, 13:02 | session transcript tool results at those times |
| poller started | 01:38:02 | 07:08:02 | `eval/submit_log.txt:3` |
| poller saw no PENDING | 10:31:05 | 16:01:05 | `eval/submit_log.txt:4` ("SubmissionStatus.COMPLETE,0.12") |
| "about 10.4 hours" first written | 10:47:47 | 16:17:47 | orchestrator reasoning, 25 s after it read `submit_log.txt` |
| LB snapshot shows 0.12 | 11:23:01 | 16:53:01 | `scratchpad/lb2/...2026-09-27T11:23:01.csv` line 49 (rank 48) |

The poller (`scripts/push_after_scoring.sh:7-12`) runs `kaggle competitions submissions` every 600 s plus CLI time and logs only its
start and its exit. So sub3 completed between the previous poll (≈10:20:50 UTC) and 10:31:05 UTC: **10.33-10.50 h after submission**.
The lower end assumes that previous poll succeeded (a failed CLI call is retried silently, `:9`); the upper end is hard.
10:31:05 minus 00:01:12 is 10.50 h, which the orchestrator rounded to "about 10.4 hours". **So 10.4 h is submit-to-score.**
It contains queue wait (Q), notebook start-up (S), the agent phase (all tasks), validation (V) and any publish lag (P).

The Kaggle API cannot split these. `kagglesdk` `ApiSubmission` has only ref, total_bytes, date, description, error_description,
file_name, public/private score, status, submitted_by, team_name and url (introspected today), with no completion time or runtime.
The Chrome extension was not connected (`list_connected_browsers` returned `[]`), so the runtime the UI shows could not be read.

### 1.2 sub1 (v0, no eval_config): a correction
The follow-up brief says sub1 went from submit (17:55 UTC) to scored "by 04:30 (ledger.md:17): at most 10.6 h". The transcript says otherwise:
- 2026-09-26T04:26:16Z, CLI output: `56557072 ... SubmissionStatus.PENDING` (and `date -u` = 04:26:16). That is **10.51 h after submission**.
- 2026-09-26T06:40:13Z: first COMPLETE / 0.10 seen. That is **12.74 h after submission**.
- The ledger row "2026-09-26 04:30 | Kaggle sub1 v0 scored" was appended at 06:42:14Z (transcript) and backdated.

So **sub1 took 10.51-12.74 h**, at least as long as capped sub3, not "about the same". It is a different bundle (sample agent, 8192 output
tokens, no cap), so it does not tell us much more. It does not support the claim that an uncapped bundle scores in the same time.

### 1.3 What Carson can confirm (one look, no cost)
The "My Submissions" page shows a runtime per submission (forum 743663 premise: "the runtime shown for a Kaggle submission is the
total wall-clock time"). If sub3's displayed runtime is ≈10.3-10.5 h, queue wait was ~0 and the accounting below holds. If it is much
shorter (e.g. 8 h), sub3 queued and **the agent phase was even smaller**, which makes a longer cap safer. Either reading leaves the
conclusions below standing. What Carson cannot see there is the Stage 1 / Stage 2 split.

## 2. Step 2: decomposing sub3's 10.5 h

`T_total = Q + S + A_tasks + V + P`. The 12 h clock covers `S + A_tasks` at most. The Evaluation page says the limit is "inclusive of sandbox setup time,
but excluding time for patch validation" (`scratchpad/kaggle_pages.md:128`). Whether vLLM start-up counts is not stated, so it is counted here (conservative).
Below, **A = S + A_tasks**, i.e. everything that might count toward 12 h.

| term | value used | evidence |
|---|---|---|
| Q queue, P publish lag | 0 (unknown, ≥ 0; setting 0 maximises A, the conservative choice) | zhukov's near-null run scored ~80 min after submit (forum 743365), so submission queues were short on 09-25 |
| S start-up | 560 s (503-509 s in our L4 kernels, 562 s competitor) | `research/time_model.md:36-42` |
| V validation, all tasks patched | ~2 h ("IIRC"); a no-patch submission ~10 min | host, forum 743663 [3528731] |
| Validation is sequential after the agent phase | yes: Stage 1 `scripts/inference.py` writes `submission.parquet`, Stage 2 `scripts/metric.py score(solution, submission)` validates it | `data/HARNESS_README.md:98, 578-581`. Also Geremie Yeo's 14.5 h run did not error (743140 [3528322]), so ≥ 2.5 h of a displayed runtime sits outside the 12 h |
| v4 non-empty patch rate | **0.824** (p_v4 61/74, r_v4 42/51); v9_eog 0.92 (47/51) | `eval/eval3/eval/runs/p_v4/task_results.jsonl`, `eval/race1/runs/r_v4|r_v9_eog/task_results.jsonl` (`agent_patch_size > 0`) |
| **V for sub3** | 0.824 × 2 h = **1.65 h** (with a 10-min fixed part: 1.68 h). Host figure ± 25 % gives **1.24-2.06 h** | scaled |
| **A for sub3** | central 10.42 − 1.66 = **8.75 h**; conservative 10.50 − 1.24 = **9.26 h**; low 10.33 − 2.06 = **8.27 h** | |
| mean in-clock seconds per task, `(A − S)/N` | 258 s at N=120 (243-273 s over the A range); 238 s at N=130 | `budget5.out` E |

The Geremie data point pushes A down, not up. If the 12 h check covers `S + A_tasks` and his 14.5 h run passed, then V ≥ ~2.35 h for that uncapped bundle,
more than the host's 2 h. A larger V means a smaller A. The 9.26 h row is therefore the conservative end, and the orchestrator's 9.4 h row is a stress case.

## 3. Refuting "every hidden task hits the cap", and what remains true

- **All tasks capped needs A ≥ 10.49 h** at N=120 (560 s + 120 × (300 + 5 overshoot + 5 overhead)), which leaves V + Q + P ≤ 0.01 h of the observed
  10.50 h. At N=116 it leaves ≤ 0.36 h. The host puts V near 1.65 h, so the all-capped reading
  (`research/time_model.md:79-84`, `research/own_data.md:47`, `research/test_plan.md:290`, `research/harness_runtime.md:564`) is **inconsistent with the evidence**.
- **Most hidden tasks still hit the cap.** Public e74_v3 on L4 averages 146.8 s agent time with 9/74 capped. Two ways of fitting 258 s per task:
  - uniform slowdown: hidden agent time = k × public time, **k = 2.9-4.6**, which gives **55-74 % capped at 5.0 min** (`budget5.out` A, N=120, overhead 5-12 s);
  - mixture: some tasks behave like public ones, the rest run to the cap. (305 − 253)/(305 − 147) = 0.33 public-like, so **67 % capped**.
- Consequences for v10 design: (a) raising the cap adds time on ~60 % of tasks, so it is not free; (b) time_model's point still applies to that ~60 %: extra
  within-task work such as parallel candidates adds no wall time on capped tasks (`research/time_model.md:193-196`), but it does add time on the other ~40 %.
- Per-task container overhead is inside A in any case. Docker per-task lifecycle (gap 1, Mac arm64 Docker, 9 gold tasks): setup 3.6-15.2 s (mean 7.6),
  start 0.1 s, stop 2.1 s, about **10 s per task** against 4.7 s under subprocess (`scratchpad/gap1/oracle_docker.jsonl`). The scorer's x86 figure is UNVERIFIED.
  zhukov's near-null run (5-min cap, tasks failed early, ~120 tasks, ~80 min submit-to-score) bounds overhead plus early failure at **≤ ~35 s per task**. The table
  therefore uses 5, 12 and 35 s.

## 4. Step 3: the 12 h table with validation excluded

Method (`budget5.py`): the e74_v3 per-task agent times (74 L4 tasks, `scratchpad/tm/tasks.json`, capped = `err` contains "session timeout") are rescaled so that
`S + N × mean(overhead + min(k·a_i, cap + 5 s))` equals A at the 5.0-min cap. A task capped on the public run is assumed to run to any cap. Each cap is then re-projected.
"v10" multiplies uncapped time by 1.2 (v9_eog vs v4: +22 % wall on H100, 135 vs 111 s/task; +18 % projected L4 agent time, 171 vs 145 s; `research/time_model.md:248-252`).
12 h = 43,200 s. **Hours inside the 12 h clock:**

| A (h) | N | overhead/task | capped at 5.0 | v4-like 5.0 / 5.5 / 6.0 | v10 (×1.2) 5.0 / 5.5 / 6.0 | sd of the sum (upper bound) |
|---|---|---|---|---|---|---|
| 8.40 | 120 | 5 s | 57 % | 8.40 / 8.96 / 9.52 | 8.80 / 9.42 / **10.00** | 0.34 |
| 8.40 | 130 | 5 s | 53 % | 8.40 / 8.93 / 9.39 | 8.80 / 9.40 / **9.99** | 0.39 |
| **8.75** | 120 | 5 s | 64 % | 8.75 / 9.37 / 9.93 | 9.13 / 9.78 / **10.41** | 0.32 |
| 8.75 | 120 | 12 s | 58 % | 8.75 / 9.32 / 9.88 | 9.13 / 9.77 / **10.37** | 0.34 |
| 8.75 | 130 | 5 s | 55 % | 8.75 / 9.35 / 9.93 | 9.20 / 9.81 / **10.41** | 0.38 |
| 9.24 | 120 | 5 s | 69 % | 9.24 / 9.91 / 10.55 | 9.54 / 10.31 / **11.00** | 0.28 |
| 9.24 | 130 | 5 s | 58 % | 9.24 / 9.85 / 10.46 | 9.65 / 10.34 / **11.00** | 0.35 |
| 9.40 | 120 | 5 s | 74 % | 9.40 / 10.09 / 10.76 | 9.65 / 10.43 / **11.19** | 0.27 |
| 9.40 | 130 | 5 s | 64 % | 9.40 / 10.04 / 10.66 | 9.81 / 10.50 / **11.19** | 0.34 |

(At 35 s overhead every 6.0-min figure is 0.1-0.4 h lower; all rows are in `budget5.out`.) A bootstrap over the 74 public tasks moves the 6.0-min v10 total by
< 0.1 h (p95), so shape uncertainty is small. The **run-to-run** uncertainty is larger. The last column (between-task sd × √N) bounds it at 0.27-0.39 h, **so hold ~0.7 h of margin (2 sd)**.

**Distribution-free check.** For any task-time distribution, `min(m·x, c1) ≤ max(m, c1/c0) · min(x, c0)`. So
`T(c1) ≤ S + N·ovh + max(m, c1/c0) · (A − S − N·ovh)`, where m is v10's per-task slowdown against v4. For c1 = 6.0 min and any m ≤ 1.2, the factor is 1.2:
- A = 8.75 → **≤ 10.44 h**; A = 9.24 → ≤ 11.02 h; A = 9.4 → ≤ 11.22 h. At m = 1.3: 11.28 / 11.92 / 12.12 h.
- **Break-even (N=120): cap 5.5 is safe for A ≤ 10.94 h, cap 6.0 for A ≤ 10.05 h, cap 6.5 for A ≤ 9.31 h** (each at m ≤ c1/c0).

**Absolute worst case (every task capped; excluded by sect. 3, shown for completeness):** at N=120 and 5 s overhead, 10.49 / 11.49 / 12.49 h for 5.0 / 5.5 / 6.0.
At N=130 and 12 s overhead, 11.60 / 12.69 / 13.77 h.

**Reading:**
- **5.5 min: safe everywhere.** The worst projected v10 row is 10.50 h, and adding 0.7 h margin gives 11.2 h. The distribution-free bound for m ≤ 1.2 is 11.22 h at A = 9.4.
- **6.0 min: safe at the central A** (10.4 h projected, 11.1 h with margin), **not at A ≥ 9.2 h** (11.0-11.2 h projected, 11.7-11.9 h with margin).
  6.0 therefore needs A ≤ ~9.0 h, i.e. validation + queue + lag ≥ ~1.5 h of sub3's 10.5 h. That is the host's figure (1.65 h), but it is one "IIRC" sentence.
- A heavier v10 (m > 1.2), e.g. 3 parallel fixers at +15 to +60 s per task (`research/time_model.md:22`), invalidates the 6.0 case: at m = 1.3 the bound reaches 11.9-12.1 h.

## 5. What the extra minute buys (`solvegain.py`)
A solve counts if its last edit lands before the cap, because at timeout the `/workspace` diff is graded (`HARNESS_README.md` sect. 8.1).
Under uniform slowdown k, a public solve with last edit at x lands on the hidden set iff k·x ≤ cap:

| k | L4 real solves (n=40): share landing at 5.0 / 6.0, gain | race-1 solves projected to L4 (n=94): 5.0 / 6.0, gain |
|---|---|---|
| 3.0 | 0.75 / 0.75, +0 % | 0.63 / 0.72, +15 % |
| 3.5 | 0.62 / 0.75, +20 % | 0.47 / 0.63, +34 % |
| 4.0 | 0.60 / 0.68, +13 % | 0.33 / 0.48, +45 % |
| 4.5 | 0.53 / 0.62, +19 % | 0.29 / 0.37, +30 % |

Applied to sub3's ~7/58 public solves, that is **+0 to +3 tasks, central about +1**. Under the mixture model the gain is ~0. The gain is small and uncertain, but it is
the cheapest lever available, and 5.5 already takes roughly half of it.

## 6. Step 4: `timeout_seconds`

### 6.1 Agent side: what raw 180 s timeouts cost (`timeouts.py`, 500 task-runs, 11,470 `run_command` calls)
| run | tasks | raw timeouts | s lost | saved if 60 / 90 / 120 | affected tasks (C = capped, none resolved) |
|---|---|---|---|---|---|
| e74_v3 (L4 Kaggle) | 74 | 3 (2 `pip install`, 1 repro) | 541 (7.3/task) | 361 / 271 / 181 s | fastapi_11194, fastapi_14986, rich_3480 C |
| e74_v2 (L4 Kaggle) | 74 | 2 | 241 (3.3/task) | 121 / 91 / 61 | rich_3480 C |
| r_v9_eog (H100) | 51 | 1 (`python3 reproduce_issue.py`) | 180 (3.5/task) | 120 / 90 / 60 | rich_4006 |
| r_v4, r_v9_c, r_v9_eg, r_v9_eo, r_v9_og | 255 | 5 | 823 | | rich_4006 ×2, rich_3480 ×2, fastapi_13920 C |
| c_v9_eg, c_v9_eog | 46 | 3 | 464 | | fastapi_14258 C ×2 |
| **pooled** | **500** | **14** | **2,249 (4.5/task)** | **1,409 / 1,019 / 667 s = 2.8 / 2.0 / 1.3 s per task** | |

- **12 h effect: 120 × 2.0 s = 0.07 h at 90, 0.04 h at 120.** It is negligible, and `max_time_minutes` already bounds every task.
- **Per-task effect:** 2.8 % of tasks lose 60 % of a 300 s budget to one hang. They are issues about hangs (rich_3480 "infinite loop in append", rich_4006,
  fastapi_14258): the model's raw repro hangs on the unfixed code. `run.py` (20 s default, `helpers_v9/run.py:6-8`) is the right bound for these, not the global key.
- Zero raw timeouts went through a helper. The two `pip install` hangs are a no-network artefact of our subprocess sandboxes. Under Docker
  `network_mode="none"` (`HARNESS_README.md:249`), pip probably fails fast (UNVERIFIED).

### 6.2 What a lower value would kill (finished calls longer than T, same 500 task-runs)
- **> 60 s: 4 calls.** `gate.py` on requests_6644 took 65.3 s and 65.5 s (c_v9_eg, c_v9_eog; a legitimate, useful regression result), a 66.2 s `python3 -c` pipe test (r_v9_c rich_3468, exit 0), and a 133 s `curl` (useless).
- **> 90 s: 1 call (the curl). > 120 s: 1 (the same curl).**
- `gate.py` makes two pytest runs at `--timeout 60` each plus untimed `git grep`/`git archive` calls (`helpers_v9/gate.py:12-13, 29-43`). Its worst case is **~120 s + git time**.
  With `timeout_seconds` < ~130 the harness can kill it and its output is lost. `timeout_seconds` also sets the `run_skill_script` timeout (`research/config_space.md:97`).

### 6.3 Validation side (outside the 12 h)
- Local harness: the verification pytest uses `config.harness.command_timeout_seconds` (`swegemma/harness/verification.py:498-503`). That value is `timeout_seconds` when set
  (`swegemma/config.py:179-189`) and 300 otherwise (`swegemma/budget.py:29`, `swegemma/evaluate.py:62-66`).
- **On Kaggle it may not apply at all.** eval_config is loaded by Stage 1 `scripts/inference.py` (`HARNESS_README.md:98, 528`). Stage 2 runs in `scripts/metric.py score(solution, submission)`
  on the parquet (`:578-581`). Whether metric.py reads the bundle's eval_config is **UNVERIFIED**, and the file is not in the wheelhouse.
- If it does apply, the risk is a correct patch whose hidden suite runs longer than T on 2 vCPUs. Public passing verifications take ≤ 12.6 s (`eval/kaggle/oracle_all`, 74 valid tasks).
  But real verification runs (setup + pytest) reach **69-77 s** on the Kaggle CPU: all 13 `requests_*` oracle runs, which failed for environment reasons (`oracle_all/results.jsonl`, median 69.0 s).
  Because validation sits outside the 12 h, a low T there saves nothing and can only lose a solve.

### 6.4 New defect: `run.py` timeouts orphan the real command
`run.py` calls `subprocess.run(cmd, shell=True, ..., timeout=t)` (`helpers_v9/run.py:14`). On timeout Python kills only `/bin/sh`. For a compound or piped command the child keeps running.
Tested today with scratchpad copies: `run.py --timeout 2 "cd . && sleep 7.77 && echo hi"` returned in 2.11 s and `sleep 7.77` was still alive afterwards. The same happened for
`"sleep 7.79 | tail -5"`. A plain `"sleep 7.78"` was killed (sh execs it). macOS `/bin/sh`; Linux dash execs fewer commands, so the effect is at least as likely there (UNVERIFIED on the scorer).
Agents write `cd /workspace && python -m pytest ... | tail` constantly. An orphaned pytest keeps burning the sandbox's 2 vCPUs and slows every later command in the task. **Fix:** `Popen(..., start_new_session=True)`,
and on timeout `os.killpg(p.pid, SIGKILL)` before reading the output. `gate.py`'s `sh()` has no timeout at all. Add edge-case tests for compound, pipe, background (`&`) and a grandchild that ignores SIGTERM.

### 6.5 Choice
**`timeout_seconds: 120`.** It kills no legitimate finished call in 500 task-runs. It saves 1.3 s/task against 180, and 90 would save only 0.7 s/task more.
If Stage 2 uses it, it keeps a 1.6× margin over the slowest real suite seen (77 s) and 9.5× over public passing verifications. Pair it with:
(a) `gate.py --timeout` ≤ 50 so 2 runs + git fit under 120, (b) the `run.py` process-group fix, (c) prompts that route repros and tests through `run.py`, since that bounds a hang at 20 s.
60 and 90 (`research/own_data.md:173, 493`; `research/time_model.md:298`) are not justified: they save ≤ 0.09 h per run and 60 kills `gate.py`.
Raising to 300 (`research/forum.md` implication 2) protects only against a Stage-2 risk that may not exist, and costs 120 s on each of the 2.8 % hang tasks.

## 7. Recommendations for v10 (eval_config and process)

```yaml
evaluation:
  max_time_minutes: 5.5   # safe in every scenario in sect. 4; step to 6.0 only after the sub4 rule below passes
  timeout_seconds: 120    # sect. 6.5; gate.py --timeout <= 50; run.py must kill the process group
  max_tool_calls: ...     # loop brakes only, not 12 h knobs (time_model sect. 5)
  max_turns: ...
```

**Decision rule for 6.0, from sub4.** sub4 (v9_eog, heavier than v4, 92 % non-empty) is armed for **05:36 IST 2026-09-28 (00:06 UTC)** (`eval/submit_log.txt:12-13`; the brief says 00:01).
Let `T4` be its submit-to-COMPLETE and `V4 = 0.92 × 1.5-2.0 h ≈ 1.39-1.85 h`, so `A4 = T4 − V4`. Requiring 6.0 min to stay under 11.3 h (0.7 h margin) at factor 1.2 gives `A4 ≤ 9.47 h`, i.e.:
- **T4 ≤ 10.85 h: 6.0 min is safe** for a v10 no heavier per task than v9_eog.
- 10.85 < T4 ≤ 11.7 h: 5.5 min.
- T4 > 11.7 h: stay at 5.0 and look for the missing time.
- The model predicts T4 ≈ 10.9-11.0 h (v10 ×1.2 row at 5.0 plus V4), so the rule is live, not a formality.

**Bracket sub4 properly.** The current poller logs only start and end, which is why sub3's bracket rests on an assumption. Poll every 300 s and log every observation, e.g. to the scratchpad:
`while :; do s=$(kaggle competitions submissions gemma-4-developer-agent -v 2>&1 | grep 'sub4:'); echo "$(date -u +%FT%TZ) ${s:-no-sub4-row-or-cli-error}" >> <scratch>/sub4_poll.log; case "$s" in *COMPLETE*|*ERROR*) break;; esac; sleep 300; done`
It matches the sub4 row by its tag, so sub3's COMPLETE row cannot end it early, and a CLI error is logged and retried. This gives ±5 min. Also read sub3's and sub4's displayed runtimes in the UI (sect. 1.3). **Not started here** (read-only brief; it runs about 11 h).

## 8. Corrections to earlier reports
- `research/time_model.md:79-84, 219-236, 297`: "plan for all tasks at the cap", "5.0 is the right cap, never above 5.25". The all-capped case is inconsistent with sub3's 10.50 h once validation is subtracted (sect. 3). 5.5 fits every scenario (sect. 4).
- `research/own_data.md:47-50, 162-168`: "hidden tasks run ~1.9× longer", "v10 may be at most +15 % total wall (12/10.4)". The 10.4 h includes ~1.65 h of validation. The in-clock ceiling ratio is 12/8.75 ≈ 1.37, or 12/9.26 ≈ 1.30 conservatively, before margin.
- `research/own_data.md:173, 493` and `research/time_model.md:298`: `timeout_seconds` 60/90. See sect. 6.5.
- `research/test_plan.md:290, 412` (R71 derives ≤ 5.0 from the all-capped reading) and `:413` (R72: keep 120-180): **R72 stands; R71 should use A, not 10.4 h.**
- `research/competitors.md:287-289, 358-359`: "12 min/task cap exceeds the 12 h (zhukov v3)" and "thinking on exceeds the 12 h (Black Cat)" are **not established**. "Notebook Exceeded Allowed Compute" is also the UI label of the platform-side resource error of 09-25/26
  (forum 743213 [3528737]: submission 56571006 "requested more CPU, GPU or TPU resources", UI "Notebook Exceeded Allowed Compute"; 743661: the same error 2-5 h into runs, one with a 12-min cap). Only Chandram Dutta [3528559] reports a real 12 h error, with no configuration given.
- The follow-up brief's sub1 figure ("at most 10.6 h", from `eval/ledger.md:17`) is wrong: 10.51-12.74 h (sect. 1.2). The ledger timestamp was backdated.

## 9. Open items and UNVERIFIED
- The host's ~2 h validation figure ("IIRC") is the load-bearing input for choosing 6.0 over 5.5. sub4's bracket is the cheapest check.
- Whether the 12 h counts vLLM start-up (counted here; worth 0.16 h).
- Whether Stage 2 (`scripts/metric.py`) uses the bundle's `timeout_seconds` (sect. 6.3).
- Scorer Docker per-task overhead on x86 (Mac arm64: ~10 s; bounded ≤ ~35 s by zhukov's 80-min run).
- Run-to-run sd of a full scoring run: bounded at ≤ 0.4 h here from between-task spread. A rerun of the same bundle would measure it.
- Whether "unfinished = 0" has shipped (743063). If it has, an overrun stops being fatal and 6.0 becomes low-risk regardless.
