# v10 race-2 round-1 diagnosis 2: the six empty patches

Written 2026-09-29, read-only, from `eval/race2/eval/runs/r2_v10_1` (74 tasks, Kaggle compaction 14,336, L4 clock scale
1.7) and `r2_v9_eog_1`. Step numbers are `step_id` in `traces/trace_<task>.json`. "t=" is the helper clock
(scaled, cap 300 s); "real" is `extra.elapsed_s` (cap 176 s). Nothing in `submissions/` was changed; the helper
reproductions below ran against copies in a scratch git repo.

## 1. Summary

| task | end | agent time used | what killed the edit | Kaggle L4 v4 / v9_eog | race v9_eog |
|---|---|---|---|---|---|
| fastapi_13537 | crash at 13 s | 6 s | locator step 5 called a tool named `view.py` (args `filepath, start_line, end_line`); ADK `ValueError`, whole task discarded | solved / solved | solved |
| fastapi_14873 | submitted empty at 72 s real | 68 of 176 s | cascade of three stage-ending text-form tool calls (steps 29, 33, 34); submitter had no issue text, its two edits were cut by a stray `EOF` line (36, 37), then `submit_patch` on an empty tree (40) with about 108 s unused | solved / solved | solved |
| fastapi_15280 | submitted empty at 166 s real, 100/100 tool calls | full | fixer ended at step 18 (real 30 s) with `call:grep.py ...` as text; verifier made 51 `read_file` and 20 raw calls; two OK edits (91, 101) were undone by the model (94, 102); no checkpoint existed to restore at finalize (103) | - / - | empty |
| fastapi_14306 | submitted empty at 170 s real | full | locator: 20 `grep.py` calls with a path argument that the helper folded into the regex (16 zero hits or invalid, 4 wrong matches); fixer: 9 byte-identical failing `edit_file` calls (44-53); first footer the fixer saw said `TIME: ... End your stage now` on an empty tree (54) | - / - | wrong patch |
| fastapi_14851 | session timeout | full | a 108 s infrastructure stall (steps 16 to 17) that hit both arms at the same wall time; fixer then read files until the cap; `status.py` at step 38 printed `DIFF: no source change` plus `TIME: ... End your stage now` | solved / solved | empty (same stall) |
| rich_3180 | session timeout | full | fixer never called a helper: 67 raw commands, 56 of them the identical `python3 -c ... Text('A你好') ... wrap(c, 3, overflow='fold')` (steps 37-92) | solved / - | wrong patch |

Four of the six are tasks v4 solves on the Kaggle L4 (`eval/kaggle/g4-l4-v4/results.jsonl`), and 13537 and 14873 were
solved by v9_eog in this same race. So the empties are not only hard tasks: roughly 2 to 4 of v10's lost points in
round 1 sit here.

In none of the six did finalize or a checkpoint restore throw away a good edit. The patch was empty because:
- a source edit never landed: 13537, 14873, 14306, 14851, rich_3180;
- or the model undid its own landed edit, and edit.py keeps no checkpoint that could bring it back: 15280.

## 2. Per task, with steps

### fastapi_13537 (crash, `unknown_tool`, KPI row 3)
- Steps 2-3: setup is fine. Step 4: `locate.py` finds `fastapi/dependencies/utils.py` (`_extract_form_body L869-908`),
  the right file.
- Step 5 (real 10.1 s): the locator emits a parsed call `function_name: "view.py"` with `{"filepath":
  "fastapi/dependencies/utils.py", "start_line": 723, "end_line": 958}`. That is the helper name with `read_file`'s
  argument schema. The gemma4 parser accepts dots in names, ADK raises `Tool 'view.py' not found`, and the harness's
  outer `except` discards the task (`run.out`, traceback through `functions.py:405`).
- Cause: v10 prompts present helpers as bare names (`view.py FILE START END`). They also dropped v9's line "Tools you
  can call: ... There is no other tool" (`submissions/v9_eog/prompts/fixer.md`, last line).

### fastapi_14873 (empty, 108 s unused)
- Step 10 (t=22s): `CONTEXT` footer after 7 docstring-heavy views; ignored. Step 20: compaction (prompt 15,245 to
  3,144).
