# v10 design A: robustness-first

Architect A, 2026-09-28. Angle: keep the proven locate -> fix -> verify shape of `submissions/v9_eog`, and make every
failure mode the research reports measured either impossible or bounded. Add as little new surface as possible, and add no time.

Inputs read for this spec:
- `research/harness_runtime.md` §0-§11
- `research/config_space.md` §0, §10, §11, §14
- `research/own_data.md` (all)
- `research/time_model.md` (all)
- `research/task_catalog.md` §2-§5
- `research/test_plan.md` §0, §5
- `research/competitors.md` §0, §4-§6, §8
- `research/forum.md` §1.3-§2
- the shipped `submissions/v9_eog/**`

Four facts in this spec were checked directly in the installed harness source, `SP = .venv/lib/python3.12/site-packages`,
and none of them is in the reports:
- **pytest masking (Docker).** `SP/swegemma/harness/container_setup.py:968-1043` together with `agent_runner.py:302-309`
  mask pytest and unittest in the agent sandbox when `enable_sandbox_testing` is False: they overwrite
  `pytest/__main__.py` and `/usr/local/bin/pytest`. The default is True, and the scorer's value is unknown.
- **The per-task temp dir is findable.** Both backends export `TEST_TMPDIR` as the /tmp that commands see: `<root>/tmp` in
  subprocess (`subprocess.py:483-501`) and `/tmp` in Docker (`docker.py:93`). v10 locates its scratch directory from it.
- **An unknown tool name ends the task.** `SP/google/adk/flows/llm_flows/functions.py:490-504` re-raises unless a plugin
  handles it, and no harness plugin implements `on_tool_error_callback` (grep over `adk_eval_core`, `swegemma`).
- **The harness prompt names tools.** It mentions `submit_patch`, `read_file` and the three graph tools to the first stage
  (`agent_runner.py:95-181`).

---

## 0. Summary

