# v10 race 2 round 1, diagnosis 4: context size, verdict line, rich_4079, can't-open-file

Written 2026-09-29, read-only, from `eval/race2/eval/runs/r2_v10_1` (74 tasks, Kaggle compaction 14,336, L4 clock 1.7)
with `r2_v9_eog_1` as the control. "Step N" is the `step_id` inside
`eval/race2/eval/runs/r2_v10_1/traces/trace_<task>.json`. A stage-run is the checklist's definition (row 10): a maximal
run of consecutive agent steps by one author. "Growth" of a step is `prompt_tokens(next step of the same stage) -
prompt_tokens(this step) - completion_tokens(this step)`, which is the tool result the step added to the stage's prompt.
Every number here comes from the script in the appendix or from `scripts/replay_l4.py`.

## Summary

1. **The fixer and the verifier are where prompts cross 14,336, and harness tools are what push them.** 23 of the 27
   over-line stage-runs are fixers (17) or verifiers (6). In over-line fixer stage-runs, `read_file` output is 40% of
   the growth and raw `run_command` (not a helper) is 27%. For verifiers the shares are 52% and 16%. The helpers, which
   are the only capped and metered route, are 20% and 13%. The prompts say "View files only with view.py and run other
   code only with run.py", yet raw `run_command` or `read_file` made 53% of fixer tool calls and 49% of verifier tool
   calls.
2. **The CONTEXT footer is blind to those calls, and it misfires.** The meter counts helper output only, so 6 fixer and
   6 verifier over-line stage-runs never saw CONTEXT. The meter also carries the locator's count into the fixer, so
   17 of the 28 fixer CONTEXT footers fired on the fixer's first call, at 2,857-3,553 prompt tokens. Fixer obedience to
   CONTEXT was 1 of 28.
3. **The verdict line is missing mainly because stages end on pseudo tool calls.** v10 wrote 36 text replies of the form
   `<|tool_call>call:python3 /tmp/swe/status.py<tool_call|>`. v9_eog wrote 1. A text reply ends a SequentialAgent
   stage. 9 of the 69 verifier stages ended on their first step this way, 6 of them in tasks with no verdict. The same
   confusion caused the one crash (`fastapi_13537` step 5 called a tool named `view.py`). The v10 prompts write every
   helper step as a bare command (`1. python3 /tmp/swe/status.py`). The v9_eog verifier prompt wrote `run_command`
   before each command and listed the declared tools with "There is no other tool". Of the 16 tasks with no verdict:
   8 involve a helper written as a tool call (6 verifier text endings, the `view.py` crash, `fastapi_14616`), 4 hit
   the time cap inside the fixer, 3 had a verifier that never ran plain verify.py, and in 2 verify.py ran but printed
   `VERIFY: NO SOURCE CHANGE`, which the KPI regex does not count.
4. **rich_4079 is a fixer that never edited.** It made 72 calls, 56 of them raw `python3 -c` probes that carry no
   footer, and compacted 3 times, losing the locator's plan each time. Step 96 says "the [locator] message is missing!",
   because v10's fixer prompt no longer has `{plan?}`. Its last reply was 917 tokens, 28.4 s on the L4 model, and that
   reply alone carries it past cap + 10 s (328.0 s replayed, against 310).
5. **Neither can't-open-file call is a missing helper.** Both name scripts that never existed:
   `/tmp/swe/run_command.py` (`rich_4079` step 27) and `/tmp/swe/verify_tabs.py` (`rich_3061` step 20). Helper
   availability was 74/74.

## 1. Which stages and tools push prompts over 14,336

### 1.1 By stage

`r2_v10_1`: 303 stage-runs, 276 under the line (0.911), max 17,388. `r2_v9_eog_1`: 213 stage-runs, 0.845, max 20,729.

| stage | over / stage-runs | tool calls | raw run_command | read_file | raw + read_file share |
|---|---|---|---|---|---|
| setup | 0 / 74 | 74 | 0 | 0 | 0% |
| locator | 4 / 74 | 1,163 | 62 | 24 | 7% |
| fixer | 17 / 73 | 1,119 | 356 | 240 | 53% |
| verifier | 6 / 69 | 678 | 194 | 136 | 49% |
| submitter | 0 / 13 | 68 | 7 | 15 | 32% |

