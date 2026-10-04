# v4h2g misses: what is still reachable, and which one change to run next (pre-registration draft)

Source run: `eval/kaggle/g4-l4-v4h2g-p312/` (bundle `submissions/v4h2g`, faithful 4xL4, 74 public tasks, **34 solved,
40 missed**). For each miss I read the problem statement, the gold `patch`, the `test_patch` (`data/tasks.jsonl`), the
agent's final patch (`results.jsonl`) and the trace (`traces.tar.gz`, extracted under `/private/tmp`). Class
definitions and the repro column follow `docs/v4h/WRONG_FIX_EVIDENCE.md` (A-F). For the 22 tasks that also appear in
that doc, the D and C calls carry over: they depend on the issue and the test, not on the agent. Where this run's patch
differs from v4's, the row was re-read. This is a read-only analysis: no runs, no network.

Comparison runs, all 74 tasks on the same 4xL4 harness: `g4-l4-v4h2f-p312` (28/74), `g4-l4-v4-wh28-p312` (27/74), and,
as extra context, `g4-l4-v4` (29), `g4-l4-v4h2-p312` (25) and `g4-l4-v9-eog` (29).

## Definitions (unchanged from WRONG_FIX_EVIDENCE.md)

- **A**: the issue states the behaviour and the fix contradicts it.
- **B**: partial; a second function or file in the gold is missing.
- **C**: the test checks an edge case or API detail that the issue does not state.
- **D**: title-only, or link-out. There is no spec offline.
- **E**: semantically right, but breaks on an implementation detail (wording, type, escaping).
- **F**: other, named in the row. Three kinds appear here:
  - loop/budget: a repetition loop used up the budget before a complete fix existed;
  - loop: the same, but no source edit was ever made;
  - edit thrash.

Repro: whether a repro built only from the issue text would fail on the final patch. `obs` means it was seen in the
trace, `inf` means it is inferred from reading the code.

The other columns:

- **taxonomy**: the class in `failure_taxonomy.json`.
- **other run solved**: which of the five other runs resolved the task.
- **calls / secs**: taken from `results.jsonl`.
- **repeats**: tool calls identical (same tool, same arguments) to an earlier call in the same task.
- **ran relevant test**: whether the hidden test's file existed at base and was run after the last source edit.
  `new-file` means the hidden test file does not exist at base, so it could not be run.

## 1. Per-task table (40 misses)

