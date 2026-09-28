# v10 design B: VERIFY-AND-RETRY

Architect B, 2026-09-28. Angle: a mechanical gate (hygiene + compile/import + repro-must-flip + regression/collection +
hang) decides; a fresh-context second fixer runs only when the gate fails and time remains, **in a private copy of the
repository**, and replaces the first attempt only if it scores strictly better; the sibling sweep and the
runtime-ground-truth rules ride inside the fixer's check loop. Every construct is one `research/config_space.md`
compiled and ran: SequentialAgent root (case 03), LlmAgents with `include_contents: none` + `output_key` (case 20),
`skills` shared by several agents (case 56), `!include` of `.md` (case 96), inline `generate_content_config` (case 60,
R1d). No ParallelAgent, LoopAgent or AgentTool.

**Revision note.** This file replaces an earlier design-B draft written by a previous run of this workflow. I read that
draft fully and re-derived everything against the reports and the installed harness source. Main changes:
(1) the retry edits a git worktree under `$TMPDIR`, never `/workspace`, so a cap hit during the retry can no longer
leave a half-done second attempt as the graded patch; (2) green-checkpoint restore at the judge (literature T3);
(3) retry window and deadline (175 s / 255 s) now come from a counterfactual L4 replay of all six race-1 arms
(`docs/v10/design_B_replay.py`, section 7), and the time claim is stated with the command that produced it;
(4) restart convergence through `{final_note?}` instead of asking early stages to call a tool they do not have;
(5) new defects found and given regression tests: helpers are shadowed by stdlib-named repo modules on `PYTHONPATH`,
and heredoc text is path-rewritten by the sandbox; (6) setup-stage crash guards now include `run_command`.

Sources read: `research/harness_runtime.md` (all), `config_space.md` (all), `own_data.md` (all), `time_model.md` (all),
`task_catalog.md` (all), `test_plan.md` (0-5), `literature.md` (6, 2.11-2.16), `competitors.md` (0-2), `forum.md` (1),
the `submissions/v9_eog` bundle, `helpers_v9/*`, and the installed harness source cited below
(`SP = .venv/lib/python3.12/site-packages`).

---

## 0. One screen

| Question | Answer |
|---|---|
| Agent tree | `Sequential[setup, locator, fixer, judge, retry_fixer, finalizer]`, six LlmAgents, all `include_contents: none` |
| What makes the retry conditional | The judge calls `submit_patch` + a text reply on `DECISION: SUBMIT`, which ends the task (`agent_runner.py:569-579`); `retry_fixer` and `finalizer` only run when the judge replies without submitting (`DECISION: RETRY`) |
| Who decides | `gate.py` (stdlib): hygiene, compile + import, repro original-vs-current, related existing tests original-vs-current, hang, siblings, a score tuple, the task clock. The model copies the last line |
| Where repair happens | Attempt 1: the fixer's own `check.py` loop (at most 3 checks before a retry-eligible stop). Attempt 2: `retry_fixer`, fresh context, failure report first, private worktree |
| Cap safety | After the judge, `/workspace` always holds the best-scored candidate: retry edits go to `$TMPDIR/swe/shadow` and are promoted only when strictly better. A timeout at any point grades the best candidate |
| Helper availability | One-call `setup` stage (temperature 0), `skills` on every working stage with a literal recovery call, and every helper self-installs when run through `run_skill_script` |
| Edit channel | `edit_file` declared nowhere. `show.py` prints numbered lines; `replace.py` replaces a line range from a heredoc with syntax gate, auto-fixes, stale-number guard, loop breaker, protected-path refusal, sandbox path un-rewrite |
| eval_config | `timeout_seconds 90`, `max_tool_calls 120`, `max_time_minutes 5`, `max_turns 220` |
| Time | Cap-saturated hidden set (the measured case: v4 ~308 s/task): v10 wall per task = v4's (same 300 s cap, same overshoot bound), 10.49 h for 120 tasks. Public-like tasks, counterfactual L4 replay: **0.98 x v4** on the v9_eog base (0.86-1.03 over six bases), pessimistic 1.06 (0.92-1.09). Hidden-like (every stage x2): 0.86-0.88 x v4 |
| Expected gain | Public 28/74 (v9_eog) -> **33/74 central** (29-37). Hidden LB 0.12 -> **0.15-0.17 central** (0.12-0.21). The retry itself is worth about +1 public task and +0.3 hidden; most of the gain is the verify loop and the mechanics. **0.30 is not reachable with this design alone** |

---

## 1. Facts that bind the design

| # | Fact (source) | Consequence in this design |
|---|---|---|
| 1 | Kaggle compacts in-flow when the last prompt >= 14,336 tokens; an `include_contents: none` stage is wiped to its instruction plus a text-only summary (harness_runtime 5.4). Pod races never compact | Every stage is planned to stay < 12k tokens: bounded helper output (5.2), short handoffs, `{problem_description}`/`{plan?}` re-rendered every call, all progress on disk (`state.json`, candidate diffs) and re-materialised by `check.py`/`gate.py --mode report` |
| 2 | Any exception other than timeout/turn-limit discards the patch, submitted or not; overflow at prompt >= 32,768 - max_output_tokens; runaway replies cost ~117 s at 4,096 tokens (harness_runtime 1, time_model 3) | `max_output_tokens` 256-2,048 per stage (overflow line 30,720); brace lint; no prompt names an undeclared tool; crash-guard declarations for every tool the harness prompt advertises to stage 1 |
| 3 | `/tmp` is rewritten in command text only; `TMPDIR=HOME=<sandbox>/tmp`; install was skipped in ~40 % of race-1 tasks (harness_runtime 2.3-2.4, time_model 7.1) | Dedicated setup stage; helpers self-install through `run_skill_script`; recovery rule in every working prompt; all paths from `TMPDIR`/`tempfile.gettempdir()`; install also writes `/tmp/swe` when not on the rewriting backend (the scorer is Docker, forum 742882) |
| 4 | `edit_file` args corrupted 18-22 %, 39-52 % of calls missing `old_string`; results double-JSON-encoded; `run_command` keeps the first 5,000 chars; the verification test-file reset is a no-op; repo not installed in the subprocess backend (harness_runtime 3, 7.2) | Line-range edits via heredoc (`replace.py`), auto-unescape; helpers print <= 3,500 chars and exit 0; hygiene reverts test/config edits at every check, gate and final; import-path self-check; `PYTHONPATH=<root>[:<root>/src]` for our own runs |
| 5 | A Sequential stage ends on its first text-only reply; a nudge restarts the root from stage 1; the first `submit_patch` + text ends the task; budgets are per task (harness_runtime 5-6, config_space 11) | The judge's submit is the conditional exit; only judge and finalizer hold `submit_patch`; restart convergence via `{final_note?}` and the `FINAL:` banner |
| 6 | Hidden tasks ~1.9x public; v4 ~308 s/task, essentially all at the 5-min cap; decode is 90-97 % of agent time; ~0.085 s/call + 28.5 ms/output token + 0.65 ms/uncached prompt token on L4 (own_data 2, time_model 2) | `max_time_minutes 5` unchanged; stage clock rules and a bounded retry window; reply caps; tool output is cheap prefill, model output is expensive decode, so handoffs are pointers and `show.py` re-materialises code |
| 7 | "Right file, wrong or partial fix" is 19 of 30 v9_eog losses; ~15-19 of 74 tasks are out of reach; every capped/overflowed public run scored 0; +-3 tasks run-to-run (own_data 0) | Repro-must-flip and siblings inside the fixer loop; never-empty rule; green checkpoint; cap-safe tree |
| 8 | Lever ranking (task_catalog 4) | All ten top levers are mechanised here: see the mapping in section 8 |
| 9 | Parallel candidates: shared budgets, event-loop-blocking tools, unmeasured KV (time_model 4) | Not used; the retry is the serial alternative (literature T7) |
| 10 | Carson's rules | Every v9 helper bug found gets a regression test (R-B19-R-B25, R-B36, R-B51-R-B54); stdlib only; perf budgets asserted; `validate.py`, `linux_test.sh`, real-sandbox tests; no pods, Kaggle pushes or spend in implementation |

**Defects in the shipped v9 helpers found while reading them** (each has a regression test in section 10):
`replace.py:28` (`cfile="/tmp/_pyc_replace"`) and `check.py:7` (`BEST="/tmp/_swe_best.diff"`) use literal host `/tmp`;
`locate.py:9` reads the inherited stdin when called without a query (blocks until the command timeout on an open pipe);
`gate.py` diffs and archives against `HEAD` (after an agent commit the "original" includes the agent's change; test_plan
F5), reports PASS when no test ran (F3), and treats any file under `tests/` as a test (`tests/render.py`, 11/40);
`run.py` kills only the shell on timeout (grandchildren survive, F7); `replace.py` rewrites CRLF files whole, shifts
numbering on `\x0c`/`\x85`/` `, crashes on latin-1 and edits test files (F6); `_ws.ws()` prefers a host `/workspace`
over `PWD`. New in this review: every helper imports stdlib modules after `PYTHONPATH=<workspace>` entries, so a repo
with a root-level `json.py`/`ast.py`/`types.py` shadows them; heredoc text passed to `replace.py` has `/tmp`,
`/workspace`, `/usr/local/bin` rewritten to sandbox paths before the helper sees it (harness_runtime 2.3), so new code
containing those literals would be written with absolute sandbox paths.

---

## 2. Agent tree and YAML (exact)

```
submissions/v10/
  agent.yaml
  eval_config.yaml
  sub_agents/{setup,locator,fixer,judge,retry_fixer,finalizer}.yaml
  prompts/{setup,locator,fixer,judge,retry_fixer,finalizer}.md
  skills/swe-tools/SKILL.md
  skills/swe-tools/scripts/{_ws,install,locate,show,replace,repro,probe,run,gate,check}.py
```

`agent.yaml`
```yaml
name: swe_pipeline
agent_class: SequentialAgent
description: Install helpers, locate, fix with checks, gate, private second attempt only on a failed gate, finalize.
sub_agents:
  - config_path: sub_agents/setup.yaml
  - config_path: sub_agents/locator.yaml
  - config_path: sub_agents/fixer.yaml
  - config_path: sub_agents/judge.yaml
  - config_path: sub_agents/retry_fixer.yaml
  - config_path: sub_agents/finalizer.yaml
```

`eval_config.yaml`
```yaml
evaluation:
  timeout_seconds: 90
  max_tool_calls: 120
  max_time_minutes: 5
  max_turns: 220
```