Share of growth in over-line stage-runs (tool output plus the model's own output):

| stage | read_file | raw run_command | helpers | model output |
|---|---|---|---|---|
| fixer (401,809 tokens) | 40% | 27% | 20% | 12% |
| verifier (125,128) | 52% | 16% | 13% | 18% |
| locator (79,251) | 23% | 9% | 60% | 8% |

### 1.2 The 27 over-line stage-runs

"Growth mostly from" counts tool output only. A CONTEXT at the stage's first step is the misfire described in 1.3(b).

| task | stage | steps | calls | peak (step) | compactions | growth mostly from | largest single step | first CONTEXT at step |
|---|---|---|---|---|---|---|---|---|
| rich_3782 | fixer | 16-31 | 16 | 17,388 (26) | 1 | raw 83%, read_file 11% | 25 +8,802 (raw) | 16 |
| rich_3772 | fixer | 21-56 | 36 | 17,192 (41) | 2 | raw 62%, helper 27% | 40 +3,885 (raw heredoc script written into /tmp/swe) | 21 |
| rich_2725 | fixer | 10-21 | 12 | 16,754 (21) | 0 | read_file 55%, helper 44% | 20 +4,243 (verify --repro-only, see 6.4) | 20 |
| rich_3938 | fixer | 23-32 | 10 | 16,483 (32) | 0 | read_file 76%, raw 24% | 31 +3,167 (raw, see 6.4) | never |
| fastapi_15280 | verifier | 19-106 | 88 | 16,191 (98) | 3 | read_file 86%, helper 10% | 100 +1,553 (read_file) | never |
| rich_3676 | fixer | 24-42 | 19 | 16,028 (36) | 1 | raw 64%, helper 36% | 32 +2,811 (raw) | 24 |
| fastapi_5624 | fixer | 14-71 | 58 | 16,027 (56) | 2 | read_file 44%, raw 38% | 55 +2,370 (raw) | never |
| rich_4079 | fixer | 25-96 | 72 | 15,850 (39) | 3 | raw 72%, read_file 19% | 85 +2,062 (read_file) | never |
| fastapi_14986 | fixer | 15-38 | 24 | 15,409 (24) | 1 | read_file 85%, helper 9% | 26 +1,829 (read_file) | never |
| fastapi_14306 | fixer | 34-66 | 33 | 15,303 (64) | 2 | read_file 89%, helper 7% | 60 +1,912 (read_file) | never |
| rich_2725 | verifier | 22-56 | 35 | 15,292 (39) | 2 | read_file 77%, helper 22% | 38 +2,068 (read_file) | never |
| fastapi_14873 | locator | 4-29 | 26 | 15,245 (19) | 1 | helper 71%, read_file 26% | 24 +1,429 (read_file) | 10 |
| fastapi_14851 | fixer | 28-56 | 29 | 15,241 (52) | 2 | read_file 94%, raw 5% | 34 +1,656 (read_file) | never |
| rich_3043 | fixer | 13-72 | 60 | 15,076 (28) | 2 | helper 85%, raw 15% | 20 +2,292 (raw pytest) | 13 |
| fastapi_15589 | fixer | 16-63 | 48 | 15,063 (33) | 2 | read_file 71%, helper 14% | 35 +1,795 (read_file) | 39 |
| rich_3777 | locator | 4-58 | 55 | 14,871 (21) | 2 | helper 57%, read_file 36% | 31 +1,848 (read_file) | 16 |
| rich_4076 | fixer | 21-59 | 39 | 14,756 (44) | 1 | read_file 61%, helper 33% | 55 +2,015 (verify) | 32 |
| rich_3278 | fixer | 18-62 | 45 | 14,657 (40) | 1 | read_file 55%, helper 42% | 23 +1,681 (read_file) | 19 |
| rich_4075 | locator | 4-31 | 28 | 14,592 (21) | 1 | helper 100% | 15 +999 (view) | 13 |
| rich_3930 | verifier | 40-73 | 34 | 14,581 (69) | 1 | helper 45%, read_file 29% | 42 +1,527 (read_file) | never |
| fastapi_15800 | fixer | 22-76 | 55 | 14,566 (46) | 1 | read_file 54%, helper 31% | 67 +1,372 (raw) | 22 |
| fastapi_9425 | fixer | 22-63 | 42 | 14,490 (58) | 1 | read_file 65%, raw 22% | 30 +1,397 (read_file) | 58 |
| rich_3782 | verifier | 32-49 | 18 | 14,444 (41) | 1 | raw 80%, helper 16% | 34 +8,798 (raw) | never |
| rich_3061 | verifier | 16-80 | 65 | 14,385 (47) | 1 | read_file 51%, raw 40% | 18 +1,769 (read_file) | never |
| fastapi_14616 | verifier | 22-75 | 54 | 14,368 (71) | 1 | read_file 66%, raw 29% | 32 +1,570 (read_file) | never |
| fastapi_14487 | locator | 4-48 | 45 | 14,368 (38) | 1 | helper 42%, raw 32% | 13 +1,762 (read_file) | 46 |
| rich_3930 | fixer | 22-39 | 18 | 14,352 (39) | 0 | read_file 76%, helper 23% | 25 +2,575 (read_file) | 22 |

Two shapes account for these rows. 12 of the 27 are runaways of 42 to 88 calls, where no single output is large.
The rest are short stages that crossed on a few large raw or `read_file` outputs.

### 1.3 Mechanisms

**(a) Unmetered, uncapped harness output.**
- `read_file`: 376 fixer and verifier calls. 130 of them have no `end_line`, so each returns 150 lines, up to 10,000
  chars. 165 follow another `read_file`, which means paging through a file. Growth per call is p50 548 and p90 1,671
  tokens. 27 of the 73 fixer stages start with `read_file`, even though the prompt's first step is "view.py the plan's
  FILES". Example: `fastapi_14851` fixer steps 28-56, 19 `read_file` calls, 94% of its growth. At steps 51 and 55 the
  keys are malformed (`start_line\"`), so the call returns the top of the file.
- Raw `run_command`: 613 calls, 366 of them `python3 -c`, adding 170,780 tokens. There is no ANSI stripping: 18 outputs
  carry escape codes and add 38,964 tokens, e.g. `rich_3782` steps 25, 30 and 34, where `Console(force_terminal=True)`
  printed 5,000 chars of `\x1b[40m` and cost about 8,800 tokens each time. There is no token cap on box drawing: 39
  outputs add 40,081 tokens, e.g. `rich_4079` steps 33-39 at about 1,600 tokens per rendered table. Errors are printed
  twice (`error_message` plus `details`): 104 raw calls returned an error and together added 56,699 tokens. No repeat
  note fires: `rich_3061` verifier steps 38-47 ran the same `python3 -c` ten times and `rich_3180` fixer steps 87-92
  ran it six times. And there is no helper timeout: `fastapi_14258` step 25 (`python3 repro.py`) and `rich_3480`
  step 21 each hung for the harness's 106 s.
- Every helper applies `run.py`'s treatment (`clean_text` strips ANSI, `collapse` folds repeated lines, 2,500-char and
  833-token caps, repeat notes, a 20 s timeout, the footer). Raw calls skip all of it.

