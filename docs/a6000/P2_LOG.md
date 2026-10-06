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