`sub_agents/setup.yaml`
```yaml
name: setup
model: gemma-4-31b-it-qat-w4a16-ct
description: Installs the helper scripts. Does nothing else.
include_contents: none
instruction: !include ../prompts/setup.md
tools: [run_command, read_file, get_code_neighbors, search_similar_code, get_code_subgraph]
skills: [skills/swe-tools]
generate_content_config:
  temperature: 0.0
  top_p: 1.0
  top_k: 1
  max_output_tokens: 256
  thinking_config:
    include_thoughts: false
```
Setup is the only stage that sees the harness prompt, which names `read_file` ("File view limit ... per read_file call")
and, when graph files exist, the three graph tools (`agent_runner.py:92-101, 163-171`). An undeclared call discards the
task (harness_runtime 1), so those are declared as crash guards; `run_command` too, because it is the tool the model
reaches for first (the v9 locator's first call was `run_command` in 20/24 skipped installs, test_plan F2). The prompt
forbids all of them. `submit_patch` is named by the harness prompt only as "after your implementation is complete";
declaring it would let a confused setup submit an empty diff, which loses the task exactly like the crash would, so it is
not declared.

`sub_agents/locator.yaml`
```yaml
name: locator
model: gemma-4-31b-it-qat-w4a16-ct
description: Finds the code that must change and writes a reproduction script. Never edits the repository.
include_contents: none
instruction: !include ../prompts/locator.md
tools: [run_command, read_file]
skills: [skills/swe-tools]
output_key: plan
generate_content_config:
  temperature: 1.0
  top_p: 0.95
  top_k: 64
  max_output_tokens: 1536
  thinking_config:
    include_thoughts: false
```

`sub_agents/fixer.yaml`
```yaml
name: fixer
model: gemma-4-31b-it-qat-w4a16-ct
description: Implements the change and checks it.
include_contents: none
instruction: !include ../prompts/fixer.md
tools: [run_command, read_file, write_file]
skills: [skills/swe-tools]
output_key: fix_notes
generate_content_config:
  temperature: 1.0
  top_p: 0.95
  top_k: 64
  max_output_tokens: 2048
  thinking_config:
    include_thoughts: false
```

`sub_agents/judge.yaml`
```yaml
name: judge
model: gemma-4-31b-it-qat-w4a16-ct
description: Runs the gate and submits when it passes.
include_contents: none
instruction: !include ../prompts/judge.md
tools: [run_command, read_file, submit_patch]
output_key: verdict
generate_content_config:
  temperature: 0.0
  top_p: 1.0
  top_k: 1
  max_output_tokens: 256
  thinking_config:
    include_thoughts: false
```

`sub_agents/retry_fixer.yaml`
```yaml
name: retry_fixer
model: gemma-4-31b-it-qat-w4a16-ct
description: Second attempt in a private copy after a failed gate.
include_contents: none
instruction: !include ../prompts/retry_fixer.md
tools: [run_command, read_file, write_file]
skills: [skills/swe-tools]
generate_content_config:
  temperature: 1.0
  top_p: 0.95
  top_k: 64
  max_output_tokens: 2048
  thinking_config:
    include_thoughts: false
```
`write_file` and `read_file` stay declared on the retry stage only as crash guards (both are natural tool names); both
act on `/workspace`, not the private copy, and the prompt says so. Anything they change in `/workspace` is discarded by
`gate.py --mode final`, which restores the best candidate byte-exactly (5.4 step 11).

`sub_agents/finalizer.yaml`
```yaml
name: finalizer
model: gemma-4-31b-it-qat-w4a16-ct
description: Keeps the better attempt and submits.
include_contents: none
instruction: !include ../prompts/finalizer.md
tools: [run_command, read_file, submit_patch]
output_key: final_note
generate_content_config:
  temperature: 0.0
  top_p: 1.0
  top_k: 1
  max_output_tokens: 256
  thinking_config:
    include_thoughts: false
```

`skills/swe-tools/SKILL.md`
```
---
name: swe-tools
description: Repository helpers for locating, viewing, editing by line range, reproducing, checking and gating a fix. Install with run_skill_script(skill_name="swe-tools", file_path="install.py"), then run them with run_command as python3 /tmp/swe/<name>.py.
---
# swe-tools
Each helper prints its usage when called without arguments. Every helper also runs directly as a skill script,
for example run_skill_script(skill_name="swe-tools", file_path="show.py", args={"spec": "pkg/mod.py:10-40"}),
and installs the others when it does.
```

Construct provenance (config_space 12): Sequential root with six children (03, 14), `include_contents: none` +
`output_key` (20), one skill dir on four agents (56), `!include` `.md` (96), inline gen config with `temperature 0.0`
(schema `>= 0`, 66), `top_k 1` (schema `>= 1`), `include_thoughts: false` -> `enable_thinking: false` (R1d), no `seed`
(dead, finding 1), no `thinking_level` (finding 2). Nothing else.

---

## 3. Control flow

```
setup        run_skill_script(install.py)                          -> "ready"
locator      locate -> show -> (probe) -> repro                     -> plan: FILES/CAUSE/CHANGE/TEST/REPRO (<=120 words)
fixer        show -> replace* -> check -> repair* (<=3 checks)      -> fix_notes (<=60 words)
judge        gate.py  (restores the best checkpoint, then decides)
               DECISION: SUBMIT -> submit_patch + text               -> TASK ENDS
               DECISION: RETRY  -> text "RETRY: ..." ; shadow = baseline + attempt-1 diff; active_root = shadow
retry_fixer  gate --mode report -> [redo] -> show -> replace* -> check (promotes when strictly better)
finalizer    gate --mode final (last evaluation, promotion, exact restore of the best, hygiene) -> submit_patch + text -> TASK ENDS
```

End states and what is graded:

| Situation | Path | Graded diff |
|---|---|---|
| Judge PASS | submit + text | best attempt-1 checkpoint (usually the current tree), hygienic |
| Judge FAIL, clock <= 175 s | RETRY -> retry_fixer -> finalizer submits | strictly better of attempt 1 / attempt 2; tie keeps attempt 1 |
| Judge FAIL, clock > 175 s | judge submits | best attempt-1 checkpoint |
| Judge EMPTY (no source change) | RETRY while clock <= 235 s | attempt 2 if it produced any compilable change |
| Cap during locator/fixer | harness `TimeoutError` -> fallback `git diff` of `/workspace` (`agent_runner.py:741-776`) | attempt 1 as it stands; the last `check.py` already reverted test/config edits |
| Cap during retry_fixer or finalizer | same | best candidate (attempt 1, or attempt 2 if already promoted); never a half-done attempt 2 |
| Finalizer replies without submitting | nudge -> root restarts at setup (`runners.py:1082-1156`) | locator/fixer/retry see `{final_note?}` non-empty and reply `done` without tools; `gate.py` in judge mode sees `final_done` and says SUBMIT; ~5 LLM calls, ~12 s |
| Helpers never installed anywhere | judge prompt: no DECISION line -> submit | `/workspace` as the fixer left it |

Why a Sequential root and not an LlmAgent coordinator: a coordinator needs a model-driven `transfer_to_agent` at every hop
(a new failure mode per stage) and accumulates context. The two Sequential hazards are covered: every path ends with
submit + text (so the post-invocation compaction crash, config_space finding 4, cannot fire; it also needs the last
prompt >= 14,336 and the finalizer's is < 4k), and a nudge restart converges (table above).

Why not `LoopAgent[fixer, judge]`: no early exit except `max_iterations` (finding 9), the fixer keeps its own history
across iterations (R4), so the second pass is not fresh, and the second pass needs a different instruction
(failure report first, REPAIR/REDO/keep decision, deadline).

---

## 4. Prompts (full text)

Placeholders allowed: `{problem_description}`, `{plan?}`, `{fix_notes?}`, `{verdict?}`, `{final_note?}`. No other braces
(lint R-B11). No prompt names a tool its stage does not declare (R-B12). Sizes are without the problem statement.

### 4.1 `prompts/setup.md` (461 chars)
```
You are the SETUP step of an automated team. Your only job is to install the helper scripts the later steps use. Do not work on the issue: later steps do that.

Call exactly this tool now, with exactly these arguments:
run_skill_script(skill_name="swe-tools", file_path="install.py")

When the result says "installed", reply with the single word: ready
If the result is an error, call it once more exactly as shown, then reply: ready
Do not call any other tool.
```

### 4.2 `prompts/locator.md` (2,863 chars)
```
You are the LOCATOR in a team fixing an issue in the Python repository in /workspace. You find the code that must change and write a reproduction script. You never edit repository files; the next step does that.

Earlier pass: {final_note?}
(If the line above is not empty, the work is finished: call no tool and reply with the word done.)

Issue:
{problem_description}

Helpers (run each with run_command; every helper prints a [clock] line first):
- python3 /tmp/swe/locate.py "<names, error text and key words from the issue>"   ranks files and functions with line ranges and names related test files
- python3 /tmp/swe/show.py <path:START-END | path::Class.method | package.module.Name> ...   prints code WITH line numbers; dotted names also work for installed libraries
- python3 /tmp/swe/probe.py <<'EOF'   then Python lines, then a line EOF: runs a scratch snippet (20 s limit)
- python3 /tmp/swe/repro.py <<'EOF'   then the reproduction script, then EOF: saves it and runs it on the original code
- python3 /tmp/swe/run.py "<shell command>"   anything else, for example git grep -n name (20 s limit, bounded output)
If a helper prints "can't open file", call run_skill_script(skill_name="swe-tools", file_path="install.py") once, then repeat the command.

Steps (about 8 tool calls; never repeat a call):
1. locate.py with the names, error text and key words of the issue. If the issue is only a title (maybe with a link), split the title into code words (for example "proxy isatty" gives FileProxy and isatty) and search those; never search for the issue number.
2. show.py the best candidates and the code that calls them. A name used but not defined in the repository comes from an installed library: show.py package.module.Name prints its real source. Before relying on how a library stores a value, print the real object with probe.py (type, repr, attributes) instead of guessing.
3. repro.py: a short script that uses the public API the way the issue describes and ends with assert statements on the behaviour the issue asks for. Assert only what the issue states; never invent exact messages or names. It must FAIL on the current code. If repro.py says DOES NOT REPRODUCE, try one other input shape (other argument types, empty versus None, wrapped versus plain function, both argument orders); if it still passes, go on without a reproduction. Skip this step when the issue gives nothing you can turn into a few lines of code.
When a helper line starts with TIME (locator), stop and reply.

Then stop calling tools and reply with this plan, under 120 words, plain text:
FILES: path:START-END of every place that must change, including other places with the same code
CAUSE: one sentence
CHANGE: what to add or modify, with the exact names, parameters and messages the issue gives
TEST: one existing test file for this code
REPRO: reproduces | none
```

### 4.3 `prompts/fixer.md` (2,758 chars)
```
You are the FIXER in a team working in /workspace. Implement the change now. The current code IS wrong: never conclude that nothing needs changing, and never finish without a source change.

Earlier pass: {final_note?}
(If the line above is not empty, the work is finished: call no tool and reply with the word done.)

Issue:
{problem_description}

Locator's plan:
{plan?}

Helpers (run each with run_command; every helper prints a [clock] line first):
- python3 /tmp/swe/show.py <path:START-END | path::Class.method | package.module.Name> ...   code with line numbers
- python3 /tmp/swe/replace.py --file <path> --start <N> --end <M> <<'EOF'
<the new lines: plain Python with its real indentation, no escaping, no line numbers>
EOF
  replaces lines N to M (numbers from your latest show.py). --after N inserts after line N instead; --create makes a new file. It checks the syntax, undoes a broken edit and prints the new lines. When you edit several places in one file, edit the lowest one first.
- python3 /tmp/swe/check.py   checks your change: compiles and imports it, runs the reproduction and the related existing tests on the original code and on yours, lists SIBLINGS (other places with the same code), and undoes any edit to test files. Add --target <test file> to include the plan's TEST file.
- python3 /tmp/swe/repro.py <<'EOF' ... EOF   saves a reproduction if the plan has none; python3 /tmp/swe/probe.py <<'EOF' ... EOF for scratch Python; python3 /tmp/swe/run.py "<command>" for anything else.
If a helper prints "can't open file", call run_skill_script(skill_name="swe-tools", file_path="install.py") once, then repeat the command.

Steps:
1. show.py the FILES of the plan (several specs in one call).
2. Make the smallest complete change with replace.py. Use exactly the names, parameters and messages the issue gives; copy the style of the neighbouring code for new checks and messages; keep the behaviour for every other input.
3. Run check.py and act on what it prints:
   REPRO still failing: your change is wrong or incomplete; compare the actual and expected values.
   REGRESSIONS: you broke an existing test, unless the issue explicitly asks for exactly that change of behaviour.
   SIBLINGS: other places with the same code; apply the same fix wherever the same defect applies.
   Run check.py again after each change. Never repeat an identical command.
4. When check.py says STATUS: ok, or tells you to stop, or a TIME line says so, stop calling tools and reply in under 60 words: the files and functions you changed and check.py's last STATUS line.
Rules: never edit test files, conftest.py, pytest.ini, pyproject.toml, setup.cfg or tox.ini. Use write_file only to create a NEW source file. Never put scratch files in /workspace.
```

### 4.4 `prompts/judge.md` (505 chars)
```
You are the JUDGE. A fix has been applied in /workspace. You never edit code.

1. Call run_command with: python3 /tmp/swe/gate.py
2. Read the LAST line of its output and do exactly this:
   - "DECISION: SUBMIT": call submit_patch, then reply with one short sentence.
   - "DECISION: RETRY": do NOT call submit_patch. Reply with only the line that starts with "RETRY:", copied exactly.
If the output has no DECISION line (for example "can't open file"), call submit_patch and reply with one short sentence.
```

### 4.5 `prompts/retry_fixer.md` (2,562 chars)
```
You are the SECOND FIXER. A first attempt was made and the automatic check found a problem. You work in a private copy of the repository: the first attempt stays safe, and yours replaces it only if it checks out better.

Earlier pass: {final_note?}
(If the line above is not empty, the work is finished: call no tool and reply with the word done.)

Issue:
{problem_description}

Plan:
{plan?}

First fixer's notes:
{fix_notes?}

Check result:
{verdict?}

Helpers (run each with run_command; they all work on your private copy, with the same paths as in /workspace):
- python3 /tmp/swe/gate.py --mode report   what failed (tests with their assertion lines, the reproduction output), the current diff and your deadline. Run it FIRST.
- python3 /tmp/swe/gate.py --mode redo   resets your copy to the original code, to start a different approach.
- python3 /tmp/swe/show.py <path:START-END | path::Class.method | package.module.Name> ...   code with line numbers
- python3 /tmp/swe/replace.py --file <path> --start <N> --end <M> <<'EOF'
<the new lines: plain Python with its real indentation, no escaping, no line numbers>
EOF
  --after N inserts after line N; --create makes a new file. Edit the lowest place in a file first.
- python3 /tmp/swe/check.py   checks your copy; it says PROMOTED when your version becomes the submission.
- python3 /tmp/swe/probe.py <<'EOF' ... EOF and python3 /tmp/swe/run.py "<command>" as usual.
If a helper prints "can't open file", call run_skill_script(skill_name="swe-tools", file_path="install.py") once, then repeat the command.

Steps:
1. gate.py --mode report. If it says NOTHING TO DO, reply done.
2. Decide once:
   REPAIR the current change when the report shows a clear cause: a broken existing test, a missed SIBLING, an error, a reproduction failing for a visible reason.
   REDO (gate.py --mode redo, then a different change) when the reproduction output did not change at all, or the diff is empty (then implement the plan's CHANGE directly).
   If the failing tests assert the OLD behaviour that the issue explicitly asks to change, or the reproduction asserts something the issue does not state, the first attempt may be right: reply keep.
3. Edit with replace.py and run check.py; at most two rounds.
4. Stop at the deadline the report gives or when a TIME line says so, and reply in under 40 words.
Rules: read code with show.py (read_file shows the first attempt, not your copy). Create new files only with replace.py --create. Never edit test files, conftest.py, pytest.ini, pyproject.toml, setup.cfg or tox.ini.
```

### 4.6 `prompts/finalizer.md` (215 chars)
```
You are the FINALIZER. You never edit code.
1. Call run_command with: python3 /tmp/swe/gate.py --mode final
2. Call submit_patch. Always, whatever step 1 printed, even if it failed.
3. Reply with one short sentence.
```

Prefix size check (R-B09, sizes measured on the texts above with a brace/tool-name lint that passes): with the largest
public statement (10,095 chars) the fixer/retry instruction is ~13.5-13.9k chars ~4.2k tokens; plus declarations (run_command + read_file + write_file ~1,300 chars; skill toolset 2,083 + 1,333 chars)
the fixed prefix is ~5.5k tokens worst case (the R-B09 limit), ~2.5k typical (median statement 469 chars), leaving
>= 8.8k tokens of room below 14,336.

---

## 5. Helpers

All in `submissions/v10/skills/swe-tools/scripts/` (these files ARE the helper sources; `helpers_v9/` stays frozen).
Stdlib only, Python 3.9 syntax. Shared contract for every helper:

1. **Bootstrap** (`_ws.boot(name)`, first statement): insert its own dir at `sys.path[0]`, then **remove from
   `sys.path` every entry that is the workspace, the shadow, or came from `PYTHONPATH`** (helpers never import repo code
   in-process; repo imports happen only in subprocesses). If its own dir is not `SWE`, copy all sibling `.py` files to
   `SWE` (and to `/tmp/swe` when not on the rewriting backend, see 5.1) atomically (`.tmp` + `os.replace`), only when
   missing or `_ws.VERSION` differs.
2. **Arguments**: `--key value` pairs (a `run_skill_script` dict becomes exactly that, `skill_toolset.py:640-652`), a bare
   `--` is ignored, documented positionals accepted; no bare boolean flags required (`--create 1` and `--create` both work).
3. **Output**: first line `[clock Ns] <STATUS>` plus phase banners (5.3), then a bounded body; full text to
   `SWE/last.log`; cut marker `[... N chars cut; full output: /tmp/swe/last.log]` (the `/tmp` here is display text).
   Exit 0 on every path; an unexpected exception prints `HELPER ERROR <name>: <Type>: <msg>` (<= 300 chars), exit 0.
   (A non-zero exit makes `run_command` duplicate the text as `error_message` + `details`, harness_runtime 3.2.)
4. **stdin**: read only by `replace/repro/probe` (and `locate --stdin`), guarded by `select([stdin], [], [], 2.0)`; no data
   in 2 s or immediate EOF -> `ERROR: no text on stdin. Use <<'EOF' ... EOF` (the harness stdin is inherited, 2.4).
5. **Children**: `stdin=DEVNULL`, `start_new_session=True`, `os.killpg(pgid, SIGKILL)` on timeout, partial output kept.
6. **Paths**: no string constant `/tmp` except `_ws.FALLBACK_TMP`; scratch/state under `SWE`; lazy imports so start-up
   (import + clock line) <= 80 ms.
7. **Repeat detection**: key = sha1(helper, argv, stdin); the 3rd identical call with an unchanged diff is prefixed
   `REPEAT x3: same command, the tree has not changed, the result is the same.` (32-44 % of race-1 calls were exact
   repeats, own_data 4.4).

### 5.1 `_ws.py` (library, not called directly)

```
VERSION = "v10.0"
SWE = os.path.join(os.environ.get("TMPDIR") or tempfile.gettempdir(), "swe");  FALLBACK_TMP = "/tmp"
REWRITING = "swegemma_sandbox_" in SWE          # subprocess backend: /tmp in command text is rewritten to <root>/tmp
SANDBOX_ROOT = dirname(TMPDIR) if REWRITING else None
ws()      SWE_WS env -> walk up from $PWD -> walk up from cwd -> state["ws"] -> "/workspace"; first dir holding .git
          that is not under SWE; cached in state. (PWD survives the skill wrapper's chdir, harness_runtime 2.4.)
root()    state["active_root"] if phase == "retry" and that dir exists, else ws().
clock()   now - t0. t0 = mtime(.git/refs/tags/_swegemma_baseline) (written by setup_baseline_commit,
          container_setup.py:575-582, just before the agent timer starts, agent_runner.py:300-495) -> committer time of
          _swegemma_baseline (packed refs) -> state.installed_at - 10 s. SWE_FAKE_CLOCK overrides (tests).
          Over-estimates the harness timer by ~1-3 s: conservative.
T = dict(LOCATE_SOFT=75, FIX_EMPTY_WARN=150, FIX_STOP_FOR_RETRY=165, FIX_SOFT=200, FIX_HARD=250,
         RETRY_LATEST_START=175, RETRY_EMPTY_LATEST=235, RETRY_BUDGET=70, RETRY_HARD=255,
         QUICK_AT=270, FINAL_BY=285, CAP=300)
state_load() / state_update(fn)   SWE/state.json under fcntl.flock(SWE/state.lock); atomic replace.
run(argv|cmd, timeout, cwd, env, log)   -> (rc, out, timed_out); contract 5.
git(args, cwd, timeout=10)
BASE_TAG = "_swegemma_baseline"
diff(tree)       `git -C tree add -N . ; git -C tree diff --binary _swegemma_baseline` (HEAD only if the tag is missing)
src_changed(d)   non-protected paths in the diff
PROTECTED        (^|/)(tests?)/ | (^|/)test_[^/]*\.py$ | _test\.py$ | (^|/)conftest\.py$ |
                 ^(pytest\.ini|\.pytest\.ini|tox\.ini|setup\.cfg|pyproject\.toml)$ | \.pth$
worktree(path, diff=None)   `git -c core.hooksPath=/dev/null worktree add --detach <path> _swegemma_baseline`
                 (removing a stale one first), then copy files that are git-ignored but present in ws (<= 2,000
                 files, <= 50 MB, skipping .git, __pycache__, .pytest_cache, .adk_exec_*), then `git apply --binary diff`.
restore(tree, diff_path)    make tree's diff equal a candidate: save the current diff, `git checkout _swegemma_baseline --`
                 the tracked changed paths, delete untracked changed paths, `git apply --binary`, verify the diff
                 sha; on any failure re-apply the saved diff and report RESTORE FAILED. Refused when clock >= FINAL_BY.
cap(text, n, head_frac=0.45) -> head + marker + tail
```

### 5.2 CLI, contract, caps, timeouts, budgets

`run_command` form shown; the skill form is `run_skill_script(skill_name="swe-tools", file_path="<h>.py", args={...})`.

| helper | CLI | Contract | Output cap | Internal timeout | Perf budget |
|---|---|---|---|---|---|
| `install.py` | `run_skill_script(... "install.py")`; also `python3 /tmp/swe/install.py` | Copies every helper to `SWE` (+ `/tmp/swe` when `not REWRITING` and `/tmp` is writable and differs); never overwrites an existing `state.json`; records `installed_at`, `ws`, `version`; prints `installed: N helpers` + one usage line + `reply: ready`; after `final_done` prints `FINAL: ...` | 400 | none | <= 300 ms |
| `locate.py` | `python3 /tmp/swe/locate.py "<query>"` / `--query Q` / `--stdin` | Layout header (top-level packages with `.py` counts, test dirs). BM25 over identifier tokens (camel/snake split) of symbol names x3, path, first 3,000 chars of body; query cleaned of PR-template boilerplate, links, checklists (v9 rules). Boosts: symbol name in query x2.5, file stem in query x1.8, file changed in the last 20 commits x1.15 (marked `recently changed`); dampers: tests x0.35, `docs/ docs_src/ examples/ benchmarks/ scripts/` x0.5 unless the query says docs/example/tutorial. <= 8 files x <= 4 symbols with `L<start>-<end>`; `related tests:` line (test files naming the top symbols). Files from `git ls-files -z '*.py'`; index cached as `SWE/index_<baseline sha>.marshal`; AST parse in a 4-worker process pool when > 400 files, 6 s parse budget, then unparsed files ranked by `git grep -c -w` hits. Never reads stdin without `--stdin` | 1,600 | 15 s | cold <= 2.5 s on rich; <= 8 s on 3,000 files; warm <= 0.5 s |
| `show.py` | `python3 /tmp/swe/show.py SPEC [SPEC ...]` / `--spec "SPEC SPEC"`; SPEC = `path` \| `path:N` \| `path:N-M` \| `path::Qual.name` \| `pkg.mod.Qual.name` \| `name` | Reads from `root()`. Prints `== path lines a-b of T ==` then `N\|line`, numbering by `\n` only (identical to git and `replace.py`). `path:N` shows N-10..N+30; `path` alone shows the outline (defs with line ranges) plus the first 40 lines. `path::Qual.name` and dotted names resolve by AST in the repo first, then (dependencies) by a subprocess `importlib` + `inspect.getsourcelines` with the file path printed. Bare `name`: up to 3 definitions from the locate index. Records `views[(root, path)] = (clock, a, b)` | 3,500; <= 80 lines per spec | 10 s (dependency) | <= 150 ms path specs; <= 3 s dotted dependency |
| `replace.py` | `python3 /tmp/swe/replace.py --file F --start N --end M <<'EOF'` ... `EOF`; `--after N`; `--create 1`; `--text "..."` instead of stdin | Edits `root()/F` (the shadow during retry). Replaces lines N..M (1-based inclusive; `--end N-1` inserts). Bytes in, UTF-8 `surrogateescape`, CRLF and final-newline state preserved, no `str.splitlines`. Refuses PROTECTED paths and paths outside the root. Un-rewrites sandbox paths in the new text (`SANDBOX_ROOT/tmp` -> `/tmp`, `/workspace`, `venv/bin` -> `/usr/local/bin`). Strips `^\s*\d+\|` prefixes when every non-blank line has one. `compile()` in-process; on SyntaxError tries, in order, unescape `\"` `\'` `\\n` (only when the replaced region had none), re-indent the block to the first replaced line's indent; a variant that compiles is applied as `AUTO-FIXED: <which>`; else the file is left byte-identical and the error is printed with 3 numbered context lines. Warns when the new block starts at column 0 but the replaced line was indented. Stale-number guard: an edit starting below an earlier edit with `delta != 0` in the same file, with no later `show.py` view of that region, is refused with the corrected numbers. Loop breaker: identical failing call -> `REPEATED: ... use show.py and another range`. Deadline guard (5.3). Prints `OK: replaced lines N-M (k old) with j new. Now lines a-b:` + numbered region +-2, and the first/last replaced old line | 1,400 | none | <= 200 ms on a 5,000-line file |
| `repro.py` | `python3 /tmp/swe/repro.py <<'EOF'` script `EOF`; `--code "..."`; `--run 1` re-runs the saved script | Saves `SWE/repro.py` (never in the repo), `compile()` check (`REPRO INVALID: syntax error line k`). Runs ORIGINAL (in `ws` when its source diff is empty, else in the base worktree) and CURRENT (in `root()` when its diff is non-empty) concurrently: `cwd=<tree>`, `PYTHONPATH=<tree>[:<tree>/src]`, `TMPDIR=SWE/rt_<which>`, 20 s each. ORIGINAL rc != 0 or timeout -> `REPRODUCES`, rc 0 -> `DOES NOT REPRODUCE`. Prints per run `exit=<rc> <last traceback line or last stdout line>` (<= 500 chars) and `imports <pkg> from <path>` (+ `WARNING: imported from outside <tree>`). Stores sha, validity and ORIGINAL signature. Deletes files the runs created in the trees (porcelain before/after) and says so | 1,500 | 20 s per run | <= 200 ms + run time |
| `probe.py` | `python3 /tmp/swe/probe.py <<'EOF'` code `EOF`; `--code "..."`; `--timeout N` (1-60, default 20) | Runs a snippet like repro's CURRENT run; nothing stored except the repeat key; created files deleted and reported | 2,000 | 20 s | <= 150 ms + run time |
| `run.py` | `python3 /tmp/swe/run.py [--timeout N] "<shell command>"` | `bash -c` in `root()`, contract 5, ANSI stripped, `\r` -> `\n`, head+tail cap, `exit=<rc>` or `TIMEOUT after N s (possible infinite loop or waiting for input)` with partial output | 2,500 | 20 s default, 1-60 | <= 100 ms + run time |
| `check.py` | `python3 /tmp/swe/check.py [--target tests/test_x.py]` | `gate.py --mode check` (5.4) | 2,200 | 45 s wall | <= 1 s + tests; cached <= 0.3 s |
| `gate.py` | `python3 /tmp/swe/gate.py [--mode judge\|check\|report\|redo\|final] [--target F]` (default `judge`) | 5.4 | judge 2,400; report 3,000; final 1,000; redo 500 | 45 s wall | as check |

### 5.3 Clock line, phases and banners

`state.phase` is set by the helpers: `locate` at install; `fix` at the first `replace.py` or `check.py` of attempt 1;
`judge` by `gate.py` (judge mode); `retry` when the judge decides RETRY; `final` by `gate.py --mode final`.

| phase | condition | text appended to the first line |
|---|---|---|
| locate | clock >= 75 | `TIME (locator): 75 s used. Stop and reply with your plan now. (Fixer: ignore this line.)` |
| fix | clock >= 150 and the source diff is empty | `WARNING: no source change yet. Make your best edit from the plan now.` |
| fix | >= 3 checks with problems and clock <= 165 | `STOP: reply now. A fresh second attempt with this report follows.` |
| fix | clock >= 200 | `TIME: finish this edit, run check.py once, then reply.` |
| fix | clock >= 250 | `TIME: reply now.` |
| retry | always | `DEADLINE: stop by clock D s (now N s)` with D = min(255, retry start + 70) |
| retry | clock >= D - 10 | `TIME: reply now.` |
| retry | clock >= D | every helper except `gate --mode report/final` refuses: `DEADLINE passed: reply now.` |
| any | `final_done` | `FINAL: the patch is final. If you can call submit_patch, call it now; otherwise reply done.` |

No hard refusal exists before the retry: on hidden tasks attempt 1 may legitimately need the whole cap, and the harness
grades the working tree at the cap anyway.

### 5.4 The gate engine (`gate.py`, shared by `check.py`)

Trees: `ws` (graded), `base` (worktree at the tag, created lazily once, `SWE/base`), `shadow` (retry only, `SWE/shadow`).
"CURRENT" = `root()`.

1. **Hygiene** (every mode, on CURRENT, and on `ws` in judge/final): tracked PROTECTED files modified or deleted ->
   `git checkout _swegemma_baseline -- <path>`; untracked files deleted when: PROTECTED; a root-level
   `(repro|reproduce|debug|scratch|tmp|temp|verify|try|demo)[\w-]*\.py`; extension `.log .out .orig .rej .bak .swp .diff
   .patch`; a root-level `.txt`; inside a directory named `_pytest`, `site-packages`, `pip` or `*.dist-info` (the 9.2 MB
   vendoring case, harness_runtime 7.5). New `.py` modules in packages and other new files are kept. One line:
   `HYGIENE: undid tests/test_x.py; removed repro.py`.
2. **Diff**: `diff(CURRENT)`; `src` = non-PROTECTED paths. Empty -> `VERDICT: FAIL (EMPTY: no source change)`, skip 3-6.
3. **Compile + import**: `compile()` each changed `.py`; one subprocess `python3 -c "import m1, m2"` (module names from
   paths, `src/` stripped, files outside importable packages compiled only), `PYTHONPATH=<tree>[:<tree>/src]`, 10 s;
   prints `imports <pkg> from <path>`; a package imported from outside the tree -> `WARNING` and components 5-6 become
   neutral (F10: src-layout repos import the host copy).
4. **Related tests**: candidates = tracked files named `test_*.py` or `*_test.py` (the harness `python_files`, never
   `tests/render.py`). Score = 10 x `--target` + 5 x (`test_<stem>.py` or `<stem>_test.py` for a changed module stem) +
   3 x each changed def/class name (>= 4 chars) present as a word (one `git grep -c -w -e n1 -e n2 ...`) + 2 x imports
   the changed module + 1 x mentions the stem. Top 3. For comparisons (retry/final) the file set is the union of both
   candidates' sets. Runs the grader's line on ORIGINAL (base tree, cached per file set) and CURRENT (cached per diff sha
   + file set), concurrently:
   `python3 -s -m pytest <files> -q -p no:anyio -p no:cacheprovider -o timeout=0 -o python_classes="Test* *Test" --tb=short -rfE --junitxml=SWE/j_<which>.xml`,
   env `PYTHONSAFEPATH=1 PYTHONNOUSERSITE=1 PYTHONPATH=<tree>[:<tree>/src] TMPDIR=SWE/rt_<which>`, `cwd=<tree>`, 40 s each.
   Outcomes from JUnit. `TESTS: unavailable` (neutral, never counted as passing) when pytest is missing, prints
   `pytest is disabled in this environment` (the Docker mask, `container_setup.py:968-1000`; respected, not bypassed),
   collects 0 items, or writes no JUnit. `TESTS: too slow, skipped` (neutral, cached) when ORIGINAL exceeds 40 s.
5. **Repro** (if a valid repro exists): CURRENT run (20 s); ORIGINAL from the stored result (re-run in the base tree when
   the script sha changed).
6. **Siblings**: from the diff's removed lines (stripped, >= 12 chars, not comment/bracket/`pass`/`return`/`else:`), one
   `git grep -n -F -e l1 -e l2 ...` over non-test `.py` in CURRENT; hits outside the changed hunks; plus defs with the
   same name as a changed def in other classes/files (locate index). <= 8 lines:
   `SIBLINGS: rich/text.py:1062  for span in text._spans:  (unchanged; same defect?)`. Advisory only (not scored).
7. **Score** (lexicographic tuple, higher is better):
   `(nonempty, compiles_and_imports, collects, no_hang, repro, -regressions)` with
   `collects` = 0 when CURRENT has a collection error that ORIGINAL did not; `no_hang` = 0 when CURRENT tests or the repro
   timed out and ORIGINAL did not; `repro` = 2 valid repro passes now, 1 no valid repro (or neutral), 0 valid repro still
   fails; `regressions` = tests passed on ORIGINAL and failed/errored on CURRENT (both-failing tests listed, not counted;
   tests unavailable -> 0). `PASS` iff `(1,1,1,1, >=1, 0)`. The repro outranks regressions on purpose: in 6/39 local
   tasks the gold patch "regresses" tests that the hidden test_patch rewrites (test_plan F4), and a valid repro that
   encodes the requested behaviour is what protects such a fix from being undone.
8. **Candidates**: every evaluation of a distinct diff sha records `cand_<attempt>_<n>.diff` (binary, incl. new files),
   its score, repro sha and test file set. Scores are compared only under the same repro sha and the same test files;
   otherwise both candidates are re-evaluated on the union (cached runs make this cheap).
9. **Judge mode**: hygiene on `ws`; evaluate the current tree; if a recorded attempt-1 candidate scores strictly higher,
   `restore(ws, best)` (green-checkpoint restore, literature T3: 5/5 gold-then-destroyed cases recovered); record
   candidate 1 = the resulting tree; decide:
   - PASS -> `DECISION: SUBMIT`
   - EMPTY and clock <= 235 -> `RETRY: EMPTY ...` + `DECISION: RETRY`
   - FAIL, attempt 1, clock <= 175 -> `RETRY: <reason>` + `DECISION: RETRY`
   - otherwise (including any internal error: fail-open) -> `DECISION: SUBMIT`
   On RETRY: `worktree(SWE/shadow, cand_1.diff)`, `active_root = shadow`, `attempt = 2`, phase `retry`,
   `retry_deadline = min(255, clock + 70)`. If the worktree cannot be created: degraded mode (`active_root = ws`, the
   candidate-1 diff is kept, and final restores the best candidate), reported as `NOTE: editing in place`.
   Quick mode (clock >= 270 or clock + 1.2 x last test seconds > 285): hygiene + compile only, cached results, SUBMIT.
   Output shape (<= 2,400 chars):
   ```
   [clock 142s] GATE attempt 1
   DIFF: rich/text.py +6 -2 | rich/cells.py +1 -1
   HYGIENE: nothing to undo
   COMPILE+IMPORT: ok (rich from /workspace/rich/__init__.py)
   REPRO: original exit=1 AssertionError: 24 != 23 | now exit=0 -> FLIPPED
   TESTS: tests/test_text.py tests/test_cells.py | original 212 passed | now 210 passed, 2 failed (3.1 s)
   REGRESSIONS (passed before, fail now):
     tests/test_text.py::test_divide  AssertionError: assert [...] == [...]
   SIBLINGS: none
   CHECKPOINT: current tree is the best of 3 checks
   VERDICT: FAIL (2 regressions)
   RETRY: 2 existing tests fail now (tests/test_text.py::test_divide, ...); the reproduction passes. A regression is right only if the issue asks for exactly that behaviour change.
   DECISION: RETRY
   ```
10. **Check mode** (fixer and retry): steps 1-8 on CURRENT; in retry phase, when the shadow's score is strictly higher
    than the best candidate, `restore(ws, shadow diff)` and print `PROMOTED: your version is now the submission`.
    Last line `STATUS: ok` or `STATUS: <n> problems: REPRO; REGRESSIONS; ...` (+ banners).
11. **Report mode**: stored judge report, <= 3 failing tests with their assertion lines (from JUnit messages), repro
    output, the current diff `-U2` (<= 1,400 chars), `DEADLINE: stop by clock D s (now N s)`,
    `You are editing a private copy at <shadow>; paths are the same as in /workspace.` `NOTHING TO DO` when the last
    verdict was PASS or `final_done`.
12. **Redo mode**: record the shadow's diff as a candidate, reset the shadow to the tag (`git checkout` + clean of its
    untracked files); `/workspace` untouched.
13. **Final mode**: if the shadow changed since its last evaluation, evaluate it (quick path above: compile + repro
    only); promote when strictly better; then `restore(ws, best)` exactly (removes anything `read_file`/`write_file`/raw
    commands changed in `/workspace` during the retry); hygiene; `final_done = True`; print `READY: call submit_patch now`
    (always, also after an internal error). <= 12 s on the quick path.

### 5.5 `state.json`

```json
{"version": "v10.0", "ws": "/abs/ws", "installed_at": 0.0, "t0": 0.0, "t0_src": "tag",
 "phase": "fix", "attempt": 1, "active_root": null, "retry_deadline": null, "final_done": false,
 "repro": {"sha": "...", "valid": true, "orig": {"rc": 1, "timeout": false, "sig": "AssertionError: 24 != 23"}},
 "base_dir": ".../swe/base", "shadow_dir": null,
 "orig_tests": {"<sha(files)>": {"secs": 3.1, "collect_error": false, "timeout": false, "outcomes": {"f::c::t": "passed"}}},
 "cur_tests": {"<tree>|<diff sha>|<sha(files)>": {"secs": 2.9, "outcomes": {}}},
 "cands": [{"attempt": 1, "n": 2, "diff_sha": "...", "diff_path": ".../cand_1_2.diff", "score": [1,1,1,1,2,0],
            "repro_sha": "...", "files": ["tests/test_text.py"], "clock": 118.0}],
 "checks": {"1": 2, "2": 0}, "judge": {"clock": 142.0, "verdict": "FAIL", "decision": "RETRY", "report": "..."},
 "edits": [{"tree": "ws", "file": "rich/text.py", "start": 40, "end": 52, "delta": 3, "clock": 95.0}],
 "views": {"ws|rich/text.py": [90.0, 30, 110]},
 "recent": [{"key": "<sha1>", "diff_sha": "...", "n": 2}]}
```

---

## 6. eval_config and sampling

| knob | value | why |
|---|---|---|
| `max_time_minutes` | 5 | the only 12 h knob; 5.25 fails at N = 130 with verification counted (time_model 5) |
| `timeout_seconds` | 90 | Also the hidden-test pytest timeout (`verification.py:498-503`). Verification is outside the 12 h (host, forum 743663), so its hang tail cannot touch the cliff, while too low a value silently fails correct patches on slow hidden suites (public max 12.6 s; hidden repos differ, forum 742882). Agent-side hangs go through helpers with 20-45 s internal timeouts, so 90 vs 60 matters only for bare commands (4 of 3,440 L4 commands hung) |
| `max_tool_calls` | 120 | loop brake; the full retry path uses ~35-50 calls |
| `max_turns` | 220 | >= 1.6 x tool calls; never binds before the time cap |
| sampling | setup/judge/finalizer: T 0.0, top_p 1, top_k 1 (greedy, mechanical). locator/fixer/retry: T 1.0, top_p 0.95, top_k 64 (the v4/v9 values; changing them is an unmeasured risk). `include_thoughts: false` everywhere; no `seed` (never reaches vLLM) | |
| `max_output_tokens` | setup 256, locator 1,536, fixer 2,048, judge 256, retry 2,048, finalizer 256 | caps a runaway at 44-58 s instead of 117 s; overflow line 30,720 |

---

## 7. Time analysis

### 7.1 Per-call cost model (4x L4, time_model 2)
`t_call = 1.08 x (0.085 s + 28.5 ms x output_tokens + 0.65 ms x uncached_prompt_tokens) + tool time`.
The 1.08 is the measured under-estimate of this model against real L4 (own_data 11). A stage's first call pays the
prefill of its fixed prefix; later calls pay only the new tool result plus the previous reply.

### 7.2 Stage budget (targets on a public-like task)

| stage | calls | output tok | uncached prompt tok | LLM s | tool s | stage s |
|---|---|---|---|---|---|---|
| setup | 2 | 40 | 5,600 (harness prompt) | 5.3 | 0.2 | 5.5 |
| locator | 10 | 900 | 2,800 + 9 x 650 | 34.7 | 4 | 38.7 |
| fixer | 11 | 1,100 | 3,500 + 10 x 700 | 42.2 | 10 (3 checks) | 52.2 |
| judge | 3 | 90 | 2,200 + 900 | 5.2 | 1-3 | 7.2 |
| **attempt-1 path** | 26 | 2,130 | | 87.4 | 16 | **~103** |
| retry_fixer | 8 | 1,000 | 3,300 + 7 x 700 | 37.8 | 12 | 49.8 |
| finalizer | 3 | 60 | 2,400 | 3.8 | 3-5 | 8 |
| **retry path (fires ~0.35-0.5 public)** | | | | | | **~58** |

Target mean: 103 + 0.42 x 58 = **~127 s** per public-like task.

### 7.3 Counterfactual replay (measured trajectories, not targets)

`docs/v10/design_B_replay.py` (stdlib, 2 s) re-times every race-1 trajectory with 7.1 and applies only design-B
mechanisms: `edit_file` failure streaks collapse to one `replace.py` call; post-cap calls vanish; the 3rd+ identical
`run_command`/`read_file` in a stage vanishes (REPEAT banner); stage replies capped (200/100 tokens) and outputs capped
(1,536/2,048); the v9 verifier's gate/repro/pytest calls become `check.py` calls (one per two), its diff/preflight/
submit/reply become the judge; setup and judge stages added; the retry fires with probability 1.0 (empty patch), 0.6
(unresolved non-empty), 0.12 (resolved: false FAIL) when the judge is reached by 175 s, and costs 8 calls / 1,000
tokens, bounded by the 255 s deadline, plus the finalizer. Output (2026-09-28):

| base trajectory | v4 as-is | v10, no retry | **v10 design** (175/255) | 190/262 | pessimistic (clock rules ignored, v9 verifier calls kept) | pessimistic + 12-call/1,800-token retry | retry fire |
|---|---|---|---|---|---|---|---|
| r_v4 | 150.2 | 108.5 (0.72) | **136.4 (0.91)** | 0.91 | 145.3 (0.97) | 158.0 (1.05) | 0.48 |
| r_v9_eog | 174.0 | 125.4 (0.83) | **147.8 (0.98)** | 0.99 | 159.5 (1.06) | 168.3 (1.12) | 0.38 |
| r_v9_c | 152.7 | 99.4 (0.66) | **129.0 (0.86)** | 0.86 | 138.0 (0.92) | 150.7 (1.00) | 0.50 |
| r_v9_eg | 169.0 | 109.9 (0.73) | **137.5 (0.92)** | 0.92 | 147.5 (0.98) | 159.8 (1.06) | 0.47 |
| r_v9_eo | 166.4 | 115.8 (0.77) | **144.9 (0.96)** | 0.96 | 148.9 (0.99) | 162.3 (1.08) | 0.49 |
| r_v9_og | 177.0 | 127.2 (0.85) | **154.6 (1.03)** | 1.03 | 164.5 (1.09) | 174.9 (1.16) | 0.47 |

(Ratios are to v4 as-is, 150.2 s; own_data's independent estimate for v4 is 147 s.) Per stage on the v9_eog base:
setup 5.5 s, locator 47.5 s, fixer + checks 67.5 s, judge 8.2 s; the judge is reached by 175 s in 45/51 tasks (median
126 s). The replay keeps v9's locator behaviour (17.7 calls against the prompt's ~8), so it over-states the locator.

Hidden-like tasks (every stage x2, then the clock rules): v10 203-218 s vs **v4 as-is x2 capped at 300: 236.8 s**, so
v10 is 0.86-0.92 x v4 there; the judge is reached by 175 s in only 19-24/51, and the retry fires 0.14-0.29.

### 7.4 The 12 h cliff

**Hypothesis H1 (the measured one): hidden tasks are cap-saturated.** v4's hidden run took ~10.4 h for ~120 tasks,
~308 s/task all-in against a 300 s cap (own_data 2.4). v10 keeps the same cap, and nothing it does can make a task
exceed the cap by more than v4 could:
- the agent timer is `asyncio.timeout(300)` (`agent_runner.py:439-443`); `run_command` gets `min(timeout_seconds,
  max(5, remaining))` (`execution.py:27-40`), so a command started at the deadline overshoots by <= 5 s for both;
- `run_skill_script` runs in a thread (`skill_toolset.py:494`); the await is cancelled at the deadline, no overshoot;
- helper timeouts (20-45 s) are all below `timeout_seconds` (90), so no helper holds the loop longer than a bare
  command can; v10's 90 s (vs v4's 180 s) shortens the only command tail v4 had;