**(b) The meter carries the locator's count into the fixer.** `ctx_next` (`_swe_common.py:1759`) resets only on
`status.py`, and it moves from the locator phase to the fixer phase only at the first `edit.py`. The locator reached
CONTEXT in 43 of 74 stage-runs. So when the fixer's first helper is a view, locate or repro call, the fixer is told
"this stage's context is nearly full" with a near-empty prompt. That happened in 17 fixer stage-runs, at 2,857-3,553
tokens: `rich_3782` step 16 (3,378), `rich_3043` step 13 (3,020), `fastapi_15800` step 22 (3,221), `rich_3930`
step 22 (3,010), and 13 more. The submitter shows the same carry: `fastapi_14873` step 35 and `rich_3470` step 45
got CONTEXT on their first call, because the verifier never ran status.py. Fixer CONTEXT obedience was 1/28
(locator 18/43, verifier 0/1, submitter 0/2).

**(c) CONTEXT never reaches the long fixer and verifier stages.** It is computed from helper output only, and after
t = 210 s FINISH and TIME take priority over it (`hint()`, `_swe_common.py:1700`). 6 fixer and 6 verifier over-line
stage-runs never saw it (the "never" rows in 1.2).

**(d) Repetition.** Exact repeats of a call inside one stage, with no compaction between them, add 116,908 tokens:
217 raw commands (40,547 tokens), 81 `verify.py` (20,148), 18 `read_file` (16,902), 114 `run.py` (13,617). `run.py`
and `verify.py` do print repeat notes. Raw commands and `read_file` cannot.

**(e) The locator ignores CONTEXT while working through helpers.** In the 4 over-line locators, CONTEXT arrived at
7,826 (`fastapi_14873` step 10), 9,725 (`rich_3777` step 16), 7,790 (`rich_4075` step 13) and 5,715
(`fastapi_14487` step 46). Those locators then made 19, 42, 18 and 2 more calls. The locator is 92% helpers, so there
the meter is accurate and the missing piece is enforcement.

### 1.4 Counterfactual: what capping the harness routes would buy

