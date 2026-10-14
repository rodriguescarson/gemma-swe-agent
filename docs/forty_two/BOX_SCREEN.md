# Box screen for v13 (pre-registered; written 2026-10-14 IST, before any v13 result exists anywhere)

Not sent anywhere. The main session decides whether and when to run it.

## What runs

- **Bundle:** `submissions/v13` at commit `f4b58a879b03b4656618dce6c796b2e72ba6963d` (git tree of submissions/v13:
  `bd5eabb68534eec215c7b2e01565e11c6bc13236`; check with `git rev-parse <commit>:submissions/v13`). It is v12-b1024 plus two
  levers (docs/forty_two/LEVERS.md): (1) edit_file and write_file dropped, edits through a run_command python heredoc
  (agent.yaml, prompt step 3); (2) per-command timeout 180 -> 60 s (eval_config.yaml). Sampling, thinking (on, budget 1,024),
  the 5-minute / 40-call / 150-turn budget and every other prompt line are v12-b1024's. `scripts/validate.py submissions/v13`
  passes; tests/test_v13_bundle.py, tests/test_v13_leakage.py, tests/test_forty_two_evidence.py and
  tests/test_forty_two_screen_read.py pass (25 tests).
- **Comparator:** p4_b1024 (v12-b1024 on the same 74, same box, same pace proxy, 28/74, 13 Oct). No new control run.
- **How:** exactly like p4_b1024: `scripts/a6000/run_eval.py submissions/v13 <out> --ids data/forty_two_screen_order.txt`
  (subprocess sandbox, sequential, the bundle's own budgets, through scripts/a6000/pace_proxy.py with its log), one sample.
  The ids file lists the 42 never-solved ids first (data/never_solved_box5_ids.txt order), then the other 32, so the
  42 are read first (~3.7 h) and the full 74 finish in ~6.3 h (p4_b1024 summed 5.15 h; v13 should not be slower). The run is
  resumable by id.
- **Bring back:** `eval/a6000/results/p4_v13/{results.jsonl, results/traces/}`, `eval/a6000/results/p4_v13_proxy.jsonl`, and
  the bundle commit the box actually ran (the ARM file or the log line).

## The rule, fixed now (applied by `python scripts/forty_two/screen_read.py eval/a6000/results/p4_v13`)

1. **INVALID** (no reading; fix and rerun): fewer than 74 ids, any crash or errored row (scripts/box_p4_gate.py's definitions),
   or the traces show v12-b1024's mechanics: an edit_file/write_file call that succeeded (the tool was declared) or a run_command
   that lasted >= 61 s and returned (the 60 s limit was not applied).
2. **PASS**: solved >= 28 of 74, paired net vs p4_b1024 (tasks only v13 solves minus tasks only p4_b1024 solves) >= +2, and at
   least 2 of the 42 solved.
3. **FAIL**: solved <= 25, or paired net <= -3.
4. **NO EVIDENCE**: anything else.

Reported beside the verdict, not gated: the exact two-sided sign test on the discordant pairs, cap hits (p4_b1024: 33),
malformed-parameter replies from any tool (p4_b1024: 84; expected now: 0 except a rare run_command), attempts to call a dropped
tool (they come back as an error reply through the harness's ToolErrorPlugin), template edits and how many the template refused,
and the per-lever flips below. With one sample per arm a +2 net is inside run-to-run noise (p4_b1024 and p4_v0t2 differ on 12
tasks), so PASS means "worth a Kaggle L4 read or a slot", not "proven".

What each verdict leads to (proposed, the main session decides): PASS -> v13 is the line for the next L4 read / submission
decision; NO EVIDENCE -> read the counters (did the malformed and hang seconds disappear?) before spending a second sample; FAIL
-> read the traces of the losses first (template refusals, retries), v12-b1024 stays the line.

## Expected before any result (per lever)

| lever | should flip (of the 42) | why | expected |
|---|---|---|---|
| 1 edits through run_command | rich_3718 | right fix written at 85 s on p4_b1024, then 21 malformed calls (226 s); p4_v0t2 solved it without the loop; 9/12 L4 | likely |
| 1 | rich_4075 | right repro and cause by 43 s, then 3 malformed edits and the 40-call budget ran out (cloud dossier) | maybe |
| 1 | fastapi_14616, fastapi_9753 | 153 s and 148 s lost to malformed loops; also fix-quality causes (cloud dossiers) | maybe |
| 2 per-command timeout 60 s | rich_3480, rich_4006, rich_3052 | 161-209 s lost per task to infinite-loop repros; 60 s returns 100-240 s | maybe |
| 2 | fastapi_14258 | time back (181 s) but HIDDEN_SPEC (exact 95-character message) | no |

Total expected on the 42: 1 to 3. On the 74: about p4_b1024's 28, plus those, minus noise. Lever 1 should also protect tasks
p4_b1024 solved despite malformed loops (rich_3454 98 s, rich_3043 80 s, fastapi_14463 70 s, fastapi_11194 17 s, rich_3067 10 s
lost there); a loss among them points at the template, not at chance. Known cost: a solved task whose edits pass through an
uncompilable state (fastapi_14458 on p4_b1024) needs one retry per such edit.

## Box caveats (why the box can under-read v13)

- requests_6644 cannot flip on the box: the box sandbox imports the host venv's requests, not the workspace's (cloud dossier
  requests_6644); it is solved on 12 of 12 L4 runs.
- The A6000 is ~38 s per task slower than the L4 model on the 42 (TIMING.md row 6), and a task's call cut by the cap keeps the GPU
  busy into the next task (the proxy does not cancel it). Time-bound flips are under-counted, not over-counted.
- On the box the per-command timeout is also the verification timeout (swegemma verification.py). Non-hanging verification on the
  box takes at most 6.9 s, so 60 s should not bite; any exit-124 row on a non-hanging patch is a lever 2 problem to report (the
  fallback is 90 s).
