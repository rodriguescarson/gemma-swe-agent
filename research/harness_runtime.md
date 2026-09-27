# Harness runtime: every behaviour that decides pass/fail

Scope: swegemma 0.2.7, adk_submission 0.2.11, adk_eval_core 0.1.0, google-adk 1.36.1, litellm 1.102.1
(versions from the `*.dist-info` dirs). All paths below are relative to
`SP=/Users/carson/Projects/gemma-swe-agent/.venv/lib/python3.12/site-packages` unless absolute.

Evidence labels:
- **CODE**: read in the installed source (file:line given).
- **EXP**: reproduced locally in the scratchpad with the harness venv or git.
- **DATA**: counted in our own run artifacts (paths and counts given).
- **UNVERIFIED**: inference or organiser documentation only.

Run artifacts used for DATA: pod runs `eval/race1/runs/{r_v4,r_v9_c,r_v9_eo,r_v9_eg,r_v9_og,r_v9_eog,c_v9_eg,c_v9_eog}`,
`eval/eval3/eval/runs/{p_v4,p_v6,p_v7,p_v8}`; Kaggle L4 runs `eval/kaggle/e74_v2`, `eval/kaggle/e74_v3`,
`eval/kaggle/oracle_all`, `eval/kaggle/rescore_fair` (all under `/Users/carson/Projects/gemma-swe-agent/`).

---

## 0. The ten things that matter most (ranked by expected effect on v10)

1. **On Kaggle, token-threshold compaction wipes `include_contents: none` stages to their instruction.**
   Any LLM call whose preceding observed prompt was >= 14,336 tokens triggers an in-flow summary; the
   summary event is authored `user`, so a `none` agent's "current turn" restarts at the summary and it
   also loses the 5 "retained" events. Kaggle traces show the fixer dropping from ~14K to 1.2K-2.3K
   prompt tokens and the locator re-running `load_skill` + `install.py` from scratch. 29/74 tasks (v3)
   and 56/74 (v2) were compacted; compacted tasks resolved 3/29 vs 19/45 (v3). Our pod runs never
   compact (swegemma CLI sets no compaction), so **the race does not model this at all**. (Section 5.4)
2. **Any exception other than timeout/turn-limit discards the patch, including a submitted one and all
   edits on disk.** Seen causes: context overflow (38 pod task-runs, 11 of them had real edits),
   hallucinated tool names (3 Kaggle task-runs), plus code-level risks (missing `{state}` var,
   ParallelAgent ExceptionGroup, malformed tool-arg JSON). (Section 1)
3. **`edit_file` is the most fragile tool: 18-22% of calls arrive with corrupted argument keys and
   39-52% of all edit_file calls fail on a missing `old_string`.** The model closes a string value with a
   backtick instead of the `<|"|>` delimiter and the gemma4 parser folds the rest into garbage keys.
   `run_command` (one string arg) is corrupted in 0/1001 (r_v4) and 0/1252 (e74_v3) calls. Missing-arg
   errors cost no tool budget, so the model loops: 51 task-runs had >= 20 such errors, 0 of them
   resolved, and they account for 21/25 turn-budget exhaustions. (Section 3.4)
4. **Tool results are JSON-encoded twice before the model sees them.** A `"` in source code is shown as
   `\\\"` and a newline as `\\n`; copying code into `old_string` then fails (edits whose old_string
   contains backslash escapes fail 92-97%). (Section 3.1, EXP)
5. **The verification "reset test files" step is a no-op.** `git checkout HEAD -- <list>` always
   includes `sitecustomize.py`, `usercustomize.py`, `_swegemma_stubs.py`; they are not in HEAD, and git
   aborts the whole checkout on one bad pathspec (EXP). So edits to existing test files survive into
   verification; all 5 "Failed to apply test_patch" failures are agent edits to the file the hidden
   test_patch touches. (Section 7.2)
6. **`run_command` keeps only the first 5,000 chars of stdout and of stderr, with no truncation marker,
   and duplicates the output on non-zero exit** (`error_message` plus `details`). 51/162 pytest calls on
   Kaggle (e74_v3) hit the cap, so the pass/fail summary was cut off. Doubling also pushes stages toward
   the 14,336-token compaction line. (Section 3.2)
7. **A SequentialAgent stage ends on its first text-only reply; the next stage sees only the previous
   stage's last event plus its own instruction; `submit_patch` followed by any text reply ends the
   whole task.** (Section 6)
8. **Kaggle LLM cost model: ~1.4 s per step plus ~35 ms per output token; prompt size up to 16K adds
   only ~0.7 s** (3,068 steps, e74_v3). Time is steps and output tokens, not context. (Section 9)
9. **Verification runs every test in each file the test_patch touches, under the harness's own
   `pytest.ini`** (repo pytest config ignored), requires exit 0 + clean JUnit + every test function the
   test_patch adds to pass unskipped, with `timeout_seconds` from eval_config as the pytest timeout.
   (Section 7)
10. **Subprocess backend: the repo is not pip-installed; it imports only through `PYTHONPATH=<workspace
    root>`; dependencies come from the host interpreter's site-packages; `/tmp`, `/workspace`,
    `/usr/local/bin`, `/wheels` are rewritten in command text only.** (Section 2)

---

## 1. What happens to the patch in each end state

`agent_patch` starts as `''` (`swegemma/harness/agent_runner.py:209`) and is only assigned after the
agent loop returns normally or via the two caught exception types (`agent_runner.py:741-758`).
`Evaluator.evaluate_task` skips verification whenever `agent_error` is set **and** the patch is empty
(`swegemma/evaluate.py:324-351`).

| End state | Code path | Patch used | Verified? |
|---|---|---|---|
| `submit_patch` then a text reply from any agent | break at `agent_runner.py:569-579`, then `:635-637` | `ctx.submitted_patch`, the diff **at the time of the last submit** (`tools/execution.py:81-94`) | yes |
| `submit_patch` called, invocation keeps going, more edits, no second submit | `agent_runner.py:758-760`: fallback diff is skipped when `patch_submitted` is True | stale submitted diff; later edits lost | yes |
| `submit_patch` with an empty diff | `patch_submitted=True`, `submitted_patch=''`, no error | empty | yes, fails (nothing applied) |
| Session timeout (`asyncio.timeout`, deadline set at `:439-443`) or elapsed check (`:581-589`, `:639-645`) | `TimeoutError` caught at `:741-746` | submitted diff if any, else fallback `git add -N . && git diff --binary _swegemma_baseline` (`:760-776`) | yes if non-empty |
| Turn limit (ADK `max_llm_calls`, `RunConfig(max_llm_calls=remaining)` at `:516`) | `LlmCallsLimitExceededError` caught at `:741-753` | as above | yes if non-empty |
| Tool-call budget exhausted | tools return `BudgetExceeded` (`context.py:470-481`); invocation continues until the model stops; loop breaks at `:647-660` | as above | yes if non-empty |
| 3 consecutive nudges with no tool call | break at `:680-686` | fallback diff | yes if non-empty |
| Fallback diff empty and no earlier error | `agent_error='Agent completed execution without calling submit_patch.'` (`:777-781`) | none | no |
| **Any other exception** from `runner.run_async` (context overflow, unknown tool, KeyError, ExceptionGroup, JSONDecodeError, vLLM down) | outer `except Exception` at `:799-801` | **`''` even if submit_patch succeeded and even if the working tree holds a correct fix** | **no** |
| `ContainerSetupError` | re-raised `:797-798`, caught by worker `evaluate.py:495-543` | none | no |

