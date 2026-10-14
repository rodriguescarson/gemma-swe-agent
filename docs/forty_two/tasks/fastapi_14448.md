# fastapi_14448: `functools.wraps` + `partial` combined, for async and sync callables at every level

Sources:
- `docs/forty_two/ground_truth/fastapi_14448.json`: the ground truth, from `gt_fastapi.py`.
- `docs/forty_two/ground_truth/fastapi_tools/trace_timing/fastapi_14448.json`: the per-run timing, from `tr_fastapi.py`.

"Measured" means taken from those files. "Inferred" means a reading of them.

## Problem

- **Issue (PR text).** It states the rule exactly.
  - Deciding whether a dependency or endpoint is async, a generator, an async generator or a callable instance must unwrap `wraps` and extract `partial` "in all those levels".
  - "the original function could be async or not, the wrapper could be async or not. If either is async, then it has to be awaited… analyzing only the last point in the chain is not enough."
- **Gold:** 2 files, 3 hunks, +82/-24 lines.
  - `dependencies/models.py`: module-level `_impartial()` (strip `partial`) and `_unwrapped_call()`. `is_gen_callable`, `is_async_gen_callable` and `is_coroutine_callable` each test the impartial call, the unwrapped call, the impartial and unwrapped `__call__`, and the `__call__` of the unwrapped object, and return True if any matches.
  - `dependencies/utils.py` `_solve_generator`: check `is_async_gen_callable` **before** `is_gen_callable`. A sync wrapper around an async generator is now both.
- **FAIL_TO_PASS (8, measured):** 8 new parametrised cases of `tests/test_dependency_wrapped.py::test_class_dependency`:
  - `class-instance-async-wrapped-dependency`, `class-instance-async-wrapped-gen-dependency`, `class-instance-wrapped-gen-dependency`
  - `wrapped-class-dependency-async-wrapper`, `wrapped-class-instance-dependency-async-wrapper`
  - `wrapped-dependency-async-wrapper`, `wrapped-endpoint-async-wrapper`, `wrapped-gen-dependency-async-wrapper`

  Failures at base are `'coroutine' object is not iterable`, `'async_generator' object is not iterable`, or `[True] is True`.
  - **PASS_TO_PASS (20):** the cases already in that file, which pass at base. **The file exists at base**, so it is an obvious target to extend and run.

## Constraints

- **Budget:** 5 minutes. 40 calls (v12-b1024, v0-think) or 70 calls (older bundles). 180 s per command.
- **What the issue gives away:** the rule ("either async means await"). No exact string or new name is needed.
- **What is hard:**
  - The matrix: wrapper sync or async, inner sync, async, gen or async-gen, function, class, instance, or method, with or without `partial`.
  - The ordering subtlety in a second file (`_solve_generator`).
  - Any fix that checks only one level passes part of the matrix. Measured: 4 of 8, below.
- **Gold in a clean environment: yes (measured).** Before: 20 passed, 8 failed. After: 28 passed. The Kaggle oracle resolves it too (8.4 s).
- **Test cost (indicative: macOS arm64, Python 3.12.14):**

  | Step | Time |
  |---|---|
  | install | 0.4 s |
  | the 8 F2P cases | 0.76 s |
  | the touched file | 0.77 s |
  | full `tests/` | 4.4 s |

## What the six box runs did

| run (bundle) | secs / calls | model s (calls) | tools s | final patch | clean env (F2P passing) |
|---|---|---|---|---|---|
| p4 (v5h2) | 99 / 24 | 89.7 (30) | 1.7 | models.py | **4/8** (fails: class-instance async-wrapped, async-wrapped-gen, wrapped-gen, wrapped-gen-dependency-async-wrapper) |
| p4_v7 (v7) | 165 / 67 | 154.5 (72) | 2.5 | models.py | **4/8** (the same 4 fail) |
| p4_v7c (v7c) | 152 / 68 | 143.4 (73) | 2.3 | models.py | **4/8** (the same 4 fail) |
| p4_v7d (v7d) | 166 / 32 | 156.6 (37) | 2.1 | models.py (803 chars) | 0/8 |
| p4_b1024 (v12-b1024) | 302 / 14 (time cap) | 273.8 (15) | 0.4 | **empty** | 0/8 |
| p4_v0t2 (v0-think) | 302 / 7 (time cap) | 297.6 (8) | 0.1 | **empty** | 0/8 |

