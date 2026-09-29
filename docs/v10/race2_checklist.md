# Race 2 checklist: pre-registered KPIs (SPEC 10.3, R118)

Written 2026-09-28, before any race-2 run exists. Nothing in this file may change after the first race-2 task starts.
If a threshold turns out to be wrong, the change goes into a dated addendum at the end with the reason, and the
original row stays as written.

Arms, both on the same pod and the same 74 task ids (`data/arena_ids.txt` + `data/rest_ids.txt`):
- control `r2_v9_eog` = `submissions/v9_eog`, the shipped sub4 bundle;
- treatment `r2_v10` = `submissions/v10`.

Each arm runs twice (`r2_<arm>_1`, `r2_<arm>_2`), 2 tasks per GPU. Round 1 puts the control on GPU0 and v10 on GPU1;
round 2 swaps them. Chain: `pod/chain_race2.sh`. Starting it is Carson's call.

Faithful settings for both arms (`scripts/run_eval.py`, R115):

| switch | value | effect |
|---|---|---|
| `G4_COMPACTION` | 1 | `EventsCompactionConfig(compaction_interval=5, overlap_size=2, token_threshold=14336, event_retention_size=5)` (README 553-561) |
| `G4_L4_SCALE` | 1.7 | caps divided by 1.7 (v10: 176 s and 71 s; v9_eog: 176 s and 106 s); `clock_scale` 1.7 in every agent sandbox |
| `G4_NO_EDITABLE` | 1 | nothing is installed into `/workspace` (Kaggle, F9d) |
| `FAITHFUL` | 1 | the four budgets come from each bundle's `eval_config.yaml` |

## 1. Before the race (all free, in this order)

1. CI green: `.venv/bin/python -m pytest -q tests`.
2. NIGHTLY green: `G4_NIGHTLY=1 .venv/bin/python -m pytest -q tests/test_v10_tasks.py tests/test_v10_flow.py`, then
   `V10_ONLY=1 G4_NIGHTLY=1 scripts/linux_test.sh`.
3. `.venv/bin/python scripts/validate.py submissions/v10` prints `OK model=`; `scripts/pack_bundle.py` is deterministic;
   `bash -n` and `shellcheck` pass on `pod/chain_race2.sh` (covered by `tests/test_build.py`).
4. Replay sanity (R116): `.venv/bin/python scripts/replay_l4.py --baseline` prints 150.2 and
   `.venv/bin/python scripts/replay_l4.py --design final` prints 154.0.
5. The Mac writes `GO_RACE2` (one line, `GO`) on the pod. Anything else stops the chain after at most 100 minutes.

## 2. Pass conditions (every row must pass for v10 to replace v9_eog)