Evidence (DATA): across the 14 pod runs, 38 task-runs ended `Sandbox execution error:
litellm.ContextWindowExceededError`, all with `agent_patch_size 0`; 11 of those 38 had at least one
successful edit before the crash, 0 had submitted. Log line (`eval/race1/runs/r_v4/run.out`):
"you requested 4096 output tokens and your prompt contains at least 28673 input tokens" followed by
"Non-retryable model error". On Kaggle L4, 3 task-runs were lost to `Sandbox execution error: Tool
'search_similar_code' not found` (e74_v3 rich_4076, fastapi_14419) and `Tool 'git_grep' not found`
(e74_v2 rich_3676).

Why each crash is not retried:
- `ModelRetryPlugin._is_retryable_error` (`adk_eval_core/plugins/retry_plugin.py:54-117`) retries only
  429/5xx, rate-limit, connection and timeout classes. `ContextWindowExceededError` (HTTP 400) is not
  retryable, so `on_model_error_callback` returns None and ADK re-raises. LiteLLM itself retries it 5
  times first (`num_retries=5`, harmless but wasted round trips).
- The prompt ceiling is `32768 - max_output_tokens`: with v4's `max_output_tokens: 4096` the prompt may
  not exceed 28,672 tokens.
- Unknown tool name: `google/adk/flows/llm_flows/functions.py:490-504` raises `ValueError` unless an
  `on_tool_error_callback` returns a response. `compile_submission` is called without a callback
  registry (`agent_runner.py:334-346`), so submissions cannot install one.
- Instruction templating: every `{identifier}` (also `{{identifier}}`, regex `{+[^{}]*}+`) is replaced
  from session state; a missing non-optional key raises `KeyError`
  (`google/adk/utils/instructions_utils.py:81-123`). Session state holds only `problem_description`,
  plus `hints` when non-empty (`agent_runner.py:392-397`); 0/129 public tasks have hints. v4/v9 prompts
  use only `{problem_description}`, `{plan?}`, `{fix_notes?}` (safe).
- ParallelAgent: branches run in `asyncio.TaskGroup` (`google/adk/agents/parallel_agent.py:71`). A
  branch exception is re-raised as an `ExceptionGroup`, which the harness's
  `except (TimeoutError, LlmCallsLimitExceededError)` does not match, so even a turn-limit inside a
  parallel branch discards the patch (CODE, Python semantics; not observed in our runs).
- Malformed tool arguments: `google/adk/models/lite_llm.py:1726-1731` does `json.loads(arguments)`
  with no guard (CODE; never observed, vLLM emits valid JSON).
- Post-invocation compaction with a non-LLM root: `google/adk/apps/compaction.py:223-236` raises
  `ValueError('No LlmAgent model available...')` when `app.root_agent` is a SequentialAgent and no
  summarizer has been set yet (`:475-490` passes `agent=app.root_agent`). The summarizer is stored on
  the shared config object after the first in-flow compaction, so this can only fire before any
  in-flow compaction has happened in the scoring process (CODE; not observed).

---

## 2. Sandbox: paths, environment, interpreter

### 2.1 Which backend the scorer uses
UNVERIFIED but strongly indicated: `EvalConfig.sandbox` docs say `'subprocess' (Kaggle/notebooks)`
(`swegemma/config.py:98`); `SubprocessManager.exec` hard-codes Kaggle wheel paths
(`swegemma/sandbox/subprocess.py:462-469`); Kaggle notebooks have no Docker daemon; our Kaggle kernel
(`scripts/make_eval_kernel.py:92`) and competitor notebooks use `sandbox='subprocess'`. Everything
below describes the subprocess backend unless marked Docker.

### 2.2 Layout (per task, twice: agent sandbox A and verification sandbox B)
`SubprocessManager.start` (`swegemma/sandbox/subprocess.py:311-412`) creates
`<mkdtemp>/swegemma_sandbox_<id>_*/{workspace,tmp,wheels,venv}`. The venv is built from the harness
interpreter (`venv.create(system_site_packages=True, with_pip=True)`, `:331-356`), and a
`_host_env.pth` listing every `site-packages` on the harness `sys.path` is written into it (`:389-400`).

### 2.3 Command rewriting (`subprocess.py:432-481`), command text only
1. The literal sandbox root is protected by a sentinel.
2. `/./tmp`, `/../workspace` etc. are normalised: `(?<![\w.-])/(?:\.\.?/)+(tmp|workspace|usr/local/bin|wheels)(?![\w.-])` -> `/\1`.
3. `(?<![\w.-])/tmp(?![\w.-])` -> `<root>/tmp`; same pattern for `/workspace` -> `<root>/workspace`,
   `/usr/local/bin` -> `<root>/venv/bin`, `/wheels` -> `<root>/wheels` if it holds `*.whl`, else the first
   existing of `/kaggle/input/competition-data/wheels`, a Kaggle dataset path, `build/wheelhouse`,
   `data/wheels`, `wheels`, `/tmp/wheelhouse`.
- Matches `/tmp/x`, `"/tmp"`, `=/tmp`, `file:///tmp`; not `/var/tmp`, `/tmpdir`, `/tmp.txt`, `a/tmp`.
- It rewrites **everything in the command string**: heredoc bodies, `python3 -c` source, `sed`
  scripts, `echo` text. Code written into the repo through `run_command` that contains one of these
  literals gets the absolute sandbox path baked in (0/129 gold patches add such a line, so rare; DATA:
  2 r_v9_eg patches contain `swegemma_sandbox` paths, both inside scratch log files).
