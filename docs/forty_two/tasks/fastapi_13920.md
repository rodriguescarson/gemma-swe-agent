# fastapi_13920: support PEP 695 `TypeAliasType` (an alias that carries `Depends`)

Sources:
- `docs/forty_two/ground_truth/fastapi_13920.json`: the ground truth, from `gt_fastapi.py`.
- `docs/forty_two/ground_truth/fastapi_tools/trace_timing/fastapi_13920.json`: the per-run timing, from `tr_fastapi.py`.

"Measured" means taken from those files or a command named here. "Inferred" means a reading of them.

## Problem

- **Issue (PR text, 2 lines):** "Add support for PEP695 `TypeAliasType`". It says the PR continues #11140, "fixed by vendoring a copy of `is_typealiastype` from `typing-inspection`".
  - It gives no example and no symptom.
  - It does not say which use of an alias is broken.
- **Gold:** `fastapi/dependencies/utils.py`, 2 hunks, +4 lines.
  - `from typing_inspection.typing_objects import is_typealiastype`.
  - At the top of `analyze_param`: `if is_typealiastype(annotation): annotation = annotation.__value__`.
- **FAIL_TO_PASS (1, measured):** `tests/test_dependency_pep695.py::test_pep695_type_dependencies`.
  - `DependedValue = TypeAliasType("DependedValue", Annotated[int, Depends(some_value)])` is used as an endpoint parameter type. The test asserts a 200 response with body `"value: 123"`.
  - At base it fails with 422: FastAPI does not see the `Depends` inside the alias, so it treats `value` as a required query parameter. No PASS_TO_PASS.

## Constraints

- **Budget:** 5 minutes. 40 calls (v12-b1024, v0-think) or 70 calls (older bundles). 180 s per command.
- **What is hidden (measured with `probe_13920.py`, below):** which alias use is broken.
  - At base, with the task's venv:
    - `type PlainInt = int` as a query parameter works: 200.
    - `type QueryInt = Annotated[int, Query(gt=0)]` works: 200 for 5, 422 for -1. Pydantic resolves those aliases itself.
    - **Only** an alias whose `Annotated` metadata is FastAPI-level (`Depends`) fails: 422 `missing query v`.
  - So an agent's natural repro (`type MyInt = int`) passes at base and tells it nothing.
  - The issue's only concrete pointer, "vendoring `is_typealiastype`", points at a compatibility helper. That is where all five runs with a patch went (`fastapi/_compat/shared.py`).
  - No exact string is hidden. The gold import is a third-party function that is already installed (typing-inspection 0.4.2 is in the parity pins).
  - Probe command (from `$SCR/ws/fastapi_13920` at base): `$SCR/venv/fastapi_13920-ws/bin/python -I docs/forty_two/ground_truth/fastapi_tools/probes/probe_13920.py`. The probe is committed there. Its output:
    ```
    /plain?q=5 200 5
    /query?q=5 200 5
    /query?q=-1 422 ... greater_than ...
    /dep 422 ... "type":"missing","loc":["query","v"] ...
    ```
- **Gold in a clean environment: yes (measured).** Before: 1 failed (422 == 200). After: 1 passed. The Kaggle oracle resolves it too (8.5 s).
- **Test cost (indicative: macOS arm64, Python 3.12.14, warm uv cache):**

  | Step | Time |
  |---|---|
  | install | 0.4 s |
  | the F2P test | 0.73 s |
  | the touched file | 0.65 s |
  | full `tests/` | 8.7 s (2,876 passed, 4 failed, 127 errors: modules missing from the parity env) |

## What the six box runs did

| run (bundle) | secs / calls | model s (calls) | tools s | final state | clean env |
|---|---|---|---|---|---|
| p4 (v5h2) | 173 / 70 (budget) | 161.8 (77) | 4.5 | `_compat/shared.py`: `is_typealiastype` plus unwrapping in the `field_annotation_*` helpers | F2P fails (422) |
| p4_v7 (v7) | 147 / 70 (budget) | 132.7 (76) | 5.8 | `_compat/shared.py`, using `types.TypeAliasType` | F2P fails: `AttributeError: module 'types' has no attribute 'TypeAliasType'` |
| p4_v7c (v7c) | 115 / 70 (budget) | 106.6 (76) | 2.1 | **empty** | F2P fails |
| p4_v7d (v7d) | 175 / 70 (budget) | 163.6 (76) | 4.2 | `_compat/shared.py` | F2P fails (422) |
| p4_b1024 (v12-b1024) | 305 / 32 (time cap) | 298.8 (33) | 0.8 | `_compat/shared.py` (3 edits at t=288 to 299) + `reproduce_issue.py` | F2P fails (422) |
| p4_v0t2 (v0-think) | 305 / 20 (time cap) | 300.8 (22) | 0.2 | `_compat/shared.py` (8 edits at t=251 to 298) | F2P fails (422) |

