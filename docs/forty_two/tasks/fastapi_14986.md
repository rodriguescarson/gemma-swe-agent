# fastapi_14986: do not store `root_path` in OpenAPI servers; escape Swagger UI config JSON

Sources:
- `docs/forty_two/ground_truth/fastapi_14986.json`: the ground truth, from `gt_fastapi.py`.
- `docs/forty_two/ground_truth/fastapi_tools/trace_timing/fastapi_14986.json`: the per-run timing, from `tr_fastapi.py`.

"Measured" means taken from those files or a command named here. "Inferred" means a reading of them.

## Problem

- **Issue (PR text).** Two changes:
  1. "OpenAPI, do not store `root_path` in servers". Today the `/openapi.json` handler inserts the request's `root_path` into `self.servers`, which persists across requests.
  2. "Escape Swagger UI configs": JSON embedded in the Swagger HTML `<script>`.
- **Gold:** 2 files, 4 hunks, +27/-7 lines.
  - `applications.py` `setup()`: build `schema = self.openapi()` per request. When `root_path` is set and `root_path_in_servers`, return a **copy** of the schema with `{"url": root_path}` prepended. Never mutate `self.servers`.
  - `openapi/docs.py`: `_html_safe_json()` (`json.dumps` with `<`, `>` and `&` written as `<`, `>`, `&`), used for the swagger parameters and `initOAuth`.
- **FAIL_TO_PASS (5, measured):**
  - `test_openapi_cache_root_path.py::{test_root_path_does_not_persist_across_requests, test_multiple_different_root_paths_do_not_accumulate, test_configured_servers_not_mutated}`
  - `test_swagger_ui_escape.py::{test_init_oauth_html_chars_are_escaped, test_swagger_ui_parameters_html_chars_are_escaped}`
  - The escape tests require the literal `<...` forms.
- **PASS_TO_PASS (2):**
  - `test_legitimate_root_path_still_appears`: a request with `root_path="/api/v1"` must still list it in `servers`.
  - `test_normal_init_oauth_still_works`.

## Constraints

- **Budget:** 5 minutes. 40 calls (v12-b1024, v0-think) or 70 calls (older bundles). 180 s per command.
- **What the issue gives away:**
  - Both locations: the `/openapi.json` route in `applications.py`, and `get_swagger_ui_html`.
  - The direction of the change. "do not store" means stop mutating shared state, not stop emitting the server entry, though the issue does not spell that out.
  - The escape format is the standard JSON-in-HTML one. p4 and v7c chose it unprompted.
- **What hides:** the per-request behaviour must be kept (a P2P test). Deleting the insertion fails that P2P and the first assert of `test_root_path_does_not_persist_across_requests`.
- **Existing regression tests cannot run in the competition env (measured).**
  - All 5 existing test files mentioning `root_path` fail at collection with `ModuleNotFoundError: No module named 'inline_snapshot'`: `test_deprecated_openapi_prefix.py` and `test_behind_a_proxy/test_tutorial001-004.py`.
  - Command: `SCR=... bash docs/forty_two/ground_truth/fastapi_tools/probes/regress_14986.sh` (pytest over `grep -rl root_path tests`). Output: `5 errors` for base, p4, v7 and b1024 alike.
  - More broadly, 295 of 564 test files in this tree import `inline_snapshot` or `dirty_equals`. Neither is in the Kaggle freeze (`eval/kaggle/g4-l4-v12-p312/pip_freeze.txt`; `scripts/build_kpar.sh` notes the same).
  - So "run the related existing tests" could not have caught the regression here.
- **Gold in a clean environment: yes (measured).** Before: 5 failed, 2 passed. After: 7 passed. The Kaggle oracle resolves it too (8.6 s).
- **Test cost (indicative):**

  | Step | Time |
  |---|---|
  | install | 0.4 s |
  | the 5 F2P tests | 0.62 s |
  | the touched files | 0.70 s |
  | full `tests/` | 5.1 s (296 collection errors, almost all the missing snapshot and equality helpers) |

## What the six box runs did

| run (bundle) | secs / calls | model s (calls) | tools s | final patch | clean env (of 7) |
|---|---|---|---|---|---|
| p4 (v5h2) | 114 / 35 | 106.4 (40) | 2.5 | **deleted** the root_path insertion + correct `<` escaping | 5 pass: escape fixed, root_path broken |
| p4_v7 (v7) | 73 / 17 | 64.2 (22) | 2.3 | deleted the insertion + other escaping | 3 pass |
| p4_v7c (v7c) | 92 / 20 | 84.5 (25) | 2.1 | deleted the insertion + correct escaping | 5 pass |
| p4_v7d (v7d) | 255 / 70 (budget) | 243.1 (76) | 3.0 | deleted the insertion + other escaping (9 identical `edit.py` retries on a `<script>` block) | 3 pass |
| p4_b1024 (v12-b1024) | 197 / 15 | 190.8 (17) | 0.5 | deleted the insertion + `json.dumps` on `url` and `oauth2RedirectUrl` (not the config values) | 3 pass |
| p4_v0t2 (v0-think) | 302 / 20 (time cap) | 237.9 (21) | 0.2 (+62.0 cut off at the cap) | **empty** | 2 pass (base) |

- Every run that edited `applications.py` removed the `servers.insert` block outright. Measured: `test_legitimate_root_path_still_appears` (P2P) fails for all 5.
- Their only check was `tests/test_local_docs.py` (p4, v7, v7c, b1024: 5 passed each, 0.3 to 0.4 s). It covers neither change.
- **b1024:** model calls of 39.8, 37.9 and 36.6 s; submitted at t=197.
- **v0t2:** a 69.1 s call and a 24.9 s compaction; no edit by the cap.
- **L4:** 0 of 12 L4 runs with 74 rows solved it. Both traces also ran `test_local_docs.py`. e74_v3 hit `ModuleNotFoundError` on `test_behind_a_proxy/test_tutorial001.py` (exit 2) twice.

**Where the time went (measured, six runs, 1,032.9 s):**

| | Seconds |
|---|---|
| model | 926.9 |
| tools | 10.6 |
| tail cut off by the cap | 62.0 |
| other | 33.4 |

p4's row has no end time in `results.jsonl`. Its window is anchored on its first proxy call (`start_estimated` in the timing JSON).

## Root cause, feasibility, lever

- **Root cause: WRONG_SEMANTICS.**
  - "do not store X" was implemented as "never emit X" in 5 of 5 edits. The escape half was done right by 2 runs.
  - The regression tests that would have caught the deletion exist but cannot be collected in the competition environment.
  - This agrees with the old diagnosis's mechanism. The new evidence is that the related-test gate it proposed is blocked by missing test dependencies.
- **Feasible in 5 minutes: maybe.** Measured: p4 and v7c were one hunk short (a per-request schema copy) at 92 to 114 s.
- **General levers:**
  1. **Prompt rule: "do not store, cache or persist X" means keep returning X per call and stop mutating shared or instance state.** Never satisfy it by deleting the feature. Check the output before and after, for the same input. This is cheap and applies to any repo.
  2. **When an existing test file fails at import with `ModuleNotFoundError` for a test-only helper** (`inline_snapshot`, `dirty_equals`), copy its asserts into a /tmp script instead of giving up on regression checks. This matters for every fastapi task in the hidden set, since about half the test files are affected (measured above).
  3. **Bound thinking per call** (v0t2: 69 s; b1024: three calls of 37 to 40 s).