- It does **not** touch file contents written by `write_file`/`edit_file`, nor the source of skill
  scripts. That is the v2-v8 helper bug: a skill script wrote to the real `/tmp/swe`, while
  `python3 /tmp/swe/x.py` in `run_command` was rewritten to `<root>/tmp/swe/x.py`.
- Docker backend: no rewriting at all; `/tmp` and `/workspace` are real (`swegemma/sandbox/docker.py:693-712`).

### 2.4 Environment of every command (`subprocess.py:483-501`, `adk_eval_core/sandbox/subprocess_sandbox.py:24-54`)
- Passed through from the host only if set: `PATH, LANG, LC_ALL, TERM, USER, LOGNAME, SYSTEMROOT,
  LD_LIBRARY_PATH, TMPDIR, TEST_TMPDIR`. Everything else (COLUMNS, FORCE_COLOR, CUDA_*, KAGGLE_*) is dropped.
- Set: `HOME=TMPDIR=TEST_TMPDIR=<root>/tmp`, `PYTHONNOUSERSITE=1`, `VIRTUAL_ENV=<root>/venv`,
  `PATH=<root>/venv/bin:<dir of harness python>:$PATH`, `PYTHONPATH=<root>/workspace`.
- `cwd=<root>/workspace`; `/bin/bash -c <cmd>`; new session; stdout/stderr piped and decoded
  `utf-8, errors='replace'`; each stream capped at 10 MB. **stdin is not redirected** (inherits the
  harness's stdin; a command that reads stdin may block until the timeout; UNVERIFIED what stdin is on
  Kaggle).
- The whole process group is SIGKILLed in `finally` after **every** command
  (`subprocess_sandbox.py:140-144`): background servers never survive to the next call. `cd` and
  `export` never persist between calls.
- bash exports `PWD` even under the sanitised env (EXP: `env -i ... bash -c 'cd /usr && python3 -c
  "print(os.environ[\"PWD\"])"'` prints `/usr`), so skill scripts can recover the workspace from `PWD`.
- No network isolation in the subprocess backend (CODE: nothing unshares or blocks sockets). The
  harness prompt still says the environment is offline.

### 2.5 Python, pytest and the repo
- `python`/`python3` = the venv interpreter = same version as the harness interpreter (pod: 3.12;
  Kaggle: the kernel's python, UNVERIFIED version). `pip` exists but has no index.
- `pytest` is not in `venv/bin`; the first `pytest` on PATH is the host script whose shebang is the host
  interpreter. `python3 -m pytest` and `pytest` resolve the same packages (host site-packages).
- **The repo is not installed in the subprocess backend**: `install_editable_package` and
  `install_test_dependencies` return immediately for `SubprocessManager`
  (`swegemma/harness/container_setup.py:512-513`, `:529-530`). The package imports only because
  `PYTHONPATH=<workspace root>` puts the checkout first. Consequences: a `src/` layout repo cannot be
  imported by anyone (UNVERIFIED whether hidden repos use it); `importlib.metadata.version(pkg)` and entry
  points report the host's copy (the harness itself ships rich, fastapi via ADK, requests, httpx).
- Dependency versions are the host's, not the repo's pins. Only 74/129 public tasks pass with the gold
  patch on the Kaggle image (`eval/kaggle/oracle_all/results.jsonl`: rich 42/48, fastapi 31/67,
  requests 1/13, httpx 0/1). Our pod `scripts/run_eval.py` replaces this with a pip install of the repo
  and its test deps, yet the Kaggle rescore of the same patches agreed closely (v4 27/74 Kaggle env vs
  26/74 pod; `eval/kaggle/rescore_fair/results.jsonl`).
- Setup before the timer: wheels, snapshot extraction, `.git/info/exclude` append of
  `__pycache__/ *.pyc .pytest_cache/ *.egg-info/ build/ dist/ .coverage .adk_exec_*.py`
  (`container_setup.py:498-503`), harness `pytest.ini` + `conftest.py` written into the workspace
  (`:864-938`), then `git add -A && git commit -m baseline && git tag -f _swegemma_baseline`
  (`:575-582`). The snapshot's `.git/config` carries `user.name=Agent`, `user.email=agent@eval`
  (read from `data/raw/snapshots/httpx_3672.tgz`), so commits work with `HOME=<tmp>`.
- The initial prompt includes `find . -maxdepth 3 ... | sort | head -150` (`agent_runner.py:312-317`).

---

## 3. Built-in tools

All nine tools are closures over one `SwegemmaContext` (`swegemma/tools/__init__.py:34-46`), so every
agent, sub-agent and AgentTool shares the same sandbox, workspace, tool counter and clock.

### 3.1 How every tool result reaches the model (EXP)
The swegemma tools return JSON **strings**. ADK wraps a non-dict result as `{'result': <string>}`
(`google/adk/flows/llm_flows/functions.py:1116-1117`) and LiteLLM serialises that dict again with
`json.dumps(..., ensure_ascii=False)` (`google/adk/models/lite_llm.py:546-559`, `:800-814`, role
`tool_responses` for gemma4). Reproduced with the harness venv: a `read_file` of
`def f():\n    return "x"\n` (24 chars) reaches the model as
`{"result": "{\"status\": \"ok\", \"content\": \"def f():\\n    return \\\"x\\\"\\n\"}"}` (87 chars).
Every `"` in code becomes `\\\"`, every newline `\\n`. Skill-tool results are dicts
(`google/adk/tools/skill_toolset.py:530-536`) and are escaped only once.

DATA: `edit_file` calls whose `old_string` contains `\"`, `\'` or `\n` escapes failed 148/153 (r_v4),
82/87 (r_v9_eog), 138/149 (e74_v3), 194/202 (p_v4). Patches that added backslash-escape lines absent
from the gold patch: 2 (r_v4), 3 (r_v9_eog), 1 (p_v4); a Kaggle trace (fastapi_15800) shows the model
running `sed` to strip `\\\"` it had written into source.

### 3.2 `run_command(command)` (`swegemma/tools/execution.py:15-68`)
- Budget-gated, counts 1 tool call.
- Timeout = `min(timeout_seconds, max(5, int(remaining_session_seconds)))` (`:27-40`); on timeout the
  process group is killed and **all partial output is discarded**; the reply is only
  `TimeoutExceeded: Command timed out after N seconds` (`:43-47`). The session continues.
- Output: `stdout[:5000]` and `stderr[:5000]` separately, **head only, no marker** (`:49-51`).
- Exit 0: `{"status":"ok","stdout","stderr","exit_code":0}`.
- Exit != 0: `{"status":"error","error_type":"CommandError","error_message": stderr or stdout,
  "details":{"stdout","stderr","exit_code"}}` (`:53-62`): the same text appears twice (up to 15,000
  chars before the double escaping of 3.1).
- DATA: mean serialized size of CommandError replies 1,099 chars (r_v4) and 2,353 (e74_v3) vs 707 / 768
  for ok replies; 43 (r_v4) and 95 (e74_v3) error replies duplicated stdout into error_message; pytest
  output reached the 5,000 cap in 9/102 (r_v4), 3/110 (r_v9_eog), 51/162 (e74_v3) pytest calls.
- helpers_v9 already exit 0 and print their own status line (`helpers_v9/run.py:15-27`,
  `replace.py:15-31`, `gate.py:16-46`), which avoids the duplication. Keep that invariant.

### 3.3 `read_file(filepath, start_line=None, end_line=None)` (`swegemma/tools/workspace.py:53-140`)
- Budget-gated. Only paths inside `/workspace` (absolute `/workspace/...` or relative); any other
  absolute path, e.g. `$TMPDIR/swe/last.log`, raises "Path traversal detected" (`:17-50`), so scratch
  files must be read with `run_command`.
- 150 lines and 10,000 chars max (`budget.py:31-32`). Content has **no line numbers**.
- Bug: when the 10,000-char cap cuts the slice, `end_line` is not reduced (`:117-135`), so the reply
  claims lines it did not show.
- Decoding `errors='replace'`; `start_line > end_line` returns a ValueError response; empty file returns
  `content=''`.

### 3.4 `edit_file(filepath, old_string, new_string, allow_multiple=False)` (`workspace.py:179-251`, `adk_eval_core/editing/edit.py`)
- Budget-gated. Errors: file missing, file empty (use write_file), `old_string` empty, identical strings
  ("No changes to apply", `edit.py:323-329`), not found, ambiguous.
- Tiers (`edit.py:308-354`):
  1. **exact**: `content.count(old)`; replaces substrings, even mid-line (`:109-135`).
  2. **flexible**: whole-line window compare, first with `rstrip()`, then `strip()` (`:138-236`); the
     replacement is re-indented to the window's minimum indent plus
     `max(0, new_ref_indent - old_ref_indent)` (`:192-214`), so **a dedent can never be expressed
     through this tier**; blank lines in `new_string` lose their whitespace.
  3. **regex**: tokens of `old_string` joined by `\s*` (or `\s+` between two word tokens), anchored to a
     line start and a line end (`:239-305`); `\s*` crosses newlines.
- No escape processing anywhere: `\x1b`, `\u1234`, `\n` in the arguments are whatever the vLLM gemma4
  parser produced. Gemma 4 tool strings are raw (`<|"|>...<|"|>` delimiters, visible in unparsed text
  e.g. r_v4 trace_fastapi_14077), so any backslash the model adds is literal.
- `allow_multiple` is not type-coerced: the string `"false"` is truthy.
- File read with `errors='replace'` and written back as UTF-8 (`workspace.py:212-229`): editing a
  non-UTF-8 file silently replaces every undecodable byte with U+FFFD.
- Returns a unified diff capped at 5,000 chars.
- **Argument corruption (DATA)**: edit_file calls with keys outside the schema: 142/665 (r_v4), 72/411
  (r_v9_eog), 153/698 (e74_v3). Outcomes in r_v4: missing-arg 336, not-found 230, ok 84, identical 15;
  e74_v3: missing-arg 360, not-found 192, ok 136. Raw example (r_v4 trace_fastapi_15589): the
  new_string value ends in `` ...get_validation_alias(field))`,old_string: `` and the next key is
  `"if convert_underscores"`: a backtick closed the string and the parser folded `old_string:` into the
  previous value. Other tools: run_command 0/1001 (r_v4), 0/1252 (e74_v3); write_file 0/70, 0/35;
  run_skill_script 0/30, 0/46; read_file 32/597, 34/852 (keys such as `end_line"`).
