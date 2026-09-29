# v10.1 diagnosis 1: helper names turned into tool calls (race 2 round 1, crash KPI)

Scope: this diagnosis is read-only. Nothing in `submissions/`, `tests/` or `scripts/` was changed. Traces are in
`eval/race2/eval/runs/<run>/traces/trace_<id>.json`, and step numbers are ATIF `step_id`s. Kaggle L4 traces were
unpacked from `eval/kaggle/g4-l4-{v4,v9-eog}/traces.tar.gz` into a scratch directory. The proposed rewrite and the
lint below were checked on a scratch copy of the bundle only.

## TL;DR

1. **The crash is not a one-off.** On fastapi_13537 (step 5) the locator emitted a function call named `view.py`,
   with `read_file`'s argument names (`filepath`, `start_line`, `end_line`). ADK raised, and the harness threw away the
   task at t=13 s. v9_eog solved the same task. Across the 74 v10 traces the model tried a non-tool name as a tool
   **30 times in 21 tasks**: 1 parsed call (the crash) and 29 unparsed `<|tool_call>call:NAME ...` texts. Every unparsed
   one ended its stage on the spot. The same scan finds **0** in r2_v9_eog_1, 0 in Kaggle g4-l4-v4 and 2 in Kaggle
   g4-l4-v9-eog.
2. **Every unparsed one was a single `{` away from the same crash.** The scorer's vLLM 0.19.1 Gemma 4 parser matches
   `call:([\w\-\.]+)\{...\}`, so `view.py`, `grep.py` and `status.py` all parse as tool names once a brace follows.
   A submission cannot install `on_tool_error_callback` (research/harness_runtime.md section 4). **Prompt wording
   is the only lever.**
