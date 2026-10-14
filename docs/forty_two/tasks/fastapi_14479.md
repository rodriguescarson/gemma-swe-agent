# fastapi_14479: a clearer assertion message for invalid query parameter types

Sources:
- `docs/forty_two/ground_truth/fastapi_14479.json`: the ground truth, from `gt_fastapi.py`.
- `docs/forty_two/ground_truth/fastapi_tools/trace_timing/fastapi_14479.json`: the per-run timing, from `tr_fastapi.py`.

"Measured" means taken from those files. "Inferred" means a reading of them.

## Problem

- **Issue (PR text, with a full repro and the before/after traceback).** The bare `AssertionError` from `analyze_param` (dependencies/utils.py) on an unsupported query-parameter type should carry a message.
  - The "after" traceback in the issue shows the message `AssertionError: Query param 'data' must be of one of the supported types`.
- **Gold:** `fastapi/dependencies/utils.py`, 1 hunk, 1 line. The assert in `analyze_param` gets `f"Query parameter {param_name!r} must be one of the supported types"`.
- **FAIL_TO_PASS (4, measured):** `tests/test_invalid_sequence_param.py::test_invalid_sequence`, `test_invalid_tuple`, `test_invalid_dict` and `test_invalid_simple_dict`.
  - Each now uses `pytest.raises(AssertionError, match="Query parameter 'q' must be one of the supported types")`.
  - All 4 fail at base (no message). No PASS_TO_PASS.

## Constraints

- **Budget:** 5 minutes. 40 calls (v12-b1024, v0-think) or 70 calls (older bundles). 180 s per command.
- **The issue contradicts the test.** The issue's message says "Query **param** … must be **of** one of"; the test regex says "Query **parameter** … must be one of". Nothing in the repo or the issue gives the second wording.
  - The location is trivial: the issue's traceback names `analyze_param` at the assert.
- **Gold in a clean environment: yes (measured).** Before: 4 failed. After: 4 passed. The Kaggle oracle resolves it too (8.3 s).
- **Test cost (indicative: macOS arm64, Python 3.12.14):**

  | Step | Time |
  |---|---|
  | install | 0.4 s |
  | the 4 F2P tests | 0.59 s |
  | full `tests/` | 5.4 s |

## What the six box runs did

All six final patches are **byte-identical in effect**: 524 characters, the one assert in `analyze_param`, message `f"Query param {param_name!r} must be of one of the supported types"`.

Re-verified in my env, every one fails all 4 tests with `Regex pattern did not match … Input: "Query param 'q' must be of one of the supported types"` (`agent_patches_reverified` in the JSON).

| run (bundle) | secs / calls | model s (calls) | tools s | other s |
|---|---|---|---|---|
| p4 (v5h2) | 84 / 23 | 74.7 (28) | 1.7 | 7.6 |
| p4_v7 (v7) | 79 / 14 | 69.9 (19) | 1.8 | 7.3 |
| p4_v7c (v7c) | 110 / 17 | 102.5 (22) | 2.3 | 5.6 |
| p4_v7d (v7d) | 76 / 12 | 66.8 (17) | 1.7 | 7.2 |
| p4_b1024 (v12-b1024) | 113 / 14 | 106.7 (17) | 1.1 | 4.7 |
| p4_v0t2 (v0-think) | 100 / 12 | 93.5 (14) | 0.6 | 5.9 |

- **These are the batch's fastest and cleanest runs.**
  - b1024: located `analyze_param` at t=17, read the assert by t=25, edited at t=55, submitted at t=95.
  - v7c checked with the issue's own example (`Caught expected AssertionError with correct message`, t=72).
  - The agents did exactly what the issue says. The 2 L4 traces (e74_v2, e74_v3) produced the same message and also failed.
  - 0 of 12 L4 runs with 74 rows solved it.
- **Where the time went (measured, six runs, 561.6 s):**

  | | Seconds |
  |---|---|
  | model | 514.1 |
  | tools | 9.2 |
  | other | 38.3 |

  The runs finished at 76 to 113 s, well inside the budget.

## Root cause, feasibility, lever

- **Root cause: HIDDEN_SPEC.** The wording was changed after the issue text was written, and the test pins the final wording. Location, semantics and time were all fine.
  - This agrees with the old diagnosis and is confirmed in a clean environment for all six current box patches.
- **Feasible in 5 minutes: no.** A model that copies the issue fails. A model that paraphrases has no reason to land on this exact sentence.
- **Lever: none realistic.**
  - Inferring "the maintainers will reword the message" is not a rule that transfers to hidden tasks from other repos.
  - The one generic habit, "match the phrasing of neighbouring messages in the file", also fails here. Measured: the neighbouring assert at utils.py:544 reads `"Path params must be of one of the supported types"`, which is the issue's wording, not the test's.
  - Spend nothing on this task.