- setup and verification are harness-side and identical (verification is excluded from the 12 h anyway).
Worst case, every task at the cap: `600 + N x (300 + 3.6 + 5 + 1)` = **10.49 h (N = 120), 11.35 h (N = 130)**; v10's
whole-run wall is <= v4's, i.e. **+0 %** against a +8 % allowance.

**Hypothesis H2 (not supported by the data, budgeted anyway): hidden agent time is public-like and the extra wall came
from somewhere else.** Then v10's mean agent time must be <= 1.08 x v4's on public-like tasks. Replay: **0.98 central**
on the v9_eog base (0.86-1.03 over six bases); pessimistic 1.06 (0.92-1.09); only the compound pessimistic case with a
retry twice the planned size exceeds 1.08 on three bases (1.08-1.16), and at 1.16 the run is still 11.0 h for 120 tasks
(12 h cliff at +15 %, own_data 2.4). The single knob that trades retry value for time is `T["RETRY_LATEST_START"]`;
the ship gate R-B69 re-runs this replay on the real v10 race and requires <= 1.08.

**Hypothesis H3 (intermediate: hidden tasks harder, not all capped):** the x2 replay above; v10 is 0.86-0.92 x v4
because its clock rules end stages that v4 let run to the cap.

### 7.5 What the retry can cost where it matters
The retry never extends a task: it starts by 175 s (EMPTY: 235 s), every helper refuses edits after the retry deadline
(<= 255 s), and the finalizer needs ~8 s. If the model ignores all of that, the harness cap still ends the task at 300 s
with the best candidate in `/workspace`. On cap-saturated hidden tasks the retry rarely fires (0.14-0.29), because the
judge arrives late.