| # | KPI | pass condition | how it is computed (`scripts/replay_l4.py --race2 eval/runs`) | race-1 v9_eog, same code |
|---|---|---|---|---|
| 1 | resolved, sum of 2 runs | v10 at least v9_eog + 6 on the paired 74 x 2 | sum of `resolved` in `task_results.jsonl` over runs 1 and 2 of each arm | 21/51 (28/74 with the confirmation run) |
| 2 | resolved, per run | no run has v10 below v9_eog - 3 | run k of v10 against run k of v9_eog | - |
| 3 | crashes | 0 per class, over both v10 runs | `error` of each result row: context overflow (`ContextWindowExceeded`, `maximum context length`, `prompt contains at least`), unknown tool (`Tool '...' not found`), KeyError (`KeyError`, `Context variable not found`), post-invocation ValueError (`No LlmAgent model available`) | 0 / 0 / 0 / 0 |
| 4 | helper availability | at least 98% of tasks, in each v10 run | a task counts when a `run_skill_script` returned status success, or a `run_command` naming `/tmp/swe/` returned neither `can't open file` nor `No such file or directory` | 0.59 (30/51) |
| 5 | missing helpers | `can't open file` 1 per 50 tasks or fewer, in each v10 run | `run_command` calls naming `/tmp/swe/` whose result contains `can't open file`, divided by tasks | 1.37 per task (70 calls) |
| 6 | malformed `edit_file` | 1 or fewer per task on average, in each v10 run | `edit_file` calls whose result says `mandatory input parameters are not present`, divided by tasks | 3.16 |
| 7 | patches touching protected files | 0 | files of each saved patch checked with the harness rule `_is_protected_test_or_config_path` (copied into `replay_l4.is_protected`) | 10/51 |
| 8 | patches with scratch or vendored files | 0 | NEW files only: at the root `repro*`, `reproduce*`, `scratch*`, `debug*`, `tmp*`, `temp*`, `try*`, `demo*`, `test_*.py`, `*_test.py`; anywhere `*.log`, `*.orig`, `*.rej`, `*.bak`, `*.swp`, `.coverage`; any path through `site-packages/`, `_pytest/` or `*.dist-info/` | 12/51 |
| 9 | empty patches | 2 or fewer per 74 tasks, in each v10 run | result rows with `agent_patch_size` 0 and no saved patch text | 4/51 |
| 10 | prompt tokens | at least 95% of stage-runs peak under 14,336; the largest prompt under 26,000 | a stage-run is a maximal run of consecutive agent steps by one author; its peak is the largest `prompt_tokens` | 81% under; max 25,657 |
| 11 | compaction events | reported, no threshold | same-author call at 14,336 or more followed by a call under 70% of it (gap_4 rule) | 0 (pod runs never compacted) |
| 12 | time (R117, restated 2026-09-28, see Addenda) | no task projected past cap + 10 s, and the N=130 hidden-run projection (600 s + per task 3.6 + min(1.9 x re-timed, 305) + 1 s) under 12 h. The replayed mean against the r_v4 replay on the same ids is reported. Above 1.08 x, the first pre-registered knob is applied (verifier repair rounds 2 -> 1), then the second (LOCATOR banner 75 -> 60 s) | `replay_l4.py --run eval/runs/r2_v10_k --against r_v4`: every call re-timed with the L4 model plus 5.6 s per detected compaction (time_model 3.4) | v9_eog: FAIL, 5 tasks past the cap; 1.16 x; 9.79 h |
| 14 | footer obedience | reported, no threshold | the first time each footer (LOCATOR, EDIT NOW, CONTEXT, FINISH, TIME) reaches a stage in a task: did that stage's next step do what it asks (`replay_l4.footer_obedience`) | n/a (v9 prints no v10 footer) |
| 13 | verify behaviour | a `VERIFY:` verdict line in at least 90% of tasks, in each v10 run; checkpoint restores reported | any tool result containing `VERIFY: GREEN`, `AMBER`, `RED` or `UNKNOWN`; restores = count of `RESTORED` | n/a (v9 prints no verdict) |

Machine-readable thresholds. `tests/test_v10_runner.py` fails if these differ from `replay_l4.KPI`:

```
resolved_sum_margin = 6
resolved_run_floor = -3
crashes_max = 0
helper_ok_min = 0.98
cant_open_per_task_max = 0.02
malformed_edit_per_task_max = 1.0
protected_patches_max = 0
scratch_patches_max = 0
empty_patches_max = 2
stage_under_line_min = 0.95
prompt_max = 26000
verdict_share_min = 0.90
time_ratio_max = 1.08
time_over_s = 10
time_proj_h_max = 12
time_n_hidden = 130
kill_floor = -3
```

The last column is `replay_l4.run_kpis` on `eval/race1/runs/r_v9_eog` (51 arena tasks, no compaction, pod caps),
so race 2 is compared with numbers produced by the same definitions. It is context, not a threshold.

## 3. Kill rule (applied by the chain after run 1)

After round 1, `scripts/replay_l4.py --kill-check eval/runs` stops the chain (backup, then the pod goes down) when
v10 run 1 resolves fewer than v9_eog run 1 minus 3, or when any crash class of row 3 is above 0 in v10 run 1. It fails
closed: a run 1 with no task results, arms with different task counts, or a failure of the checker itself also stop
the chain. Run 2 does not start; the traces are diagnosed on the Mac first.

## 4. Ship rule

v10 replaces v9_eog as the next Kaggle submission only if every row of section 2 passes
(`tests/test_v10_runner.py::test_race_kpis`, RACE tier, reads `eval/runs/r2_*` or `$G4_RACE_DIR`). The push is Carson's.

## 5. After the race (not part of this build)

