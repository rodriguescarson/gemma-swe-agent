# v10 design C: spec extraction first

Author: architect C. Date: 2026-09-28. Status: design only. Nothing was built in the repo, pushed, submitted or spent;
no pod was started. This file replaces the earlier draft of design C from a previous run of this workflow (kept at
`<scratchpad>/design_C.prev.md`); section 14 lists what changed and why.

Inputs read for this design: `research/harness_runtime.md` (all sections), `research/config_space.md` (0-14),
`research/own_data.md` (0-11), `research/time_model.md` (0-9), `research/task_catalog.md` (1-5),
`research/test_plan.md` (0, F1-F12), `research/forum.md` (1-3), `research/competitors.md` (0-5),
`research/literature.md` (0, 2.11-2.12, 3, 6), `research/pain_points.md` (0), the shipped bundle
`submissions/v9_eog/**`, `helpers_v9/*.py`, and the installed harness source under
`.venv/lib/python3.12/site-packages` (cited as `SP/...`).

New evidence gathered for this design (all offline, all reproducible):
- **Compile probe.** The exact agent tree, YAML, sampling configs and prompts of sections 2-3 were written to
  `<scratchpad>/v10c_probe/` and compiled with the official path (`scripts/validate.py`): `OK model=gemma-4-31b-it-qat-w4a16-ct`,
  six `LlmAgent` stages, tool lists as specified. The brace lint finds only `{problem_description}` and `{key?}`
  placeholders; the prompts contain 0 backticks; the COMMON block is byte-identical in the five working stages.
- **run_skill_script argument corruption, counted over every trace we have** (section 1, fact N1).
- **Graph-tool crash stage**: in e74_v3 both "Tool 'search_similar_code' not found" crashes came from the *locator*, whose
  tool list was `[run_command, read_file]` while the harness prompt advertised the graph tools (fact N3).
- **Docker pytest masking**: `SP/swegemma/harness/container_setup.py:968-1010` masks the `pytest` binary and
  `pytest/__main__.py` in the agent container when `enable_sandbox_testing=False`; `import pytest; pytest.main()` survives (fact N4).
- **Snapshot history**: task snapshots carry the full upstream history (rich_3935: 4,346 commits), but none of the 13
  local statements with `#N` or hex references resolved to a commit that names a gold file (fact N6).
- **Statement and gold statistics** over the 74 Kaggle-valid tasks (fact N7).

`<scratchpad>` = `/private/tmp/claude-501/-Users-carson-Projects/654244a3-b38c-45a0-96af-d7e5f0aac6ce/scratchpad`.
Everything not measured is marked UNVERIFIED.

Output locations: bundle `submissions/v10` (helpers only in `submissions/v10/skills/swe-tools/scripts/*.py`),
tests `tests/test_v10_*.py`, docs `docs/v10/`. `submissions/v9_eog` and `submissions/v4` are frozen.

---

## 0. One-screen summary

The problem statement is the upstream PR description, and the hidden tests are that PR's test changes. In the hidden
set the host additionally screened every task so that the failing tests "could have been gotten correct with the
information given" (forum 743817). So the statement *is* the test spec, written in prose. Our biggest loss bucket is
"right file, wrong or partial fix" (19 of 30 v9_eog losses; 13 of those 19 patches have fewer hunks than gold,
own_data 0 and 7.3). Design C attacks that bucket directly:

1. **SPEC stage.** The model writes a compact, machine-readable SPEC: `KIND`, `TITLE`, `NAMES` (each NEW or EXISTS),
   `MESSAGES` (exact quoted strings) and numbered `CLAIMS` (one testable behaviour per line). `spec.py` localises by
   identifiers (definitions, usages, inheritance into dependencies, title-word expansion), prints the related test
   file's import lines and one short test (the Konwinski first-place lesson), and saves the spec.