- FunctionTool returns `{"error": "Invoking edit_file() failed as the following mandatory input
  parameters are not present..."}` before the budget-gated body runs
  (`google/adk/tools/function_tool.py:180-190`): **no tool call is charged, only a turn and ~1.5 s**.
  DATA across 10 pod runs: 51 task-runs had >= 20 missing-argument errors; 0 resolved; they contain 21
  of the 25 turn-budget exhaustions and 18 of the 37 timeouts. Worst single tasks: 134 and 141 repeated
  failing calls.

### 3.5 `write_file(filepath, content)` (`workspace.py:143-176`)
Budget-gated; `/workspace` only; `mkdir -p` of the parent; UTF-8; no size cap; overwrites. The file is
staged in a host temp dir and copied with `shutil.copy2`, so an existing executable file is reset to
the temp file's mode (0644 under the usual umask) and the diff carries a mode change.

### 3.6 `submit_patch()` and `get_status()` (`execution.py:71-127`)
- Both `budget_gated(count_tool_call=False)`: they skip the tool and turn checks but still fail once
  the session clock has run out (`context.py:522-540`), and still cost an LLM turn.
- `submit_patch`: `git add -N .` then `git diff --binary _swegemma_baseline || git diff --binary HEAD`;
  a non-zero exit returns `GitDiffError` and leaves `patch_submitted` False.
- `get_status` returns tool_calls_used/remaining, max_tool_calls, patch_submitted, patch_size,
  time_seconds_remaining, max_time_minutes, agent_elapsed_seconds, max_turns, command_timeout_seconds.
  It does not report turns used.
- When `max_tool_calls >= 20` and <= 10 calls remain, every budget-gated reply gets a `budget_warning`
  field (`swegemma/tools/base.py:34-56`).
- Graph tools (`get_code_neighbors`, `search_similar_code`, `get_code_subgraph`) are budget-gated and
  return error JSON on failure (`swegemma/tools/graph.py:46-223`); they never crash.

### 3.7 Tool execution model
- Budget-gated tools hold `ctx.tool_lock` (an RLock) while they run (`base.py:66-80`).
- The harness passes no `tool_thread_pool_config`, so ADK calls synchronous tools directly on the event
  loop thread (`function_tool.py:223-236`, `functions.py:971-981`). A running command blocks the whole
  loop: the `asyncio.timeout` deadline cannot fire until it returns, and several function calls in one
  model response run one after another despite `asyncio.gather` (`functions.py:387-412`).
- `run_skill_script` is the exception: it runs in `asyncio.to_thread` (`skill_toolset.py:494-498`), so
  two skill calls in one response run concurrently and a timeout can cancel the await while the thread
  keeps running.

---

## 4. Skills