`docs/v10/race2_report.md`: paired per-task wins and losses with an exact sign test, the union of solves, per-lever
attribution from the verify verdicts (claims flipped, siblings acted on, restores that turned RED into GREEN, EMPTY
recoveries), and the replay time. Compaction counts from row 11 are compared with the Kaggle L4 rate (1.04 events per
task, gap_4) to judge how faithful the pod was.

## Addenda

1. **2026-09-28, review round 2, before any race-2 run.** Row 12 changed. It used to be the replayed mean at most
   1.08 x r_v4 plus no task past cap + 10 s. The ratio was a ship blocker, and the ratio is not what the 12 h cliff
   depends on:
   - The SPEC 9.1 projection behind it cut every stage at its footer time and capped stage replies at 200/100/60
     tokens, so it could not show a task at the cap.
   - With measured replies, v10 projects 0.93-1.09 x v4 on public-like tasks with the footers obeyed and 0.96-1.15 x
     with no footer cuts. That is about 6.3 h for a whole run.
   - On hidden, cap-saturated tasks the per-task wall is bounded by the cap (10.49 h at N=120, 11.35 h at N=130),
     whatever the ratio.
   So the blocker is now the cap: no task past cap + 10 s, and the N=130 projection under 12 h. The ratio triggers the
   pre-registered knobs. Row 14, footer obedience, is new and reported only: the projection assumes the footers are
   obeyed, and race 2 measures whether they are. The thresholds were changed before any race-2 data existed.
2. **2026-09-29, after race 2 round 1, for the v10.1 measurement.** No row above changes: rows 1-14 keep their
   definitions and thresholds, and round 1 stays scored by them. `scripts/replay_l4.py --race2` now also prints eleven
   diagnostic rows marked `(v10.1)`, computed by `replay_l4.pipeline_diag` and `patch_mechanism` from the same traces.
   They are reported with the targets the diagnoses proposed (`docs/v10/v10_1_diag_1.md` to `_4.md`) and never fail a
   race. Round-1 values, same code (`r2_v10_1`, then `r2_v9_eog_1` where it differs):

   | row | definition | round 1 | proposed target |
   |---|---|---|---|
   | invented tool names | parsed: a tool call whose name is no declared or skill tool (the fastapi_13537 crash); unparsed: a reply containing `<\|tool_call>call:NAME` whose NAME is no tool (each ends its stage) | parsed 1, unparsed 29 (v9_eog 0, 0) | parsed 0, unparsed at most 2 per 74 |
   | stage-ending text calls | every reply containing `<\|tool_call>`, plus how many name a real tool (cut or malformed) and how many tasks have two stage-runs in a row ending on one | 36, real tool 7, cascades 7 (v9_eog 1) | at most 8 per 74 |
   | verifier first turn is a text call | verifier stage-runs whose first step is such a reply | 9/69 (v9_eog 0/63) | at most 2 per 74 |
   | helper / tool typed as a shell command | `run_command` whose command starts with `NAME.py` of a helper, or with a tool name | 6, 2 (v9_eog 0, 18) | reported |
   | locator replies at the output cap | locator text replies with `completion_tokens` at 768 | 11 | at most 2 per 74 |
   | grep.py trailing-path calls that missed | `grep.py` calls (shlex-split) with a positional word after the regex, and how many printed 0 hits or an invalid regex | 65 of 72 | at most 10% |
   | empty submit before t=285 | `submit_patch` with `patch_size` 0 while the last helper footer read t < 285 | 3 (t=115, 271, 283) | 0 |
   | can't open file: real / invented helper | row 5 split by whether the missing `/tmp/swe/X.py` is one of the 9 helpers | 0 / 2 | reported |
   | KPI 7/8 mechanism | for each row-7/8 patch: a write after the last finalize that printed READY, or no READY finalize | fastapi_14077: write after READY finalize (step 44); fastapi_14258: no READY finalize (end state) | reported |
   | tasks past cap + 10 s, all ids | row 12's re-timing over every task, not only the 51 shared with r_v4 | fastapi_14306, rich_3061, rich_4079 | reported |
   | verify ran, NO SOURCE CHANGE only | tasks whose only verify output was `VERIFY: NO SOURCE CHANGE` (row 13 counts them as no verdict) | 4 | reported |
