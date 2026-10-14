# fastapi_14616: `Json[list[str]]` with Form/Query/Header is read with `getlist()`

Sources:
- `docs/forty_two/ground_truth/fastapi_14616.json`: the ground truth, from `gt_fastapi.py fastapi_14616`.
- `docs/forty_two/ground_truth/fastapi_tools/trace_timing/fastapi_14616.json`: the per-run timing, from `tr_fastapi.py fastapi_14616`.

"Measured" means taken from one of those files. "Inferred" means a reading of them.

## Problem

- **Issue (PR text, with code):**
  - What happens: `Annotated[Json[list[str]], Form()]` fails with `JSON input should be string, bytes or bytearray`. FastAPI treats the field as a sequence and calls `values.getlist("items")`, which wraps the JSON string in a list.
  - The fix it describes: use `values.get()` for Json fields.
  - It names `getlist`, `Form()` and the Pydantic `FieldInfo.metadata` attribute.
- **Gold:** `fastapi/dependencies/utils.py`, 2 hunks, +10/-2 lines.
  - Import `Json`.
  - Add `_is_json_field(field)`: `any(type(item) is Json for item in field.field_info.metadata)`.
  - In `_get_multidict_value`, call `getlist` only when the field is not a Json field.
- **FAIL_TO_PASS (3, measured):** `tests/test_json_type.py::test_form_json_list`, `test_query_json_list` and `test_header_json_list`.
  - Each posts or gets `'["abc", "def"]'` through Form, Query or Header. It asserts a 200 response with body `["abc", "def"]`.
  - Before the fix all three return 422 `json_type`.
  - PASS_TO_PASS (1): `test_cookie_json_list`. Cookies are never read with `getlist`.

## Constraints

- **Budget:** 5 minutes. v12-b1024 and v0-think get 40 calls and v5h2/v7* get 70. 180 s per command.
- **What the issue gives away:** the exact function (`getlist`, one call site in `_get_multidict_value`) and the idea (skip `getlist` for Json).
- **What it hides:**
  1. **Query and Header are tested too.** The issue shows only Form. Any condition that narrows the fix to `params.Form` fails 2 of 3 tests (v7d did exactly this).
  2. **How `Json` appears in `field_info.metadata`.** It is an *instance*, which is why gold uses `type(item) is Json`.
     - `typing.get_args(Json[list[str]])` shows the *class*. That reconstruction misled two runs.
     - `"json" in metadata` and `m.__name__ == "Json"` are both False on the real object.
     - `isinstance(item, Json)` works, as the L4 v12 patch shows. So does "any metadata at all" (the L4 v4h2g patch).
  - No exact string or new public name is hidden.
- **Gold in a clean environment: yes (measured).** Kaggle-parity venv, harness pytest line: before, 3 failed and 1 passed; after, 4 passed. The Kaggle oracle also resolves it (8.9 s, `eval/kaggle/oracle_all/results.jsonl`).
  - The python-multipart problem in the old diagnosis does not apply to these box runs. They exit 1 (assertion failures, not collection errors), and my clean env reproduces their failures exactly.
- **Test cost (indicative: macOS arm64, Python 3.12.14, warm uv cache):**

  | Step | Time |
  |---|---|
  | install | 1.1 s |
  | the 3 F2P tests | 0.75 s |
  | the touched file | 0.74 s |
  | full `tests/` | 9.2 s (2,880 passed, 4 failed, 127 errors: modules the parity env lacks) |

  Verification is nearly free against 300 s.

## What the six box runs did

| run (bundle) | secs / calls | model s (calls) | tools s | final state | clean env |
|---|---|---|---|---|---|
| p4 (v5h2) | 164 / 70 (budget) | 154.6 (77) | 2.3 | right function, predicate `"json" in field_info.metadata` | 3 F2P fail |
| p4_v7 (v7) | 117 / 70 (budget) | 107.1 (79) | 2.2 | **empty patch** | 3 F2P fail |
| p4_v7c (v7c) | 255 / 70 (budget) | 243.9 (77) | 3.8 | right function, predicate `m.__name__ == "Json"` | 3 F2P fail |
| p4_v7d (v7d) | 305 / 68 (time cap) | 286.1 (72) | 9.5 | right function, narrowed to `params.Form` | form passes; query and header fail |
| p4_b1024 (v12-b1024) | 305 / 14 (time cap) | 296.8 (30) | 4.2 | only `reproduce_issue.py`, no source edit | 3 F2P fail |
| p4_v0t2 (v0-think) | 305 / 26 (time cap) | 298.6 (28) | 1.3 | `is_sequence_field` in `_compat/v2.py`, plus 4 debug scripts | 3 F2P fail |

Measured from the trace timelines:

- **p4.**
  - The locator lost 5 calls to a parser-corrupted `read_file` (`filepath` arrived as ``utils.py`,start_line:729,end_line:923``).
  - It then ran `grep -n "Json" fastapi/dependencies/utils.py` (exit 1, no match) **24 times in a row**, t=48 to 82 s: 25.7 s of model time.
  - The fixer wrote the wrong predicate at t=124. The verifier hit the 70-call budget at t=153 before running anything.
- **p4_v7.** The locator repeated `git ls-files | grep "fastapi/internal"` **60 times**: t=21 to 80 s, 58.4 s of model time. The budget ran out with no edit.
- **p4_v7c.**
  - The locator used 44 search calls and reported at t=186.
  - The fixer's first edit landed at t=206. At t=214 a `/tmp` repro of the issue example failed.
  - It then probed `typing.get_args(Json[list[str]])`, which shows the class, so it never saw the instance.
  - It re-edited at t=231 with the same mistake. The verifier had no budget left at t=252.
  - A 15.1 s compaction call came at t=43.
- **p4_v7d.**
  - It edited the right line and narrowed it to Form. Its Form-only repro passed at t=268 and t=301.
  - The time cap stopped it at 305 s, before submit. The harness's fallback diff carried the edit, so it was graded.
  - Its slowest model call took 45.5 s. Two compaction calls took 30.7 s together.
- **p4_b1024.**
  - Located and read the right code in 5 calls (t=10 to 33 s), then ran one probe (t=60).
  - From t=82 to 225 it sent the **same `write_file` call 14 times**. Every one came back `mandatory input parameters are not present: filepath`: the tool-call parser drops `filepath` from a long `content` argument.
  - That is 152.8 s of model time, at about 10 s a call, for 0.1 s of tool time.
  - At t=203 a `printf` repro had broken quoting. At t=236 a `cat <<EOF` repro worked.
  - It never edited the source. A 24.7 s compaction came at t=259, and the time cap at 305 s.
- **p4_v0t2.**
  - Wrote 4 debug scripts into /workspace, each with a 22 to 44 s model call (t=73 to 167).
  - It learned `metadata=[Json]` and `is_sequence_field: True` at t=168. Then a 34.3 s compaction followed.
  - It edited `is_sequence_field` at t=274 to 280, but its predicate still returned True (debug at t=282). The time cap hit with the scratch files still in the patch.
- **What the L4 solvers did differently.**
  - Of the 12 L4 runs with 74 rows, 4 resolved it: e74_v3, g4-l4-v12, g4-l4-v4h2 and g4-l4-v4h2g. All 4 patches re-verify in my env.
  - Each used a predicate that is true on the real metadata item: `isinstance(item, Json)` (v12), "any metadata" (v4h2g), or a name check on the instance.
  - e74_v3, the only traced solver, wrote its own pytest file under `tests/` and ran it 6 times (t=71 to 203 s) until it passed. It ran the real code path, not a reconstruction of the annotation. Its test file is discarded by the grader and harmless.

**Where the time went (measured, six runs, 1,450 s):**

| | Seconds |
|---|---|
| model calls | 1,387.1 |
| tool runtime | 23.3 |
| other (harness) | 39.7 |

Among the model time:
- Repeated identical calls: 152.8 s (b1024's `write_file`), 58.4 s (v7) and 25.7 s (p4).
- Compaction-like summariser calls: 104.8 s.
- Single thinking calls of 20 to 45 s: v0t2, b1024 and v7d.

## Root cause, feasibility, lever

- **Root cause: WRONG_SEMANTICS.**
  - The right hunk was found in 4 of 6 runs. The predicate was false on the real `FieldInfo.metadata` item (p4, v7c, v0t2), or it was narrowed to the issue's one example (v7d).
  - Two runs never reached a fix: v7 and p4 lost their budgets to search loops, and b1024 to the dropped `write_file` argument (an EDIT_TOOL_FAILURE).
  - This corrects the old diagnosis (ENV plus location variance): on the box the env is not the cause, and the location was mostly right.
- **Feasible in 5 minutes: yes.**
  - Measured: 4 of 12 L4 runs resolved it, and gold is 10 lines in a function the issue names.
  - A run that edits the right line by t=100 s still has about 3 minutes for one end-to-end check (0.75 s of tool time here).
- **General levers, in order of seconds recovered here:**
  1. **Never resend a call that just failed identically.** On the second identical tool error, the agent or a tool wrapper must change approach. Use `run_command` with `cat > /tmp/x.py <<'EOF'` instead of `write_file` for scratch files, or drop `write_file` from the tool list. Here that recovers 153 + 58 + 26 s.
  2. **Check a fix on the real code path, not a reconstruction.** Rule: "when the fix depends on a type or marker check, assert it by running the issue's example through the public API after the edit. Do not run `typing.get_args` on a hand-built annotation." This applies to any repo.
  3. **Do not narrow a shared helper's fix to the issue's one example.** No `isinstance(..., Form)` guard when the changed function serves every parameter kind. One prompt line.
  4. **Keep scratch scripts in /tmp.** v0t2's patch carried 4 debug files. They are harmless to grading here, but they cost calls and context.