Compiled into an ADK `SkillToolset(skills, code_executor, script_timeout, additional_tools)`
(`adk_submission/resolvers/tools.py:253-264`); script_timeout = `timeout_seconds`, default 300
(`agent_runner.py:322-333`).

- **Tools added**: `list_skills`, `load_skill`, `load_skill_resource`, `run_skill_script`
  (`skill_toolset.py:938-943`). Only `run_skill_script` is charged against `max_tool_calls` (through
  `budget_check_fn=context.check_budget`, `adk_eval_core/sandbox/base.py:179-186`); the other three are
  free of the tool budget but each costs a turn.
- **Every LLM call of an agent that has skills** gets the 1,333-char skill boilerplate appended to its
  system instruction (`skill_toolset.py:61-88`, `:1062-1082`).
- `load_skill` is not required before `run_skill_script` (activation only gates
  `adk_additional_tools`, `:956-1010`), so installing helpers can be a single call.
- `run_skill_script(skill_name, file_path, args, short_options, positional_args)`
  (`:776-874`, argv building `:638-700`): `args` as a list is used verbatim; as a dict it becomes
  `--k v` pairs; `short_options` -> `-k v`; `positional_args` are appended after `--`.
- Execution (`base.py:176-223`): the wrapper embeds **all** files of the skill (scripts, references,
  assets) as a Python dict literal, is written to `/workspace/.adk_exec_<hex>.py` (git-excluded) and run
  as `python3 /workspace/.adk_exec_<hex>.py`, then deleted. The wrapper materialises the skill into
  `tempfile.TemporaryDirectory()` (which lands in `$TMPDIR`), **chdirs into it**, sets `sys.argv`, and
  runs `.py` scripts in-process via `runpy.run_path`; `.sh`/`.bash` run via `subprocess.run(timeout=...)`.
  So: cwd is the temp dir, not the repo; `sys.path[0]` is the workspace root (the wrapper's directory),
  not `scripts/`; the script source is never path-rewritten (use `os.environ["TMPDIR"]` /
  `tempfile.gettempdir()` and `os.environ["PWD"]`, never a literal `/tmp`).
- Timeout: `max(1, min(script_timeout, remaining session seconds))` (`base.py:187-197`).
- Output: stdout and stderr returned in full (only the 10 MB process cap), **not** truncated to 5,000.
  A chatty script can overflow the context in one call. Status is `error` when stderr is set and stdout
  empty, `warning` when both are set.
- A non-zero `SystemExit` is re-raised, the wrapper exits with that code, and stderr becomes
  `Command failed with status=error, exit_code=N`.
- `load_skill_resource(skill_name, file_path)`: path must start with `references/`, `assets/` or
  `scripts/`; returns the whole text; binary files are injected into the next request as inline data
  (`:291-439`).
- DATA (the v2-v8 bug): `python3 /tmp/swe/locate.py` failed "can't open file" in 81/85 v4 pod calls and
  137/157 Kaggle calls; trace e74_v3 fastapi_11194 step 3 shows the rewritten path
  `/tmp/swegemma_sandbox_.../tmp/swe/locate.py`.

---

## 5. Turns, nudges, invocation boundaries, compaction

### 5.1 Turn counting
- `context.llm_calls_used` += 1 for every non-partial event authored by an agent that has content and
  is not purely function responses (`swegemma/context.py:276-298`). Events come through the display
  plugin, which AgentTool inner runners inherit (`google/adk/tools/agent_tool.py:236-249`), so inner
  agent calls count too. Summariser calls (compaction) are not agent events and do not count.
- After each `run_async` the harness recounts session events and keeps the max (`agent_runner.py:595-633`).
- Once `llm_calls_used >= max_turns`, budget-gated tools return `Turn budget exhausted`
  (`context.py:483-494`), and ADK raises `LlmCallsLimitExceededError` when the invocation exceeds
  `remaining_turns` (`google/adk/agents/invocation_context.py:82-97`). AgentTool inner runs use a fresh
  default `RunConfig` (500 calls) and are not bound by the ADK limit, only by the tool-side check.

### 5.2 What ends an agent, a stage, an invocation
- An LlmAgent's loop stops on the first event that `is_final_response()`: no function calls, no
  function responses, not partial (`google/adk/flows/llm_flows/base_llm_flow.py:862-875`,
  `google/adk/events/event.py:83-98`). That includes a text-only reply, an empty reply, and a reply whose
  tool call failed to parse (text containing `<|tool_call>`): agent steps with unparsed tool-call text:
  1 (r_v4), 1 (r_v9_eog), 5 (e74_v3), 6 (p_v4). Examples: `call,edit_file{...` (p_v4
  fastapi_13537) and `call:python3 /tmp/swe/replace.py ...` used as a tool name (r_v9_eog rich_3043).
- `skip_summarization=True` on an AgentTool makes its function-response event final
  (`event.py:91-92`, `agent_tool.py:212-213`): the **calling** agent stops right after the sub-agent
  returns, which ends the invocation and costs a nudge round.
- Invocation end: the root agent finishes, the harness breaks on submit+text (`agent_runner.py:569-579`;
  breaking closes the generator, so post-invocation compaction is skipped), an exception, or a limit.

### 5.3 Nudges (`agent_runner.py:677-739`)
If an invocation ends without `submit_patch` and with budget left, the harness sends a new user
message and starts a new invocation. `consecutive_nudges` resets to 0 whenever the pass contained a
function call made while tool budget remained; after 3 consecutive nudges it stops. Messages: unclosed
`<|tool_call>` in the last text, `finish_reason` containing MAX_TOKENS/LENGTH, or the generic "Please
continue your work...". Each nudge is a new invocation, which matters for sliding-window compaction and
for which agent runs (6.1). DATA: nudges were rare with v4-style pipelines (1 task-run per run in r_v4,
r_v9_eog, e74_v3) because the verifier almost always submits (46, 49, 58 submit_patch calls).

### 5.4 Events compaction (the Kaggle-only behaviour)
Config: `App(events_compaction_config=...)` only if the scorer passes one (`agent_runner.py:408-411`).
The organiser README says the scorer uses `compaction_interval=5, overlap_size=2,
token_threshold=14336, event_retention_size=5` (`data/HARNESS_README.md:556-559`); our Kaggle kernel
and two competitor notebooks derived from the Getting Started code use interval 15 with the same
threshold/retention (`scripts/make_eval_kernel.py:95`; scratchpad `nb/gemma-4-ast-graph-augmented-...`).
The threshold and retention agree in both sources (UNVERIFIED against the real `scripts/inference.py`).
The swegemma CLI sets no compaction (`swegemma/cli.py:141-152`), so **none of our pod runs compacted**.

Mechanics (CODE):
- **In-flow, before every LLM call** (`google/adk/flows/llm_flows/compaction.py:35-54`, ordered
  before the contents processor in `single_flow.py:40-49`): if the latest `usage_metadata.prompt_token_count`
  anywhere in the session (any agent) is >= 14,336, all raw events after the previous compaction except
  the last 5 (moved earlier so no function response is orphaned) are summarised
  (`apps/compaction.py:239-296`, `:389-472`).
- **Post-invocation** (`google/adk/runners.py:598-610`): the same token check unless in-flow already
  compacted this invocation, then the sliding window: once `compaction_interval` new invocations exist,
  whole invocations (the newest included, plus `overlap_size` older ones) are summarised with no
  retention (`apps/compaction.py:493-695`).
- **Summariser**: `LlmEventSummarizer(llm=agent.canonical_model)`, one extra non-streamed call with the
  default prompt; it formats **only `part.text`** of each event (`apps/llm_event_summarizer.py:73-80`):
  function calls and tool outputs (file contents, test results, diffs) are dropped from the summary.
  The compaction event is authored `'user'` (`:134`).
- In `include_contents: default` agents the summary is materialised at its end timestamp and the
  retained raw events follow (`contents.py:325-418`).
- In `include_contents: none` agents, `_get_current_turn_contents` restarts at the latest event authored
  `user` or by another agent (`contents.py:542-582`). The compaction event is authored `user` and is
  appended after the retained events, so the agent sees **only the summary**: the retained 5 events and
  the previous stage's handoff message are gone. The instruction (with `{problem_description}`,
  `{plan?}`) is rebuilt every call and survives.