| id | class | taxonomy | other run solved | calls | secs | repeats | ran relevant test | repro | what was missing |
|---|---|---|---|---|---|---|---|---|---|
| fastapi_14419 | A | rfwf | v9-eog | 19 | 87 | 2 | new-file; other test run | yes (inf) | Same as v4. It unions sub-dep scopes into the cache key, which contradicts the title's rule. It used only 19 calls, so there was budget for a check. |
| fastapi_14986 | A | rfwf | - | 22 | 92 | 1 | new-file; other test run | no | Same as v4. It deleted the per-request root_path insertion, which the test needs, and escaped only part of the output. |
| rich_3180 | A | rfwf | v4 | 70 | 152 | 2 | yes, but the run hit BudgetExceeded | yes (inf) | The issue states the fold rule. The agent reversed `chop_cells` output and left `divide_line` alone. The locator alternated two `python -c` probes for 63 calls; the verifier's test run hit `BudgetExceeded`. |
| fastapi_14306 | B | rfwf | - | 70 | 193 | 27 | new-file; no test run | yes (inf) | Same as v4. `endpoint_context` was added to the exceptions, but nothing in `routing.py` passes it, so the issue's "After" output never appears. The fixer re-read `exceptions.py` 22x and hit 70 calls. |
| fastapi_14448 | B | rfwf | - | 70 | 298 | 38 | yes | unknowable | Rewrote the `models.py` unwrap loops. The gold also swaps the async-gen/gen order in `utils._solve_generator`, the consumer of those properties. The fixer ran one `python -c` 30x and hit 70 calls. |
| fastapi_14487 | C | wrong_files | - | 47 | 128 | 7 | no | no | Wrong file this time (edited the `.md` and not `docs_src/.../tutorial004.py`). The binding problem is the v4 C: the test asserts an exact `Validation errors:` format. |
| rich_3061 | C | rfwf | - | 21 | 71 | 3 | yes | yes (inf) | Same as v4. The test asserts a new `Text.extend_style` API. The agent passed `part.style` (also A). |
| rich_3535 | C | rfwf | - | 18 | 75 | 1 | yes | no | Same as v4 (box-drawing range not stated). |
| rich_3676 | C | rfwf | v4-wh28 | 42 | 132 | 3 | no | no | The note renders (its `test_notes.py` shows it). The test asserts `stack.notes == [...]` (a list); the agent stores a str. |
| rich_3777 | C | rfwf | v4h2f, v4, v9-eog | 67 | 114 | 46 | no; other test run | no | The issue states only `TTY_INTERACTIVE=0`. The test also wants `"1"` to force interactive, mirroring the `TTY_COMPATIBLE` 0/1 handling a few lines above. The agent did `"0"` only. The locator alternated two greps 46x. |
| rich_3930 | C | rfwf | - | 70 | 278 | 50 | no | unknowable | Same as v4 (12.7k-line feature). The fixer re-read `cells.py` 40x. |
| fastapi_15280 | D | rfwf | - | 25 | 97 | 4 | new-file; no test run | unknowable | Title only (`@app.vibe()`). The gold is an April-Fool `raise FastAPIError("Are you kidding me?...")`. The agent aliased it to `get`. |
| fastapi_15661 | D | wrong_files | - | 64 | 175 | 32 | new-file; no test run | unknowable | Empty PR body (title + checklist). The test imports a new `scripts/prepare_release.py` (216 lines). The agent edited `add_latest_release_date.py`. |
| fastapi_15800 | D | crash | - | 70 | 190 | 137 | new-file; no test run | unknowable | Title only, 654-line feature. The locator made 74 identical calls in a row, then hit the 150-turn cap with an empty patch. |
| rich_3105 | D | no_patch | - | 33 | 127 | 10 | yes | unknowable | "Fix #3104" only. The test pins an exact `<code style="font-family:inherit">` HTML string. Empty patch. |
| rich_3468 | D | rfwf | - | 70 | 184 | 26 | no | unknowable | Same as v4 (exit code 1 on broken pipe is not stated). The locator used 64 calls. |
| rich_3470 | D | rfwf | - | 70 | 257 | 38 | before last edit only | unknowable | Title + link. The hidden test inverts an existing test (record must NOT include captured output). The locator ran one `python -c` 43x. |
| rich_3471 | D | rfwf | - | 15 | 50 | 1 | yes | unknowable | Same as v4. |
| rich_3472 | D | rfwf | - | 45 | 157 | 16 | yes | unknowable | Same as v4. |
| rich_3480 | D | timeout | - | 15 | 306 (timeout) | 2 | no | unknowable | Same as v4. Its repro ran `t.append(t)`, the infinite loop itself, and burned the 5 minutes on command timeouts (15 calls). Empty patch. |
| rich_3675 | D | rfwf | v4, v9-eog | 10 | 45 | 2 | yes | unknowable | Title + link. The test needs `"0"`/`"1"`/other semantics; the agent treated any value as a terminal. Solved by v4 and v9-eog, presumably from recall, since the spec is not in the text. |
| rich_3772 | D | rfwf | - | 70 | 309 | 57 | no | unknowable | Same as v4. The locator ran `python3 -c "def foo(n): foo(n); foo(1)"` 57x. |
| rich_3782 | D | rfwf | - | 16 | 70 | 1 | yes | unknowable | Same as v4. |
| rich_3934 | D | rfwf | - | 35 | 134 | 17 | yes | unknowable | Same as v4. |
| rich_3935 | D | wrong_files | - | 31 | 157 | 7 | no; other test run | unknowable | Title + link. The gold is in `table.py`; the agent edited `padding.py`. |
| rich_3938 | D | rfwf | - | 52 | 182 | 17 | yes | unknowable | Same as v4. |
| rich_3942 | D | no_patch | - | 61 | 159 | 42 | yes | unknowable | "Updates to Markdown styling". The test pins exact new style values. Empty patch after 35 repeated reads. |
| rich_3944 | D | wrong_files | - | 15 | 83 | 0 | no; other test run | unknowable | "fix fonts" + link. The gold makes unassigned codepoints width 1 in `cells.py`; the agent renamed the SVG font. |
| rich_3953 | D | rfwf | - | 69 | 185 | 47 | yes | unknowable | Same as v4. The fixer ran one `python -c split_graphemes` 45x. |
| rich_4006 | D | rfwf | - | 61 | 170 | 41 | yes | unknowable | Title + link. The test pins exact spans for ESC/ZWJ/VS16-only strings. The fixer re-read `cells.py` 33x. |
| rich_4075 | D | wrong_files | - | 35 | 141 | 4 | no; other test run | unknowable | Title + link. The test is `print(end="!")` -> `"!"`. The agent edited `Text.split`. |
| rich_4076 | D | wrong_files | - | 39 | 140 | 8 | no; other test run | unknowable | Title + link. The gold is in `ansi.py`; the agent edited `syntax.py`. |
| rich_4079 | D | rfwf | - | 65 | 182 | 16 | yes | unknowable | Title + link. The test pins exact ANSI output for inline code in a table cell. |
| fastapi_14258 | E | rfwf | - | 67 | 138 | 40 | new-file; other test run | no | Right place, but it raises `FastAPIError("A router cannot include itself")`. The test wants `AssertionError` and an exact message that the issue never gives. The fixer re-read the same 5 lines 36x. |
| fastapi_14479 | E | rfwf | - | 19 | 118 | 1 | no; other test run | no | Same as v4. It copied the issue's wording, and the test asserts different wording. It also committed `tests/test_query_param_error.py`. |
| fastapi_15588 | E | rfwf | - | 26 | 231 | 3 | yes | no | Same as v4: message wording (`SSE field must not contain newline characters`, where the test wants `SSE 'event' must be a single line`). |
| rich_3278 | E | rfwf | v4-wh28, v4 | 59 | 308 (timeout) | 25 | before last edit only | yes (obs) | The issue states the rule (ignore `\x1b0`-`\x1b?`), and the change is 1 line. Over-escaped heredoc (`\\x1b`) broke the raw regex. Its own `python -c` after the last edit raised a Traceback; it repeated an identical edit 6x ("NO CHANGE") and timed out in the verifier. |
| fastapi_13920 | F | rfwf | - | 70 | 163 | 28 | new-file; no test run | yes (inf) | F: loop/budget. Locator ran the same `grep get_type_hints` 22x and used 60 calls; the fixer added only a `TypeAliasType` import and nothing uses it. Even with budget left, the v4 E risk remains: the issue names typing-inspection `is_typealiastype`. |
| fastapi_15589 | F | wrong_files | v4-wh28, v9-eog | 57 | 318 (timeout) | 18 | no | yes (obs) | F: loop. The issue states the rule. Its own `repro.py` failed on base, then the fixer re-read `utils.py 790-825` 15x without editing source and timed out in the fixer. The patch is the scratch `repro.py` only. |
| rich_3052 | F | rfwf | - | 47 | 309 (timeout) | 28 | no | yes (inf) | F: edit thrash. 32 edits with literal `*,\n` in SEARCH blocks; a `--lines` replace deleted the `@classmethod @overload` decorators. It timed out in the fixer. C risk: the test wants the canonical choice returned (`"FoO"` -> `"foo"`), which the issue does not state. |

