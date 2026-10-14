# forty_two: Textualize/rich never-solved tasks, one line per task

One line per task, in the order the tasks were worked. Each line is UTC time | id | root cause | feasible in 5 min | general lever | F2P count | gold passes clean.
- Per-task dossiers: `docs/forty_two/tasks/<id>.md`.
- Ground truth and per-run time accounting: `docs/forty_two/ground_truth/<id>.json`, written by `docs/forty_two/ground_truth/rich_tools/gt_rich.py` and `trace_rich.py`.
- Clean environment: Python 3.12, pytest 8.4.2, Pygments 2.20.0, markdown-it-py 4.0.0 (the Kaggle freeze).
- Box runs: p4 (v5h2), p4_v7, p4_v7c, p4_v7d, p4_b1024 (v12-b1024), p4_v0t2 (v0-think).

- 2026-10-14T12:41Z | rich_3718 | WRONG_SEMANTICS (sibling subtitle site missed; b1024 EDIT_TOOL_FAILURE malformed args; v7/v7d wrong line + edit loop) | yes (v0-think solved on box 207 s; 9/12 L4 runs) | fail-first repro + sibling sweep of the replaced expression + malformed-call breaker | F2P 1 | gold passes yes
- 2026-10-14T12:43Z | rich_3777 | WRONG_SEMANTICS (only TTY_INTERACTIVE=0 implemented; the =1 force-on follows the TTY_COMPATIBLE sibling the issue names; b1024 broke Console with a setter-less property, untested; v7d 46 identical greps) | yes (v0-think solved on box 289 s; 4/12 L4) | mirror the named sibling option in source+tests; run the module's test file once; identical-command breaker | F2P 1 | gold passes yes