2. **Claim-structured repro, written before any fix.** One `# CLAIM n:` section per claim, each run in its own process on
   the original and on the edited tree. Partial fixes show up as "1/3 claims fixed". A repro that fails for its own
   reasons (NameError, missing module, a claim using another claim's variable) is reported as BROKEN, not as evidence.
3. **FIXER implements to the spec** through one reliable edit channel (`edit.py`, SEARCH/REPLACE in a `run_command`
   heredoc), checking claims, SIBLINGS (same removed code elsewhere) and SPEC GAPS (NEW names, parameters in every
   same-named def, runtime importability, exact messages).
4. **Deterministic gate** (`gate.py`) decides `submit | repair | implement | retry` from claims, compile/import,
   regression (grader-parity pytest on original vs edited tree, SOFT/HARD), spec gaps, hygiene and the clock. One
   fresh-context retry (`fixer2` + `verifier2`) runs only when time remains; the final stage always submits the best
   checkpoint.

Agent tree (SequentialAgent root, six LlmAgent stages, all `include_contents: none`):

```
swe_v10 (SequentialAgent)
  boot       run_skill_script(install.py) -> READY line                 2 calls   ~8 s on L4
  spec       SPEC -> spec.py -> show/probe -> repro (claims) -> PLAN    5-7 calls ~35 s
  fixer      show -> edit.py -> repro.py --check -> (fix claims/gaps)   5-9 calls ~35 s
  verifier   gate.py --round 1 -> submit | repair | implement | RETRY   2-4 calls ~15 s + gate
  fixer2     only after RETRY: repair or restart                        <=8 calls ~40 s
  verifier2  gate.py --round 2 -> restore best -> always submit         2-3 calls ~12 s + gate
```

Helper availability no longer depends on the model remembering one call: a one-purpose `boot` stage makes the
install call first; every helper self-installs the whole set when it is run through `run_skill_script`; every stage
carries `skills: [skills/swe-tools]` and a one-line recovery rule; installs go to the directory that
`python3 /tmp/swe/...` resolves to in **both** sandbox backends (subprocess rewrite and the scorer's Docker sandbox).

`eval_config`: `max_time_minutes 5`, `timeout_seconds 90`, `max_tool_calls 90`, `max_turns 150`. The per-task wall is
bounded by the same 5-minute cap as v4 with a shorter hang tail, so the whole-run wall cannot exceed v4's by more than
the +8% the orchestrator allows (section 9: worst case 10.49 h at N=120 versus v4's measured 10.4 h).

Honest expectation (section 10): local 28/74 (v9_eog) to about 34/74 (range 30-37); hidden 0.12 to about **0.16-0.17**
(9-10/58, range 0.12-0.21). The 0.30 target (18/58) is below 10% likely with a single 5-minute 31B stream.

---

## 1. Facts that bind the design, and the decision each forces

Numbered H1-H10 are the orchestrator's hard facts (verified in the cited reports); N1-N7 are new in this pass.

| # | Fact (source) | Decision in v10 |
|---|---|---|
| H1 | Kaggle-style compaction fires in-flow when the last prompt is >= 14,336 tokens and wipes an `include_contents: none` stage to its instruction; the post-invocation path can crash a workflow root (harness_runtime 5.4; config_space finding 4). The scorer's threshold is unresolved: README says 32,768, the host notebook 14,336 (forum 1.6). | Design for both: every stage stays under ~12k tokens typical (section 8) so neither compaction nor overflow happens; helper outputs are capped at 900-2,500 chars; all progress lives on disk (`$SWE/state.json`, spec, repros, checkpoints) and `gate.py --status` rebuilds a stage after a wipe. The last stage always ends with `submit_patch` + text, so the harness breaks out before the post-invocation compaction path. |
| H2 | Any exception other than timeout/turn-limit discards the patch, including a submitted one; overflow at 28,673 prompt tokens with `max_output_tokens` 4,096 scored 0 in 38/38 runs; a runaway to 4,096 costs ~110-117 s on L4 (harness_runtime 1; own_data 0; time_model 3). | `max_output_tokens` 256 / 1,536 / 2,048 / 1,024 by stage (overflow line moves to >= 30,720); worst-case stage prompt ~17k. Every harness tool that any stage could name is attached to every stage (N3). Brace lint on all prompts. |
| H3 | `/tmp` in command text is rewritten to `<sandbox>/tmp` in the subprocess backend; skill scripts must use TMPDIR; in race 1 the helpers were missing in ~40% of tasks because install was one remembered call (harness_runtime 2.3; own_data 5; time_model 7.1). The host says the scorer uses a **private Docker sandbox** (forum 742882), where nothing is rewritten and only `TEST_TMPDIR=/tmp` is set (`SP/swegemma/sandbox/docker.py:93`). | `boot` stage; self-install from any skill call; recovery rule and `skills:` in every stage. Install targets: `$TMPDIR/swe` (or `tempfile.gettempdir()/swe`) **and**, outside the subprocess sandbox, `/tmp/swe`, so `python3 /tmp/swe/x.py` resolves in both backends even if a Docker image sets TMPDIR elsewhere. At runtime a helper takes its state directory from its own `__file__`, never from a literal. |
| H4 | `edit_file`: 18-22% of calls arrive with corrupted keys, 39-52% fail on a missing `old_string`; tool results are JSON-encoded twice; `run_command` keeps the first 5,000 chars of stdout and stderr with no marker; the test-file reset in verification is a no-op; the repo is not pip-installed in the subprocess sandbox (harness_runtime 3, 7.2, 2.5). | The only edit channel is `edit.py` through a `run_command` heredoc (one string argument; 0/1,001 and 0/1,252 corrupted). Every helper exits 0, prints its verdict first and stays far below 5,000 chars. Protected files are reverted by every mutating helper; scratch is removed by the gate. Helper test runs mirror the grader (`PYTHONPATH=<root>`, `PYTHONSAFEPATH=1`, harness `pytest.ini`). |
| H5 | A SequentialAgent stage ends on its first text-only reply; a nudge restarts from stage 1; the first `submit_patch` + text anywhere ends the task; budgets are per task (harness_runtime 5-6). | "Each reply is one tool call or the final text." Handoffs through `output_key` + disk. `install.py` prints RESUME on a restart and the stages short-circuit. Only the two verifiers attach `submit_patch`; `verifier2` always submits. |
| H6 | Hidden tasks take ~1.9x the public ones and v4 ran most of them to the cap; v10's whole-run wall may be at most ~+8% over v4; decode is 90-97% of agent time: ~1.4 s per step + ~35 ms per output token (own_data 2; time_model 2, 5). | Same 5-minute cap. `timeout_seconds` 90 (< v4's 180). Output tokens are the budget: no example duplicated between SPEC and repro, stage replies capped at 60-120 words, no re-reads (numbered views; plan in state). Helpers print `t=` and time-driven NEXT lines (section 6). |
| H7 | "Right file, wrong or partial fix" = 19 of 30 losses; ~15-19 of 74 tasks unreachable from the statement; every capped/overflowed run scored 0; +-3 tasks run-to-run noise; union of 14 runs 38/74 vs best single 28 (own_data 0, 9). | Claim-structured repro + spec gaps + siblings make partial fixes visible; the gate turns "partial" into a targeted repair or a retry; checkpoints keep the best state; the time discipline turns capped runs into gated submits. |
| H8 | Ranked levers (task_catalog 4). | Mapped one-to-one in section 10's table. |
| H9 | Parallel candidates are expressible but tools serialise, budgets are shared and KV headroom at gmu 0.80 is unmeasured (config_space 7; time_model 4). | Not used. Concurrency only inside helpers (claims and trees run as concurrent subprocesses). |
| H10 | Carson's standing rules: a regression test per bug, stdlib only, fastest correct primitive, timing budgets asserted, `bash -n`/shellcheck/`py_compile`/`scripts/validate.py`/`scripts/linux_test.sh` before shipping. | Section 12 (registry) and 13 (build and ship gate). |
| N1 | **`run_skill_script` corruption, all traces.** e74_v2 (prompt showed the install call wrapped in backticks): 94/107 calls INVALID_ARGUMENTS, 72 of them with a backtick-closed `file_path` (`install.py`,skill_name:`), 21 with empty args. race 1 v9 arms: 22-28 OK of 25-32 calls per arm; failures are quoted values (`"install.py"` -> NOT_FOUND, 1-4 per arm), backtick closes (0-3) and `":"`/`{}` garbage. e74_v3: 44/46 OK. Mechanism (pain_points 0.1): the gemma4 template sorts parameters (`file_path` < `skill_name`), and a string closed with a backtick swallows the next argument. | No backticks anywhere in prompts or SKILL.md; every tool call and command is shown on its own line in plain text; the install call is shown in template order `run_skill_script(file_path="install.py", skill_name="swe-tools")`; boot repeats it once on error. |
| N2 | **The v9 locator skipped install in 20 of 24 no-helper tasks by calling `run_command` first** (test_plan F2); prompt-stated call caps are ignored (locator 19.4 calls vs "at most 8", own_data 6). | Install is its own stage with nothing else to do; stage length is steered by helper `NEXT:` lines and the clock, not by prompt caps. |
| N3 | **Unattached tool = crash.** e74_v3 rich_4076 and fastapi_14419: the locator (tools `[run_command, read_file]`) called `search_similar_code`, advertised by the harness prompt (`SP/swegemma/harness/agent_runner.py:163-172`), and the task was lost. When attached, graph tools were called in 4/51 (r_v9_eog) and 12/51 (r_v4) tasks, max result 11,245 chars; a competitor saw 136k chars for one class (competitors 4). | All eight non-submit harness tools on every stage (boot sees the harness prompt); COMMON says never call the graph tools. The residual risk (a voluntary call returning a huge result) is listed in section 11. |
| N4 | **pytest can be masked in the agent sandbox.** With `enable_sandbox_testing=False` (default True; scorer value UNVERIFIED) the Docker agent container gets a failing `pytest` shim and a failing `pytest/__main__.py`; `unittest` stays (`container_setup.py:968-1010`); the harness prompt then tells the model tests are disabled (`agent_runner.py:130-133`). | The gate runs pytest in-process: `python3 -s -c "import sys,pytest; sys.exit(pytest.main(sys.argv[1:]))" ...`. Repros never need pytest. |
| N5 | **Validation is outside the 12 h** and takes ~2 h (host, forum 743663); the public board has 58 tasks and truncates (forum 743506). The verification pytest uses `timeout_seconds` (`SP/swegemma/harness/verification.py:498-503`). | `timeout_seconds` only affects agent-side raw hangs and the pass/fail risk of slow hidden test files; 90 s balances both (section 2.3). |
| N6 | **Snapshots carry full history** (rich_3935: 4,346 commits), but in the 13 local statements with `#N` or hex references none resolved to a commit touching a gold file (issue numbers are not in merge messages; `7a38204` in rich_3718 is not in the snapshot). | Hex refs are resolved best-effort (bounded, silent when absent); issue numbers are never searched. No lever is credited to history. |
| N7 | **Statements and gold patches (74 valid tasks).** Statement length median 468 chars, p95 2,455, max 10,095. Code blocks in 12/74 (median 23.5 lines); backticked identifiers in 31/74; quoted strings of >= 8 chars in 23/74. Gold patches touching > 1 def/class 31/74; >= 3 hunks 25/74. 0/129 gold source patches touch tests, conftest, pytest.ini, pyproject.toml, setup.cfg or tox.ini; 0/129 add a root-level `.py`. | Repros are usually constructed from prose (only 12/74 have an example to copy), so CLAIMS carry the spec. Completeness checks matter in ~40% of tasks. Reverting protected-file edits and deleting root-level scratch `.py` cost nothing on public data. |

Rejected alternatives: an `LlmAgent` coordinator root (immune to the post-invocation compaction crash and the nudge
restart, but every hop needs a correct `transfer_to_agent` call and it was never scored); `LoopAgent[fixer, verifier]`
(no early exit, and its last iteration cannot be told "always submit", config_space 9); `ParallelAgent` candidates (H9);
`AgentTool` (no compaction inside, `skip_summarization` ends the caller's turn, config_space 10); thinking on (budget
never enforced, config_space 2); a cap above 5 minutes (fails at N=130, time_model 5).

---

## 2. Agent tree, exact YAML, eval_config, sampling

Only constructs that config_space compiled and ran: SequentialAgent root (case 03, runtime R6), LlmAgent with
`include_contents: none` + `output_key` (case 20), one skill shared by several agents (case 56), `!include` of `.md`
and `.yaml` (case 96), `generate_content_config` with `temperature/top_p/top_k/max_output_tokens/thinking_config.include_thoughts`
(cases 60, 77, 82; R1d). No callbacks (ignored), planners, `global_instruction`, `thinking_level` or `seed` (dead).

### 2.1 Files

`submissions/v10/agent.yaml`
```yaml
name: swe_v10
agent_class: SequentialAgent
description: Spec first, then fix, gate, and one gated retry.
sub_agents:
  - config_path: sub_agents/boot.yaml
  - config_path: sub_agents/spec.yaml
  - config_path: sub_agents/fixer.yaml
  - config_path: sub_agents/verifier.yaml
  - config_path: sub_agents/fixer2.yaml
  - config_path: sub_agents/verifier2.yaml
```

`submissions/v10/eval_config.yaml`
```yaml
evaluation:
  max_time_minutes: 5
  timeout_seconds: 90
  max_tool_calls: 90
  max_turns: 150
```

Stage files (all identical in shape; `T8` = `[run_command, read_file, edit_file, write_file, get_status, get_code_neighbors, search_similar_code, get_code_subgraph]`):

| file | name | description | tools | output_key | generate_content_config |
|---|---|---|---|---|---|
| `sub_agents/boot.yaml` | boot | Installs the team's helper scripts. | T8 | none | `configs/gen_boot.yaml` |
| `sub_agents/spec.yaml` | spec | Turns the issue into an exact spec, a failing repro and the places to change. | T8 | `plan` | `configs/gen_spec.yaml` |
| `sub_agents/fixer.yaml` | fixer | Implements the plan claim by claim. | T8 | `fix_notes` | `configs/gen_fix.yaml` |
| `sub_agents/verifier.yaml` | verifier | Runs the gate, then submits, repairs or asks for a retry. | T8 + `submit_patch` | `verdict` | `configs/gen_judge.yaml` |
| `sub_agents/fixer2.yaml` | fixer2 | Second attempt after a failed gate. | T8 | none | `configs/gen_fix.yaml` |
| `sub_agents/verifier2.yaml` | verifier2 | Final gate; always submits. | T8 + `submit_patch` | none | `configs/gen_judge.yaml` |

Every stage file has exactly these keys (example, `spec.yaml`, as compiled in the probe):
```yaml
name: spec
model: gemma-4-31b-it-qat-w4a16-ct
description: Turns the issue into an exact spec, a failing repro and the places to change.
include_contents: none
instruction: !include ../prompts/spec.md
tools: [run_command, read_file, edit_file, write_file, get_status, get_code_neighbors, search_similar_code, get_code_subgraph]
skills: [skills/swe-tools]
output_key: plan
generate_content_config: !include ../configs/gen_spec.yaml
```

Bundle layout:
```
submissions/v10/
  agent.yaml  eval_config.yaml
  configs/   gen_boot.yaml gen_spec.yaml gen_fix.yaml gen_judge.yaml
  sub_agents/ boot.yaml spec.yaml fixer.yaml verifier.yaml fixer2.yaml verifier2.yaml
  prompts/   boot.md spec.md fixer.md verifier.md fixer2.md verifier2.md
  skills/swe-tools/SKILL.md
  skills/swe-tools/scripts/ _common.py _index.py install.py spec.py show.py edit.py repro.py probe.py gate.py run.py
```
No `.sh`, dotfiles, `__pycache__` or symlinks (config_space 8). No script stem is in `sys.stdlib_module_names`.

### 2.2 Sampling

| config | temperature | top_p | top_k | max_output_tokens | include_thoughts | used by |
|---|---|---|---|---|---|---|
| gen_boot | 0.3 | 0.95 | 64 | 256 | false | boot |
| gen_spec | 1.0 | 0.95 | 64 | 1,536 | false | spec |
| gen_fix | 1.0 | 0.95 | 64 | 2,048 | false | fixer, fixer2 |
| gen_judge | 0.7 | 0.95 | 64 | 1,024 | false | verifier, verifier2 |

Why: explore stages keep the values that scored 0.12 (v4) and 21/51 (v9_eog) and that Google recommends for Gemma 4
(T 1.0 / 0.95 / 64, literature 5); the retry benefits from their diversity. Boot copies one literal call, so a low
temperature reduces malformed arguments (N1 failures are sampling noise). Judges follow deterministic NEXT lines;
0.7 rather than 0.2 because a rival measured 13.5 verbatim repeats per task at 0.2 against 5.1 at 0.7 with the same
resolve rate (pain_points 0.5). `seed` is not forwarded (config_space 1) and `thinking_level` is omitted (a typo would
silently enable thinking, config_space 2). Output caps: no tool call in the L4 runs exceeded 2,048 tokens (time_model 3);
p99 completion is 731 tokens (own_data 10.3); a runaway text reply now costs at most ~44-58 s (1,536-2,048 tokens)
instead of ~117 s, and the prompt ceiling rises to >= 30,720 tokens.

### 2.3 eval_config values

| key | value | why |
|---|---|---|
| `max_time_minutes` | 5 | The only 12 h safety knob; 5.25 already fails at N=130 (time_model 5). |
| `timeout_seconds` | 90 | Per-command cap in the agent and the verification pytest timeout (N5). Every helper's internal timeout is <= 60 s, so 90 only binds raw commands the model runs itself; 90 halves v4's 180 s raw-hang tail. It keeps a 7x margin over the slowest public verification (12.6 s, time_model 1.2) for unknown private test files. 60 would cut 30 s more per raw hang but raises the risk that a slow hidden test file fails a correct patch; 300 (forum 2.2) would let one raw hang eat the whole task. |
| `max_tool_calls` | 90 | Happy path ~20 calls, retry path ~35; a loop brake only. `submit_patch`/`get_status` are free. |
| `max_turns` | 150 | v4/v9 value. At ~1.5-3 s per turn the 300 s cap binds first except in malformed-call spirals. |

---

## 3. Prompts (full text) and prompt-writing rules

### 3.1 Rules every prompt obeys (each is a lint in the registry)

1. No backticks anywhere (N1). Tool calls and commands are shown on their own line, in plain text.
2. Tool-call examples list arguments in the chat template's order (alphabetical), e.g.
   `run_skill_script(file_path="install.py", skill_name="swe-tools")`.
3. Only `{problem_description}`, `{plan?}`, `{fix_notes?}`, `{verdict?}` may appear in braces; no f-strings, dict
   literals or any other `{...}` in examples (a missing state key raises KeyError and loses the task, config_space 10).
4. Every helper and flag named in a prompt exists (checked against each helper's exported `FLAGS`).
5. Every tool named in a prompt is attached to that stage or provided by its skill toolset.
6. Stage replies are bounded in words; each stage says when to stop in `t=` seconds that match the helper constants.
7. Heredocs use `<<'EOF'` (quoted, no shell expansion); SEARCH/REPLACE markers are the conventional seven characters.
8. The COMMON block is byte-identical in the five working stages.

Static sizes (chars; tokens ~ chars/3.6): boot 528 (~150), spec 4,073 (~1,130), fixer 3,610 (~1,000),
verifier 1,990 (~550), fixer2 2,332 (~650), verifier2 1,782 (~500), COMMON (included) 1,188 (~330).

### 3.2 `prompts/boot.md`
```
You are BOOT, stage 1 of 6. Your only job is to install the team's helper scripts. Later stages solve the issue.

Make exactly this one tool call now, with no text before it:
run_skill_script(file_path="install.py", skill_name="swe-tools")

If it returns an error, make the same call once more, written exactly as above: the two values are plain words with no extra quotes.
Then reply with only the first line it printed (it starts with READY or RESUME) and stop.
Do not run commands, read files, edit files or submit anything.
```

### 3.3 COMMON block (appended verbatim to spec, fixer, verifier, fixer2, verifier2)
```
RULES FOR EVERY STAGE
- Each reply is exactly one tool call with no text before it, or your final text reply. A text reply ends your stage.
- The helpers live in /tmp/swe and run with run_command. If a helper prints "can't open file", call run_skill_script(file_path="install.py", skill_name="swe-tools") once, then repeat the command.
- Read code with show.py, which numbers the lines. Change code only with edit.py. Do not use edit_file or write_file: their arguments get corrupted on this server.
- Run any other command that may print a lot or may hang as: python3 /tmp/swe/run.py --timeout 20 "the command"
- Never repeat a call that already returned. Never call get_code_neighbors, search_similar_code or get_code_subgraph. No other tools exist.
- Never create or edit tests, conftest.py, pytest.ini, pyproject.toml, setup.cfg or tox.ini, and keep scratch files out of /workspace: the grader replaces the tests, and every file left in /workspace becomes part of the patch.
- The first line of every helper ends with t=<seconds used>. All six stages share 300 seconds.
- If you lose track (for example because the conversation was summarized), run: python3 /tmp/swe/gate.py --status
```

### 3.4 `prompts/spec.md` (followed by COMMON)
```
You are SPEC, stage 2 of 6. You change no source file. You turn the issue into an exact spec, a repro that fails on the current code, and the places to change. The fixer implements your plan next.

ISSUE (a pull-request description; the hidden grading tests come from the same pull request):
{problem_description}

If the line from BOOT starts with RESUME, run python3 /tmp/swe/gate.py --status, reply with a PLAN built from it, and skip the steps below.

STEP 1. Write the spec. spec.py saves it and searches the repository for every name in it:
python3 /tmp/swe/spec.py <<'EOF'
KIND: bugfix or feature or refactor or docs
TITLE: the first line of the issue, verbatim
NAMES: every function, Class.method, parameter written as func(param=), attribute, constant, env var or file the change adds or touches, each followed by NEW or EXISTS
MESSAGES: each exact output or error text the issue quotes, one per line in double quotes, or none
CLAIMS:
1. input or situation -> exact expected result
2. one line per separate behaviour the issue asks for; two linked issues are at least two claims
EOF
If the issue is only a title plus links or a checklist, the title is the spec: turn each title word into code names (proxy -> a class named *Proxy, padding width -> *padding_width*) and list them as NAMES. Never search for issue numbers or URLs.

STEP 2. Open the top candidate that spec.py lists, for example:
python3 /tmp/swe/show.py path/to/file.py::Name
If spec.py marks a name NOT IN REPO or INHERITED, it lives in a dependency: run the probe.py command it prints to see the installed source. If two functions compute the same thing (measure and render, sync and async, a sibling handler), open both and note which one is wrong.

STEP 3. Write the repro: imports first, then one section per CLAIM that starts with a line # CLAIM n: and asserts the expected result, so that it FAILS on the current code:
python3 /tmp/swe/repro.py <<'EOF'
from package.module import Thing
# CLAIM 1: short description
result = Thing().method("input from the issue")
assert result == "expected value", repr(result)
EOF
Import names the way the TESTS line of spec.py shows. Copy the issue's own example when it has one. Assert exact text only when the issue states it. For width, split or round-trip functions, loop over every position or boundary input instead of one example. For a hang, just call the code: repro.py reports HANG. If a claim PASSES at base it misses the bug: rewrite the repro once with another reading (add --id 1 --replace). If repro.py says the repro itself is BROKEN, fix the repro.

STEP 4. Stop calling tools and reply with the PLAN, under 120 words:
FILES: path:start-end for every place to change
CAUSE: one sentence
CHANGE: what to add or modify for each claim, with the exact NAMES and MESSAGES
REPRO: which claims fail now, or NONE
Reply by t=100 at the latest, even if unsure.
```

### 3.5 `prompts/fixer.md` (followed by COMMON)
```
You are FIXER, stage 3 of 6. Implement the plan now: the smallest complete source change that makes every claim true.

ISSUE:
{problem_description}

PLAN from SPEC:
{plan?}

The spec and the repro are saved on disk; python3 /tmp/swe/spec.py --show prints them. If the PLAN above is empty, run spec.py yourself first, as SPEC would.

STEP 1. View the lines you will change:
python3 /tmp/swe/show.py path/to/file.py::Name

STEP 2. Edit with edit.py. Copy 2 to 6 lines exactly from show.py, without the number column, into SEARCH, and write the new lines into REPLACE:
python3 /tmp/swe/edit.py path/to/file.py <<'EOF'
<<<<<<< SEARCH
    def flush(self) -> None:
=======
    def isatty(self) -> bool:
        return self.__file.isatty()

    def flush(self) -> None:
>>>>>>> REPLACE
EOF
Several blocks may follow each other in one call. For a new file add --create. If edit.py reports SEARCH not found twice, replace by line numbers from your last show.py view: python3 /tmp/swe/edit.py path/to/file.py --lines 120-135 <<'EOF', then the new lines, then EOF. edit.py syntax-checks every edit and undoes a broken one.

STEP 3. Check:
python3 /tmp/swe/repro.py --check
It runs every claim on your version and on the original code, and lists SIBLINGS (other places that still contain the code you changed) and SPEC GAPS (names or messages of the spec that your change lacks).
- A claim that still FAILS: read its error, fix, and check again, at most three rounds.
- SIBLINGS: fix each the same way unless it clearly differs. SPEC GAPS: add what is missing.
- NO REPRO: re-read the ISSUE and make sure every point of CHANGE is done.

Rules: use exactly the spec's NAMES and MESSAGES; follow the neighbouring code's idiom (assert or raise, message wording, keyword-only parameters with safe defaults); thread a new parameter through every overload, wrapper and caller; fix the shared function every caller goes through rather than one caller; copy a shared list or dict before mutating it; when behaviour comes from a dependency, read its source with probe.py --src; to see what an object really is, run a snippet with python3 /tmp/swe/repro.py --py <<'EOF' instead of guessing. "No change needed" is never right: the hidden tests fail on the current code.

STEP 4. Stop calling tools and reply, under 80 words:
CHANGED: file:function for each edit
CLAIMS: how many pass now, for example 2/3, or NONE
Reply by t=210 at the latest.
```

### 3.6 `prompts/verifier.md` (followed by COMMON)
```
You are VERIFIER, stage 4 of 6. Do not investigate again: run the gate and do what its NEXT line says.

ISSUE:
{problem_description}

PLAN: {plan?}
FIXER: {fix_notes?}

1. python3 /tmp/swe/gate.py --round 1
2. Follow its NEXT line:
- NEXT: submit -> call submit_patch, then reply with one sentence. The gate has already cleaned the diff.
- NEXT: repair ... -> make that one change with edit.py (run show.py first if you need the lines), then run python3 /tmp/swe/gate.py --round 1 again.
- NEXT: implement ... -> make the change described there with edit.py, then run the gate again.
- NEXT: retry -> reply with the word RETRY followed by the gate's REASON line, and stop without calling submit_patch. A fresh fixer will try again.
Never call submit_patch after an edit that the gate has not checked.
```

### 3.7 `prompts/fixer2.md` (followed by COMMON)
```
You are FIXER 2, stage 5 of 6: the second and last attempt. The first attempt was checked and failed.

ISSUE:
{problem_description}

PLAN from SPEC:
{plan?}

FIRST ATTEMPT: {fix_notes?}
WHY IT FAILED: {verdict?}

STEP 1. Run python3 /tmp/swe/gate.py --status to see the first attempt's diff and which claims fail. If it shows t=240 or more, or the last gate verdict PASS, reply DONE now.
STEP 2. Choose one:
- REPAIR when the place is right but the logic is wrong or incomplete: change it with edit.py.
- RESTART when the place or the reading of the issue was wrong: python3 /tmp/swe/gate.py --revert restores the original code (the first attempt stays saved); then implement a different reading of the spec.
Editing works as before: python3 /tmp/swe/edit.py path/to/file.py <<'EOF' with SEARCH and REPLACE blocks, --lines A-B when SEARCH fails twice, --create for a new file, and show.py to view numbered lines.
STEP 3. Run python3 /tmp/swe/repro.py --check and fix every failing claim, SIBLING and SPEC GAP it lists.
STEP 4. Reply, under 60 words: CHANGED: ... and CLAIMS: ... Reply by t=265 at the latest; after that edit.py refuses edits.
```

### 3.8 `prompts/verifier2.md` (followed by COMMON)
```
You are the FINAL VERIFIER, stage 6 of 6. You always end the task by submitting.

ISSUE:
{problem_description}

PLAN: {plan?}

1. python3 /tmp/swe/gate.py --round 2
   It keeps the better of the two attempts, cleans the diff and prints NEXT.
2. NEXT: submit -> call submit_patch, then reply with one sentence.
   NEXT: implement ... (only when neither attempt changed any source file) -> make that smallest plausible edit with edit.py, run python3 /tmp/swe/gate.py --round 2 again, then call submit_patch.
Always call submit_patch before your final reply, even when the gate reports failures.
```

### 3.9 `skills/swe-tools/SKILL.md`
```
---
name: swe-tools
description: Helper scripts for resolving an issue in the repository at /workspace (spec search, numbered views, safe edits, claim-by-claim repro, regression gate). Install with run_skill_script(file_path="install.py", skill_name="swe-tools"), then run them with run_command as python3 /tmp/swe/NAME.py.
---
# swe-tools
Install: run_skill_script(file_path="install.py", skill_name="swe-tools"). Any helper run through run_skill_script installs all of them.
- python3 /tmp/swe/spec.py (SPEC on stdin) | --show | --query WORDS
- python3 /tmp/swe/show.py FILE::Name | FILE START END | FILE
- python3 /tmp/swe/edit.py FILE (SEARCH/REPLACE blocks on stdin) | --lines A-B | --create | --revert
- python3 /tmp/swe/repro.py (claim sections on stdin) | --check | --py | --id K --replace
- python3 /tmp/swe/probe.py --src dotted.name | --where Name | --mro dotted.Class
- python3 /tmp/swe/gate.py --round 1|2 | --status | --diff | --revert
- python3 /tmp/swe/run.py --timeout 20 "command"
```

---

## 4. The spec protocol

### 4.1 SPEC grammar (parsed by `spec.py`, tolerant)

- Keys, case-insensitive, optional leading `-`/`*`/`#` and surrounding backticks or bold: `KIND`, `TITLE`, `NAMES`,
  `MESSAGES`, `CLAIMS` (aliases: `BEFORE`/`AFTER`/`BUGS`/`EXAMPLE` are accepted and folded: BEFORE+AFTER become claim 1,
  BUGS is kept as a count, EXAMPLE is ignored with a note "put examples in the repro").
- `NAMES`: comma- or newline-separated items. An item is an identifier, dotted name, `func(param=)`, `ENV_VAR`, a
  path, or a quoted string; a trailing `NEW`/`EXISTS` (also `EXISTING`, `(new)`, `-> new`) tags it; untagged means
  EXISTS. Backticks and trailing `()` are stripped.
- `MESSAGES`: every double- or single-quoted run of >= 3 chars on the MESSAGES lines; `none` means none.
- `CLAIMS`: numbered lines `N.` or `N)` or `-`; continuation lines are appended to the last claim; at most 8 kept.
- CRLF, tabs, extra prose and missing keys are tolerated; nothing is ever fatal. The parsed spec is saved to
  `$SWE/spec.json` and `$SWE/spec.txt` (the raw text) and `spec.py --show` prints it back (<= 1,200 chars).

### 4.2 Localisation by identifiers (`spec.py`, section 5.4 gives the full contract)

For each NAME: exact definition lookup in the AST index (def, async def, class, method via its class, parameter,
module-level constant); usage count from one batched `git grep -n -w -I -F -f <patterns>` over tracked `*.py`;
`INHERITED from <dotted base>` when `Class.method` is looked up and the class is in the repo but the method comes from
an external base (bases resolved through the file's imports); `NOT IN REPO` when neither a definition nor a usage exists.
For NEW names the container is localised instead (the class of a NEW method; the module of a NEW function named like
existing siblings; the function of a NEW parameter). Title words (stop-words removed) expand into candidates: the word,
snake-joins of adjacent words, CamelCase, and case-insensitive substring matches over class/def names; issue numbers,
`#NNN`, URLs and 7-40-hex tokens are never searched as identifiers (hex tokens are resolved separately, N6).

### 4.3 Claim-structured repro

```
<prelude: imports and shared setup>
# CLAIM 1: <text>
<statements, usually ending in an assert>
# CLAIM 2: <text>
...
```
- No `# CLAIM` header: the whole script is claim 1.
- Each claim runs as `prelude + section` in its own `python3 -s` process (cwd `$SWE/cwd`, grader env, default 10 s,
  max 60 s), so one failing claim never masks another; claims and trees run concurrently (<= min(8, cpu_count) workers).
- Result per claim and tree: PASS (exit 0), FAIL (last exception line + last 6 output lines), HANG (timeout, killed).
- **BROKEN** (the repro, not the code, is wrong) when the failure is: `SyntaxError`/`IndentationError` in the repro;
  `NameError` raised in a frame of the repro file (with the hint "claim 2 uses a name defined in another claim: put
  shared code before the first # CLAIM line" when that name is assigned in another section); `ModuleNotFoundError` for a
  top-level module that is neither in the repo nor installed. A BROKEN claim is never evidence.
- A claim that PASSES at base is INVALID for flip purposes (it misses the bug) and is reported with the hint to rewrite.
- Failures at base on an ImportError/AttributeError/TypeError that names a NEW spec name are valid ("fails because X
  does not exist yet"); on a name that is neither NEW nor defined in the repo they are flagged "check the repro imports".
- `--check` verdict per claim: FIXED (fail/hang at base, pass now), STILL FAILS, STILL HANGS, BROKE (passed at base,
  fails now), INVALID (passes at base), BROKEN. Summary `k/n claims fixed` over valid claims.

### 4.4 Spec gaps (library, printed by `repro.py --check` and `gate.py`)

From `spec.json`, one driver subprocess on the current tree (grader env, 10 s):
- NEW `name`: defined in a non-test source file (index) and importable from its defining module (`getattr(import_module(m), name)`).
- NEW `Class.method` / attribute: `hasattr(Class, method)` after import.
- NEW `func(param=)`: `param in inspect.signature(obj).parameters` for **every** def with that name in the repo
  (overloads, subclasses, wrappers found through the index), each missing one listed.
- NEW env var / constant / quoted name: the literal occurs in a non-test source file.
- MESSAGE: the literal occurs in a non-test source file, or its longest constant fragment of >= 12 chars does
  (f-string templates).
- CLAIMS/BUGS: `n valid claims but the diff changes 1 function` note when n >= 2 and one def is changed.
Each miss is one `SPEC GAP:` line (<= 6). EXISTS names are never gaps.

### 4.5 Sibling sweep (library)

From `git diff -U0 <base_ref>` of changed non-test `.py` files: removed lines (stripped, >= 12 chars, not comments,
docstring fragments or bare brackets) and the call expressions inside them (`[\w.]+\([^()]{4,40}` of >= 16 chars) are
searched with one `git grep -n -F -f` over tracked non-test `*.py`; hits inside the diff's new hunks are dropped; at most
8 `SIBLING path:line: code (same code as your change at path:line)` lines. Advisory: the gate prints them, never blocks.

### 4.6 Title-plus-link protocol and dependency rule (task_catalog levers 4, 7, 9)

- Title-only statements (27/74 public): the prompt tells the model to translate title words into code names;
  `spec.py` also expands TITLE words itself (4.2) and prints `TITLE MATCHES`. It prints the last 2 commits of the top
  candidate file (`git log -2 --format="%h %ad %s" --date=short -- <file>`, 1 s cap) as a regression hint.
- "Two paths compute the same thing" is a prompt rule (spec STEP 2) plus a helper hint: when two candidate defs in one
  module share >= 3 identifier tokens with the title, both are listed with `COMPARE:`.
- Dependency source: a NAME that is NOT IN REPO or INHERITED prints the exact `probe.py --src <dotted>` command, and for
  the first such name spec.py runs it inline (15 s cap) and shows <= 20 numbered source lines.
- Runtime ground truth: `repro.py --py` runs a snippet in the grader env (print `type(x).__mro__`, `.metadata`, `__file__`).

---

## 5. Helper suite (contracts)

Global contract for every helper: stdlib only; Python 3.10-3.13; exits 0 on every path (a non-zero `SystemExit`
becomes an ADK error under `run_skill_script`); the first line is the status line and ends with `t=NNNs`; output
capped per helper with head/tail truncation and a `[... N lines cut; full text: /tmp/swe/last.log]` marker; the full
output is written to `$SWE/last.log`; every child runs with `start_new_session=True`, `stdin=DEVNULL` and is killed as
a process group on timeout; `PYTHONDONTWRITEBYTECODE=1` for children; no network modules; the workspace is modified
only by `edit.py`, `gate.py --round/--revert`, the protected-file revert, and T_SAFE auto-restore.
Every option is accepted as `--key value` and stdin content can be given as `--text "<content>"`, so
`run_skill_script(file_path="gate.py", skill_name="swe-tools", args={"round": "1"})` works too (and self-installs).
Each helper exports `FLAGS = {...}` for the prompt lint.

### 5.1 `_common.py` (library; import cost <= 30 ms)

- **Import discipline**: the first statements are `import sys, os`; then `sys.path` is stripped of `''`, the cwd and
  every entry that came from `PYTHONPATH`, and the helper's own directory is inserted at 0; only then are other stdlib
  modules imported. This makes helpers immune to a workspace module named like a stdlib module (`signal.py`,
  `secrets.py`, `types.py`) and to `PYTHONSAFEPATH=1`. Children that must import the repo get `PYTHONPATH` explicitly.
- **SWE directory**: if `dirname(realpath(__file__))` contains `installed.json`, that directory is SWE (installed
  mode). Otherwise (running from the skill wrapper's temp dir) `self_install()` runs and SWE is the primary target.
- **Install targets**: primary `join(os.environ.get("TMPDIR") or tempfile.gettempdir(), "swe")`; secondary
  `join(DOCKER_TMP, "swe")` with `DOCKER_TMP = "/tmp"` only when the process is not in a swegemma subprocess sandbox
  (TMPDIR's parent directory name does not start with `swegemma_sandbox_`), the path differs from the primary and is
  writable. This is the only `/tmp` literal used as a path (lint whitelist, R-C15).
- `self_install()`: copies every sibling `*.py` into each target when size or mtime differ, atomically
  (`tmp` + `os.replace`), writes `installed.json` (`version`, `time`, file list); idempotent; <= 50 ms when current.
- `ws()`: `SWE_WS` env -> git top-level of cwd -> git top-level of `$PWD` (the skill wrapper keeps `PWD`) ->
  `state.ws` -> `/workspace` only if it contains `.git`. Never a non-git directory.
- `base_ref()`: `_swegemma_baseline` if `git rev-parse -q --verify refs/tags/_swegemma_baseline`, else `state.base_sha`
  (HEAD recorded at install). Diffs therefore survive an agent `git commit` (test_plan F5).
- **Clock** `t()`: origin = committer time of `base_ref` when `0 <= now - origin <= 900` (the baseline commit is the
  last setup step, `container_setup.py:575-582`; the agent session starts at `agent_runner.py:495`, 1-3 s later, so `t`
  is slightly conservative); else `state.install_time - 8`. Printed as `t=NNNs`.
- **Constants** (single table; every helper reads them from here; all < `timeout_seconds` 90):
  `T_SPEC_REPLY 100`, `T_FIX_REPLY 210`, `T_RETRY_MAX 170`, `T_RESTART_MAX 200`, `T_FIX2_SKIP 240` (gate `--status`
  prints `reply DONE` from here on), `T_REPAIR_MAX 245`, `T_FAST_GATE 255`,
  `T_SAFE 255`, `T_EDIT_REFUSE2 265`, `T_GATE_END 292`, `GATE_BUDGET 60`, `PYTEST_TIMEOUT 30`, `IMPORT_TIMEOUT 10`,
  `REPRO_TIMEOUT 10` (max 60), `PROBE_TIMEOUT 15`, `RUN_TIMEOUT 20` (max 60),
  `CAPS = {install 400, spec 2000, show 2000, edit 900, repro 1200, check 1400, py 1200, probe 1800, gate 1600, status 1000, run 2500}`.
- `run(cmd, timeout, cwd, env)`: `Popen(start_new_session=True, stdin=DEVNULL)`, `communicate(timeout)`, on timeout
  `os.killpg(SIGKILL)` and reap; reads capped at 2 MB per stream; decoded `errors="replace"`; returns `(rc, out, err, timed_out)`.
- `emit(status, body, cap, next_line=None)`: status first, body truncated head/tail, NEXT last, total <= cap.
- `grader_env(root)`: `PYTHONPATH=<root>` (plus `<root>/src` first when the package lives there), `PYTHONSAFEPATH=1`,
  `PYTHONNOUSERSITE=1`, `PYTHONDONTWRITEBYTECODE=1`; `PATH/HOME/TMPDIR/LANG` kept (mirrors `subprocess.py:483-501`
  and `verification.py:493`).
- `read_stdin()`: returns `''` when stdin is a TTY or `select` reports nothing readable within 0.3 s; otherwise reads
  all; strips `\r`, a trailing line matching `^\s*EOF\W*$` and a trailing backtick (a dropped heredoc delimiter,
  pain_points 0.1).
- `unrewrite(text)`: in the subprocess sandbox only (TMPDIR ends in `/tmp` under a `swegemma_sandbox_*` parent),
  replaces `<sandbox>/tmp` and `<sandbox>/workspace` in heredoc content back to `/tmp` and `/workspace`.
- State: `$SWE/state.json`, atomic writes; keys `ws, base_sha, install_time, spec, repros, views, calls, checkpoints,
  gate{round, k, last_verdict, retry_issued, reason}`. A mismatch of `ws`/`base_sha` resets state, caches, repros and
  checkpoints (a reused `/tmp` in a long-lived container).
- `hygiene_light(root)`: tracked protected files changed versus `base_ref` are restored with
  `git checkout <base_ref> -- <paths>`; one `FIXED:` line each. Protected: `(^|/)(tests?|testing)/`, `test_*.py`,
  `*_test.py`, `conftest.py`, `pytest.ini`, `pyproject.toml`, `setup.cfg`, `tox.ini`, `*.pth`, `sitecustomize.py`,
  `usercustomize.py` (the verification list, `verification.py:60-83`). Called by `edit.py`, `repro.py --check`, `gate.py`.
- `hygiene_full(root, spec)`: light, plus deletion of untracked: files under test dirs, `test_*.py`, `*_test.py`,
  `conftest.py`; root-level `*.py` whose stem is not a NEW spec name; root-level `*.txt *.log *.out *.diff *.patch *.orig
  *.rej *.swp`; any path whose basename starts with `repro`, `reproduce`, `scratch` or `debug`; a new directory tree of
  > 20 files or > 200 kB unless a NEW name lives in it; a new top-level module that shadows a stdlib or installed
  distribution name. Called by `gate.py` and at T_SAFE.
- `source_diff(root)`: `git add -N .` then `git diff --binary <base_ref>`; classification into source / protected / scratch.
- Checkpoints: `save(score, verdict)` stores `$SWE/ckpt/<sha1>.diff` + metadata; `restore(sha)` is transactional
  (save current as a temp checkpoint, `git checkout <base_ref> -- <changed>`, remove created files, `git apply`, verify
  the new diff hash equals the checkpoint's, else roll back); `best()` by score (section 6.2).
- `auto_restore()`: at `t >= T_SAFE`, if the source diff is empty and a non-empty checkpoint exists, restore the best one
  and prefix the output with `RESTORED best checkpoint (claims 2/2, gate PASS)`. Called at the start of every helper.
- Loop memory: `state.calls[sha1(helper, args, stdin)] = count`.

### 5.2 `_index.py` (library)

- Files: `git ls-files -z -- '*.py'`, skipping files > 1 MB and vendored dirs (`site-packages`, `node_modules`, `.tox`,
  `build`, `dist`, `_vendor`, `vendor`); at most 6,000 files, non-test and non-docs first.
- Per file via `ast.parse`: defs and async defs (qualname, kind, lineno, end_lineno, parameter names, decorators,
  `@overload`), classes (qualname, dotted base text, method names), module-level assignment targets, imports
  (`name -> module`), BM25 token bag (v9 `locate.py` tokenizer: identifiers, camel/snake split).
- Cache: `$SWE/index.marshal` keyed by `(path, mtime_ns, size)`; only changed files reparse. Build budget 3 s per call
  (install starts, spec completes), then partial with `[index partial: N/M files]`.
- API: `find_name`, `glob_symbols`, `defs_named`, `resolve_import`, `bases_of`, `bm25`, `outline(path)`, `span(path, qualname)`.
- Path weights: tests x0.3; `docs?/ docs_src/ examples?/ benchmarks?/ scripts?/ tools?/` x0.5 unless KIND is docs or
  a NAME is defined there; vendored x0.2.

### 5.3 `install.py` (boot)

CLI: `install.py` (no args). Effects: `self_install()`; `state.json` (`ws`, `base_sha`, `install_time`); repo facts with
bounded probes (package dirs, flat/src layout, test dirs, python version, `import pytest` ok, import self-check
`python -c "import <pkg>; print(<pkg>.__file__)"` under `grader_env`, 5 s each); index build (3 s budget).
Output (<= 400 chars, the line boot copies):
`READY ws=/workspace pkgs=rich layout=flat tests=tests py=3.12.14 pytest=ok import=workspace t=6s`, with
`import=site-packages (WARNING: tests import the installed copy)` when the check fails, or on a restart
`RESUME spec=saved repro=1 claims 1/2 fixed diff=2 files gate=FAIL(round 1) t=212s`.
Budget: <= 1.5 s cold excluding the index (<= 4.5 s with a 3 s index build); <= 50 ms re-run.

### 5.4 `spec.py`

CLI: `spec.py` (SPEC on stdin), `--text`, `--show`, `--query "words"` (BM25 fallback).
Pipeline (total <= 3 s cold, <= 0.6 s warm): parse (4.1) -> NAMES (4.2) -> MESSAGES (`git grep -n -F` <= 3 hits each; if
absent, the first three words to find the repo's idiom for that kind of message) -> title expansion (4.2) -> hex refs
(`git cat-file -e`, then `git show --stat --oneline`, 3 lines, 2 s) -> ranking -> TESTS context -> NEXT.
Ranking: file score = sum over names of (5 DEFINED EXISTS, 3 container of a NEW name, 3 TITLE match) + log2(1 + usage
hits) + 0.5 x normalised BM25 of the whole SPEC over the file's symbols, times the path weight. Top 5 files, <= 3 symbols each.
TESTS context (Konwinski first place, literature 2.11): the best existing collectable test file for the top module
(4.12 scoring), its import lines (<= 6) and the shortest test function that references a NAME (<= 12 lines).
Output (<= 2,000 chars):
```
SPEC saved: kind=bugfix names=3 messages=0 claims=2  t=24s
NAMES
  FileProxy.isatty  NEW     class FileProxy DEFINED rich/file_proxy.py:9-57 (no isatty yet)
  Console.is_terminal EXISTS DEFINED rich/console.py:940-975, used 8x in 3 files
TITLE MATCHES: rich/file_proxy.py FileProxy (class L9-57)
CANDIDATES
  1. rich/file_proxy.py  FileProxy L9-57 | FileProxy.write L28-44 | FileProxy.flush L46-57
  2. rich/console.py     Console.is_terminal L940-975
NOT IN REPO: none
HISTORY rich/file_proxy.py: 3b2a1c0 2024-11-02 Fix flush ...
TESTS tests/test_file_proxy.py: from rich.file_proxy import FileProxy | from rich.console import Console
  def test_flush(): ... (8 lines)
NEXT: python3 /tmp/swe/show.py rich/file_proxy.py::FileProxy
```
At `t >= T_SPEC_REPLY` the NEXT line is `NEXT: write the repro now and reply with the PLAN`.

### 5.5 `show.py`

CLI: `show.py FILE::Qual.Name` (index lookup; overloads: first shown, others listed), `show.py FILE START END`,
`show.py FILE` (outline <= 60 entries), `--file/--symbol/--start/--end`. Lines numbered `NNNN| `, split on `\n` only
(form feed and other `str.splitlines` separators never shift numbering, test_plan F6). Cap 60 lines / 2,000 chars with
`... more: show.py FILE 181 240`. Records `state.views[file] = {sha1, ranges}` for the stale guard. Non-UTF-8 decoded
`errors="replace"` for display. Budget <= 300 ms warm, <= 1 s cold.

### 5.6 `edit.py`

CLI: `edit.py FILE` (SEARCH/REPLACE blocks on stdin), `--lines A-B` (stdin replaces lines A..B; empty deletes),
`--insert-after N`, `--create` (new file; refuses an existing one), `--revert` (restore FILE from `base_ref`), `--text`.
Grammar: marker lines `<{5,9} SEARCH`, `={5,9}`, `>{5,9} REPLACE`, case-insensitive; several blocks per call, applied
atomically to an in-memory copy (all match or nothing is written). No markers and no `--lines`: one-line usage error.
Matching tiers per block (first unique hit wins; never fuzzier):
1. exact substring;
2. unescaped: SEARCH with `\"` `\'` `\\` `\n` `\t` unescaped; when this matches, the same unescape applies to REPLACE
   (the model copied a double-encoded tool result, harness_runtime 3.1);
3. line-number prefixes `^\s*\d+\| ?` stripped from SEARCH and REPLACE when every SEARCH line carries one;
4. whitespace-flexible whole-line window (`rstrip`, then `strip`); REPLACE re-indented by the first matched line's
   indent delta (dedent is expressible, unlike `edit_file`'s flexible tier).
More than one match: `AMBIGUOUS: SEARCH matches at lines 40, 88; add a line of context`.
Post-conditions: `.py` targets compiled in memory; a SyntaxError writes nothing and prints
`REVERTED: SyntaxError at line 47 (line 3 of your REPLACE): <text>`; CRLF files keep CRLF; BOM kept; a missing final
newline stays missing unless the last line is edited; non-UTF-8 files are refused in one line (no traceback).
Guards: protected paths refused (`REFUSED: tests/test_x.py is a test file; the grader replaces it. Use repro.py for
checks.`); paths outside the workspace refused; `unrewrite()` applied to content; SEARCH == REPLACE -> `NO CHANGE`;
the second identical failed request -> `SAME FAILED EDIT AGAIN: use --lines A-B with numbers from show.py`;
`--lines` accepted only when the file hash equals the last show/edit record and `[A,B]` lies in a range shown since the
last change, else `STALE: run show.py FILE A B again (lines moved by +3 since your last view)`; with
`retry_issued` and `t >= T_EDIT_REFUSE2`: `TIME: reply now`; `hygiene_light` after every write.
Output (<= 900 chars): `EDIT OK rich/file_proxy.py: 1 block, lines 46-49 (+3 -0)  t=88s`, the new region with
+-2 numbered context lines, then `NEXT: python3 /tmp/swe/repro.py --check` (or `NEXT: reply now` at `t >= T_FIX_REPLY`
before a retry). Budget <= 300 ms.

### 5.7 `repro.py`

CLI: `repro.py` (claim-structured code on stdin, saved as `$SWE/repros/repro_N.py`, N = next free of 1..3; `--id K
--replace` overwrites), `--check`, `--py` (stdin snippet, run once, nothing saved), `--timeout N` (10, max 60), `--text`.
Save mode runs every claim on the current tree (= base when the source diff is empty, else also on the base copy) and
prints per-claim status (4.3); `--check` runs every saved repro's claims on the current tree and the base copy
concurrently, then the sibling sweep and spec gaps, then saves a checkpoint (claims score only).
Output save mode (<= 1,200 chars):
```
REPRO 1 at BASE: 2 claims  t=54s
  CLAIM 1 FAIL  AssertionError: False is not True   (good: shows the bug)
  CLAIM 2 PASS  (misses the bug: rewrite this claim with another reading)
NEXT: rewrite claim 2 once (repro.py --id 1 --replace), then reply with the PLAN
```
Output `--check` (<= 1,400 chars): `CHECK: 1/2 claims fixed (repro_1)  t=140s`, one line per claim, `SIBLINGS:` and
`SPEC GAPS:` blocks, NEXT. Wall <= max(timeout) + 3 s. `--py` output <= 1,200 chars.

### 5.8 `probe.py`

CLI: `--src dotted.name` (module.Class.method, module.func, or a bare name resolved through the repo's imports),
`--where Name` (index: every definition site + first usages, <= 12 lines), `--mro dotted.Class`.
`--src`/`--mro` run a driver (written once to `$SWE/probe_driver.py`) in a subprocess under `grader_env(ws)`, 15 s:
longest importable prefix, attribute walk, `inspect.getsourcefile`, lines a-b, signature, MRO (which base defines each
requested member), `inspect.unwrap`, <= 80 numbered source lines. An import that hangs is killed and reported
`HANG importing x`. Output <= 1,800 chars.

### 5.9 `gate.py`

CLI: `--round 1|2`, `--status`, `--diff` (bounded 2,000 chars, hunk headers kept), `--revert` (refused at
`t > T_RESTART_MAX`; otherwise checkpoint current, restore base for changed source files, delete agent-created
untracked files, keep the checkpoint), `--list` (the test files it would run; for offline tests).
`--round N` pipeline, deadline `min(GATE_BUDGET, T_GATE_END - t)` seconds; fast mode at `t >= T_FAST_GATE` skips step 5:
1. `hygiene_full`; each action one `FIXED:` line.
2. Empty check: no source change -> E.
3. Compile every changed `.py` in memory; import each changed module under `grader_env` (10 s each, concurrent) -> C
   with `file:line`.
4. Claims: as `repro.py --check` -> counts fixed / valid / broke.
5. Regression: discovery (5.10), then both trees concurrently, each
   `python3 -s -c "import sys,pytest; sys.exit(pytest.main(sys.argv[1:]))" -q -p no:anyio -p no:cacheprovider
   -o python_classes="Test* *Test" -o timeout=0 --maxfail=30 --junitxml=$SWE/junit_<tree>.xml <files>` from the tree
   root (the harness `pytest.ini` in the baseline commit applies), `PYTEST_TIMEOUT` each, `killpg`. Failures read from
   JUnit (exact classname + name). New failures (fail now, pass at base) re-run once alone (de-flake). A confirmed new
   failure is SOFT when at least one claim is FIXED and the test's source mentions a spec NAME, a MESSAGE or a literal
   from the diff's removed lines ("may encode the old behaviour the issue changes; keep the fix", test_plan F4); else
   HARD. Regression is UNKNOWN (never PASS) when no test ran in either tree, pytest is missing, the exit code is 2/4/5 or
   JUnit is missing (test_plan F3).
6. Spec gaps and siblings (4.4, 4.5).
7. Score and checkpoint (6.2).
8. Decision (6.1). On `submit`: restore the best checkpoint when it beats the current state, run `hygiene_full` again,
   verify the final diff applies to a fresh base copy (`git apply --check`) and encodes as UTF-8.
9. Memo: an unchanged diff hash returns the cached verdict in <= 300 ms; the third identical call prints
   `STOP: nothing changed since the last gate; submit or change the code`.
Output (<= 1,600 chars, verdict first):
```
GATE round 1: PASS claims=2/2 regress=0 hard,1 soft compile=ok import=ok gaps=0 siblings=0  t=142s
REASON: every claim fixed; existing tests unchanged (tests/test_file_proxy.py 12 passed on both)
FIXED: deleted repro.py (scratch in /workspace)
DIFF: rich/file_proxy.py +3 -0
NEXT: submit
```
`--status` (<= 1,000 chars): spec summary, top candidates, per-claim status, diffstat, last verdict, round, retry state,
best checkpoint score, t.

### 5.10 Test discovery (gate)

Tracked `test_*.py` / `*_test.py` only (never `conftest.py`, `tests/render.py`, `tools/*.py`, test_plan F-gate: 11/40
wrong picks in v9), read with a 300 kB cap. Score: +4 file named `test_<changed module>.py`; +3 imports the changed
module (`from pkg.mod import`, `import pkg.mod`, `from pkg import mod`); +2 per changed symbol found as a whole word;
+2 is the TESTS file spec.py chose; +1 beside the changed package. Top 3; <= 0.5 s.

### 5.11 `run.py`

CLI: `run.py [--timeout N] "command"` (N clamped 1..60; a bad value prints a notice and uses 20). `bash -c` in the
workspace, new session, `killpg` on timeout, `stdin=DEVNULL`. First line `exit=N` or `TIMEOUT after Ns (partial output
kept)`; ANSI/OSC stripped, `\r` normalised, runs of identical lines collapsed to `line (xN)`, head 25 / tail 45 lines,
the pytest summary line always kept, cap 2,500 chars, full log `$SWE/last.log`. The third run of the same command with
the same output prints `UNCHANGED (3rd identical run): change the command or move on`.

### 5.12 Budget table

| helper | typical wall | hard internal bound | output cap |
|---|---|---|---|
| install.py | 1.5 s (+ <= 3 s index) | 5 s per probe | 400 |
| spec.py | 3.0 s cold / 0.6 s warm | 2 s per git call, 15 s inline probe | 2,000 |
| show.py | 0.3 s | 1 s cold | 2,000 |
| edit.py | 0.3 s | - | 900 |
| repro.py | timeout + 0.5 s | 10 s per claim (max 60) | 1,200 / 1,400 check |
| probe.py | 1 s | 15 s | 1,800 |
| gate.py | 3-15 s | 60 s, never past t=292; 30 s per pytest tree; 10 s imports | 1,600 |
| run.py | timeout + 0.2 s | 20 s default, 60 max | 2,500 |

---

## 6. Gate decision table, scoring, checkpoints

### 6.1 Decision (first matching row wins)

Symbols: `R` round; `E` empty source diff; `C` compile/import error; `F` fixed claims; `V` valid claims (fail at base,
not BROKEN); `B` claims that passed at base and fail now; `H` hard regressions; `G` spec gaps; `k` gate calls in this
round after a repair/implement; `can_retry` = not `retry_issued` and `t <= T_RETRY_MAX (170)`;
`can_repair` = `t <= T_REPAIR_MAX (245)`.

| R | condition | NEXT |
|---|---|---|
| 1 | E and can_retry | `retry` (REASON: the first attempt changed no source file) |
| 1 | E and k < 2 | `implement <top candidate file:lines> for claim 1: <claim text>` |
| 1 | E | `submit` (nothing better exists) |
| 1 | C and k < 2 | `repair <file:line>: <error>` |
| 1 | C and can_retry | `retry` (REASON: <error>) |
| 1 | C | restore the best checkpoint without C if any, `submit` |
| 1 | (H > 0 or B > 0) and k < 1 and can_repair | `repair: <first failing test id>: <assertion line>` |
| 1 | (H > 0 or B > 0) and can_retry | `retry` (REASON: <first failure>) |
| 1 | V > 0 and 0 < F < V and k < 2 and can_repair | `repair: claim <n> still fails: <error line>` (partial: the approach is right, repair first) |
| 1 | V > 0 and F < V and can_retry | `retry` (REASON: <k/n claims fixed; first failing claim>) (nothing fixed: a fresh reading first) |
| 1 | V > 0 and F < V and k < 2 and can_repair | `repair: claim <n> still fails: <error line>` (no retry left) |
| 1 | G > 0 and k < 2 and can_repair | `repair: add <first gap>` |
| 1 | otherwise | restore the best checkpoint if it beats the current state, `submit` |
| 2 | E and no non-empty checkpoint and k < 1 | `implement <where>` |
| 2 | otherwise | restore the best checkpoint if better, `submit` |

`retry` sets `retry_issued`, records REASON, and is printed at most once per task and only in round 1. The verifier
replies `RETRY <REASON>`, which becomes `{verdict?}` for fixer2.

### 6.2 Score (lexicographic, larger is better)

`(non_empty, compile_ok and import_ok, F - B, -H, -G, -soft, -changed_lines)`; regression UNKNOWN counts as 0 hard.
Checkpoints come from `gate.py` (full score) and `repro.py --check` (claims only; regression treated as unknown).
`best()` prefers a gate-scored checkpoint on ties.

### 6.3 Why these thresholds

Public-like happy path reaches the verifier at ~100-120 s (section 9), so a retry (fixer2 ~40 s + verifier2 ~15 s)
fits before ~200 s; hidden-like tasks reach it at ~200-240 s, where a retry cannot finish, so the gate repairs once or
submits. `T_SAFE`/`T_FAST_GATE` 255 leave ~45 s for the last gate and `submit_patch`; `T_GATE_END` 292 keeps the gate
inside the cap even when started late.

---

## 7. Control flow, handoffs, recovery

- boot -> spec: boot's text is the `READY ...` line (`For context: [boot] said: ...`). Stages 2-6 never see the harness
  prompt (harness_runtime 6.1); the READY line carries the repo facts.
- spec -> fixer: `output_key: plan` (in the fixer's instruction and as the handoff event); SPEC, repro and index on disk.
- fixer -> verifier: `output_key: fix_notes`; the gate recomputes everything from disk.
- verifier: `submit_patch` + one sentence ends the task (fixer2/verifier2 never run), or `RETRY ...` (`output_key: verdict`).
- fixer2: sees `{plan?}`, `{fix_notes?}`, `{verdict?}` + handoff; `gate.py --status` restores situational awareness;
  `--revert` (only while `t <= 200`) gives a clean restart while the first attempt stays a checkpoint.
- verifier2: restores the best checkpoint and always submits.
- Time cap in any stage: the fallback diff is the working tree, from which every mutating helper (edit, `repro.py
  --check`, gate) removes protected-file edits, and which any helper call at `t >= 255` restores to the best checkpoint
  if it is empty. Read-only helpers never touch the tree below `T_SAFE`.
- Nudge (the invocation ended without a submit): the pipeline restarts at boot (harness_runtime 6.1); install prints
  RESUME; spec replies a PLAN from `--status`; the round-1 table sees `retry_issued`; the run converges on a submit.
- Compaction inside a stage: the instruction (issue, plan, rules) survives; `gate.py --status` / `spec.py --show`
  rebuild the rest in one call.
- A stage that ends on a tool call leaves its `output_key` unset; every downstream placeholder is `{key?}`.

---

## 8. Context budget (tokens; chars/3.6 for prose, chars/3.0 for double-encoded tool results)

Fixed per call: 12-13 tool declarations ~7,200-7,600 chars + skill instruction 1,333 + identity ~150 = ~2,500 tokens
(config_space 14); stage instruction 150-1,130; statement median 130 tokens, p95 ~680, max ~2,800 (N7); plan/notes
<= ~160 tokens each (duplicated once by the handoff event).

| stage | fixed (median / max statement) | calls x (output + result) typical | peak typical | peak worst (max statement, every output at its cap, +2 calls) |
|---|---|---|---|---|
| boot | 2,650 + harness prompt 1.5-4k | 2 x (40 + 150) | ~6.5k | ~9k |
| spec | 3,760 / 6,430 | 6 x ~(120 + 450) | ~7.2k | ~13.5k |
| fixer | 3,790 / 6,460 | 8 x ~(90 + 350) | ~7.4k | ~13.8k |
| verifier | 3,340 / 6,010 | 3 x ~(30 + 500) | ~4.9k | ~8.5k |
| fixer2 | 3,480 / 6,150 | 8 x ~(90 + 350) | ~7.0k | ~13.4k |
| verifier2 | 3,000 / 5,670 | 3 x ~(30 + 500) | ~4.6k | ~8.2k |

Typical peaks stay far below 14,336; the worst case touches it only with the single 10k-char statement and every output
at its cap, which is survivable (instruction + disk state) and ~13k tokens below the overflow line (30,720 with a
2,048 output cap). A stray full-window `read_file` (10,000 chars, ~3.3k tokens) still fits.

---

## 9. Time analysis

L4 model: `latency = 0.10 s + 28.5 ms x output tokens + 0.65-0.92 ms x new prompt tokens` (time_model 2; about 1.4 s
per step + 35 ms per token in the orchestrator's rounding), tools nearly free except hangs; apply the x1.08
underestimate factor (own_data 11).

### 9.1 Per stage, public-like task, one stream

| stage | calls | output tokens | LLM s | tools s | stage s |
|---|---|---|---|---|---|
| boot | 2 | 65 | 6 (first call prefills the harness prompt) | 1-4 | ~8 |
| spec | 6 | ~720 (SPEC 200, repro 250, PLAN 150, 3 x 40) | 27 | 4 | ~31 |
| fixer | 6 | ~560 (2 edits 400, show/check/reply) | 21 | 6 | ~27 |
| verifier | 3 | ~50 | 5 | 5-20 (gate) | ~15 |
| **happy path** | 17 | ~1,400 | 59 | 16-34 | **~81-100 s (x1.08: ~88-108 s)** |
| fixer2 (after RETRY) | 7 | ~600 | 24 | 6 | ~30 |
| verifier2 | 3 | ~50 | 5 | 5-15 | ~12 |
| **retry path** | 27 | ~2,050 | 88 | 27-55 | **~125-145 s (x1.08: ~135-157 s)** |

For comparison, projected L4 agent time from race 1: v4 145 s mean, v9_eog 171 s (time_model 6), because the v9
locator averaged 19.4 calls and the fixers lost turns to malformed `edit_file` calls. v10 removes both (N2, H4).

### 9.2 Hidden-like tasks

Hidden tasks run ~1.9x longer and v4 ran most of them to the cap. In v10 the helpers' NEXT lines move each stage on at
`t` 100 / 210 and the gate skips retries after 170 and repairs after 245, so a hidden task normally ends with a gated
`submit_patch` at ~230-290 s; one that still hits the cap costs 300 s + <= 5 s overshoot (`execution.py:27-40`) and
submits the clean, best-checkpoint working tree through the fallback path.

### 9.3 The 12 h cliff

Worst case: every task at the cap. Startup 600 s (measured 503-509 s), setup 3.6 s mean, teardown ~1 s, overshoot
<= 5 s; validation excluded (host, forum 743663; +11 s mean per task in brackets if it were included).

| N hidden tasks | worst case | with validation counted | expected (mean ~250 s agent) |
|---|---|---|---|
| 120 | 600 + 120 x 309.6 = 37,752 s = **10.49 h** | 10.85 h | ~9.0 h |
| 130 | 600 + 130 x 309.6 = 40,848 s = **11.35 h** | 11.75 h | ~9.7 h |

**Why v10 cannot exceed v4 by more than ~1%:** the per-task cap is identical (5 min); the raw-hang tail per command
is 90 s instead of 180 s; every helper-internal timeout is <= 60 s; setup is untouched by the bundle (skill files are
materialised in milliseconds per call); nothing in v10 runs outside the agent budget; the only addition inside a task is
work that is itself capped. v4's measured 10.4 h is therefore also v10's worst case to within the overshoot term. The
orchestrator's +8% ceiling (11.2 h) is met with ~0.7 h to spare at N=120.

---

## 10. Expected gain (honest)

Baseline: v9_eog 28/74 locally (Kaggle-env labels); v4 27/74 -> 0.12 on the public LB (7/58). Transfer ratio local ->
hidden ~0.33-0.34 (own_data 9). Lever sizes from task_catalog 4's per-task assignments with overlaps removed by hand.

| lever (task_catalog rank) | v10 mechanism | catalog tasks (likely / possible) | expected local flips vs v9_eog | transfer to hidden |
|---|---|---|---|---|
| 1 repro-must-flip | claim-structured repro written before the fix; FIXED/INVALID/BROKEN; gate rows | rich_4075, 3521, 4079 / fastapi_11194, 13920, 14616, rich_3472, 3777, 3782, 3935 | +2 to +3 | high (statements screened for inferability) |
| 2 edit channel + loop breaker | `edit.py` tiers, stale guard, SAME FAILED EDIT | rich_3278, 3454 / rich_3043, 3052, fastapi_15588 | +1 to +2 | high (same parser on the scorer) |
| 3 regression gate + hygiene | grader-parity pytest, SOFT/HARD, UNKNOWN never PASS, protected revert | rich_3180 / fastapi_14986, rich_4006, 3043 | +1 to +1.5 | high |
| 4 context guard + dependency source | bounded outputs, per-stage context, `probe.py --src`, NOT IN REPO/INHERITED | fastapi_14851, 5624 / fastapi_5077, rich_4079 | +0.5 to +1 | high |
| 5 sibling sweep | SIBLINGS in `--check` and gate | fastapi_5077, rich_3480 / fastapi_14986, rich_3953 | +1 | high |
| 6 gated second attempt | fixer2/verifier2 when t <= 170 | 8 possible | +0.5 to +1.5 | medium (rarely fires on hidden tasks) |
| 7 title-plus-link protocol | title expansion, TITLE MATCHES, COMPARE, history hint | rich_4077 / rich_3935, 3782 | +0.5 to +1 | medium |
| 8 hang-safe execution | per-claim timeouts, HANG classification, killpg everywhere | rich_3480 / rich_3772, 4006 | +0.5 | high |
| 9 runtime ground truth | `repro.py --py`, runtime spec-gap checks | fastapi_14851 / 14616, 13920 | (in 1 and 4) | medium-high |
| 10 never empty | E rows, implement path, T_SAFE auto-restore, verifier2 always submits | rich_3782, 3472 | +0.3 | high |
| spec conformance (11) | NEW names/params in every overload/importability, MESSAGES | rich_3052, 3777, fastapi_15588 | +0.5 | medium-high on hidden (screened) |
| 12 hygiene | protected revert everywhere; full cleanup at gate and T_SAFE | rich_3454 | +0.3 | high |
| helpers present in ~100% of tasks | boot + self-install + dual target | enabling; race 1 showed no direct helper effect (own_data 5) | 0 direct | high |
| costs | spec stage heavier on easy tasks; a wrong repro can mislead; a misclassified HARD can push a retry away from a correct fix (bounded by best-checkpoint restore) | | -1 to -2 | |

Net local: about **+6 (range +2 to +9) -> ~34/74 (30-37)**. Single-run noise is +-3 on 51 tasks, so a paired race
cannot confirm less than ~+4.

Hidden: 34/74 = 0.46 -> **0.15-0.16** at the v4 transfer ratio (9/58). Two reasons the mechanics and spec levers may
transfer better than that ratio: the hidden set is screened for inferability (the spec is in the statement), and hidden
tasks are cap-bound, where v10's time discipline converts capped runs into gated submits. Median estimate **0.16-0.17
(9-10/58)**, range 0.12-0.21. Probability of 0.30 (18/58): under 10%. What 0.30 would need, in order: a faster model
(the menu may widen to a 4B-active MoE, forum 2.11), execution-selected parallel candidates once L4 batching is measured,
or a working LoRA (currently wiped, forum 1.1).

Pre-registered pass condition for the first paired race (Carson's call to run it): v10 >= v9_eog + 3 solved on the
51-task arena run with the scorer's compaction config (`EventsCompactionConfig(15, 2, 14336, 5)`) and the pod cap scaled
to 175 s (time_model 6), and no increase in capped, empty or crashed runs. Any other outcome is reported as a negative
result.

---

## 11. Risks

1. **A wrong repro misleads the fixer** (test-fix coupling, literature 2.11). Mitigations: written from the statement
   before any edit; must fail at base per claim; exact strings only when stated; INVALID and BROKEN claims never count;
   the gate never blocks a submit on claims alone, it only chooses repair/retry/submit.
2. **SPEC stage overhead on easy tasks** (~31 s vs the v9 locator's ~64 s on L4, which is shorter, but a fumbled SPEC
   heredoc costs a call). spec.py never fails on malformed input and always prints candidates.
3. **Boot misbehaviour** (skips, starts solving, or garbles the arguments). Retry-once rule; recovery rule in every
   stage; self-install from any skill call. KPI: install OK in >= 98% of tasks (R-C68).
4. **Escaped copies in SEARCH** (92-97% of `edit_file` failures carry escapes): unescape tier, number-prefix tier,
   `--lines` with the stale guard.
5. **Heredoc content rewritten by the subprocess sandbox** (`/tmp`, `/workspace`): reversed by `unrewrite()`; 0/129 gold
   patches contain those literals.
6. **Backend uncertainty** (Docker per host, subprocess in our kernels): dual install target, SWE from `__file__`,
   workspace from git; tests cover both modes and a Docker image that sets TMPDIR elsewhere.
7. **A voluntary graph-tool call returns a huge result** (competitor: 136k chars): banned in COMMON; attaching them is
   still safer than the proven crash when unattached (N3).
8. **Compaction threshold 14,336 or 32,768**: typical stages stay < 8k; survivable either way.
9. **SOFT/HARD misclassification** (test_plan F4): bounded to one retry and a best-checkpoint restore before submit.
10. **Nudge restart** (1-3/51 tasks): RESUME keeps it to ~3 calls.
11. **pytest masked in the scorer's agent sandbox** (N4): in-process `pytest.main`.
12. **src-layout repos in the subprocess sandbox import the host copy** (test_plan F10): not fixable by a bundle;
    install.py reports it; the Docker scorer installs the repo editable, where our `<root>/src` PYTHONPATH matches.
13. **Large private repos**: index bounded to 3 s per call / 6,000 files with a partial notice; `git grep` batched;
    gate capped at 60 s and 30 s per pytest tree.
14. **Temperature 0.7 for judges and 0.3 for boot** are unmeasured changes; both only affect stages that copy literal
    commands or follow NEXT lines.
15. **Helper leaks**: every child is in its own session and killed as a group; no background processes (the index is
    built synchronously within 3 s budgets).

---

## 12. Requirement registry

Tiers: CI (offline, < 10 min, no GPU), NIGHTLY (all local snapshots + Linux Docker gate), REPLAY (recorded traces),
CANARY (GPU; Carson's call, outside this task). Test files: `tests/test_v10_bundle.py`, `test_v10_platform.py`,
`test_v10_sandbox.py`, `test_v10_spec.py`, `test_v10_edit.py`, `test_v10_repro.py`, `test_v10_gate.py`,
`test_v10_flow.py`, `test_v10_time.py`, `test_v10_tasks_offline.py`, `test_v10_replay.py`.
Fixtures (`tests/conftest.py`): `ws(tid)` extracts `data/raw/snapshots/<tid>.tgz` (40 of 74 valid ids are local:
39 rich + requests_6644), applies the harness setup (exclude lines, harness `pytest.ini`/`conftest.py`, baseline commit +
`_swegemma_baseline` tag) and clones per test; `helpers` copies `submissions/v10/skills/swe-tools/scripts` to a temp
dir with a private TMPDIR; `no_orphans` (autouse: no surviving process of the test's sessions); `mock_llm` (port of
`<scratchpad>/cfgspace/mock_openai.py` into `tests/_mock_openai.py`, scripted per agent name); `naive_spec(statement)`
(TITLE + backticked identifiers + CamelCase/snake tokens as NAMES + quoted strings as MESSAGES + one claim).
Every bug found while building gets its own regression test named after the finding.

### A. Bundle and configuration
| ID | Requirement | Test |
|---|---|---|
| R-C01 | Root is a SequentialAgent with exactly `[boot, spec, fixer, verifier, fixer2, verifier2]`, all LlmAgent, `include_contents: none`, one model `gemma-4-31b-it-qat-w4a16-ct`; `scripts/validate.py submissions/v10` prints OK. | `test_v10_bundle.py::test_tree_and_compile` |
| R-C02 | Every stage attaches the eight non-submit harness tools and `skills: [skills/swe-tools]`; only verifier and verifier2 attach `submit_patch`. | `::test_stage_tools` |
| R-C03 | Every tool named in a prompt is attached to that stage or provided by the skill toolset; every helper and flag named in a prompt or SKILL.md exists in that helper's exported `FLAGS`. | `::test_prompt_tools_and_flags_exist` |
| R-C04 | Prompts and SKILL.md contain no backtick; tool-call examples list arguments alphabetically; the COMMON block is byte-identical in the five working stages. | `::test_prompt_style_lints` |
| R-C05 | The only `{...}` in any instruction are `{problem_description}`, `{plan?}`, `{fix_notes?}`, `{verdict?}` (regex `{+[^{}]*}+`), and each optional key is produced by an earlier stage's `output_key` (`plan`, `fix_notes`, `verdict`). | `::test_placeholders_and_output_keys` |
| R-C06 | Generation configs equal section 2.2 (temperatures, `max_output_tokens` 256/1,536/2,048/1,024, `include_thoughts: false`, no `seed`, no `thinking_level`); the compiled bundle forwards exactly those values (mock capture). | `::test_generation_config` |
| R-C07 | `eval_config.yaml` is exactly `{max_time_minutes: 5, timeout_seconds: 90, max_tool_calls: 90, max_turns: 150}`. | `::test_eval_config` |
| R-C08 | Static instruction <= 1,300 tokens per stage (chars/3.6); rendered with the 10,095-char statement and 1,000-char plan/notes <= 5,000 tokens. | `::test_instruction_budget` |
| R-C09 | Packaging: allowed extensions only, no `__pycache__`/dotfiles/symlinks, skill name equals its kebab-case directory, no script stem in `sys.stdlib_module_names`, deterministic zip (sorted, fixed mtime) with sha256 printed. | `test_bundles.py` (auto-discovers v10) + `::test_packaging` |
| R-C10 | `submissions/v9_eog` and `submissions/v4` are byte-identical to their pinned tree hashes. | `::test_frozen_bundles_untouched` |

### B. Helper platform
| ID | Requirement | Test |
|---|---|---|
| R-C11 | Helpers import only the stdlib and each other (AST scan against `sys.stdlib_module_names`), import no network module, and `py_compile` under every local 3.10-3.13 interpreter and Linux 3.12. | `test_v10_platform.py::test_stdlib_only_compiles_no_network` |
| R-C12 | Every helper exits 0 on every tested path (bad flags, missing files, internal exceptions injected via an env hook); line 1 is the status line ending `t=NNNs`; never a traceback on stdout or stderr. | `::test_exit_zero_status_line[helper x case]` |
| R-C13 | Output caps hold on hostile inputs (1 MB file, 50 kB line, 5,000 grep hits, binary output): the CAPS table of 5.1; the full text is in `$SWE/last.log`; truncation leaves the marker. | `::test_output_caps[helper]` |
| R-C14 | A helper with an open, silent stdin returns within 1 s; a heredoc (including > 64 kB) is read completely; a trailing `EOF`+punctuation line and a trailing backtick are stripped. | `::test_stdin_never_blocks_and_terminator_junk` |
| R-C15 | No `/tmp` string literal is used as a path in helper code except `DOCKER_TMP` in `_common.py` (AST scan; printed hints whitelisted). | `::test_tmp_literal_whitelist` |
| R-C16 | Children run in new sessions and die as a group on timeout: after `run.py --timeout 1 "sleep 30 & bash -c 'sleep 20'"`, a `while True` claim, and a hanging test under the gate, no process of those sessions survives (test_plan F7). | `::test_timeouts_kill_process_group` |
| R-C17 | Below `T_SAFE`, `git status --porcelain` is unchanged by install, spec, show, repro (save, `--check`, `--py`), probe, run and `gate.py --status/--diff/--list` on a tree without protected-file edits; no `__pycache__`/`.pytest_cache` appears in the workspace. | `::test_readonly_helpers_leave_tree_clean[helper]` |
| R-C18 | Helpers are immune to stdlib shadowing and path flags: with `signal.py`, `secrets.py`, `types.py`, `select.py` at the workspace root on `PYTHONPATH`, and with `PYTHONSAFEPATH=1`, every helper still runs. | `::test_stdlib_shadowing_immunity` |
| R-C19 | Run through a skill-wrapper imitation (temp dir cwd, `PWD=<ws>`, `sys.path[0]=<ws>`), any helper installs all ten files into `$SWE` (atomic, idempotent, <= 50 ms when current) and then does its own job; installed helpers take SWE from `__file__`. | `test_v10_sandbox.py::test_any_helper_self_installs` |
| R-C20 | Real `SubprocessManager` sandbox (pattern of `tests/test_sandbox_tmp_paths.py`): after a skill-style install every `python3 /tmp/swe/<h>.py` call works; Docker mode (TMPDIR unset, cwd `/workspace`-like) and a TMPDIR set to a non-/tmp directory outside a sandbox both leave working copies where `/tmp/swe` resolves. | `::test_reachable_in_both_backends` |
| R-C21 | Every option is accepted in `--key value` form and stdin content as `--text`, so `run_skill_script(args={...})` works for every helper. | `test_v10_platform.py::test_adk_arg_form[helper]` |
| R-C22 | `t` comes from the `_swegemma_baseline` committer time when within [0, 900] s, else install time - 8; monotonic; within +-3 s of real elapsed time in the fixture. | `::test_clock_origin` |
| R-C23 | Diffs use `_swegemma_baseline`, else the recorded HEAD; an agent `git commit` neither hides changes nor empties a checkpoint (F5); a `state.json` whose `ws`/`base_sha` mismatch is reset with caches, repros and checkpoints. | `::test_diff_base_and_state_isolation` |

### C. install and spec
| ID | Requirement | Test |
|---|---|---|
| R-C24 | `install.py` prints one READY/RESUME line <= 400 chars with ws, packages, layout, test dirs, python, pytest importability and the import self-check; RESUME when spec, repro or checkpoint state exists. Fixtures: flat, src layout, no tests dir, package shadowed by an installed copy. | `test_v10_spec.py::test_install_facts` |
| R-C25 | `spec.py` parses 14 SPEC variants (missing keys, bullets, backticks, lower-case keys, CRLF, prose between keys, legacy BEFORE/AFTER/BUGS/EXAMPLE, 10 claims) into the documented structure; `--show` round-trips within 1,200 chars. | `::test_spec_parse_tolerance` |
| R-C26 | NAMES on a fixture repo: DEFINED (def, async def, method, nested class method, parameter, constant), usage counts, NEW containers, NOT IN REPO, and INHERITED from an external base (`Foo(json.JSONEncoder)`, `Foo.default EXISTS` -> `INHERITED from json.encoder.JSONEncoder` plus <= 20 numbered source lines), 18 cases. | `::test_names_localisation` |
| R-C27 | Title protocol on snapshots: `TITLE: proxy isatty` puts `rich/file_proxy.py` (FileProxy) in CANDIDATES top 3 on rich_4077 when the snapshot is present, and `fix for padding width` puts `Table._get_padding_width` in the top 5 on rich_3935; issue numbers, URLs and hex tokens yield no search terms. | `::test_title_protocol[tid]` (skips without snapshot) |
| R-C28 | MESSAGES are grepped exactly and by family; resolvable hex refs print <= 3 `git show --stat` lines and unknown ones are silent. | `::test_messages_and_hex_refs` |
| R-C29 | TESTS context prints the chosen test file's import lines (<= 6) and one test function (<= 12 lines) that references a NAME; the chosen file is collectable. | `::test_tests_context` |
| R-C30 | Offline recall with `naive_spec(statement)` over the 40 local tasks: a gold source file in CANDIDATES top 3 for >= 30/40 (v9 `locate.py`: 28/40) and top 1 for >= 22/40 (21/40); docs/examples demoted unless KIND is docs. | `test_v10_tasks_offline.py::test_candidate_recall` |
| R-C31 | `spec.py` <= 3.0 s p95 cold on the largest local snapshot and <= 0.6 s warm; a synthetic 10k-file repo stops indexing at 3 s with a partial notice and completes on the next call; the cache invalidates on file change. | `test_v10_spec.py::test_spec_timing_and_index_budget` |

### D. show and edit
| ID | Requirement | Test |
|---|---|---|
| R-C32 | `show.py` forms (`FILE::Qual.Name` incl. overloads, `FILE A B`, outline, long flags) number lines `NNNN| `, split on `\n` only (form feed safe), cap 60 lines / 2,000 chars with a continuation hint, and record the view. | `test_v10_edit.py::test_show_forms` |
| R-C33 | SEARCH/REPLACE tiers on a 22-case table: exact unique; escaped copies unescaped consistently in REPLACE; `NNNN| ` prefixes stripped; whitespace-flexible with indent delta including dedent; AMBIGUOUS lists lines; multiple blocks atomic (one failing block leaves the file byte-identical). | `::test_edit_tiers` |
| R-C34 | Gold replay: every gold hunk of every local task applied through SEARCH/REPLACE blocks derived from the hunk (bottom-up per file; `--create` for new files) yields files byte-identical to `git apply` (v9 `replace.py` baseline 122/122 line-range hunks; rich_3930's 23 new-file hunks now covered). | `test_v10_tasks_offline.py::test_gold_hunk_replay[tid]` |
| R-C35 | Encoding edges: CRLF kept with only edited lines changed; BOM kept; missing final newline kept unless the last line is edited; non-UTF-8 refused in one line; never a traceback (test_plan F6). | `test_v10_edit.py::test_encoding_edges` |
| R-C36 | A SyntaxError writes nothing and names the line relative to REPLACE; a valid edit is kept and printed with +-2 numbered context lines within 900 chars. | `::test_syntax_guard_and_output` |
| R-C37 | Refusals: protected paths and paths outside the workspace are refused in one line; `hygiene_light` after an edit restores any tracked protected file changed by other means (e.g. `sed -i` on a test file) and reports FIXED. | `::test_refusals_and_protected_revert` |
| R-C38 | Loop breaker: the second identical failed request prints SAME FAILED EDIT AGAIN naming `--lines`; stale guard: `--lines` outside the ranges shown since the last change, or after the file changed, prints STALE; with `retry_issued` and `t >= 265` edits print `TIME: reply now`. | `::test_loop_breaker_stale_and_time_guards` |
| R-C39 | Heredoc content passed through a real `SubprocessManager` with `/tmp/x` and `/workspace/y` literals is written back as `/tmp/x` and `/workspace/y`; in Docker mode content is untouched. | `test_v10_sandbox.py::test_heredoc_unrewrite` |

### E. repro, probe, spec gaps, siblings
| ID | Requirement | Test |
|---|---|---|
| R-C40 | Claim parsing: prelude + `# CLAIM n:` sections (none -> claim 1; up to 8); each claim runs in its own process with the prelude, concurrently, in `$SWE/cwd` under the grader env, default 10 s (max 60); `--py` runs once and saves nothing; the workspace is untouched even when a claim writes files. | `test_v10_repro.py::test_claim_sections_and_isolation` |
| R-C41 | Classification on a fixture with one claim per class: PASS, FAIL (last exception line), HANG, BROKEN (SyntaxError, NameError in the repro, cross-claim variable with the specific hint, missing non-repo module), valid failure on a NEW name, "check the repro imports" on an unknown name. | `::test_claim_classification` |
| R-C42 | `--check` gives FIXED / STILL FAILS / STILL HANGS / BROKE / INVALID / BROKEN per claim with the summary `k/n claims fixed`; wall <= max(timeout) + 3 s; saves a claims-only checkpoint. | `::test_check_matrix` |
| R-C43 | Real-task machinery: an oracle repro (the task's hidden test functions invoked from a claim) is FAIL or HANG at base and FIXED on gold for >= 38/40 local tasks (requests_6644 is known-free in the subprocess env, F10). | `test_v10_tasks_offline.py::test_oracle_claims_flip[tid]` |
| R-C44 | Spec gaps: a NEW name missing or not importable from its defining module, a NEW parameter missing from any same-named def or overload, a MESSAGE absent from non-test source, and >= 2 valid claims with 1 changed def are reported; EXISTS names never are. | `test_v10_repro.py::test_spec_gaps` |
| R-C45 | Sibling sweep: with only the first gold hunk applied, the remaining site is listed for fastapi_5077, rich_3480, fastapi_11194, fastapi_9555 and fastapi_14458 (snapshots permitting); full gold gives 0 SIBLINGS on >= 90% of local tasks; <= 8 lines. | `test_v10_tasks_offline.py::test_sibling_sweep[tid]` |
| R-C46 | `probe.py --src` resolves `module.Class.method` (including an inherited method), `module.func` and a bare imported name; prints file, lines, signature, MRO and <= 80 numbered lines; an import that hangs is killed at 15 s and reported; `--where` and `--mro` bounded. | `::test_probe_forms_and_timeout` |

### F. gate
| ID | Requirement | Test |
|---|---|---|
| R-C47 | Decision table 6.1 exactly: 20 synthetic states (rounds 1-2 x E/C/F/V/B/H/G/k/retry_issued/t) give the specified NEXT; the verdict line is first; NEXT is one of submit, repair, implement, retry. | `test_v10_gate.py::test_decision_table[case]` |
| R-C48 | `retry` is printed at most once per task, only in round 1, only at `t <= 170`; it sets `retry_issued` and records REASON; `--revert` is refused at `t > 200`. | `::test_retry_and_revert_windows` |
| R-C49 | Regression is UNKNOWN, never PASS, when no test ran in either tree, pytest is missing, exit code is 2/4/5 or JUnit is missing (F3). | `::test_unknown_never_pass` |
| R-C50 | Grader parity: in-process `pytest.main` with `PYTHONSAFEPATH=1 PYTHONNOUSERSITE=1`, `-p no:anyio -p no:cacheprovider -o python_classes="Test* *Test" -o timeout=0`, from the tree root so the harness `pytest.ini` applies; works when `pytest/__main__.py` and the `pytest` binary are masked as in `container_setup.py:968-1010`; failures from JUnit with parametrised ids compared exactly. | `::test_grader_parity_with_masked_pytest` |
| R-C51 | Discovery picks only collectable test files (never conftest.py, tests/render.py, tools/*.py), at most 3, in <= 0.5 s; a file that the hidden test_patch touches is picked for >= 30/39 local tasks (v9 baseline 23/39). | `test_v10_tasks_offline.py::test_discovery[tid]`, `::test_discovery_recall` |
| R-C52 | New failures are re-run once before being reported; SOFT/HARD per 5.9; on gold, the six known behaviour-change tasks (rich_3942, 3935, 3470, 3105, 3043, 3061) never get a repair/retry NEXT caused by those tests. | `::test_soft_regressions_on_gold[tid]` |
| R-C53 | `hygiene_full`: tracked protected edits reverted, test/scratch/root-level untracked files deleted, vendored trees and stdlib-shadowing top-level modules pruned, NEW-named files kept, each reported FIXED; afterwards the hidden test_patch applies and gold still verifies (tamper fixtures, F1). | `test_v10_tasks_offline.py::test_hygiene_restores_test_patch_apply[tid]` |
| R-C54 | Checkpoints: each gated or checked state is stored with its score; restore is transactional (a failed apply rolls back to the exact prior diff); `submit` restores the best when it beats the current state and verifies `git apply --check` on a fresh base copy; a non-empty checkpoint is never lost to an empty submit; at `t >= 255` any helper restores the best checkpoint when the source diff is empty. | `test_v10_gate.py::test_checkpoints_restore_and_auto_restore` |
| R-C55 | Memo: an unchanged diff returns the cached verdict in <= 300 ms; the third identical call prints STOP. | `::test_memoised_verdict` |
| R-C56 | Deadline: with hanging tests and claims the gate returns within 60 s wall and never after `t=292`; at `t >= 255` fast mode skips regression and returns within 15 s. | `::test_gate_deadlines_with_hangs` |
| R-C57 | `--status` <= 1,000 chars with spec, candidates, claims, diffstat, verdict, round, retry state, best score, t; `--diff` <= 2,000 chars with hunk headers. | `::test_status_and_diff_bounds` |
| R-C58 | On gold, the round-1 verdict is `submit` with no HARD regression for >= 37/40 local tasks; on the empty diff the gate answers in < 1 s with an E row. | `test_v10_tasks_offline.py::test_gate_gold_and_empty[tid]` |

### G. Flow, context, time, replay
| ID | Requirement | Test |
|---|---|---|
| R-C59 | Offline end-to-end through the real harness (`run_agent_sandbox` + `SubprocessManager`, `OPENAI_BASE_URL` at `mock_llm`, `EventsCompactionConfig(15, 2, 14336, 5)`, a 3-file synthetic task): (a) verifier submits -> fixer2/verifier2 never run and the patch equals the tree diff; (b) RETRY -> fixer2 gets `{verdict?}`, verifier2 submits the better checkpoint; (c) nobody submits -> no exception and a non-empty, clean fallback diff; (d) boot skips install -> spec recovers through the COMMON rule; (e) a scripted 15k-token result in the fixer triggers compaction and `gate.py --status` recovers. | `test_v10_flow.py::test_paths[a-e]` |
| R-C60 | Handoff templating: spec's final text appears as `{plan?}` in fixer/verifier/fixer2; a stage ending on a tool call leaves its key unset and downstream renders `''` without KeyError. | `::test_handoff_templating` |
| R-C61 | After every mutating helper call in the mock flow (edit, `repro.py --check`, gate), including one scripted right after a raw `sed -i` on a test file, the workspace diff contains no protected-file change, so a time-cap fallback diff taken after any of them is clean. | `::test_clean_protected_files_after_mutating_helpers` |
| R-C62 | Static context budget per stage (instruction with the 10,095-char statement, declarations measured through the mock, typical call count x the helper caps) <= 14,000 tokens, and <= 9,000 with the median statement; verifier stages <= 9,000 worst. | `test_v10_time.py::test_context_budget` |
| R-C63 | Time constants live in one table in `_common.py` with the values of 5.1; prompts quote the same thresholds (100, 210, 240, 265); every helper-internal timeout < `timeout_seconds`; `600 + N x (60 x max_time_minutes + 9.6) <= 0.95 x 43,200` for N=120 and `<= 43,200` for N=130. | `::test_time_constants_and_12h` |
| R-C64 | L4 projection of the mock-flow traces (0.10 s + 28.5 ms/output token + 0.8 ms/new prompt token, x1.08, plus measured tool time): happy path <= 120 s, retry path <= 170 s. | `::test_l4_projection` |
| R-C65 | Helper wall budgets of 5.12 hold on the largest local snapshot (p95 over 20 runs). | `::test_helper_wall_budgets[helper]` |
| R-C66 | Replay KPIs for any canary run directory: install OK >= 98% of tasks; 0 `can't open file` after recovery; 0 crashes (ContextWindow, unknown tool, KeyError); 0 patches touching protected files; <= 2/51 scratch-bearing patches; <= 2/51 empty patches; boot <= 3 calls in >= 95%; max prompt <= 16k; mean output tokens <= 3,000 per task; `edit_file` calls <= 1 per task mean. | `test_v10_replay.py::test_kpis` (REPLAY, skipped without a run dir) |
| R-C67 | Linux gate: the CI tier of `tests/test_v10_*.py` passes in `scripts/linux_test.sh` (python:3.12-slim). | `scripts/linux_test.sh` (NIGHTLY) |
| R-C68 | Pre-registered race criterion is recorded before the run: v10 >= v9_eog + 3 on the 51-task arena with the scorer's compaction config and the 175 s pod cap, and no increase in capped/empty/crashed runs; the verdict is written to `docs/v10/` whatever it is. | `docs/v10/race_prereg.md` exists and is referenced by `test_v10_replay.py::test_prereg_present` |

---

## 13. Build order, tiers, ship gate

Order (each step green before the next):
1. `_common.py`, `install.py`, `run.py` + R-C11..R-C23 (real-sandbox tests first: R-C19, R-C20).
2. `_index.py`, `show.py`, `edit.py` + R-C32..R-C39 (gold-hunk replay R-C34 is the acceptance test).
3. `spec.py` + R-C24..R-C31 (recall on the 40 local snapshots; the 34 missing snapshots, all fastapi plus rich_4076,
   4077, 4079, need Carson's approval for the one-time download named in test_plan 2).
4. `repro.py`, `probe.py`, spec gaps, sweep + R-C40..R-C46.
5. `gate.py` + R-C47..R-C58 (decision table first, then real-task gold/empty/tamper).
6. Prompts, YAML, SKILL.md + R-C01..R-C10; `scripts/validate.py submissions/v10`.
7. Flow tests R-C59..R-C65, then `scripts/linux_test.sh` (R-C67).
8. Pre-register (R-C68), then the paired race (Carson's call; not in this task).

Ship checklist: `py_compile` of all helpers; `scripts/validate.py submissions/v10` prints OK; the full suite
(`.venv/bin/python -m pytest -q tests`, 370 existing + v10) green; `scripts/linux_test.sh` green; zip sha256 recorded;
`submissions/v9_eog` and `v4` hashes unchanged. No Kaggle push, no pod, no spend from this design task.

---

## 14. What changed versus v9_eog, and versus the earlier draft of this design

| area | v9_eog | earlier draft C | this design |
|---|---|---|---|
| install | one remembered call in the locator (skipped 40%) | boot + self-install, `$TMPDIR/swe` only | boot + self-install; dual target so `/tmp/swe` resolves in the Docker scorer too; SWE taken from `__file__` |
| prompts | backtick-wrapped calls and commands | backtick-wrapped in places | zero backticks, commands on their own lines, args in template order (N1) |
| spec | free-text locator plan | SPEC with EXAMPLE, BEFORE/AFTER, BUGS | SPEC with numbered CLAIMS; examples go only into the repro (saves ~250 output tokens, ~9 s on L4) |
| repro | written after the fix in `/tmp/repro.py` | one script, pass/fail as a whole | one process per claim; partial fixes visible; BROKEN and INVALID claims never count |
| spec gaps | none | static presence of names/messages | runtime checks: importability, parameters in every same-named def and overload |
| editing | `edit_file` first, `replace.py` by line range | SEARCH/REPLACE tiers + stale guard | same, plus protected-file revert after every write and heredoc terminator junk stripping |
| gate | related tests vs HEAD, false PASS, "undo" wording | repro + regression + gaps + checkpoints | claim-aware decision table; in-process pytest (masked-pytest safe); UNKNOWN never PASS |
| restart hole | n/a | `--revert` could leave an empty tree at the cap | `--revert` only while t <= 200; any helper restores the best checkpoint at t >= 255 if the tree is empty |
| hygiene | preflight check the model may skip | gate cleanup | light revert in every mutating helper; full cleanup at the gate and at T_SAFE |
| helper robustness | none | stdin select | plus stdlib-shadowing immunity and `PYTHONSAFEPATH` immunity |
| sampling | T 1.0 everywhere, seed (dead), 4,096 | T 1.0 / 0.2, 256-2,048 | T 1.0 explore, 0.7 judges (0.2 loops, pain_points 0.5), 0.3 boot; 256-2,048 |
| eval_config | 180 / 70 / 5 / 150 | 90 / 90 / 5 / 150 | 90 / 90 / 5 / 150, justified with validation outside the 12 h (N5) |
| evidence | - | - | compiled probe bundle, run_skill_script corruption census, graph-tool crash attribution, pytest masking path, snapshot history check, statement statistics |