- Step 29 (real 48.6 s): the locator's final message is a text-form call,
  `<|tool_call>call:python3 /tmp/swe/verify.py --repro-only <<'EOF' ...<tool_call|>` (the `run_command{command:`
  wrapper is missing). That text becomes the plan (`output_key: plan`).
- Step 33 (real 53.3 s): after 3 calls the fixer ends with `<|tool_call>call:grep.py "class APIRouter"
  fastapi/routing.py<tool_call|>`.
- Step 34: the verifier's first and only step is `<|tool_call>call:python3 /tmp/swe/status.py<tool_call|>`, the same
  malformed form as the handoff it was shown.
- Submitter:
  - Step 35: `NOT READY: EMPTY`.
  - Steps 36-37: edit.py with a SEARCH block invented from memory. The submitter prompt has only `{plan?}`, and the plan
    is the text call from step 29. Each section also ends in a stray `EOF` line, so bash ended the heredoc early:
    `=======: command not found`, and edit.py printed `block 1 has no ======= line`. The second attempt repeats the
    first.
  - Step 39: `EMPTY` again, with `LOCATOR: 75s used ... Other stages: ignore this line`.
  - Step 40 (real 71.7 s): `submit_patch` returns `patch_size 0`.

### fastapi_15280 (empty, tool budget exhausted)
- Locator OK: plan at step 14 (real 26 s): FILES `fastapi/applications.py` (FastAPI) and `fastapi/routing.py`
  (APIRouter), FIX: add `vibe` like `get`.
- Step 18 (real 30 s): the fixer ends with `<|tool_call>call:grep.py "def get(" fastapi/applications.py<|"|><tool_call|>`,
  leaving 146 s to the verifier.
- Verifier:
  - Steps 19-90: 51 `read_file` calls and 20 raw `grep -n` calls. The only helper output it saw carried `LOCATOR: 75s
    used ... Other stages: ignore this line` (steps 47 and 75, t=96 and t=141). `EDIT NOW` first reached it at step 90
    (t=164).
  - Step 91 (t=170): an OK edit that renames `get` to `vibe`. The call reports `status: error` (`EOF: command not found`,
    exit 127) because the heredoc ends with `EOF` twice.
  - Step 94: the model renames it back (OK).
  - Step 96 (t=187) and step 97 (t=247) are REVERTED for syntax errors. Step 97 is a 1,831-token insertion at a
    guessed range, 2178-2186, that starts inside a docstring. It took 35 s of generation.
  - Steps 101-102 (t=266, 268): `get` to `vibe`, then back.
  - Step 103: finalize says `EMPTY`, and `status.py` shows `checkpoints: 0`. edit.py never saves one, so finalize's
    `K.best(None)` restore had nothing to use.
  - Step 105: `submit_patch` with `patch_size 0` at 100/100 tool calls.

### fastapi_14306 (empty)
- Locator:
  - Steps 7-27: 20 `grep.py` calls, every one with a trailing path, for example
    `grep.py "RequestValidationError" fastapi/routing.py`. 16 return `GREP: 0 hits ... NOTE: no match in source
    files` or `invalid regex`, although routing.py imports and raises it (the fixer's raw `grep -n` at step 37 finds
    lines 50, 347, 423 and 453). The other 4 (steps 13, 17, 20, 22) matched the mangled pattern, e.g.
    `ValidationError .`.
  - Step 16: `grep.py "RequestValidationError(" .` returns `invalid regex: ... 'RequestValidationError( .'`.
  - Plan at step 33 (real 52 s).
- Fixer:
  - Steps 44-53: 9 byte-identical `edit_file` calls, 73 s real (69.0 to 141.7). The `old_string` carries literal `\"`
    copied from `read_file` output, so every call fails with `old_string not found`. There is no edit.py call, so no
    NO MATCH guidance.
  - Step 54 (t=250): the first helper output the fixer saw (`locate.py`) printed `TIME: t>=250s. End your stage now`
    on an empty tree.
  - Steps 55-64: read_file. Step 66: the stage ends on `<|tool_call>call:view.py fastapi/exceptions.py<|"|><tool_call|>`.