---

## 8. Expected gain (honest)

Baseline: v9_eog 28/74 local (21/51 race + 7/23 rest); v4 26-27/74 local = 0.12 LB (7/58). Flips counted against
v9_eog's 46 misses, by primary loss bucket (own_data 9) and the catalog's per-task lever tiers (task_catalog 4).

| lever (mechanism here) | tasks it plausibly flips | expected |
|---|---|---|
| repro-must-flip inside the fixer loop + gate (`repro.py`, `check.py`) | rich_4075, rich_3521, rich_4079 likely; fastapi_11194, fastapi_13920, fastapi_14616, rich_3472, rich_3777, rich_3782, rich_3935 possible | +1.5 to +2 |
| edit channel without `edit_file` (numbers, heredoc, auto-fix, loop breaker) | rich_3278, rich_3043, rich_3052, fastapi_15588 (+ loop-spiral tasks, 2-7 per arm) | +1 to +1.5 |
| siblings (SIBLINGS line in every check and in the retry report) | fastapi_5077, rich_3480 likely; fastapi_14986, rich_3953 possible | +1 to +1.5 |
| regression/collection gate + hygiene (test-file revert, scratch removal) | rich_3180, rich_4006, fastapi_14986; the 4-16 patches per run touching tests/ | +0.5 to +1 |
| hang-safe execution (repro/probe/run/gate timeouts, group kill) | rich_3480, rich_3772, rich_4006 | +0.3 to +0.5 |
| context guard + dependency source + runtime truth (`show.py pkg.mod.Name`, `probe.py`) | fastapi_14851, fastapi_5624, fastapi_14616 | +0.5 |
| guaranteed helpers | prerequisite (helpers were live in ~55 % of race-1 tasks) | +0.5 |
| green-checkpoint restore + never-empty warnings + EMPTY retry | rich_3472, rich_3782, capped-then-broken runs | +0.3 to +0.5 |
| **fresh-context retry** | second-draw ceiling on v9_eog's 30 race misses = sum over misses of the other five arms' solve rate = **1.2 tasks / 51** (computed from `eval/race1/runs/*/task_results.jsonl`); x detection ~0.6 x availability ~0.9 -> 0.65/51 -> **~0.9/74**; informed context (report, siblings) may add a little | +0.5 to +1 |
| new-failure costs (unknown-tool crash risk from no `edit_file`, setup overhead, false-FAIL retries that undo a correct fix without a repro) | | -1 to -1.5 |

