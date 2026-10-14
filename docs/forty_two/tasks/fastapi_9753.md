# fastapi_9753: `functools.partial()` dependables (async, callable classes, generators)

Sources:
- `docs/forty_two/ground_truth/fastapi_9753.json`: the ground truth, from `gt_fastapi.py`.
- `docs/forty_two/ground_truth/fastapi_tools/trace_timing/fastapi_9753.json`: the per-run timing, from `tr_fastapi.py`.

"Measured" means taken from those files. "Inferred" means a reading of them.

## Problem

- **Issue (PR text):** `Depends(partial(f, ...))` already works for plain functions, but not consistently for async functions or callable classes. The PR makes `partial()` work in all combinations.
  - It mentions that `test_dependency_class.py` was renamed to `test_dependency_types.py`. Neither name is the hidden test file.
  - It names no source symbol.
- **Gold:** `fastapi/dependencies/models.py`, 2 hunks, +5/-2 lines.
  - Import `partial`.
  - `Dependant._unwrapped_call`: after `inspect.unwrap(self.call)`, take `.func` when the result is a `partial`.
  - `_unwrapped_call` feeds `is_gen_callable`, `is_async_gen_callable` and `is_coroutine_callable`. Those properties decide whether FastAPI awaits or iterates a dependency.
- **FAIL_TO_PASS (5 of 12 parametrised cases, measured):** `tests/test_dependency_partial.py::test_dependency_types_with_partial[...]` for these partials:
  - async function
  - callable-class generator
  - async callable class
  - async callable-class generator
  - async method

  Each GETs a route whose dependency is the partial and asserts it returns the bound string. Before the fix, FastAPI returns the raw coroutine or generator object, so response validation fails with `string_type`.
  - PASS_TO_PASS (7): the plain function, generator and async generator partials, plus the method cases that already classify correctly.

## Constraints

- **Budget:** 5 minutes. 40 calls (v12-b1024, v0-think) or 70 calls (v5h2/v7*). 180 s per command.
- **What the issue gives away:** the feature (`partial` around every dependency kind) and the failing kinds (async, callable classes).
- **What it hides:** where the fix goes.
  - `inspect.unwrap(` appears at three sites. Two are in `dependencies/utils.py` (`get_typed_signature`, `get_typed_return_annotation`), which already handle signatures. One is in `dependencies/models.py` (`Dependant._unwrapped_call`), which decides sync, async or generator.
  - Only the models.py site matters. Every box run went to utils.py.
  - No exact string or new API name is hidden.
- **Gold in a clean environment: yes (measured).** Before: 5 failed, 7 passed. After: 12 passed. The Kaggle oracle resolves it too (`eval/kaggle/oracle_all/results.jsonl`, 8.0 s).
- **Test cost (indicative: macOS arm64, Python 3.12.14, warm uv cache):**

  | Step | Time |
  |---|---|
  | install | 0.5 s |
  | the 5 F2P cases | 0.71 s |
  | the touched file | 0.69 s |
  | full `tests/` | 4.4 s (717 passed, 4 failed, 148 errors: modules missing from the parity env) |

## What the six box runs did

| run (bundle) | secs / calls | model s (calls) | tools s | final state | clean env |
|---|---|---|---|---|---|
| p4 (v5h2) | 157 / 51 | 143.8 (57) | 5.4 | utils.py: `inspect.signature(unwrapped)` in two functions (wrong file) | 5 F2P fail |
| p4_v7 (v7) | 81 / 26 | 70.5 (31) | 2.8 | utils.py: unwrap `partial` before `inspect.unwrap` at both signature sites (right idea, wrong site) | 5 F2P fail |
| p4_v7c (v7c) | 115 / 35 | 106.8 (40) | 2.3 | the same utils.py edit as v7 | 5 F2P fail |
| p4_v7d (v7d) | 79 / 22 | 71.2 (27) | 1.6 | utils.py: `getattr(call, "__name__", ...)` in an error message (unrelated) | 5 F2P fail |
| p4_b1024 (v12-b1024) | 305 / 19 (time cap) | 276.4 (27) | 0.6 (+25.2 cut off at the cap) | only `reproduce_issue.py` and `test.py`, no source edit | 5 F2P fail |
| p4_v0t2 (v0-think) | 302 / 12 (time cap) | 293.3 (13) | 0.1 | empty patch | 5 F2P fail |

Measured from the timelines:

- **p4.**
  - The locator wrote 3 repro scripts into /workspace (t=32 to 59 s). The async one printed `RuntimeWarning: coroutine 'dep' was never awaited`, which is the bug's own symptom.
  - The fixer edited the two utils.py sites (t=92 and 101).
  - The verifier reran the async repro 3 times (t=121 to 146). Each still printed the never-awaited warning, but exit was 0, and it submitted at t=154.
  - It also called `test.py --target tests/test_dependency_types.py`: the file named in the issue, which does not exist at base (exit 4).
- **p4_v7.**
  - Located utils.py:195 at t=35. Edited both signature sites at t=47 to 53.
  - Ran the existing `tests/test_dependency_class.py` (8 passed after an import fix) and submitted at t=78.
  - That existing test file does not cover `partial`.
- **p4_v7c.** The same path as v7. Five `view.py` calls on the same range (10.2 s of model time). Submitted at t=112.
- **p4_v7d.** The locator picked the `__name__` access in a scope-error message (utils.py:276) and fixed that. The verifier "verified" it at t=76.
- **p4_b1024.**
  - Read the right neighbourhood by t=46. It read `dependencies/models.py` in full at t=46, so it saw `_unwrapped_call`.
  - Then it sent 8 `write_file` calls between t=81 and 199. Seven came back `mandatory input parameters are not present: filepath` and one wrote a 14-byte `test.py`. That is 152.6 s of model time for 0.1 s of tool time.
  - Its `cat <<EOF` repro at t=219 printed `Partial async: False / Partial async class: False`, the exact defect. It re-read models.py lines 70 to 113 at t=257 to 261, but the cap came at 305 s before any edit.
  - A 28.0 s compaction call came at t=220.
- **p4_v0t2.**
  - Seven quick reads and searches (t=10 to 36 s). Then **one 127.9 s model call** (t=36 to 164) produced a `grep`. The run's 13 calls made 8,055 completion tokens in all.
  - A 67.8 s call wrote a test into `tests/`, which the grader would discard.
  - A 37.8 s call was cut off by the cap. The patch is empty.
- **The L4 solvers.** 2 of 12 L4 runs with 74 rows resolved it: g4-l4-v4h2g (18 calls, 71 s) and g4-l4-v5h2-t0 (34 calls, 87 s).
  - Both patched `Dependant._unwrapped_call` in models.py with a `while isinstance(call, functools.partial): call = call.func` loop, the same as gold. Both re-verify in my env (12 passed).
  - These runs have no traces, so how they located the site is **not verifiable**.
  - Inferred: this is location sampling. The same v5h2 bundle went to utils.py on the box (p4) and to models.py on L4 at temperature 0.

**Where the time went (measured, six runs, 1,038.5 s):**

| | Seconds |
|---|---|
| model calls | 962.0 |
| tool runtime | 12.8 |
| tail cut off by the cap | 25.2 |
| other (harness) | 38.5 |

The large sinks were all model calls:
- b1024's repeated `write_file`: 152.6 s.
- v0t2's single 127.9 s call and its 67.8 s call.
- b1024's 28 s compaction.

## Root cause, feasibility, lever

- **Root cause: WRONG_LOCATION.**
  - In 4 of 6 runs the idea (unwrap `partial`) or a nearby idea was applied at the signature-introspection sites in utils.py. The defect is at the call-kind classification site in models.py, which uses the same `inspect.unwrap(` expression.
  - b1024 was an EDIT_TOOL_FAILURE. Its repro had already pinpointed the defect, but the dropped `write_file` argument ate 153 s.
  - v0t2 ran out of time on two very long thinking calls.
  - This agrees with the old diagnosis's "locate + edit tool" reading. It adds the b1024 and v0t2 evidence and the timing.
- **Feasible in 5 minutes: yes.** Measured: 2 of 12 L4 runs resolved it in 71 to 87 s, and gold is 4 lines.
- **General levers:**
  1. **Patch every site of the primitive you changed.** After editing an expression such as `inspect.unwrap(x)`, run `git grep -n "inspect.unwrap(" -- "*.py"` and decide for each hit. This turns a "sibling" rule the prompt already has into a mechanical step. It would have shown models.py:82 to v7 and v7c, the runs closest to gold.
  2. **A repro must assert the issue's expected value for each variant the issue names**, here the response body for each dependency kind. Exit code 0 is not enough. Treat `coroutine ... was never awaited` and similar warnings as failure: p4 saw the warning three times and submitted.
  3. **Do not resend a call that just failed identically.** On the second identical tool error, switch to a `run_command` heredoc into /tmp. Here that recovers 153 s in b1024.
  4. **Cap thinking per call.** v0-think's 4,096-token budget allowed a 128 s call. v12-b1024's 1,024 budget still had 35 s calls. A tighter budget for search and read steps is a decoding-config lever, not a prompt one. Its cost on hard reasoning is unmeasured.
