# Gap 3: the edit channel, measured by offline replay

Written 2026-09-28 (IST). Read-only. Nothing was submitted, pushed or started, and no money was spent. The only
network calls were HTTPS GETs of public files from `raw.githubusercontent.com` at each task's `base_commit`, used
for the 34 tasks that have no local snapshot. Scripts and intermediate data are in
`/private/tmp/claude-501/-Users-carson-Projects/654244a3-b38c-45a0-96af-d7e5f0aac6ce/scratchpad/gap3/`. The
files from this pass are `common.py`, `collect.py`, `fetch.py`, `replay.py`, `analyze1.py`, `analyze2.py`,
`analyze3.py`, `analyze_replace.py`, `shiftkind.py`, `shiftsim.py`, `viewsrc.py`, `stale2.py`, `chan_esc.py`,
`bsq2.py`, `extra_tiers.py`, `newcheck.py`, `newcheck2.py`, `timecost.py`, `pertask.py`, `rates.py`,
`final_compile.py` and `ladder_timing.py`. The `calls.jsonl`, `analyze4.py`, `analyze5.py`, `analyze_none.py`,
`minimal_policy.json` and `replay_out.json` files in the same folder are older and were not used here.

## Answer first

1. **v10 edit API: an anchored old/new edit sent through `run_command` as a quoted heredoc.** It retries with an
   unescape only after a failure, and it checks syntax on every write. Keep line ranges only as a guarded
   secondary mode: the model gives the expected first line, and the helper shows numbered lines. Do not build
   the edit API on line ranges alone.
2. **Unescape-on-failure is the only fallback that rescues anything.** It turns 356 of 659 edit_file "old_string
   not found" failures in p_v4, r_v4 and r_v9_eog into a unique match (54%; 67 of 137 distinct failures). A
   whitespace-normalized anchor rescues 0 more, because the harness already has whitespace tiers. Stripping pasted
   line numbers also rescues 0.
3. **The premise about heredoc bodies is mostly wrong.** Unescaping repairs **1 of 53** REVERTED `replace.py`
   bodies. The reverts are range-boundary miscounts. 35 of 53 compile if the range moves by 1 to 3 lines, and 30
   of the 33 reverts that came right after an unnumbered `read_file` are of this kind. Outside one looping task,
   heredoc bodies carry the `\"` escape signature in 1 of 107 bodies. The rate for edit_file old_strings is 37%.
4. **Stale line ranges did not occur.** Across 84 cases where a landed edit was followed by a `replace.py` call on
   the same file, 0 were confirmed stale.
5. **edit_file can be removed without losing edits, once one precondition holds: the helper must be installed.**
   All 1,079 replayed edit_file successes used the exact matcher, so a helper's exact tier reproduces them. But the
   helper was installed in only **27 of 51** r_v9_eog tasks (fastapi: 24 of 95 arm-task runs). Remove edit_file
   without guaranteeing the install, and about half the tasks would have no edit tool except write_file.

## 1. Method and validation

- **Base files.** 40 tasks come from `data/raw/snapshots/*.tgz`. The harness builds these with `git fast-export`
  up to `base_commit` (`data/HARNESS_README.md:263`). The other 34 tasks (fastapi, and rich tasks with no
   snapshot) come from GitHub raw at `base_commit`. All 266 base files were re-checked byte for byte: 138 against
   a fresh tar extract and 128 against a fresh download, with 0 differences. 303 more paths did not exist at base.
   These are scratch files or new modules the model created.
- **Replay** (`replay.py`, run with the repo venv so it imports the harness's own matcher,
  `adk_eval_core/editing/edit.py:308 apply_replacement`). Per task, file state starts at base and changes through
  edit_file (the harness matcher), write_file, and each `replace.py` invocation (the same splice as
  `helpers_v9/replace.py`). `read_file` outputs are checked against the state. A full read re-syncs a file. A
  shell write that names a tracked file marks it "dirty", and dirty files are excluded. The runs are p_v4, p_v6,
  p_v7 and p_v8 (fair pod runs, 74 tasks each), plus race 1: r_v4, r_v9_c, r_v9_eo, r_v9_eg, r_v9_og, r_v9_eog,
  c_v9_eg and c_v9_eog.
