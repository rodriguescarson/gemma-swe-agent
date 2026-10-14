# Per-task lever queue (pre-registered 2026-10-14 ~23:45 IST, before any queue row exists)

Owner's instruction (14 Oct): divide the 42 never-solved tasks, solve each individually until it passes, then merge.
The per-task agents wrote docs/forty_two/queue/<id>.json for all 33 tasks they assessed (24 runnable, 9 not feasible; the 9
unwinnable fastapi/requests tasks have no queue file). Each runnable task names one bundle = submissions/v13 plus ONE rule.

## What runs on the box (after p4_v13's END)
- Plan: data/forty_two_queue/plan.json, made by `python scripts/forty_two/queue_plan.py docs/forty_two/queue --override
  rich_4079=submissions/v13_title_ident --write data/forty_two_queue` (rich_4079 moved from v13_titlegrep to v13_title_ident: the
  same lever, the shorter plain-English wording without regex syntax; v13_titlegrep stays the fallback if v13_title_ident
  passes neither task).
- 24 tasks in 15 bundles, k = 3 samples each, 45 steps, interleaved: sample 1 of every bundle, then sample 2, then sample 3.
  Step = `scripts/a6000/run_eval.py submissions/<bundle> ~/g4/runs/q_<bundle>_s<k> --ids data/forty_two_queue/<bundle>.txt`
  through the pace proxy, the bundle's own budgets, sequential. 72 task runs, about 5.5 h.
- Results come back to eval/a6000/results/q_<bundle>_s<k>/ with traces.

## The rule (applied by `python scripts/forty_two/queue_read.py eval/a6000/results --plan data/forty_two_queue/plan.json`)
- Task PASS: solved in >= 2 of its 3 samples, no errored sample (box_p4_gate.py's definition). FAIL: fewer. INCOMPLETE: a sample
  missing or errored (rerun that sample; not a fail).
- Lever ACCEPT: at least one of its tasks PASSES and none is INCOMPLETE. REJECT: none passes. One lever per task-set, so a pass
  is attributable to that lever on top of v13.
- p4_v13's own rows (v13 alone, 1 sample) are reported beside each task (v13 solved fastapi_9753 and rich_3718 there), not counted.

## Then merge
v14 = v13 + every ACCEPTed lever's rule, built as its own bundle with tests first (each accepted rule present, nothing else
changed, the leakage test, validate.py). v14 then gets a full 74 read on the box with a rule written before that run (at
least: every id, 0 crash, 0 errored; solved and paired net vs p4_b1024 reported; text-leak rows counted).

## Known limits
- k = 3 detects a large lift only: a task the base solves 10% of the time passes by chance 2.8% of the time per task; with 24
  tasks about 0.7 false passes are expected. The v14 full read is the check.
- The box's Pygments version is unknown (rich_4079 and rich_3782 gold depend on it); the box records it before the queue.
- requests_6644 is not in the queue (box-only artefact).

## Amendment (2026-10-15 00:20 IST, after p4_v13's 42 and before any queue row)
p4_v13 (v13 alone, 1 sample) solved 4 of the 42: fastapi_9753, rich_3718, rich_3777, rich_4075. Three of them are queued on a
lever bundle (v13_grepsites, v13_modtests, v13_warnedit), so a pass there could be v13's, not the lever's. Change: the queue
also runs v13 alone on all four (k = 3; rich_3718 was already on v13), 9 more task runs (~45 min), and queue_read credits a
lever only for tasks where v13 alone does NOT also pass (`--base v13`, written into plan.json). Regenerated with
`queue_plan.py docs/forty_two/queue --override rich_4079=submissions/v13_title_ident --control
v13=fastapi_9753,rich_3718,rich_3777,rich_4075 --base v13 --write data/forty_two_queue`. Test first
(test_controls_add_base_bundle_samples_and_a_lever_gets_no_credit_where_the_base_also_passes). 27 task slots, 81 task runs,
about 6.2 h.
