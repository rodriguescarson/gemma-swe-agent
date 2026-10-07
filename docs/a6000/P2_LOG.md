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