## 2. Counts

By class (40):

| class | n | ids |
|---|---|---|
| A, issue states it, fix contradicts | 3 | fastapi_14419, fastapi_14986, rich_3180 |
| B, partial | 2 | fastapi_14306, fastapi_14448 |
| C, unstated edge case / API | 6 | fastapi_14487, rich_3061, rich_3535, rich_3676, rich_3777, rich_3930 |
| D, title-only / link-out | 22 | fastapi_15280, fastapi_15661, fastapi_15800, rich_3105, 3468, 3470, 3471, 3472, 3480, 3675, 3772, 3782, 3934, 3935, 3938, 3942, 3944, 3953, 4006, 4075, 4076, 4079 |
| E, implementation detail | 4 | fastapi_14258, fastapi_14479, fastapi_15588 (all three: wording or type the issue does not give); rich_3278 (escaping, reachable) |
| F, other | 3 | fastapi_13920 (loop/budget), fastapi_15589 (loop, no source edit), rich_3052 (edit thrash) |

Reachability (40 = 7 + 5 + 28):

- **7 were solved by some other run**:
  - by v4h2f: rich_3777;
  - by v4-wh28: rich_3278, rich_3676, fastapi_15589;
  - only by the extra runs: rich_3180 (v4), rich_3675 (v4, v9-eog), fastapi_14419 (v9-eog).
  - Union with v4h2f and v4-wh28 only: 38/74. With all six runs: 41/74.
