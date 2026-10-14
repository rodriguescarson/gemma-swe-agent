# fastapi_14258: a clear error when a router is included into itself

Sources:
- `docs/forty_two/ground_truth/fastapi_14258.json`: the ground truth, from `gt_fastapi.py`.
- `docs/forty_two/ground_truth/fastapi_tools/trace_timing/fastapi_14258.json`: the per-run timing, from `tr_fastapi.py`.

"Measured" means taken from those files. "Inferred" means a reading of them.

## Problem

- **Issue (PR text):** "Show a clear error on attempt to include router into itself". The rest is links to discussions and an earlier PR.
  - It gives no exception type and no message.
- **Gold:** `fastapi/routing.py`, 1 hunk, +4 lines at the top of `APIRouter.include_router`:
  ```python
  assert self is not router, (
      "Cannot include the same APIRouter instance into itself. "
      "Did you mean to include a different router?"
  )
  ```
- **FAIL_TO_PASS (1, measured):** `tests/test_router_circular_import.py::test_router_circular_import`. It runs `pytest.raises(AssertionError, match="Cannot include the same APIRouter instance into itself. Did you mean to include a different router?")` around `router.include_router(router)`. No PASS_TO_PASS.

## Constraints

- **Budget:** 5 minutes. 40 calls (v12-b1024, v0-think) or 70 calls (older bundles). 180 s per command.
- **Hidden spec:**
  - The exception *type* is guessable from local convention: the other checks in `include_router` are `assert`s.
  - The *message* is not guessable. The `match=` regex is the full 95-character sentence. No run, box or L4, produced it.
- **The bug's own repro hangs.** Including a router *that has routes* into itself loops forever: `include_router` iterates `router.routes` while appending to `self.routes`, and they are the same list.
  - With an empty router it returns at once. p4 and v7d both saw `Success` and `0` first.
  - Measured at base: `gtimeout 5 python -u -c "r=APIRouter(); r.include_router(r); print('empty ok', len(r.routes)); @r.get('/t') ...; r.include_router(r)"` printed `empty ok 0`, then exit 124. The loop is `for route in router.routes:` (routing.py:1411).
  - Any unbounded repro with a route therefore burns the harness's per-command limit: 180 s in these bundles (`timeout_seconds: 180` in `eval_config.yaml`).
- **Gold in a clean environment: yes (measured).** Before: 1 failed. After: 1 passed. The Kaggle oracle resolves it too (8.8 s).
- **Test cost (indicative: macOS arm64, Python 3.12.14):**

  | Step | Time |
  |---|---|
  | install | 0.4 s |
  | the F2P test | 0.53 s |
  | full `tests/` | 4.9 s (1,047 passed, 294 errors: modules missing from the parity env) |

## What the six box runs did

| run (bundle) | secs / calls | model s (calls) | tools s | final state | clean env |
|---|---|---|---|---|---|
| p4 (v5h2) | 254 / 70 (budget) | 243.1 (79) | 3.4 | **empty** | fails |
| p4_v7 (v7) | 84 / 23 | 75.2 (28) | 2.5 | `raise FastAPIError("A router cannot be included into itself")` | fails (type and text) |
| p4_v7c (v7c) | 116 / 31 | 108.3 (36) | 2.3 | the same as v7 | fails |
| p4_v7d (v7d) | 302 / 13 (time cap) | 31.6 (14) | **182.4** (+84.7 cut off at the cap) | **empty** | fails |
| p4_b1024 (v12-b1024) | 305 / 15 (time cap) | 119.5 (18) | **181.4** | `raise FastAPIError("Cannot include a router in itself")` | fails |
| p4_v0t2 (v0-think) | 305 / 22 (time cap) | 114.0 (22) | **181.3** | `raise FastAPIError("You cannot include a router into itself.")` + 2 repro files | fails |

Measured from the timelines:

- **p4.**
  - Located `include_router` by t=31.
  - The fixer sent the same `edit.py` SEARCH/REPLACE **46 times** (t=54 to 241). Each time the helper answered `NO CHANGE: the replacement equals the current text`. That is 170.2 s of model time and 1.7 s of tool time.
  - It hit the 70-call budget with no edit.
- **p4_v7 and p4_v7c.**
  - Fixed at t=40 to 50 with `FastAPIError` and a message of their own.
  - v7 checked with `timeout 30 python3 -c ...` (0.25 s) and submitted at t=84. These are the fastest runs and the right fix in all but the hidden message.
- **p4_v7d.**
  - Its 5th repro (t=32) gave the router a route. It ran without a timeout and hit the 180 s limit (180.7 s).
  - The retry at t=218 (a thread wrapper) was cut off by the session cap after 84 s. **265 s of 302 were spent waiting on the hang.**
- **p4_b1024.**
  - Read `include_router` by t=18. Its first `write_file` repro (empty router) reported "No error raised".
  - The second, with routes, ran `python3 reproduce_issue.py` at t=46 with no `timeout`: 180.7 s.
  - Then two `edit_file` calls lost `old_string` (`mandatory input parameters are not present`). The edit landed at t=258 and the repro passed at t=260. It never submitted, and the fallback diff was graded.
- **p4_v0t2.** The edit was in place early. At t=84 `python3 test_duplicates.py`, a repro it wrote, hung for 180.7 s. It re-ran its repro at t=299 and was capped.
- **L4.** 0 of 12 L4 runs with 74 rows solved it. Of the traced ones, e74_v2 also used its own message. e74_v3 made 46 failing `edit_file` calls and ended on the 80-turn budget.

**Where the time went (measured, six runs, 1,366 s):**

| | Seconds |
|---|---|
| model calls | 691.7 |
| **tool runtime** | **553.3** (543.4 of it is three 180 s command timeouts) |
| tail cut off by the cap | 90.3 |
| other (harness) | 30.7 |

This is the one task in the batch where tools, not the model, used most of the time.

## Root cause, feasibility, lever

- **Root cause: HIDDEN_SPEC.** The test pins an exact sentence that appears only in the test and the gold. Every run that edited put the check in the right place, with its own message.
  - Separately, HANG_INFINITE_LOOP cost three runs 180 s each: the bug's repro is an infinite loop. EDIT_TOOL_FAILURE cost p4 its budget: 46 identical "no change" edits.
  - This agrees with the old diagnosis (HIDDEN_SPEC, feasible no) and adds the hang measurement for the current bundles.
- **Feasible in 5 minutes: no.** The message is unguessable. Any fix scores 0 regardless of time.
- **General levers.** These don't flip this task, but they matter elsewhere:
  1. **Lower the per-command timeout.** In `eval_config.yaml` (declarative, applies to every task), `timeout_seconds: 180` becomes 30 to 60. Alternatively, a prompt rule: prefix every `python`/`pytest` run with `timeout 20`.
     - Here it would have returned 120 to 150 s to each of v7d, b1024 and v0t2.
     - Any repo whose bug is a hang or a slow loop has the same failure mode. rich has three such tasks (old diagnosis, HANG_INFINITE_LOOP).
     - Risk: a test suite slower than the cap. My clean full-suite runs for these fastapi tasks take 4 to 9 s (indicative).
  2. **Treat "NO CHANGE" and identical-error replies as a stop signal**: re-read the lines, then change the SEARCH block. This applies to helper-based bundles. The current line uses `edit_file`, but the same rule covers b1024's dropped-argument retries.
  3. **Match the module's existing error idiom** (`assert` here). It is cheap and right in kind, but it would not have rescued this task.
