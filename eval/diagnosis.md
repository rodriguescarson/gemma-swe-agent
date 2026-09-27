# Never-solved and contested failure diagnosis

Offline, from the four fair pod runs (`eval/eval3/eval/runs/p_v4,p_v6,p_v7,p_v8`, 74 tasks each). Contested solved/failed sets also use Kaggle `e74_v2`, `e74_v3` and sqlite `v3_conc8`, `v4_conc8`. Per-task detail is in `eval/diagnosis_never_solved.json`.

## Corrections to the inputs

- **fastapi_5624 was solved.** `v8_fair` resolved it with the 1-line gold fix, so it is contested, not never-solved.
- **The pod eval env hides some solves.**
  - `python-multipart` is missing, so fastapi_11194, fastapi_13537 and fastapi_14616 fail at test collection in every fair run.
  - The installed pygments version makes the **gold** patch fail on rich_4079 and rich_3782 (`eval/runs/oracle1`).
  - On those tasks the agent patches look correct:
    - fastapi_11194: v6 and v7 are semantically identical to gold.
    - rich_4079: v6 and v7 produce the same output as gold.
    - rich_3782: v7 fails the same 8 tests as gold and passes the target test.
  - So the fair runs likely undercount v6 and v7 by 2 to 3 tasks.
- **Four contested tasks are spurious.** fastapi_14786, fastapi_14372, requests_6644 and rich_3067 are solved by all 8 tracked configs. They only fail in no-patch baselines or older sweep runs.

## Sub-cause counts (never-solved, n=39)

| Sub-cause | Count | fastapi | rich | Meaning |
|---|---|---|---|---|
| HIDDEN_SPEC | 9 | 4 | 5 | Test needs an exact string, a new API name or behaviour that only the test or gold reveals |
| WRONG_SEMANTICS | 7 | 2 | 5 | Right file/hunk, but the fix is wrong or partial |
| UNDERSPECIFIED_ISSUE | 6 | 0 | 6 | Issue is only a title plus a link; wrong file, or the cause can't be inferred |
| EDIT_TOOL_FAILURE | 5 | 1 | 4 | Right place and idea, but edit_file failures or corrupting rewrites used up the budget |
| FEATURE_TOO_LARGE | 4 | 3 | 1 | Gold is 121 to 12,170 lines, or needs an API defined only in the tests |
| ENV_BLOCKED_LOCAL | 3 | 1 | 2 | Pod env can't pass the gold patch; the agent patch is probably right |
| HANG_INFINITE_LOOP | 3 | 0 | 3 | Infinite-loop bug; the repro or verification hangs (exit 124) |
| WRONG_LOCATION | 2 | 2 | 0 | Right concept, wrong function or file, in a well-specified issue |

Split by repo: 26 rich and 13 fastapi. rich has all 6 UNDERSPECIFIED tasks: short maintainer PRs whose title is "Fixes #NNNN".

Feasibility in 5 minutes: **yes 11** (3 of them are ENV_BLOCKED and already likely solved), **maybe 13**, **no 15**.

Cross-cutting, over the 155 failing never-solved runs (39×4, minus fastapi_5624 in v8):

| Pattern | Runs |
|---|---|
| No pytest call at all | 78 |
| Empty patch | 40 |
| ≥20 failed edit_file calls (17 tasks) | 32 |
| Session timeout | 18 |
| Context-window overflow | 13 |
| Verification hang | 9 |

The failed edit calls are of two kinds:
- `FileEditError`: old_string not found, mostly double-escaped `\uXXXX`, `\x1b` or `\n` in regex or string lines.
- `mandatory input parameters missing`: malformed multi-line arguments.

Both repeat 60 to 200 times per run.

## Top levers, ranked by tasks they could plausibly flip