- **5 have enough in the issue text but were never solved by any of the six runs**: fastapi_13920, fastapi_14306,
  fastapi_14448, fastapi_14986, rich_3052.
- **28 look unreachable from the issue text and were never solved**: D 21 (all but rich_3675), C 4 (14487, 3061,
  3535, 3930), E-wording 3 (14258, 14479, 15588).

Budget and loops:

- **13 of the 40 ended at 65 or more of the 70 calls** (9 exactly at 70). Only 4 timed out: 15589, 3052, 3278, 3480.
  The call budget binds far more often than the 5 minutes; the mean on misses is about 170 s.
- **Repetition loops are the strongest trace marker of a miss.** 22 of the 40 misses repeat an identical tool call
  10 or more times; so do 3 of the 34 solved. Median repeats: 16 on misses, 2 on solved.
- The loops are sequential, one call per step, not parallel calls. Examples:
  - rich_3772 ran `python3 -c "def foo(n): foo(n); foo(1)"` 57 times;
  - fastapi_14258 read the same 5 lines 36 times;
  - rich_3953 ran one `python -c` 45 times.
- All three prompts already say "never repeat a call".
- By the kind of call repeated: mostly raw `run_command` (`python -c`, grep) and `read_file`. Repeats through the
  `/tmp/swe` helpers are significant only in rich_3052 (25), rich_3278 (7) and rich_4006 (6).
- 7 of the 12 non-unreachable rows have 10 or more repeats: 13920, 14306, 14448, 15589, 3052, 3278, 3777.

Ran relevant test (40):

- yes: 16. One of them, rich_3180, was refused with `BudgetExceeded`, so 15 really ran.
- `new-file`: 8 (the hidden test file does not exist at base).
- no, or only before the last edit: 16.

Of the 15 that did run, 13 are D/C rows: the existing tests pass on a wrong patch because the hidden tests are new.

Noise:

- v4h2f and v4h2g differ by one locator line, yet the pair splits 7 v4h2g-only solves against 1 v4h2f-only.
- GATE.md puts single-read noise at about 2.3 tasks.
- 5 v4h2g solves were solved by neither v4h2f nor v4-wh28: fastapi_9753, fastapi_5077, fastapi_14616, fastapi_11194
  and rich_3063. Expect some of them to flip back on any rerun.

## 3. Candidates, with upper bounds counted from rows

The bound counts the v4h2g misses where the mechanism would plausibly change the outcome. A row is counted only when:
the issue (or nearby code) holds the needed information; the mechanism fires inside the remaining calls; and nothing
else in the row binds.

| rank | candidate | bound | rows | why not more |
|---|---|---|---|---|
| 1 | **Sibling/caller sweep after the edit**: `git grep` the edited function, the changed expression and any new parameter; apply the same change to siblings and pass new params from producers | **3** | fastapi_14306 (new `endpoint_context` kwarg with no producer; the gold wires it in `routing.py`), fastapi_14448 (gold also changes the consumer `_solve_generator` of the edited properties), rich_3777 (mirror the `"1"` branch of the `TTY_COMPATIBLE` handling a few lines above) | 14306 and 14448 both hit 70 calls through read/`python -c` loops, so the sweep needs to run right after the edit, before any loop. 14448's consumer change (an order swap) is weak evidence. rich_3777 was already solved by 3 other runs, so it is partly noise. Two targets (14306, 14448) were never solved by any of six runs, so a flip there can be credited to the mechanism. It also protects fastapi_5077, a v4 B row (sibling `get_typed_return_annotation`), solved this run by neither v4h2f nor v4-wh28. |
| 2 | Temperature 0.2 (built as `v4h2gt`) | 7 up, at least 5 at risk | Up: the 7 rows solved by some other run (3777, 3278, 3676, 15589, 3180, 3675, 14419). At risk: the 5 v4h2g-only solves (9753, 5077, 14616, 11194, 3063). | This changes the whole distribution, so its sign cannot be bounded from rows. The 22 loop-heavy misses are the risk: lower temperature is the usual condition for repetition loops, which is an untested hypothesis here. The other-run solves at temperature 1.0 show these rows are reachable by sampling, not that 0.2 reaches them. |
| 3 | Verifier repro step (built as `v4h4g`) | **1** | fastapi_14419 (yes (inf); 19 calls used, so there was room) | 3278: already failing visibly, so nothing new. 15589 and 3052: the verifier never ran. 13920, 14306, 3180: no calls left. 14986, 3676, 3777, 15588, 14479: a repro of the stated behaviour passes. D rows: no example to build one from. GATE.md's bound of 6 was counted on v4h2f's misses, not on these. |
| 4 | Read git log / existing test names for title-only issues | at most 1, unverified | rich_3675 at most, and its other-run solves look like recall, not git log | The base commit has neither the linked issue nor the hidden tests. For rich_3470, the existing `test_capture_and_record` asserts the opposite of the hidden test, so reading tests would mislead. 21 of the 22 D rows stay out of reach. |
| 5 | Forced submit watchdog | **0** | none | The harness already grades the working-tree diff without `submit_patch`: 3052, 3278 and 15589 have patches although they never submitted. No timed-out or capped row had a better intermediate state. 3278's every edit was over-escaped, 3052's file was broken, 15589 never edited source, and 3480/15800 have no edit at all. |

