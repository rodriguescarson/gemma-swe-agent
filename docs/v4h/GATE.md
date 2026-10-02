# v4h ship gate (pre-registered 2026-10-02 09:35 IST, before the smoke result exists)

v4h = submissions/v4 plus ONE variable: the edit channel. `edit_file` is removed from the fixer and verifier; edits go
through `python3 /tmp/swe/edit.py` (stdlib SEARCH/REPLACE or line-range helper, installed into the sandbox's rewritten
tmp so it is reachable where v4's helpers were not). The locator, eval_config, sampling and the other helpers are
byte-identical to v4 (tests/test_v4h_bundle.py).

Why this variable: on the faithful Kaggle 4xL4 run of v4 (2026-09-28), 152 of 439 `edit_file` calls (35%) failed
"old_string not found"; 18 of 74 tasks hit at least one failure (mean 8.4 per affected task), 5 of those 18 solved.
On the Pallets OpenRouter race (2026-10-01): 32 of 71 (45%), 11 tasks, 1 solved. v10.1's helper edit on the same Pallets
tasks: 8 of 63 (13%). Test-file writes by v4: 0 in both runs, so write protection is NOT part of v4h.

## Gate (all must hold), read from eval/runs/or_smoke_v4h (10 Pallets dev tasks, v4 vs v4h, same provider, same hour)

1. Helper reachable: no `can't open file` / `No such file` on any `python3 /tmp/swe/edit.py` call, in 10 of 10 tasks.
2. Helper edit error rate under 15%: (NO MATCH + AMBIGUOUS + ERROR + SYNTAX ERROR + REFUSED outputs) / edit.py calls.
3. Zero crash rows (an `error` that is not the 5-minute timeout) in the v4h arm.
4. Sanity, not a gate: v4h solved >= v4 solved - 1 on the 10 tasks (10 tasks cannot rank bundles; this only catches a
   bundle that is broken outright).

PASS: v4h takes the 2026-10-03 00:01 UTC slot (05:31 IST) as sub9, then its second read on 2026-10-04.
FAIL: the 2026-10-03 slot re-reads the better of v4 / v10.1 (decided by sub8's score); v4h is fixed and gated again.

Result (appended after the smoke, never edited above this line):

### Smoke 1 (2026-10-02 09:45-10:11 IST, eval/runs/or_smoke_v4h, parasail/fp8 averaging 8-10 s/call): GATE FAIL

v4h 0/10 solved, v4 0/10 (8 of 10 capped in both arms: the provider was 2x slower than the night before, so this
smoke says nothing about solves). Gate metrics: 19 edit.py calls in 4 tasks, helper error rate 5.3% (PASS), 6 calls
"can't open file" in 3 tasks (FAIL 1), 1 non-timeout crash (FAIL 3). v4 had 2 non-timeout crashes of its own.

Reading of the two failures (traces, pl_v4h/traces):
- Every "can't open file" happened BEFORE any `run_skill_script(install.py)` in that task; after an install, 12 of 12
  edit.py calls in the same tasks returned OK or a clean helper verdict. Causes: the locator skipped install (as v4's
  does in ~30% of tasks: 52 install calls over 74 tasks on L4), and one locator sent the skill name with literal quotes
  (`SKILL_NOT_FOUND`). So gate 1 measured the model's compliance with a locator step v4 shares, not the helper.
- The crash: the model emitted the whole heredoc command as a tool NAME ("Tool 'python3 /tmp/swe/edit.py ...' not
  found"), the unknown-tool class that killed race 2 round 1 and that v10.1 prevents with one prompt line.

## Addendum 2026-10-02 10:20 IST (the original gate above stays as written)

Changes to the bundle, both prompt-only, both in the fixer and verifier: (a) "your first tool call is always
run_skill_script(install.py)"; (b) "helpers are never tool names: run every python3 /tmp/swe/... line through
run_command". The locator is still byte-identical to v4.

Gate 1 is replaced by: (1a) zero "can't open file" on edit.py calls AFTER an install in the same task, and (1b) the
fixer's first tool call is `run_skill_script` in at least 9 of 10 tasks. Gates 2-4 are unchanged. Smoke 2 is run under
the same provider pin; if the provider is again slower than 6 s/call on average, the solve numbers are reported but not
read.

### Smoke 2 (2026-10-02 10:12-10:36 IST, eval/runs/or_smoke2_v4h, parasail/fp8 at 6-7 s/call, bundle commit 352583a): GATE PASS

v4h: 21 edit.py calls in 8 tasks, 0 "can't open file" before or after install, fixer's first call was install in
10/10 tasks, helper error rate 0.0%, 0 crash rows (v4: 1), empty patches 1 (v4: 4). Solved 2/10 vs v4 3/10 (paired 1-2,
both 1): reported, not read (provider still 2x slower than L4-paced). Ships as sub9, 2026-10-03 00:01 UTC, notebook
g4agent-v4h version 2.

### 2026-10-02 17:00 IST: sub9 DISARMED before it fired

Carson's rule from this afternoon: nothing is submitted until the candidate has run on all 74 public tasks with every
case handled. The 10-task smoke stays a breakage check, not a ship gate. v4h's ladder is now: v4 vs v4h on all 74 public
tasks through OpenRouter/Docker (scripts/or_race_public.sh, gate metrics on every task), then the Kaggle 4xL4 faithful
run of v4h on 74 (Saturday quota) against v4's 29/74, then a slot.
