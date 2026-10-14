# Where the 5 minutes go on the 42 never-solved public tasks (Phase A)

Written 2026-10-14 (IST) on the Mac, offline. No model, GPU or paid API was used. Inputs: the six box runs of the 74 public
tasks (same A6000, same pace proxy, same 5-minute cap): p4 (v5h2), p4_v7, p4_v7c, p4_v7d (thinking-off pipelines), p4_b1024
(v12-b1024, our current line, thinking on, budget 1,024) and p4_v0t2 (v0-think, the official starter with thinking on, budget
4,096), plus the two Kaggle L4 runs that kept traces (e74_v2, e74_v3) for the command-duration census. The 42 ids are
data/never_solved_box5_ids.txt (no solve in the first five runs). Labels: MEASURED (read from traces/proxy logs), ESTIMATE (a
model of something not logged), INFERRED.

Every number below comes from one command (about 1 s, reads only committed files):

    .venv/bin/python scripts/forty_two/timing_report.py --json /tmp/timing.json

Per-task clock: `scripts/forty_two/timing.py RUN_DIR PROXY_LOG [--table]` (method in its docstring, summarised in section 1).

## 0. Answers in one screen (p4_b1024, the 42, 280 agent-seconds per task on average, 30 of 42 at the cap)

| # | where the time goes / is lost | seconds on the 42 | tasks | what it is | label |
|---|---|---|---|---|---|
| 1 | model decode | 173 s per task (7,266 s) of 228 model s | 42 | ~75 % of output tokens are thinking (char-share estimate); 25 calls per task at 9.2 s each | MEASURED (thinking split ESTIMATE) |
| 2 | locating: search + read calls | 116 s per task (17.4 calls) vs 58 s (9.4 calls) on the 28 solved | 42 | the 42 search twice as long; 21 of 42 never make a source edit; solved tasks first edit at call 10 / 114 s (median) | MEASURED |
| 3 | compaction summaries + re-reads they cause | 848 s (30 summaries, 28 s each) + 446 s (82 re-reads of files already read) | 26 | ADK summarises the history at 14,336 prompt tokens with one extra unbounded thinking call; the summary sees no tool output and no verbatim issue | MEASURED + ADK source |
| 4 | commands hung until the per-command timeout | 749 s | 4 (fastapi_14258 181, rich_3052 161, rich_3480 209, rich_4006 198) | infinite-loop repros; 180 s timeout (or the cap) ends them | MEASURED |
| 5 | malformed edit_file / write_file calls | 560 s (883 s on all 74) | 5 (rich_3718 226, fastapi_14616 153, fastapi_9753 148, rich_4075 20, fastapi_14258 13) | 84 of 228 edit/write calls (37 %) lose an argument; 0 of 852 run_command calls do | MEASURED + vLLM parser source |
| 6 | box slower than the L4 model | 1,612 s (38 s per task) | 42 | the pace proxy holds calls to the L4 time but cannot speed up a slower A6000 | MEASURED, box only |
| 7 | repeated identical calls | 941 s (22 s per task) | 26 | overlaps rows 5 and 3 | MEASURED |
| 8 | everything else: tools, prefill, harness | tools under 0.02 s per non-hung call (18 of 768 tool-seconds over 1,022 calls), prefill 14 s per task, harness gaps 0.2 s per task | 42 | search 2.6 s and targeted pytest 1.9 s in total over the 42 | MEASURED |

Top three findings by seconds that a bundle can recover:
1. **Malformed multi-argument edits (560 s on 5 of the 42, 883 s on 11 of 74).** The model sometimes closes a string argument
   with a backtick or a quote instead of Gemma 4's `<|"|>` delimiter; vLLM 0.19.1's gemma4 parser then reads the next argument
   name into the string and drops that argument (section 6). On rich_3718 the right fix (`title_text.stylize_before(border_style)`)
   was written at 85 s and resent 21 times until the cap. The single-string tool, run_command, had 0 malformed calls in 1,521.
2. **Hung commands (749 s on 4 of the 42).** In 15,090 recorded commands no command that finished took 60 s or more (the
   longest were `find /` at 58 s and a `curl` at 32 s, both on L4, both useless); every command at 60 s or more was a hang.
3. **Compaction (848 s + 446 s of re-reads on 26 of the 42).** Not removable from the bundle (the scorer sets the threshold and
   the summariser), but its damage is: the issue text can be kept out of the summarised history.