Re-summing each over-line stage-run with every `read_file` growth capped at view.py's 933-token cap and every raw
growth capped at run.py's 833. The lower figure keeps every later step, including recovery calls that only happen
after compaction (pessimistic). The upper figure stops at the first compaction (optimistic).

| change | stage-runs under 14,336 |
|---|---|
| as run | 0.911 |
| read_file capped | 0.924-0.967 |
| raw run_command capped | 0.924-0.941 |
| both | 0.934-0.993 |
| both, exact repeats dropped | 0.941-0.993 |

Routing the fixer's and verifier's I/O through the helpers is necessary and probably close to sufficient for 0.95.
The 12 runaway stage-runs also need their length bounded, and in the fixer and verifier only prompts can do that (5.2).

## 2. Why 16 tasks have no VERIFY verdict line (row 13: 58/74 = 0.784)

| cause | tasks (trace, steps) |
|---|---|
| **Verifier's first reply was a pseudo tool call in text** (`<|tool_call>call:python3 /tmp/swe/status.py<tool_call|>`); the stage ended and the submitter finalized without verify.py (6) | fastapi_14301 18, fastapi_14458 17, fastapi_14873 34, fastapi_5077 16, rich_3470 44, rich_3518 18 |
| **No verifier stage: the fixer ran into the time cap without editing** (4) | fastapi_14258 (step 25: raw `python3 repro.py` hung 106 s), fastapi_14851 (19 read_file, 0 edits, steps 28-56), rich_3180 (67 raw `python3 -c`, identical at steps 87-92), rich_4079 (section 3) |
| **Crash before the verifier**: locator called a tool named `view.py` (1) | fastapi_13537 5 (`Tool 'view.py' not found`, the row-3 unknown_tool crash) |
| **Verifier ran but never ran plain verify.py** (3) | fastapi_13920 (steps 48, 50-52: `verify.py --repro-only` four times, then finalize 53), fastapi_14616 (steps 23-71: 49 raw grep and `python3 -c`, compaction 71 to 72, then pseudo call `grep.py` at 75), rich_3061 (steps 23-47 raw `python3 -c` loop, compaction 47 to 48, the same loop again 55-77, finalize at step 78 at t=274) |
| **verify.py ran and printed `VERIFY: NO SOURCE CHANGE`**, which is not in the KPI regex (2) | fastapi_14306 68 (t=277), fastapi_15280 98 (t=250) |

**Pseudo tool calls are v10's new failure.** Across all stages: locator 9, fixer 14, verifier 13, and every one of them
ended its stage. `r2_v9_eog_1` had 1. The names used:
- `python3` as the function name (`call:python3 /tmp/swe/status.py`): 18;
- `run_command` with a body that did not parse: 7;
- `view.py`: 6;
- `grep.py`: 5.