1. **Robust edit tool and an edit-loop breaker.** Plausible flips: 5 never-solved + 7 contested = 12.
   - Change:
     - Tolerate or repair escaped old_string.
     - Add a line-range replace.
     - Validate the arguments and explain the error once.
     - After 3 identical failures, force a scripted rewrite.
     - Run `py_compile` and an import check after every edit, and auto-revert on SyntaxError.
   - Never-solved: fastapi_15588, rich_3535, rich_3052, rich_3278, rich_3043.
   - Contested failing runs: fastapi_14851, fastapi_9753, fastapi_14077, rich_3882, rich_3777, rich_3454, rich_3063.
   - It also turns SyntaxErrors into partial passes on fastapi_14306 and fastapi_15280, but won't solve them.
2. **Context-window guard.** Plausible flips: 1 never-solved + 9 contested, of which 5 aren't covered by lever 1.
   - Change: truncate observations (especially ANSI and long repro output), evict old turns before 28k, and cap repeated identical commands.
   - Overflow hit 13 never-solved runs and 12 contested runs.
   - Tasks: fastapi_5624, fastapi_15589, fastapi_14851, fastapi_9753, fastapi_5077, rich_3518, rich_3676, rich_3777, rich_3454, fastapi_13537.
3. **Repro/test gate before submit.** Plausible flips: 3 never-solved + 6 contested = 9.
   - Change:
     - Run the existing test file for each edited module, plus the agent's own repro.
     - Refuse or revert on new failures.
     - Never modify `tests/`.
     - Delete scratch files.
   - Never-solved: rich_4075, rich_3934, fastapi_13920 (plus the regressions on 15588 and 3043).
   - Contested: rich_3894, rich_3718, rich_3454 (v6 edited tests/, so test_patch failed to apply), fastapi_9425, rich_3506, rich_3521.
   - Current behaviour: 78/155 failing runs never ran pytest. v4 on rich_3934 and rich_3043 ran tests, saw failures, and submitted anyway.
4. **Fix the pod eval env (measurement, not agent).** Mis-scored tasks: 3 never-solved + 2 contested = 5.
   - Change: install `python-multipart` and pin pygments to Kaggle's version.
   - Tasks: fastapi_11194, rich_4079, rich_3782, fastapi_13537, fastapi_14616.
   - Do this first. It is cheap and it changes the v4 vs v6/v7 comparison.

Smaller levers:
- **Timeouts on commands and tests** (`timeout 20`, reporting "TIMEOUT = still looping"), plus a "fix the sibling site" grep. Plausible flips: 3, namely rich_3480 (yes), rich_4006 and rich_3772. It also stops the fastapi_14258 v4 hang.
- **Title-to-identifier grep**, e.g. "padding width" to `_get_padding_width`, "proxy isatty" to `FileProxy.isatty`. Plausible flips: rich_3935, rich_4077 (contested), and possibly rich_4076.

## Realistically out of reach (15, feasible=no)

- **FEATURE_TOO_LARGE (4):** fastapi_15661, fastapi_14306, rich_3930, fastapi_15800.
- **HIDDEN_SPEC (7):**
  - Exact strings: fastapi_14258, fastapi_14487, fastapi_15280 ("Are you kidding me").
  - fastapi_14479: the issue text shows a different message from the one the test expects, and all 4 runs copied the issue's wording.
  - Test-only APIs: rich_3938 (`Segment.split_lines_terminator`), rich_3061 (`Text.extend_style`).
  - Taste-defined style values: rich_3942.
- **UNDERSPECIFIED (3):** rich_3944, rich_3471, rich_3105.
- **Large two-file rewrite (1):** rich_3180.

## Contested variance

Mostly infrastructure, not reasoning: context overflow or edit-tool failure 11, missing test gate 5, env 2, location sampling 3 (rich_4077, fastapi_9753, fastapi_14616), partial multi-hunk 2 (fastapi_5077, fastapi_14419). The rest fail only on Kaggle, conc8 or baselines. Levers 1 to 3 target this variance.
