# fastapi_15800: `app.frontend("/", directory="dist")` and `router.frontend(...)`

Sources:
- `docs/forty_two/ground_truth/fastapi_15800.json`: the ground truth, from `gt_fastapi.py`.
- `docs/forty_two/ground_truth/fastapi_tools/trace_timing/fastapi_15800.json`: the per-run timing, from `tr_fastapi.py`.

"Measured" means taken from those files. "Inferred" means a reading of them.

## Problem

- **Issue:** the title only, inside an empty PR template: "Add support for `app.frontend("/", directory="dist")` and `router.frontend("/", directory="dist")`".
- **Gold:** 8 files, 20 hunks, +649/-5 lines.
  - Six `docs_src/frontend/tutorial00N_py310.py` examples.
  - `FastAPI.frontend` and `APIRouter.frontend` with directory serving, an `index.html` fallback, low-priority routes, router-prefix handling, a fallback validation, and websocket and method handling.
- **FAIL_TO_PASS (60, measured):** every test in the new 858-line `tests/test_frontend.py`. The old diagnosis counted 47; the parametrised total is 60. No PASS_TO_PASS.

## Constraints

- **Budget:** 5 minutes. 40 calls (v12-b1024, v0-think) or 70 calls (older bundles). 180 s per command.
- **Hidden spec:** the behaviour of all 60 cases: fallback rules, error types, priority and path semantics. The title gives only the call shape.
- **Gold in a clean environment: yes (measured).** Before: 60 failed. After: 60 passed. The Kaggle oracle resolves it too (11.1 s).
- **Test cost (indicative):**

  | Step | Time |
  |---|---|
  | install | 0.4 s |
  | the 60 F2P tests | 0.81 s |
  | full `tests/` | 6.4 s |

## What the six box runs did

| run (bundle) | secs / calls | model s (calls) | tools s | final patch | clean env (of 60) |
|---|---|---|---|---|---|
| p4 (v5h2) | 164 / 70 (budget) | 148.0 (76) | 8.4 | `frontend` on app and router, mounting a static directory | 13 pass |
| p4_v7 (v7) | 115 / 70 (budget) | 100.9 (76) | 5.6 | a stub on `FastAPI` only | 0 pass (`AttributeError`) |
| p4_v7c (v7c) | 125 / 70 (budget) | 113.7 (76) | 5.7 | empty | 0 pass |
| p4_v7d (v7d) | 122 / 70 (budget) | 108.2 (76) | 5.9 | empty | 0 pass |
| p4_b1024 (v12-b1024) | 306 / 32 (time cap) | 288.9 (33) | 2.8 (+11.7 cut off at the cap) | app and router `frontend` | **17 pass** |
| p4_v0t2 (v0-think) | 288 / 28 | 278.7 (31) | 1.8 | app and router `frontend` | 13 pass |

- **The v7 family spent its 70-call budgets on identical searches** for a method that does not exist yet:
  - v7: `git grep -n "def frontend"` 54 times.
  - v7c: `git grep -n "def " | grep "frontend" || true` 58 times.
  - v7d: the same pipeline 59 times.
- **b1024 and v0t2** wrote real implementations, with 10 and 7 python checks respectively. Both stayed far from the 60-case behaviour. Their prompts reached about 14.7k tokens, and both had a 27 to 36 s compaction.
- **L4:** 0 of 12 L4 runs with 74 rows solved it.

**Where the time went (measured, six runs, 1,119.5 s):**

| | Seconds |
|---|---|
| model | 1,038.4 |
| tools | 30.2 |
| tail cut off by the cap | 11.7 |
| other | 39.2 |

## Root cause, feasibility, lever

- **Root cause: FEATURE_TOO_LARGE.** A 649-line feature on a title-only issue, whose semantics are defined by 60 hidden tests.
  - This agrees with the old diagnosis, with the F2P count corrected to 60.
- **Feasible in 5 minutes: no.** The best box patch passes 17 of 60, and scoring is binary.
- **Lever: none realistic for the task.** The general lesson is the same as fastapi_13920: a search for a symbol the issue asks you to *create* returns nothing, and repeating it burns the budget. v7, v7c and v7d each lost 54 to 59 calls this way.