3. **The wording is the trigger, and the invented calls copy the prompt's shapes.** The bundle text has 38 bare
   helper names: helper names used as verbs ("2. view.py the best candidates"), a `NAME.py` template list ("each as
   python3 /tmp/swe/NAME.py: view.py FILE START END, ..., grep.py "regex""), and nouns ("with edit.py"). It also has
   4 numbered steps that start with a bare command ("1. python3 /tmp/swe/status.py"). The invented calls repeat
   these shapes almost word for word: `call:view.py rich/_inspect.py 100 120`, `call:grep.py "def get(" ...` and
   `call:python3 /tmp/swe/status.py`. The v9_eog prompts always said "Run `python3 /tmp/swe/gate.py`" and ended with
   "There is no other tool". Its race-2 run has none of these calls.
4. **The existing lints cannot see this, and about 23 pinned strings in 7 test files lock in the bad wording.** R89 checks only
   declared tool names. R96 (`tests/test_v10_prompts.py:817-842`) requires "View files only with view.py ...",
   "view.py the plan's FILES" and "1. python3 /tmp/swe/status.py". Helper output also carries 28 bare names in
   21 string constants (the CONTEXT hint alone appeared 339 times). The race-2 run showed a bare name in 531 of
   1,859 helper outputs, in 72 of 74 tasks.
5. **The proposed fix is a rule plus a lint, both checked.** The rule allows a helper name only as
   `python3 /tmp/swe/NAME.py` or `run_skill_script(file_path="NAME.py", skill_name="swe-tools")`, and every run
   instruction starts with "Run". The prototype lint reports 70 violations on the current bundle and 0 on the
   scratch rewrite. All 19 control cases behave as expected, and the rewrite stays within the R91 word and
   character caps (fixer 370/370 words).

## 1. The crash, step by step (`trace_fastapi_13537.json`)

| step | stage | what happened |
|---|---|---|
| 2 | setup | `run_skill_script(file_path="install.py", skill_name="swe-tools")` ran, and the banner read "swe-tools v10.0 ready in /tmp/swe (9 helpers). Next: python3 /tmp/swe/locate.py "key words"" |
| 3 | setup | text `READY` |
| 4 | locator | `run_command` with `python3 /tmp/swe/locate.py "_get_multidict_value _extract_form_body"` found `fastapi/dependencies/utils.py` L723-958, which is the right file |
| 5 | locator | **function call `view.py`** `{"filepath": "fastapi/dependencies/utils.py", "start_line": 723, "end_line": 958}` (42 completion tokens, empty text) |
| - | harness | `Sandbox execution error: Tool 'view.py' not found. Available tools: run_command, read_file, ...` Result: patch 0 at 13.2 s (`task_results.jsonl` line 45) |

The locator's next instruction was step 2 of `prompts/locator.md:18`: "2. view.py the best candidates; ...". The model
treated the verb "view.py" as a function name, and because it had no schema for that name it borrowed `read_file`'s
(`filepath`, `start_line`, `end_line`, which is exactly the key set of the 415 `read_file` calls in this run). ADK
1.36.1 `functions.py:490-504` raises `ValueError`, and `agent_runner.py:799-801` records a sandbox error with an
empty patch (research/harness_runtime.md section 4).

## 2. Every invented tool name in the v10 race-2 traces

Detector: (a) `function_name` not among the 13 declared and skill tool names, or (b) an agent text containing
`<|tool_call>` whose `call:` name is not one of them. Of the 38 texts in the run that contain `<|tool_call>`, 29 are (b). The other
9 name a real tool but failed to parse (section 5, N3).

| # | trace, step | stage (calls before it in the stage) | name the model used as a tool | outcome of the stage |
|---|---|---|---|---|
| 1 | fastapi_13537 s5 | locator (1) | `view.py` (**parsed**) | task lost, patch 0 |
| 2 | rich_3518 s5 | locator (1) | `python3 /tmp/swe/view.py rich/table.py` | locator ended, plan = this text |
| 3 | rich_3905 s5 | locator (1) | `python3 /tmp/swe/view.py rich/progress.py Progress.stop` | locator ended |
| 4 | fastapi_14873 s29 | locator (25) | `python3 /tmp/swe/verify.py --repro-only <<'EOF' ...` | locator ended |
| 5 | fastapi_14306 s66 | fixer (32) | `view.py fastapi/exceptions.py` | fixer ended |
| 6 | rich_3454 s32 | fixer (1) | `view.py rich/highlighter.py 90 110` | fixer ended |
| 7 | rich_3782 s31 | fixer (15) | `view.py rich/syntax.py` | fixer ended |
| 8 | rich_3894 s18 | fixer (2) | `view.py rich/_inspect.py 100 120` | fixer ended |
| 9 | rich_3930 s39 | fixer (17) | `view.py rich/cells.py 50 100` | fixer ended |
| 10 | rich_4075 s37 | fixer (5) | `view.py README.md 30 50` | fixer ended |
| 11 | fastapi_14616 s21 | fixer (4) | `grep.py "def is_sequence_field" fastapi/dependencies/utils.py` | fixer ended |
| 12 | fastapi_14873 s33 | fixer (3) | `grep.py "class APIRouter" fastapi/routing.py` | fixer ended |
| 13 | fastapi_15280 s18 | fixer (3) | `grep.py "def get(" fastapi/applications.py` | fixer ended |
| 14 | rich_3061 s15 | fixer (8) | `grep.py "def stylize" rich/text.py` | fixer ended |
| 15 | fastapi_14301 s17 | fixer (6) | `python3 /tmp/swe/edit.py fastapi/dependencies/utils.py <<'EOF' ...` | fixer ended, the edit never ran |
| 16 | fastapi_14458 s16 | fixer (2) | `python3 /tmp/swe/edit.py fastapi/dependencies/models.py <<'EOF' ...` | fixer ended, the edit never ran |
| 17 | fastapi_5077 s15 | fixer (1) | `python3 /tmp/swe/edit.py fastapi/dependencies/utils.py <<'EOF' ...` | fixer ended, the edit never ran |
| 18 | rich_3470 s43 | fixer (9) | `python3 /tmp/swe/edit.py rich/console.py <<'EOF' ...` | fixer ended, the edit never ran |
| 19 | fastapi_14301 s18 | verifier (**0**) | `python3 /tmp/swe/status.py` | verifier ended on turn 1 |
| 20 | fastapi_14458 s17 | verifier (0) | `python3 /tmp/swe/status.py` | verifier ended on turn 1 |
| 21 | fastapi_14873 s34 | verifier (0) | `python3 /tmp/swe/status.py` | verifier ended on turn 1 |
| 22 | fastapi_5077 s16 | verifier (0) | `python3 /tmp/swe/status.py` | verifier ended on turn 1 |
| 23 | rich_3470 s44 | verifier (0) | `python3 /tmp/swe/status.py` | verifier ended on turn 1 |
| 24 | rich_3471 s18 | verifier (0) | `python3 /tmp/swe/status.py{}` | verifier ended on turn 1 |
| 25 | rich_3518 s18 | verifier (0) | `python3 /tmp/swe/status.py` | verifier ended on turn 1 |
| 26 | rich_3905 s12 | verifier (0) | `python3 /tmp/swe/status.py` | verifier ended on turn 1 |
| 27 | rich_3953 s41 | verifier (0) | `python3 /tmp/swe/status.py` | verifier ended on turn 1 |
| 28 | fastapi_14487 s56 | verifier (2) | `python3 /tmp/swe/verify.py+run_command{command:...}` | verifier ended |
| 29 | requests_6644 s40 | verifier (10) | `python3 /tmp/swe/finalize.py finalize.py` / `run_command{...}` | verifier ended |
| 30 | fastapi_14616 s75 | verifier (53) | `grep.py -e "def is_sequence_field" ...` | verifier ended |

By stage, that is 4 of 74 locators, 14 of 73 fixers and 12 of 69 verifiers. **The verifier's first action was an
unparsed call in 9 of 69 verifier stages** (58 opened with a proper `status.py` run, 2 with `verify.py`). All 13
submitters opened correctly with `finalize.py`, even though the submitter prompt uses the same "1. python3
/tmp/swe/finalize.py" form.

Row 24 is the closest call. `call:python3 /tmp/swe/status.py{}<tool_call|>` has the braces, and only the space and
the slashes in the name kept the parser's `[\w\-\.]+` from matching. `call:status.py{}` would have crashed.

**Comparison across runs.** The same scanner was used on every run. For these counts, "tool name as a shell
command" means `run_command` was called with a command that begins with a tool name.

| run | parsed invented names | unparsed invented names (tasks) | unparsed calls to real tools | helper name typed as a shell command | tool name typed as a shell command |
|---|---|---|---|---|---|
| r2_v10_1 | 1 (`view.py`) | 29 (20) | 9 | 6 | 2 |
| r2_v9_eog_1 | 0 | 0 | 3 | 0 | 23 |
| Kaggle g4-l4-v4 | 0 | 0 | 1 | 0 | 32 |
| Kaggle g4-l4-v9-eog | 0 | 2 (`call:python3 /tmp/swe/replace.py ...`, fastapi_15800 s78, rich_3944 s21) | 0 | 0 | 29 |

v10 almost removed the old, harmless error, where a tool name was typed into the shell (for example
`run_command python3 ...`, which fails with exit 127 and costs one call). It went from 23-32 per run to 2. At the
same time v10 introduced the dangerous one, where a helper name is used as the tool name. The v9_eog lines that
produced "run_command CMD" shell errors were the `run_command`: `CMD` colon form (fastapi_13537 s34, fastapi_15588
s49 and rich_2725 s38 all came from its verifier step 3). The "Run `python3 /tmp/swe/gate.py`" sentence form
produced neither kind of error. The proposed wording follows it.

## 3. What in the bundle triggers each family

| family | events (section 2 rows) | trigger text | why this is the trigger |
|---|---|---|---|
| T1 locator: helper verb at step 2 | 1, 2, 3 (all at the locator's 2nd call, right after `locate.py`) | `prompts/locator.md:18` "2. view.py the best candidates; grep.py exact names ... view.py --obj it. Print real objects with run.py" | the position matches exactly: step 1 ran through `run_command`, then step 2 began with the bare verb. 3 of 74 locators |
| T2 fixer: the `NAME.py` template list | 5-14, plus the 6 bare shell commands in section 5 N1 | `prompts/fixer.md:20` "Other helpers, each as python3 /tmp/swe/NAME.py: view.py FILE START END, view.py FILE NAME, grep.py "regex", run.py --timeout 20 "command", verify.py, status.py." and `:21` "View files only with view.py ...", `:27` "view.py the plan's FILES." | the calls copy the list items word for word: `view.py FILE START END` became `view.py rich/_inspect.py 100 120`, and `grep.py "regex"` became `grep.py "def get(" fastapi/applications.py`. All 6 bare shell commands are fixer calls in the same shape (`view.py rich/console.py 920-940`, `run.py --timeout 20 "..."`) |
| T3 numbered step that starts with a command | 19-29 | `prompts/verifier.md:29` "1. python3 /tmp/swe/status.py (the diff ...)", `:31` "3. python3 /tmp/swe/verify.py", `:35` "4. python3 /tmp/swe/finalize.py" | 9 of the 11 are the verifier's very first turn, and step 1 is a bare command with no verb and no tool. The fixer's "Run python3 /tmp/swe/verify.py" (with a verb) produced 0 `call:...verify.py` in 73 fixers |
| T4 command-only template lines | 4, 15-18 | the EDITFORM heredoc template `python3 /tmp/swe/edit.py path/to/file.py <<'EOF'` (fixer, verifier, submitter) and the locator's `python3 /tmp/swe/verify.py --repro-only <<'EOF'` | the model wrote the whole heredoc edit as the function name. The EDITFORM header "Edit only with edit.py through run_command" names the helper as a noun and puts the tool second |
| T5 contagion through the handoff | 19, 20, 21, 22, 23 (after 15, 16, 12, 17, 18), 30 (after 11) | SPEC 3.7: the previous stage's final text arrives as "For context: [fixer] said: ..." and, for the locator, as `{plan?}` | 5 of the 9 verifier turn-1 deaths came right after a fixer whose last text was itself an unparsed call. fastapi_14873 cascaded through three stages: locator s29, fixer s33, verifier s34. The submitter then found `NOT READY: EMPTY`, and 2 of its edits broke in the shell (s36 and s37) before it submitted a patch of size 0 at s40. rich_3518's fixer notes quoted the template "VERIFY: the first line verify.py printed (N/A ...)" (s17) just before verifier s18 |

Helper output is a minor trigger. Only 2 of the 30 events (rows 5 and 16) had a bare helper name in the stage's
previous observation. Helper output still needs the same rule, because "Verifier: run finalize.py" is just as
easy to turn into `call:finalize.py{}`.

## 4. Inventory: every place a helper name is used bare

The regex is `(?<![\w.\-/])(install|locate|grep|view|edit|run|verify|finalize|status)\.py(?!\w)`. It runs after the
allowed spans have been blanked out (section 6).

### 4.1 Prompts and SKILL.md: 38 bare names and 4 steps that start with a command

| file:line | text (bare names in bold) |
|---|---|
| locator.md:17 | "1. **locate.py** with the issue's names and error text." |
| locator.md:18 | "2. **view.py** the best candidates; **grep.py** exact names ... dependency: **view.py** --obj it. Print real objects with **run.py** instead ..." (4) |
| fixer.md:8, verifier.md:11, submitter.md:9 | EDITFORM "Edit only with **edit.py** through run_command, ..." (3) |
| fixer.md:11, verifier.md:14, submitter.md:12 | EDITFORM "exact current lines from **view.py** (the number column may stay)" (3) |
| fixer.md:19, verifier.md:22, submitter.md:20 | EDITFORM "... --lines. **edit.py** checks the syntax ..." (3) |
| fixer.md:20 | "Other helpers, each as python3 /tmp/swe/NAME.py: **view.py** FILE START END, **view.py** FILE NAME, **grep.py** "regex", **run.py** --timeout 20 "command", **verify.py**, **status.py**." (6, plus the NAME template) |
| verifier.md:23 | "Other helpers, each as python3 /tmp/swe/NAME.py: **status.py**, **verify.py**, **finalize.py**, **view.py**, **grep.py**, **run.py**." (6, plus the NAME template) |
| fixer.md:21, verifier.md:24 | RAW_IO "View files only with **view.py** and run other code only with **run.py**." (4) |
| fixer.md:27 | "... first. **view.py** the plan's FILES." |
| fixer.md:32 | "VERIFY: the first line **verify.py** printed" |
| verifier.md:30 | "make the plan's change yourself with **edit.py** now" |
| verifier.md:33 | "- RED: fix what it names with **edit.py** and run **verify.py** again" (2) |
| submitter.md:7 | "make the plan's FIX with **edit.py** (...), then run **finalize.py** again." (2) |
| SKILL.md:7 | "Options work as args, for example args file, start and end for **view.py**." (the body is seen only after `load_skill`, which was called 0 times in race 2) |
| verifier.md:29, :31, :35 and submitter.md:6 | steps that start with a command: "1. python3 /tmp/swe/status.py", "3. python3 /tmp/swe/verify.py", "4. python3 /tmp/swe/finalize.py", "1. python3 /tmp/swe/finalize.py" |

setup.md, the YAML descriptions and the SKILL.md frontmatter are clean.

### 4.2 Helper output: 28 bare names in 21 string constants (AST, docstrings excluded)

The "seen" column counts how often the line appeared in the 1,859 helper outputs of r2_v10_1.

| constant (file:line) | text | seen |
|---|---|---|
| CONTEXT_HINT `_swe_common.py:64` | "... Verifier: run **finalize.py** next." | 339 |
| READY `verify.py:20` and `_swe_gate.py:1777` | "NEXT: ready. Fixer: reply with your notes. Verifier: run **finalize.py**." | 90 |
| `_swe_gate.py:1764` | "NEXT: claim %d still fails (%s). Fix the code, then run **verify.py** again." | 71 |
| TIME_HINT `_swe_common.py:59` | "TIME: t>=250s. End your stage now (verifier: run **finalize.py** next)." | 25 |
| `verify.py:381` and `_swe_gate.py:1751` | "VERIFY: NO SOURCE CHANGE - make the plan's change with **edit.py** first." | 20 |
| ALREADY TRIED `edit.py:877` | "... Do something different: python3 /tmp/swe/view.py %s %d %d, then **edit.py** %s --lines %d-%d." | 17 |
| EDIT_NOW_HINT `_swe_common.py:61` | "... Other stages: make the plan's change with **edit.py** now." | 11 |
| EMPTY `finalize.py:139` | "NOT READY: EMPTY - ... with **edit.py**, then run **finalize.py** again." | 11 |
| `_swe_gate.py:1752`, `:1755`, `:1767`, `:1771` | "... with **edit.py**, then run **verify.py** again." and similar | 0 in race 2 |
| SYNTAX `finalize.py:136` | "NOT READY: SYNTAX ERROR ... Fix it with **edit.py**, then run **finalize.py** again." | 0 |
| `verify.py:529` | "NEXT: run **verify.py** once more; ... (verifier: run **finalize.py**)." | 0 |
| REFUSED `edit.py:863` | "...; **edit.py** only edits text files." | 0 |
| DISABLED_NOTE `run.py:20` | "... a reproduction (**verify.py** --repro-only) instead." | 0 |
| `status.py:136` | "CHANGED AFTER FINALIZE: run **finalize.py** again." | 0 |
| `status.py:155` | "PROTECTED (reverted by **edit.py**, **verify.py** and **finalize.py**): " | 0 |
| HANG `view.py:338` | "... read the file with **view.py** FILE instead)" | 0 |

These helper strings are already clean: the install banner (`install.py:34`, "Next: python3 /tmp/swe/locate.py"),
the INSTALL FAILED line (`install.py:31`, which uses the allowed `run_skill_script(file_path="NAME.py", ...)` form),
edit NO MATCH (`edit.py:1099`, `:1107` and `RECIPE` `:27`, all full commands), `edit.py:974` "NEXT: python3
/tmp/swe/verify.py", view beyond EOF (`view.py:301` "Try: python3 /tmp/swe/view.py"), locate no-match (`locate.py:330`),
and LOCATOR, FINISH, FINAL and REPEAT_NOTES (stems only, such as "STOP re-running verify"). Journal lines in
`status.py` output use stems ("verify: ...", "edit fastapi/...") and are also allowed.

## 5. Other near-misses in the v10 traces (no invented tool name, same risk area)

- **N1. A helper typed as a shell command (6, all fixer, all "command not found"):** fastapi_14077 s24 `grep.py
  "HTTP_422_UNPROCESSABLE_ENTITY" ...`, fastapi_15661 s27 `view.py .github/workflows/publish.yml`, rich_3777 s61
  `view.py rich/console.py 920-940` and s76 `grep.py "is_terminal" rich/progress.py`, rich_3934 s33 `view.py
  rich/live.py`, rich_3942 s17 `run.py --timeout 20 "..."`. These come from T2.
- **N2. A tool name typed into the shell or into a helper path (4):** fastapi_14851 s11 `run_command python3
  /tmp/swe/view.py ...`, rich_3676 s27 `write_file --filepath repro_notes.py ...`, rich_4079 s27 `python3
  /tmp/swe/run_command.py --timeout 20 "pytest ..."` (a tool name fused into a helper path), and rich_3061 s20
  `python3 /tmp/swe/verify_tabs.py` (an invented helper). In rich_3061, `write_file` to `/tmp/swe/verify_tabs.py`
  was refused at s19 with "Path traversal detected".
- **N3. A real tool name that failed to parse, which also ends the stage (9):** 6 of these are locator repro heredocs
  cut off at exactly `completion_tokens` 768, the `max_output_tokens` of `configs/gen_locator.yaml`, with no closing
  `<tool_call|>`: fastapi_14301 s10, fastapi_14419 s13, rich_2725 s9, rich_3061 s6, rich_3067 s13, rich_3521 s11.
  The model writes its reasoning as `#` comments inside the reproduction. In each case the locator's "plan" became
  the truncated call (5 of the 6 were still resolved). The other 3 are rich_3278 s67 (verifier), rich_2725 s21 and
  rich_3938 s32 (fixer).
- **N4. Invented argument keys (15 `read_file` calls in 7 tasks):** keys such as `start_line\"`, from the known
  delimiter bug (research/pain_points.md A-class). ADK ignores the key, so the file is read from line 1.
  Examples: fastapi_14851 s40-s55, rich_2725 s29/s38/s39, fastapi_15280 s17.
- **N5. `read_file` versus "view.py":** the fixer and verifier prompts say "View files only with view.py". Even so,
  the run has 415 `read_file` calls, and 27 of 73 fixers opened with `read_file`. The crash call carried
  `read_file`'s argument schema, so the model links the bare word "view.py" to `read_file`. This is an
  inference, not a measurement.
- **N6. A range format from helper output that view.py rejects (2):** fastapi_14851 s10 and fastapi_5624 s6 passed
  `L1191-1433`, the span format that `locate.py` and `grep.py` print, and got "VIEW: no def or class named L1191-1433".

## 6. The wording rule (proposed SPEC 3.0 and 4.0.10 text, R89b)

> **Helper naming (R89b).** In prompts, SKILL.md, YAML descriptions and every string a helper prints, a helper file
> name `NAME.py` appears only inside `python3 /tmp/swe/NAME.py ...` or inside the exact skill call
> `run_skill_script(file_path="NAME.py", skill_name="swe-tools"...)`. Nowhere else: never as a verb ("view.py the
> candidates"), a noun ("with edit.py"), a list item ("status.py, verify.py"), a usage fragment ("view.py FILE START
> END"), a `NAME.py` template list, or a `/tmp/swe/NAME.py` path without `python3 `. Where the full command would
> be repeated, use an English word or a step reference instead ("View the plan's FILES", "run step 3 again", "It checks
> the syntax"). Only stems without `.py` ("verify:", "the run helper") may appear bare.
> **Run instructions (R89c).** An instruction to run a helper is a sentence whose verb comes first: "Run python3
> /tmp/swe/status.py ...". A numbered step never starts with `python3`. The tool is named after the command ("with
> run_command"), never as a `run_command: CMD` prefix, because that form was typed into the shell 23 times per 74
> in v9_eog. Each stage that runs helpers says once: "Helpers run through run_command, not as tools."
> **Helper hints (4.0.10 extended).** Next-step hints in helper output name the full command, for example
> "Verifier: run python3 /tmp/swe/finalize.py next.", the way `edit.py:974` already does.

## 7. The rewrite, checked on a scratch copy

These are applied to a copy of `submissions/v10` in the scratchpad, not to the bundle:

- **EDITFORM (fixer, verifier, submitter):**
  - "Edit only with edit.py through run_command," becomes "Edit only this way, through run_command,".
  - "exact current lines from view.py" becomes "exact current lines as viewed".
  - "edit.py checks the syntax" becomes "It checks the syntax".
- **Locator:**
  - "Helpers (run with run_command):" becomes "Helpers (shell commands for run_command, not tools):".
  - "1. locate.py with the issue's names" becomes "1. Locate the issue's names".
  - "2. view.py the best candidates; grep.py exact names" becomes "2. View the best candidates; grep exact names".
  - "view.py --obj it. Print real objects with run.py instead" becomes "python3 /tmp/swe/view.py --obj it. Print
    real objects instead".
- **Fixer:** fixer.md:20-21 become one line: "Helpers run through run_command, not as tools. View files only with
  python3 /tmp/swe/view.py FILE START END (or FILE NAME), search with python3 /tmp/swe/grep.py "regex" and run other
  code only with python3 /tmp/swe/run.py --timeout 20 "command"."
  - "view.py the plan's FILES" becomes "View the plan's FILES".
  - "the first line verify.py printed" becomes "the first line verify printed".
- **Verifier:** verifier.md:23-24 become "Helpers run through run_command, not as tools. View files only with
  python3 /tmp/swe/view.py FILE START END and run other code only with python3 /tmp/swe/run.py --timeout 20
  "command"."
  - Steps 1, 3 and 4 become "Run python3 /tmp/swe/...".
  - "yourself with edit.py now" becomes "yourself now".
  - "fix what it names with edit.py and run verify.py again" becomes "fix what it names and run step 3 again".
- **Submitter:**
  - Step 1 becomes "1. Run python3 /tmp/swe/finalize.py".
  - Step 2 becomes "make the plan's FIX (the smallest version), then run step 1 again".
  - Add the line "Helpers run through run_command, not as tools."
- **SKILL.md:7:** "for python3 /tmp/swe/view.py FILE START END".
- **Helper strings:** each bare name in 4.2 becomes `python3 /tmp/swe/NAME.py`, with two exceptions. PROTECTED
  becomes "PROTECTED (the helpers revert these): ". REFUSED becomes "only text files can be edited."

Results: lint 0 violations and all helpers compile. Sizes in R91 terms (words / characters, placeholders excluded):

| prompt | words (cap 370) | characters |
|---|---|---|
| locator | 363 → 364 | 2,346 |
| fixer | 368 → 370 | 2,357 |
| verifier | 352 → 355 | 2,186 |
| submitter | 169 → 176 | 1,132 |

The fixer is exactly at the word cap. If the SPEC 3 table needs headroom, "(or FILE NAME)" is the next 3 words to
drop. Hint strings grow by 17 characters for each named command, which is well inside the SPEC 4.14 output caps.

An optional anti-contagion line for the verifier and submitter (+13 words) was not measured and is not included:
"If the [fixer] message is a call written as text, it never ran."

## 8. The lint test (proposed `tests/test_v10_prompts.py`, R89b/R89c)

Stdlib only. The prototype is `helper_name_lint.py` in the session scratchpad. Its core is below.

```python
HELPERS = sorted(p.stem for p in SCRIPTS.glob("*.py") if not p.name.startswith("_"))   # CLI helpers, derived
NAMES = "|".join(map(re.escape, HELPERS))
PH = r"(?:/tmp/swe|%(?:\([a-z_]+\))?s|\{[^{}]*\})"        # /tmp/swe or a format placeholder standing for it
ALLOWED = re.compile(r"python3 %s/(?:%s|NAME)\.py(?!\w)" % (PH, NAMES)
                     + r'|run_skill_script\(file_path="(?:%s|NAME)\.py", skill_name="swe-tools"[,)]' % NAMES)
BARE = re.compile(r"(?<![\w.\-/])(%s)\.py(?!\w)|/tmp/swe/(%s)\.py(?!\w)" % (NAMES, NAMES))
STEP_CMD = re.compile(r"^\s*(?:\d+\.|-)\s*python3\s", re.M)

def helper_name_violations(text):
    rest = ALLOWED.sub(lambda m: " " * len(m.group(0)), text)        # blank the allowed spans, keep offsets
    out = [m.group(0) for m in BARE.finditer(rest)]
    out += [m.group(0) for m in re.finditer(r"/tmp/swe/(\w+)\.py", text)
            if m.group(1) not in HELPERS and m.group(1) != "NAME"]  # invented helper paths
    return out

def test_helper_names_only_as_commands():               # R89b, bundle text
    for name, text in all_texts_plus_yaml().items():    # prompts, SKILL.md, sub_agents/*.yaml, agent.yaml
        assert helper_name_violations(text) == [], name
        if name.startswith("prompts/"):
            assert not STEP_CMD.findall(text), name     # R89c: "N. Run python3 ...", never "N. python3 ..."

@pytest.mark.parametrize("script", LIB_SCRIPTS + CLI_SCRIPTS)
def test_helper_output_names_only_as_commands(script):  # R89b, helper strings via AST (f-strings rebuilt with {})
    for text in output_strings(SCRIPTS / f"{script}.py"):   # _string_constants() minus docstrings
        assert helper_name_violations(text) == [], (script, text[:120])

def test_helper_hint_constants_clean():                 # footers used by every helper
    for h in (C.TIME_HINT, C.EDIT_NOW_HINT, C.CONTEXT_HINT, C.FINISH_HINT, C.LOCATOR_HINT, C.FINAL_HINT,
              *C.REPEAT_NOTES.values(), V.READY):
        assert helper_name_violations(h) == [], h

def test_helper_name_lint_controls():                   # R89b control: the exact race-2 triggers are caught
    for bad in ["2. view.py the best candidates", "each as python3 /tmp/swe/NAME.py: view.py FILE START END",
                "Edit only with edit.py through run_command", "Verifier: run finalize.py.", "cat /tmp/swe/view.py",
                'run_skill_script(file_path="view.py")', "then edit.py %s --lines %d-%d.", "(status.py)",
                "python3 /tmp/swe/verify_tabs.py", "the first line verify.py printed"]:
        assert helper_name_violations(bad), bad
    for good in ["python3 /tmp/swe/view.py FILE START END", 'run_skill_script(file_path="install.py", '
                 'skill_name="swe-tools")', 'Next: python3 %s/locate.py "key words"', "python3 {}/view.py",
                 "NEXT: python3 /tmp/swe/verify.py", "fastapi/routing/run.py", "preview.py and view.pyc",
                 "Run python3 /tmp/swe/edit.py.", "the verify helper"]:
        assert not helper_name_violations(good), good
    assert STEP_CMD.findall("1. python3 /tmp/swe/status.py (x)\n3. Run python3 /tmp/swe/verify.py") == \
        ["1. python3 "]
```

Measured with the prototype:

- **Current bundle:** 70 violations. They are the 38 bare names in the prompts and SKILL.md, the 4 steps that start
  with a command, and the 28 bare names in helper strings.
- **Scratch rewrite:** 0 violations.
- **Controls:** 10 of 10 bad texts caught and 9 of 9 good texts passed.

Add a runtime pass, because some hints are assembled at run time. Run each helper once on the tiny
`v10_support.repo.make_repo` fixture with `run_helper()`, covering each output state in 4.2, and pass stdout to
`helper_name_violations`. Do not name any fixture file `run.py`, `view.py` or similar.

**Trace KPI for `scripts/replay_l4.py`** (race2_checklist.md, next to "crashes"):

```python
TOOLCALL_TEXT = re.compile(r"<\|tool_call>\s*call:([^{<\n]*)")
# per task: parsed = tool_calls whose function_name is not in the stage's declared tools (+ skill tools);
#           unparsed = agent texts where TOOLCALL_TEXT's name is not a declared tool (stage-ending)
# KPI "invented tool names per 74": parsed 0 (hard), unparsed <= 2 (v9_eog race 2: 0; Kaggle v9_eog: 2)
# also report "verifier stages whose first turn is text" (v10 r1: 9/69) and "helper typed as shell" (v10 r1: 6)
```

Note that `load()` in `replay_l4.py` keeps only steps that have `prompt_tokens`. The 13537 crash step has them
(3,630), so no event is lost.

## 9. Tests and SPEC text that pin the current wording (change them together)

- `tests/test_v10_prompts.py`:
  - Line 817 `RAW_IO` requires "View files only with view.py and run other code only with run.py.".
  - Lines 821-822 require the locator text "Print real objects with run.py instead of guessing library types".
    "view.py --obj" still matches the full command.
  - Lines 829 and 832 require "1. python3 /tmp/swe/status.py" and "1. python3 /tmp/swe/finalize.py".
  - Lines 836-842 `ORDER` require "view.py the plan's FILES" and "N. python3 ..." for the verifier and submitter.
  - Lines 343-351 `command_examples` parse the `NAME.py` template list. Once the list is gone, that branch is dead;
    the fixer assertions at 406-409 still hold with the full commands.
- `tests/test_v10_core.py:881, 884` (TIME_HINT, EDIT_NOW_HINT) and `tests/test_v10_runner.py:324` (TIME_HINT).
- `tests/test_v10_finalize.py:24-25, 536`, `tests/test_v10_verify.py:399, 756, 796, 816`.
- `tests/test_v10_run_status.py:18, 216, 233`, `tests/test_v10_edit.py:373`.
- `docs/v10/SPEC.md`:
  - Section 3 prompt text, including lines 339 and 368.
  - The section 3 size table: `test_prompt_sizes` compares against it.
  - The EDITFORM block: `spec_blocks` reads it verbatim.
  - Section 4.0.10.
  - The 4.1 hint constants.

Current state: `tests/test_v10_prompts.py` passes (58 passed), even though the bundle breaks the proposed rule 70
times.

## 10. Outcome impact (paired, one run; treat as indicative)

v10 lost 5 tasks that v9_eog solved. Two of those losses follow directly from this bug:

- **fastapi_13537:** the crash.
- **fastapi_14873:** the three-stage cascade, ending in an empty patch.

Two more losses had near-misses that probably did not decide the outcome:

- **rich_3777:** a bare `view.py` and `grep.py` typed into the shell.
- **rich_3676:** `write_file` typed into the shell.

On the 21 tasks with an invented name, v10 solved 6 and v9_eog solved 7. On the other 53, v10 solved 19 and v9_eog
solved 17.

This class also accounts for 4 of v10's 6 empty patches (13537, 14306, 14873 and 15280 each had an invented-name
event). Removing the triggers does not touch fix quality, which is what limits the solve rate. The honest
expectation is 0 crashes of this class (each one is a certain zero on the scorer), fewer empty patches, and at most
1-2 tasks back per 74.

## 11. How the numbers were made

The scanners were one-off stdlib scripts in the session scratchpad. What they did:

- **Tool-name tallies:** read `steps[].tool_calls[].function_name` and compare against the 13 declared and skill
  tool names.
- **Unparsed calls:** search agent `message` text for `<|tool_call>` and take the `call:` name up to `{`, `<` or a
  newline.
- **Stage position:** count the calls the same `extra.author` made before the event.
- **Previous-stage message:** the last `event_type == "final"` message before the event.
- **Helper output:** read the `stdout` of `run_command` observations whose command starts with `python3 /tmp/swe/`.
- **Truncation:** `metrics.completion_tokens == 768`, with no `<tool_call|>` in the message.

The same code was run unchanged on `r2_v9_eog_1` and on the two unpacked Kaggle L4 runs.
