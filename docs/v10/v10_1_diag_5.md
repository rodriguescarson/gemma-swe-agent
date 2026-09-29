# v10.1 diagnosis 5: fix quality (race 2 round 1)

Scope: read-only diagnosis of why v10's solve rate stayed flat (v10 25/74, v9_eog 24/74, paired 6-5) once the plumbing
KPIs passed. Nothing in `submissions/` was changed. Traces are `eval/race2/eval/runs/<arm>/traces/trace_<id>.json`;
`#N` is the ATIF `step_id`. Gold patches and hidden-test demands come from `data/tasks.jsonl` and
`research/task_catalog.json`. Analysis scripts (re-runnable in seconds) are in the session scratchpad
`/private/tmp/claude-501/-Users-carson-Projects/654244a3-b38c-45a0-96af-d7e5f0aac6ce/scratchpad/d5/`
(`table.py`, `verd.py`, `stages.py`, `leak.py`, `q2.py`, `rep.py`, `cost.py`, `plans.py`, `dump.py`).

L4 time model used throughout (`research/time_model.md`): 1.4 s per LLM step plus 35 ms per output token, plus
0.65-0.92 ms per new prompt token for large tool outputs. Call sizes are measured on the 74 v10 traces.

## 0. Bottom line

1. **Paired result.** 19 both, 6 v10-only, 5 v9-only, union 30. The 11 discordant tasks split cleanly:
   - v10's 6 wins: 2 from the new edit and hygiene channels (`rich_3454`, `fastapi_14077`), 4 from fix-quality
     variance, two of which ended with a RED verdict (`fastapi_5624`, `fastapi_15589`).
   - v9's 5 wins: **2 from a new v10 plumbing bug that no race-2 KPI measures** (`fastapi_14873`, `fastapi_13537`), 3
     from fix quality (`fastapi_9425`, `rich_3777`, `rich_3676`: wrong location or wrong layer).
2. **New plumbing bug: helper names emitted as tool names.** 29 leaked tool calls in 20 tasks (fixer 14, verifier 12,
   locator 3), plus one crash (`fastapi_13537`, tool `view.py` not found). v9_eog: 0. The model writes
   `<|tool_call>call:python3 /tmp/swe/status.py<tool_call|>`, the parser cannot accept `python3 /tmp/...` as a function
   name, the step becomes a text reply, and a text reply ends the stage. The verifier's first step (`status.py`) leaked
   in 9 tasks, so the repair stage never ran there (5 of the 9 were lost). This must be fixed before any fix-quality
   A/B, or the A/B measures the leak.
3. **Fix quality, where the gold file was edited.** 32 of 49 v10 failures edited a gold file; 18 of those are feasible
   (not infeasible, hidden_spec or env). Mechanisms: 7 partial (a sibling site, a second linked bug or a second layer
   missed), 6 fixed the wrong behaviour because the claim misread or skipped the spec, 3 edit-channel corruptions, 1
   guessed runtime type, 1 wrong function in the right file. Three of the partial fixes left a loop, and their hidden
   tests hung (exit 124).
4. **The verify verdict is weak evidence.** Final verdict against resolved: GREEN 12/20, AMBER 6/26, RED 4/12, no
   verdict 3/16. AMBER is the biggest bucket and is almost all "no reproduction saved" (13) or "passes on original"
   (10). On feasible tasks, a claim that failed on original at some point goes with 19/36 solved, against 6/20 without
   (association only).
5. **The locator is starved of repro budget.** The CONTEXT footer (4,700 estimated added tokens, derived for the
   fixer) fired in the locator in 42/74 tasks, in 27 of them before any repro. The locator wrote no repro in 27 tasks.
   The fixer wrote repros in only 39 calls across 74 tasks and treats AMBER as "done".
6. **Recommended for the next faithful Kaggle-L4 A/B** (section 4): P0 helper call form (precondition, about +8.5 s
   per task), then A repro-must-flip carried into the fixer with literal, sweep and return-value claims (+8 to +14 s),
   B completeness sweep over sites, linked bugs and layers (+2 to +7 s), C read the nearest existing test before the
   first edit, and fix two gate blind spots (+6 to +10 s). Temperature 0.2 costs 0 s but needs its own arm. Thinking on
   in the fixer costs +79 to +143 s per task and is not recommended. The combined arm is about +25 to +40 s per public task;
   the N=130 projection then sits at the all-capped ceiling of 11.31 h (margin 0.69 h), so every new step must be gated
   by the existing FINISH/TIME footers.