Outside the list, but the largest mechanism in the evidence: **a repetition-loop breaker**. Its bound is 7 (the
7 loop-heavy rows that are not unreachable: 13920, 14306, 14448, 15589, 3052, 3278, 3777). A prompt line cannot do it,
because "never repeat a call" is already in all three prompts. A stdlib skill cannot do it either: the loops go through
`read_file` and raw `run_command`, which the helpers never see. The only helper-visible part is the repeated identical
`edit.py` calls in 3052 and 3278. An `edit.py` that answers a repeated identical call with "STOP: identical to call N"
covers only those 2 rows, and both have another binding problem (thrash, escaping). Before it can be ranked, someone
needs to check whether the Kaggle harness accepts ADK `before_tool_callback`s in the bundle. That check was not done
here.

## 4. Recommendation (pre-registration draft)

**Next single variable: the sibling/caller sweep, as one helper call in the fixer.**

v4h5g = v4h2g plus one fixer line and one stdlib helper `/tmp/swe/sweep.py`.

The helper:
- reads `git diff -U0`;
- extracts the edited function names, any newly added parameter names, and each changed source line, with
  whitespace normalised;
- runs `git grep -n -F` for each in non-test `.py` files;
- prints at most 20 hits that are outside the diff, as `path:line: text`.

The fixer line: *"After your last edit, run `python3 /tmp/swe/sweep.py` once. If it shows the same expression in
another function, or a caller that must pass a parameter you added, apply the same change there."* Nothing else
changes; the temperature stays at 1.0.

It is ranked above the two bundles that are already built for these reasons:
- **The largest one-sided bound.** It has the largest row-counted bound (3) of any candidate whose effect is
  one-directional.
- **Two targets free of sampling luck.** 2 of its 3 targets were never solved in six runs, so a flip there is
  attributable to the mechanism.
- **v4h4g is almost exhausted.** It has 1 row left on this population.
- **v4h2gt cannot be bounded.** Its effect is a distribution change with at least 5 solves at risk.

If the queue order cannot change, v4h2gt and v4h4g still run as pre-registered in GATE.md. This draft only claims that
the sweep has the better row evidence.

Pre-registration (written before any v4h5g run):

- **Population**: the same 74 tasks on the faithful 4xL4 harness, paired per task against v4h2g (34/74).
- **Target set**: T = {fastapi_14306, fastapi_14448, rich_3777}.
- **PASS** requires all of the following:
  - solved >= 36 (+2, the GATE.md slot threshold);
  - at least 1 flip in T where `sweep.py` was actually invoked in that task's trace;
  - crash rows <= 3;
  - mean secs <= 190;
  - `sweep.py` invoked in >= 30% of tasks (the mechanism ran).
- **FAIL**: anything else.
- **Ceiling, stated up front**: +3 through this mechanism on this population. Because the noise is 2.3 tasks, the T
  flips and their traces are the primary reading and the total count is secondary.
- **Losses**: report every v4h2g-pass to v4h5g-fail row. Losses among the 5 v4h2g-only solves (9753, 5077, 14616,
  11194, 3063) are read as noise. A loss elsewhere, whose trace shows the sweep caused an extra edit, counts against
  the mechanism.
- **Secondary measurements** (do not gate):
  - calls spent between the first edit and the sweep;
  - how often the sweep printed 0 hits;
  - how often the agent edited a sweep hit.

