# fastapi_14487: docs example re-raising validation errors must not echo `str(exc)`

Sources:
- `docs/forty_two/ground_truth/fastapi_14487.json`: the ground truth, from `gt_fastapi.py`.
- `docs/forty_two/ground_truth/fastapi_tools/trace_timing/fastapi_14487.json`: the per-run timing, from `tr_fastapi.py`.

"Measured" means taken from those files. "Inferred" means a reading of them.

## Problem

- **Issue (title only, repeated twice):** "Update docs about re-raising validation errors, do not include string as is to not leak information".
- **Gold:** `docs_src/handling_errors/tutorial004.py`, 1 hunk, +5/-2 lines. The `RequestValidationError` handler builds `"Validation errors:"` plus one line per error, `"\nField: {loc}, Error: {msg}"`, instead of returning `str(exc)`.
- **FAIL_TO_PASS (1, measured):** `tests/test_tutorial/test_handling_errors/test_tutorial004.py::test_get_validation_error`. GET `/items/foo` must return 400, and the text must contain `Validation errors:` and `Field: ('path', 'item_id')`.
  - **PASS_TO_PASS (3):** `test_get`, `test_get_http_error`, `test_openapi_schema`.

## Constraints

- **Budget:** 5 minutes. 40 calls (v12-b1024, v0-think) or 70 calls (older bundles). 180 s per command.
- **Hidden spec:**
  - The two exact substrings (`Validation errors:`, `Field: ('path', 'item_id')`) exist only in the updated test. Any other safe message fails.
  - The file is findable with one search: `str(exc)` occurs in `docs_src` only at `handling_errors/tutorial004.py` (b1024's `grep -r "str(exc)" docs_src`, measured in its trace).
  - The repo's own `KNOWN_LOCATE_MISS` list (tests/v10_support/tasks.py) already marks this task's location as hard for a locator.
- **Gold in a clean environment: yes (measured).** Before: 1 failed, 3 passed. After: 4 passed. The Kaggle oracle resolves it too (8.0 s).
- **Test cost (indicative):**

  | Step | Time |
  |---|---|
  | install | 0.4 s |
  | the F2P test | 0.66 s |
  | the touched file | 0.74 s |
  | full `tests/` | 4.5 s |

## What the six box runs did

| run (bundle) | secs / calls | model s (calls) | tools s | final patch | clean env |
|---|---|---|---|---|---|
| p4 (v5h2) | 94 / 23 | 85.0 (28) | 1.5 | `docs_src/custom_request_and_route/tutorial002*.py` (6 variants), wrong file | F2P fails, P2P pass |
| p4_v7 (v7) | 95 / 24 | 85.2 (29) | 2.5 | `custom_request_and_route/tutorial002*` plus `handling_errors/tutorial004.py` returning `"Validation Error"` | F2P fails (`'Validation Error'`) |
| p4_v7c (v7c) | 155 / 53 | 144.4 (59) | 3.4 | the same as v7 | F2P fails (`'Validation Error'`) |
| p4_v7d (v7d) | 101 / 28 | 91.5 (33) | 2.5 | `custom_request_and_route/tutorial002*` plus `handling_errors/tutorial005.py` (wrong files) | F2P fails |
| p4_b1024 (v12-b1024) | 192 / 39 | 182.7 (43) | 1.0 | `handling_errors/tutorial004.py` → `PlainTextResponse("Validation Error", 400)`: right file, wrong text | F2P fails |
| p4_v0t2 (v0-think) | 278 / 28 | 270.2 (31) | 0.3 | `custom_request_and_route/tutorial002*` plus `handling_errors/tutorial005.py` (wrong files) | F2P fails |

Measured from the timelines:

- **The `custom_request_and_route/tutorial002` family** is the other docs example that turns a `RequestValidationError` into a response. 5 of 6 runs edited it, either as their only edit or alongside another handling_errors file (v7 and v7c also changed tutorial004; v7d and v0t2 changed tutorial005).
- **p4_b1024.**
  - 33 searches over `docs` and `docs_src` ("re-raise", "leak information", `detail=str(`, ...), t=9 to 146.
  - At t=79 it **read the right file** and moved on.
  - A 28.1 s compaction came at t=146. At t=178, `grep -r "str(exc)" docs_src` returned the one hit.
  - It edited at t=185 and submitted at t=186, with `"Validation Error"`.
- **p4_v0t2.** Read `handling_errors/tutorial004.py`, `005` and `006`, but edited `custom_request_and_route`. Its model calls ran to 35.6 s, plus a 31.8 s compaction.
- **v7c** repeated `grep -r "detail=" docs_src/ | grep "e"` 11 times.
- **L4.** 0 of 12 L4 runs with 74 rows solved it. Both traced runs (e74_v2, e74_v3) finished in under 60 s with other messages.

**Where the time went (measured, six runs, 914.1 s):**

| | Seconds |
|---|---|
| model | 859.0 |
| tools | 11.2 |
| other | 43.9 |

None of the runs hit a cap. The time was not the constraint.

## Root cause, feasibility, lever

- **Root cause: HIDDEN_SPEC.** The required message format exists only in the updated test.
  - The location problem (5 of 6 runs edited a sibling docs example) is real but secondary. b1024 found the right file and still fails on the text.
  - This agrees with the old diagnosis and adds the location detail.
- **Feasible in 5 minutes: no.** No reading of the one-line title yields `Validation errors:` / `Field: (...)`.
- **Lever: none realistic for the hidden text.**
  - A general locate habit would have found the file at once: **grep the exact code idiom the issue describes** (here "include string as is", i.e. `str(exc)`) before searching prose words. It does not change this task's score.