The largest bucket (decode, rows 1-2) is the model's own pace. Tool execution is not where the time goes, so faster search
tools or async tool execution cannot buy back time (section 11).

## 1. Method and checks

- **Clock.** Each trace step carries the epoch at which its model call returned (agent steps) and its tool returned
  (observation). The agent budget starts at the task_prompt step. Call k returns at E_k, its tools run E_k to O_k, the next call
  starts at O_k. The pace proxy (scripts/a6000/pace_proxy.py) logs every model call when it answers, after holding it to the
  modelled Kaggle-L4 time `0.102 + 0.02815 x completion + 0.000921 x uncached prompt` (scripts/golden/router.py).
- **Join.** Proxy rows are matched to traced calls on identical (prompt, completion) tokens within 3 s. An unmatched row that
  started inside the agent window and ended before the last traced call is a compaction summary; one after the last traced event
  is a call cut by the cap (or a post-run summary); one that started before the task began is the previous task's cut call
  (its reply arrives during the next task: the proxy does not cancel it, so the box GPU is shared for up to ~35 s; box only).
- **Split of model time.** decode / prefill / fixed from the L4 model; "box late" = A6000 latency above the L4 model.
  Thinking vs visible tokens: completion tokens split by the characters of the thought vs visible text + tool arguments of the same
  call (ESTIMATE: the proxy does not log the split).