- Verifier:
  - t=276: `status.py` shows no source change. `verify.py` gives `NO SOURCE CHANGE`, and finalize gives `EMPTY` with
    the TIME hint "run finalize.py next", which sends it round in a circle.
  - Step 70: one invented edit with a stray `EOF`.
  - Step 72: empty submit.

### fastapi_14851 (timeout, no edit)
- The task prompt arrives at real 14 s (others about 4 s).
- Steps 16 to 17: 108.3 s pass between a 6,697-token call and the next 51-token call. This was not the agent. The
  co-running task on the same GPU, fastapi_14258, stalls 107 s at the same wall time (its steps 25 to 26), and the
  **v9_eog arm's own fastapi_14851** stalls 107 s (its step 30). Both arms stall on the same task ids (fastapi_14258,
  fastapi_14851, requests_6644, rich_3180 and rich_3480), so this is shared pod infrastructure.
- Steps 22 and 26: the grep.py path bug again (`grep.py "on_startup" fastapi/routing.py` returns 0 hits, but line 1426
  has it).
- Plan at step 27 (real 150 s, t about 233).
- Fixer: 19 read_file, 8 raw and 2 `status.py` calls. At step 38 (t=263) `status.py` printed `DIFF: no source change`
  and `TIME: t>=250s. End your stage now (verifier: run finalize.py next)`. The timeout came at 192 s real with no edit.

### rich_3180 (timeout, no edit)
- Steps 11 to 12: a 35 s stall, shared with requests_6644 at the same wall time.
- The locator ignored `LOCATOR` in 10 consecutive run.py outputs (steps 12-21), then replied at real 77 s (t about 127).
- Fixer (steps 24-92): 69 calls, none to a `/tmp/swe` helper, so no footer, repeat note or EDIT NOW could reach it.
  From step 37 on it sends the same raw `python3 -c` command 56 times until the session timeout.

## 3. Mechanisms, counted over the whole run (v10 vs v9_eog, same 74 ids)

