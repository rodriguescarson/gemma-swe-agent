# fastapi_14419: cache dependencies that neither use scopes nor have sub-dependencies that do

Sources:
- `docs/forty_two/ground_truth/fastapi_14419.json`: the ground truth, from `gt_fastapi.py`.
- `docs/forty_two/ground_truth/fastapi_tools/trace_timing/fastapi_14419.json`: the per-run timing, from `tr_fastapi.py`.

"Measured" means taken from those files. "Inferred" means a reading of them.

## Problem

- **Issue (PR text).** The title is the spec: *cache dependencies that don't use scopes and don't have sub-dependencies with scopes.* The last paragraph says exactly when scopes may split the cache: "only when those scopes are used by this dependency or by a sub-dependency: this dependency or a sub-dependency declare scopes or access the `SecurityScopes`."
  - At base, `Dependant.cache_key` is `(call, sorted(security_scopes), computed_scope)`.
  - `security_scopes` there is the *accumulated* list (parent scopes plus own). So `get_db` under `Security(get_user, scopes=["read"])` gets a different key from plain `Depends(get_db)`, and it runs twice.
- **Gold:** 2 files, 7 hunks, about +40/-20 lines.
  - `models.py`: split `security_scopes` into `own_oauth_scopes` and `parent_oauth_scopes`. Add an `oauth_scopes` property. Add `_uses_scopes`: own scopes, or `security_scopes_param_name`, or any sub-dependency that uses scopes. `cache_key` uses the scopes only when `_uses_scopes` is true.
  - `utils.py`: rename the plumbing in `get_dependant`, `get_parameterless_sub_dependant` and `solve_dependencies`.
- **FAIL_TO_PASS (2, measured):**
  - `tests/test_security_scopes.py::test_security_scopes_dependency_called_once`: `get_db` used directly and under a `Security(..., scopes=["read"])` sub-dependency is called once.
  - `tests/test_security_scopes_sub_dependency.py::test_security_scopes_sub_dependency_caching`: exact call counts (db 1, current_user 2, user_me 2, user_items 1) and the exact response JSON, including `"scopes": ["items", "me"]`.
  - Both fail at base with `assert 2 == 1`. PASS_TO_PASS: none in the touched files.

## Constraints

- **Budget:** 5 minutes. 40 calls (v12-b1024, v0-think) or 70 calls (older bundles). 180 s per command.
- **What the issue gives away:** the full rule, in words. The function to change is easy to find (`cache_key` is the only cache key, models.py:47).
- **What it hides:** a trap in the base code.
  - `security_scopes` holds inherited scopes too. "Has scopes" checked on that field is true for every dependency under a `Security(...)`, so it cannot be the "uses scopes" test.
  - The working test at base is `security_scopes_param_name is not None` (the dependency accesses `SecurityScopes`), applied recursively over sub-dependencies.
  - No exact string or new API name is needed. The tests use only public API.
  - **The full gold refactor is not required (measured).** The L4 solve `g4-l4-v9-eog` changed only `models.py`: a recursive `uses_scopes` on `security_scopes_param_name`, plus `scopes if uses_scopes else ()` in `cache_key`, about 10 lines. It passes both tests in my clean env.
  - This corrects the old diagnosis's "multi-file partial" reading.
- **Gold in a clean environment: yes (measured).** Before: 2 failed. After: 2 passed. The Kaggle oracle resolves it too (12.3 s).
- **Test cost (indicative: macOS arm64, Python 3.12.14, warm uv cache):**

  | Step | Time |
  |---|---|
  | install | 0.5 s |
  | the 2 F2P tests | 0.72 s |
  | the touched files | 0.74 s |
  | full `tests/` | 4.2 s (691 passed, 4 failed, 146 errors: modules missing from the parity env) |

## What the six box runs did

| run (bundle) | secs / calls | model s (calls) | tools s | final state | clean env |
|---|---|---|---|---|---|
| p4 (v5h2) | 111 / 21 | 101.6 (27) | 2.7 | `cache_key` + `security_scopes_param_name is not None` added to the tuple (the key gets *more* specific) | 2 F2P fail |
| p4_v7 (v7) | 125 / 69 | 114.9 (74) | 2.7 | `cache_key`: scopes kept when `dependant.security_scopes` is non-empty, recursively. Inherited scopes make it always true. | 2 F2P fail |
| p4_v7c (v7c) | 85 / 17 | 77.0 (22) | 2.0 | `cache_key` keyed on the union of all sub-dependency scopes (the wrong direction) | 2 F2P fail |
| p4_v7d (v7d) | 223 / 70 (budget) | 201.9 (77) | 14.0 | **empty**: the edit came after the budget | 2 F2P fail |
| p4_b1024 (v12-b1024) | 305 / 16 (time cap) | 285.2 (17) | 0.7 (+16.4 cut off at the cap) | only `reproduce_issue.py`, no source edit | 2 F2P fail |
| p4_v0t2 (v0-think) | 302 / 18 (time cap) | 231.9 (19) | 0.4 (+67.7 cut off at the cap) | empty | 2 F2P fail |

