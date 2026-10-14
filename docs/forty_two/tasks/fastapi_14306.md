# fastapi_14306: endpoint metadata in validation-error tracebacks

Sources:
- `docs/forty_two/ground_truth/fastapi_14306.json`: the ground truth, from `gt_fastapi.py`.
- `docs/forty_two/ground_truth/fastapi_tools/trace_timing/fastapi_14306.json`: the per-run timing, from `tr_fastapi.py`.

"Measured" means taken from those files. "Inferred" means a reading of them.

## Problem

- **Issue (a long PR text with before/after examples).**
  - `str()` of `RequestValidationError`, `ResponseValidationError` and `WebSocketRequestValidationError` should end with the endpoint's file, line and function, plus `METHOD /path`.
  - The context is extracted once per endpoint and cached. It is not sent to clients.
  - The examples print `1 validation error:` in the singular.
- **Gold:** 2 files, 12 hunks, +121/-16 lines.
  - `exceptions.py`: an `EndpointContext` TypedDict. `ValidationException.__init__(errors, *, endpoint_ctx=None)`. `_format_endpoint_context()`: either `File "...", line N, in func` plus `    METHOD /path`, or `Endpoint: <path>` when only the path is known. A shared `__str__` with singular/plural handling. The `endpoint_ctx` kwarg on all three subclasses.
  - `routing.py`: a cached per-endpoint context extractor, plus `endpoint_ctx=` passed at every raise site in request, response and websocket handling.
- **FAIL_TO_PASS (7, measured):** `tests/test_validation_error_context.py`.
  - **5 integration tests:** request, response, websocket, sub-app request and sub-app websocket. Each asserts the function name and the route path are in `str(exc)`.
  - **2 unit tests:**
    - `RequestValidationError(errors, endpoint_ctx={"path": "GET /api/test"})` must contain `Endpoint: GET /api/test`.
    - `RequestValidationError(errors, endpoint_ctx={})` must contain `1 validation error:`, and contain neither `Endpoint` nor `File "`.
  - Before the fix all 7 fail. No PASS_TO_PASS.

## Constraints

- **Budget:** 5 minutes. 40 calls (v12-b1024, v0-think) or 70 calls (older bundles). 180 s per command.
- **What the issue gives away:** the output format for the full context (the examples), the singular wording, and the three exception classes.
- **What is hidden:**
  - The constructor kwarg name `endpoint_ctx`, which the 2 unit tests call directly.
  - The `Endpoint: <path>` fallback format for a path-only context.
  - So at most 5 of 7 are reachable from the issue text. One wrong kwarg name fails the task.
- **Size:** a correct run must change one `__str__`, three constructors, and about 9 raise sites in `routing.py`, then verify through a mounted sub-app and a websocket. Measured from the older bundles' traces: 8 to 13 edit calls each.
- **Gold in a clean environment: yes (measured).** Before: 7 failed. After: 7 passed. The Kaggle oracle resolves it too (8.8 s).
- **Test cost (indicative: macOS arm64, Python 3.12.14):**

  | Step | Time |
  |---|---|
  | install | 0.4 s |
  | the 7 F2P tests | 0.66 s |
  | the touched file | 0.73 s |
  | full `tests/` | 4.4 s |

## What the six box runs did

| run (bundle) | secs / calls | model s (calls) | tools s | final patch | clean env |
|---|---|---|---|---|---|
| p4 (v5h2) | 240 / 67 | 226.2 (75) | 3.0 | exceptions.py + routing.py (11 helper edits, t=73 to 201) | 0/7 (`str` lacks the context) |
| p4_v7 (v7) | 159 / 29 | 148.7 (34) | 2.3 | exceptions.py + routing.py (9 edits, t=54 to 146) | 0/7 (the custom handlers never receive the exception) |
| p4_v7c (v7c) | 251 / 56 | 239.3 (63) | 4.1 | exceptions.py + routing.py (4 identical import edits at t=139 to 146, then 7 more) | 0/7 |
| p4_v7d (v7d) | 305 / 70 (time cap) | 288.4 (78) | 3.5 | exceptions.py + routing.py + dependencies/models.py | 0/7 |
| p4_b1024 (v12-b1024) | 305 / 31 (time cap) | 297.5 (34) | 0.3 | exceptions.py only (3 edits at t=131 to 145) | 0/7 |
| p4_v0t2 (v0-think) | 305 / 33 (time cap) | 277.7 (34) | 0.3 | exceptions.py only (first edit at t=272) | 0/7 |

Measured from the timelines:

- **The v5h2/v7 family** reached all the right sites. They edited the 3 classes and threaded a context through `routing.py`.
  - None ran the new behaviour end to end.
  - v7c ran the existing `tests/test_exception_handlers.py` 3 times (t=198 to 234). That file does not exercise the context.
  - All 6 box patches named the kwarg `endpoint_context` (measured by grepping each patch; none contains `endpoint_ctx`). It is the natural name, and not the hidden one.
  - v7 and v7c's routing changes stop the exception from reaching the app's handlers. Measured: `captured_exception.exception is None`.
- **p4_b1024.**
  - 17 reads and 11 searches until t=125.
  - Three `edit_file` calls to `exceptions.py` (the first after a 36.6 s model call).
  - A 44.8 s compaction at t=210. The cap came before any routing.py change.
- **p4_v0t2.**
  - 22 reads. A 32.6 s compaction at t=79. Two model calls of 58 s each.
  - First edit at t=272. The second edit (routing.py) was cut off by the cap.
- **L4.** 0 of 12 L4 runs with 74 rows solved it. e74_v3 got furthest: 2 source files plus its own test, and it hit the time cap.

**Where the time went (measured, six runs, 1,563.5 s):**

| | Seconds |
|---|---|
| model calls | 1,477.8 |
| tool runtime | 13.5 |
| tail cut off by the cap | 21.0 |
| other (harness) | 51.2 |

This run includes compaction calls: 13.4 s (p4), 20.5 s (v7c), 24.2 s (v7d), 44.8 s (b1024) and 32.6 s (v0t2). The prompts of the long older-bundle runs grow toward the 14,336-token compaction threshold.

## Root cause, feasibility, lever

- **Root cause: FEATURE_TOO_LARGE plus HIDDEN_SPEC.**
  - A 12-hunk, 2-file feature. Two of the 7 tests call a constructor kwarg (`endpoint_ctx`) and a fallback format (`Endpoint: `) that appear only in the tests.
  - The older bundles reached all the right sites within the budget but never ran the behaviour. The current line spends the 5 minutes on reading and long thinking calls.
  - This agrees with the old diagnosis. Correction: on these box runs the integration tests also fail (0/7, not 3/7).
- **Feasible in 5 minutes: no.**
  - Even a perfect reading of the issue gets 5 of 7, and the task is binary.
  - Measured for the reachable part: the fastest full threading of the context (v7) took 9 edits from t=54 to 146 s, and its result was wrong.
- **General levers.** These won't flip this task:
  1. **Exercise the feature through the public API before submitting.** Here: raise each of the three errors from a test client and print `str(exc)`. v7 and v7c would have seen that their handlers no longer received the exception, about 1 s of tool time.
  2. **Never resend an identical edit.** v7c made 4 identical import edits.
  3. **Spend context sparingly on multi-site features.** All five runs that compacted lost 13 to 45 s to the summariser. Reading only the raise sites with `grep -n "raise .*ValidationError"` instead of whole files keeps prompts under the threshold.