- AgentTool inner runners get no compaction (Runner built with `agent=`, `app=None`, `runners.py:177`,
  `:1429-1431`): an AgentTool sub-agent can still overflow and crash the task.

DATA (Kaggle traces, prompt drop > 30% within one agent after > 8K tokens): 56/74 task-runs (e74_v2)
and 29/74 (e74_v3), vs 1/51 (r_v4), 1/51 (r_v9_eog), 2/74 (p_v4) on the pod. Examples (e74_v3):
fastapi_14301 fixer 14,340 -> 1,236; fastapi_14306 fixer 15,298 -> 2,309; fastapi_14851 fixer
15,219 -> 1,406; fastapi_14616 locator 14,851 -> 2,118 followed by `load_skill` and `install.py` again.
Max prompt on Kaggle 19,398 (v2) / 18,661 (v3) vs 28,596-28,668 on the pod, which is why Kaggle shows
no context-overflow crashes.
Resolution: e74_v3 compacted 3/29 vs not 19/45; e74_v2 12/56 vs 7/18. Confounded by difficulty: the
pod control (no compaction) gives 6/23 vs 12/28 (r_v4), 8/24 vs 13/27 (r_v9_eog), 7/34 vs 19/40
(p_v4) for tasks whose max prompt was >= 14,336 vs below. The Kaggle gap (10% vs 42%) is larger than
the pod gap (21-33% vs 43-48%): suggestive that compaction itself costs tasks, small n.

---

## 6. Multi-agent semantics under this harness

### 6.1 SequentialAgent (v4, v9)
- One invocation runs the sub-agents in order on the same session, sandbox, workspace, tool counter and
  clock (`google/adk/agents/sequential_agent.py:60-90`). There is no early exit other than a paused
  invocation; every stage runs unless the harness breaks out.
- A stage ends on its first text-only/empty/unparsed reply (5.2); no nudge happens inside the pipeline.
  DATA: text-only agent steps per stage in r_v4: locator 54, fixer 47, verifier 47 over 51 tasks
  (roughly one final reply per stage, as intended).
- `submit_patch` followed by a text reply from **any** stage ends the task immediately
  (`agent_runner.py:569-579`); later stages never run.
- On a nudge the Runner looks for an agent to resume. A sub-agent qualifies only if every ancestor has
  `disallow_transfer_to_parent`, which exists only on LlmAgent (`google/adk/agents/llm_agent.py:307`),
  so under a SequentialAgent root the Runner falls back to the root (`runners.py:1082-1156`) and **the
  whole pipeline restarts from stage 1** with the nudge text as its only user message (1 such restart
  per run in r_v4, r_v9_eog, e74_v3).
- `include_contents: none` (`contents.py:71-86`, `:542-677`): a stage sees its instruction plus
  everything from the latest event authored `user` or by another agent. For stage 1 that is the harness
  prompt (problem, budgets, workspace tree, rules); for later stages it is **only the previous stage's
  last non-empty event**, rendered as `For context: [locator] said: ...` (thoughts dropped, tool calls
  and results rendered as text), followed by the stage's own events. The harness prompt (budget, tree,
  rules) is invisible to stages 2+.
- `output_key` stores the stage's final text (non-thought text parts joined) in session state
  (`llm_agent.py:830-870`); later instructions read it with `{plan?}`. With `none`, the fixer sees the
  plan twice (instruction and handoff event).

### 6.2 LoopAgent
Runs sub-agents repeatedly until `max_iterations` (capped by submission limit 500,
`adk_submission/builders/workflows.py:124-131`) or an event with `actions.escalate`
(`google/adk/agents/loop_agent.py:60-120`). No harness-specific behaviour; submit+text still ends the
task at once.

### 6.3 ParallelAgent
Each sub-agent gets branch `<parent>.<child>` (`parallel_agent.py:35-49`), so histories are isolated,
but the sandbox, files, tool counter and clock are shared. Tools are effectively serialised (3.7), so
parallelism only overlaps LLM calls. Any branch exception becomes an ExceptionGroup and discards the
patch (1). Branches editing the same files race.

### 6.4 AgentTool
New Runner and in-memory session per call; parent state copied in (minus `_adk*`), state deltas
forwarded back; the tool result is the sub-agent's last content text (`agent_tool.py:203-296`); plugins
propagate (display, retry); no compaction; `max_llm_calls` 500; tools and budget shared with the parent.

### 6.5 Generation settings
Defaults when an agent has no `generate_content_config`: `max_output_tokens 16384`,
`thinking_budget 4096` (`swegemma/config.py:59-67`). `thinking_budget` is **not** forwarded to vLLM;
only `include_thoughts`/`thinking_level` are bridged into `chat_template_kwargs.enable_thinking`
(`adk_submission/resolvers/generation.py:61-116`); the server default is `enable_thinking: True`.

---

## 7. Verification (sandbox B)

### 7.1 Pipeline (`swegemma/harness/verification.py:223-559`)
1. Fresh sandbox, same setup as A including the harness `pytest.ini`/`conftest.py` and the
   `eval_baseline` commit (`:262-305`).