Measured from the timelines:

- **The v5h2/v7 family.** Each run searched for the symbol the issue names. It does not exist at base, so every `git grep` exited 1 with empty output. They then repeated the same failing search until the 70-call budget ran out:

  | run | search | repeats | model time | span |
  |---|---|---|---|---|
  | p4 | `git grep -n "is_typealiastype" .` | 34 | 36.8 s | t=45 to 83 |
  | v7c | `git grep -n "TypeAlias" /workspace/fastapi/utils.py` | 63 | 74.8 s | t=14 to 89 |
  | v7d | `git grep -n "is_type_alias" /workspace/fastapi/` | 43 | 50.8 s | t=32 to 83 |

  v7 re-viewed `shared.py 1-200` 10 times. None of the four ran an endpoint repro.
- **p4_b1024.**
  - Searched and read t=12 to 106 s, mostly `_compat/shared.py` and its callers (`field_annotation_is_scalar` in dependencies/utils.py at t=99).
  - Its repro (t=224 and 250) imported `TypeAliasType` from `types`, fell back to `typing`, and tested the `shared.py` helpers directly ("MyList is complex: False"). It never built an endpoint.
  - Edits came at t=288 to 299, and the cap at 305 s.
  - Five calls took 28 to 46 s. One 28.0 s compaction.
- **p4_v0t2.**
  - Read `utils.py`, `params.py`, `routing.py` and `dependencies/utils.py` (including `get_dependant`, lines 256 to 400) by t=38. Then `shared.py`.
  - **One 150.1 s model call** (t=50 to 200) produced `grep -n "def " fastapi/_compat/shared.py`.
  - It made 8 edits that thread a `resolve_type_alias` through the helpers (t=251 to 298). No check ran before the cap.
- **L4.** 0 of 12 L4 runs with 74 rows solved it. The two traced ones (e74_v2, e74_v3) also patched `_compat/shared.py`. e74_v3 ran its own `test_pep695.py` 6 times.

**Where the time went (measured, six runs, 1,218.9 s):**

| | Seconds |
|---|---|
| model calls | 1,164.3 |
| tool runtime | 17.6 |
| tail cut off by the cap | 3.0 |
| other (harness) | 34.0 |

Model time on identical no-match searches: 162 s, across p4, v7c and v7d. Single calls of 28 to 150 s: b1024 and v0t2.

## Root cause, feasibility, lever

- **Root cause: UNDERSPECIFIED_ISSUE**, which led to WRONG_LOCATION.
  - The issue is a title plus a link. The one failing use (an alias carrying `Depends`) appears only in the hidden test. Plain and `Query` aliases already work at base, so a generic repro cannot fail.
  - The "vendoring" sentence steers to `_compat`. 18 of 18 recorded runs (6 box + 12 L4) missed `analyze_param`.
  - This corrects the old diagnosis (WRONG_LOCATION, feasible yes). It added that the repro gate alone cannot help, because the obvious repro already passes.
- **Feasible in 5 minutes: maybe (low).**
  - An agent that writes the framework's *own* use of `Annotated` (`Annotated[int, Depends(f)]`) inside an alias gets a 422 in under 1 s of tool time. The error `missing query v` points at parameter analysis, and the fix is 4 lines.
  - Nothing in the issue suggests `Depends`. Measured: 0 of 18 runs.
- **General levers:**
  1. **"Add support for X" means X in every role the library gives it.** Rule: for a feature request about a type construct, write the repro with that construct in each annotation role the framework documents (plain type, `Annotated[..., <framework marker>]`), through the public API. Edit only after one of them fails. This applies to any repo with an annotation-driven API. Its hit rate is unmeasured.
  2. **A search that returns nothing is an answer.** Never repeat a no-match search. Append `|| echo NO_MATCH` so the reply is explicit, and widen or change the term. In p4, v7c and v7d this would have recovered 162 s and about 140 calls. The current v12 line's prompt already says "search a shorter token", and b1024 did not loop.
  3. **Bound thinking per call.** v0t2's 150 s call produced one grep.