- **Validation.** For every edit_file call on a clean file with a known observation, the replayed outcome matched
  the observed one: p_v4 455/455, r_v4 313/313, r_v9_eog 232/233, r_v9_eo 261/262, p_v7 610/611. The only
  mismatches are budget-exhausted calls and full-width-bracket paths (`「rich/ansi.py」`), which my path normaliser
  strips and the harness does not. All 46 successful `replace.py` invocations printed a numbered region, and it
  matched the replayed file 46/46. The state model is faithful.
- **Scope note.** The fixer prompt for v9_eog (`submissions/v9_eog/prompts/fixer.md`) says to use edit_file
  first and switch to `replace.py` only after one failure. So `replace.py` calls are a selected, harder subset,
  and edit_file stayed dominant in race 1 (411 edit_file calls against 39 `replace.py` invocations in r_v9_eog).

## 2. edit_file "old_string not found": which fallback rescues what

Observed edit_file outcomes (single-call steps; "unknown" means a multi-call step whose observation cannot be
attributed):

| Run | calls | ok | not found | malformed (no old_string) | ambiguous | identical | unknown |
|---|---|---|---|---|---|---|---|
| p_v4 | 1,030 | 134 | 356 | 502 | 31 | 0 | 7 |
| r_v4 | 665 | 74 | 228 | 336 | 0 | 11 | 16 |
| r_v9_eog | 411 | 85 | 138 | 161 | 9 | 2 | 15 |