2. Apply `agent_patch` with `apply_patch_in_container` (`container_setup.py:585-856`): `git apply`,
   `-3`, `--ignore-space-change --ignore-whitespace`, `--recount`; the same on a symlink-normalised copy;
   `-p0` variants; then GNU `patch -p1`/`-p0` (`--batch --forward`, `-l`) gated by `--dry-run`. (The
   README's `--unsafe-paths` is not in the code.) Paths with `..` or leading `/` are rejected. Any
   failure -> "Failed to apply agent patch", not resolved (`:325-351`).
3. Reset list = files touched by the test_patch + protected files touched by the agent patch + the
   five fixed names (`:355-415`). Protected: `conftest.py pytest.ini pyproject.toml tox.ini setup.cfg
   .pytest.ini sitecustomize.py usercustomize.py _swegemma_stubs.py`, `*.pth`, `test_*.py`, `*_test.py`,
   any `.py` under a `tests/`, `test/` or `testing/` directory (`:60-83`).
4. Apply `task.test_patch` with the same helper; failure -> not resolved (`:417-463`).
5. Rewrite `pytest.ini` (overwrite) and prepend the hook header to `conftest.py` (`:474-480`).
6. `cd /workspace && PYTHONSAFEPATH=1 PYTHONNOUSERSITE=1 python3 -s -m pytest <.py files of the
   test_patch, conftest.py excluded> --junitxml=/tmp/_swegemma_junit_<id>.xml -p no:anyio -o timeout=0
   -o python_classes="Test* *Test" -q`, timeout = `timeout_seconds` (`:483-503`).

### 7.2 The reset is a no-op (EXP + DATA)
`git checkout HEAD -- a b sitecustomize.py` in a scratch repo printed "pathspec 'sitecustomize.py' did
not match" and restored nothing (exit 1); `git clean -f -- tests/test_new.py sitecustomize.py` still
removed the untracked file (exit 0). None of `sitecustomize.py`, `usercustomize.py`,
`_swegemma_stubs.py` is created by setup (`data/sandbox_setup.py` has none, and setup.py is skipped for
subprocess sandboxes anyway), so the checkout always aborts. Net effect:
- tracked files the agent modified (existing tests, `pyproject.toml`, `setup.cfg`, `tox.ini`) **stay
  modified** in verification;
- untracked protected files the agent created (e.g. `tests/test_repro.py`, root `test_fix.py`) **are
  deleted**;
- `pytest.ini` is rewritten anyway; `conftest.py` keeps the agent's content after the header.
DATA: 22 task-runs in which the agent patch touched a file that the test_patch also touches: 5
"Failed to apply test_patch" (c_v9_eg fastapi_14492, r_v9_eo fastapi_15588 and fastapi_14077, r_v9_c
fastapi_14077, p_v6 rich_3454), 11 other failures, 6 resolved (27%), vs 197/509 (39%) for task-runs
that did not touch those files.

### 7.3 Pass criterion (`:505-542`, `:144-220`)
Resolved only if all hold:
- pytest exit code 0;
- the JUnit file exists and parses, total > 0, passed > 0, failures == 0, errors == 0;
- every required node passes and is not skipped or failed anywhere. Required nodes =
  `FAIL_TO_PASS + PASS_TO_PASS` if present (they are not in `data/tasks.jsonl` and the secret hydration
  only fills `test_patch`/`patch`, `evaluate.py:165-178`), else every `test_*` function that the
  test_patch **adds** (`+def test_x(` lines), else hunk-header/context names (`:86-127`); matching
  accepts parametrised ids and numeric suffixes (`:130-141`);
- stdout contains "passed" and not "0 passed", "no tests ran", "collected 0 items".
Consequences: every test in each touched file must pass, not only the new ones; skipping a required test
fails; the harness `pytest.ini` applies (`filterwarnings` ignores Deprecation/User warnings, `-p no:anyio`,
`python_files = test_*.py *_test.py`), not the repo's pytest config.

### 7.4 Timing
`timeout_seconds` from eval_config is both the per-command timeout in sandbox A and the verification
pytest timeout (`evaluate.py:64-79`, `verification.py:498-503`). Kaggle oracle verification (whole
`verify_task`, gold patch) took 3.7 s min, 6.8 s median, 9.0 s p90, 12.6 s max over the 74 valid tasks
(`eval/kaggle/oracle_all/results.jsonl`). Exit 124 (verification timeout) happened in 22 pod task-runs,
all on rich_4006, rich_3772, rich_3480 and fastapi_14448, whose gold patches verify in 5-9 s: agent
patches that hang (r_v4 rich_4006 log shows `FFFFF` then the kill). `-o timeout=0` disables
pytest-timeout, so one hanging test fails the task.

### 7.5 What enters the patch
`git add -N .` + `git diff --binary <baseline>`: modified tracked files, new untracked files not ignored
by `.gitignore` or `.git/info/exclude`, mode changes (repo `filemode = true`), symlinks, binary content.
Empty directories do not. Files in git-ignored paths (the exclude list above plus the repo's
`.gitignore`) silently do not. Commits made by the agent are still included (diff is against the tag);
`git stash`, `git checkout -- f`, `git reset --hard` remove work. The diff is decoded with
`errors='replace'`, so changes to non-UTF-8 text files cannot round-trip.
DATA: 55/290 race1 patches carried scratch files at the repo root (`repro.py` 25, `reproduce_issue.py`
13, ...); r_v9_eg fastapi_14448 was a 9.2 MB patch that vendored `_pytest/` into the repo root, which
then shadows the real pytest through `PYTHONPATH` in verification.

---

## 8. Other ways points are lost silently

- **Advertised but unattached tools**: `build_agent_prompt` appends a "Code Intelligence Tools" section
  naming `search_similar_code`, `get_code_neighbors`, `get_code_subgraph` whenever graph and embedding
  files > 100 bytes exist for the repo (`agent_runner.py:144-181`), regardless of the agent's tool list.
  Calling one that is not attached crashes the task (1). Only the first stage sees this prompt under
  `include_contents: none`; later stages can still copy tool names from `For context:` renderings.
- **Budget exhaustion is not an exit**: after the tool budget is spent, every budget-gated call returns
  an error and the model keeps spending turns and time until it stops (27 BudgetExceeded replies in
  r_v4 traces).
- **Near-deadline overshoot**: run_command gets at least 5 s even with less remaining; the loop-blocking
  sync tool delays the deadline further (3.7).
- **Scratch files in /workspace** become part of the patch; root-level `test_*.py` are deleted in
  verification, others are applied as-is.
- **Instruction braces**: any `{identifier}` in an instruction is a state lookup (1).
- **12-hour wall clock**: v4 used ~10.4 h for ~120 tasks with a 5-minute cap, i.e. ~312 s per task, of
  which setup+verification overhead is small (Kaggle e74_v3: task total minus agent span median 7.1 s,
  p90 20.0 s). 43,200 s / 120 tasks = 360 s per task, so `max_time_minutes` cannot rise much above 5
  without risking a run with no score.
- **Setup cost outside the agent budget but inside 12 h**: two venv creations with ensurepip per task
  (`subprocess.py:331-356`) and possibly a copy of the wheel directory into each sandbox when none of the
  fallback wheel paths exists (`container_setup.py:393-413`, `subprocess.py:458-472`); not controllable
  by the submission.
- **`/workspace` symlink on a host** (e.g. a pod volume): `_resolve_workspace_path` resolves `/workspace`
  on the host before mapping (`workspace.py:24-35`); if the host path is a symlink, file tools map to the
  wrong place. Pod-only fidelity risk, UNVERIFIED on our pods.

---

## 9. Measured cost model on Kaggle 4x L4 (DATA, e74_v3, 3,068 LLM steps)

Latency from the previous observation to the next agent step:
- by prompt size: 0-4K 1.49 s, 4-8K 1.57 s, 8-12K 2.03 s, 12-16K 2.15 s, 16-20K 5.9 s (n=18);
- by completion tokens: 0-99 1.41 s, 100-199 3.64 s, 200-299 7.07 s, 300-399 9.57 s, 500-599
  15.54 s, 700-799 21.43 s, >= 1000 49.3 s.
So roughly **1.4 s per step + 35 ms per output token**; prefix caching makes prompt size nearly free
below the compaction line (`cached_tokens` is reported as 0 by LiteLLM, so the caching itself is
UNVERIFIED; the latency pattern implies it). Per task, e.g. fastapi_11194: 259K prompt tokens and only
3,003 completion tokens over 39 steps. First agent step arrives 3.5-21 s after trace start (median
5.7 s, includes setup). A 300 s budget therefore buys about 60-100 steps if replies stay short; one
500-token `edit_file` costs ~17 s.

---

## 10. Fidelity gaps between our local evaluation and the scorer

| Aspect | Pod race (`scripts/run_eval.py` -> swegemma CLI) | Kaggle scorer (per README / our kernel) |
|---|---|---|
| Events compaction | none (`cli.py:141-152`) | threshold 14,336 / retention 5 (interval 5 or 15) |
| Repo install / deps | pip `-e` + test deps from wheels (`run_eval.py:11-51`) | not installed; host site-packages |
| Hardware | 2x H100 (v9_eog 135 s/task mean, v4 111 s) | 4x L4 (v3 163 s/task mean) |
| Max prompt seen | 28.6K (overflow crashes) | 19.4K (compaction instead) |
Rescoring the same patches in the Kaggle env matched the pod closely (v4 27/74 vs 26/74), so the
environment gap is small for public repos, but the compaction gap is not modelled at all. Race 1
rankings (all paired sign tests p > 0.14) should be treated as provisional until re-run with the
scorer's compaction config.

---

## 11. Design rules for v10 that follow from the code

1. Run local races through `Evaluator(EvalConfig(..., events_compaction_config=EventsCompactionConfig(
   compaction_interval=15, overlap_size=2, token_threshold=14336, event_retention_size=5)))`
   exactly as `scripts/make_eval_kernel.py:95` does; the CLI path cannot reproduce the scorer.
2. Treat 14,336 prompt tokens (vLLM count) as the per-stage context budget. Keep tool outputs short:
   every helper prints a one-line status plus a bounded body (<= ~2,500 chars), exits 0, and logs the
   full output to `$TMPDIR/swe/last.log`.
3. Put everything a stage needs after an amnesia event into its instruction via `{problem_description}`
   and `output_key` state (`{plan?}`), and keep a progress file in `$TMPDIR` that the stage can re-read.
4. Prefer single-string-argument actions: `run_command` with a heredoc into a helper (line-range
   replace with syntax check) instead of `edit_file`; `write_file` only for new files. Remember heredoc
   text is path-rewritten (2.3).
5. Never make the model copy existing code: print code with line numbers from a helper, edit by line
   range, verify by re-printing.
6. Attach the three graph tools to every agent that can see the harness prompt, or to all agents (cost:
   declaration tokens). Avoid ParallelAgent. Never use a non-optional `{var}` other than
   `{problem_description}`.
7. Forbid editing existing test files, `conftest.py`, `pytest.ini`, `pyproject.toml`, `setup.cfg`;
   write repro scripts and tests under `$TMPDIR`; delete root-level scratch files before submitting.
8. Only the last stage has `submit_patch`; it must be the last tool call, followed by a one-line text
   reply. Every other stage should end with a single text reply that is its handoff (captured by
   `output_key`).
9. Gate on the whole related test files under the harness `pytest.ini`, with a short timeout (hangs
   fail verification).
10. Keep `timeout_seconds` >= 60 (it is also the verification timeout; public verifies take <= 13 s,
    hidden repos unknown), `max_time_minutes` at 5 (12 h budget), `max_output_tokens` around 2,048 (Kaggle
    completions stayed <= ~1,000 tokens) to widen the overflow margin to 30,720 prompt tokens.
11. Skills: call `run_skill_script` directly (no `load_skill`), resolve paths from `TMPDIR` and `PWD`,
    cap output inside the script, attach skills only to the stage that installs helpers (the skill
    boilerplate is added to every call of that stage).

---

## 12. Open questions (not answerable from the local source)

- Which sandbox backend and which exact `EventsCompactionConfig` the real `scripts/inference.py` uses
  (README says interval 5; Getting Started-derived notebooks say 15; both say 14,336 / 5).
- The Python version, installed packages and stdin of the Kaggle scoring process (they decide which
  hidden repos are importable and whether stdin-reading commands hang).
- Whether hidden repos have graph/embedding files (decides whether the harness prompt advertises the
  graph tools there) and whether any use a `src/` layout (unimportable without installation).
- How vLLM 0.19.1's gemma4 tool parser treats a string value closed with the wrong delimiter; the
  symptom (garbage keys, lost `old_string`) is measured, the parser code was not available locally.
- Whether calling the local vLLM endpoint from a skill script (possible in the subprocess backend, which
  has no network isolation) is allowed by the competition rules; it bypasses the harness's turn
  accounting, so treat it as off-limits unless the rules say otherwise.