## 5. Unreachable rows, and why

The 28 rows that no change to prompt or helper reaches from the issue text:

- **D, 21 rows** (all D except rich_3675). The spec is a link or a title.
  - The hidden tests pin exact strings, spans, exit codes or styles: 3105 HTML, 3942 style values, 4079 ANSI,
    4006 spans, 3468 exit code 1.
  - Some pin a behaviour that inverts an existing test (3470), or an April-Fool raise (15280).
  - Some are new features of 216 to 654 lines (15661, 15800).
  - 6 of the 21 also went to the wrong file (15661, 3935, 3944, 4075, 4076, and 15800 with an empty patch), because the
    title names no code.
- **C, 4 rows**: the tests assert APIs the issue does not describe.
  - 3061: `Text.extend_style`.
  - 3930: a 12.7k-line grapheme feature (`split_text`, `CellSpan`).
  - 3535: the box-drawing range.
  - 14487: the exact `Validation errors:` / `Field:` format.
- **E-wording, 3 rows**: the test matches error text the issue omits (14258 `AssertionError` + exact message; 15588
  `SSE 'event' must be a single line`) or contradicts (14479).
- **Recall exceptions**: rich_3675 (D) and rich_3676/rich_3777 (C) were solved by other runs, presumably from the
  model's recall of rich, since the text does not carry the spec. They count as sampling-reachable, not text-reachable.

The practical ceiling on this population is about 34 + 12 = 46/74. Reaching it would take every non-unreachable row
flipping while no current solve is lost.

## 6. Method and commands

Scratch: `$S=/private/tmp/claude-501/-Users-carson-Projects/654244a3-b38c-45a0-96af-d7e5f0aac6ce/scratchpad/v4h2g`,
cwd `/Users/carson/Projects/gemma-swe-agent`.

```bash
mkdir -p $S/tr $S/trf $S/trw
tar -xzf eval/kaggle/g4-l4-v4h2g-p312/traces.tar.gz -C $S/tr     # also v4h2f -> trf, v4-wh28 -> trw
python3 $S/compact.py $S   # per-miss review files $S/c/<id>.txt (problem/gold/test/agent/trace) + $S/stats.json
python3 $S/table.py $S     # table rows; class + note are hand-assigned in the script's `ann` dict
diff -r submissions/v4h2g submissions/v4h4g; diff -r submissions/v4h2g submissions/v4h2gt   # one line each
```

- **Cross-run solves**: `resolved` from the six `results.jsonl` files, joined by `id`.
- **Repeats**: the count of tool calls whose (function name, sorted-JSON arguments) equals an earlier call in the
  same trace. Consecutive streaks were checked separately: at least 3 in a row in 19/40 misses against 2/34 solved;
  the same holds in v4h2f (22/46 against 1/28) and v4-wh28 (32/47 against 7/27).
- **Ran relevant test**: test files from the `+++ b/` headers of `test_patch`; a file is new when its first hunk is
  `@@ -0,0`. Then: was a `pytest`/`test.py` command naming the file (path or basename) run after the last `edit.py` or
  `write_file` on a non-test, non-scratch path?

Caveats:

- Gold patches over 5,000 characters and test patches over 4,500 were read only up to those caps.
- Every `yes (inf)` is a code-reading inference, not a run.
- The 14448 consumer-change link and the 3777 sibling-mirror link are judgment calls; they are the weakest two of the
  three sweep targets.
- "Ran relevant test" matches command strings, so a test run through an unusual wrapper could be missed.

## Addendum 2026-10-04 20:15 IST: callbacks are not available to a loop breaker
adk_submission compiles callbacks only from a closed CallbackRegistry supplied by the host; swegemma 0.2.7 registers
models only (swegemma/models/registry.py), never a CallbackRegistry, so a bundle cannot attach before_tool/after_tool
callbacks on the scorer. A loop breaker must live in what the agent calls: candidates (each needs its own test and an
L4 run): (1) fixer without read_file, reading through a /tmp/swe/view.py helper that keeps a per-task log in the
sandbox tmp and answers an exact repeat with "already shown above (lines X-Y); edit now" instead of the content;
(2) a lower per-stage budget by splitting the fixer into two stages with fresh context (include_contents: none), so a
loop in the first half cannot eat the second. Bound for either: 7 (rows in the table above).
