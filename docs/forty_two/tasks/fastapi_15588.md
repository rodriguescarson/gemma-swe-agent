# fastapi_15588: reject multi-line `event` and `id` in Server-Sent Events

Sources:
- `docs/forty_two/ground_truth/fastapi_15588.json`: the ground truth, from `gt_fastapi.py`.
- `docs/forty_two/ground_truth/fastapi_tools/trace_timing/fastapi_15588.json`: the per-run timing, from `tr_fastapi.py`.

"Measured" means taken from those files. "Inferred" means a reading of them.

## Problem

- **Issue (PR text).** "Validate Server Sent Event fields to avoid applications from sending broken data". If an app sets an `id` or `event` with multi-line content, FastAPI should treat it as a server error.
  - It gives no error text.
- **Gold:** `fastapi/sse.py`, 2 hunks, +17/-4 lines.
  - Add `_check_single_line(v, field_name)`, raising `ValueError(f"SSE '{field_name}' must be a single line")` on `\r` or `\n`.
  - An `AfterValidator` on `event`. The existing `id` validator (null characters) also calls it.
- **FAIL_TO_PASS (6, measured):** `tests/test_sse.py::test_server_sent_event_single_line_fields_reject_newlines[...]`, for {event, id} × {`\n`, `\r`, `\r\n`}. Each uses `pytest.raises(ValueError, match=f"SSE '{field_name}' must be a single line")`.
  - **PASS_TO_PASS (18):** the rest of `tests/test_sse.py`.

## Constraints

- **Budget:** 5 minutes. 40 calls (v12-b1024, v0-think) or 70 calls (older bundles). 180 s per command.
- **Hidden spec:** the message wording `must be a single line`.
  - The behaviour (reject `\r`/`\n` in `event` and `id` with a `ValueError`) is fully specified.
  - The neighbouring convention in the same file, `"SSE 'id' must not contain null characters"`, leads naturally to `"SSE 'event' must not contain newlines"`. That is what v0t2 wrote, and it does not match.
- **Gold in a clean environment: yes (measured).** Before: 18 passed, 6 failed. After: 24 passed. The Kaggle oracle resolves it too (10.2 s).
- **Test cost (indicative):**

  | Step | Time |
  |---|---|
  | install | 0.4 s |
  | the 6 F2P cases | 0.67 s |
  | `tests/test_sse.py` | 1.4 s |
  | full `tests/` | 5.8 s |

## What the six box runs did

Every patch is **behaviourally correct**: newlines are rejected in both fields with a `ValueError`, and all 18 P2P tests still pass. Every patch **fails all 6 F2P cases on the regex alone** (`agent_patches_reverified`: 18 passed, 6 failed, each `Regex pattern did not match`).

The messages the six runs chose (counted from the patches):

| messages | count |
|---|---|
| `"SSE field must not contain newline characters"` | 3 |
| `"SSE field must not contain newlines"` | 1 |
| `"SSE field must not contain null or newline characters"` | 1 |
| `"SSE 'event' / 'id' must not contain newlines"` | 1 (v0t2) |

| run (bundle) | secs / calls | model s (calls) | tools s | check it ran |
|---|---|---|---|---|
| p4 (v5h2) | 107 / 21 | 98.1 (26) | 2.8 | helper test run |
| p4_v7 (v7) | 82 / 17 | 69.8 (22) | 3.8 | `timeout 30 pytest tests/test_sse.py`: 18 passed |
| p4_v7c (v7c) | 114 / 19 | 103.5 (24) | 4.0 | the same: 18 passed |
| p4_v7d (v7d) | 143 / 17 | 130.4 (22) | 4.5 | its own /tmp newline test + `tests/test_sse.py` |
| p4_b1024 (v12-b1024) | 223 / 9 | 216.7 (12) | 0.4 | one python check |
| p4_v0t2 (v0-think) | 306 / 15 (time cap) | 244.4 (16) | 0.1 | none |

- **b1024** used only 9 tool calls in 223 s. Its model calls took 47.8, 42.6, 37.9 and 22.3 s.
- **v0t2:** calls of 61.6 and 47.7 s, then a call cut off by the cap (61 s of "other"). Its edit was in place, and the fallback diff was graded.
- **L4:** 0 of 12 L4 runs with 74 rows solved it. Both traced runs passed `tests/test_sse.py` with their own messages. e74_v3 also repeated a corrupted `read_file` 47 times.

**Where the time went (measured, six runs, 975.2 s):**

| | Seconds |
|---|---|
| model | 862.9 |
| tools | 15.6 |
| other (mostly v0t2's call cut off at the cap) | 96.7 |

## Root cause, feasibility, lever

- **Root cause: HIDDEN_SPEC** (an exact error message).
  - **This corrects the old diagnosis** (EDIT_TOOL_FAILURE, feasible yes). That diagnosis was based on older pod runs. On these six box runs the edit tool worked, and every patch implements the behaviour correctly and keeps all 18 existing tests green. They differ from gold only in the message text, which the test pins with `match=`.
- **Feasible in 5 minutes: no.** `must be a single line` is one of many equally natural phrasings. The file's own convention points elsewhere.
- **Lever: none realistic for the text.** Two notes for the levers file:
  1. This is the clearest case in the batch where the agent's work was right and the scoring hinges on wording. It belongs in any estimate of the solve-rate ceiling, not in agent-behaviour levers.
  2. b1024's 9 calls in 223 s (40 to 48 s per call) are the same per-call thinking cost seen across the batch.