Measured from the timelines:

- **p4.**
  - The locator ended with one 45.8 s call (t=29 to 75) and got the rule right in prose.
  - The fixer's single edit (t=94) adds a field to the key instead of dropping the scopes.
  - It checked with the existing `tests/test_dependency_cache.py` (3 runs, 4 passed). That file has no scopes, so it cannot fail.
  - Submitted at t=108.
- **p4_v7.** The locator ran `git grep -ln "solve_dependencies" tests/` **55 times** (t=16 to 69): 52.9 s of model time, 1.3 s of tool time. The fix that followed tests the accumulated field.
- **p4_v7c.** 17 calls, submitted at t=85 with the union-of-scopes key. It never ran a repro.
- **p4_v7d.**
  - The locator found `cache_key` and the `test_security_scopes_dont_propagate.py` neighbour by t=42.
  - The fixer wrote a `/tmp` test script with no `__main__` call. It then ran `python3 /tmp/test_dependencies_cache_scopes.py` **48 times**: each exit 0, each with no output. That is 53.5 s of model time and 11.7 s of tool time (t=93 to 199).
  - Its first edit came at t=208 and was refused: the budget was exhausted.
- **p4_b1024.**
  - Read the right code (`types.py`, `models.py`, the utils.py `get_dependant` and `solve_dependencies` ranges) by t=115 in 12 calls.
  - Then wrote `cat <<'EOF' > reproduce_issue.py` twice, at t=161 and t=285, from calls of 46.4 s and 63.1 s. Both failed at line 2 with `from fastapi import ... SecurityScopes` (it lives in `fastapi.security`).
  - Model calls of 34 to 63 s (5 of them) used the 5 minutes. No source edit.
- **p4_v0t2.**
  - Read the right files by t=57. Then two calls of 92.3 s and 52.1 s each produced one `grep -r` over the whole repo.
  - A 24.0 s compaction followed. A call still running at the cap accounts for the last 67.7 s.
  - No edit.
- **The L4 solver (`g4-l4-v9-eog`, 1 of 12 L4 runs with 74 rows).**
  - 40 calls, 308 s. It hit the cap; the fallback diff was graded.
  - The recursive `security_scopes_param_name` check described above, plus `repro.py` and `tests/test_security_scopes_cache.py`. The grader discards that test file, and `repro.py` is harmless.
  - There is no trace of it, so how it got there is **not verifiable**.

**Where the time went (measured, six runs, 1,150.4 s):**

| | Seconds |
|---|---|
| model calls | 1,012.5 |
| tool runtime | 22.5 |
| tail cut off by the cap | 84.1 |
| other (harness) | 31.3 |

The model time went to:
- Repeated identical commands: v7's grep, 52.9 s; v7d's silent script, 53.5 s plus 11.7 s of tool time.
- Very long thinking calls, 34 to 92 s each: b1024 and v0t2.
- Compaction: b1024 22.2 s, v0t2 24.0 s.

## Root cause, feasibility, lever

- **Root cause: WRONG_SEMANTICS.**
  - 3 of 6 runs edited the right function with the wrong predicate. The trap is that the base field mixes inherited and own scopes.
  - The other 3 ran out of budget or time before editing: an identical-command loop (v7d), and slow thinking calls with a broken repro (b1024, v0t2).
  - Every run that submitted a patch had **no failing check before its fix**. The existing test file they ran cannot fail on this bug.
- **Feasible in 5 minutes: maybe.** Measured: 1 of 12 L4 runs, at 308 s. The minimal fix is about 10 lines in one function. Getting the predicate right needs one experiment that shows the accumulated field is non-empty under `Security`.
- **General levers:**
  1. **Red before green.** Write the issue's claim as an assert (here: a call counter equals 1) and run it *before* editing. Only an assert that failed at base can confirm the fix. p4, v7 and v7c would have seen their fixes fail in about 0.5 s of tool time.
  2. **A script that prints nothing proves nothing.** If a check exits 0 with empty output, add a print or assert. Never rerun it unchanged. A harness-side breaker for the 3rd identical command would have saved v7 53 s and v7d 65 s.
  3. **Import names from where the repo defines them.** Before a repro imports a name, `git grep -n "class Name"` (b1024 lost two 40 to 60 s calls to `from fastapi import SecurityScopes`). This is a cheap habit for any repo.
  4. **Bound thinking per call** (v0-think 92 s, b1024 63 s calls). This is a decoding-config lever. Its effect on hard tasks is unmeasured.