- **Checks (section 1 of the report).** In every run, model + compaction + tools + harness gaps + tail equals the agent window
  within 3 s for 74 of 74 tasks. A tool still running at the cap has no observation in the trace; it is charged up to the cap
  (rich_3052 on p4_b1024: a `Prompt.ask` repro that loops on its mocked input, 161 s). Verification after the agent: median 2.2 s,
  longest non-hanging 6.9 s, 1-3 verification hangs per run (exit 124, the agent's patch did not fix an infinite loop).

## 2. Where the agent time goes (means per task; the full table is section 2 of the report)

| run | group | n | capped | agent s | model s | decode s | prefill s | box late s | think share (est) | compaction s (tasks) | tool s | tail s | model calls |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| p4_b1024 | the 42 | 42 | 30 | 280 | 228 | 173 | 14 | 38 | 75 % | 20 (26) | 18 | 13 | 24.9 |
| p4_b1024 | solved | 28 | 0 | 187 | 175 | 135 | 9 | 29 | 63 % | 7 (7) | 1 | 4 | 20.0 |
| p4_v0t2 | the 42 | 42 | 32 | 278 | 226 | 168 | 17 | 39 | 82 % | 17 (23) | 9 | 26 | 21.5 |
| p4_v0t2 | solved | 26 | 0 | 212 | 189 | 140 | 15 | 31 | 70 % | 18 (16) | 1 | 5 | 23.9 |
| p4_v7d (thinking off) | the 42 | 42 | 7 | 170 | 152 | 105 | 22 | 20 | 0 % | 4 (14) | 14 | 0 | 49.6 |
| p4 (v5h2, thinking off) | the 42 | 42 | 4 | 159 | 147 | 98 | 24 | 19 | 0 % | 4 (13) | 7 | 1 | 51.5 |

Reading: with thinking on, the 42 are a time problem in a way they were not with thinking off (30 vs 4-7 capped). A
thinking-on call costs 9.2 s (b1024) against ~3 s off; the thinking-off pipelines made twice the calls and still finished early,
but never solved these 42 either (they failed on fix quality, eval/diagnosis.md).

## 3. The 42 on p4_b1024, task by task

The table (agent s, calls, model s split, thinking estimate, compactions, cut calls, tool seconds by kind, gaps, tail, repeats,
re-reads after compaction, command timeouts) is section 3 of the report. Final state of every one of the 42 in all six box runs
(empty patch / gold file / wrong file, capped, compactions, hangs) is section 10. Two patterns stand out:
- **Capped with an empty patch, few long calls:** fastapi_14448, rich_3180, rich_3278, rich_3471, rich_3718, rich_3782, rich_3930,
  rich_3934, rich_3935, rich_3938, rich_3953 made 13-34 calls in 300 s. Their expensive calls are `python3 - <<EOF` experiment
  scripts and edits with ~1,000-1,300 output tokens (35-45 s each): thinking hits the 1,024 budget, then a long script follows.
  Most of them touched a gold file in the thinking-off runs (section 10 of the report).
- **Hung or malformed:** rich_3480, rich_4006 (two hung repros each, 6 calls in 300 s), fastapi_14258, rich_3052 (hung repro),
  rich_3718, fastapi_14616, fastapi_9753 (malformed-edit loops).

## 4. Model time by the tool each call emitted (p4_b1024)

| emitted tool | the 42: calls/task | s/task | s/call | solved: calls/task | s/task | s/call |
|---|---|---|---|---|---|---|
| run_command search | 9.0 | 66.0 | 7.3 | 4.9 | 33.9 | 6.9 |
| read_file | 8.4 | 49.7 | 5.9 | 4.5 | 23.7 | 5.2 |
| run_command python (repro/experiment) | 3.4 | 58.6 | 17.3 | 3.4 | 33.8 | 10.0 |
| edit_file | 1.8 | 25.8 | 14.6 | 3.0 | 45.0 | 15.0 |
| write_file | 0.8 | 11.4 | 13.6 | 1.0 | 15.8 | 16.3 |
| run_command targeted pytest | 0.2 | 4.1 | 24.7 | 0.0 | 0.7 | 3.8 |

The 42 spend 116 s per task locating (search + read) against 58 s on solved tasks, and their python experiments cost 17 s per
call against 10 s. Targeted pytest is almost never run (7 calls over 42 tasks, 5 over 28 solved): checks are ad-hoc python.

## 5. When the first source edit happens (p4_b1024)

- Solved (28): every task edits; first source edit at call 10 median (max 25), 114 s median (p75 157 s, max 273 s).
- The 42: **21 of 42 never edit a source file**; the 21 that do, first at call 16 median (max 41), 168 s median (p75 236 s).

Scratch files at the repo root (repro*.py), tests and /tmp do not count as source edits here.

## 6. Malformed tool calls (MEASURED), and why they happen (vLLM 0.19.1 source)

| run | malformed / calls | tasks |
|---|---|---|
| p4, p4_v7, p4_v7c, p4_v7d (thinking off; edits through run_command helpers) | 0; run_command 0 of 10,124 | 0 |
| p4_b1024 (temperature 1.0) | edit_file 63/166, write_file 21/62, run_command 0/852 | 11 |
| p4_v0t2 (temperature 0.2) | edit_file 16/129, write_file 1/121, run_command 0/669 | 5 |

Mechanism. A Gemma 4 call is `<|tool_call>call:edit_file{filepath:<|"|>...<|"|>,new_string:<|"|>...<|"|>,old_string:<|"|>...<|"|>}<tool_call|>`.
vLLM's parser (vllm/tool_parsers/gemma4_tool_parser.py at v0.19.1, the version in eval/kaggle/g4-l4-v12-p312/pip_freeze.txt,
`_parse_gemma4_args`) reads a string value from one `<|"|>` to the next. In all 101 malformed calls the model closed the first
code argument with a backtick or quote (`...stylize_before(border_style)` + "`,old_string:"), so the parser takes the next
argument's name into the string, turns the following code into junk keys, and the harness rejects the call ("mandatory input
parameters are not present: old_string"). The arguments are emitted in alphabetical schema order (content before filepath,
new_string before old_string), so the long code string always comes first and its slip always swallows a required argument.
The model then resends the same malformed call (rich_3718: 21 times). run_command has one string argument; nothing follows it to
swallow, and 0 of 1,521 thinking-on run_command calls (many of them long heredocs) were malformed.

## 7. Command durations (MEASURED, 15,090 run_command calls in 592 traces: six box runs + Kaggle L4 e74_v2/e74_v3)

| duration | finished | hit the timeout |
|---|---|---|
| < 5 s | 15,061 | 0 |
| 5-15 s | 8 | 0 |
| 15-30 s | 0 | 2 |
| 30-60 s | 2 (`find /` 58 s, `curl` 32 s, both L4) | 1 |
| 60-170 s | 0 | 1 |
| >= 170 s | 0 | 15 |

Apart from those two, the longest finished command was `pytest tests/` on rich at 7.5 s (L4). Gold-patch verification on Kaggle
L4 takes at most 12.6 s on the 74 valid public tasks (eval/kaggle/oracle_all/results.jsonl; the other 55 of the 129 fail even
with the gold patch there, and some of those runs take up to 77 s, all requests tasks); on the box, verification of a
non-hanging agent patch takes at most 6.9 s. research/harness_runtime.md sect. 7.4 notes that timeout_seconds is also the
verification timeout in the local harness (so on the box), and its item 10 says to keep it >= 60 s; whether Kaggle's Stage 2
metric reads it is UNVERIFIED (research/gap_5.md sect. 9).