| # | mechanism | v10 run 1 | v9_eog run 1 | in the six |
|---|---|---|---|---|
| M1 | stage ended by a text-form tool call (`<\|tool_call>` in a final message) | **38** (locator 9, fixer 16, verifier 13), in 26 tasks | 3 | 14873 x3, 15280, 14306 |
| M1a | ...of which the model used a shell command or a helper as the function name (`call:python3 /tmp/swe/...` 18, `call:view.py/grep.py ...` 11); the other 9 are `run_command{...}` cut at the locator cap (6, see M2) or malformed arguments (3) | 29 | 0 | 14873, 15280, 14306 |
| M1b | verifier's first step is a text call (`call:python3 /tmp/swe/status.py`) | 9 of 69 verifier runs; 5/16 after a text-call handoff vs 4/53 after a normal one | 0 | 14873 |
| M1c | parsed call to a helper name, so the task crashes | 1 | 0 | 13537 |
| M2 | locator reply cut at `max_output_tokens: 768` | 11 of 73 locator hand-offs (6 truncated repro calls that ended the stage, 5 truncated plans); parsed repro calls p50 259, p90 509, max 732 tokens | n/a (cap 4096) | - |
| M3 | `grep.py "REGEX" PATH` folds PATH into the regex | 74 of 206 grep.py calls (11 tasks) had a trailing path; 65 returned 0 hits or `invalid regex`, and the other 9 matched the mangled pattern | n/a | 14306, 14851 |
| M4 | FINISH/TIME footers on an empty tree say "keep the edit you have and end your stage" / "End your stage now" | every helper call at t>=210 with no source change | n/a | 14851 (38), 14306 (54, 65, 67-71), 15280 (98-104) |
| M5 | edit.py saves no checkpoint; finalize can only restore trees that verify/finalize scored | a landed-then-undone edit is unrecoverable | n/a | 15280 |
| M6 | `submit_patch` on an empty tree | 3 (14873 at real 72 s; 14306 and 15280 near the cap) | 10 | 14873 |
| M7 | stray `EOF` in an edit.py heredoc | 4 early (edit lost: 14873 #36 #37, rich_3471 #12, rich_3777 #73), 12 trailing (edit landed but the call reports `status: error`, exit 127) | n/a | 14873, 14306, 15280 |
| M8 | fixer work that bypasses helpers (no footer can reach it) | 44% of fixer calls are helpers; 12 fixer runs with 8 or more calls and under 20% helpers resolved 2 (17%); identical raw `python3 -c` loops of 30, 44 and 56 calls (rich_4075 verifier, rich_3063 and rich_3180 fixer) that no repeat note can see | - | rich_3180, 14851, 15280 |
| M9 | pod stall of more than 25 s (net of generation) | 5 (394 s) | 8 (722 s) | 14851, rich_3180 |

Notes on M1:
- It is the largest v10-specific regression: 38 against 3 in the control. It does not show in the solve count
  because the downstream stages often rescue. The submitter started from `EMPTY` in 6 tasks and landed an edit in 5
  of them: it solved fastapi_14301 and fastapi_14458, and gave wrong non-empty patches in fastapi_14616,
  fastapi_5077 and rich_3470. It failed only in 14873.
- The contrast inside v10 is sharp. Setup's prompt shows the call in function form,
  `run_skill_script(file_path="install.py", skill_name="swe-tools")`, and setup made 74 of 74 well-formed calls. The
  verifier's step 1 is a bare `python3 /tmp/swe/status.py`, and the verifier sent it as a raw text call in 9 of 69 runs.

Reproductions (scratch repo, v10 scripts unchanged, `SWE_FAKE_CLOCK` set):
- M3: `grep.py "on_startup" pkg/routing.py` gives `GREP: 0 hits`, and `grep.py "on_startup" .` also gives 0 hits.
  `grep.py "on_startup" --path pkg/routing.py` gives 2 hits. `grep.py "on_startup(" .` gives `invalid regex ...
  'on_startup( .'`. The cause is `C.parse_args(argv, FLAGS, ["regex*"])` in `grep.py:146`: the starred positional
  joins every remaining word into the regex.
- M4: `status.py` on an empty tree prints `EDIT NOW` at t=160, `FINISH: ... keep the edit you have and end your stage`
  at t=215, and `TIME: ... End your stage now (verifier: run finalize.py next)` at t=263. This is `hint()` in
  `_swe_common.py:1700-1724`: TIME and FINISH are checked before the no-source-change branch. The test matrix pins it:
  `tests/test_v10_core.py` FOOTER_CASES row `("finish", 215, None, "FINISH: t>=210s.")`.
- M5: an edit.py OK at t=170, then a revert at t=179, then finalize at t=269 gives `NOT READY: EMPTY` with
  `state.ckpts == []`.
- M7: `EOF` inside the block makes bash run `=======` and the rest as commands, and edit.py reports `block 1 has no
  ======= line`. A doubled trailing `EOF` lands the edit, then exits 127 with `EOF: command not found`.

## 4. Fixes, ranked by expected effect on empty patches

Every one gets a regression test. All helper changes are stdlib only. Frozen bundles stay untouched.

**P1. Show every helper call in tool form, and say helpers are not tools (M1, M1b, M1c; 13537, 14873, 15280, 14306).**
- In the locator, fixer, verifier and submitter prompts, write each helper invocation as
  `run_command(command="python3 /tmp/swe/status.py")`. For heredocs, keep the heredoc inside the command string.
  Delete the shorthand list `view.py FILE START END, grep.py "regex", ...` from the fixer.
- Add one line: "view.py, grep.py, edit.py, verify.py, finalize.py and status.py are scripts, not tools: run them only
  through run_command."
- Tests (`test_v10_prompts.py`):
  - every `/tmp/swe/` mention in a work-stage prompt sits inside a `run_command(command="...")` form;
  - no bare `NAME.py ARG` shorthand appears;
  - the not-tools line is present;
  - control cases for the lint.
- Expected: stage-ending text calls from 38 toward v9_eog's 3, and verifier first-step failures from 9 toward 0. The
  crash class is the same mechanism.

**P2. Locator output cap from 768 to 1536, and make the reply start with `FILES:` (M2).**
- 11 of 73 hand-offs were cut: 14301, 14419, 14986, 9425, rich_2725, 3061, 3067, 3470, 3521, 3782 and 3942.
- The cost falls only on capped calls: about 27 s more per capped call at 35 ms/token.
- Add to the prompt: "reply starting with FILES:, under 120 words; the reproduction at most 25 lines".
- Test: the config pin (`gen_locator.yaml` max_output_tokens at least 1536) plus the prompt rule in RULES.

**P3. grep.py: read trailing positional words that name existing paths as `--path` (M3).**
- The first positional word is the regex. A later word that exists under `ws()` (file or directory) joins the pathspec.
- A later word that does not exist but looks like a path (contains `/` or ends in `.py`) gives a one-line
  `NOTE: 'x' is not a path in the workspace; searched everywhere`.
- A quoted regex with spaces is unchanged.
- Tests (`test_v10_locate_view.py::test_grep_positional_paths`):
  - base: `"on_startup" pkg/routing.py` gives 2 hits;
  - `.`, a directory, two paths, `--tests` after a path, a path outside ws;
  - a non-existent `pkg/nope.py`;
  - `"def foo"` quoted;
  - `setup.py` alone is still a regex.

**P4. Footers: an empty tree never hears "end your stage" (M4; 14851, 14306, 15280).**
- New priority: FINAL > EMPTY > TIME > FINISH > CONTEXT > EDIT NOW > LOCATOR.
- EMPTY applies when there is no source change, t >= T_EDIT_NOW (or the locator stage is over, see below), and the
  tree is not final. Text:
  `EDIT NOW: no source change at t=Ns; an empty patch always fails. Locator: reply with your plan now. Other stages:
  make the smallest plausible version of the plan's change with edit.py now.`
- At t >= T_TIME the EMPTY text adds: `then run finalize.py once`.
- Replace LOCATOR by EDIT NOW as soon as the journal shows the locator is over: a `status`, `finalize`, full `verify`
  or `edit` entry. That would have changed 15280 steps 47 and 75 and 14873 steps 36-39 from "ignore this line" to an
  edit directive.
- Tests:
  - rewrite the `finish` row, and add `time_empty`, `time_src`, `locator_over_edit_now`;
  - a sweep over t = 0..300 (step 5) with src False: no hint contains "keep the edit you have" or "End your stage";
  - FINAL still wins.
- Variant, not default: T_EDIT_NOW 150 to 120. In v10, resolved tasks made their first edit by t=64 (p50) and t=106
  (p90); only 1 of 25 made it after 150.

**P5. Checkpoint every landed edit, unscored (M5; 15280).**
- After an OK write that leaves a non-empty source diff, edit.py calls `K.save(diff, None, None, "EDITED", False)`.
  status.py does the same for a non-empty tree it has already diffed, which covers trees built with the harness's
  `edit_file`.
- `rank()` already puts an unscored entry (`(1,)`) below every scored one (score[0] is `nonempty`, always 1). So
  `best_against` is unaffected, and finalize's EMPTY branch and `late_guard` at T_SAFE restore the latest EDITED tree.
- Tests (`test_v10_edit.py`, `test_v10_finalize.py`):
  - an edit, a revert, then finalize gives `RESTORED: checkpoint #1 (EDITED ...)` and a non-empty diff;
  - a scored checkpoint beats an EDITED one;
  - no restore on a non-empty tree;
  - a refusal at t >= T_NO_RESTORE;
  - edit.py p95 stays within budget (the added `diff_bytes` should cost under 60 ms).
- Caveat: this can restore an edit the model reverted on purpose. That is still no worse than empty, since both
  score 0.

**P6. The last stage keeps working until a patch exists (M6; 14873).**
- The submitter prompt gains `{problem_description}`. Its edits in 14873 were invented because it never saw the
  issue.
- finalize.py's EMPTY line becomes: `NOT READY: EMPTY at t=Ns (Ms left). Do not submit an empty patch: it always
  fails.` It is followed by `EDIT TARGET:` with the last source range recorded in `state.views` (the locator's
  view.py calls), shown as at most 20 numbered lines ready for `edit.py --lines`.
- The prompts say submit only after `READY`, or at t >= 285.
- Wrap the submitter in `LoopAgent(max_iterations: 3)`:
  - `submit_patch` followed by text still ends the task at once;
  - a submitter that ends on a text call or without submitting gets up to two more turns, keeping its own history
    (config_space R4);
  - the compiler accepts nested Sequential/Loop (case 09).
- A missing submit is safe: at the timeout the harness takes the working-tree diff (harness_runtime section 1). If
  all three iterations end without a submit, the harness nudge restarts the pipeline from setup with the tree and
  `/tmp/swe` state intact (harness_runtime 6.1), which is another attempt, not a loss.
- Tests: the finalize EMPTY text and EDIT TARGET from a seeded `state.views`; the bundle structure pin in
  `test_v10_bundle.py`; `validate.py` OK; the prompt lint for `{problem_description}` in the submitter.

**P7. Heredoc hygiene (M7).**
- edit.py, when stdin has `<<<<<<< SEARCH` but no `=======`: `ERROR: the edit ended early. A line EOF inside the block
  ends the heredoc and the rest ran as shell commands. Put EOF once, as the last line, and send the whole edit again.`
- Prompt: "EOF appears exactly once, as the last line."
- Test: the early-EOF stdin shape from 14873 step 36.

**P8. Fixer prompt: make the edit before probing (M8; rich_3180, 14851, 15280).**
- "Your first edit.py call comes within your first 5 tool calls; never run the same command twice."
- No helper can interrupt a stage that never calls one. There are no callbacks and no per-agent budget
  (config_space rows 9 and 11), and `frequency_penalty` works within one completion only. So this is prompt-only, and
  its effect has to be measured, not assumed.

Rejected:
- Removing `read_file`/`edit_file` from the fixer's tools. An undeclared call crashes the whole task (13537), and
  hand-offs render the previous stage's tool calls as text.
- A `python3` or `EOF` shim in the sandbox venv. It changes the harness environment for every command.
- Callbacks: the scorer ignores them.

## 5. Expected effect on the six (my estimate, to be checked, not claimed)

| task | fixes that apply | non-empty likely? | solve plausible? |
|---|---|---|---|
| fastapi_13537 | P1 | yes | yes (v4, v9_eog solve it) |
| fastapi_14873 | P1, P6, P7 | yes | yes (v4, v9_eog solve it) |
| fastapi_15280 | P1, P4, P5 | yes | unlikely (no baseline solves it) |
| fastapi_14306 | P3, P4, P6 | likely | unlikely |
| fastapi_14851 | P3, P4, P8 | depends on the 108 s stall | possible without the stall |
| rich_3180 | P8 only | uncertain | possible (v4 solves it) |

## 6. Pre-registered checks for the next measurement (written before any run)

Measure on the same 74 ids, faithful settings, both arms. Every KPI below is computable from the existing trace
format and should be added to `scripts/replay_l4.py` before the run:

| KPI | now (v10 run 1) | pass |
|---|---|---|
| empty patches per 74 | 6 | at most 2 (existing row 9) |
| stage-ending text calls per 74 | 38 | at most 8 |
| verifier first-step text calls | 9 of 69 | at most 2 |
| locator hand-offs at the output cap | 11 of 73 | at most 2 |
| grep.py trailing-path calls with 0 hits or invalid regex (counted with shlex, not a regex) | 65 of 74 | at most 10% |
| `submit_patch` on an empty tree at t < 285 | 1 | 0 |
| unknown-tool crashes | 1 | 0 (existing row 3) |
| resolved | 25 | no fewer than 25 in the paired run; this change targets empties, not fix quality |

If empties fall but resolved does not rise, that is the expected shape: the non-empty best-effort patches for
15280, 14306 and 14851 would mostly fail. Only 13537 and 14873 (and 14851 without the stall) are realistic solve
recoveries. The 42 non-empty failures are the fix-quality problem this note does not address.