**Malformed calls cannot be replayed.** In 987 of the 999 malformed calls in these three runs, new_string ends
with a marker such as `` `,old_string: ``. In 399 of them nothing of the old text survives in the parsed
arguments. Section 2 counts only their time cost, and section 5 gives the channel-level fix.

Every policy was tested on the replayed file content at the moment of the call. "Rescue" means a unique match.

| Policy on the not-found calls (clean state) | p_v4 | r_v4 | r_v9_eog | 3 runs | all 12 runs |
|---|---|---|---|---|---|
| not-found calls evaluated | 294 | 228 | 137 | 659 | 2,220 |
| old_string contains an escape-like sequence | 281 | 219 | 130 | 630 | 1,995 |
| exact match (harness tiers, check) | 0 | 0 | 0 | 0 | 0 |
| **unescape once, then exact** | 158 | 127 | 70 | 355 | 1,044 |
| unescape once, then harness tiers | 158 | 128 | 70 | **356 (54%)** | 1,056 |
| whitespace-normalized anchor, raw | 0 | 0 | 0 | 0 | 0 |
| whitespace-normalized anchor after unescape | 158 | 128 | 70 | 356 (same set) | 1,057 |
| strip pasted line numbers | 0 | 0 | 0 | 0 | 0 |
| distinct failures (identical retries merged) | 53 | 38 | 46 | 137 | 486 |
| distinct failures rescued | 20 | 16 | 31 | **67 (49%)** | 233 |

The task asked for a test on the base file too. Measured against base content, unescape rescues 259 of 721
(36%). That count is lower because many anchors target text an earlier edit had already added. The replayed
state is the authoritative number.

**Why a whitespace-normalized anchor adds nothing.** The harness already runs exact, then rstrip/strip line
windows, then a token regex (`adk_eval_core/editing/edit.py:109, 138, 239`). Those later tiers almost never
fire: of 1,079 replayed edit_file successes in the 12 runs, 1,072 were `exact`, 2 `flexible` and 5 `regex`.

**new_string must be unescaped together with old_string.**
- In the three runs, 145 of the unescape rescues compile only with the unescaped new_string, and 3 only with the
  raw one.
- Across all 12 runs there are 206 distinct rescues where raw and unescaped new_string differ. Against the
  model's final landed patch, the unescaped version is closer in 73, the raw version in 5, and the rest tie or
  have no reference. Against the gold patch the split is 44 to 4.
- Where any version overlaps the final patch (133 cases), full unescape is best or tied in 126. Unescaping only
  the escape kinds that old_string needed is best or tied in 99, so it is worse. (`newcheck.py`,
  `newcheck2.py`)

**Syntax after a rescue.**
- 295 of the 356 rescued edits leave a compiling file. 32 more repair a file that did not compile before the
  edit. 61 break a file that compiled.
- 59 of those 61 come from one retry loop: p_v4 fastapi_15588 `fastapi/sse.py`, whose new_string mixes single-
  and double-escaped `\n` (step 42). The other two are r_v4 rich_3777 and rich_4076.
- A compile gate catches all of them.

**What is left after unescape** (303 calls, 62 distinct):
- 184 calls (18 distinct anchors) contain no anchor line at all, even after unescape. They are dominated by
  rich_3278's ANSI regex, where the model adds more backslashes on every retry (76 + 32 + 25 calls). Others have
  a trailing backtick, full-width brackets, or 2 to 3 levels of escaping.
- 84 calls have most lines present but one hallucinated line. Example: r_v9_eog fastapi_13920 step 49 repeats a
  line that is not in the file.
- 2 calls are ambiguous after unescape. `font-family: "Fira Code";` occurs twice in `rich/_export_format.py`.

Extra tiers on those 303 calls (`extra_tiers.py`):
- 2 to 3 rounds of unescape rescue 8 calls (5 distinct).
- Stripping stray delimiters (a trailing backtick, `「」`) rescues 3.
- A backslash-run-insensitive search locates the region in 173 calls (18 distinct). The new text's backslash
  count cannot be checked by compiling, so this tier should only show numbered lines, never write.

**Effect on tasks and on time** (`analyze3.py`, `timecost.py`, `pertask.py`):
- Identical retries: the 659 not-found calls are 137 distinct failures, so each failure repeats 4.8 times on
  average.
- Across the three runs, 43 of 96 failure episodes contain a rescuable call, where an episode is a run of failed
  attempts on one file before the next landed edit. Up to 374 later failed attempts fall inside those episodes.
- 8 episodes in 7 task-runs ended without any landed edit to that file. All 7 were unresolved.
- Across the 12 runs, 32 task-runs covering 17 distinct tasks ended this way. 13 of those tasks were never solved
  in any run. 4 are contested: rich_3454 solved 4 of 10 times, fastapi_14077 5/10, rich_3777 2/10 and
  fastapi_13537 6/10.
- Wall time, measured from step timestamps on H100:

| Run | agent time (s) | failed edit attempts (s) | share | malformed | not found | of which rescuable |
|---|---|---|---|---|---|---|
| p_v4 | 8,421 | 2,167 | 25.7% | 1,065 | 1,036 | 615 |
| r_v4 | 4,526 | 1,197 | 26.4% | 676 | 500 | 276 |
| r_v9_eog | 5,431 | 914 | 16.8% | 473 | 379 | 230 |
| r_v9_eo | 5,119 | 1,580 | 30.9% | 955 | 576 | 435 |

- Tasks with 10 or more failed edit calls resolved 0 of 11 times in r_v4, 1 of 8 in r_v9_eog and 1 of 10 in
  p_v4. That is a correlation; hard tasks may cause both.

## 3. `replace.py` REVERTED bodies: unescape fixes 1 of 53

Every `replace.py` invocation in race 1 (129 invocations; 3 commands chained 2 or 3 invocations):

| Arm | invocations | OK | REVERTED | can't open file | other | range error |
|---|---|---|---|---|---|---|
| r_v9_eog | 39 | 17 | 10 | 7 | 4 (wrapped inside `run.py "..."`; bash quoting broke) | 1 |
| r_v9_eo | 23 | 13 | 4 | 5 | 1 (budget exhausted) | 0 |
| r_v9_eg | 34 | 8 | 17 | 9 | 0 | 0 |
| c_v9_eg | 11 | 4 | 4 | 3 | 0 | 0 |
| c_v9_eog | 22 | 4 | 18 | 0 | 0 | 0 |
| **all** | **129** | **46** | **53** | **24** | **5** | **1** |

For each REVERTED body I spliced it into the replayed file (`analyze_replace.py`, `shiftkind.py`, `viewsrc.py`):
- **Unescape once, then compile: 1 of 53 become valid.** The one is r_v9_eog
  `trace_fastapi_13920.json` step 46 (`split(\".\")`), the example in the brief. 23 of the 53 bodies contain any
  escape-like sequence.
- **The same body with the range moved by 1 to 3 lines: 35 of 53 compile.** Of those, 24 need a 1-line move and
  6 a 2-line move. The failures are boundary miscounts: the range is too long at the end in 14 cases, too short
  at the end in 13, starts too late in 7 and too early in 3.
- Automatic re-ranging is not safe. Only 4 of the 35 have exactly one compiling shift, and 17 have two.
- **The source of the line numbers predicts the revert:**

| Model's last view of the file before the call | OK | REVERTED | reverts fixable by a 1-3 line shift |
|---|---|---|---|
| `read_file` (content is unnumbered; only `start_line` is given) | 31 | 33 | 30 |
| `replace.py`'s own numbered output | 13 | 18 | 4 (the other 14 are one content loop, below) |

- **Error kinds:**
  - "invalid decimal literal": 21, from cutting a triple-quoted HTML/CSS template in `rich/_export_format.py`.
  - "unexpected indent": 19.
  - Other indentation errors: 7.
  - Other syntax errors: 6, including one "unexpected character after line continuation".
- **Concentration:** the 53 reverts come from 15 task-files, and 3 of them account for 34: c_v9_eog rich_3944
  `tests/test_console.py` 18, r_v9_eg rich_3043 `_export_format.py` 11, and r_v9_eog rich_3043 5.
- **The c_v9_eog rich_3944 loop (18 reverts) is not escape corruption.**
  - 14 of the 18 bodies contain `\"`, 17 contain `\'` and 18 contain `\n`. All of them sit inside a single-quoted
    expected-HTML string literal, where they are legal Python.
  - 15 of the 18 fail with the same `IndentationError: unexpected indent (test_console.py, line 527)`.
  - Unescape fixes 0 of 18.
  - The edit targets a test file, and the graders discard test-file changes.

**Silent damage from line ranges.** 2 of the 46 OK invocations compiled but duplicated a boundary line. They are
r_v9_eo rich_4077 step 18 (`return self.__file.isatty()` twice) and r_v9_eog rich_3468 step 70 (`raise` twice).
A syntax gate cannot catch this.

## 4. Stale line ranges: not observed

`stale2.py` checked every case where a landed edit (edit_file or an OK `replace.py`) was followed by a
`replace.py` call on the same file. A case counts as a candidate when the edit changed the line count, the second
range starts after the edit, and no numbered view of the file came in between. The script then compared the
body's lines with the region at the given numbers and at the numbers shifted back by the edit's delta.

| pairs | same line count | second range before or inside the first edit | numbered view in between | candidates | stale | fresh | unclear |
|---|---|---|---|---|---|---|---|
| 84 | 29 | 30 | 8 | 17 (3 distinct situations) | 0 | 1 | 16 |

The 16 unclear cases are 15 retries in the c_v9_eog rich_3944 loop plus r_v9_eo rich_3043
`tests/test_console.py` step 43. The body matches the region under neither hypothesis. The line-number failure in
our data is miscounting from unnumbered views, not staleness. The literature T1 figure ("99.1% corrupted after a
1-line shift") describes a situation our traces did not produce. The sample is small, though: 46 OK
invocations.

## 5. Does the heredoc channel carry the escape corruption?

The signature is a line containing `\"`. It appears on 0.01% of lines in the repositories' own `.py` files (29
of 223,364 lines in the edited files).

| Channel (race 1, 7 arms) | items | items with `\"` or `\n` outside quotes | lines with `\"` |
|---|---|---|---|
| edit_file old_string | 1,411 | 518 (37%) | 511 of 7,197 (7.1%) |
| edit_file new_string (well-formed calls) | 1,409 | 407 (29%) | 456 of 8,849 |
| write_file content | 375 | 17 (5%) | 47 of 10,282 |
| **`replace.py` heredoc body** | **107** | **1 (1%)** | **1 of 1,059** |
| `replace.py` body, c_v9_eog rich_3944 loop only | 22 | 14 | 14 of 50 (legal inside the literal) |
| heredoc bodies in sw1_v1, sw1_v1_t10, sw1_v1_t10_low and sw1_v2 | 203 | 0 | 0 of 2,856 |

A line-level check (`chan_esc.py`) looks only at re-typed lines that contain an escape. For edit_file
old_strings, 457 of those lines match the file only after unescape and 46 match raw. For `replace.py` bodies the
split is 1 against 12.

Parsing points the same way. Across 16 runs, 1 of 682 heredoc-bearing `run_command` calls was malformed: r_v9_eo
used `run_command` as the argument name. For edit_file, 161 of 411 calls (39%) were malformed in r_v9_eog alone.
The 123 wrongly shaped `run_command` calls in r_v9_eog are a single rich_3472 loop that wrapped the arguments in
`{"description", "parameters"}`. That is schema confusion, not a string-parse failure.

**Conclusion.** Content the model types in a quoted heredoc is nearly free of the H4 escape corruption. The
unescape tier stays as a cheap fallback: it costs nothing when unused and fixed 1 of 53 reverts.

## 6. Can edit_file be removed without losing edits?

- **Parity:** every edit_file success was an exact match (1,072 of 1,079). The same old/new text sent to a
  helper whose first tier is an exact unique match lands identically. Per distinct attempt in the race-1 v9 arms,
  edit_file succeeded 65% of the time raw, and 82% with the unescape tier (`rates.py`). `replace.py` line ranges
  succeeded in 42 of 65 distinct attempts (65%), and those attempts come after an edit_file failure, so they are
  harder.
- **edit_file has no syntax gate.**
  - Across the 12 runs, 1,016 landed `.py` edits hit a file that compiled before the edit. 40 of them left it not
    compiling. Unescaping new_string would have fixed 13 of those.
  - 506 final task patches touch a non-test source file. In 13 of them that file does not compile under Python
    3.12, and all 13 tasks are unresolved.
  - 7 of the 13 errors are "unexpected character after line continuation character", which is the escape
    signature landing in source (`final_compile.py`).
- **Blocking precondition: the helper must exist.**
  - `run_skill_script` copies the skill into a fresh temp dir for each call
    (`google/adk/tools/skill_toolset.py:685`, `cwd=td`), so `run_command` can reach the helpers only after
    `install.py` has run.
  - The locator skipped the install, or the install call was itself corrupted, in 24 of 51 r_v9_eog tasks: 20
    had no install call and 4 failed.
  - Across the 5 r_v9 arms, the install succeeded in 24 of 95 fastapi runs and 97 of 160 rich runs.
  - Corrupted install arguments seen: `skill_name '"swe-tools"'`, `file_path 'install.py`,skill_name:'` and
    `file_path '":"'`.
  - Install status is decided by the task, not the arm. 18 tasks never install in any arm and 17 always do.
  - Within the 16 mixed tasks, resolution with and without helpers is the same: 3 better, 3 worse, 10 tied, mean
    +0.04.
  - So race 1 measured the helpers mostly on rich, on about half the tasks. It also explains the 24
    "can't open file" invocations above.
- **Sandbox rewrite (edge case).** The subprocess sandbox rewrites the literal `/tmp`, `/workspace`,
  `/usr/local/bin` and `/wheels` everywhere in command text, heredoc bodies included
  (`swegemma/sandbox/subprocess.py:441-479`). No edit content in the 12 runs contained those paths (0 of 13,445
  old/new strings), but the helper should map `$TMPDIR` and the sandbox workspace path back.

## 7. v10 edit API, as the data supports it

**Interface.** There is one helper. It is called directly from `run_command`, never wrapped in `run.py`: 4
r_v9_eog invocations broke bash quoting that way. The body is a quoted heredoc holding an old block and a new
block, separated by exactly one separator line. The separator must be checked, because
`rich_3942 tests/test_markdown.py` contains a bare `=======` line.

**Match ladder.** The helper tries each tier in order, stops at the first unique match, and refuses on multiple
matches:
1. exact;
2. unescape once, applied to old and new together (54% of not-found failures);
3. the harness's rstrip/strip/token tiers, reimplemented (they almost never fire, but they cost nothing);
4. strip stray backticks and `「」`;
5. unescape 2 to 3 times.

**On failure the helper never writes.** It prints the reason: 0 matches, or N matches with their line numbers. It
also prints up to two candidate regions with line numbers, found by line overlap or a backslash-insensitive
search, so the next call can use line-range mode with correct numbers.

**Line-range mode** takes `--start/--end` plus a required `--expect "<first line>"`, compared after whitespace
normalisation. If the line does not match, the helper refuses and prints lines ±5 with numbers. It does not
auto-shift, because only 4 of 35 fixable reverts had a single compiling shift. `read_file` output is unnumbered,
so give the fixer a numbered view, or print numbers from the helper itself.

**Syntax gate on every write.** Use in-memory `compile()`, not `py_compile` with `cfile="/tmp/_pyc_replace"`
(`helpers_v9/replace.py:28`), which writes to a host path shared across tasks. If compiling fails and the raw text
matched, try the unescaped new text once. Otherwise revert and print the error plus the numbered region. After
every OK write, print the new region with line numbers, as `replace.py` does now. Write atomically: a temp file,
then `os.replace`.

**Loop breaker.** Keep a hash of each failed request in `$TMPDIR/swe/`. On an identical second failure, the
helper replies with the candidate region and the line-range command instead of the same error. Identical retries
average 4.8 per failure in the three primary runs.

**Timing budget** (measured on this Mac over all 2,220 recorded not-found cases, files up to 5,694 lines;
`ladder_timing.py`):
- The full ladder takes 0.19 ms at the median, 5.9 ms at p95 and 32 ms at worst.
- `compile()` takes 0.43 ms at the median, 5.8 ms at p95 and 27.5 ms at worst.
- Budget: under 50 ms of helper work per call, plus Python start-up. UNVERIFIED on the Kaggle host CPU.

**Edge-case tests the helper needs:**
- 0, 1 and 2+ matches, both raw and after unescape.
- Empty old block, and old equal to new.
- CRLF files, a missing final newline, and tabs.
- Mixed escaping in new text: fastapi_15588's `"\\n"` next to `"\n"`.
- Legal `\"` inside a string literal. Unescape must stay a fallback, because 6 of the 12 OK `replace.py` bodies
  that contain escapes would stop compiling if unescaped.
- A separator line inside the content.
- Sandbox-rewritten paths in the body.
- Non-UTF-8 bytes, handled with `surrogateescape`.
- Non-`.py` targets (no compile gate; parse `.json`/`.toml` instead).
- Test-file targets: warn, because a test-file edit stopped the hidden test_patch from applying in 4 fair-run
  failures.
- The helper not installed: the fixer's first step must check for it, and every "can't open file" should trigger
  a re-install.

## 8. What this does not show

- **Heredoc format is untested (UNVERIFIED).** No run has put anchored old/new edits through a heredoc. The
  exact-match rate there should beat edit_file's 65% raw, given the 1% against 37% escape signature, but only a
  pod race can show it. The same goes for whether Gemma 4 31B follows a separator format within the budget.
- **Time freed is not the same as tasks gained.** Failed edits take 17 to 31% of agent time, and removing the
  malformed class alone frees 8.7% in r_v9_eog. How many hidden tasks that converts under the 5-minute L4 cap
  was not measured.
- **Lost-edit rescues touch only contested tasks.** 13 of the 17 tasks with a lost rescuable edit were never
  solved in any run. The direct gain is on the 4 contested tasks.
- The timings above come from H100 pod runs, not L4.

## Reproduce

```bash
S=/private/tmp/claude-501/-Users-carson-Projects/654244a3-b38c-45a0-96af-d7e5f0aac6ce/scratchpad/gap3
PY=/Users/carson/Projects/gemma-swe-agent/.venv/bin/python
python3 $S/collect.py && python3 $S/fetch.py          # base files: snapshots, then GitHub raw at base_commit
cd /Users/carson/Projects/gemma-swe-agent && $PY $S/replay.py   # about 20 s; writes $S/replay_events.jsonl and $S/stash/
cd $S && python3 analyze1.py && python3 rates.py && python3 analyze3.py && python3 timecost.py && python3 pertask.py
$PY analyze_replace.py && $PY shiftkind.py && $PY viewsrc.py && python3 stale2.py
$PY chan_esc.py && python3 bsq2.py && $PY extra_tiers.py && $PY newcheck.py && $PY newcheck2.py
$PY final_compile.py && $PY ladder_timing.py
```