| # | Failure mode (report evidence) | v10 mechanism | Requirement |
|---|---|---|---|
| 1 | Helpers missing in ~40% of tasks: install skipped or arguments malformed (own_data §5, test_plan F2) | A one-call `setup` stage, `skills:` on every stage, a bootstrap in every script, and a "can't open file" recovery line in every prompt | R-A11..R-A15 |
| 2 | `edit_file` gets malformed arguments (18-22%), then death spirals: 0 solves in 51 loop tasks (harness §3.4) | `edit.py` through a `run_command` heredoc is the only documented edit path. It has tiered matching, a numbered "closest match" hint, and a loop breaker. It syntax-checks and reverts. `edit_file` stays declared (so calling it does not crash the task) but is never recommended | R-A19..R-A30 |
| 3 | Compaction at 14,336 prompt tokens wipes `none` stages; overflow at about 28.7k discards the patch (harness §0.1-0.2) | Every helper output has a hard cap (400-4,000 chars). View by line range or symbol, not `read_file`. Handoffs are short and fixed-format, with a per-stage static budget of 12k tokens or less. `status.py` recovers state after amnesia. `max_output_tokens` is 3,072 or less, which puts overflow at 29,696 or more | R-A31..R-A35 |
| 4 | Hangs cost 60-100% of a task, and `run.py` leaks process groups (time_model §3, F7) | Every subprocess runs in a new session with a deadline and `killpg`, and stdin is `/dev/null`. The prompts route all execution through `run.py` / `verify.py`. `timeout_seconds` is 120 | R-A36..R-A39 |
| 5 | Agent edits to test files break `test_patch` application: the harness reset is a no-op (harness §7.2) | `edit.py` refuses protected paths. `edit.py`, `verify.py` and `finalize.py` all revert tracked protected-file edits automatically, so even the timeout fallback diff is clean | R-A25, R-A51..R-A54 |
| 6 | Empty, test-only or "no bug" patches score 0: 20/47 v4 misses changed no source file (catalog §2) | `finalize.py` refuses READY on an empty or test-only diff. After t >= 150 s with no source change, every helper footer says EDIT NOW | R-A33, R-A52 |
| 7 | No gate, or a gate that says PASS when nothing ran or tells the model to undo correct fixes (F3, F4) | `verify.py` runs a repro-must-flip check, an import/collection check, and a comparison of related tests on the original and on the current version, with the grader's exact pytest flags. It reports UNKNOWN when nothing ran, and its regression wording warns that a failing test may encode the old behaviour | R-A40..R-A50 |
| 8 | A final stage that ends without `submit_patch` restarts the pipeline or crashes the Sequential root at post-invocation compaction (config_space #4, #12) | A fast path where the verifier submits, plus a `submitter` stage that runs only if the verifier did not submit. That stage's prompt is always small, so the last LLM call of an unfinished pipeline is always below 14,336 tokens | R-A10, R-A62 |
| 9 | Unknown-tool crash discards everything (harness §1) | Every stage declares the v9_eog 8-tool set, and `submit_patch` is declared only where the prompt names it. A lint checks that no prompt or helper output names an undeclared tool | R-A02, R-A03 |
| 10 | Scorer unknowns: Docker or subprocess, compaction at 14,336 or 32,768, pytest masked or not (forum §2) | Every mechanism is specified and tested to work under all 8 combinations | R-A13, R-A46, R-A62, R-A64 |

What v10 does **not** add, to keep new surface small (sect. 9): parallel candidates, a LoopAgent retry, an LlmAgent
coordinator root, AgentTool, thinking, and temperature changes on the working stages. Those belong to the other
architects' angles.

---

## 1. Agent tree

```
swe_pipeline  SequentialAgent
 ├─ setup      LlmAgent   one call: run_skill_script(install.py), reply READY
 ├─ locator    LlmAgent   locate, view, write /tmp/swe/repro.py, check it fails on original, reply PLAN      output_key: plan
 ├─ fixer      LlmAgent   edit.py, verify.py --repro-only, sibling grep, reply NOTES                      output_key: fix_notes
 ├─ verifier   LlmAgent   status.py, verify.py, <=2 repair rounds, finalize.py, submit_patch, one-line text
 └─ submitter  LlmAgent   runs ONLY if the verifier did not submit: finalize.py, submit_patch, one-line text
```

Only constructs that config_space.md compiled and ran are used: a Sequential root with LlmAgent children,
`include_contents: none`, `output_key`, `{key?}` templating, `skills:` shared by several agents (case 56), `!include` of
`.md`/`.yaml`, and per-agent `generate_content_config`. There are no callbacks (they are ignored), no LoopAgent,
ParallelAgent or AgentTool, and no `thinking_level`.

### 1.1 Why each stage exists

- **setup** exists because the locator skipped `run_skill_script(install.py)` in 20-26 of 51 tasks when install was
  "step 1 of 3" in a long prompt (own_data §5). A stage whose instruction is one line and one call removes the
  competition from exploration. It costs about 5.7 s on L4 (sect. 7). It is not the only line of defence (sect. 4.1).
- **submitter** exists for two reasons.
  - It is the backstop for a verifier that replies with text before calling `submit_patch`. Without it the harness
    nudges and the Sequential root restarts from `setup` (config_space #12).
  - A small final prompt means that when the pipeline ends naturally, the latest `prompt_token_count` is far below
    14,336. That is the only condition under which post-invocation compaction can crash a Sequential root
    (config_space #4, `SP/google/adk/apps/compaction.py:223-236`).

  When the verifier submits and then replies, the harness ends the task (`agent_runner.py:569-579`) and the submitter
  never runs, so it costs 0 s in the common case.

### 1.2 Exact YAML

`agent.yaml`
```yaml
name: swe_pipeline
agent_class: SequentialAgent
description: Setup, locate, fix, verify, submit; fresh context per stage.
sub_agents:
  - config_path: sub_agents/setup.yaml
  - config_path: sub_agents/locator.yaml
  - config_path: sub_agents/fixer.yaml
  - config_path: sub_agents/verifier.yaml
  - config_path: sub_agents/submitter.yaml
```

`sub_agents/setup.yaml`. The other four differ only in name, description, instruction, output_key, gen config and the
presence of `submit_patch`.
```yaml
name: setup
model: gemma-4-31b-it-qat-w4a16-ct
description: Installs the helper scripts.
include_contents: none
instruction: !include ../prompts/setup.md
tools: [run_command, read_file, edit_file, write_file, get_status, get_code_neighbors, search_similar_code, get_code_subgraph]
skills: [skills/swe-tools]
generate_content_config: !include ../configs/gen_tiny.yaml
```

| agent | description (<= 60 chars; it enters the system prompt) | tools | skills | output_key | gen config |
|---|---|---|---|---|---|
| setup | Installs the helper scripts. | BASE8 | swe-tools | - | gen_tiny |
| locator | Finds the code to change and writes a repro. | BASE8 | swe-tools | plan | gen_locator |
| fixer | Implements the change. | BASE8 | swe-tools | fix_notes | gen_fixer |
| verifier | Checks, repairs and submits the change. | BASE8 + submit_patch | swe-tools | - | gen_verifier |
| submitter | Submits the patch if not yet submitted. | BASE8 + submit_patch | swe-tools | - | gen_submitter |

`BASE8 = [run_command, read_file, edit_file, write_file, get_status, get_code_neighbors, search_similar_code, get_code_subgraph]`.
This is exactly the v9_eog set, which recorded 0 unknown-tool crashes in race 1.

The tool policy is:
- Declare every name the model can plausibly call, because an undeclared name ends the task.
- Recommend in the prompts only `run_command` plus the helpers.
- `edit_file`, `write_file` and `read_file` stay declared but are either de-recommended by name (edit/write: "their code
  arguments get corrupted here") or replaced in the prompts (`view.py`).
- The three graph tools are declared because the harness prompt advertises them to stage 1 whenever graphs exist, and
  since the 2026-09-25 re-issue they exist for every task. No prompt recommends them. `search_similar_code` can return
  136k chars (competitors §4).

### 1.3 Generation configs (`configs/*.yaml`)

| file | temperature | top_p | top_k | max_output_tokens | thinking_config |
|---|---|---|---|---|---|
| gen_tiny.yaml (setup) | 0.2 | 0.95 | 64 | 256 | include_thoughts: false |
| gen_locator.yaml | 1.0 | 0.95 | 64 | 1536 | include_thoughts: false |
| gen_fixer.yaml | 1.0 | 0.95 | 64 | 3072 | include_thoughts: false |
| gen_verifier.yaml | 1.0 | 0.95 | 64 | 2048 | include_thoughts: false |
| gen_submitter.yaml | 0.2 | 0.95 | 64 | 1024 | include_thoughts: false |

Rationale:
- **No `seed`, no `thinking_level`.** `seed` is dead (never forwarded), and `thinking_level` is a silent-typo hazard
  (config_space #1-#2).
- **Working stages keep v9_eog's sampling** (T 1.0, top_p 0.95, top_k 64). That is the only sampling our 28/74 was
  measured with, and changing it would confound the robustness changes. T 0.6 is listed as an optional race arm in sect. 10.
- **The two one-job stages run near-greedy** so that they comply deterministically.
- **`max_output_tokens` bounds a runaway reply on L4:**
  - 44 s at 1,536, 58 s at 2,048 and 88 s at 3,072, against 117 s at v9's 4,096 (time_model §3).
  - It also moves the overflow line to 32,768 - 3,072 = 29,696 or higher.
  - The fixer gets 3,072 because a legitimate 60-100-line replacement heredoc is 700-1,200 tokens (gold p90 is 91
    changed lines).

### 1.4 `eval_config.yaml`

```yaml
evaluation:
  max_time_minutes: 5
  timeout_seconds: 120
  max_tool_calls: 100
  max_turns: 200
```

- **`max_time_minutes` = 5.** This is the only knob that bounds the 12 h worst case, and it is unchanged from v4
  (time_model §5).
- **`timeout_seconds` = 120** (v4: 180; the recommendation was 60).
  - In v10, hang safety comes from the helpers' internal deadlines (20-60 s, R-A39), not from this value.
  - Its remaining roles:
    - (a) A backstop for a raw `run_command` the model runs outside the helpers. That time is inside the 300 s cap, so it
      has no effect on the 12 h budget.
    - (b) The timeout of the hidden-test pytest in verification (`verification.py:498-503`). There, a false negative on a
      correct patch is the most expensive error in the whole system.
  - Public verifications take 12.6 s or less on Kaggle CPU. The private scorer is probably Docker with 2 vCPU and runs
    unknown private suites. 120 s is a 10x margin, and 60 s is not.
  - Against v4, 120 is strictly better on wall time.
- **`max_tool_calls` = 100 and `max_turns` = 200.** These are loop brakes only, because the time cap binds first.
  - Raised from 70/150 because v10 routes edits through `run_command`, where v9's failed `edit_file` calls did not count
    against the tool budget. The tool budget now carries all edits.
  - In race 1, 21 verifier stages hit the 70-call cap mid-verification (own_data §6).
  - `submit_patch` and `get_status` are free, so the verifier can still submit after the cap.

---

## 2. Prompts (the full text, per stage)

Rules applied to every prompt:
- Placeholders: only `{problem_description}`, `{plan?}` and `{fix_notes?}` (R-A04).
- Every command is shown in its exact form.
- A tool is named only if it is declared on that stage.
- `submit_patch` is named only in the verifier and submitter prompts.
- Instruction size is 2,600 chars or fewer, excluding the problem (R-A08).
- Every prompt carries the same recovery line and the same amnesia line.

Shared blocks, inlined into each file by hand (`!include` cannot concatenate). A test (R-A14) checks they are identical
in every prompt:

RECOVER: `If a python3 /tmp/swe/... command fails with "can't open file", call run_skill_script(skill_name="swe-tools", file_path="install.py") once, then repeat the command.`

AMNESIA: `If you cannot see your earlier tool results in this stage (the context was shortened), run python3 /tmp/swe/status.py first and continue from what it shows.`

TIME: `Every helper prints the elapsed task time as [t=...s]. The whole task is stopped at t=300s. Obey any EDIT NOW / FINISH / TIME line a helper prints.`

EDITFORM (fixer, verifier and submitter only):
```
Edit files ONLY with edit.py through run_command (raw text, no escaping; edit_file and write_file corrupt code here):
python3 /tmp/swe/edit.py <file> <<'SWE_EOF'
<<<<<<< SEARCH
<exact current lines, copied from view.py output; the line numbers may be left in>
=======
<new lines>
>>>>>>> REPLACE
SWE_EOF
By line numbers instead: python3 /tmp/swe/edit.py <file> --lines 120-135 <<'SWE_EOF'  (new lines)  SWE_EOF
New file: python3 /tmp/swe/edit.py <newfile> --create <<'SWE_EOF'  (content)  SWE_EOF
edit.py checks syntax and undoes a bad edit. When a SEARCH does not match it shows the closest lines with numbers:
use them or the --lines form. Never send the same failing edit twice.
```

### 2.1 `prompts/setup.md`
```
You are SETUP, stage 1 of 5. Your whole job is one tool call. Do not work on the issue; later stages do that.
1. Call exactly: run_skill_script(skill_name="swe-tools", file_path="install.py")
2. Then reply with the single word READY (text only, no tool call).
If that call returns an error, call it once more exactly as written, then reply READY.
```

### 2.2 `prompts/locator.md`
```
You are the LOCATOR, stage 2 of 5, for an issue in the Python repository at /workspace. You find the code and write
a reproduction. You do not edit files in /workspace; the next stage does.

Issue:
{problem_description}

Helpers (run with run_command; short output):
- python3 /tmp/swe/locate.py "<identifiers, error text and key words from the issue>"
- python3 /tmp/swe/grep.py "<regex>"                (bounded git grep; add --tests to search tests)
- python3 /tmp/swe/view.py <file> <start> <end>     or: view.py <file> <function or Class.method>
- python3 /tmp/swe/view.py --obj <module.attr>      (source of an installed dependency object)
- python3 /tmp/swe/run.py --timeout 20 "<command>"  (run any code only this way)
<RECOVER> <AMNESIA> <TIME>

Steps (at most 10 tool calls; reply by t=90s):
1. locate.py with the issue's identifiers and error text. If the issue is only a title plus a link, first turn the
   title's words into code names (a "proxy" -> *Proxy* classes, "padding width" -> *padding* functions).
2. view.py the top 1-2 candidates. grep.py exact names from the issue. If a name is not defined in the repository it
   comes from a dependency: view.py --obj it. Print real objects with run.py before assuming a library type.
3. If the bug can be checked by a script, write a reproduction that FAILS now and passes once fixed, using the exact
   input and expected value from the issue:
   cat > /tmp/swe/repro.py <<'SWE_EOF'
   from pkg.mod import thing
   out = thing(<input from the issue>)
   assert out == <expected from the issue>, repr(out)
   SWE_EOF
   Then run: python3 /tmp/swe/verify.py --repro-only
   It must say "fails on original". If it passes, the repro misses the bug: try one other input shape. If the issue is
   about a hang, a TIMEOUT there confirms it.
4. Stop and reply with the plan (text only, under 120 words), exactly these lines:
FILES: <path:start-end (function)> for every place to change
CAUSE: <one sentence>
FIX: <what to change, with the exact names, messages and signatures the issue gives>
REPRO: fails on original (<error>) | none
TESTS: <existing test file(s) for this code>
Do not use edit_file or write_file. Scratch files only in /tmp/swe.
```

### 2.3 `prompts/fixer.md`
```
You are the FIXER, stage 3 of 5. Make the code change in /workspace now.

Issue:
{problem_description}

Locator's plan:
{plan?}

<EDITFORM>
Other helpers: view.py <file> <start> <end> | view.py <file> <symbol> | grep.py "<regex>" | run.py --timeout 20 "<cmd>" |
verify.py --repro-only | status.py   (all as python3 /tmp/swe/<name>)
<RECOVER> <AMNESIA> <TIME>

Steps (at most 12 tool calls; first edit by t=150s, stop editing by t=210s):
1. If the plan is empty, run locate.py "<key words>" first. view.py the plan's FILES lines.
2. Make the smallest COMPLETE change: every place the plan lists, exactly the names and messages the issue gives,
   existing behaviour kept for other inputs. The current code IS wrong: never conclude that nothing needs changing.
3. If the plan has a repro: python3 /tmp/swe/verify.py --repro-only. If it still fails, read why and fix again.
4. Sibling sweep: grep.py the expression you changed; fix the same defect wherever else it occurs in the package.
5. Stop and reply (text only, under 60 words):
CHANGED: <file function (lines)>
REPRO: passes | still fails | none
SIBLINGS: none | fixed <where>
Never edit tests, conftest.py, pytest.ini, pyproject.toml, setup.cfg or tox.ini: the graders replace test files and
such edits make grading fail. Run code only through run.py or verify.py (they have timeouts).
```

### 2.4 `prompts/verifier.md`
```
You are the VERIFIER, stage 4 of 5. The change should already be in /workspace. Check it, repair it if needed, submit.

Issue:
{problem_description}

Plan:
{plan?}

Fixer's notes:
{fix_notes?}

<EDITFORM>
Other helpers: view.py, grep.py, run.py, status.py, verify.py, finalize.py (all as python3 /tmp/swe/<name>)
<RECOVER> <AMNESIA> <TIME>

1. python3 /tmp/swe/status.py  (shows the diff and what earlier stages did).
2. If no source file is changed, make the plan's change yourself with edit.py now, the smallest plausible version.
3. python3 /tmp/swe/verify.py
   - GREEN or AMBER: go to step 4.
   - RED (IMPORT/SYNTAX error, or the repro still fails): fix with edit.py and run verify.py again; at most 2 repair
     rounds, and none after t=240s.
   - REGRESSIONS: a test that passed before now fails. If it asserts the OLD behaviour that the issue asks to change,
     keep your fix (the graders update such tests). Otherwise your change broke it: fix that.
4. python3 /tmp/swe/finalize.py  (cleans the patch). If it says NOT READY, fix what it names and run it again.
5. Call submit_patch. Then reply with one short sentence. submit_patch must be your last tool call.
If a helper prints TIME, go straight to step 4.
```

### 2.5 `prompts/submitter.md`
```
You are the SUBMITTER, the last stage. The patch has not been submitted yet.
Plan (for reference): {plan?}
1. Run python3 /tmp/swe/finalize.py
2. Only if it says EMPTY, apply the plan's FIX with edit.py (smallest version) and run finalize.py again.
3. Call submit_patch, then reply with the one word submitted.
<EDITFORM> <RECOVER>
```

### 2.6 `skills/swe-tools/SKILL.md`
Frontmatter: `name: swe-tools`, plus a description of 300 chars or fewer. The body has one line per helper CLI and must
match the argparse usage of each script exactly (R-A14). It opens with the literal install call.

---

## 3. Handoff contracts

| from -> to | channel | format | bound |
|---|---|---|---|
| harness -> setup | user event (harness prompt) | problem, budgets, rules, tree (150 lines) | fixed by the harness |
| setup -> locator | `For context: [setup] said: READY` | one word | 5 tokens |
| locator -> fixer | `{plan?}` in the instruction, plus the handoff event | FILES/CAUSE/FIX/REPRO/TESTS | 120 words (about 250 tokens) |
| fixer -> verifier | `{plan?}`, `{fix_notes?}`, plus the handoff | CHANGED/REPRO/SIBLINGS | 60 words |
| any stage -> any later stage | `$SWE/journal.jsonl` (via `status.py`) and `$SWE/repro.py` | JSON lines written by the helpers | tail of 8 entries shown |
| verifier -> submitter | handoff event plus `{plan?}` | one sentence | small |

`output_key` is written only from a final text reply (config_space §3). Every downstream use is therefore optional
(`{plan?}`), and the fixer prompt handles an empty plan.

---

## 4. Helpers (`skills/swe-tools/scripts/`, the only sources)

The rules that apply to every script:
- **Stdlib only.** Python 3.8+ syntax (`ast.parse(..., feature_version=(3, 8))`). No network modules. No script name
  shadows a stdlib module (R-A17).
- **Always exit 0.** A non-zero `SystemExit` becomes a skill error. `run_command` duplicates output on a non-zero exit
  (harness §3.2, §4).
- **Status first.** The first line of output is the status or verdict. The output is hard-capped (the budget table in
  sect. 4.12), the full text goes to `$SWE/last.log`, and a one-line footer comes last.
- **Paths come from the environment.** The workspace comes from `ws()` (sect. 4.1), never from a `/workspace` literal.
  The scratch directory comes from `SWE_DIR()`, never from a `/tmp` literal (R-A16).
- **Subprocess discipline.** Every subprocess uses `start_new_session=True`, `stdin=DEVNULL` and a deadline with
  `os.killpg(SIGKILL)`. Surviving background processes are reaped on normal exit too (R-A36).
- **No destructive git on the workspace.** No `reset --hard`, `checkout .`, `clean -fd` or `stash`. The only reverts are
  path-scoped, `git checkout <baseline> -- <protected path>` (R-A55).
- **Helper output never names a tool** other than `run_command` and `run_skill_script`, which every stage declares
  (R-A03). The "TIME" hint deliberately says "end your stage now", not "call submit_patch".

### 4.1 `_swe_common.py` (library, not a CLI)

**`SWE_DIR()`** returns the first of `$SWE_DIR` (tests), `$TEST_TMPDIR`, `$TMPDIR`, `"/tmp"`, joined with `swe`.
- `TEST_TMPDIR` is the command-visible /tmp in both backends: subprocess sets `HOME=TMPDIR=TEST_TMPDIR=<root>/tmp`, and
  Docker sets `environment={'TEST_TMPDIR': '/tmp'}` (`docker.py:93`).
- So `python3 /tmp/swe/x.py` in command text and `SWE_DIR()` in Python always name the same directory. That holds even in
  a Docker image that sets `TMPDIR` to something else, which v9's `TMPDIR or /tmp` gets wrong.

**`ws()`** returns the first of:
1. `$SWE_WS`;
2. the `git rev-parse --show-toplevel` of `os.getcwd()` (the `run_command` context: cwd is the workspace);
3. the same for `$PWD` (the skill context: the wrapper chdirs into a temp dir, but bash's exported `PWD` stays the
   workspace, harness §2.4);
4. the directory of `sys.argv[0]`'s wrapper if it is named `.adk_exec_*.py`;
5. `/workspace`, only if it is a git repository.

v9 put the `/workspace` literal second. On a RunPod pod, `/workspace` is the network volume, so v9 could target the
wrong repository (R-A15).

**`baseline()`** is `git rev-parse -q --verify refs/tags/_swegemma_baseline^{commit}`, falling back to `HEAD`. It is
cached in `$SWE/baseline`. That is the ref `submit_patch` diffs against (`execution.py:83-86`) and survives an agent
`git commit` (F5).

**`clock()`** returns seconds since the baseline commit's committer time, `git log -1 --format=%ct <baseline>`.
- The harness creates that commit during setup, just before the agent timer starts (`container_setup.py:575-582`), so
  the clock is correct even when the setup stage never installed.
- If the commit time is more than 900 s in the past or in the future, it falls back to the install stamp
  `$SWE/t0`, written once.

**`sh(argv|str, timeout, cwd=None, env=None)`** returns `(rc|None, text)`.
- Popen with `start_new_session=True` and `stdin=DEVNULL`, stdout+stderr merged, read into memory with a 4 MB cap.
- On deadline: `killpg(SIGKILL)`, then a 2 s drain of what is already buffered, returning `rc=None` with partial output.
- On normal exit: `killpg` of the session to reap background children, ignoring `ProcessLookupError`.

**`cap(text, limit, head=20, tail=40, keep=SUMMARY_RE)`**
- Strips ANSI/OSC and normalises `\r`.
- If the text is over the limit, it keeps the first `head` lines, the last `tail` lines and the last line that matches
  the pytest summary regex, then inserts `... [N lines cut; full output: /tmp/swe/last.log] ...`.
- A single line longer than 400 chars is cut to 200 + `…` + 100.

**`journal(event)`** appends one JSON line to `$SWE/journal.jsonl`. `jtail(n)` returns short renderings of the last n
entries.

**`is_protected(rel)`** returns a reason, or None. Protected:
- `test_*.py`, `*_test.py` and `conftest.py` anywhere;
- any path whose first component is `tests`, `test` or `testing`, or which contains `/tests/` or `/test/`;
- `pytest.ini`, `tox.ini`, `setup.cfg`, `pyproject.toml`, `.git/`;
- anything outside `ws()`, or containing `..`.

Library code under a nested `pkg/testing/` is **not** protected (R-A25). This is narrower than the harness's pattern on
purpose.

**`changes()`** returns `(source, protected, untracked)` relative paths, from `git diff --name-only <baseline>` and
`git ls-files --others --exclude-standard`. It does not write to the index (no `git add -N`).

**`hygiene_revert()`** handles tracked protected files that were changed:
- files modified since baseline: `git checkout <baseline> -- <p>`;
- files deleted since baseline: restored the same way;
- untracked protected files: deleted.

It returns the list, and the helpers print it on one line: `reverted test/config edits: ...`.

**`footer(src_changed)`** always returns `[t=123s]`, plus at most one hint line:
- `t >= 150 and not src_changed`: `EDIT NOW: no source file changed at t=150s+. Locator: reply with your plan now. Others: make the plan's change with edit.py now.`
- `t >= 210`: `FINISH: t>=210s. Stop exploring; keep the edit and end your stage.`
- `t >= 250`: `TIME: t>=250s. End your stage now (the verifier: go to finalize.py).`

**`unrewrite(text)`** undoes the subprocess sandbox's command-text rewrite (harness §2.3) on text a helper received
through a heredoc or stdin.
- It applies only when `$TEST_TMPDIR` ends in `/tmp` and its parent's basename starts with `swegemma_sandbox_`.
- It replaces `<root>/tmp` with `/tmp`, `<root>/workspace` with `/workspace` and `<root>/venv/bin` with
  `/usr/local/bin`, where `root = dirname(TEST_TMPDIR)`.
- In Docker it changes nothing (there is no rewrite).
- Otherwise code containing `"/tmp"` in a heredoc would be written into the repository with the sandbox path baked in
  (test_plan R06).

**`bootstrap()`** runs at the top of every script. If `__file__` is not under `SWE_DIR()`, which means it is running
from a skill temp dir, it silently runs the install copy. So any `run_skill_script` call of any helper also installs all
of them.

### 4.2 `install.py`
- CLI: `run_skill_script(skill_name="swe-tools", file_path="install.py")`, with no arguments.
- Copies every `*.py` next to it into `SWE_DIR()`, each via a temp file and `os.replace` (atomic), with modes 0644. It is
  idempotent and skips identical content by comparing sha1 values.
- Writes `$SWE/VERSION` (the bundle version string) and `$SWE/t0` if absent.
- Prints, in 400 chars or fewer:
  `swe-tools ready in /tmp/swe: locate grep view edit run verify finalize status. Next: python3 /tmp/swe/locate.py "<key words>"`
- Performance: 300 ms or less (measured today: 25 ms).

### 4.3 `locate.py`
CLI:
- `python3 /tmp/swe/locate.py "<query>"`
- also `--query Q` (skill dict-args form), and the query on stdin if no argument is given.

Output:
- Line 1: `LOCATE: <n> symbols in <m> files`.
- An orientation line: the top-level packages, the test dirs, and the **import origin** of each top-level package
  (`importlib.util.find_spec(name).origin` in a 5 s subprocess). It flags `OUTSIDE WORKSPACE` when the package resolves
  to site-packages (src-layout or a shadowing install; test_plan F10, competitors §5.11).
- Up to 6 files, each with up to 3 symbols as `kind qualname Lstart-end`.
- The footer.
- 1,800 chars or fewer.

Algorithm:
- The v9 BM25 over AST symbols, which is kept because it measured 21/28/34 of 40 at R@1/3/8.
- File list from `git ls-files -z '*.py'` (fallback `os.scandir` walk). It skips vendored and hidden dirs and files over
  1 MB.
- Index cached in `$SWE/index_<baseline>.marshal`, invalidated per file by `(mtime_ns, size)`. A 15 s parse deadline
  keeps whatever is indexed and scores the rest by path tokens.
- Tests ×0.35, and `docs`/`docs_src`/`examples`/`benchmarks` ×0.6. That reduces the fastapi `docs_src` flooding without
  excluding runnable examples (catalog P17).
- A third call in one task adds `NOTE: 3rd locate call; stop searching and use what you have.`

Performance: 3 s or less on the first call for 3k files, 300 ms or less cached.

### 4.4 `grep.py`
CLI: `python3 /tmp/swe/grep.py "<regex>" [--tests] [--max 40] [--path <dir>]`

Runs `git grep -n -E -I --no-color` with tests excluded unless `--tests` is given.

Output: grouped by file, at most 5 hits per file and 40 in total, each line cut to 160 chars. Each hit is annotated with
its enclosing `def`/`class` from the cached AST index (for the sibling sweep). It ends with a count line.
1,800 chars or fewer, and 1 s or less.

### 4.5 `view.py`
CLI:
- `view.py <file> <start> <end>`
- `view.py <file> <symbol>` (`func`, `Class`, `Class.method`, async included)
- `view.py <file>` (outline: defs and classes with ranges, at most 60)
- `view.py --obj <dotted.name>` (`inspect.getsourcelines` in a 15 s subprocess)

Output:
- Header: `<file> lines A-B of N` (or `origin: <path> [installed dependency: read-only]`).
- Lines formatted `f"{n:>5}  {line}"`, numbered by splitting on `\n` only, so the numbers equal git's and
  `edit.py --lines` (F6).
- At most 100 lines and 4,000 chars. A clamped range says `range clamped; next: view.py <file> <B+1> <B+100>`.

Performance: 200 ms or less (plus 15 s at most for `--obj`).

### 4.6 `edit.py` (the edit channel)
CLI (the new text is always on stdin, from a quoted heredoc):
- `edit.py <file>` followed by one or more SEARCH/REPLACE blocks;
- `edit.py <file> --lines A-B` (empty stdin deletes the lines, and says so);
- `edit.py <file> --insert-after N`;
- `edit.py <file> --create`.

**Input normalisation**, before matching:
1. `unrewrite()`.
2. Strip a trailing line equal to `SWE_EOF` (an unrecognised indented delimiter).
3. When **every** line of a SEARCH or REPLACE body carries the `^\s*\d+  ` view.py prefix, strip the prefixes.
4. Accept marker variants: `<{5,} SEARCH`, `={5,}`, `>{5,} REPLACE`.

**Matching tiers** for each SEARCH, all on a working copy:
1. Exact substring, unique.
2. Line-wise `rstrip` (this also absorbs CRLF).
3. Unescape: decode `\\\"`, `\"`, `\'`, `\\n`, `\\t` and `\\\\` once, then retry tiers 1-2. **The same decode is applied
   to REPLACE.** This is the double-JSON-encoding artefact (harness §3.1): edits whose `old_string` held escapes failed
   92-97%.
4. Indentation-relative. Compare `lstrip`-ed lines over windows of equal length and require a unique match. Re-indent
   REPLACE by `(file window's first indent) - (SEARCH first indent)`, which may be negative, so a dedent can be
   expressed (the harness flexible tier cannot).

**Outcomes:**
- `OK (tier)`: the file is written. The edited region is printed with numbers, plus or minus 2 lines, at most 30 lines.
- `NO MATCH`: the file is untouched. The output shows the closest window (difflib ratio over same-length windows, the
  best 1), its similarity, its numbered lines, and the exact recipe `use: edit.py <file> --lines A-B`.
- `AMBIGUOUS`: every candidate start line is listed, with `add context lines or use --lines`.
- `REVERTED`: the new text does not compile. `compile(src, path, 'exec')` runs in memory, with no .pyc. The output gives
  the error line relative to the edit and the offending line. The file stays byte-identical.
- `REFUSED`: `is_protected()`. The output says why: "graders replace test files; this edit would make grading fail; put
  checks in /tmp/swe/repro.py".

**File fidelity:**
- EOL detected per file; inserted text is converted to it.
- UTF-8 BOM kept. A missing final newline stays missing unless the last line is edited.
- Non-UTF-8: decode latin-1 and write latin-1 (byte-exact round trip). Any other failure gives a one-line error, never a
  traceback.

**Loop breaker:** a journal entry of `(file, sha1(stdin), mode, outcome)` is written on every call.
- An identical failing call gives `ALREADY TRIED: this exact edit failed at t=..s (<reason>). Do something different: view.py <file> A B, then edit.py <file> --lines A-B.`
- Three consecutive failures on one file print the numbered current region of the last closest window, together with the
  `--lines` recipe.

**Warnings:**
- The REPLACE contains `\"` while neither the SEARCH nor the matched region does: `WARNING: new text contains \" ; if you meant a plain quote, redo it`.
- The file is a dependency outside `ws()`: refused.

**Post-hook:** `hygiene_revert()` runs after every successful edit (sect. 4.1).

Budgets: 1,500 chars of output or less. 150 ms or less on a 5k-line file.

### 4.7 `run.py`
CLI: `run.py [--timeout N] "<shell command>"`
- Default 20 s, clamped to 1..90. An invalid value prints `NOTE: --timeout must be an integer; used 20`.
- `cwd = ws()`. The environment adds `PYTHONDONTWRITEBYTECODE=1`, `NO_COLOR=1`, `TERM=dumb` and `COLUMNS=120`.

Output:
- Line 1 is `exit=N` or `TIMEOUT after Ns (partial output below). If the issue is about a hang or loop, this may be the bug.`
- Then `cap(..., 2500)` with the pytest summary line always kept, then the footer.
- If the output contains the harness's `pytest is disabled in this environment`, it appends
  `Test runners are disabled by the harness here: check behaviour with /tmp/swe/repro.py and verify.py instead.`
- A third identical command with identical output hash appends `NOTE: same command, same output 3 times; change something.`

Performance: 50 ms of overhead or less.

### 4.8 `verify.py` (the gate: repro-must-flip, collection, regression)
CLI:
- `verify.py [--repro-only] [--repro PATH] [--tests f1.py ...] [--timeout 40]`
- The default repro is `$SWE/repro.py` if it exists.

Pipeline, under one global deadline of 60 s:
0. `hygiene_revert()`. Compute `changes()`.
1. **No source change.**
   - With `--repro-only`: run the repro once on the workspace, which equals the original. Report
     `REPRO: fails on original (<last exception line>)`, `passes on original: the repro misses the bug`, or
     `hangs on original (expected for hang bugs)`. Stop.
   - Otherwise: `VERDICT: NO SOURCE CHANGE - make the fix first.` in under 1 s. Stop.
2. **Base copy**, once per task and cached. `git worktree add --detach $SWE/base <baseline>` (fallback:
   `git archive <baseline> | tar -x`). Then copy the workspace's git-ignored build artefacts into it (`*.so`, `*.pyd`,
   generated `_version.py` and similar), from `git ls-files --others --ignored --exclude-standard`, excluding
   `__pycache__`, `.pytest_cache`, `*.pyc` and `.adk_exec_*`, with at most 2,000 files and 50 MB.
   This handles C-extension repos that the v9 `git archive` copy broke. If base imports fail anyway, the base side is
   UNKNOWN, not "fails".
3. **Import check.** `py_compile`, in memory, of each changed .py. Then import each changed module (`python3 -s -c "import pkg.mod"`, 10 s,
   with grader env). A failure gives `RED: IMPORT/SYNTAX <module>: <last line>`. That covers collection errors, which is
   how fastapi_15588's three patches died.
4. **Repro on original and current**, run concurrently, 20 s each, grader env. The original uses
   `cwd=$SWE/base` and `PYTHONPATH` with the workspace root replaced by the base copy (plus `base/src` if it exists);
   the current uses `cwd=ws()` and the inherited `PYTHONPATH`.
   Outcomes: FLIPPED (fail -> pass), STILL FAILS, PASSES ON BOTH (repro misses the bug), BROKE (pass -> fail),
   HANG-ORIG, HANG-NOW.
5. **Related tests.** Skipped with `--repro-only`, and skipped with a note when pytest is masked. Masking is detected by
   reading `pytest/__main__.py` for the harness's "disabled" text; v10 does **not** bypass it (R-A46).
   - Discovery: collectable test files only (`test_*.py`, `*_test.py`), at most 3, scored by changed symbols from the
     `-U0` diff (`def`/`class`/`@@` headers, methods, async), module stems, and `from <pkg.mod> import` lines. Plus
     `--tests`.
   - Run on base and current concurrently (at most 2 processes, which fits Docker's 2 vCPU), each as
     `PYTHONSAFEPATH=1 PYTHONNOUSERSITE=1 python3 -s -c "import sys,pytest; sys.exit(pytest.main(sys.argv[1:]))" <files> --junitxml=$SWE/j_<side>.xml -p no:anyio -o timeout=0 -o python_classes="Test* *Test" -q -p no:cacheprovider`.
     These are the grader's flags (`verification.py:493`), and there is no `-o addopts=` (R-A44).
   - Failing node sets come from JUnit. A regression is re-run once, alone, before it is reported (de-flake).
6. **Verdict line first:**
   - `GREEN`: imports OK, repro FLIPPED, no regressions.
   - `AMBER`: imports OK, no regressions, and the repro is none or passes on both, or the tests are UNKNOWN.
   - `RED`: an import error, repro STILL FAILS / BROKE / HANG-NOW, or confirmed regressions.
   - `UNKNOWN` replaces PASS whenever no test ran (no summary, exit 2/4/5, collection error on both sides, or timeout).
     This is F3.
   - Regressions are listed with one assertion line each and the fixed text `If a test asserts the OLD behaviour the issue asks to change, keep your fix; otherwise fix the regression.` This is F4.
7. **Memo.** An identical `(diff sha1, repro sha1, tests)` returns `SAME AS LAST RUN (t=..): <verdict>. Change something before re-running.` The third identical call adds `STOP re-running verify; decide now.` This addresses F12: in rich_3506 the gate ran 16 times in a row.

Budgets: 1,800 chars of output or less. 8 s or less typical (R-A48), and 60 s at most including base-copy creation.

### 4.9 `finalize.py`
CLI: `finalize.py` (no flags; always fixes, never only reports).
1. `hygiene_revert()`.
2. Delete untracked scratch files:
   - `repro*`, `scratch*`, `debug*`, `tmp*` and `test_*.py` at the repository root;
   - `*.log`, `*.orig`, `*.rej` and `.coverage` anywhere untracked;
   - untracked files over 1 MB;
   - untracked directories that contain their own `setup.py`, `site-packages` or `_pytest` (vendoring, like the 9.2 MB
     fastapi_14448 patch).

   Untracked `.py` files inside an existing package directory (one with tracked files) that match no scratch pattern are
   **kept**, because they are legitimate new modules.
3. Compile every changed .py. A syntax error gives `NOT READY: SYNTAX ERROR <file>:<line>`.
4. If there is no changed source file, or only protected/test changes: `NOT READY: EMPTY - no source change. Make the plan's FIX (smallest plausible version) with edit.py, then run finalize.py again.`
5. If the diff is over 200 kB or adds more than 20 files: `NOT READY: patch too large (<why>)`. The largest untracked
   additions are named.
6. Otherwise: `READY: <n> files changed (+a -d): <paths>. Next step: submit the patch.`

Budgets: 1,000 chars or less, 1.5 s or less.

### 4.10 `status.py`
CLI: `status.py`

Prints, in this order:
- `t=`;
- the helpers-installed version;
- the journal tail (8 entries: locate/verify verdicts, repro status, edits with outcome);
- `git diff --stat <baseline>`;
- the diff itself (`-U2`), capped at 1,600 chars (hunk headers only beyond that).

It gives the verifier the fixer's work without a re-read (44% of reads were cross-stage re-reads, own_data §3), and is
the amnesia recovery after compaction.

Budgets: 2,200 chars or less, 500 ms or less.

### 4.11 What was removed from v9, and why

| v9 script | fate | reason (regression test) |
|---|---|---|
| `replace.py` | merged into `edit.py --lines` | form-feed line shift, CRLF rewrite, latin-1 traceback, test-file edits, host `/tmp/_pyc_replace` (F6, R05) |
| `gate.py` | replaced by `verify.py` | PASS when nothing ran (F3), "must fix" on old-behaviour tests (F4), HEAD base (F5), `-o addopts=` and missing grader flags (competitors §5.1), no killpg |
| `check.py` | replaced by `finalize.py` | host `/tmp/_swe_best.diff` literal (R05), report-only hygiene, HEAD base (F5), flags nested `pkg/testing/` library code |
| `test.py` | folded into `verify.py --tests` and `run.py` | no killpg; no grader flags |
| `_ws.py` | folded into `_swe_common.py` | `/workspace` literal before `$PWD` (pod hazard); `TMPDIR or /tmp` wrong for a Docker image with a custom TMPDIR |
| `locate.py` | kept and extended | its docstring names the skill `swe_tools` (wrong; the kebab name is `swe-tools`): R-A14 |

### 4.12 Output budgets (after JSON double encoding each stays under run_command's 5,000-char head cap)

| helper | stdout cap (chars) | typical | perf budget |
|---|---|---|---|
| install | 400 | 180 | 300 ms |
| locate | 1,800 | 1,200 | 3,000 ms first / 300 ms cached |
| grep | 1,800 | 800 | 1,000 ms |
| view | 4,000 | 2,500 | 200 ms (+15 s for --obj) |
| edit | 1,500 | 700 | 150 ms |
| run | 2,500 | 600 | command + 50 ms |
| verify | 1,800 | 700 | 8 s typical, 60 s max |
| finalize | 1,000 | 250 | 1,500 ms |
| status | 2,200 | 1,200 | 500 ms |

---

## 5. Context budget (per stage, static and dynamic)

Fixed part of every call, in tokens, estimated at 3.4 chars per token for prose and 2.6 for escaped code:

| part | setup | locator | fixer | verifier | submitter |
|---|---|---|---|---|---|
| instruction without problem | 90 | 750 | 900 | 850 | 450 |
| `{problem_description}` (p50 473 chars, p90 1,891, max 10,095) | 0 | 140 / 560 / 3,000 | same | same | 0 |
| plan + notes | 0 | 0 | 250 | 350 | 250 |
| declarations: 8 base + 4 skill tools (about 7,200 chars) + skill boilerplate (1,333) + identity | 2,450 | 2,450 | 2,450 | 2,600 | 2,600 |
| harness prompt (problem, rules, 150-line tree) | 1,500-5,000 | 0 | 0 | 0 | 0 |
| **fixed total, p50 / max** | **4.0k / 7.5k** | **3.3k / 6.2k** | **3.7k / 6.6k** | **3.9k / 6.8k** | **3.3k** |

Dynamic part, at the prompt caps and the typical output sizes of sect. 4.12:
- **Locator.** 10 calls: locate 450, 3 views × 1,000, 2 greps × 350, repro write 350 + 150, verify 200, plan 250,
  plus about 30 of overhead per call. About 5.3k.
- **Fixer.** 12 calls: 2 views × 1,000, 3 edits × (400 out + 300 in), verify 250, grep 350, reply 100. About 4.8k.
- **Verifier.** 10 calls: status 500, verify 300, 1 repair (view 1,000 + edit 700 + verify 300), finalize 100. About 3.3k.

Peak prompt at the caps:
- p50: 8.6k / 8.5k / 7.2k for locator / fixer / verifier;
- worst (10 kB problem): 11.5k / 11.4k / 10.1k.

All of these are under 14,336, and every stage keeps at least 17k tokens of headroom to the 29,696 overflow line.
R-A34 checks this arithmetic in CI with the real instruction files and the helpers' real maxima.

If a stage runs far past its cap and in-flow compaction fires anyway:
- the instruction still carries the problem and the plan;
- the AMNESIA rule sends the model to `status.py`;
- the journal holds every edit and verdict.

That is degraded but not lost. Overflow needs 29.7k tokens, which at the helpers' caps means about 25 or more calls in
one stage. The FINISH and TIME footers (t >= 210 s) and the tool caps make that rare.

---

## 6. Where the failure modes of the ten hard facts end up

| hard fact (orchestrator) | v10 answer |
|---|---|
| 1. compaction at 14,336; post-invocation crash of Sequential roots | stage peaks of 7-12k tokens (sect. 5); the submitter keeps the last prompt small; `status.py` for amnesia |
| 2. any exception discards the patch; runaway to 4,096 costs about 110 s | tool lint (R-A03); brace lint (R-A04); `max_output_tokens` 256-3,072; bounded outputs; no ParallelAgent |
| 3. `/tmp` rewrite; install skipped in about 40% | `SWE_DIR` from `TEST_TMPDIR`; setup stage; bootstrap in every script; skills on every stage; RECOVER line; `unrewrite()` |
| 4. `edit_file` corruption; double JSON; 5,000-char head cap; reset no-op; not pip-installed | `edit.py` heredoc with an unescape tier and number-prefix stripping; caps well under 5,000; auto-revert of protected files; import-origin warning |
| 5. stage ends on text; nudge restarts; first submit+text ends the task; shared budgets | fixed-format final replies; verifier fast path plus submitter backstop; tool budget 100 |
| 6. time: +8% at most; decode is 90-97% | fewer, shorter calls (sect. 7); caps; the 5 min cap unchanged; helper-internal timeouts |
| 7. "right file, partial fix" 19/30 | repro-must-flip, the sibling sweep rule, and "every place the plan lists" |
| 8. ranked levers | repro (verify), edit channel, gate plus test revert, context plus `view --obj`, sibling sweep, hang safety, never-empty, title-to-identifier localisation. The retry lever is excluded (sect. 9) |
| 9. parallel candidates | not in v10-A |
| 10. Carson's rules | sect. 11 test registry: timing asserted, stdlib only, Docker parity, real-sandbox tests |

---

## 7. Time analysis (L4 cost model: 0.1 s per call + 28.5 ms per output token + 0.65 ms per uncached prompt token + tools; time_model §2)

### 7.1 Per stage, public-like task

| stage | calls | output tokens | uncached prompt tokens | tool seconds | L4 seconds | v9_eog projected | v4 (e74_v3) |
|---|---|---|---|---|---|---|---|
| setup | 2 | 40 | 6,000 | 0.4 | 5.7 | (inside locator) | - |
| locator | 11 | 850 | 9,500 | 5 | 36 | 64 | 40 |
| fixer | 8 | 930 | 9,000 | 4 | 37 | 58 | 65 |
| verifier (40% with 1 repair) | 5-8 | 180-700 | 6,500 | 10 | 25 | 49 | 39 |
| submitter (runs in about 5%) | 3 | 60 | 3,500 | 1 | 0.3 | - | - |
| **total** | about 30 | about 2.3k | about 31k | about 20 | **about 104 s (x1.08 model bias: about 112 s)** | 171 s | about 145-147 s (L4 replay) |

The sources of the saving:
- no malformed `edit_file` loops, which were 23% of v9_eog agent time;
- no failed helper calls (58 of 66 failed where install was skipped);
- `status.py` in place of cross-stage re-reads;
- fixed-format final replies (120 and 60 words, against an average of 336-400 tokens, which is about 20 s per task);
- lower runaway caps.

The additions: the setup stage (+5.7 s), writing the repro (+about 10 s), and verify runs (+about 10 s).

Sensitivity: the stage caps are prompt-only, and the locator ignored its cap in 80% of v9 tasks. At v9-like call counts
(locator 19, fixer 16) the estimate rises by about 40 s to about 150 s, which is +3% over v4. The ship gate R-A66
replays real canary traces against a threshold of 1.08 × v4.

### 7.2 Hidden tasks and the 12 h cliff

v4 spent about 308 s per hidden task, so hidden tasks are effectively cap-bound (own_data §2.4). The per-task wall is
then `setup 3.6 + min(agent, 300 + <=5 overshoot) + teardown <1`. It does not depend on the design as long as the cap
holds. v10 does not raise `max_time_minutes`. Its only overshoot source is a `run_command` still running at the deadline,
which is clamped to 5 s or less (`execution.py:27-40`). Skill scripts run in `to_thread` and do not block the deadline.

Worst case, every task at the cap, 600 s startup, verification excluded from the 12 h (host 743663):
- N = 120: 600 + 120 × 310 = 37,800 s = **10.5 h**, a 1.5 h margin;
- N = 130: 40,900 s = **11.4 h**, a 0.6 h margin.

If verification did count (the UNVERIFIED alternative), each task adds its verification time, and a hang is capped by
`timeout_seconds` = 120 (v4: 180):
- 120 × about 12 s mean = +0.4 h, giving 10.9 h;
- at N = 130 it is 11.8 h, which is still better than v4 under the same assumption, and v4 finished.

**v10's wall is at most v4's wall** under every assumption, because the per-task maximum is identical, the command
overshoot is identical, the verification tail is shorter, and public-like tasks finish earlier. R-A65 asserts the
arithmetic. R-A66 asserts the replayed mean.

---

## 8. Expected gain (honest)

Anchors:
- v9_eog measured 28/74 locally in one run, with ±3 run-to-run noise.
- v4 measured 26/74 locally and scored 0.12 (7/58) on the leaderboard, a transfer ratio of about 0.34.
- The union of 14 runs is 38/74, the ceiling for anything that removes variance.
- About 15-19 public tasks are unreachable from the statement. The host screened the hidden set for these, so the hidden
  set is more feasible than the public one.

Levers v10 delivers, with realistic public flips over v9_eog and the catalog's plausible tasks:

| lever | v10 mechanism | catalog expected flips (vs v4) | realistic over v9_eog | tasks |
|---|---|---|---|---|
| edit channel + loop breaker | edit.py only | 2.4 | +1.0 to +1.5 | rich_3278, rich_3052, fastapi_15588, rich_3043 |
| repro-must-flip | locator repro + verify | 4.5 | +1.5 to +2.0 | rich_4075, rich_3521, rich_4079, rich_3472, fastapi_11194 |
| regression/collection gate + test revert | verify + finalize + auto-revert | 2.8 + 0.3 | +1.0 | rich_3180, fastapi_14986, rich_4006 |
| context guard + dependency source | caps, view --obj, status | 2.1 | +0.5 to +1.0 | fastapi_14851, fastapi_5624 |
| sibling sweep | grep.py rule | 2.1 | +0.5 | fastapi_5077, rich_3480, rich_3953 |
| hang safety | killpg, run.py rule | 1.4 | +0.3 | rich_3480, rich_3772 |
| never-empty + EDIT NOW | finalize, footers | 0.7 | +0.3 | rich_3782 |
| localisation for title-plus-link | prompt rule + locate | 1.4 | +0.2 | rich_3935 |
| helpers in 100% of tasks, not 55% | setup + bootstrap | (enables the rows above) | included above | - |

The levers overlap, so the sum (about +5 to +7) overstates the result. **Expected local: 31-34/74, median 32**, a gain
of +4 over v9_eog, detectable only with at least 2 paired runs.

**Expected leaderboard: 0.14-0.17 (8-10 of 58), median about 0.15.** There is an upside to about 0.19-0.21 if the
hidden losses are mostly mechanical, as the cap saturation suggests. Under v4, most hidden tasks ran to the cap, where
the fallback diff is graded as-is. v10 makes that diff syntax-checked, free of test edits, and non-empty by t = 150 s.

**Carson's 0.30 (18/58) is not expected from this design.** It exceeds our own 14-run union ceiling after transfer
(38/74 × 0.34 ≈ 0.17-0.18) unless the hidden set rewards robustness far more than the public set does. A step change
needs capability levers: parallel candidates with a faster model if the MoE ships, or a working LoRA. Both are outside
design A.

---

## 9. Excluded on purpose (and why)

- **Parallel candidates.** `run_command` blocks the loop, budgets are shared, the KV cache at gmu 0.80 is unmeasured,
  and the gain is small (time_model §4).
- **LoopAgent retry.** It has no early exit, and the second iteration is not a fresh context (config_space #9). The
  verifier's two repair rounds are the in-context version.
- **LlmAgent coordinator root.** It adds transfer calls and unpredictability. The submitter stage already removes the
  post-invocation crash condition.
- **AgentTool.** It has no compaction and a 500-call cap.
- **Temperature change on the working stages.** It is unmeasured and would confound the robustness changes. It is an
  optional race arm.

---

## 10. Build and acceptance plan

**Build.** Write `submissions/v10/` by hand. It is small, and `make_variant.py` targets v9-style bundles. Add
`scripts/pack_bundle.py`, which strips `__pycache__`, dotfiles and extensionless files and writes a deterministic zip
with its sha256.

Gates, in order. Nothing touches a GPU or Kaggle before gate 5, and gate 5 needs Carson's explicit go:
1. `bash -n`/`shellcheck` on any shell scripts; `py_compile` of every helper; `scripts/validate.py submissions/v10`
   (official compiler).
2. `.venv/bin/python -m pytest -q tests`: the full suite, all 370 existing tests and the new `test_v10_*` files, green
   on the Mac.
3. `scripts/linux_test.sh`, extended with a v10 Docker job (`--network none`, `--cpus 2`, `--memory 4g`, TMPDIR unset,
   harness pytest-masking script applied for R-A46).
4. Offline per-task suite on the local snapshots (R-A29, R-A49, R-A54, R-A57) and the scripted-gold end-to-end
   (R-A63).
5. Only with Carson's approval: a paired race of v10 against v9_eog on 74 tasks with
   `EventsCompactionConfig(15, 2, 14336, 5)` and the L4-equivalent cap, then the R-A66/R-A68 KPIs. Optional arm: T 0.6
   on the working stages.

---

## 11. Requirement registry

Test files: `tests/test_v10_bundle.py`, `test_v10_paths.py`, `test_v10_edit.py`, `test_v10_run.py`,
`test_v10_view_locate.py`, `test_v10_verify.py`, `test_v10_finalize.py`, `test_v10_budget.py`, `test_v10_flow.py`,
`test_v10_tasks.py` and `test_v10_e2e.py`. Shared fixtures live in `tests/conftest.py` additions:
- `sandbox_repo`, a real `SubprocessManager` sandbox with a git repo;
- `skill_run`, which builds the real ADK wrapper with `SkillToolset`'s `_build_wrapper_code` for the loaded
  `skills/swe-tools` and runs it inside the sandbox;
- `no_orphans`, an autouse fixture that asserts no process of the test's sessions survives.

Tiers:
- CI: under 10 min on the Mac.
- NIGHTLY: Docker, or all local snapshots.
- REPLAY and RACE: need traces and Carson's go.

| ID | Requirement | Test | Tier |
|---|---|---|---|
| R-A01 | Tree is exactly Sequential[setup, locator, fixer, verifier, submitter], all LlmAgent, `include_contents: none`, single model `gemma-4-31b-it-qat-w4a16-ct`; compiles with the official compiler | test_v10_bundle.py::test_tree_and_official_compile (runs `scripts/validate.py`) | CI |
| R-A02 | Every stage declares BASE8 + `skills: [skills/swe-tools]`; `submit_patch` is declared on verifier and submitter only | test_v10_bundle.py::test_tool_sets | CI |
| R-A03 | No text a stage can see names an undeclared tool: its instruction, SKILL.md, the harness prompt template (`build_agent_prompt` rendered with graphs on, for stage 1), and every helper's possible output strings (AST scan of string constants for registry and known-hallucinated names such as git_grep and exit_loop). `submit_patch` is absent from all helper strings | test_v10_bundle.py::test_named_tools_declared | CI |
| R-A04 | Brace lint: instructions contain only `{problem_description}`, `{plan?}`, `{fix_notes?}` | test_v10_bundle.py::test_brace_lint | CI |
| R-A05 | Gen configs as in sect. 1.3: `include_thoughts: false` everywhere, no `thinking_level`, no `seed`, the `max_output_tokens` table, temperatures | test_v10_bundle.py::test_generation_config (also checks the compiled `extra_args` has `enable_thinking: false`) | CI |
| R-A06 | eval_config is exactly `{max_time_minutes: 5, timeout_seconds: 120, max_tool_calls: 100, max_turns: 200}` under `evaluation:` | test_v10_bundle.py::test_eval_config | CI |
| R-A07 | Packaging: allowed extensions only; no `__pycache__`, dotfiles or extensionless files; `agent.yaml` at root; deterministic zip (same sha256 twice); under 1 MB | test_v10_bundle.py::test_pack_deterministic | CI |
| R-A08 | Each instruction without the problem is 2,600 chars or fewer; worst-case stage-start prompt (10,095-char problem, 800-char plan, declarations, boilerplate, harness prompt for setup) is 8,000 tokens or fewer | test_v10_budget.py::test_static_stage_start_budget | CI |
| R-A09 | `output_key`: locator = plan, fixer = fix_notes; downstream prompts use only the `?` forms | test_v10_bundle.py::test_output_keys | CI |
| R-A10 | Only the verifier and submitter prompts mention `submit_patch`; both make it the last tool call followed by a one-line text reply; the submitter prompt is 1,200 chars or fewer | test_v10_bundle.py::test_submit_rules | CI |
| R-A11 | `install.py` copies every helper into `SWE_DIR()` (`SWE_DIR` > `TEST_TMPDIR` > `TMPDIR` > `/tmp`), atomically and idempotently, in 300 ms or less; output 400 chars or fewer names `/tmp/swe`; writes VERSION and t0 once | test_v10_paths.py::test_install_contract (parametrized over env combinations, including a Docker-like TMPDIR=/var/tmp with TEST_TMPDIR=/tmp) | CI |
| R-A12 | Any helper run through `run_skill_script` (the real ADK wrapper, dict args as `--k v`) self-installs all helpers and runs correctly with cwd set to the wrapper temp dir | test_v10_paths.py::test_skill_bootstrap_real_wrapper | CI |
| R-A13 | In a real `SubprocessManager` sandbox, after install through the real wrapper, every helper is reachable as `python3 /tmp/swe/<x>.py` from `run_command`; the same holds in Docker (no rewrite, TMPDIR unset) | test_v10_paths.py::test_reachable_subprocess; `scripts/linux_test.sh` v10 job | CI / NIGHTLY |
| R-A14 | Every stage prompt contains the identical RECOVER, AMNESIA and TIME blocks; SKILL.md opens with the exact install call and its usage lines equal each script's argparse usage; no doc names `swe_tools` | test_v10_bundle.py::test_recovery_blocks_and_skill_usage | CI |
| R-A15 | `ws()` order: SWE_WS, git toplevel of cwd, git toplevel of `$PWD`, the wrapper dir, then `/workspace` only if it is a git repo. A decoy `/workspace`-like git repo is never chosen when cwd or PWD is the sandbox workspace | test_v10_paths.py::test_ws_resolution_with_decoy | CI |
| R-A16 | No helper uses a `/tmp` or `/workspace` string literal as a path (AST: Constant nodes outside docstrings and the display strings containing `/tmp/swe`) | test_v10_paths.py::test_no_path_literals | CI |
| R-A17 | Helpers use stdlib only (imports ⊆ `sys.stdlib_module_names` plus own modules), no socket/urllib/http/ssl, parse with `feature_version=(3, 8)`, and no script name equals a stdlib module | test_v10_paths.py::test_stdlib_only_py38 | CI |
| R-A18 | `baseline()` uses `_swegemma_baseline` when present and survives an agent `git commit`; every diff-based helper agrees with `submit_patch`'s diff | test_v10_paths.py::test_baseline_after_agent_commit | CI |
| R-A19 | `edit.py` SEARCH/REPLACE applies a unique exact match; several blocks in one call are all-or-nothing | test_v10_edit.py::test_search_replace_basic_and_atomic | CI |
| R-A20 | Tiers 2-4 (rstrip/CRLF, JSON-unescape with the same transform on REPLACE, indentation-relative with dedent) each apply correctly on their fixture and report the tier name | test_v10_edit.py::test_match_tiers[12 fixtures] | CI |
| R-A21 | NO MATCH prints the closest window with numbers and the exact `--lines A-B` recipe; AMBIGUOUS lists every candidate start; the file stays byte-identical in both | test_v10_edit.py::test_nomatch_and_ambiguous_advice | CI |
| R-A22 | `--lines`, `--insert-after`, `--create` and empty-body delete, with line numbers that equal git and view.py numbering on files containing \f, \x0b, \x1c-\x1e, \x85, U+2028 and U+2029 | test_v10_edit.py::test_line_modes_and_numbering | CI |
| R-A23 | Syntax check with in-memory `compile()`: a bad edit gives REVERTED with a byte-identical file, the error line relative to the edit, and no .pyc anywhere | test_v10_edit.py::test_syntax_revert | CI |
| R-A24 | CRLF, BOM and a missing final newline are preserved; latin-1 files round-trip byte-exact; an undecodable file gives a one-line error, never a traceback | test_v10_edit.py::test_encodings | CI |
| R-A25 | `is_protected` refuses test files, conftest, pytest.ini, tox.ini, setup.cfg, pyproject.toml, `.git/`, absolute paths outside ws and `..`, each with the reason; `pkg/testing/util.py` is allowed | test_v10_edit.py::test_protected_paths[param] | CI |
| R-A26 | Loop breaker: the second identical failing input prints ALREADY TRIED plus the alternative; three consecutive failures on one file print the numbered region and the `--lines` recipe | test_v10_edit.py::test_loop_breaker | CI |
| R-A27 | `unrewrite()`: a heredoc edit through the real `SubprocessManager` whose text contains `"/tmp/x"` and `/workspace/y` writes those literals to the file, not the sandbox paths; Docker (no rewrite) is unchanged | test_v10_edit.py::test_unrewrite_real_sandbox | CI |
| R-A28 | View-number prefixes are stripped only when every line of a body carries them; a trailing `SWE_EOF` line is stripped; output is 1,500 chars or fewer with the status on line 1 | test_v10_edit.py::test_prefix_strip_and_output | CI |
| R-A29 | Every hunk of every local gold patch, applied through edit.py (both SEARCH/REPLACE and `--lines`, bottom-up), gives files byte-identical to `git apply`; new files go through `--create` | test_v10_tasks.py::test_gold_hunks_via_edit[tid] | CI (snapshots) |
| R-A30 | `edit.py` p95 is 150 ms or less on a 5,000-line file over 20 runs | test_v10_edit.py::test_edit_perf | CI |
| R-A31 | Every helper's stdout stays within its sect. 4.12 cap on adversarial inputs (a 20 kB single line, binary bytes, 10k output lines, a 10 kB query), and within 5,000 chars after json.dumps twice | test_v10_budget.py::test_output_caps[helper] | CI |
| R-A32 | The status or verdict is always line 1; run.py keeps the pytest summary line when truncating | test_v10_budget.py::test_first_line_and_summary_kept | CI |
| R-A33 | The footer shows `[t=Ns]` from the baseline-commit clock (install-stamp fallback); EDIT NOW at t >= 150 s with no source change, FINISH at 210 s, TIME at 250 s; hint text never names `submit_patch` | test_v10_budget.py::test_clock_and_hints (fake commit dates) | CI |
| R-A34 | Worst-case dynamic stage prompt (fixed part + cap calls × each helper's max typical output) is 12,000 tokens or fewer for locator, fixer and verifier, and 14,336 or fewer at the helpers' absolute caps | test_v10_budget.py::test_worst_case_stage_budget | CI |
| R-A35 | `status.py` shows the journal tail (edits, verdicts, repro), the diffstat and a bounded diff, and works with an empty journal and with a 2 MB diff | test_v10_finalize.py::test_status_journal_and_bounds | CI |
| R-A36 | `run.py` timeout kills the whole session, including `sleep 30 &` and grandchildren, returns within timeout + 2 s, keeps partial output, and does not block on a command that reads stdin | test_v10_run.py::test_timeout_killpg_and_stdin | CI |
| R-A37 | `run.py` clamps `--timeout` to 1..90 with a visible note on invalid values; background processes left by a normally-exiting command are reaped | test_v10_run.py::test_timeout_arg_and_reap | CI |
| R-A38 | Every helper that runs subprocesses (locate, view --obj, verify, finalize) finishes within its deadline + 2 s on a repo whose package has `while True: pass` at import and a repro that never ends | test_v10_run.py::test_hang_fixture_bounded[helper] | CI |
| R-A39 | Every helper-internal deadline is less than `timeout_seconds` - 10 (static check against eval_config) | test_v10_budget.py::test_deadlines_under_command_timeout | CI |
| R-A40 | `verify.py --repro-only` on an unedited tree runs the repro once and prints exactly one of: fails on original / passes on original (misses the bug) / hangs on original | test_v10_verify.py::test_repro_only_states | CI |
| R-A41 | Repro matrix FLIPPED, STILL FAILS, PASSES ON BOTH, BROKE, HANG-ORIG, HANG-NOW, each on a fixture; original from the cached base copy that includes ignored build artefacts (fixture: a module importing an untracked, git-ignored `_speedups.py`); workspace unchanged (`git status --porcelain` identical) | test_v10_verify.py::test_repro_matrix_and_base_copy | CI |
| R-A42 | An import or syntax error in a changed module gives RED IMPORT/SYNTAX with the last error line, including a NameError at import | test_v10_verify.py::test_import_error_red | CI |
| R-A43 | Discovery picks only collectable test files (never `tests/render.py`, `tests/_card_render.py` or `tools/*.py`), at most 3, related by changed symbols, module stems and imports | test_v10_verify.py::test_discovery; test_v10_tasks.py::test_discovery_recall[tid] (at least 23/39 files the test_patch edits, target 30) | CI |
| R-A44 | pytest runs use `PYTHONSAFEPATH=1 PYTHONNOUSERSITE=1 python3 -s`, `-p no:anyio -o timeout=0 -o python_classes="Test* *Test"`, JUnit XML, and never `-o addopts=` | test_v10_verify.py::test_grader_flags (captures argv/env with a fake python) | CI |
| R-A45 | Verdict semantics: UNKNOWN, never PASS or GREEN, when no test ran, on exit 2/4/5, on collection errors on both sides or on timeout (F3 regression); regressions de-flaked by one rerun; the regression wording contains the old-behaviour sentence and never "undo" or "must fix" (F4 regression) | test_v10_verify.py::test_verdict_semantics | CI |
| R-A46 | With the harness's masking script applied (copied verbatim from `container_setup.py:989-1036` into a throwaway venv), verify skips test runs with the note and still runs the repro; it never imports pytest to bypass the mask | test_v10_verify.py::test_masked_pytest (throwaway venv) + Docker job | CI / NIGHTLY |
| R-A47 | Memo: an identical (diff, repro, tests) returns SAME AS LAST RUN in one line; the third identical call adds STOP | test_v10_verify.py::test_memo | CI |
| R-A48 | verify.py finishes in 60 s or less in the worst case and in 8 s or less at p90 over the local tasks (typical); base and current run concurrently, never more than 2 processes | test_v10_verify.py::test_deadline; test_v10_tasks.py::test_verify_timing | CI |
| R-A49 | On local tasks: gold patch, no RED from imports, no F4 "undo" wording; empty diff, NO SOURCE CHANGE in under 1 s | test_v10_tasks.py::test_verify_gold_and_empty[tid] | CI (snapshots) |
| R-A50 | Import-origin check: locate.py and verify.py flag `OUTSIDE WORKSPACE` when the top-level package resolves to site-packages (fixture: an src-layout repo plus an installed copy on PYTHONPATH) | test_v10_view_locate.py::test_import_origin_warning | CI |
| R-A51 | `finalize.py` reverts tracked protected edits, deletes the scratch patterns and vendored trees, **keeps** an untracked new module inside a package, and prints READY with the diffstat | test_v10_finalize.py::test_hygiene_matrix | CI |
| R-A52 | `finalize.py` prints NOT READY for an empty diff, a test-only diff, a syntax error left by raw `sed`, and a diff over 200 kB or with more than 20 new files, each with its fixed message | test_v10_finalize.py::test_not_ready_cases | CI |
| R-A53 | `edit.py` and `verify.py` revert tracked protected-file edits made by raw shell, so the working-tree diff taken at timeout carries no test edits | test_v10_finalize.py::test_auto_revert_via_edit_and_verify | CI |
| R-A54 | On each local task, with an agent edit to the test file the test_patch touches injected: after finalize, `git diff --binary <baseline>` passes `git apply --check` on a fresh baseline and the task's test_patch applies on top | test_v10_tasks.py::test_test_patch_applies_after_finalize[tid] | CI (snapshots) |
| R-A55 | No helper contains destructive workspace git (`reset --hard`, `checkout .`, `checkout -- .`, `clean -f` without paths, `stash`); the only checkout form is path-scoped to protected files | test_v10_paths.py::test_no_destructive_git (AST/regex scan) | CI |
| R-A56 | After every helper runs in a git fixture, `git status --porcelain` is unchanged except for the intended edit (no scratch, no `__pycache__`, no `.pytest_cache`) | test_v10_paths.py::test_workspace_clean_after_helpers[helper] | CI |
| R-A57 | `locate.py` recall on the local tasks is not below v9: gold file at rank 1 in at least 21/40, top 3 in at least 28/40, top 8 in at least 34/40; ranks `docs_src/` below the package on the fastapi fixture | test_v10_tasks.py::test_locate_recall (aggregate) | CI (snapshots) |
| R-A58 | locate.py first call 3 s or less on a 3k-file synthetic repo, cached call 300 ms or less, partial index and valid output under a forced 1 s parse deadline | test_v10_view_locate.py::test_locate_perf_cache_deadline | CI |
| R-A59 | locate, grep and view survive hostile trees (SyntaxError, py2 print, non-UTF-8, a 2 MB file, a symlink loop, a vendored `site-packages`) with deterministic output across 3 runs | test_v10_view_locate.py::test_hostile_tree | CI |
| R-A60 | view.py modes (range, symbol including async and `Class.method`, outline, `--obj` for an installed stdlib object) give numbered git-consistent lines, 100 lines or fewer, origin shown, `--obj` 15 s deadline | test_v10_view_locate.py::test_view_modes | CI |
| R-A61 | grep.py: 40 hits or fewer, 5 or fewer per file, tests excluded unless `--tests`, enclosing def shown, 1 s or less | test_v10_view_locate.py::test_grep_bounds | CI |
| R-A62 | Mock-LLM flow through the compiled bundle with `EventsCompactionConfig(15, 2, 14336, 5)` and a scripted OpenAI-compatible server: (a) the happy path ends at the verifier's submit+text and the submitter never runs; (b) a verifier reply without submit, then the submitter submits; (c) setup replying READY without a call, then the locator's "can't open file" recovery installs; (d) a compaction forced mid-fixer raises nothing; (e) in every scenario the last LLM call's prompt is under 14,336 tokens; (f) any undeclared tool the script tries is caught by the R-A03 lint beforehand | test_v10_flow.py::test_flow[a..e] | CI |
| R-A63 | Scripted-gold end-to-end in the real `Evaluator` (subprocess sandbox, local snapshot, mock model): gold applied through edit.py plus verify, finalize and submit gives resolved=True on 3 tasks; a scripted raw `sed` edit of the hidden test file is reverted and the task still resolves | test_v10_e2e.py::test_scripted_gold[3 tids] | NIGHTLY |
| R-A64 | Linux parity: the full `test_v10_*` suite passes in `python:3.12-slim` with `--network none --cpus 2 --memory 4g`, TMPDIR unset and TEST_TMPDIR=/tmp | `scripts/linux_test.sh` v10 job | NIGHTLY |
| R-A65 | 12 h fit: 600 + N × (60 × max_time_minutes + 10) ≤ 0.95 × 43,200 for N = 130 | test_v10_budget.py::test_fits_12h | CI |
| R-A66 | Replayed L4 time of v10 canary traces (sect. 7 model × 1.08) is at most 1.08 × v4's replay on the same tasks, with no task over cap + 10 s | test_v10_replay.py::test_projected_time (needs traces) | REPLAY |
| R-A67 | Performance budgets per helper, asserted on the largest local snapshot: install 300 ms, edit 150, view 200, grep 1,000, status 500, finalize 1,500, locate 3,000 first / 300 cached | test_v10_budget.py::test_perf_budgets | CI |
| R-A68 | Race acceptance (Carson's go only): v10 is at least v9_eog + 3 on the paired 74, with 0 context-overflow and 0 unknown-tool errors, install/bootstrap success in at least 98% of tasks, and malformed `edit_file` calls at 1 or fewer per task on average | test_v10_replay.py::test_race_kpis | RACE |

### 11.1 v9 bugs, each with its regression test

| bug (source) | regression test |
|---|---|
| gate PASS when nothing ran (F3) | R-A45 |
| gate "must fix/undo" on old-behaviour tests (F4) | R-A45, R-A49 |
| HEAD instead of `_swegemma_baseline` (F5) | R-A18 |
| replace.py CRLF, form feed, latin-1, test-file edits (F6) | R-A22, R-A24, R-A25 |
| run.py leaks process groups (F7) | R-A36, R-A37 |
| host `/tmp` literals in check.py and replace.py (test_plan R05) | R-A16 |
| gate `-o addopts=` and missing grader flags (competitors §5.1) | R-A44 |
| `_ws.py` `/workspace` before `$PWD` | R-A15 |
| locate.py docstring skill name `swe_tools` | R-A14 |
| install skipped: 20 tasks never called it; 4 malformed calls (F2) | R-A11..R-A14, R-A62c |
| gate re-run loops, 16 times (F12) | R-A47 |
| heredoc `/tmp` rewrite mutates code (R06) | R-A27 |

---

## 12. Risks

1. **The setup stage misfires.** It explores or replies without calling install. The bootstrap and RECOVER paths then
   carry install, at the cost of one failed call. The race KPI in R-A68 measures it.
2. **The model still uses the declared `edit_file`.** Loops remain possible at a lower rate, and there is no callback to
   stop them. The alternative, detaching the tool, trades that for an unknown-tool crash, which loses the whole task.
3. **SEARCH/REPLACE fit with Gemma 4.** If blocks fail often, the numbered NO MATCH hint and `--lines` carry the edit.
   That still beats `edit_file`, where 39-52% of calls were malformed.
4. **Wrong repros.** A repro that asserts a wrong expected value steers the fixer toward the wrong behaviour. Mitigations:
   the prompt demands the issue's exact values, PASSES ON BOTH is flagged, and STILL FAILS allows only 2 repair rounds.
5. **Time.** The stage caps are prompt-only. With v9-like overruns, v10 is about +3% over v4 (sect. 7.1), still under
   +8%. R-A66 must pass before shipping.
6. **Scorer unknowns.**
   - Docker 2 vCPU slows verify and locate. The deadlines bound that.
   - The compaction threshold may be 32,768. v10 is built for the no-compaction case anyway.
   - pytest may be masked. Then verify degrades to repro only.
   - The Python version is unknown. The helpers target 3.8+.
7. **Base-copy fidelity** for exotic builds (generated code outside git, compiled extensions over 50 MB). Base failures
   are reported as UNKNOWN, not as regressions.
8. **Hygiene false positives.** A legitimate new file matching a scratch pattern at the repository root, such as
   `debug.py`, would be deleted. The patterns are root-only, and no gold patch in the 74 adds such a file.
9. **Hints end work early.** WRAP-UP hints could cut off a slow but correct trajectory. The thresholds (150/210/250 s)
   sit after every public L4 solve's last edit (median 62 s, maximum 218 s).
10. **The pipeline restarts on a nudge.** It re-runs all 5 stages. This happens in 1 of 51 tasks.
11. **Noise.** ±3 tasks per run means a +4 median gain needs at least 2 paired runs to confirm. A single race can mislead
    in both directions.