Sum ~+6.5 to +9 before overlap; central **+5 -> 33/74 (45 %)**, range 29-37 (run-to-run noise alone is +-3).
Transfer: v4 went 35 % local -> 12 % LB (ratio 0.34). At that ratio v10 lands at **0.15 (9/58)**. The mechanics levers
(no edit spirals, cap-safe tree, never-empty, hygiene, helpers) fire on repo-agnostic signatures that are, if anything,
more common on the hidden set, where v4 ran to the cap; if hidden losses are mostly mechanical, 0.17-0.21 (10-12/58) is
possible. The retry is worth ~+0.3 hidden tasks because it fires in only 14-29 % of hidden-like tasks.
**0.30 (18/58) would need ~85 % local at the measured transfer; this design does not get there.** Its value is a verify
loop and a cap-safe, hygienic patch under the same 12 h cost as v4.

---

## 9. Risks and mitigations

| risk | why it matters | mitigation / kill switch |
|---|---|---|
| Hallucinated undeclared tool (`edit_file` most likely) | task lost with the patch | no prompt names it; `read_file`/`write_file`/`run_command` declared as guards; R-B70 requires 0 unknown-tool crashes in the race; fallback: declare `edit_file` on fixer/retry with a ban (v9_eog's setting: 2 loop tasks in 51) |
| Setup replies without installing | helpers missing in the locator | recovery rule in locator/fixer/retry; self-install through any `run_skill_script`; install rate >= 97 % is a race metric (R-B70) |
| Gate false FAIL (F4: 1/39 with default selection) -> retry undoes a correct fix | lost task | repro outranks regressions; KEEP rule; promotion only when strictly better; ties keep attempt 1 |
| Model-written repro asserts a guessed string | fixer chases a wrong target; retry fires wrongly | prompt rule "assert only what the issue states"; repro is one component; retry may reply keep; the retry can rewrite the repro and both candidates are then re-scored on the new one |
| `git worktree` unavailable or fails (disk, odd repo) | no private copy | degraded in-place mode with exact best-candidate restore at final (R-B62) |
| Clock source missing (packed refs, no tag) | thresholds misfire | tag mtime -> commit time -> install time - 10 s |
| Docker scorer: TMPDIR unset, no rewriting, editable install, pytest masked | helpers misplaced, gate blind | install writes `/tmp/swe` when not rewriting; explicit `PYTHONPATH` for our runs; import-path self-check; mask detected and respected (neutral, never a false PASS); Linux Docker test (R-B26) |
| Kaggle compaction mid-stage | stage loses its history | < 12k planned per stage; `{problem_description}`/`{plan?}` re-rendered; `check.py` and `gate --mode report` re-materialise state from disk |
| H2 time overrun | 12 h risk only under the unsupported hypothesis | replay 0.98 central; `RETRY_LATEST_START` knob; R-B69 ship gate |
| Large hidden repos | locate cold parse, worktree checkout, git status | 6 s parse budget + grep fallback; lazy base worktree; timings asserted on a 3,000-file synthetic repo |
| Concurrent ORIGINAL/CURRENT test runs interfere | flaky regressions | separate `TMPDIR` per run, `-p no:cacheprovider`, separate trees; a regression whose message contains `Address already in use` is re-run serially once |
| Stale line numbers after an edit | wrong lines replaced | stale guard refuses with corrected numbers; bottom-up rule; replaced old lines echoed |
| Nudge restart | wasted time, re-edits | `{final_note?}` guard, `FINAL:` banner, judge SUBMIT on `final_done` |
| `/tmp` literal in new code rewritten by the sandbox | wrong path baked into the patch | `replace.py` un-rewrites (R-B41) |
| Repo module named like a stdlib module | helper import breaks | helpers drop `PYTHONPATH`/workspace from their own `sys.path` (R-B22) |
| Gate crash or hang | no decision | 45 s wall; fail-open SUBMIT in judge mode; finalizer submits whatever happens |

---

## 10. Requirement registry

Tiers: **CI** (< 10 min on this Mac, no network), **NIGHTLY** (40 local snapshots in the kpar venv, Docker), **REPLAY**
(recorded traces), **RACE** (GPU, Carson's call). Test files: `tests/test_v10_{bundle,prompts,flow,sandbox,clock,caps,
locate,show,replace,repro,run,gate,perf,timing,tasks}.py`. Helper tests spawn the helper as a subprocess against the
fixture `swe_repo` (new `tests/conftest.py` fixture: scratch git repo with a package, tests, the harness `pytest.ini` +
`conftest.py` exactly as `setup_workspace_test_config` writes them, a baseline commit and the `_swegemma_baseline` tag;
`TMPDIR` and `SWE_WS` pointed at `tmp_path`) and assert `rc == 0`, the `[clock` first line and the output cap.
Real-sandbox tests follow `tests/test_sandbox_tmp_paths.py`. Flow tests reuse the mock server
(`scratchpad/cfgspace/mock_openai.py`, copied to `tests/helpers/mock_openai.py`).

| id | requirement | test (tier) |
|---|---|---|
| R-B01 | `submissions/v10` compiles with the official compiler; tree = `SequentialAgent swe_pipeline` -> `setup, locator, fixer, judge, retry_fixer, finalizer` in order | `test_v10_bundle.py::test_official_compile_tree` runs `scripts/validate.py submissions/v10` and parses the tree (CI) |
| R-B02 | Every LlmAgent: the one model id, `include_contents: none`, inline gen config with the section-6 values, `include_thoughts: false`; no `seed`, `thinking_level`, `thinking_budget` | `test_v10_bundle.py::test_agent_fields` (CI) |
| R-B03 | Tool lists exactly as section 2; `edit_file` in no stage; `submit_patch` only on judge and finalizer; `skills` only on setup, locator, fixer, retry_fixer | `test_v10_bundle.py::test_tool_lists` (YAML + compiled names) (CI) |
| R-B04 | `output_key`: locator `plan`, fixer `fix_notes`, judge `verdict`, finalizer `final_note`; none elsewhere | `test_v10_bundle.py::test_output_keys` (CI) |
| R-B05 | `eval_config.yaml` is exactly `90 / 120 / 5 / 220` | `test_v10_bundle.py::test_eval_config` (CI) |
| R-B06 | Packaging: only `.yaml .md .py`; no `__pycache__`, dotfiles, symlinks, extensionless files; `SKILL.md` name = dir; < 1 MB | `test_bundles.py` parametrisation extended to v10 + `test_v10_bundle.py::test_packaging` (CI) |
| R-B07 | `submissions/v9_eog`, `submissions/v4`, `helpers_v9` unchanged | `test_v10_bundle.py::test_frozen_unchanged` (`git diff --quiet HEAD --` on those paths) (CI) |
| R-B08 | The request body of each stage carries its sampling (`temperature, top_p, top_k, max_completion_tokens, chat_template_kwargs.enable_thinking=false`) and no `seed` | `test_v10_flow.py::test_sampling_in_requests` (mock capture) (CI) |
| R-B09 | Rendered fixed prefix (instruction with the 10,095-char statement + compiled declarations + skill boilerplate) <= 5,500 tokens (chars / 3.2) for locator/fixer/retry; <= 3,000 for judge/finalizer and for setup excluding the harness prompt | `test_v10_flow.py::test_prefix_budget` (CI) |
| R-B10 | Flow through `App`/`Runner` with scripted replies: (a) judge SUBMIT ends after 4 stages; (b) RETRY runs retry_fixer and finalizer, finalizer submit ends; (c) text-only setup still reaches the locator; (d) finalizer text without submit -> nudge restart -> locator/fixer/retry answer `done` with no tool call because `{final_note?}` is set, judge submits | `test_v10_flow.py::test_paths[a-d]` (CI) |
| R-B11 | Brace lint: every `{...}` in every prompt is one of the five allowed placeholders | `test_v10_prompts.py::test_brace_lint` (config_space 10 regex) (CI) |
| R-B12 | No prompt names a tool its stage lacks (scan: 9 registry names, `run_skill_script`, `load_skill`, `list_skills`, `edit_file`, `git_grep`, `exit_loop`); `run_skill_script` only in prompts of stages with skills | `test_v10_prompts.py::test_tool_names` (CI) |
| R-B13 | setup <= 700 chars with the literal install call; judge and finalizer <= 900 chars, no problem statement; finalizer says always submit | `test_v10_prompts.py::test_small_prompts` (CI) |
| R-B14 | Locator prompt contains the helper usages, title-to-identifier rule, dependency-source rule, runtime-truth rule, repro rules (assert only stated behaviour, must fail, one alternative shape, skip when no example), plan format, 120-word cap, `final_note` guard | `test_v10_prompts.py::test_locator_rules` (CI) |
| R-B15 | Fixer/retry prompts contain the heredoc example with `--start/--end/--after/--create`, bottom-up rule, check loop rules (REPRO / REGRESSIONS with the intended-change exception / SIBLINGS), never-empty rule, protected-files rule, reply caps, `final_note` guard; retry also report-first, REPAIR/REDO/keep, "show.py not read_file" | `test_v10_prompts.py::test_fixer_retry_rules` (CI) |
| R-B16 | Every command line in any prompt runs verbatim in the real sandbox after install (placeholders filled from a fixture repo) with no `can't open file` and no usage error | `test_v10_prompts.py::test_prompt_commands_execute` (CI) |
| R-B17 | `install.py` run like a skill in a real `SubprocessManager` makes every helper reachable as `python3 /tmp/swe/<h>.py`; idempotent; <= 400 chars; <= 300 ms | `test_v10_sandbox.py::test_install_reaches_all_helpers` (CI) |
| R-B18 | Every helper runs as a skill script (cwd = temp skill dir, argv built as `skill_toolset.py:640-652` builds it) and self-installs the rest; afterwards `python3 /tmp/swe/check.py` works | `test_v10_sandbox.py::test_every_helper_as_skill_script` (CI) |
| R-B19 | No `/tmp` string constant in helper code except `_ws.FALLBACK_TMP`; state and scratch only under `TMPDIR` (regression: v9 `replace.py:28`, `check.py:7`) | `test_v10_sandbox.py::test_no_tmp_literals` (AST walk) (CI) |
| R-B20 | Workspace detection order SWE_WS -> PWD -> cwd -> state -> `/workspace`; never under `SWE`; a host `/workspace` git repo does not beat `PWD` (regression: v9 `_ws.ws()` order); `cd sub && python3 /tmp/swe/show.py ...` works | `test_v10_sandbox.py::test_ws_detection` (CI) |
| R-B21 | Stdlib only; `ast.parse(..., feature_version=(3, 9))` passes; imports within `sys.stdlib_module_names`; no helper name shadows a stdlib module or `pytest`, `_pytest`, `py` | `test_v10_sandbox.py::test_stdlib_only_and_names` (CI) |
| R-B22 | A repo with root-level `json.py`, `ast.py`, `types.py`, `select.py` on `PYTHONPATH` breaks no helper | `test_v10_sandbox.py::test_repo_shadow_modules` (CI) |
| R-B23 | Every helper exits 0 with a `[clock` first line on every path (missing args, bad ints, missing and binary files, 1 MB stdin); unexpected exceptions print `HELPER ERROR ...` <= 300 chars | `test_v10_sandbox.py::test_fuzz_contract` (CI) |
| R-B24 | `replace/repro/probe` return within 3 s with `no text on stdin` on an open empty pipe or `/dev/null`; `locate.py` never reads stdin without `--stdin` (regression: v9 `locate.py:9`) | `test_v10_sandbox.py::test_stdin_never_blocks` (timing assert) (CI) |
| R-B25 | On timeout the whole process group dies: `sleep 30 &` and a grandchild `bash -c 'sleep 20'` are gone 0.5 s after `run.py --timeout 2` returns (regression: v9 `run.py`, F7) | `test_v10_run.py::test_timeout_kills_group` (CI) |
| R-B26 | Docker-like mode (TMPDIR unset, no rewriting, repo pip-installed editable, `src/` layout): install and every helper work, base-tree runs import the base copy | `scripts/linux_test.sh` running `test_v10_sandbox.py -k docker_like` in `python:3.12-slim` (NIGHTLY) |
| R-B27 | `clock()` from the tag mtime; packed refs -> commit time; no tag -> install time - 10 s; `SWE_FAKE_CLOCK` override; every output starts `[clock Ns]` | `test_v10_clock.py::test_t0_sources` (`os.utime` the ref, `git pack-refs --all`, delete the tag) (CI) |
| R-B28 | Thresholds live only in `_ws.T` with the section-5.1 values; banners exactly per the 5.3 table | `test_v10_clock.py::test_banners` (phase x clock matrix) (CI) |
| R-B29 | Output caps per 5.2; cut marker present when cut; full text in `SWE/last.log` | `test_v10_caps.py::test_caps` (1 MB adversarial output per helper) (CI) |
| R-B30 | The 3rd identical helper call with an unchanged diff carries `REPEAT x3` | `test_v10_caps.py::test_repeat_banner` (CI) |
| R-B31 | `locate.py`: layout header; <= 8 files x <= 4 symbols with line ranges; `related tests:`; `recently changed` marks; `docs_src/` below the package for identical identifiers; tests damped | `test_v10_locate.py::test_ranking_rules` (synthetic repo) (CI) |
| R-B32 | Recall with the problem statement as query on the 40 local snapshots: R@1 >= 21, R@3 >= 28, R@8 >= 34 (v9 measured 21/28/34) | `test_v10_tasks.py::test_locate_recall` (NIGHTLY) |
| R-B33 | `locate.py` <= 2.5 s cold on rich, <= 8 s on a synthetic 3,000-file repo, <= 0.5 s warm; syntax errors, latin-1, BOMs do not crash it | `test_v10_perf.py::test_locate`, `test_v10_locate.py::test_bad_files` (CI) |
| R-B34 | `show.py` spec forms all work; a dependency symbol (`json.JSONEncoder.default`) resolves through the subprocess with its path; numbering equals `replace.py`'s on a file with `\x0c`, `\x85`, ` `; views recorded; in retry phase it shows the shadow | `test_v10_show.py::test_specs`, `::test_numbering_matches_replace`, `::test_shadow_view` (CI) |
| R-B35 | All gold hunks of the 40 local tasks applied bottom-up by line range are byte-identical to `git apply` (122/122 hunks, 50/50 files; new files via `--create`) | `test_v10_tasks.py::test_replace_gold` (NIGHTLY) |
| R-B36 | CRLF kept on a 1-line edit (numstat 1/1); latin-1 and invalid UTF-8 bytes kept; separator characters do not shift numbering; final-newline state kept (regression: v9 `replace.py`, F6) | `test_v10_replace.py::test_byte_fidelity` (CI) |
| R-B37 | Syntax gate and auto-fixes in order (prefix strip, unescape only when the old region had no escapes, re-indent); `AUTO-FIXED:` reported; otherwise the file is byte-identical and the error shows 3 numbered lines; column-0 warning | `test_v10_replace.py::test_autofix_prefix`, `::test_autofix_unescape`, `::test_autofix_reindent`, `::test_revert_byte_identical` (CI) |
| R-B38 | Refuses PROTECTED paths and paths outside the root; the file is untouched (regression: v9 edited test files) | `test_v10_replace.py::test_refusals` (CI) |
| R-B39 | Stale guard: below an earlier `delta != 0` edit without a newer view -> refused with corrected numbers; after `show.py` accepted; above accepted | `test_v10_replace.py::test_stale_guard` (CI) |
| R-B40 | An identical failing call prints `REPEATED:` naming the alternative | `test_v10_replace.py::test_repeated_failure` (CI) |
| R-B41 | Heredoc text rewritten by the real sandbox (`/tmp` -> `<root>/tmp`, `/workspace`, `/usr/local/bin`) is written to the file with the original literals | `test_v10_sandbox.py::test_heredoc_path_roundtrip` (real `SubprocessManager`) (CI) |
| R-B42 | `--after`, `--create` (refused when the file exists), `--text`; prints the new region +-2 and the first/last replaced line; <= 200 ms on 5,000 lines; in retry phase edits only the shadow (`/workspace` byte-identical) | `test_v10_replace.py::test_modes`, `::test_shadow_only`, `test_v10_perf.py::test_replace` (CI) |
| R-B43 | Retry deadline: in phase `retry` at clock >= deadline, `replace/check/show/run/probe/repro` refuse with `DEADLINE passed`; `gate --mode report/final` still work | `test_v10_replace.py::test_deadline_refusal` (`SWE_FAKE_CLOCK`) (CI) |
| R-B44 | `repro.py` saves outside the repo, compile-checks, runs ORIGINAL (in place when clean, base tree when dirty) and CURRENT concurrently, classifies REPRODUCES / DOES NOT REPRODUCE / INVALID, stores the ORIGINAL signature, prints the import-path line | `test_v10_repro.py::test_classification` (synthetic bug before/after) (CI) |
| R-B45 | With each local task's added test functions as the repro, ORIGINAL fails and CURRENT (gold) passes in >= 30 of the tasks whose gold passes locally | `test_v10_tasks.py::test_repro_flip_with_hidden_tests` (NIGHTLY) |
| R-B46 | A `while True: pass` repro returns TIMEOUT within 21 s with no surviving child; files a repro/probe run creates in a tree are deleted and reported | `test_v10_repro.py::test_hang_and_cleanup` (CI) |
| R-B47 | `src/` layout with an installed same-named package -> `WARNING: imported from outside` in repro/check/gate and neutral repro/test components | `test_v10_repro.py::test_import_path_warning` (CI) |
| R-B48 | `run.py`: default 20 s (1-60), partial output kept on timeout, ANSI stripped, `\r` -> `\n`, `exit=`/`TIMEOUT` status, cwd = active root | `test_v10_run.py::test_run` (CI) |
| R-B49 | Hygiene matrix: tracked protected files restored from the tag; untracked test files, root scratch scripts, scratch extensions, root `.txt`, vendored dirs deleted; new package modules and data files kept; one HYGIENE line | `test_v10_gate.py::test_hygiene_matrix` (CI) |
| R-B50 | Gold + an edit inside the hidden test file: after hygiene the harness-exact mini `verify_task` (reset list, test_patch apply, grader pytest line, JUnit rules) passes in >= 38/39 local tasks (test_plan F1) | `test_v10_tasks.py::test_hygiene_saves_tampered_gold` (NIGHTLY) |
| R-B51 | Diff base is `_swegemma_baseline`: after an agent `git commit`, check/gate/final see and submit the change, and the base tree is the tag, not HEAD (regression: v9 gate, F5) | `test_v10_gate.py::test_diff_after_commit` (CI) |
| R-B52 | Test selection: only `test_*.py`/`*_test.py` (regression: v9 picked `tests/render.py`); score rule of 5.4; `--target` first; <= 3 files; union for comparisons; the hidden test file chosen in >= 25/39 local tasks | `test_v10_gate.py::test_selection`, `test_v10_tasks.py::test_selection_hit_rate` (CI, NIGHTLY) |
| R-B53 | Test runs use the grader's flags and env, separate `TMPDIR`s, ORIGINAL and CURRENT concurrently (wall <= max + 1 s); pass/fail/error/skip/collection error parsed from JUnit | `test_v10_gate.py::test_pytest_and_junit` (CI) |
| R-B54 | No false PASS from tests: 0 collected, no JUnit, pytest missing, or the `pytest is disabled` shim -> `TESTS: unavailable`, never counted as passing (regression: v9 gate, F3) | `test_v10_gate.py::test_no_false_pass` (fake `pytest` shim on PATH) (CI) |
| R-B55 | Regression classes: passed -> failed/error counted; both-failing listed only; CURRENT collection error with ORIGINAL collecting -> `collects` 0; CURRENT timeout with ORIGINAL finishing -> `no_hang` 0 | `test_v10_gate.py::test_regression_classes` (CI) |
| R-B56 | SIBLINGS from removed lines and same-name defs, <= 8 lines; a synthetic twin-function repo lists the untouched twin; on rich_3480 with only the first gold hunk the second site is listed | `test_v10_gate.py::test_siblings`, `test_v10_tasks.py::test_siblings_rich_3480` (CI, NIGHTLY) |
| R-B57 | Score tuple and lexicographic order exactly as 5.4 step 7 (table-driven: empty < compile error < collection error < hang < repro still failing < regressions < pass; repro flip with 1 regression > no repro with 0 regressions) | `test_v10_gate.py::test_score_order` (CI) |
| R-B58 | Base worktree made once (at the tag, ignored-but-present files copied); ORIGINAL cached per file set, CURRENT per tree + diff sha; an unchanged second gate <= 0.3 s | `test_v10_gate.py::test_cache_speed` (CI) |
| R-B59 | 45 s hard wall: a 60 s test file -> `TESTS: too slow` cached; an internal exception in judge mode -> `DECISION: SUBMIT` (fail-open) | `test_v10_gate.py::test_hard_wall_and_fail_open` (CI) |
| R-B60 | Green checkpoint: the judge restores the strictly best recorded attempt-1 candidate when the current tree scores lower; the resulting diff sha equals the candidate's | `test_v10_gate.py::test_checkpoint_restore` (CI) |
| R-B61 | Decision matrix: PASS -> SUBMIT; FAIL attempt 1 at clock <= 175 -> RETRY; EMPTY at clock <= 235 -> RETRY; else SUBMIT; quick mode at clock >= 270; last line exactly `DECISION: SUBMIT|RETRY`, `RETRY:` line before RETRY | `test_v10_gate.py::test_decision_matrix` (`SWE_FAKE_CLOCK` x verdict x attempt) (CI) |
| R-B62 | Shadow lifecycle: on RETRY the shadow = tag + candidate-1 diff; helpers edit only it; `/workspace` byte-identical until promotion; promotion only on a strictly better score under the same repro and test files, after which the `/workspace` diff sha equals the shadow's; `redo` resets only the shadow; worktree failure -> degraded in-place mode with exact restore at final | `test_v10_gate.py::test_shadow_lifecycle`, `::test_promotion_rules`, `::test_degraded_mode` (CI) |
| R-B63 | Report mode: stored report + <= 3 failing tests with assertion lines + repro output + `-U2` diff <= 1,400 chars + DEADLINE line, <= 3,000 chars; `NOTHING TO DO` after PASS or `final_done` | `test_v10_gate.py::test_report` (CI) |
| R-B64 | Final mode: re-evaluates a changed shadow (quick path when short of time), promotes when strictly better, restores the best candidate exactly into `/workspace` (stray files from `write_file`/raw commands removed), hygiene, `final_done`, always prints READY; quick path <= 12 s | `test_v10_gate.py::test_final` (CI) |
| R-B65 | After `final_done` every helper's first line carries `FINAL:`; judge mode then decides SUBMIT | `test_v10_gate.py::test_final_banner` (CI) |
| R-B66 | Offline oracle pipeline on the local snapshots: a scripted model (install, locate, repro from the hidden test, gold via `replace.py` bottom-up, check, gate) reaches `DECISION: SUBMIT` and the submitted diff passes the mini `verify_task` in >= 38/39 | `test_v10_tasks.py::test_oracle_pipeline` (NIGHTLY) |
| R-B67 | Offline retry simulation on >= 10 multi-hunk local tasks: attempt 1 = gold minus its last hunk, attempt 2 = full gold -> final keeps attempt 2 and verify passes; attempt 2 with a syntax error or empty -> attempt 1 kept; no final call (cap mid-retry) -> `/workspace` is attempt 1 byte-identical | `test_v10_tasks.py::test_retry_selection` (NIGHTLY) |
| R-B68 | Cliff arithmetic from the shipped values: `600 + N x (3.6 + 60 x max_time_minutes + 5 + 1) <= 0.92 x 43,200` for N = 120 and `<= 43,200` for N = 130; `timeout_seconds <= 90`; every helper internal timeout < `timeout_seconds`; `RETRY_HARD + 15 <= CAP` | `test_v10_timing.py::test_cliff_arithmetic` (CI) |
| R-B69 | `scripts/replay_l4.py` (port of `docs/v10/design_B_replay.py`) on the v10 race vs the v4 arm on the same tasks: mean projected agent time <= 1.08 x v4; tasks projected >= 295 s no more than v4's + 2 | `test_v10_timing.py::test_replay_budget` (REPLAY) |
| R-B70 | Kaggle-faithful race (compaction on: `EventsCompactionConfig(15, 2, 14336, 5)` as `scripts/make_eval_kernel.py:95`, L4 or 175 s pod cap), 74 tasks, pass conditions stated before the run: 0 unknown-tool crashes, 0 context overflows, install success >= 97 %, stage prompt < 14,336 in >= 95 % of stage-runs, resolved >= 26 (v9_eog 28 minus noise), retry fire rate 0.25-0.55 | RACE tier, Carson's call; queries listed in `docs/v10/race_checklist.md` |

---

## 11. Implementation order and ship gates

1. `_ws.py`, `install.py`, `run.py`, `show.py`, `replace.py` + CI tests (R-B17-R-B25, R-B27-R-B30, R-B34, R-B36-R-B43, R-B48).
2. `repro.py`, `probe.py` (R-B44, R-B46, R-B47).
3. Gate engine `gate.py` + `check.py` alias, including shadow, checkpoints, final (R-B49, R-B51-R-B65).
4. Bundle YAML, prompts, lints (R-B01-R-B16); `scripts/validate.py submissions/v10`; `bash -n`/`shellcheck`/`py_compile` via
   the existing `test_build.py`.
5. Flow tests with the mock server (R-B10); Linux Docker gate (R-B26); NIGHTLY task tests (R-B32, R-B35, R-B45, R-B50,
   R-B52, R-B56, R-B66, R-B67).
6. `scripts/replay_l4.py` and `docs/v10/race_checklist.md`; R-B69/R-B70 are Carson's call (GPU).

Ship rule (stated before any race): v10 replaces v9_eog only if R-B70 holds. If unknown-tool crashes > 0: declare
`edit_file` on fixer/retry with a ban and re-race. If install < 97 %: add the literal install call as the locator's
step 0. If R-B69 fails: lower `T["RETRY_LATEST_START"]` to 150 and re-run the replay.

---

## 12. Considered and rejected

- **In-place retry with a restore at final** (the earlier draft): a cap hit mid-retry grades a half-done attempt 2, and
  stages ignore their budgets often (locator in ~80 % of tasks, own_data 6). The private worktree costs ~1 s of tool time.
- **LoopAgent verify-retry** and **LlmAgent coordinator root**: see section 3.
- **Parallel candidates** (Sequential[setup, Parallel[k fixers], selector]): shared budgets, event-loop-blocking tools,
  unmeasured KV at gmu 0.80 (time_model 4); +15 to +60 s per task on L4. The serial retry is the cheap version.
- **Early `submit_patch` as insurance**: exceptions discard submitted patches too, and a later improvement needs a second
  submit; at the cap the working-tree fallback already grades the tree.
- **Bypassing a masked pytest** (`python -c "import pytest; pytest.main(...)"`): would circumvent an organiser control;
  the gate degrades to repro + compile instead.
- **A cross-task ledger in the host `/tmp`** to govern the 12 h budget globally: works only on the subprocess backend
  (the scorer is Docker) and is a rules grey zone.
- **Calling the vLLM endpoint from a skill script**: bypasses the harness's turn accounting (harness_runtime 12).
- **`run_skill_script` as the main channel** (its dict result is JSON-escaped once, not twice, so code reads cleaner):
  plausible, unmeasured, and heredocs still need `run_command`; a candidate for a later A/B.
- **Lower temperature for the working stages**: unmeasured; kept at the v4/v9 values.