## 1. The 11 discordant tasks

| task | winner | v10 mechanism (trace, steps) | v9_eog mechanism |
|---|---|---|---|
| fastapi_14873 | v9 | Three leaks in a row: locator #29 (the plan becomes the leaked repro text), fixer #33 `call:grep.py`, verifier #34 `call:python3 /tmp/swe/status.py`. Submitter #36-#37 invents a SEARCH block for a `FastAPI.__init__` it never viewed (bash heredoc errors), #40 submits an **empty patch at t=115 s of 300**. `solved_by_all`, P1 (statement gives the fix). | fixed at 47 calls |
| fastapi_13537 | v9 | Locator #5 calls a tool named `view.py`: `Tool 'view.py' not found`, crash at 13 s, patch discarded. | fixed |
| fastapi_9425 | v9 | Locator #4 paraphrases the statement ("return type None bodiless response" instead of its words "return annotation" / "typed annotation"): top hit `scripts/contributors.py`; #5-#6 grep `return_type` gets 0 hits. CONTEXT footer at #15 (prompt only 9,641 tokens). Three repros #15, #17, #18 all pass on original, and none uses the literal `-> "None"` the statement quotes. Plan #21 names `routing.serialize_response`; fixer #57 edits routing.py; verify #58 AMBER, accepted. | #3 locate with the statement's words ranks `dependencies/utils.py` 2nd; fixer #15-#17 tests the literal `-> "None"`, #19 edits `get_typed_return_annotation` |
| rich_3777 | v9 | Plan #58 adds a new `is_interactive` property (it already exists as an attribute set in `Console.__init__`), ignores the companion `TTY_COMPATIBLE` tri-state, "REPRO: none (feature request)". Fixer: #60 `--lines` REVERTED, #64-#69 the same SEARCH block applied and reverted three times, #71 `--lines 934-940` puts the new property inside `is_terminal`'s body (valid syntax, dead code). Verify #82 reports `TESTS ... UNKNOWN (no JUnit report (pytest exit 3))` and grades it AMBER; the hidden run dies with INTERNALERROR (exit 3). | edits `Console.__init__` with a `_environ` tri-state |
| rich_3676 | v9 | Plan #23 names only the renderer `Traceback.__rich_console__`; the patch prints `__notes__` there. The hidden test asserts `traceback.trace.stacks[0].notes == ['Hello', 'World']`, a data-model field. | adds `Stack.notes` plus the render |
| fastapi_14077 | v10 | edit.py REFUSED the pyproject edit (#17); the patch applied cleanly | "Failed to apply test_patch" (test-file edit) |
| rich_3454 | v10 | edit.py landed the regex edit on the first try | session timeout, empty patch: 75 repeated calls, longest identical run 48 |
| fastapi_15589 | v10 | 48 fixer steps; final verdict RED 0/1 (#76) yet resolved: the claim was wrong, the fix right | empty patch |
| fastapi_5624 | v10 | fixer 58 steps; final verdict RED 0/1 (#74) yet resolved | wrong fix |
| fastapi_14419 | v10 | GREEN 1/1 (#26). No fair config had ever solved it | partial fix |
| rich_3521 | v10 | AMBER, no repro (#34), resolved | wrong fix in 14 calls |

Net: the plumbing swap is 2-2 (v10 fixed edit loops and test edits, and introduced the helper-name leak); fix quality is
4-3. v10's fix quality is not better than v9's; it is noisier in the same place.

## 2. v10 failures that edited a gold file (18 feasible of 32)

Excluded: infeasible (fastapi_14479, 15800, rich_3105, 3930, 3938, 3942), hidden_spec (fastapi_15588, rich_3061,
3468, 3470, 3471, 3675, 3934) and env (rich_3782).

| class | task | what went wrong (trace, steps) | other runs that solved it |
|---|---|---|---|
| partial: sibling site | fastapi_5077 | Plan #13 names `get_typed_signature` only (gold also fixes `get_typed_return_annotation`). Six repros #6-#11 pass on original; #12 flips only by monkeypatching `ForwardRef`. The fixer leaked its edit as text (#15) and the verifier leaked `status.py` (#16); the submitter landed the plan's single-site edit (#21). | r_v4, e74_v3 |
| partial: sibling site | rich_3480 | Plan #19 names `Text.append` only. The fixer re-ran the known hang as a raw `python3 -c` (#21), not through run.py, and lost 106 s; the edit landed at t=289 s (#22), verify ran in quick mode (#23), so the SIBLINGS scan was skipped although the removed line `for start, end, style in text._spans` recurs in `append_text`. Hidden test **hangs** (exit 124). | none |
| partial: second linked bug | rich_3953 | "Fix ZWJ and edge cases": plan #35 handles the ZWJ only. GREEN 2/2 (#39). Hidden `test_non_printable` fails (control chars must be width 0). | none |
| partial: other loop branches | rich_4006 | Plan #27 fixes the VS16 branch only. GREEN 1/1 (#35), but no claim tried `'\x1b'`, `'‍'` alone or doubled. Hidden test **hangs** (exit 124). | none |
| partial: second file | fastapi_14448 | `models.py` only; the consumer in `utils.py` untouched. | none |
| partial: second layer | rich_3676 | see section 1 (renderer only, no `Stack.notes`). | r2 v9_eog, v4, v6 |
| partial: ranges | rich_3535 | One character range fixed (`007f`, gold `007e`), the `00a0-02ff` hyphen and box-drawing range missed; AMBER no repro (#25). | none |
| claim misread | rich_4075 | Locator claim #30 is `console.print([], end="!") == "!"`; `print([])` renders the list, so the claim can never pass. The bug is `print(end="!")` with no objects. Plan #31 also adds pyproject/README edits. Verifier RED #39, then **the same `python3 -c` 30 times** (#65-#94). Final patch: one deleted blank line. | none (tier likely in catalog) |
| no invariant sweep | rich_3506 | Title "fix split cells", no repro given. Locator #8-#29: 21 probes, almost all on `'A'` or `'ABC'` with cuts 0/1/2/-1/0.5, four "same command 3 times" notes (#18, #22, #23, #29). Never a wide-character sweep. Plan #30 invents a ZeroDivisionError; AMBER no repro (#34, #36). | v4, v6, v7, Kaggle-L4 v9_eog |
| return value not claimed | rich_3052 | Plan #14 calls returning the canonical choice "optional". GREEN (#21, claim 2 INVALID). Hidden test: `'FoO' == 'foo'` fails. | none |
| wrong reading | rich_3472 | Try/except that renders an error node; the hidden test wants the unset field omitted. GREEN (#44). | none |
| wrong layer, no repro | rich_3777 | see section 1. | r2 v9_eog, v7, Kaggle-L4 v4 and v9_eog |
| deleted a feature | fastapi_14986 | Removed the `root_path` insertion instead of copying the schema; AMBER no repro (#42). Existing root_path tests would flag it. | none |
| guessed runtime type | fastapi_14616 | `not hasattr(field.field_info, "__pydantic_core_schema__")` can never distinguish `Json`; `FieldInfo.metadata` holds a `Json()` instance. | e74_v3 |
| edit corruption: escaping | rich_3278 | Patch writes `\\x1b` for `\x1b` in the regex. Verify #22, #29, #64: RED with 6 REGRESSIONS in tests/test_ansi.py; submitted anyway (22 hidden tests fail). | Kaggle-L4 v4, r_v9_og |
| edit corruption: continuation | rich_3043 | Patch drops the `"""\` continuation, so the HTML starts with a newline. Verify #17, #55, #59, #75: **"TESTS: none related"**, though tests/test_console.py exercises `CONSOLE_HTML_FORMAT` through `export_html`. 3 hidden failures. | none |
| edit loop | rich_3063 | 65 fixer steps, **44 identical calls** (#50-#93); regex edits never produce the escape; RED (#96-#103). | v4 (Kaggle env) |
| wrong function | rich_3772 | Rewrote `install()`'s excepthook instead of a cycle guard in `extract`. Hidden test **hangs** (exit 124). | none |

Feasible v10 failures that did **not** touch a gold file, for completeness: wrong file (fastapi_9425, fastapi_9753,
fastapi_13920, rich_3935, rich_3944, rich_4076); no patch because of a loop (rich_3180: **56 identical `python3 -c`
calls**, fixer #37-#92) or timeout (rich_4079); crash or leak (fastapi_13537, fastapi_14873).

## 3. Cross-cutting findings

### 3.1 Helper-as-tool leak (new in v10)

| | v10 | v9_eog |
|---|---|---|
| agent steps with `<\|tool_call>` text and no parsed call | 36 in 25 tasks | 1 (fastapi_5624 #30, a malformed edit_file) |
| of which a helper used as the function name | 29 in 20 tasks (fixer 14, verifier 12, locator 3) | 0 |
| unknown-tool crash from the same confusion | 1 (fastapi_13537 #5) | 0 |
| verifier's step 1 `call:python3 /tmp/swe/status.py` (15 tokens), verifier over | 9 tasks: 14301, 14458, 14873, 5077, 3470, 3471, 3518, 3905, 3953 (5 unresolved) | 0 |
| locator reply cut at `max_output_tokens` 768 mid tool call | 6 (14301, 14419, 2725, 3061, 3067, 3521; 5 of 6 still resolved) | n/a |

Cause, from the prompt text: the fixer and verifier list helpers as bare callables ("Other helpers, each as
python3 /tmp/swe/NAME.py: view.py FILE START END, ... grep.py "regex" ..."; verifier step "1. python3
/tmp/swe/status.py"). The leaked names match that listing exactly (`call:view.py rich/syntax.py`, `call:grep.py "..."`).
The locator prompt says "Helpers (run with run_command):" and leaked 3 times; the setup prompt spells the full call
`run_skill_script(file_path=..., skill_name=...)` and never leaked. v9_eog's prompts end with "Tools you can call: ...
There is no other tool". The locator's 768-token truncations cost little (5 of 6 resolved), so the cap can stay.

Thinking-channel text (`thought<|channel>`) is equal in both arms (6 and 7) and is not part of this bug.

### 3.2 Verdict calibration and repro coverage

| final verdict | tasks | resolved |
|---|---|---|
| GREEN | 20 | 12 |
| AMBER, no reproduction saved | 13 | 2 |
| AMBER, reproduction passes on original | 10 | 3 |
| AMBER, other (broken repro, tests unknown, no time) | 3 | 1 |
| RED | 12 | 4 |
| none (crash, timeout, NO SOURCE CHANGE) | 16 | 3 |

- The 8 GREEN failures: 4 feasible (rich_3052, 3472, 3953, 4006). In each, the claims covered the crash the model
  understood and nothing else: no return value, no second linked bug, no other input of the same family.
- The 4 RED successes (fastapi_5624, 15589, 14492, rich_2725) show that claims are often wrong while the fix is right.
  **A RED verdict must never become a veto.** A lever that forces a flipping repro must guide the fix, not gate it.
- Repro calls by stage: locator 121, fixer 39, verifier 11.

### 3.3 Identical-call loops

v10 made 400 calls that repeat an earlier identical call for the third time or more (12.9% of 3,104). v9_eog made 735
(21.9% of 3,360), mostly malformed edit_file loops. v10's worst loops are raw `python3 -c` via `run_command`, which no
helper sees, so the helpers' "same command 3 times" note never fires: rich_3180 56 in a row (fixer #37-#92), rich_3063
44 (fixer #50-#93), rich_4075 30 (verifier #65-#94). At about 4 s per call on L4 that is about 22 s per task of pure
waste on average. v10 made 366 raw `python3 -c` calls although every prompt says to run code only with run.py. The
same habit costs time on hang bugs: rich_3480's fixer re-ran the known hang raw (#21) and lost 106 s of a 176.5 s
budget, the same mechanism diag_3 found in fastapi_14258. Removing even half of the repeats would pay for levers A and B.

### 3.4 Gate blind spots

- **Related-test selection misses importers.** rich_3043 changed `rich/_export_format.py`; verify said "TESTS: none
  related" 4 times, while `tests/test_console.py::test_export_html*` renders that template through `console.py`.
- **pytest exit 3 is graded UNKNOWN.** `_swe_gate.py:1268` sets `status="unknown"` for any exit without a JUnit report.
  rich_3777 #82: original tests ran, the patched tree gave exit 3 (INTERNALERROR), verdict AMBER. A patched-side
  exit 3/4 where the original produced a report is a regression.
- rich_3278: RED with 6 regressions and still submitted. It cost nothing here (any wrong patch scores 0), but it shows
  the verifier does not revert to base when every checkpoint is RED with regressions.

### 3.5 Race-2 environment artifacts (both arms)

- requests_6644: verify #19 prints `requests OUTSIDE WORKSPACE: /usr/local/lib/python3.12/dist-packages`; tests import
  the system copy, so no workspace edit can pass. Every Kaggle-L4 run (v4, v9_eog) solves it.
- fastapi_14851: every race-2 arm timed out; on Kaggle the hidden test passes at base, and v4 and v9_eog Kaggle-L4 both
  solved it.
- So race 2 undercounts both arms by about 2 tasks against Kaggle-L4. This is one more reason to run the next A/B on
  Kaggle-L4, as planned.

## 4. Levers for the next faithful Kaggle-L4 A/B

Measured v10 call costs on L4: repro call 284 output tokens = 11.3 s (+0.6 s tool); edit 176 tokens = 7.6 s; verify
27 tokens = 2.3 s (+1.1 s tool, pod CPU); view 38 tokens + about 540 prompt tokens = 3.2 s; grep = 2.8 s. Fixer median
9 steps / 614 tokens = 34 s; verifier median 5 steps / 172 tokens = 13 s.

12 h rule used below: v10's N=130 projection is 9.24 h (`round1_kpis.txt`, time row). Each extra public second adds at
most 130 x 1.9 / 3600 = 0.069 h, and the projection cannot exceed the all-capped ceiling 600 + 130 x (3.6 + 305 + 1) s
= **11.31 h**, as long as the per-task cap holds. It did in race 2: the four timeouts ended 4-16 s after the 176.5 s
scaled cap, setup and verification included (rich_3180 180.7 s, rich_4079 186.4 s, fastapi_14258 190.3 s,
fastapi_14851 192.3 s). So these levers cannot cross 12 h on their own; the 12 h cliff is N > 137 tasks or a broken
cap. Their real risk is displacement: on cap-saturated hidden tasks, each added second is taken from later work, so
every new step must obey the existing FINISH (210 s) and TIME (250 s) footers.

### P0 (precondition, not fix quality): helpers only ever appear as `run_command` arguments

- **Change.** In fixer.md, verifier.md, submitter.md and SKILL.md, write every helper as the literal call
  `run_command(command="python3 /tmp/swe/status.py")`. Replace "Other helpers, each as python3 /tmp/swe/NAME.py: view.py
  FILE ..." with the same form, and add v9_eog's line: "Tools you can call: run_command, read_file, edit_file,
  write_file, ... There is no other tool: view.py, grep.py, edit.py and the other /tmp/swe helpers are commands you pass
  to run_command." Keep the locator's `max_output_tokens` at 768.
- **Evidence.** Section 3.1; fastapi_14873 #29/#33/#34 and fastapi_13537 #5 are 2 of v9's 5 wins.
- **Tasks.** Likely: fastapi_14873, fastapi_13537. Possible: fastapi_5077 (with B).
- **L4 cost.** Leaked stages run to completion again: 14 fixer stages x 34 s + 12 verifier stages x 13 s over 74 tasks =
  **about +8.5 s per task**. Prompt growth about 60 tokens per stage (under 0.1 s of prefill).
- **12 h risk.** Projection at most 9.82 h. None beyond that.

### A. Repro-must-flip, carried into the fixer, with literal, sweep and return-value claims

- **Change.**
  1. Fixer: when verify says AMBER "no reproduction saved" or "passes on original", write the reproduction before the
     final edit, with at least one claim that FAILS now. Claims use the statement's literal inputs (the quoted
     `-> "None"`, `print(end="!")` with no objects); one claim per behaviour, including the return value
     (`Prompt.ask(...) == 'foo'`); for a function with an invariant ("fix split cells", widths, round trips), a loop over
     every position and every example input, including wide or zero-width characters. Guide only: a RED verdict never
     reverts a fix (section 3.2).
  2. Locator: give the locator phase its own CONTEXT threshold (about 7,000 estimated tokens, still about 3k under the
     14,336 compaction line from a 3.5-4k start). The LOCATOR 75 s time footer stays the real bound.
  3. `verify.py`'s NEXT line for those two AMBER cases names the requirement, so the rule arrives at the moment it
     applies rather than only in the prompt.
- **Evidence.** 23 of 26 AMBER tasks are the two no-flip cases (5 solved); the locator's CONTEXT footer fired before any
  repro in 27 tasks; the misread or missing claims in rich_4075 #30, fastapi_9425 #15/#17/#18, rich_3506 #8-#29 and
  rich_3052 #21; feasible tasks with a flipping claim solve 19/36 against 6/20.
- **Tasks.** Likely: rich_3506, fastapi_9425. Possible: rich_4075, rich_3052, rich_3777, rich_4006, fastapi_9753.
- **L4 cost.** 23/74 tasks trigger it; 1-2 repro calls plus a verify = 15-28 s each, **+5 to +9 s per task**. The locator
  threshold adds about 2-3 locator steps where it fired (42/74), **+3 to +5 s**. Total **+8 to +14 s**.
- **12 h risk.** Projection 9.79-10.20 h alone. Gate: no new repro after FINISH.

### B. Completeness sweep: every site, every linked bug, every layer

- **Change.**
  1. Move the existing removed-line scan (`_swe_gate.siblings`, a `git grep -F` over `*.py`, well under a second) into
     edit.py's success output ("SAME CODE ELSEWHERE: path:line"), so the fixer sees it at the edit, not only when a
     full verify has time left. Keep it in verify, but never skip it in quick mode. Rank exact removed-line matches
     first and drop same-name defs whose code differs (rich_3063's `jupyter._render_segments.escape`, fastapi_14986's
     `FastAPI.openapi`, rich_3905's `Live.stop`), and generic lines such as `width=width,`.
  2. The locator's plan and the fixer's claims carry one line per "Fixes #N" link and per "X and Y" clause of the
     title.
  3. For a new attribute or setting, the plan names where the neighbouring attribute is captured (`Stack.exc_value`)
     and where its companion setting is parsed (`TTY_COMPATIBLE` in `Console.__init__`), and changes both the data
     model and the renderer.
  4. For hang titles, check every loop branch that can finish without advancing.
- **Evidence.** 7 partial fixes in section 2; three left a hang (rich_3480, rich_4006, rich_3772: exit 124). SIBLINGS
  fired in 17 tasks. Where it matched a removed line it can be right: fastapi_11194 #17 listed
  `first_field = body_fields[0]`, the second site of the gold fix, and the task resolved. In 9 of the 17 it listed only
  same-name defs. In none of the 7 partial-fix tasks did it fire: rich_3480's verify was in quick mode (#23), and
  fastapi_5077's single-site edit came from the submitter, which never runs verify.
- **Tasks.** Likely: fastapi_5077, rich_3480. Possible: rich_3953, rich_3676, rich_4006. Long shot: fastapi_14448,
  rich_3535.
- **L4 cost.** Siblings printed by edit.py: about 50 more prompt tokens per edit, no extra call. A sibling view, edit and
  verify where one exists (about 15% of tasks): 14 s -> +2 s. Claims per linked bug and per clause ride on A's repro
  call. If the fixer is instead told to grep and view per task: +6 s x 90% = +5.4 s. **+2 to +7 s per task.**
- **12 h risk.** Projection 9.38-9.72 h alone. It also shortens verification: a partial loop fix makes the hidden
  test hang to `timeout_seconds` (180 s on Kaggle). That time counts toward the 12 h if verification is inside it
  (UNVERIFIED, time_model 1.3).

### C. Read the nearest existing test before the first edit; close two gate holes

- **Change.**
  1. Fixer step 1: view the test that exercises the planned function (the plan's TESTS line; `grep.py --tests` for the
     function name), capped at 60 lines, before editing. Tests show the expected shape: rich_3676's
     `trace.stacks[...]` fields, rich_3052's returned choices, rich_3043's exact HTML head, rich_3472's dataclass
     reprs.
  2. `_swe_gate` related-test selection adds tests of modules that import the changed module (one level).
  3. A patched-side pytest exit 3 or 4 where the original side produced a report becomes REGRESSIONS (RED), not
     UNKNOWN.
- **Evidence.** rich_3043 verify #17/#55/#59/#75 "none related"; rich_3777 #82 exit 3 graded AMBER; GraphLoc's public
  repeat runs: editing a gold function resolves 57% against 6% otherwise (`research/update_0928.md`); 65/74 tasks carry
  `existing_tests_cover_area`.
- **Tasks.** Possible: rich_3676, rich_3043, rich_3052, rich_3777. Long shot: rich_3472.
- **L4 cost.** One view of about 540-1,500 prompt tokens: 3.2-4 s. Broader related tests: about +1-2 s per verify call x
  2.8 verify calls per task = +3-6 s (the pytest side stays capped by PYTEST_SIDE = 40 s). **+6 to +10 s per task.**
  The view pushes the fixer's CONTEXT footer about one view earlier.
- **12 h risk.** Projection 9.65-9.93 h alone.

### D (separate arm only). Temperature 0.2 on locator, fixer and verifier

- **Evidence for.** Every public bundle at 0.12 or above runs T 0.2 / top_k 40 (`research/update_0928.md` 1.3). The
  leaked function names in 3.1 are low-probability token choices after `call:`, which T 1.0 / top_k 64 samples more
  often.
- **Evidence against.** Our pod sweep found no temperature effect (sweep1, 47 tasks, all paired p > 0.45). The loops in
  3.3 are in-context copying, which lower temperature tends to strengthen.
- **L4 cost.** 0 s. **12 h risk.** None directly. If loops lengthen, more tasks hit the cap, which the ceiling bounds.
- **How to run it.** `scripts/make_variant.py --work-temp 0.2` on top of the P0+A+B+C bundle, as a third kernel only if
  the Kaggle queue allows. Mixing it into the main treatment makes the A/B uninterpretable.

### Not recommended now: thinking on for the fixer

- Thinking-on turns average 316-376 completion tokens against about 88 per fixer step here
  (`research/notebooks_update_0928.md` 4.1); `thinking_budget` is not enforced, so only `max_output_tokens` bounds a
  turn. +250 tokens x 35 ms x 9 (median) to 16.3 (mean) fixer steps = **+79 to +143 s per task**, which puts nearly every
  hidden task at the cap (projection at the 11.31 h ceiling) and takes the time from the verifier.
- The cheaper variant, if wanted later, is one extra no-tool "design" stage with thinking on and
  `max_output_tokens: 1024` before the fixer: at most 1.4 + 1,024 x 35 ms = 37 s, typically 15-25 s. No trace here
  measures its effect, and it would cost an arm.

### Expected effect and how to read the A/B

- Likely flips: P0 2, A 2, B 2 (6 tasks); possible about 12 more, overlapping. At the catalog's priors (0.7 likely,
  0.35 possible) that is roughly +5 to +7 public tasks before overlap is removed. Run-to-run SD is about 2.5 tasks per
  74 (GraphLoc repeat runs), so one paired 74-task A/B can confirm only the large end of that.
- So pre-register the mechanism KPIs as primary and solves as secondary: leaked tool-call text per task at most 0.05
  (from 0.49); AMBER-without-flip share of tasks from 31% to under 15%; GREEN precision at least 12/20; identical-call
  repeats per task from 5.4 down; hidden-test hangs (exit 124) from 3 to 0 or 1.
- Combined time: P0 + A + B + C = **+25 to +40 s per public task** on L4, from the replayed 157.4 s to about 182-197 s,
  which is 1.21-1.31 x r_v4. That trips the pre-registered 1.08 x knobs (verifier repair rounds 2 to 1, LOCATOR 75 to
  60 s) under `race2_checklist.md` row 12. Decide before the run whether those knobs apply to v10.1, and restate it in a
  dated addendum.

## 5. Regression tests (one per bug, base and edge cases; stdlib only)

- `tests/test_v10_prompts.py::test_helpers_only_as_run_command_args` (P0): every `/tmp/swe/*.py` or bare helper name in
  each prompt and SKILL.md appears inside `run_command(command="...")`. Base case: the current fixer line "Other helpers,
  each as python3 /tmp/swe/NAME.py: view.py ..." and verifier step "1. python3 /tmp/swe/status.py" must fail the lint.
  Edge cases: backticks, numbered steps, heredoc examples, SKILL.md.
- `::test_each_stage_names_its_tools`: each stage prompt has the "Tools you can call: ... There is no other tool" line,
  and its list equals that stage's YAML `tools` (plus `run_skill_script` where skills are declared).
- `tests/test_v10_runner.py::test_kpi_leaked_tool_text`: `replay_l4` counts agent steps whose message contains
  `<|tool_call>` and that have no parsed tool call. Fixtures: r2_v10_1 fastapi_14873 (#29, #33, #34 = 3), r2_v9_eog_1
  fastapi_5624 (#30 = 1). Edge: `thought<|channel>` text is not counted. Threshold 0.05 per task.
- `tests/test_v10_flow.py` scenario: verifier's first reply is the 15-token `status.py` leak. The submitter must still
  finalize and ship the fixer's edit (today's behaviour; keep it).
- `tests/test_v10_core.py::test_ctx_locator_threshold` (A): locator phase at 5,000 estimated tokens shows no CONTEXT;
  at 7,000 it does; fixer phase unchanged at 4,700; the R95 derivation still keeps the fixer under 14,336.
- `tests/test_v10_verify.py::test_amber_next_requires_flip` (A): a repro that passes on original, and no repro at all,
  each give a NEXT line that asks for a claim failing now with the issue's literal inputs.
- Offline claim-validity check (A, CPU only, no GPU): extract every `verify.py --repro-only` heredoc from the traces,
  run it at base and with the gold patch from `data/tasks.jsonl`; a claim is valid if it fails at base and passes with
  gold. Fixtures: rich_4075 #30 must be INVALID (fails with gold), fastapi_9425 #15 INVALID (passes at base), and a
  rich_3506 width sweep VALID. Report the valid-claim share per arm.
- `tests/test_v10_edit.py::test_edit_prints_same_code_elsewhere` (B): two methods with the same
  `for start, end, style in text._spans` line; an edit.py fix of one prints the other as SAME CODE ELSEWHERE. Edge: a
  same-name def with different code (jupyter `escape`) and a generic `width=width,` line are not listed; the scan
  stays under 0.5 s on a 3,000-file repo.
- `tests/test_v10_verify.py::test_siblings_in_quick_mode` (B, rich_3480): with the deadline inside quick mode, verify
  still prints SIBLINGS. Edge: a statement with two "Fixes #" links reports claims covering 1 of 2.
- `tests/test_v10_gate.py::test_related_tests_follow_importers` (C): `pkg/_fmt.py` imported by `pkg/console.py`, tested
  by `tests/test_console.py`; editing `_fmt.py` selects that test. Base case: direct tests still selected first.
- `::test_patched_exit3_is_regression` (C): original side has a JUnit report, patched side exits 3 (a broken conftest
  import) -> REGRESSIONS / RED. Edge: exit 3 on both sides stays UNKNOWN; exit 5 on both sides stays "no tests".
- `tests/test_v10_runner.py::test_kpi_identical_calls`: counts calls repeating an identical earlier call beyond the
  second; fixtures rich_3180 (longest run 56), rich_4075 (30); report only.

Race-3 targets: leaked tool-call text 0.05 per task or less; unknown-tool crashes 0; AMBER-without-flip under 15%;
hidden-test hangs 1 or fewer; and the combined time decision recorded before the run.
