# fastapi_15280: "Add support for `@app.vibe()`" (an April Fools' PR)

Sources:
- `docs/forty_two/ground_truth/fastapi_15280.json`: the ground truth, from `gt_fastapi.py`.
- `docs/forty_two/ground_truth/fastapi_tools/trace_timing/fastapi_15280.json`: the per-run timing, from `tr_fastapi.py`.

"Measured" means taken from those files. "Inferred" means a reading of them.

## Problem

- **Issue:** the title only, twice: "✨ Add support for `@app.vibe()`".
- **Gold:** 2 files, 3 hunks, +71/-1 lines.
  - A new `docs_src/vibe/tutorial001_py310.py`.
  - `FastAPI.vibe(path, *, prompt="")` in `applications.py`. Its docstring describes sending the payload to an LLM, and its body is `raise FastAPIError("Are you kidding me? Happy April Fool's")`.
- **FAIL_TO_PASS (1, measured):** `tests/test_vibe.py::test_vibe_raises`. It calls `pytest.raises(FastAPIError, match="Are you kidding me")` around `@app.vibe("/vibe/", prompt=...)`. No PASS_TO_PASS.

## Constraints

- **Budget:** 5 minutes. 40 calls (v12-b1024, v0-think) or 70 calls (older bundles). 180 s per command.
- **Hidden spec, three ways:**
  - The method must *raise* rather than register a route.
  - It must raise `FastAPIError`.
  - The message must contain "Are you kidding me".
  - It needs a `prompt=` keyword. That one is reachable only from the test.
  - None of this can be derived from a title-only issue. A faithful implementation of "support for `@app.vibe()`" fails.
- **Gold in a clean environment: yes (measured).** Before: 1 failed. After: 1 passed. The Kaggle oracle resolves it too (9.0 s).
- **Test cost (indicative):**

  | Step | Time |
  |---|---|
  | install | 0.6 s |
  | the F2P test | 0.46 s |
  | full `tests/` | 5.9 s |

## What the six box runs did

| run (bundle) | secs / calls | model s (calls) | tools s | final patch | clean env |
|---|---|---|---|---|---|
| p4 (v5h2) | 293 / 70 (budget) | 284.7 (76) | 2.6 | empty | `AttributeError: no attribute 'vibe'` |
| p4_v7 (v7) | 160 / 70 (budget) | 149.6 (76) | 3.2 | `APIRouter.vibe` in routing.py (not on `FastAPI`) | AttributeError |
| p4_v7c (v7c) | 302 / 65 (time cap) | 219.7 (67) | 4.6 (+75.4 cut off at the cap) | empty | AttributeError |
| p4_v7d (v7d) | 165 / 67 | 151.7 (73) | 4.8 | `FastAPI.vibe(*args, **kwargs)` returning a no-op decorator | `DID NOT RAISE FastAPIError` |
| p4_b1024 (v12-b1024) | 230 / 40 | 224.7 (44) | 0.4 | replaced the `def get(` header in routing.py with a `vibe` method | collection error: `SyntaxError: unmatched ')'` (exit 2) |
| p4_v0t2 (v0-think) | 302 / 32 (time cap) | 281.7 (34) | 0.4 (+14.0 cut off at the cap) | empty | AttributeError |

Measured from the timelines:

- **Identical-call loops:**
  - p4: `git grep -n "def get" fastapi/applications.py | grep -C 1 "def get("` 38 times.
  - v7: `view.py fastapi/routing.py 1950 2050` 29 times and `1336 1360` 8 times.
  - e74_v2 (L4): `grep -n "def vibe"` 13 times.
- **Single very long model calls:** p4 **144.8 s**, v7c **117.1 s**, v0t2 65.9 s, b1024 37.4 s and 36.9 s.
- **b1024's edit** used an `old_string` that was only the header line `def get(`. The replacement left the old signature's arguments dangling: an EDIT_TOOL_FAILURE of the corrupting kind. It never compiled the module.
- **L4:** 0 of 12 L4 runs with 74 rows solved it.

**Where the time went (measured, six runs, 1,451.7 s):**

| | Seconds |
|---|---|
| model | 1,312.1 |
| tools | 16.0 |
| tail cut off by the cap | 89.5 |
| other | 34.2 |

## Root cause, feasibility, lever

- **Root cause: HIDDEN_SPEC.** The test asserts a joke `FastAPIError` message that exists only in the gold and the test.
  - This agrees with the old diagnosis.
- **Feasible in 5 minutes: no.**
- **Lever: none realistic for this task.** Two general habits show up here:
  1. **Compile after every edit.** `python -m py_compile <file>` costs about 0.1 s. It would have turned b1024's broken module (pytest exit 2) into an immediate retry. A collection error fails *every* test, and a hidden task with any P2P test pays for it.
  2. **Never repeat an identical command, and bound thinking per call.** The p4 and v7c runs lost 145 and 117 s to single calls, and p4 and v7 lost their 70-call budgets to loops.
