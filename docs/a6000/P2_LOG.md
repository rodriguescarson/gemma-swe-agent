# P2 / P4 / P3 autonomous run log (A6000)

Plan and pre-registration: docs/v4h/GATE.md, "P2 addendum 4". The supervisor (scripts/a6000/autopilot.py) appends one health line per hour:
`step | done/total | solved | empty | errors | median secs | cap hits | GPU util | disk free | server restarts`.

## Health
- 2026-10-06T21:44:04Z | LAUNCH stage 1a; HARD STOP 2026-10-08T09:44:04Z
- 2026-10-06T21:44:09Z | step=stage1a | EVENT started pid 21342 (restarts so far 0; hard stop in 36.0 h)
- 2026-10-06T21:48:21Z | step=stage1a | EVENT started pid 26870 (restarts so far 0; hard stop in 35.9 h)
- 2026-10-06T21:48:51Z | step=stage1a | EVENT pace proxy died; restart 1/3
- 2026-10-06T21:48:54Z | step=stage1a | EVENT started pid 28071 (restarts so far 1; hard stop in 35.9 h)
- 2026-10-06T21:49:24Z | step=stage1a | EVENT pace proxy died; restart 2/3
- 2026-10-06T21:49:51Z | step=stage1a | EVENT started pid 30142 (restarts so far 0; hard stop in 35.9 h)
- 2026-10-06T21:50Z | EVENT supervisor restart at 21:48 started a duplicate race runner (the first supervisor had not recorded its child's pid, so the new one could not adopt it). Both runners, the in-container processes and 2 partial items were removed; 2 completed items (21:47) kept; supervisor restarted clean at 21:49:51. Fix: the supervisor now records child/proxy pids and adopts them on restart. Stage 1a lost about 5 minutes; the 36 h clock is unchanged (launch 21:44:04 UTC).
- 2026-10-06T21:56:01Z | step=stage1a | EVENT adopted running pid 30142
- 2026-10-06T22:13:16Z | step=stage1a | EVENT adopted running pid 30142
- 2026-10-06T22:49:05Z | step=stage1a | EVENT adopted running pid 30142
- 2026-10-06T22:55Z | EVENT duplicate-runner incident closed: one supervisor (pid 2348), one runner (30142), one proxy (29997), one backup loop; items.jsonl 0 duplicate (arm, task) rows; 2 items were in flight during the 21:48:21-21:49:30 overlap and are registered as CONTENDED in docs/a6000/contended_items.json (v6p-think/arrow_06fe693, v6p/arrow_0fe5f06; both deleted and re-run clean from 21:49:52); stage tables are reported with and without them; regression tests added (fresh supervisor records the child pid; restarted supervisor adopts, no duplicate; mutation-checked).
- 2026-10-06T23:49:07Z | step=stage1a | done=48/150 | solved=7 | empty=20 | errors=0 | median_s=276.1 | cap=13 | gpu=100% | disk_free=902GB | restarts=0
- 2026-10-07T00:49:12Z | step=stage1a | done=69/150 | solved=10 | empty=33 | errors=0 | median_s=306.0 | cap=24 | gpu=100% | disk_free=902GB | restarts=0
- 2026-10-07T01:49:17Z | step=stage1a | done=91/150 | solved=13 | empty=46 | errors=0 | median_s=306.4 | cap=31 | gpu=100% | disk_free=902GB | restarts=0
- 2026-10-07T02:49:22Z | step=stage1a | done=119/150 | solved=26 | empty=53 | errors=0 | median_s=292.0 | cap=39 | gpu=100% | disk_free=902GB | restarts=0
- 2026-10-07T03:49:28Z | step=stage1a | done=143/150 | solved=33 | empty=64 | errors=2 | median_s=292.0 | cap=48 | gpu=99% | disk_free=902GB | restarts=0
- 2026-10-07T06:57:38Z | EVENT OUTAGE: WSL shut down after the Claude session exited (about 04:06 UTC: last GitHub backup 04:06, last health line 03:49) and was back about 06:53, roughly 2 h 47 min with the supervisor, vLLM, dockerd, the race runner and the proxy all down. State on disk: stage 1a 148/150 items finished and intact (866 backed-up files compared with their sources, every result/summary/trace parses, items.jsonl 148 clean lines); in flight and re-run: v4h2/cattrs_5cce85f and v6p-think/cattrs_5cce85f (partial directories removed). Damage repaired: the last local commit left 50 zero-length git objects and a branch ref pointing at one (the push itself had completed: remote 9e75297 is intact), so .git was saved to ~/g4/git_corrupt_backup_*, the empty objects removed, the branch reset to origin, git fsck is clean; 30 backed-up copies in the working tree were truncated by the crash (the run data under ~/g4/runs was not), restored from git, and the backup loop re-copies any file whose size differs. Hard stop UNCHANGED: 2026-10-08T09:44:04Z (launch 21:44:04 + 36 h), the outage is not added back.
- 2026-10-07T07:00:32Z | step=stage1a | EVENT started pid 1717 (restarts so far 0; hard stop in 26.8 h)
- 2026-10-07T07:10:32Z | step=stage1a | END done: done=150/150 solved=33
- 2026-10-07T07:10:36Z | step=stage1a | POST /home/jc/g4/venv/bin/python scripts/a6000/p2_results_md.py /home/jc/g4/runs/p2 rc=0
- 2026-10-07T07:10:42Z | step=p4 | EVENT started pid 4174 (restarts so far 0; hard stop in 26.6 h)
- 2026-10-07T08:10:42Z | step=p4 | done=15/74 | solved=2 | empty=7 | errors=0 | median_s=292.8 | cap=7 | gpu=100% | disk_free=902GB | restarts=0
- 2026-10-07T09:10:45Z | step=p4 | done=27/74 | solved=3 | empty=17 | errors=0 | median_s=302.2 | cap=18 | gpu=100% | disk_free=902GB | restarts=0
- 2026-10-07T09:18:29Z | EVENT EXTERNAL GPU CONTENTION: from about 07:30 UTC another workload on this lab PC (outside WSL, not mine) uses the A6000. Evidence: vLLM generated 25-29 tokens/s per running request until 07:30 and 5-6 afterwards (0.1 in stretches); P4's proxy slowdown S went 1.18 (07:00) -> 3.1 (07:30) -> 57 (08:00) -> 140 (09:00) with tasks reaching the cap after 0 tool calls; at 09:11:58 vLLM reported 0 running / 0 waiting requests while nvidia-smi showed 100% utilisation; with vLLM, the proxy and the supervisor all stopped, nvidia-smi still showed 96% utilisation at about 186 W (a ~1 GB footprint that is not mine); a raw bf16 matmul benchmark swung between 50 and 3 TFLOPS. The supervisor's stop rule (errors, median under 60 s) cannot see this: the rows are cap hits, not errors. ACTION: P4 paused at 09:17; its 7 rows finished before 07:29 (healthy GPU) are kept, the 21 rows after that are quarantined in ~/g4/runs/p4/contaminated/ (not deleted) and will be re-run; a GPU-contention guard (detect from the proxy slowdown, confirm with nvidia-smi while vLLM is idle, pause, wait for a free GPU, purge the contaminated items, resume) is being built test-first. The hard stop is unchanged (2026-10-08T09:44:04Z).
- 2026-10-07T09:30:49Z | step=p4 | EVENT GPU busy at step start (another workload is using it; utilisation samples [97.0, 0.0, 97.0, 0.0, 96.0, 0.0]); waiting for it to be free
- 2026-10-07T09:31:19Z | step=p4 | EVENT waiting for a free GPU (1 min so far; utilisation samples [97.0, 0.0, 97.0, 0.0, 97.0, 44.0])
- 2026-10-07T09:38:48Z | EVENT contention source identified (read-only queries, nothing touched): Windows-side python.exe pid 200732 (started 2026-10-07 12:39:35 local = 07:09:35 UTC from a cmd window, parent pid 123656, working set 5.3 GB, owner and command line not readable from WSL) uses about 97% of the GPU's 3D engine; WSL itself is clean (booted 06:53 UTC, one distro, one vLLM, idle container, no leftovers of the interrupted run). Not ours; the step waits for a free GPU (guard) and the hard stop is unchanged.
- 2026-10-07T09:41:21Z | step=p4 | EVENT waiting for a free GPU (11 min so far; utilisation samples [0.0, 95.0, 0.0, 94.0, 96.0, 0.0])
- 2026-10-07T09:51:23Z | step=p4 | EVENT waiting for a free GPU (21 min so far; utilisation samples [96.0, 96.0, 0.0, 96.0, 0.0, 97.0])
- 2026-10-07T10:01:25Z | step=p4 | EVENT waiting for a free GPU (31 min so far; utilisation samples [95.0, 95.0, 94.0, 95.0, 0.0, 94.0])
- 2026-10-07T10:11:27Z | step=p4 | EVENT waiting for a free GPU (41 min so far; utilisation samples [95.0, 95.0, 96.0, 0.0, 95.0, 0.0])
- 2026-10-07T10:21:29Z | step=p4 | EVENT waiting for a free GPU (51 min so far; utilisation samples [0.0, 91.0, 93.0, 92.0, 94.0, 0.0])
- 2026-10-07T10:31:31Z | step=p4 | EVENT waiting for a free GPU (61 min so far; utilisation samples [95.0, 96.0, 0.0, 96.0, 96.0, 0.0])
- 2026-10-07T10:41:33Z | step=p4 | EVENT waiting for a free GPU (71 min so far; utilisation samples [97.0, 37.0, 95.0, 0.0, 96.0, 0.0])
- 2026-10-07T10:51:35Z | step=p4 | EVENT waiting for a free GPU (81 min so far; utilisation samples [0.0, 0.0, 0.0, 0.0, 1.0, 0.0])
- 2026-10-07T10:52:35Z | step=p4 | EVENT GPU free again; starting
- 2026-10-07T10:52:38Z | step=p4 | EVENT started pid 26417 (restarts so far 0; hard stop in 24.3 h)
- 2026-10-07T11:52:39Z | step=p4 | done=33/74 | solved=16 | empty=3 | errors=0 | median_s=111.1 | cap=0 | gpu=0% | disk_free=902GB | restarts=0
- 2026-10-07T12:52:42Z | step=p4 | done=55/74 | solved=21 | empty=8 | errors=0 | median_s=135.1 | cap=2 | gpu=100% | disk_free=902GB | restarts=0
- 2026-10-07T13:46:46Z | step=p4 | END done: done=74/74 solved=29
- 2026-10-07T13:46:49Z | step=p4 | POST /home/jc/g4/venv/bin/python scripts/a6000/p4_judge.py rc=0
- 2026-10-07T13:47:22Z | step=probe_v6pb | EVENT started pid 30621 (restarts so far 0; hard stop in 20.0 h)
- 2026-10-07T13:55:23Z | step=probe_v6pb | END done: done=0/4 solved=0
- 2026-10-07T13:55:26Z | probe gate v6p-b: GATE PASS | items 4, empty patches 0, tool-call-budget errors 0, infrastructure errors 0, items with a can't open file 0, counted helper calls 61
  - ledger trio_34e7a2e: locator 2, fixer a 7, b 3, c 4 counted helper calls, 0 refusals (from traces)
  - ledger trio_ac7b93f: locator 1, fixer a 6, b 6, c 7 counted helper calls, 0 refusals (from traces)
  - ledger typer_42196d4: locator 4, fixer a 7, b 7, c 7 counted helper calls, 2 refusals (from traces)
  - ledger typer_8e75bc3: locator 3, fixer a 3, b 2, c 2 counted helper calls, 2 refusals (from traces)
- 2026-10-07T13:55:26Z | step=probe_v6pb | POST /home/jc/g4/venv/bin/python scripts/a6000/p2_probe_gate.py /home/jc/g4/runs/p2 rc=0
- 2026-10-07T13:56:02Z | step=stage1b | EVENT started pid 2788 (restarts so far 0; hard stop in 19.8 h)
- 2026-10-07T14:54:31Z | step=stage1b | EVENT STOPPED for P6 (Carson: no more compute on the old bundles): supervisor and runner stopped 14:41:41 UTC, the 2 in-flight items finished (14:43:25, 14:44:47), then the proxy, vLLM and the container were stopped; GPU free. Stage 1b as run was v6p-b on the first 31 stage-1a ids (the queue ran the new arm's items for ids 1-50 before any id 51-100: a plan mistake of mine), 0 items of ids 51-100; PARTIAL table in GATE.md. The old P3 step is removed from the plan; the plan stays open and the supervisor idles with hourly health lines until v7 arrives.
- 2026-10-07T14:54:35Z | EVENT idle: every step of the plan is done; waiting for new steps (the plan is open)
- 2026-10-07T15:54:37Z | step=idle | done=0/0 | solved=0 | empty=0 | errors=0 | median_s=n/a | cap=0 | gpu=0% | disk_free=910GB | restarts=0
- 2026-10-07T16:54:40Z | step=idle | done=0/0 | solved=0 | empty=0 | errors=0 | median_s=n/a | cap=0 | gpu=0% | disk_free=910GB | restarts=0
- 2026-10-07T17:22:11Z | EVENT P6 waiting for v7: tests/test_v7_bundle.py is not on origin/wip/gemma-agent yet (the expected ~2 h passed at about 16:40 UTC); the branch is polled every 10 min; GPU idle, supervisor idle with hourly health lines; hard stop unchanged 2026-10-08 09:44:04 UTC (16.4 h left).
- 2026-10-07T17:43:49Z | EVENT P6 step 2: v7 arrived (branch a1ac091; bundle fixes in d1ac8d4, bundle test ccc5aa6); tests/test_v7_*.py + tests/test_setup_stage.py: 128 passed, 1 skipped; scripts/validate.py submissions/v7 OK (setup [skills] / locator [run_command, get_status] / fixer [run_command, write_file, get_status] / verifier [run_command, get_status, submit_patch]). Pre-registered as GATE.md P2 addendum 11; the v7 steps (probe_v7, v7_s50, v7_p4, v7_p3 x4 passes) go into the plan now; the idle supervisor starts the probe.
- 2026-10-07T17:47:27Z | step=probe_v7 | EVENT started pid 24431 (restarts so far 0; hard stop in 16.0 h)
- 2026-10-07T17:56:57Z | step=probe_v7 | END done: done=0/4 solved=0
- 2026-10-07T17:57:00Z | step=probe_v7 | POST /home/jc/g4/venv/bin/python scripts/a6000/v7_counters.py /home/jc/g4/runs/p2 rc=0
- 2026-10-07T17:57:36Z | EVENT P6 probe_v7 RESULT: v7 arm-pure, last 4 ids, T = 2: S = 1.373 (122 calls, mean item 233 s, items 171/324/293/144 s, rc 0 x4) -> G4_L4_SCALE 0.7281 (effective cap 412 s); counters on the 4 probe items: view.py usage-line calls 0, literal-wrapper commands 0, write_file path refusals 0, forced-install {} calls 0 (must-be-zero: PASS), cap refusals 2 (v7's read cap, typer_42196d4), loops 0, budget-exhausted 0, helper unreachable 0; solved 0/4 (probe ids, not a table). Next: v7 on the 50 stage-1a ids at C = 2.
- 2026-10-07T17:57:36Z | step=v7_s50 | EVENT started pid 29560 (restarts so far 0; hard stop in 15.8 h)
- 2026-10-07T18:57:39Z | step=v7_s50 | done=40/50 | solved=15 | empty=9 | errors=0 | median_s=175.4 | cap=1 | gpu=100% | disk_free=901GB | restarts=0
- 2026-10-07T19:15:12Z | step=v7_s50 | END done: done=50/50 solved=19
- 2026-10-07T19:15:15Z | step=v7_s50 | POST /home/jc/g4/venv/bin/python scripts/a6000/p2_results_md.py /home/jc/g4/runs/p2 rc=0
- 2026-10-07T19:15:15Z | step=v7_s50 | POST /home/jc/g4/venv/bin/python scripts/a6000/v7_counters.py /home/jc/g4/runs/p2 rc=0
- 2026-10-07T19:15:18Z | step=v7_s50 | POST /home/jc/g4/venv/bin/python scripts/a6000/backup_results.py rc=0
- 2026-10-07T19:15:54Z | step=v7_p4 | EVENT started pid 32219 (restarts so far 0; hard stop in 14.5 h)
- 2026-10-07T20:15:54Z | step=v7_p4 | done=28/74 | solved=11 | empty=2 | errors=0 | median_s=91.9 | cap=0 | gpu=100% | disk_free=901GB | restarts=0
- 2026-10-07T21:15:57Z | step=v7_p4 | done=58/74 | solved=21 | empty=9 | errors=0 | median_s=99.3 | cap=2 | gpu=100% | disk_free=901GB | restarts=0
- 2026-10-07T22:01:30Z | step=v7_p4 | END done: done=74/74 solved=27
- 2026-10-07T22:01:33Z | step=v7_p4 | POST /home/jc/g4/venv/bin/python scripts/a6000/p4_judge.py --out rc=0
- 2026-10-07T22:01:33Z | step=v7_p4 | POST /home/jc/g4/venv/bin/python scripts/a6000/v7_counters.py /home/jc/g4/runs/p4_v7 rc=0
- 2026-10-07T22:01:36Z | step=v7_p4 | POST /home/jc/g4/venv/bin/python scripts/a6000/backup_results.py rc=0
- 2026-10-07T22:02:09Z | step=v7_p3 | EVENT started pid 12756 (restarts so far 0; hard stop in 11.7 h)
- 2026-10-07T22:22:20Z | EVENT P6 results so far. (a) v7 on the 50 stage-1a ids (GATE.md "v7 on the stage-1a ids", commit 1bdd72e): v7 19/50 (Wilson 0.259-0.518) vs v4h2 16/50; paired 5 wins / 2 losses, sign p = 0.453, cap gap -0.04 -> NO EVIDENCE; v7 median 167 s (v4h2 222), empty patches 10 (7), cap hits 1 (3). Counters (runs/v7_s50_counters.json): view.py usage-line 0, literal-wrapper commands 2 (FAIL of the must-be-zero rule: attrs_7804a68 and arrow_7bb5c60 send `run_command "git grep ..."`, the bare tool name before a quoted shell line), write_file path refusals 0, forced-install {} 0, cap refusals 737, loops >= 5 in 25 tasks, budget-exhausted 11, helper unreachable 0. (b) v7 on the public 74 (GATE.md P4 v7 section, commit 1087b47): 27/74 (v5h2 P4 29, L4 v4h2g 34), keep rule DROP (2 wins / 9 losses, net -7); counters (runs/v7_p4_counters.json): literal-wrapper 6 (fastapi_15589 `submit_patch` as a shell line; fastapi_14458, rich_3718 `run_command "git grep ..."`), cap refusals 107, loops 24, budget-exhausted 9, the other three must-be-zero counters 0, helper unreachable 0/74. NEW FINDING for the Mac side: the pre-edit read cap (fix 9) is hammered: the model repeats the refused view.py call 19-49 times in a row (cattrs_2ac6c03 x49, attrs_6e3786c x43, fastapi_15280 x29), every refusal costs one of the 70 harness calls, so the cap now drives budget exhaustion (11/50, 9/74) instead of preventing it. (c) P3 with v7, 4 passes, started 22:02 UTC: 4 pace proxies (8003-8006, seeds 42-45), container g4-p3, 12 of 3376 items done at 22:21, S = 1.34.
- 2026-10-07T23:02:11Z | step=v7_p3 | done=9/3376 | solved=0 | empty=2 | errors=0 | median_s=167.8 | cap=2 | gpu=100% | disk_free=890GB | restarts=0
- 2026-10-08T11:31:49Z | EVENT P7 recovery (new session): STATE. Nothing is alive: no autopilot, vLLM, pace_proxy, race or swegemma process; no docker daemon; no tmux server; nvidia-smi shows no compute process (678 MiB used, 0%). The WSL VM itself was down: it booted again at 11:29:23 UTC today, and the newest P3 files are from 23:29:38 UTC on 2026-10-07 (race.log 23:29:14, last health line 23:02:11), so the interruption killed the supervisor (autopilot_state.json still names child 12756 / proxy 32218, both gone), vLLM, the container g4-p3, the 4 pace proxies and the P3 pass at about 23:30 UTC. The plan is on step v7_p3 (done: stage1a, p4, probe_v6pb, stage1b, probe_v7, v7_s50, v7_p4). P3 (v7 = b62a546): 50 of 3376 items finished (race.log), rows.jsonl 47, pairs_raw 2 (as of the 22:22 build), disk free 830 GB. LOST: items in flight at the interruption = arrow_356035a__s3 and arrow_356035a__s4 (no task_results; the supervisor's purge rule re-runs them); P3 made no progress for about 12 h while the box was down.
- 2026-10-08T11:31:49Z | EVENT P7 DECISION: the hard stop (2026-10-08 09:44:04 UTC) passed 1 h 51 min before this session started (11:29 UTC). P7 step 5 applies: P3 is NOT resumed (that would be new GPU work after the hard stop and the supervisor's run_step returns "hardstop" before it starts docker or vLLM anyway). The supervisor is started once so that it runs its own finalize (plan finalize hooks: p3_build.py, final_summary.py, backup_results.py), cleanup and DONE line; P3 stays at 50/3376 items.
- 2026-10-08T11:31:49Z | step=v7_p3 | END hardstop: done=50/3376 solved=9

### P3 data report (2026-10-08 11:31 UTC; ONE pass, bundle v7, stopped at the hard stop; weights and data stay out of git)
- tasks finished 13 (solved in at least one pass 5); attempts 50 over 4 passes (rows per pass {1: 13, 2: 13, 3: 12, 4: 12}); captured model calls 2154
- SFT rows (test-verified successes only, sample-200 ids refused): 280; after rebalance (drop repeats, read_file share 0.15, 200 per task, unknown tools dropped): 216
- rebalance profile: `{"before": {"rows": 280, "tasks": 5, "tools": {"run_command": 230, "null": 36, "submit_patch": 9, "run_skill_script": 5}, "stages": {"setup": 14, "locator": 66, "fixer": 140, "verifier": 60}, "replies": 36}, "after": {"rows": 216, "tasks": 5, "tools": {"run_command": 166, "null": 36, "submit_patch": 9, "run_skill_script": 5}, "stages": {"setup": 14, "locator": 66, "fixer": 78, "verifier": 58}, "re`
- validation rc: 0 (build rc 0, rebalance rc 0); `s_p50_p90_max": [
  null,
  null,
  null
 ],
 "completion_tokens_p50_p90_max": [
  null,
  null,
  null
 ],
 "problems": 0,
 "first_problems": [],
 "ok": true
}`
- preference pairs (a solved and a failed attempt of the same task): **3** (raw material in pairs_raw.jsonl: task, solved passes, failed passes; the Adaption SDK's alignment schema is applied on the Mac, the package is not installed here)
- 2026-10-08T11:31:55Z | FINALIZE /home/jc/g4/venv/bin/python scripts/a6000/p3_build.py --out rc=0

## FINAL SUMMARY (2026-10-08 11:31 UTC) - every number is an A6000 screen, never a Kaggle result

#### stage 1a (ids 1-50)
**stage 1a (ids 1-50): 50 ids, arms v4h2, v6p, v6p-think; A6000 screen (int4 checkpoint, bf16 KV at 0.95, Docker-emulated sandbox, per-arm stretched cap), 1 sample per task per arm, paired, never a Kaggle result.**

| arm | finished | solved | Wilson 95% | empty patch | errored | cap hits | median s | loops |
|---|---|---|---|---|---|---|---|---|
| v4h2 | 50 | 16 | 0.208-0.458 | 7 | 0 | 3 | 222 | 7 |
| v6p | 50 | 14 | 0.175-0.417 | 19 | 2 | 3 | 226 | 9 |
| v6p-think | 50 | 3 | 0.021-0.162 | 41 | 0 | 45 | 426 | 6 |

| contrast | valid pairs | wins | losses | sign p | cap gap | verdict | no-cap pairs (W/L) |
|---|---|---|---|---|---|---|---|
| v6p vs v4h2 | 50 | 3 | 5 | 0.727 | +0.00 | NO EVIDENCE | 45 (3/5) |
| v6p-think vs v4h2 | 50 | 1 | 14 | 0.001 | +0.84 | UNRESOLVED | 5 (1/2) |

#### stage 1b (ids 51-100)
**stage 1b (ids 51-100): 50 ids, arms v4h2, v6p, v6p-b; A6000 screen (int4 checkpoint, bf16 KV at 0.95, Docker-emulated sandbox, per-arm stretched cap), 1 sample per task per arm, paired, never a Kaggle result.**

| arm | finished | solved | Wilson 95% | empty patch | errored | cap hits | median s | loops |
|---|---|---|---|---|---|---|---|---|
| v4h2 | 0 | 0 | 0.000-1.000 | 0 | 0 | 0 | nan | 0 |
| v6p | 0 | 0 | 0.000-1.000 | 0 | 0 | 0 | nan | 0 |
| v6p-b | 0 | 0 | 0.000-1.000 | 0 | 0 | 0 | nan | 0 |

| contrast | valid pairs | wins | losses | sign p | cap gap | verdict | no-cap pairs (W/L) |
|---|---|---|---|---|---|---|---|
| v6p vs v4h2 | 0 | 0 | 0 | 1.000 | +0.00 | NO EVIDENCE | 0 (0/0) |
| v6p-b vs v4h2 | 0 | 0 | 0 | 1.000 | +0.00 | NO EVIDENCE | 0 (0/0) |

#### pooled stage 1a + 1b (ids 1-100), arms that ran in both
**pooled stage 1a + 1b (ids 1-100), arms that ran in both: 100 ids, arms v4h2, v6p; A6000 screen (int4 checkpoint, bf16 KV at 0.95, Docker-emulated sandbox, per-arm stretched cap), 1 sample per task per arm, paired, never a Kaggle result.**

| arm | finished | solved | Wilson 95% | empty patch | errored | cap hits | median s | loops |
|---|---|---|---|---|---|---|---|---|
| v4h2 | 50 | 16 | 0.208-0.458 | 7 | 0 | 3 | 222 | 7 |
| v6p | 50 | 14 | 0.175-0.417 | 19 | 2 | 3 | 226 | 9 |

| contrast | valid pairs | wins | losses | sign p | cap gap | verdict | no-cap pairs (W/L) |
|---|---|---|---|---|---|---|---|
| v6p vs v4h2 | 50 | 3 | 5 | 0.727 | +0.00 | NO EVIDENCE | 45 (3/5) |


### P4 A6000 screen RESULT: v5h2 on the public 74 (2026-10-08 11:31 UTC)
**A6000 screen, never a Kaggle result:** int4 checkpoint, bf16 KV at 0.95, the bundle's own (not stretched) budgets, sequential, pace proxy; the A6000 is slower than the L4 model, so a miss is pessimistic.

- solved 29/74 (L4 reference v4h2g: 34/74); keep rule (solved >= 37 and paired wins - losses >= +3 vs eval/kaggle/g4-l4-v4h2g-p312): **DROP**
  `solved 29/74 (base 34/74) | wins 2 losses 7 net -5 | rule: solved >= 37 and net >= +3
won: fastapi_15589 rich_3676
lost: fastapi_11194 fastapi_14616 fastapi_9753 requests_6644 rich_3063 rich_3521 rich_3718
DROP: solved 29 < 37; net -5 < +3`
- helper reachability: 0/74 tasks with a can't-open; cap hits 3; errored rows 0; median task seconds 148; S(1) over clean windows = 1.17; over the whole log 2.29 (3855 calls; 7 of 28 ten-minute windows were contended by another GPU workload and are left out of the clean figure)


### P4 A6000 screen RESULT: v7 on the public 74 (2026-10-08 11:31 UTC)
**A6000 screen, never a Kaggle result:** int4 checkpoint, bf16 KV at 0.95, the bundle's own (not stretched) budgets, sequential, pace proxy; the A6000 is slower than the L4 model, so a miss is pessimistic.

- solved 27/74 (L4 reference v4h2g: 34/74); keep rule (solved >= 37 and paired wins - losses >= +3 vs eval/kaggle/g4-l4-v4h2g-p312): **DROP**
  `solved 27/74 (base 34/74) | wins 2 losses 9 net -7 | rule: solved >= 37 and net >= +3
won: fastapi_15589 rich_3676
lost: fastapi_11194 fastapi_14616 fastapi_5077 fastapi_9753 requests_6644 rich_3067 rich_3506 rich_3718 rich_4077
DROP: solved 27 < 37; net -7 < +3`
- helper reachability: 0/74 tasks with a can't-open; cap hits 4; errored rows 0; median task seconds 108; S(1) over clean windows = 1.14; over the whole log 1.14 (2895 calls; 0 of 17 ten-minute windows were contended by another GPU workload and are left out of the clean figure)

#### P3
not run (no capture)
- 2026-10-08T11:31:56Z | FINALIZE /home/jc/g4/venv/bin/python scripts/a6000/final_summary.py rc=0
- 2026-10-08T11:31:59Z | FINALIZE /home/jc/g4/venv/bin/python scripts/a6000/backup_results.py rc=0
- 2026-10-08T11:31:59Z | FINALIZE bash -c kill $(pgrep -f '[b]ackup_results.py --loop') 2>/dev/null; true rc=0
- 2026-10-08T11:32:17Z | END cleanup (hard stop): nvidia-smi compute apps: none
- DONE 2026-10-08T11:32:20Z (hard stop)
- 2026-10-08T16:26:49Z | LAUNCH stage 1a; HARD STOP 2026-10-09T16:26:49Z
- 2026-10-08T16:29:43Z | step=probe_v7c | EVENT started pid 1316 (restarts so far 0; hard stop in 24.0 h)
- 2026-10-08T16:41:14Z | step=probe_v7c | END done: done=0/4 solved=0
- 2026-10-08T16:41:17Z | step=probe_v7c | POST /home/jc/g4/venv/bin/python scripts/a6000/v7_counters.py /home/jc/g4/runs/p2 rc=0
- 2026-10-08T16:41:52Z | step=v7c_s50 | EVENT started pid 8921 (restarts so far 0; hard stop in 23.8 h)
- 2026-10-08T17:41:55Z | step=v7c_s50 | done=33/50 | solved=10 | empty=1 | errors=0 | median_s=207.9 | cap=0 | gpu=95% | disk_free=890GB | restarts=0
- 2026-10-08T18:08:59Z | step=v7c_s50 | END done: done=50/50 solved=20
- 2026-10-08T18:09:02Z | step=v7c_s50 | POST /home/jc/g4/venv/bin/python scripts/a6000/p2_results_md.py /home/jc/g4/runs/p2 rc=0
- 2026-10-08T18:09:02Z | step=v7c_s50 | POST /home/jc/g4/venv/bin/python scripts/a6000/v7_counters.py /home/jc/g4/runs/p2 rc=0
- 2026-10-08T18:09:06Z | step=v7c_s50 | POST /home/jc/g4/venv/bin/python scripts/a6000/backup_results.py rc=0
- 2026-10-08T18:09:41Z | step=v7c_p4 | EVENT started pid 12151 (restarts so far 0; hard stop in 22.3 h)
- 2026-10-08T19:09:42Z | step=v7c_p4 | done=25/74 | solved=8 | empty=2 | errors=0 | median_s=114.6 | cap=1 | gpu=100% | disk_free=890GB | restarts=0
- 2026-10-08T20:09:45Z | step=v7c_p4 | done=49/74 | solved=18 | empty=5 | errors=0 | median_s=116.3 | cap=3 | gpu=100% | disk_free=890GB | restarts=0
- 2026-10-08T21:09:48Z | step=v7c_p4 | done=72/74 | solved=24 | empty=12 | errors=0 | median_s=127.2 | cap=7 | gpu=100% | disk_free=890GB | restarts=0
- 2026-10-08T21:16:51Z | step=v7c_p4 | END done: done=74/74 solved=25
- 2026-10-08T21:16:54Z | step=v7c_p4 | POST /home/jc/g4/venv/bin/python scripts/a6000/p4_judge.py --out rc=0
- 2026-10-08T21:16:54Z | step=v7c_p4 | POST /home/jc/g4/venv/bin/python scripts/a6000/v7_counters.py /home/jc/g4/runs/p4_v7c rc=0
- 2026-10-08T21:16:58Z | step=v7c_p4 | POST /home/jc/g4/venv/bin/python scripts/a6000/backup_results.py rc=0
- 2026-10-08T21:17:31Z | step=v7c_p3 | EVENT started pid 22792 (restarts so far 0; hard stop in 19.2 h)
- 2026-10-08T22:17:33Z | step=v7c_p3 | done=36/844 | solved=12 | empty=2 | errors=0 | median_s=171.2 | cap=2 | gpu=86% | disk_free=890GB | restarts=0
- 2026-10-08T23:17:39Z | step=v7c_p3 | done=74/844 | solved=16 | empty=3 | errors=0 | median_s=172.7 | cap=8 | gpu=100% | disk_free=890GB | restarts=0
- 2026-10-09T00:17:44Z | step=v7c_p3 | done=115/844 | solved=29 | empty=7 | errors=0 | median_s=167.9 | cap=12 | gpu=100% | disk_free=890GB | restarts=0
- 2026-10-09T01:17:49Z | step=v7c_p3 | done=150/844 | solved=44 | empty=9 | errors=0 | median_s=168.8 | cap=18 | gpu=100% | disk_free=890GB | restarts=0
- 2026-10-09T02:17:54Z | step=v7c_p3 | done=195/844 | solved=72 | empty=12 | errors=0 | median_s=159.1 | cap=23 | gpu=100% | disk_free=890GB | restarts=0
- 2026-10-09T03:18:00Z | step=v7c_p3 | done=233/844 | solved=81 | empty=16 | errors=0 | median_s=160.9 | cap=32 | gpu=0% | disk_free=890GB | restarts=0
- 2026-10-09T04:18:05Z | step=v7c_p3 | done=270/844 | solved=89 | empty=22 | errors=0 | median_s=163.0 | cap=38 | gpu=100% | disk_free=890GB | restarts=0
- 2026-10-09T05:18:10Z | step=v7c_p3 | done=306/844 | solved=101 | empty=27 | errors=0 | median_s=160.2 | cap=45 | gpu=100% | disk_free=889GB | restarts=0
- 2026-10-09T06:18:15Z | step=v7c_p3 | done=341/844 | solved=114 | empty=28 | errors=0 | median_s=164.5 | cap=48 | gpu=100% | disk_free=890GB | restarts=0
- 2026-10-09T07:18:21Z | step=v7c_p3 | done=382/844 | solved=133 | empty=31 | errors=0 | median_s=163.0 | cap=51 | gpu=100% | disk_free=890GB | restarts=0
- 2026-10-09T08:18:26Z | step=v7c_p3 | done=430/844 | solved=155 | empty=35 | errors=1 | median_s=155.8 | cap=55 | gpu=100% | disk_free=890GB | restarts=0
- 2026-10-09T09:18:31Z | step=v7c_p3 | done=471/844 | solved=174 | empty=37 | errors=1 | median_s=156.0 | cap=59 | gpu=100% | disk_free=890GB | restarts=0
- 2026-10-09T10:18:37Z | step=v7c_p3 | done=511/844 | solved=186 | empty=39 | errors=1 | median_s=155.5 | cap=64 | gpu=100% | disk_free=890GB | restarts=0
- 2026-10-09T11:18:42Z | step=v7c_p3 | done=555/844 | solved=205 | empty=43 | errors=1 | median_s=154.2 | cap=71 | gpu=100% | disk_free=890GB | restarts=0
- 2026-10-09T12:18:48Z | step=v7c_p3 | done=599/844 | solved=222 | empty=44 | errors=1 | median_s=150.8 | cap=75 | gpu=98% | disk_free=890GB | restarts=0
- 2026-10-09T13:18:53Z | step=v7c_p3 | done=644/844 | solved=243 | empty=50 | errors=1 | median_s=150.8 | cap=80 | gpu=100% | disk_free=890GB | restarts=0
- 2026-10-09T14:18:59Z | step=v7c_p3 | done=677/844 | solved=252 | empty=51 | errors=1 | median_s=152.8 | cap=88 | gpu=100% | disk_free=889GB | restarts=0
- 2026-10-09T15:19:05Z | step=v7c_p3 | done=720/844 | solved=269 | empty=58 | errors=1 | median_s=151.8 | cap=93 | gpu=100% | disk_free=889GB | restarts=0