Measured from the timelines:

- **p4, v7 and v7c** found `models.py` and made the "either level is async" change for functions. That flips the 4 function and endpoint cases.
  - They did not cover class instances whose `__call__` is wrapped, or the `_solve_generator` order (no run touched `utils.py`).
  - v7 repeated `git grep -ln "Dependant" tests/test_tutorial/.../test_tutorial012.py` **39 times**: 57.6 s of model time.
  - v7c repeated `git grep -n "iscoroutinefunction" fastapi/routing.py` **50 times**: 60.7 s.
  - v7c then tried a test file that does not exist (`tests/test_dependencies_wraps_partial.py`, exit 4).
  - p4 read the existing `tests/test_dependency_wrapped.py` (t=31) and ran it after its edit (t=91: `4 passed`). Those 4 base cases already pass at base, so the check could not fail. It submitted at t=96.
  - No run added a case for the combinations the issue lists.
- **p4_b1024.**
  - Located `models.py` by t=26 and read it.
  - **One 97.8 s model call** (t=26 to 124) produced a `git grep` that found nothing.
  - Its three probes of `iscoroutinefunction` on wrapped partials (t=182, 227 and 241) came from calls of 43.9, 45.2 and 14.0 s. They showed exactly the defect: `iscoroutinefunction(inspect.unwrap(p.func)): True` while the other checks print False.
  - A 35.4 s call followed, then a call cut off at the cap (inferred from 28 s that no logged call explains). No edit.
- **p4_v0t2.**
  - 7 tool calls in 302 s. Model calls took 53.3, 56.7, **128.0** and 36.0 s.
  - The 128 s call produced `grep -r "_unwrapped_call" fastapi/`. No edit.
- **L4.** 0 of 12 L4 runs with 74 rows solved it. e74_v3 edited models.py and routing.py and wrote its own 4-case test, which passed. The hidden matrix has 28 cases.

**Where the time went (measured, six runs, 1,186.3 s):**

| | Seconds |
|---|---|
| model calls | 1,115.6 |
| tool runtime | 9.1 |
| tail cut off by the cap | 1.1 |
| other (harness, plus a call cut off in b1024) | 60.5 |

The largest single sinks were model calls: v0t2's 128 s, b1024's 98 s, and the identical-search loops (58 and 61 s).

## Root cause, feasibility, lever

- **Root cause: WRONG_SEMANTICS (partial fix).**
  - 3 of 6 runs fixed the function-level half of the matrix in the right file (4 of 8 pass) and missed the instance-`__call__` levels and the second-file ordering.
  - The current-line runs never edited: their 5 minutes went to 4 model calls of 44 to 128 s.
  - This agrees with the old diagnosis and adds the measured 4/8 partial passes and the timing.
- **Feasible in 5 minutes: maybe.**
  - The rule is in the issue, the file is found within 30 s, and the existing test file holds the pattern for a parametrised matrix (it runs in under 1 s).
  - Covering every level correctly is still a careful 2-file edit. No run got there, box or L4.
- **General levers:**
  1. **Extend the existing test file before editing, and make it red first.** When the issue lists combinations, add the missing ones to the existing parametrised test (in /tmp or as a copy), run it red, then fix until green. Here p4 ran the existing `test_dependency_wrapped.py` only as-is (green before and after, so it proved nothing). The agent's copy is discarded by the grader, so it costs nothing.
  2. **Bound thinking per call.** v0-think's 4,096-token budget allowed a 128 s call. Even v12-b1024 at 1,024 had a 98 s call (it ignores the budget or runs long because of output length, **not verified**). A per-call wall-clock cap is a harness feature we cannot add, so this is a decoding-config lever: smaller `thinking_budget` and `max_output_tokens`. Its effect on solve rate is unmeasured.
  3. **Never repeat a search** (v7 and v7c: 39 and 50 repeats).