## 8. Thinking volume (p4_b1024)

- The 42: 1,045 calls, completion tokens median 115, p90 606; 70 calls at >= 1,000 (the budget binds: 56 calls sit in the
  1,024-1,279 bucket). Tokens above 512 per call: 60,756 = 1,710 L4-seconds, 41 s per task: the most a 512 budget could return.
- Solved: 559 calls, median 115, p90 584; above 512: 877 s, 31 s per task.
- Malformed edits are not budget-truncated calls (0 of 84 had >= 1,000 completion tokens; their thoughts are shorter than
  successful edits': median 156 vs 271 characters).

## 9. Compaction (MEASURED; mechanism from google-adk 1.36.1 source)

- The 42: 26 of 42 tasks compacted, 30 summaries, 848 s (28 s each; summary completion median 743 tokens); 82 re-reads of a file
  already read before the summary, 446 s. Solved: 7 of 28 compacted, 192 s; 9 re-reads, 41 s.
- Mechanism: `google/adk/flows/llm_flows/compaction.py` runs before every model call; `apps/compaction.py:425-472` summarises once
  the last prompt reached `token_threshold` 14,336 (the scorer's value, HARNESS_README sect. 7.2), keeping the last 5 events;
  `apps/llm_event_summarizer.py:73-81` formats only `part.text` (thoughts and visible text), never function calls or responses,
  and sends the request with no generation config (thinking unbounded). The first user message (the issue) is among the
  compacted events, so after the first summary the model has only the summariser's paraphrase of the issue, and none of the file
  contents it read.
- Growth: read_file results are 69 % of all observation characters (whole-file reads median 4,239 chars, ranged reads 1,546);
  ~3.15 characters per token. Issue texts are short (median 469 characters, ~134 tokens; p90 1,891).

## 10. The starter contrast (p4_v0t2, v0-think: starter prompt, graph tools, code_analyzer agent tool, temperature 0.2, budget 4,096)

`python scripts/solve_overlap.py eval/a6000/results/{p4,p4_v7,p4_v7c,p4_v7d,p4_b1024,p4_v0t2} --focus p4_v0t2`: 26/74, unique
solves rich_3718, rich_3772, rich_3777; it missed 9 tasks that >= 2 other runs solved (fastapi_11194, 14873, 15589, 5077,
rich_3043, 3063, 3506, 3521, 4077), mostly capped with only repro files written. Same budget, same time profile on the 42
(278 agent s, 226 model s, 32 capped). What made its three unique solves:
- rich_3718: no malformed-edit loop (1 malformed call vs b1024's 21); the fix is a two-line title/subtitle change b1024 had
  already written. General: the edit path, not the starter's prompt.
- rich_3772, rich_3777: both runs edited the gold files; the starter's edits passed, b1024's did not (rich_3777's b1024 patch also
  touched rich/progress.py). INFERRED: fix-quality variance, not a mechanism; no general lever.
- Graph tools were barely used (23 search_similar_code, 8 get_code_neighbors, 5 code_analyzer calls over 74 tasks).
- Lower temperature cut malformed edits from 37 % to 7 % of edit/write calls but did not remove them; the lever below removes
  the mechanism at any temperature.

## 11. Speed levers this implies (to test; built ones are in LEVERS.md)

Built in submissions/v13 (Phase C, tests first; LEVERS.md):
1. **Edits through run_command only** (drop edit_file and write_file; the prompt gives one python heredoc pattern that replaces
   exact text, checks it occurs once, compiles the result before writing). Targets row 5. Expected flips: rich_3718 (fix already
   written), fastapi_14616 and fastapi_9753 (solved on L4 4 and 2 times; 153 s and 148 s lost to the loop).
2. **Per-command timeout 180 -> 60 s** (eval_config.yaml timeout_seconds; not the time budget). Targets row 4: each hang costs
   60 s instead of 180 s. Candidates: rich_3480, rich_4006, fastapi_14258, rich_3052.
(Both built, commits and offline evidence in LEVERS.md.)

Considered and not built (why):
- Issue text pinned in the instruction (`{problem_description}`, HARNESS_README sect. 5.1) so a compaction cannot reduce it to a
  paraphrase: no measured effect (the re-reads after a compaction are of files, not the issue), and +134 tokens per call (median,
  540 at p90) bring the compaction threshold earlier. A separate read.
- Thinking budget 512: up to 41 s per task back on the 42 (31 s on solved), but the long-thinking calls are where edits are
  designed; the 4,096 -> 1,024 step was neutral on 50 ids (19 vs 19). A separate single-variable read, not part of v13.
- Faster search tools (ripgrep) and async tool execution: tool time is under 0.02 s per non-hung call; search took 2.6 s in total over
  the 42 tasks. No trace ever ran `rg`, and whether the container has it is unverified; it would not matter.
- Parallel tool calls in one turn: the harness would run them, but the model emitted more than one call in 0 of 1,688 turns on
  p4_b1024 (7 of 6,167 in v7c/v7d); nothing measured says a prompt line would change that.
- Narrower reads to delay compaction: halving read sizes delays the threshold by a few calls but adds read calls at 5.9 s each;
  no measured net.
- Lower max_tool_calls (to bring the harness's budget warning earlier): solved tasks used up to 33 calls on the box and 40 on L4.
- Lower temperature: the forum ablation (746250) found 0.2 slightly below 0.4/1.0; lever 1 removes the malformed-edit
  mechanism without changing sampling.

Box caveat for the screen: the A6000 is 38 s per task slower than the L4 model on the 42 (row 6), and the previous task's cut
call can overlap the next task's first calls. On Kaggle the same bundle has more model time per task; time-bound flips are
under-counted on the box, not over-counted.

## 12. Cross-check with the cloud sessions' accounting (2026-10-14, after their fastapi batch landed)

The cloud fastapi write-ups (origin/forty-two-cloud-fastapi 3ea61103) measured the 15 fastapi/requests tasks of the 42 over all
six box runs (90 task-runs). Same population through scripts/forty_two/timing.py; every number in this section comes from
`python scripts/forty_two/timing_report.py --crosscheck` (about 10 s):

| quantity (fastapi 15 x 6 runs) | cloud | here | why they differ |
|---|---|---|---|
| total seconds | 17,057 | 17,057 (sum of row `secs`); agent windows 16,705 | same rows; `secs` adds setup, verification and hung-verification tails |
| model share / tool share | 89 % / 4.4 % | 86.6 % / 4.8 % of the agent windows | denominators (row secs vs agent windows); compaction counted separately here (4.5 %) |
| single model calls of 30 s or more | 3,230 s | 3,497 s (65 calls) by trace interval; 2,798 s (51 calls) by the proxy's own call duration | the trace interval also holds a compaction summary or box lateness when one precedes the call |
| identical calls | 2,407 s, 1,188 repeats (identical reply too) | 2,479 s, 1,209 repeats (any earlier identical call) | definition |
| compaction summaries | 751 s | 751 s | none |
| hung repro on fastapi_14258 | ~180 s x 3 | 181 s (b1024), 180 s (v0t2), 180 s + 84 s (v7d) | none |

No disagreement on substance. Two things the cross-check adds to sections 0-11:
- **Long single calls are a bucket of their own.** On p4_b1024 the 42 spend 3,421 s of 11,761 agent seconds (29 %) in model
  calls of 30 s or more (fastapi 1,017 s, rich 2,404 s); over all six runs, 9,201 s on the 42. They are calls whose thinking reaches
  the budget and are then followed by a long script or edit. A 512 thinking budget would remove an estimated 27 s per task on the 42
  (thinking tokens above 512 per call, char-share estimate; 15 s on solved tasks), less than the 41 s upper bound of section 8,
  which also counted visible output. Still not built into v13 (LEVERS.md, "considered"): it is the obvious next single-variable read.
- **Identical-call loops:** over the six runs, 7,486 s on the 42 (fastapi 2,479, rich 5,007), mostly in the thinking-off
  pipelines. On p4_b1024 the largest loop class is the malformed edit resend (rich_3718 21x, fastapi_14616 14x), which lever 1
  removes; the rest (identical greps, re-reads after compaction) has no structural fix in a declarative bundle.
- **Test files that cannot import (cloud finding 2: 295 of 564 fastapi test files import inline_snapshot or dirty_equals).** On
  p4_b1024 the agent ran pytest 7 times on the 42 and 5 times on solved tasks (3 import errors, 1 of them a snapshot/dirty_equals
  import); it checks with its own python repros instead (3.4 per task). Steering it toward self-written repros would change little
  on this line; not built.