Where they come from:
- **Bare commands in the prompts.** The v10 prompts write each helper step as a bare command (`verifier.md` step
  "1. python3 /tmp/swe/status.py", `submitter.md` "1. python3 /tmp/swe/finalize.py", the fixer's "view.py FILE START
  END") and never say which tool runs them. v9_eog's verifier wrote `run_command`: `git diff` and ended with "Tools you
  can call: run_command, ... There is no other tool". R89 lints tool names, but it cannot catch a helper written where a
  tool call should be.
- **Imitating the fixer's handoff.** In 5 of the 9 verifier cases the fixer's last message was itself a pseudo call:
  `fastapi_14301` 17, `fastapi_14458` 16, `fastapi_14873` 33, `fastapi_5077` 15, `rich_3470` 43. The verifier reads
  that message as "the [fixer] message below" and copies its form. In 4 of them the fixer's pseudo call was an
  `edit.py` call, which never ran.
- **Truncation at the locator's output cap.** 6 locator pseudo calls are well-formed `run_command` calls cut off at
  exactly 768 completion tokens, the locator's `max_output_tokens`: `fastapi_14301` 10, `fastapi_14419` 13,
  `rich_2725` 9, `rich_3061` 6, `rich_3067` 13, `rich_3521` 11. The reproduction heredoc was full of reasoning in
  comments (`fastapi_14301` step 10), so the fixer received a truncated tool call as its plan.

Temperature is not the difference: v9_eog also sampled at 1.0. The submitter, at 0.2, made 0 pseudo calls, but the
submitter prompt uses the same bare form.

## 3. rich_4079: past cap + 10 s (row 12)

Replayed at 328.0 s against the 310 s limit (`replay_l4.retime`). By stage: setup 4.1 s; locator 80.4 s (21 calls);
fixer 226.7 s (72 calls, of which decode is 176.4 s); 3 compactions at 5.6 s each.

1. **The locator's plan was prose with no FILES line.** The locator made 15 `run.py` probes (steps 7-23), then got
   CONTEXT at step 23 (9,999 tokens) and obeyed at step 24 (261 tokens).
2. **The fixer never edited.** Across steps 25-96 it ran 56 raw `python3 -c` probes that print rich tables with
   `force_terminal=True`: box drawing, some with ANSI, at about 1,600 tokens per call (steps 33-39). It also invented a
   helper at step 27 (section 4), ran raw pytest at step 28, and made 5 `read_file` calls asking for 150-300 lines
   (steps 65, 85, 89-91).
3. **The footers reached it only on its rare helper calls**, and it obeyed none of them: LOCATOR at steps 31 and 40
   (t=84, 119), EDIT NOW at 56-57 (t=177, 179), FINISH at 83-84 (t=248), TIME at 94-95 (t=273). The raw calls in
   between carry no footer.
4. **Three compactions at 15,850 (39 to 40), 15,411 (55 to 56) and 14,509 (82 to 83).** Each wiped the stage. After
   each one it re-ran locate.py or status.py and restarted exploring. status.py shows the journal but not the plan, and
   the fixer prompt has had no `{plan?}` since review round 2 ("handoff paid once"). The final reply at step 96 says
   the plan "is missing from the prompt but mentioned in the instructions" and "the [locator] message is missing!".
   Compacted tasks resolved 3/23 in this run, against 22/51 not compacted (v9_eog: 3/24 against 21/50).
5. **The final reply ran to 917 tokens** (the prompt allows "under 60 words") after TIME said "End your stage now".
   That is 28.4 s on the L4 model. With a 60-token reply the task replays at about 302 s, under the limit, so the reply
   is the proximate cause and the no-edit loop is the root cause. Fixer text replies are p50 42 and p90 116 tokens in
   this run. Two exceeded 500 (this one and a 2,048-token runaway).
6. **Its patch is only scratch.** It adds `out.txt` and `output.txt` (finalize at step 95 said NOT READY: EMPTY and
   removed `repro*.txt`, but it does not remove `out*.txt`). Row 8 does not catch these, because `*.txt` is not in its
   scratch rule.

**Row 12 only checks 51 of the 74 tasks.** `gate()` uses the ids shared with `r_v4`. Over all 74, three v10 tasks
replay past cap + 10 s:
- `rich_3061`: 330.0 s, verifier raw loop, 1 compaction;
- `rich_4079`: 328.0 s;
- `fastapi_14306`: 313.9 s, fixer with no edit, 2 compactions, verify at t=277.

v9_eog has 10 on the same basis, so v10 is better on time. The 51-id view still hides 2 of the 3.

## 4. The 2 can't-open-file helper calls (row 5: 2/74 = 0.027, limit 0.02)

| task, step | stage | command | what happened |
|---|---|---|---|
| rich_4079 27 | fixer | `python3 /tmp/swe/run_command.py --timeout 20 "pytest tests/test_table.py"` | an invented helper that mixes the `run_command` tool with `run.py`; the next step (28) ran pytest raw |
| rich_3061 20 | verifier | `python3 /tmp/swe/verify_tabs.py` | step 19 tried `write_file` to `/tmp/swe/verify_tabs.py` and was refused ("Path traversal detected ... escapes workspace root"); it ran the script anyway, then wrote it into /workspace (step 21) and ran it there (22) |

Both helpers were installed; install succeeded in 74/74 tasks. Row 5's regex counts any `/tmp/swe/*.py` path, so
invented names count as missing helpers. Neither stage wasted a call reinstalling.

## 5. Proposals

In rough order of expected effect. Each lists the regression test it needs (standing rule: every bug gets one), and all
are stdlib-only.

### 5.1 Write every helper call in the explicit tool form (verdict, crash, stage endings)

- **Prompt change.** In all stage prompts, write each helper step as `run_command(command="python3 /tmp/swe/status.py")`
  (and likewise verify.py, finalize.py, view.py and the edit.py heredoc form), in template order and with no braces or
  backticks (rules 1-3). Add one line per stage: "Helpers run only through run_command; python3, view.py, grep.py and
  status.py are not tools."
- **Verifier.** Say "verify.py with no flags" in step 3, which covers `fastapi_13920`.
- **Handoff.** Tell the verifier that a [fixer] message that is a tool call is not the fixer's notes, so it should start
  from status.py (5 of the 9 cases).
- **Locator.** Allow no comments in the reproduction except `# CLAIM` lines, and at most 25 lines. This keeps the 6
  locator calls cut at 768 tokens from happening.
- **Tests.**
  - TP lint: no numbered step starts with a bare `python3 /tmp/swe/`, and every helper named in a step sits inside
    `run_command(command="...")`.
  - R96 `RULES` and `ORDER` updated to the new strings.
  - A reported (not gating) replay row in `replay_l4`: text replies containing `<|tool_call>` per 74 tasks (v10 36,
    v9_eog 1), plus the share of verifier stages whose first step is text (v10 9/69).
- **Expected effect.** Up to 8 of the 16 no-verdict tasks (6 first-step verifier endings, the crash, and
  `fastapi_14616`'s ending), plus `fastapi_13920`: about 67/74 = 0.905 at best.
- **Side effect.** The 36 stages that ended early will run longer. The 9 verifiers start at 2,800-4,200 tokens, so the
  context risk is small.

### 5.2 Give the fixer and verifier a metered way to try code and read files (row 10, time)

- **run.py heredoc mode.** `run_command(command="python3 /tmp/swe/run.py <<'EOF'` plus Python lines plus `EOF")` runs
  the body with `python3 -` in /workspace. It gets run.py's timeout, ANSI stripping, line collapsing, char and token
  caps, repeat note and footer.
  - Why: the 366 raw `python3 -c` calls exist because run.py needs nested quoting for Python code and a raw call does
    not.
  - Prompts: "try code only with run.py <<'EOF'; never python3 -c or python3 file.py".
  - Tests: empty stdin; ANSI output stripped; box-drawing output held under `CAP_TOKENS["run"]`; a hang killed at the
    timeout with the TIMEOUT line; the same code twice gives the repeat note; exit code on line 1; stdout and stderr
    merged once, not duplicated.
- **Plan lines that are view.py commands.** The locator's reply template writes each FILES line as a ready command,
  `python3 /tmp/swe/view.py path START END (function)`, instead of `path:start-end`.
  - Why: the current form maps directly onto `read_file(filepath, start_line, end_line)`, and 27 of 73 fixers opened
    with `read_file`.
  - Test: TP lint on the locator template, and the handoff-size model in `test_v10_prompts` re-derived.
- **A stage call budget in the prompts** (fixer and verifier: "at most 25 tool calls; then reply"). This is the only
  length bound available for stages whose calls do not reach the meter. Test: a prompt lint that the number matches a
  constant.
- **Expected effect.** 1.4 bounds the output caps alone at 0.934-0.993. The budget targets the 12 runaway rows.

### 5.3 Fix the context meter (row 10, footer obedience)

- **(a) Reset at the fixer's start.**
  - Change: the fixer's step 1 becomes `run_command(command="python3 /tmp/swe/status.py")`. That already sets n = 0.
    Also make `ctx_next` treat a `status` call in phase `locator` as the start of the fixer phase.
  - Cost: about 1 s on L4 and the status output (mean 444 tokens, or less with a `--brief` form that prints the one
    STATUS line and the repro state).
  - Removes the 17 first-call misfires, and the 2 on the submitter if the submitter also starts with status.py or
    finalize resets the meter.
  - Test: `ctx_next` regression. Locator calls to 6,000 estimated tokens, then status, then view: the hint is not
    CONTEXT. Locator views to 6,000, then edit: the carry is at most 3 views (the existing behaviour, kept).
- **(b) Enforce CONTEXT in the locator.**
  - Change: in phase `locator`, after CONTEXT has been shown 3 times since the last reset, a helper prints only its
    first line and "CONTEXT: output withheld; reply with your plan now".
  - This is safe only with (a) in place, so that a fixer is never taken for a locator. The 4 over-line locators would
    have stopped at about CONTEXT + 3 outputs: 7.7k-11.7k tokens, not 14.4k-15.2k.
  - Test: phase `locator` plus 3 CONTEXT displays means the 4th output is withheld; phase `fixer` never withholds;
    status resets the count.
- **(c) Do not rely on a wall-clock surcharge.** I tested it: charging unaccounted seconds between helper calls to the
  meter correlates only 0.48 with the unmetered tokens (572 helper calls, fixer and verifier). It is too noisy to gate
  on.

### 5.4 Keep the plan across a fixer compaction (rich_4079, solves)

There were 22 fixer compactions in 14 tasks. After each one the fixer has no plan, because `{plan?}` was removed in
review round 2 and the handoff event is gone. There are two options:
- **(a)** Restore `{plan?}` in the fixer and `{fix_notes?}` in the verifier. This costs the plan once more on every
  fixer call (race-2 locator replies: p50 282, p90 735 tokens), which works against row 10 until 5.2 lands.
- **(b)** Zero cost: status.py prints the files and ranges the locator viewed (it already journals every view.py call)
  under a `LOCATOR VIEWED:` line, so a recovering fixer gets the FILES back. Test: status output after locator views
  lists them, capped at 4 entries.

I would do (b) now and measure (a) on the 14 fixer-compacted tasks.

### 5.5 Short replies at FINISH and TIME (row 12)

The TIME footer becomes "TIME: t>=250s. Reply now in one line, under 30 words (verifier: run finalize.py next)", and
FINISH likewise. Test: the hint strings name the word limit, and `test_prompt_times_match_helper_clock` still passes.
This removes the 917-token reply that put `rich_4079` over. There is no other lever on the reply: the fixer's
`max_output_tokens` has to stay at 2,048 for edit heredocs.

### 5.6 Close the can't-open-file gap (row 5)

- `install.py` writes a one-line alias `/tmp/swe/run_command.py` that runs `run.py` with the same arguments. It is
  generated at install time, so the bundle's file set does not change. Test: after install the alias exists, forwards
  `--timeout` and the command, and prints run.py's output.
- 5.1 removes where the blend comes from.
- `verify_tabs.py` is a scratch script, and the harness already refused to write it. No helper fix is needed.

### 5.7 Finalize prints its quick verdict (row 13, a backstop)

finalize.py already runs a quick evaluation (`G.evaluate(quick=True)`, `finalize.py:115`) whenever the current diff has
no score, and computes the verdict word, but never prints it. Printing `VERIFY: <word> (quick, finalize)` costs about
10 tokens. It would give a checked verdict in tasks where only the submitter ran. It moves row 13 without changing the
verifier's behaviour, though, so report "verdict from verify.py" and "verdict from finalize" as separate replay rows.
Test: finalize on a diff with no checkpoint score prints exactly one VERIFY line; on a scored diff it prints none.

## 6. Measurement notes (for an addendum, not a threshold change)

1. **Row 13** misses `VERIFY: NO SOURCE CHANGE` (2 tasks). Its intent is "verify.py ran", and in those tasks it did.
   Report it separately rather than adding it to the regex: those are no-edit failures, not verifier failures.
2. **Row 5** should count only the 9 helper names (install, locate, grep, view, edit, run, verify, finalize, status),
   with invented names reported apart. On that basis round 1 has 0 missing helpers.
3. **Row 12**'s over-cap check covers the 51 ids shared with `r_v4`. Over all 74 there are 3 tasks past cap + 10 s,
   against 1.
4. **Two prompt jumps are not explained by the tool output:**
   - `rich_2725` step 20 to 21: +4,243 tokens from a 356-char result;
   - `rich_3938` step 31 to 32: +3,167 tokens from a 105-char result.

   Both are the fixer's last call, and in both the next response mixes a pseudo-call text block with a real
   `status.py` call. That looks like an intermediate generation that the trace does not record. It does not change the
   conclusions above: 7.4k of 606k over-line tokens.
5. **Row 8's scratch rule** does not catch `out.txt` or `output.txt` (`rich_4079`), and finalize's `clean_scratch`
   does not remove them.

## Appendix: reproduce

Save the script below as `diag4.py` and run `python3 diag4.py eval/race2/eval/runs/r2_v10_1` from the repo root. It
prints the stage split, the growth shares, the call mix, the pseudo-call counts, the first-call CONTEXT misfires, the
no-verdict ids and the can't-open-file calls. On `r2_v9_eog_1` it gives 0.845, max 20,729, and 1 pseudo call. The time
figures come from `replay_l4`: `R.retime(R.load('r2_v10_1', runs_dir='eval/race2/eval/runs')['rich_4079'])` is 328.0.
Its rules: a stage-run is consecutive agent steps with one author; growth is the next same-author `prompt_tokens`
minus this step's prompt and completion tokens, and a drop of more than 1,000 is a compaction and is skipped; a helper
is a `run_command` naming one of the 9 helper names under `/tmp/swe/`, or `run_skill_script`; raw is any other
`run_command`; a pseudo call is an agent step with no tool call whose message contains `<|tool_call>`.

```python
"""Headline numbers of docs/v10/v10_1_diag_4.md. Stdlib only. Run from the repo root:
python3 diag4.py eval/race2/eval/runs/r2_v10_1"""
import collections, glob, json, os, re, sys
RUN = sys.argv[1] if len(sys.argv) > 1 else "eval/race2/eval/runs/r2_v10_1"
LINE = 14336
HELP = {"view", "grep", "locate", "edit", "verify", "status", "finalize", "run", "install"}
V = re.compile(r"VERIFY: (GREEN|AMBER|RED|UNKNOWN)")

def obs(s):
    o = s.get("observation")
    return str(o.get("content") or "") if isinstance(o, dict) else str(o or "")

def tool(s):
    if not s["fn"]:
        return "TEXT"
    if s["fn"] == "run_command":
        c = str((s["args"] or {}).get("command", ""))
        m = re.search(r"/tmp/swe/(\w+)\.py", c)
        return ("helper" if m.group(1) in HELP else "raw") if m else "raw"
    return "read_file" if s["fn"] == "read_file" else ("helper" if s["fn"] == "run_skill_script" else "other")

tasks = {}
for fp in sorted(glob.glob(os.path.join(RUN, "traces", "trace_*.json"))):
    st = []
    for s in json.load(open(fp))["steps"]:
        if s["source"] != "agent" or (s.get("metrics") or {}).get("prompt_tokens") is None:
            continue
        tc = s.get("tool_calls") or []
        a = (s.get("extra") or {}).get("author") or (tc and (tc[0].get("extra") or {}).get("author")) or "?"
        st.append(dict(sid=s["step_id"], a=a, pt=s["metrics"]["prompt_tokens"], ct=s["metrics"].get("completion_tokens") or 0,
                       fn=tc[0]["function_name"] if tc else None, args=tc[0].get("arguments") if tc else None,
                       obs=obs(s), msg=str(s.get("message") or "")))
    tasks[os.path.basename(fp)[6:-5]] = st

runs, growth, over_growth = [], collections.Counter(), collections.defaultdict(collections.Counter)
for iid, st in tasks.items():
    cur = None
    for i, s in enumerate(st):
        if cur is None or s["a"] != cur[1]:
            cur = [iid, s["a"], []]
            runs.append(cur)
        cur[2].append(i)
for iid, a, idx in runs:
    st = tasks[iid]
    peak = max(st[i]["pt"] for i in idx)
    for j in range(len(idx) - 1):
        s, n = st[idx[j]], st[idx[j + 1]]
        d = n["pt"] - s["pt"] - s["ct"]
        if d < -1000:
            continue          # compaction
        if peak >= LINE:
            over_growth[a][tool(s)] += d
            over_growth[a]["model output"] += s["ct"]
peaks = [max(tasks[iid][i]["pt"] for i in idx) for iid, _, idx in runs]
print("stage-runs %d, under %.3f, max %d" % (len(runs), sum(p < LINE for p in peaks) / len(runs), max(peaks)))
by = collections.Counter(r[1] for r in runs)
ov = collections.Counter(r[1] for r in runs if max(tasks[r[0]][i]["pt"] for i in r[2]) >= LINE)
print("over-line by stage", {k: "%d/%d" % (ov[k], by[k]) for k in by})
for a, c in over_growth.items():
    tot = sum(c.values())
    print("over-line growth", a, tot, {k: round(v / tot, 2) for k, v in c.most_common()})
calls = collections.defaultdict(collections.Counter)
for st in tasks.values():
    for s in st:
        calls[s["a"]][tool(s)] += 1
print("call mix", {a: dict(c) for a, c in calls.items()})
pseudo = collections.Counter((s["a"]) for st in tasks.values() for s in st if not s["fn"] and "<|tool_call>" in s["msg"])
print("pseudo tool calls (text replies)", dict(pseudo), "total", sum(pseudo.values()))
first_ctx = [(iid, s["sid"], s["pt"]) for iid, a, idx in runs if a == "fixer" for s in [tasks[iid][idx[0]]]
             if "CONTEXT: this stage" in s["obs"]]
print("fixer CONTEXT at the stage's first call", len(first_ctx), sorted(p for _, _, p in first_ctx))
nov = [iid for iid, st in tasks.items() if not any(V.search(s["obs"]) for s in st)]
print("no verdict", len(nov), "/", len(tasks), nov)
co = [(iid, s["sid"], s["a"], s["args"]["command"][:60]) for iid, st in tasks.items() for s in st
      if s["fn"] == "run_command" and "/tmp/swe/" in str(s["args"]) and "can't open file" in s["obs"]]
print("can't open file", co)
```
