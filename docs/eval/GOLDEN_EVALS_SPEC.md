# Golden evals for the v10 pipeline: spec v1.1 (2026-09-29)

Status: design, not built. Owner of the build: three components (section 12). Everything here was checked against the
installed harness (`.venv/lib/python3.12/site-packages`: swegemma, adk_submission, adk_eval_core, google/adk), the v10.1
bundle, the race-2 and Kaggle-L4 traces, and a live `agents-cli 1.7.0` probe (section 11 lists what the probe found).
v1.1 re-verified v1 against the same sources and fixed seven defects; section 13 lists every change and its evidence.

## 0. Purpose

A full faithful run is 74 tasks, about 3.5 h on 4x L4, and its resolved count moves by about +-3 tasks between identical
runs. Plumbing is fixed (helper availability 100 %, malformed edits 0.05/task); FIX QUALITY is the binding constraint.
We need per-stage evals that score a prompt change in minutes, with confidence intervals and a paired comparison, and
that isolate the stage being changed:

| Suite | Live stage | What it isolates | Headline metric |
|---|---|---|---|
| L | locator | finding the code and writing a failing reproduction from the real issue | `l_all_gold_files_named` |
| F | fixer | fix quality given a PERFECT plan | `f_hidden_pass` (fixer pass@1 given a golden plan) |
| V | verifier | keep a good tree, repair a bad one, fill an empty one, then finalize and submit | `v_variant_goal` |
| X | every live stage | protocol health (tool names, malformed calls, compaction line, runaway outputs) | `x_clean` |

Method follows the installed skill `~/.agents/skills/google-agents-cli-eval` (SKILL.md, references/dataset_schema.md,
references/metrics-guide.md): an EvaluationDataset per suite and split, decoupled generate then grade, grading with
`agents-cli eval grade --traces DIR --config CONFIG` using LOCAL deterministic code metrics (`custom_function_file`,
execution local, no GCP), `agents-cli eval compare`, and a stratified HOLDOUT that is never used while tuning prompts.
Our agent needs a per-task sandbox, so WE generate traces with our own runner and write them in the skill's trace
format; agents-cli only grades and compares. Statistics that agents-cli does not do (Wilson CIs, paired exact sign test)
come from our summary script (section 8).

## 1. Inputs (read-only for every component)

| Input | Content | Notes |
|---|---|---|
| `data/kaggle_valid_ids.txt` | the 74 task ids | rich 42, fastapi 31, requests 1 |
| `data/tasks.jsonl` | `problem_statement`, `patch` (gold), `test_patch` (hidden tests), `repo`, `hints_text` | gold patches are plain `--- a/`/`+++ b/` diffs, .py only, 1 to 26 files; no hints_text in the 74 |
| `research/task_catalog.json` | per task: `gold_files`, `root_cause`, `one_line_solution` (4-24 words), `best_solution`, `hidden_test_demands`, `locating_signals`, `tags`, `new_api_names`, ... | `hidden_test_demands` is NEVER used in model-visible text |
| `data/raw/snapshots/<tid>.tgz` | repo snapshot with .git | 40 of 74 local: rich 39 (missing rich_4076, 4077, 4079), requests 1, fastapi 0 |
| `~/.cache/g4/kpar/{rich,requests}` | Kaggle-parity venvs (python 3.12, pins = Kaggle pip_freeze) | fastapi venv absent: `scripts/build_kpar.sh fastapi` needs the network once (Carson's call) |
| `eval/race2/eval/runs/r2_v10_1/` | race-2 v10 run: `task_results.jsonl`, `traces/trace_<tid>.json` (ATIF-v1.7), `patches/` | 25/74 resolved. NOTE: its helpers print `swe-tools v10.0`, the bundle is now v10.1 |
| `eval/race2/eval/runs/r2_v9_eog_1/` | race-2 v9_eog run | 24/74 resolved |
| `eval/kaggle/g4-l4-v4/results.jsonl`, `eval/kaggle/g4-l4-v9-eog/results.jsonl` | Kaggle L4 runs (`id`, `resolved`, `patch`) | 29/74 each |
| `submissions/v10/` | the bundle under test (VERSION v10.1) | never edited; runs use a copy (`tests/v10_support/sandbox.copy_bundle`) |

Existing infrastructure REUSED, never edited by these components: `scripts/run_eval.py` (compaction, L4 clock scale,
faithful-env hooks), `tests/v10_support/sandbox.py` (`copy_bundle`, `run_eval_cli` pattern, `trace_observations`),
`tests/v10_support/mock_llm.py` (`MockLLM`, `Route`, `Request`, step builders, `estimate_prompt_tokens`,
`COMPACTION_LINE`), `tests/v10_support/tasks.py` (`load_task`, `parse_patch`, `base_ws`, `fresh_ws`, `sandbox_env`,
`install_helpers`, `run_helper`, `harness_apply`, `mini_verify`, `hidden_claim_nodes`, `hidden_outcomes`, `KNOWN_*`),
`scripts/replay_l4.py` (KPI definitions: `TOOLS`, `HELPER_NAMES`, `HELPER_SHELL`, `TOOLCALL_TEXT`, `CRASH`,
`is_protected`, `scratch_files`), `tests/test_v10_flow.py` (`gold_steps`, `hidden_claims` ideas), `eval/compare.py`
(`wilson`), `scripts/ab_l4_decide.py` (`sign_p`). If a genuine bug is found in one of these, write the failing
regression test in the component's own test file, mark it `xfail(strict=True)` with the reason, and report it; do not
edit the shared file.

## 2. Split: DEV and HOLDOUT

One split per TASK, shared by all suites, so a holdout task never appears in any dev suite.

- Strata: `repo` (rich / fastapi / requests) x race-2 outcome over `r2_v10_1` and `r2_v9_eog_1`: `both` resolved,
  `one` resolved, `none`.
- Seed: the string `golden-v1`. Order inside a stratum: ascending `sha256(f"golden-v1:{tid}")` hex. No RNG, so the
  split is identical on every platform and Python version.
- Holdout size per stratum: `k = floor(n * 0.25 + 0.5)`; the first k in that order are holdout, the rest dev.
- Result with the current inputs (the builder must reproduce exactly this):

| stratum | n | holdout | holdout ids |
|---|---|---|---|
| fastapi/both | 9 | 2 | fastapi_11194, fastapi_14492 |
| fastapi/none | 15 | 4 | fastapi_15800, fastapi_14616, fastapi_14258, fastapi_15661 |
| fastapi/one | 7 | 2 | fastapi_5624, fastapi_15589 |
| requests/none | 1 | 0 | |
| rich/both | 10 | 3 | rich_3882, rich_3905, rich_3006 |
| rich/none | 28 | 7 | rich_4076, rich_3052, rich_3930, rich_3942, rich_3061, rich_3934, rich_3944 |
| rich/one | 4 | 1 | rich_3454 |
| total | 74 | 19 | dev 55 |

- Runnable today (snapshot and kpar venv present): dev 30 (rich 29, requests 1), holdout 10 (rich). The split never
  changes when snapshots arrive; only `runnable` does.
- File: `eval/golden/split.json`, committed:
  `{"schema": "golden-split-v1", "seed": "golden-v1", "holdout_frac": 0.25, "rule": "floor(n*0.25+0.5) by sha256 order",
  "inputs": {"<path>": "<sha256>"}, "strata": {"rich/none": {"n": 28, "holdout": [...], "dev": [...]}, ...},
  "tasks": {"<tid>": {"split": "dev|holdout", "repo": "rich", "race2": "none"}}}` (keys sorted, 1-space indent, trailing
  newline).
- Holdout protocol: the runner refuses `--split holdout` without `--holdout-reason TEXT`, and appends one line per holdout
  run to `eval/golden/holdout_log.jsonl` (`ts`, `suite`, `bundle_sha`, `run_id`, `reason`). The summary prints the number
  of holdout looks. Tune on dev only; grade holdout once when a candidate is final.

## 3. Suites and cases

Case id: `L__<tid>`, `F__<tid>`, `V__<tid>__gold|wrong|empty`; a run adds the sample suffix `__s<k>` (`k = 0..samples-1`).

### 3.1 L (locator)
- Input: the real issue. Setup is scripted; the locator is LIVE; everything after it is scripted to end the run at once.
- Cases: 74 (dev 55, holdout 19).
- Checks: plan names every gold file; plan names the gold function(s); reply format `FILES:`/`CAUSE`/`FIX`/`REPRO`/`TESTS`;
  plan length; a reproduction was written and printed `fails on original` (reported on the `reproducible` subset,
  section 4.2); the reproduction is VALID (fails on the original tree and passes on the gold tree, executed in the kpar
  venv); the stage ended by a text reply; helper clock at the end <= 90 s; tool calls <= 12; LLM calls; tokens.

### 3.2 F (fixer; isolates fix quality)
- Input: the issue, plus a GOLDEN PLAN (section 4.1) delivered exactly as a real locator reply, plus the helper state a
  real locator leaves (locate index, validated golden repro when one exists). The fixer is LIVE; the verifier is
  scripted to call `submit_patch` at once, so the graded patch is the fixer's raw tree.
- Cases: 74 (dev 55, holdout 19). Only `gradable` cases (gold passes the hidden tests twice in kpar, the empty patch
  fails) count toward fix metrics.
- Checks: the diff touches every gold file; applies to the original snapshot through the harness apply pipeline;
  every changed .py compiles; HIDDEN TESTS PASS with the task's test_patch in the task's kpar venv (headline:
  `f_hidden_pass`, fixer pass@1 given a perfect plan); no protected file; no scratch file; notes format; first edit time;
  verify rounds; calls; tokens.

### 3.3 V (verifier)
- Inputs: the issue, the golden plan, and a tree state produced by a scripted fixer that replays a recorded patch
  through the real helpers: (i) `gold`: the gold patch; (ii) `wrong`: a real unresolved patch from the race traces
  (section 4.3); (iii) `empty`: no change. The verifier is LIVE; if it does not submit, the submitter is scripted to
  submit the tree as the verifier left it (and `v_submitted_by_verifier` records the miss).
- Cases: 74 gold + 74 empty + one `wrong` per task that has a qualifying wrong patch.
- Checks: final diff passes hidden tests; per variant goal: (i) stays passing, (ii) passes (repaired), (iii) non-empty
  source change; not worse than the pre-state (hidden nodes passing did not drop, still applies and compiles);
  `finalize.py` ran before `submit_patch`; the verifier itself submitted; no protected/scratch files; calls; time.

### 3.4 X (cross-cutting, computed on every trace, live stage only)
Invented tool names = 0; bare helper names used as tool names or shell commands = 0; malformed tool calls; `edit_file` /
`write_file` use (the prompts forbid them); edit.py failures; tool calls written as text (`<|tool_call>`); live calls at or
above the 14,336 compaction line; compaction events; runaway outputs (finish_reason `length`, or completion tokens >= 95 %
of the stage's `max_output_tokens`); `can't open file`; crash class; live-agent restarts; live stage capped at helper
t=300 (reported, not part of `x_clean`). Definitions port
`scripts/replay_l4.py` so race-2 KPIs and golden metrics agree on the same trace (component c tests this).

## 4. Golden data (component a)

### 4.1 Golden plan
The exact format the locator prompt asks for (`submissions/v10/prompts/locator.md` step 4), under 120 words:

```
FILES: <path>:<start>-<end> (<function>)[, <path>:<start>-<end> (<function>) ...]
CAUSE: <one sentence>
FIX: <what to change, with the exact names, messages and signatures the issue gives>
REPRO: fails on original | none
TESTS: <an existing test file> | none
```

- FILES: one entry per (gold file, innermost enclosing def/class of the changed lines) on the ORIGINAL file. Range =
  first..last changed old-side line (for a pure insertion: the line after which it is inserted). Function = qualname
  from `ast` of the original file (`Class.method`), `module level` when none. Several hunks in one function merge into
  one entry. A gold file that does not exist yet: `<path> (new file)`. When the snapshot is absent, the function comes
  from the hunk header context (`@@ ... @@ def name(`), and the task records `plan_basis: "hunk_header"`. More than 6
  entries: the first 6, then `and N more places in <files>`, then ` (<qualnames>)` naming the functions of the cut
  entries that the plan does not name anywhere else (2026-09-30: without it the golden plans of fastapi_14306,
  fastapi_15800, rich_3061 and rich_3930 missed gold functions and the oracle L check failed).
- CAUSE: the first sentence of `root_cause`, cut to 35 words at a word boundary.
- FIX: `one_line_solution`.
- REPRO: `fails on original` when a validated golden repro exists (4.2) and the scripted locator's run of it printed
  `fails on original` (the scripted step fills this line from the real tool output), else `none`.
- TESTS: the first test_patch file that exists in the original tree; else `tests/test_<stem of first gold file>.py` if it
  exists; else `none`. Naming an existing file leaks no hidden test content.
- Leak rules (all must hold; the builder fails listing violations unless an override exists):
  1. No substring of 12+ characters (whitespace-normalised) of any gold ADDED line appears in the plan unless it also
     appears in the original file or in the issue text. (One-line solutions leak code today in 9 tasks:
     fastapi_14616, fastapi_14794, rich_2943, rich_3006, rich_3105, rich_3278, rich_3470, rich_3472, rich_3905.)
  2. Every code identifier in the plan (a backticked span, or a token with `_`, `.`, or an inner capital) occurs in the
     issue text or in the original repository source (`grep -rF` over the base workspace; for tasks without a snapshot:
     the gold patch's context and removed lines), or is a Python 3.12 builtin or stdlib name (`dir(builtins)`, or
     `mod.attr` where `mod` is in `sys.stdlib_module_names` and `hasattr(importlib.import_module(mod), attr)`; the
     builder imports stdlib modules only, never repository code). A name only the gold patch introduces is a leak.
  3. Nothing from `hidden_test_demands` or the test_patch appears (checked with rule 1 against test_patch added lines).
- Overrides: `eval/golden/fixtures/plan_overrides.json`, hand-written: `{"<tid>": {"FIX": "...", "CAUSE": "...",
  "why": "..."}}`. An override describes the change in words and may use names from the issue or the repo; it never
  contains new code. The leak rules run on the final plan including overrides.
- Word count: whitespace tokens of the whole plan <= 120; if over, CAUSE shrinks to 20 words, then FILES collapses.

### 4.2 Golden repro
- Source: `r2_v10_1` locator steps only (v10 helpers; the v9 and v4 runs have no `--repro-only`). Take the LAST
  `python3 /tmp/swe/verify.py --repro-only <<'EOF' ... EOF` run_command whose observation contains `fails on original`
  or `hangs on original`; the body is the text between the heredoc opener line and the final `EOF` line.
- Validation in the kpar venv on fresh clones (`tasks.fresh_ws`, `tasks.sandbox_env`, cwd = workspace,
  `PYTHONPATH` = workspace, literal `/workspace` mapped to the clone path): original tree -> exit != 0 (or timeout at
  20 s); gold tree -> exit 0 within 20 s. Both hold: `repro` = body, `reproducible = true`. Else `repro = null`,
  `reproducible = false`, with the reason.
- The golden repro is a REAL locator's reproduction that is known to discriminate. It is never derived from the hidden
  tests.
- Supply today: 121 locator `--repro-only` runs in `r2_v10_1` (59 `fails on original`, 3 `hangs on original`, 52
  `passes on original`); 39 of the 74 tasks have at least one failing candidate before validation, so expect fewer
  than 39 `reproducible` tasks, and fewer still among the 40 with a local snapshot.

### 4.3 Wrong patch (V variant ii)
Candidates in this order: `r2_v10_1/patches/<tid>.patch`, `r2_v9_eog_1/patches/<tid>.patch`,
`eval/kaggle/g4-l4-v9-eog/results.jsonl` `patch`, `eval/kaggle/g4-l4-v4/results.jsonl` `patch`. First, every file section
whose path is protected (`replay_l4.is_protected`) is dropped from the candidate: the v10.1 submit guard
(`_swe_common.arm_submit_guard`, armed by setup's install) marks those files assume-unchanged, so a v10.1 run could never
submit them, and dropping them keeps the replay on edit.py. A candidate then qualifies when
it is non-empty, touches at least one non-test source file, applies to the snapshot (`tasks.harness_apply`), its
changed lines differ from gold, and it FAILS the hidden tests in kpar (`tasks.mini_verify`, retried once when every
failing node is in `KNOWN_FLAKY`). Pick: qualifying candidates that touch a gold file first (a near miss the verifier can
repair), then source order, then fewest changed lines. No qualifying candidate: no `wrong` case for that task
(`wrong_why` recorded).

### 4.4 Tree replay steps (V variants i and ii)
- Default `replay: "edit"`: one `python3 /tmp/swe/edit.py` run_command per hunk, bottom-up per file, built from
  `tasks.parse_patch`: `--lines A-B` with the new body on stdin via `<<'EOF'`, `--insert-after N` for pure insertions,
  `--lines A-B --delete` for pure deletions, `--create` for new files (the `gold_steps` shape of
  `tests/test_v10_flow.py`, but on the robust parser: `\ No newline at end of file`, trailing blank lines).
- Validation: replay on a fresh clone with the installed helpers (`tasks.install_helpers`, `tasks.run_helper`); every
  step must print `OK`, and the sorted changed lines of `git diff` must equal those of the patch.
- Fallback `replay: "git_apply"` when validation fails, when edit.py refuses a path, when the patch deletes or renames a
  file, changes only a mode, or is binary (edit.py cannot express these), when any new-side body line is exactly `EOF`
  (it would end the heredoc early), when any body line matches `tasks._MARKER` (a `=======` RST underline or a
  `<<<<<<< SEARCH` line: edit.py then reads the body as SEARCH/REPLACE blocks and ignores `--lines`, edit.py:846), or
  when any hunk contains a substring the subprocess sandbox rewrites in COMMAND TEXT (`/tmp`, `/workspace`,
  `/wheels`, `/usr/local/bin`): one run_command
  `python3 -c "import base64,subprocess,sys;sys.exit(subprocess.run(['git','apply','--whitespace=nowarn','-'],input=base64.b64decode('<b64>')).returncode)"`.
  Base64 keeps the rewrite away from the patch. Helper journal then has no edit entries (a documented deviation).
- `notes_changed`: the scripted fixer's CHANGED line, `CHANGED: <file> <function> (<start>-<end>)[; ...]` from the
  replayed patch (or `CHANGED: nothing` for `empty`).

### 4.5 Gradability and hidden nodes
- `gradable`: gold passes the hidden tests in kpar twice (`tasks.mini_verify`) AND the empty patch fails. Known today:
  `requests_6644` is not gradable (`KNOWN_FREE`: the empty patch resolves in parity). Non-gradable cases are not run by
  default (`--include-ungradable` runs them for X metrics only).
- `hidden_nodes`: `tasks.hidden_claim_nodes(tid)`. `pre_hidden_nodes_pass` (V): passing count of those nodes on the
  pre-state tree (`tasks.hidden_outcomes` on `base_ws(tid, with_test_patch=True)` plus the tree patch).
- `t0` per suite (helper clock at the live stage's first request) = the median, over the `r2_v10_1` tasks in which
  that stage ran, of the last `[t=Ns]` footer before the stage's first step. Measured 2026-09-29: L 2 s (74 tasks),
  F 47 s (73), V 91 s (69). (v1 used 101 s for V, the median of the fixer's LAST footer over 73 tasks; that includes the
  4 tasks whose fixer ran the clock out so the verifier never started.) The builder recomputes these from the traces
  and records them in the manifest; the dataset carries them per case.
- Every hidden-test run (`gradable`, exec checks) calls `tasks.mini_verify(..., timeout=180)`: the grader's pytest
  timeout is `command_timeout_seconds` (verification.py:502, 180 s in the bundle's eval_config), while mini_verify's
  default of 20 s is a unit-test convenience that would score a slow but passing suite as a hang.

### 4.6 Outputs of the builder (committed, deterministic, sorted keys, 1-space indent, trailing newline)
- `eval/golden/split.json` (section 2).
- `eval/golden/fixtures/task_fixtures.json`: `{"<tid>": {...per-task fixture...}}` with every field of 4.1 to 4.5 and
  the validation evidence (`gold_pass_runs`, `empty_pass`, `repro_orig_rc`, `repro_gold_rc`, `replay_ok`, `wrong_source`,
  `wrong_mini_verify_why`, ...).
- `eval/golden/fixtures/plan_overrides.json` (hand-written; the builder only reads it).
- `eval/golden/fixtures/MANIFEST.json`: builder version, input sha256s, t0 values, counts per suite x split x
  runnable x gradable x reproducible, leak-check summary.
- `eval/golden/datasets/{L,F,V}_{dev,holdout}.json`: EvaluationDatasets in the skill's INFERENCE-INPUT form:

```json
{"eval_cases": [{
  "eval_case_id": "F__rich_3043",
  "prompt": {"role": "user", "parts": [{"text": "<problem_statement>"}]},
  "reference": {"response": {"role": "model", "parts": [{"text": "<golden plan (L) | gold patch (F, V)>"}]}},
  "golden": {
    "schema": "golden-case-v1", "suite": "F", "task": "rich_3043", "variant": "-", "split": "dev",
    "repo": "rich", "stratum": "rich/none", "runnable": true, "runnable_why": "", "gradable": true, "gradable_why": "",
    "fixture_sha": "<sha256 of the canonical JSON of this golden block without fixture_sha>",
    "t0": 47, "pre_s": 150, "plan": "FILES: ...", "plan_source": "template|override", "plan_basis": "ast|hunk_header",
    "title_words": "<first line of the statement, <= 80 chars, quotes removed>",
    "repro": "<body>|null", "reproducible": true,
    "tree_patch": "", "tree_source": "gold|r2_v10_1|r2_v9_eog_1|g4-l4-v9-eog|g4-l4-v4|empty", "replay": "edit|git_apply|none",
    "replay_steps": [{"tool": "run_command", "args": {"command": "python3 /tmp/swe/edit.py rich/repr.py --lines 79-79 <<'EOF'\n...\nEOF"}}],
    "notes_changed": "CHANGED: ...",
    "gold_files": ["rich/repr.py"], "gold_new_files": [], "gold_functions": [{"file": "rich/repr.py", "qualname": "auto.auto_rich_repr", "name": "auto_rich_repr"}],
    "test_files": ["tests/test_repr.py"], "hidden_nodes": ["tests/test_repr.py::test_rich_repr_auto"],
    "pre_hidden_nodes_pass": null, "known": []
  }}]}
```

  `tree_patch`, `tree_source`, `replay`, `replay_steps`, `notes_changed`, `pre_hidden_nodes_pass` are V-only (empty or
  null elsewhere). Holdout tasks appear only in `*_holdout.json`.
- Incremental: per-task results cached at `~/.cache/g4/golden/<tid>.json` keyed by the sha256 of every input that task
  depends on (tasks row, catalog row, snapshot size+mtime, race-trace files, overrides entry, bundle helper sha,
  builder version). `--check` rebuilds everything in memory and fails if any committed file would change.

## 5. Runner: faithful single-stage runs (component b)

### 5.1 Design choice: the unmodified bundle, scripted neighbours
We do NOT build a truncated root agent. Three facts from the installed code rule it out:
1. With `include_contents: none`, ADK (`google/adk/flows/llm_flows/contents.py::_get_current_turn_contents`) shows a
   stage only the latest event from the user or ANOTHER agent, presented as `For context:` + `[<agent>] said: <text>`
   (`_present_other_agent_message`). The v10 fixer reads its plan from that `[locator]` message, not from `{plan?}`, and
   the verifier reads the fixer notes from the `[fixer]` message; no v10 prompt references `{fix_notes?}`. Injecting
   session state alone cannot reproduce what the fixer or verifier sees.
2. A root that ends after the target stage without `submit_patch` triggers the harness nudge loop
   (`agent_runner.run_agent_sandbox`: up to 3 nudges, reset whenever a pass made a tool call), which re-runs the whole
   SequentialAgent from setup, so the target stage would run again.
3. The bundle under test must be the bundle that ships; a copied-and-edited bundle can drift.

So every stage run executes the REAL `swegemma` Evaluator (through `scripts/run_eval.py`) on an unmodified copy of the
bundle, and a per-case HTTP router answers each LLM request by agent name: LIVE stages go to the real model endpoint;
the stages before and after it are SCRIPTED responses that drive the real helpers exactly like a model would. The
target stage then sees the same system instruction, the same tool declarations, the same `[prev] said:` message shape,
the same helper-generated tool results and helper state as in a real run. The only varied inputs are the ones we
control on purpose (the golden plan, the recorded tree, the pinned start clock).

### 5.2 What the live stage sees, real run vs stage run

| Item | Real run | Stage run | Equal? |
|---|---|---|---|
| System instruction | stage prompt, `{problem_description}` from session state, `{plan?}` from the locator's `output_key` | same bundle copy; the scripted locator's final text is stored by the same ADK `output_key` code | yes |
| ADK identity, tool declarations, skill boilerplate | ADK | ADK, same bundle | yes |
| First content | `For context:` + `[locator] said: <plan>` (fixer), `[fixer] said: <notes>` (verifier), `[setup] said: READY` (locator) | same event shape; text = golden plan / scripted notes / READY | shape yes, text is golden |
| Earlier stages' tool calls | invisible (`include_contents: none`) | invisible | yes |
| Tool results | real helpers on a real workspace | real helpers; helper state (journal, repro, claims, checkpoints, index, context meter) produced by real helper calls of the scripted steps | yes, except journal times of scripted steps are compressed |
| Helper clock at stage start | varies (median L 2, F 47, V 91 s) | exactly `t0` (5.4) | pinned by design |
| Stage stops at helper t=300 | harness wall budget kills the task | router cap at helper t=300 (5.4 step 4) | yes, at the next LLM request |
| Compaction | `EventsCompactionConfig(5, 2, 14336, 5)` on reported usage | same config via `run_eval.py`; scripted calls report `mock_llm.estimate_prompt_tokens` usage | yes |
| Tool and turn budgets (100 / 200) | shared by all stages | shared; scripted stages use fewer calls than real ones | slightly looser |
| Model | vLLM, gemma-4-31b-it-qat-w4a16-ct, gemma4 tool parser | OpenRouter google/gemma-4-31b-it bf16 (PROXY) or vLLM (FAITHFUL) | PROXY differs, labelled |

Component (b) proves the "yes" rows with a parity test (5.10).

### 5.3 Scripts per suite (built by `scripts/golden/stage_scripts.py` from the dataset case)
Step syntax is `tests/v10_support/mock_llm.py`'s (`skill`, `cmd`, `heredoc`, `text`, `submit`, reactive callables).
`LIVE` means "forward to the upstream". `CLOCK(t)` is the clock-set step of 5.4. `LOCATE` =
`cmd('python3 /tmp/swe/locate.py "<title_words>"')`. `REPRO` = `heredoc("python3 /tmp/swe/verify.py --repro-only",
repro)` when the case has a repro. `VERIFY` = `cmd("python3 /tmp/swe/verify.py")`. `PLAN` = a reactive text step that
emits the golden plan with its REPRO line set from the REPRO result: it scans ALL tool results of the request
(`Request.tool_results()`, newest first) for the one produced by the `--repro-only` call and writes `fails on original`
if that result contains `fails on original` or `hangs on original`, else `none`. `NOTES` = reactive text
`notes_changed + "\nVERIFY: " + <first line starting with VERIFY: in the newest tool result that has one, else "not
run">`. Both must scan, not read `last_tool_result()`: `CLOCK` is the stage's last tool call, so the last result is
always the clock write (v1 defect; component b tests it).

| Suite / variant | setup | locator | fixer | verifier | submitter |
|---|---|---|---|---|---|
| L | `skill("install.py")`, `CLOCK(2)`, `text("READY")` | LIVE | `text("CHANGED: nothing")` | `submit()`, `text("Submitted.")` | `submit()`, `text("submitted")` |
| F | same, `CLOCK` omitted | `LOCATE`, `REPRO`?, `CLOCK(47)`, `PLAN` | LIVE | `submit()`, `text("Submitted.")` | `submit()`, `text("submitted")` |
| V gold / wrong | same | `LOCATE`, `REPRO`?, `PLAN` | `replay_steps...`, `VERIFY`, `CLOCK(91)`, `NOTES` | LIVE | `submit()`, `text("submitted")` |
| V empty | same | `LOCATE`, `REPRO`?, `PLAN` | `VERIFY`, `CLOCK(91)`, `NOTES` | LIVE | `submit()`, `text("submitted")` |

The CLOCK value is the case's `golden.t0`, never a literal; the numbers above are today's values.

Rules the router enforces:
- A LIVE agent is served live only during its FIRST stage-run: once a request from any other agent has arrived after
  the live agent's first request, later requests for the live agent are answered `text("done")` and logged
  `served: "done_after_end"` (counted by `x_live_restarts`). This stops a harness restart from re-running the live stage.
- Live cap (5.4 step 4): once `now - t_live0 >= (300 - t0) / scale`, where `t_live0` is the arrival time of the live
  agent's first request, every further live request is answered `text("done")` and logged `served: "cap"`; nothing
  more is forwarded, and the scripted later stage submits the tree. `x_capped` counts it.
- An exhausted script answers `text("done")` (mock_llm default) and logs `exhausted`.
- Summariser requests (no agent name, `SUMMARIZER_MARK` present) go to the upstream in live endpoints (the Kaggle
  summariser is the same model) and to the mock summary text for `oracle`/`null`.
- A request with no agent name and no summariser mark fails the case (`infra_error: unknown_request`).
- `submit_patch` with an empty diff is accepted by the harness (`swegemma/tools/execution.py`), so every suite ends in
  one pass: patch submitted plus a final text breaks the harness loop.

### 5.4 Clock handoff
The helpers take task time zero (`_swe_common.t0()`) from the baseline commit's committer time when it is 0 to 900 s
old, else from the `_swegemma_baseline` tag file mtime when 0 to 900 s old, else from `$SWE/t0`. The child therefore:
1. Wraps `swegemma.harness.agent_runner.setup_baseline_commit`: after the original runs, it executes in the sandbox
   `cd /workspace && GIT_COMMITTER_DATE='<now-86400> +0000' git commit --amend --no-edit -q --allow-empty &&
   git tag -f _swegemma_baseline >/dev/null && python3 -c "import os;p='.git/refs/tags/_swegemma_baseline';
   os.path.exists(p) and os.utime(p,(<now-86400>,)*2)"`. Tree and diff are unchanged; only dates move, so `t0()` falls
   through to `$SWE/t0` (written by install at the scripted setup).
2. `CLOCK(t)` = `cmd("python3 -c \"import time;open('/tmp/swe/t0','w').write(repr(time.time()-%r))\"" % (t / scale))`,
   the last tool call of the scripted stage before the live one. The subprocess sandbox rewrites `/tmp` in command text
   to `<sandbox>/tmp`, which is where the helpers read `$SWE` (the same path `run_eval.clock_scale_cmd` relies on). The
   live stage's first helper footer then reads `[t=<t0>s]` (+- 2 s).
3. Scale: `scale` = `--l4-scale` (default 1.0). `run_eval.py` writes `clock_scale` into every agent sandbox and divides
   `--max-time-minutes` and `--timeout-seconds` by it.
4. Stage end. The harness wall budget starts at the agent loop, BEFORE the scripted pre-stages, and cannot be moved
   later, so it cannot be the live stage's 300 s cap. v1 gave the pre-stages 20 s; the V pre-stage runs `verify.py`
   (up to `VERIFY_TOTAL` = 60 s) after the replay, and F runs `locate.py` plus a `--repro-only` run, so a 20 s allowance
   would cut the live stage short by up to a minute. v1.1: the harness budget is `(300 - t0) / scale + pre_s` real
   seconds with `pre_s` = 150 (per case in the dataset), and the ROUTER enforces the faithful cap (5.3, `served: "cap"`).
   The helpers already pace themselves on the helper clock (`real_budget()`, the FINISH/TIME lines), so the live stage
   sees the same hints at the same helper times as on Kaggle; only a non-helper command that is running when the cap
   passes can overrun it (bounded by the harness budget). The flat JSON records `pre_stage_s` (measured) and
   `capped`; a case whose `pre_stage_s > pre_s` is `infra_error: pre_stage_slow`.

### 5.5 The child process (`scripts/golden/stage_child.py`)
One child process per case sample, like `sandbox.run_eval_cli`: its own results dir, its own router route in
`OPENAI_BASE_URL`, `OPENAI_API_KEY=EMPTY`, `TMPDIR=<case>/sbx`, `G4_FAITHFUL_ENV=0` on the Mac (`--faithful-env` sets 1 on
a pod), `G4_COMPACTION` unset (run_eval default on), `G4_L4_SCALE` from `--l4-scale`, `PYTHONDONTWRITEBYTECODE=1`. The
parent strips `OPENROUTER_KEY`, `OPENAI_*`, `MODEL_PROXY_*`, `LITELLM_*`, `LOCAL_*` from the child environment first; the
real key lives only in the parent's router. The child installs these hooks, each a restorable wrapper around a harness
module global (the `run_eval.install_patches` pattern), then calls `run_eval.main(argv)`:

| Hook | Wraps | Effect | Model-visible? |
|---|---|---|---|
| baseline date | `agent_runner.setup_baseline_commit` | 5.4 step 1 | no (only commit dates) |
| cached extraction | `swegemma.harness.agent_runner.extract_snapshot` (the name agent_runner imported; verification's copy is untouched) | for the duration of that one call only, sets an INSTANCE attribute `docker.extract_archive_to_container` (the extension point `container_setup.extract_snapshot` already probes with `getattr`), calls the original, then deletes the attribute. The attribute clones the CONTENTS of a verbatim extraction cached at `~/.cache/g4/plain/<tid>/` into the existing sandbox workspace (`cp -c -R <cache>/. <ws>/` on macOS, `cp -a --reflink=auto` on Linux, fallback plain `cp -R`), built once with the harness's own `tar --no-same-owner -xzf` under an flock and stamped with tgz size+mtime; it returns True so the harness skips copy+tar but still runs its circular-symlink cleanup and every later setup step. NEVER a class-level method: `setup_container_wheels` runs first and returns early when `hasattr(docker, 'extract_archive_to_container')` (container_setup.py:405-408), which would leave `/wheels` empty and break run_eval's `faithful_install` on a pod. Expected gain about 1 s per case (a 92 MB rich snapshot extracts in 0.2 s plus a copy into the sandbox); `--no-extract-cache` turns it off | no (identical tree) |
| agent env | `swegemma.harness.agent_runner.install_test_dependencies`, installed BEFORE `run_eval.main` runs, as a plain function without the `_g4` attribute | `run_eval._harness_original` then records it as the harness original, and `install_patches` composes it: with `G4_FAITHFUL_ENV=0` it is the base, and with a scale `agent_install(base, s)` adds the clock-scale write after it. `--agent-env kpar` (default when `tasks.kpar_ok(repo)`): writes `_g4_kpar.pth` = the kpar site-packages path into the sandbox venv's site-packages. The name is load-bearing: `site` processes `.pth` files in sorted order and the sandbox already holds `_host_env.pth` (the harness's host site-packages, subprocess.py:389-400); `_g4_kpar.pth` sorts first, so Kaggle-parity versions shadow the host ones while `PYTHONPATH` = workspace still wins over both. `host` keeps the stock env. The runner refuses `--agent-env kpar` together with `--faithful-env` (the pod's faithful_install owns the env there) | tool outputs become MORE Kaggle-like |
| verification skip | `swegemma.evaluate.verify_task` (the name evaluate imported) | default on (`--harness-verify` keeps the real one): `async def _skip(docker, config, task, snapshot_path, **kw)`; the `**kw` matters because evaluate.py:365-370 inspects the signature before passing `base_snapshot_path`/`patch_path`. It saves the trace with `verification.save_trace_artifact(kw["trace"], config.results_dir, task.instance_id)` and returns `TaskResult(instance_id, repo, resolved=False, agent_patch=kw["agent_patch"], test_output="", test_exit_code=-2, duration_seconds=..., error=kw["agent_error"], trace=..., trace_json_path=...)` so `results.py` still writes `patches/<tid>.patch`; the flat JSON reports `harness_resolved: null`. Grading is ours (section 7). (Blanking `test_patch` in the case's tasks.jsonl would also skip verification, but evaluate.py:166-175 re-hydrates an empty test_patch from a secret bundle when one is found, so it is not used.) | no (after the agent phase) |

argv: `eval --tasks <case>/tasks.jsonl --snapshots-dir <case>/snapshots --submission-dir <run>/bundle/<name>
--results-dir <case>/results --sandbox subprocess --max-time-minutes M --max-tool-calls 100 --max-turns 200
--timeout-seconds 180 --concurrency 1 --display quiet --task-ids <tid>`. `<case>/tasks.jsonl` is the single tasks.jsonl
row; `<case>/snapshots/<tid>.tgz` is a symlink to `data/raw/snapshots/<tid>.tgz`. Budgets come from the bundle's
`eval_config.yaml`. `M = ((300 - t0) + pre_s * scale) / 60`, so after run_eval divides by `scale` the harness wall
budget is the live stage's remaining task time plus `pre_s` (150 s) for the scripted pre-stages; the faithful cap is the
router's (5.4 step 4). cwd = `<case>/results` (as `run_eval_cli`). The parent kills the child's process group at harness
budget + 240 s (`infra_error: child_timeout`). Note the harness task prompt then states a longer time allowance than a
real run; only the setup stage sees that user message (every later stage starts at the previous stage's reply under
`include_contents: none`), and setup is always scripted.

### 5.6 Endpoints (the router's upstream)
| `--endpoint` | Upstream | Label | Notes |
|---|---|---|---|
| `openrouter` | `https://openrouter.ai/api/v1/chat/completions`, model `google/gemma-4-31b-it`, `Authorization: Bearer $OPENROUTER_KEY` (env, else parsed from `--env-file`, default `/Users/carson/Projects/.env`) | PROXY | a different tool-call parser than the scorer's vLLM gemma4 parser; pinned by default (review 2026-09-30) to `{"provider": {"order": ["crusoe/bf16"], "allow_fallbacks": false}}` (bf16 with tools); `--or-provider NAME` pins another, `--or-provider any` lifts the pin; the provider actually used is logged |
| `vllm` | `--upstream-base URL` (required), model `--upstream-model` (default `gemma-4-31b-it-qat-w4a16-ct`), key `EMPTY` | FAITHFUL | pod or Kaggle L4 only; not exercised in this workflow (no pods, no Kaggle pushes) |
| `oracle` | none: per-case oracle script (5.9) | CONTROL | free |
| `null` | none: every live request -> `text("done")` | CONTROL | free |

Forwarding: the request body is forwarded verbatim except `model` (rewritten), plus `--upstream-extra JSON` merged in,
plus `seed` when `--seed-mode case` (`int(sha256(case_id)[:8], 16)`; vLLM honours it, OpenRouter depends on the provider;
default off). Non-streaming, like `mock_llm`. Timeout 300 s. The router itself retries only 429/502/503 (twice, honouring
`Retry-After`, else 4 s then 8 s); LiteLLM retries the rest. A response without `usage` gets an estimate and
`usage_estimated: true`. Cost (review 2026-09-30): OpenRouter's billed `usage.cost` when present (`cost_source:
billed`), else prompt x `--price-in` (default 0.14 $/M, the pinned endpoint's) + completion x `--price-out` (default
0.40 $/M), reasoning tokens counted as completion (`cost_source: estimate`); vllm is free per token, so its figure is
logged as `est_usd_at_proxy_prices` and `cost_usd` is 0. The router logs `reasoning_tokens` when present and the smoke
step reports them. Budget: `--max-usd` (default 1.00 for openrouter; vllm only when given; the smoke default is 0.40)
caps the run's total across `--resume`. Before launching, a capped run refuses when its estimate (EST_COST repriced at
the endpoint's prices x the case samples to run) plus the run's earlier spend exceeds the cap. Before forwarding, the
router refuses when spent >= cap - 0.01 with HTTP 500 `golden budget exhausted`; the parent stops launching cases after
the first refusal and marks refused cases `infra_error: budget`. The key is never logged (the router log stores headers
without `Authorization`).

### 5.7 Router log (per case, `<case>/router.jsonl`, one line per LLM request)
`{"i": 0, "t_in": 1.2, "t_out": 3.4, "agent": "fixer|_summarizer", "kind": "agent|summarizer|unknown", "live": true,
"stage_run": 0, "served": "upstream|script|oracle|null|done_after_end|cap|exhausted", "http_status": 200, "retries": 0,
"prompt_tokens": 9123, "completion_tokens": 211, "reasoning_tokens": 0, "usage_estimated": false,
"finish_reason": "tool_calls|stop|length", "latency_s": 2.1, "cost_usd": 0.00089, "provider": "..."|null,
"error": null}`. The request and response bodies go to `<case>/router_bodies.jsonl` only with `--log-bodies` (the
parity test uses it).

### 5.8 CLI (`scripts/golden/run_suite.py`, run with `.venv/bin/python`)
```
run_suite.py run --suite {L,F,V} --split {dev,holdout} [--tasks T1,T2] [--variants gold,wrong,empty]
    --endpoint {openrouter,vllm,oracle,null} [--upstream-base URL] [--upstream-model NAME] [--env-file PATH]
    [--or-provider NAME|any] [--upstream-extra JSON] [--price-in 0.14] [--price-out 0.40] [--max-usd USD]
    [--bundle submissions/v10] [--samples 1] [--seed-mode {off,case}] [-j 6] [--l4-scale 1.0] [--agent-env {kpar,host}]
    [--harness-verify] [--faithful-env] [--no-extract-cache] [--include-ungradable] [--run-id ID] [--out eval/golden/runs]
    [--resume] [--keep-sandboxes] [--log-bodies] [--holdout-reason TEXT] [--dataset PATH] [--grade]
run_suite.py write RUN_DIR [-j 6]          # exec checks + flat JSON + EvaluationDataset traces (run does this at the end)
run_suite.py controls --suite S --split dev [-j 6]    # oracle and null arms, asserts 5.9 expectations
run_suite.py smoke --endpoint openrouter [--max-usd 0.40]
```
Env equivalents: `G4_GOLDEN_ENDPOINT`, `G4_GOLDEN_UPSTREAM_BASE`, `G4_GOLDEN_UPSTREAM_MODEL`, `G4_GOLDEN_J`,
`G4_GOLDEN_MAX_USD`. `-j` defaults to 6: each case is a child harness process (ADK, LiteLLM, about 350 MB) plus sandbox
helpers and pytest, and the Mac has 10 cores and 16 GB. Default dataset: `eval/golden/datasets/<suite>_<split>.json`.
`scripts/golden/` is not a package (no `__init__.py`): every script inserts its own directory and `ROOT/tests` into
`sys.path` and imports siblings and `v10_support` by name; component (b) calls component (c)'s `summary.py` only as a
subprocess, so no component imports another's module. Cases not `runnable` are recorded as
`skipped` with the reason (and the fetch/build command from `tasks.fetch_cmd` / `tasks.build_cmd`). The bundle is copied
once to `<run>/bundle/` (`sandbox.copy_bundle`); `bundle_sha` = sha256 over sorted relative paths and bytes. The runner
refuses a bundle whose sub-agents are not exactly setup, locator, fixer, verifier, submitter. `--resume` skips cases whose
flat JSON has status `ok` or `model_error`, refuses settings that differ from the run.json it continues (endpoint,
upstream base and model, provider pin, extra body, seed mode, samples, `--l4-scale`, dataset sha, filters, agent
environment, `--faithful-env`, `--harness-verify`), and moves each re-run case's earlier attempt to
`<run>/attempts/<case>.attempt<N>/` (its spend still counts). Each case's `meta.json` records the endpoint, label, model
and pin that served it. Ctrl-C or SIGTERM cancels queued cases, kills live children, writes the partial run with
`status: interrupted` and exits 130. `--grade` runs agents-cli and the summary when both exist. Runs are idempotent per
run dir.

### 5.9 Controls (free, run before any paid run)
- `oracle`: L: live locator answered `REPRO`? then `text(golden plan)`. F: live fixer answered `replay` of the GOLD
  patch, `VERIFY`, `text(notes)`. V: verifier answered: gold -> `STATUS`, `VERIFY`, `FINALIZE`, `submit()`, `text`;
  wrong -> `cmd("cd /workspace && git checkout -q _swegemma_baseline -- <paths of the wrong patch that exist at the
  baseline> && rm -f -- <paths it created>")` (paths shell-quoted, from `patch_files`), then the gold replay, `VERIFY`,
  `FINALIZE`, `submit()`, `text`; empty -> gold replay,
  `VERIFY`, `FINALIZE`, `submit()`, `text`. (`STATUS`/`FINALIZE` = `python3 /tmp/swe/status.py` / `finalize.py`.)
- `null`: every live request -> `text("done")`.
- Pre-registered expectations on gradable runnable cases (the `controls` command fails listing every violating case):
  oracle F `hidden_pass` = 1 for 100 %; oracle V `hidden_pass` = 1 for 100 %; oracle L plan checks all 1; null F
  `hidden_pass` = 0 for 100 %; null V gold `hidden_pass` = 1, wrong 0, empty 0 (the scripted submitter submits the
  untouched pre-state); null L `ended_by_text` = 1, plan format 0. A violation means the runner or the grader is wrong
  (or a task is flaky), never the model.

### 5.10 Parity test (the regression test for "the model sees the same thing")
On the synthetic calc task of `tests/test_v10_flow.py` (and, NIGHTLY, on 2 real rich tasks):
1. Full pipeline: `run_eval_cli` with a MockLLM whose locator ends with `text(golden plan)` and whose fixer replays a
   patch, runs VERIFY and replies notes; capture the fixer's and the verifier's FIRST request body.
2. Stage runs F and V with `--endpoint vllm --upstream-base <a MockLLM route>` (the mock acts as the upstream) and
   `--log-bodies`; capture the live stage's first request body.
3. Assert equality of `messages` and `tools` after normalising tool-call ids, `[t=Ns]` digits and journal times. The
   system message, the `For context:` message and the tool declarations must be byte-identical.

## 6. Trace output (component b)

### 6.1 Run directory
```
eval/golden/runs/<run_id>/
  run.json                    manifest (6.4)
  bundle/<name>/              the bundle copy
  cases/<case_id>/            tasks.jsonl, snapshots/<tid>.tgz symlink, results/ (child output: logs/, patches/,
                              traces/trace_<tid>.json, task_results.jsonl), router.jsonl, child.out, child.err, sbx/
  cases/<case_id>.json        flat per-case record (6.3)
  traces/<suite>_<split>.json EvaluationDataset in the skill's GRADING-INPUT form (6.2), all cases of the run
  grade/results_<ts>.{json,html}  agents-cli output
  summary.json, summary.md    component c
```
`sbx/` and `results/logs/` are deleted after `write` unless `--keep-sandboxes`. `.gitignore` gets
`eval/golden/runs/*/cases/*/` and `eval/golden/runs/*/bundle/`; run.json, flat JSONs, traces and summaries stay small
enough to commit.

### 6.2 Trace case (one per case sample; `traces/<suite>_<split>.json` = `{"eval_cases": [...]}` sorted by case id)
```json
{
  "eval_case_id": "F__rich_3043__s0",
  "responses": [{"response": {"role": "model", "parts": [{"text": "<live stage's final reply text, or empty>"}]}}],
  "reference": {"response": {"role": "model", "parts": [{"text": "<golden plan (L) | gold patch (F, V)>"}]}},
  "agent_data": {
    "agents": {"setup": {"agent_id": "setup", "agent_type": "LlmAgent", "instruction": "<prompts/setup.md>",
                         "tools": [{"function_declarations": [{"name": "run_command"}, ...]}]}, "...": {}},
    "turns": [{"turn_index": 0, "events": [
      {"author": "user", "content": {"role": "user", "parts": [{"text": "<harness task prompt>"}]}},
      {"author": "setup", "content": {"role": "model", "parts": [{"function_call": {"name": "run_skill_script", "args": {"file_path": "install.py", "skill_name": "swe-tools"}}}]}},
      {"author": "setup", "content": {"role": "user", "parts": [{"function_response": {"name": "run_skill_script", "response": {"stdout": "..."}}}]}},
      {"author": "setup", "content": {"role": "model", "parts": [{"text": "READY"}]}}]}]
  },
  "golden": {"...": "the dataset case's golden block, plus:",
    "case_id": "F__rich_3043__s0", "dataset_case_id": "F__rich_3043", "sample": 0,
    "live_agents": ["fixer"], "status": "ok|model_error|infra_error|skipped", "status_detail": "", "crash_class": null,
    "final_patch": "<submitted patch text>",
    "run": {"run_id": "...", "endpoint": "openrouter", "label": "PROXY", "upstream_model": "...", "bundle_sha": "...",
            "l4_scale": 1.0, "max_output_tokens": {"setup": 256, "locator": 768, "fixer": 2048, "verifier": 2048, "submitter": 1024}},
    "llm_calls": ["<router.jsonl records, 5.7>"],
    "exec_checks": {"<6.3>": "..."},
    "writer_warnings": []}
}
```
Mapping from the child's ATIF-v1.7 trace (`results/traces/trace_<tid>.json`):
- `source: "user"` steps: the first opens turn 0 as a `user` text event; any later one (a harness nudge) opens a new
  turn. Harness custom records present in the trace (`continuation_nudge`) become `user` events too.
- `source: "agent"` with `tool_calls`: one `model` event with one `function_call` part per call (`name` =
  `function_name`, `args` = `arguments`), author = `extra.author` of the call; then one event by the same author with
  role `user` and one `function_response` part per call (`response` = the observation JSON parsed to a dict when it
  parses to one, else `{"result": "<text>"}`).
- `source: "agent"` text (`message`, `extra.event_type` `final` or none): `model` text event. `event_type: "thinking"`
  steps are dropped (ADK never shows thoughts to later calls) and counted in `writer_warnings`.
- `source: "system"` with an observation: a `function_response` event attributed to the author of the preceding call.
- Anything else: a `user` text event prefixed `[<source>] ` plus a writer warning.
- `turn_index` is 0-based and sequential; authors are only `user` or a key of `agents`.
- `responses[0]` text = the live stage's last text event in its first stage-run ("" when none). There is NO `prompt`
  field: the skill says not to mix `prompt` with `agent_data`, and the agents-cli probe shows local metrics need only
  `responses` (section 11).

### 6.3 Exec checks and the flat per-case JSON (`scripts/golden/checks.py`, run by `write`)
Computed in the kpar venv on `tasks.base_ws` clones, `-j` parallel, never inside the sandbox:

| key | type | how |
|---|---|---|
| `patch_files` | `[[path, is_new], ...]` | parsed from `final_patch` |
| `applies` | bool | `tasks.harness_apply` of `final_patch` on a fresh clone of `base_ws(tid)` (the harness pipeline) |
| `compiles` / `compile_errors` | bool / list | `python -m py_compile` (kpar python) on every changed, non-deleted .py of the patched clone |
| `hidden_pass` / `hidden_why` / `hidden_secs` / `hidden_retried` | bool / str / float / bool | `tasks.mini_verify(base_ws(tid), final_patch, test_patch, repo=tid, timeout=180)` (4.5); one retry when every failing node is in `KNOWN_FLAKY` (test_v10_flow rule) |
| `hidden_nodes_total` / `hidden_nodes_pass` | int / int | `tasks.hidden_outcomes` on `base_ws(tid, with_test_patch=True)` + `final_patch` over `golden.hidden_nodes` (V always; F and L skip it unless `--nodes`) |
| `pre_hidden_nodes_pass` | int | copied from the fixture (V) |
| `repro_text` | str or null | L: body of the locator's last `verify.py --repro-only` heredoc in its first stage-run |
| `repro_fails_orig` / `repro_passes_gold` | bool or null | L: run `repro_text` as in 4.2 on the original and on the gold tree |
| `harness_resolved` | bool or null | from `task_results.jsonl` when `--harness-verify`, else null |

null means "not computed" (not runnable, not gradable, or not applicable); metrics then report `applicable: false`.
Grading needs only `final_patch` and the fixture, so it is re-runnable offline and deterministic.

Flat per-case JSON (`cases/<case_id>.json`): `case_id`, `dataset_case_id`, `suite`, `task`, `variant`, `sample`,
`split`, `status`, `status_detail`, `crash_class`, `endpoint`, `label`, `upstream_model`, `providers`, `bundle_sha`,
`fixture_sha`, `wall_s`, `pre_stage_s`, `capped`, `live` {`agent`, `llm_calls`, `tool_calls`, `prompt_tokens`,
`completion_tokens`, `cost_usd`, `max_prompt_tokens`, `t_first`, `t_last`}, `harness` {`error`, `tool_calls`, `llm_calls`, `duration_s`}, `paths`
{`patch`, `atif`, `router_log`}, `exec_checks`. Status rules: `infra_error` = upstream HTTP failure after retries,
budget refusal, sandbox or setup error, replay step not printing `OK`, `pre_stage_slow` (5.4 step 4), child timeout,
unknown request; excluded from metrics and counted. `model_error` = a `replay_l4.CRASH` class in the child log or the harness error (unknown tool,
context overflow, key error, post-invocation); counted as failure (`hidden_pass` false, `x_crash` 1). A comparison is
INVALID when either run has more than 5 % `infra_error` cases.

### 6.4 run.json
`run_id`, `created`, `git_head`, `git_dirty`, `suite`, `split`, `dataset_path`, `dataset_sha`, `fixture_manifest_sha`,
`endpoint`, `label`, `upstream_base` (no key), `upstream_model`, `or_provider`, `providers_seen`, `l4_scale`,
`agent_env`, `samples`, `seed_mode`, `bundle_path`, `bundle_sha`, `versions` (swegemma, google-adk, litellm, python),
`t0`, `budget_usd`, `spent_usd`, `wall_s`, `mean_live_latency_s`, `cases` {`total`, `ok`, `model_error`,
`infra_error`, `skipped`}, `holdout_reason`.

## 7. Metrics (component c)

### 7.1 One library, generated self-contained metric files
- Source of truth: `eval/golden/golden_metrics.py`, stdlib only (`re`, `json`, `math`, `shlex`), Python 3.8 syntax,
  no module-level side effects. It defines trace parsing (stage-runs per author, footers `[t=Ns]`, commands, replies)
  and one function per metric: `m_<name>(instance) -> {"score": float, "explanation": json.dumps({"applicable": bool,
  "detail": ...})}`, plus `METRICS = {name: {"suites": "LFV"|..., "kind": "binary|count|numeric", "better": "higher|lower",
  "headline": bool, "doc": "..."}}`. Scores are never None (agents-cli counts None as an error); inapplicable cases
  score 0.0 with `applicable: false`, and our summary excludes them.
- `scripts/golden/gen_config.py` generates `eval/golden/metrics/<name>.py` = the library source + 
  `def evaluate(instance):\n    return _score("<name>", instance)` for every metric, and
  `eval/golden/eval_config_{L,F,V}.yaml`:
  ```yaml
  # generated by scripts/golden/gen_config.py; do not edit
  metrics_to_run: [l_all_gold_files_named, ..., x_clean]
  custom_metrics:
    - name: l_all_gold_files_named
      custom_function_file: metrics/l_all_gold_files_named.py
  ```
  One config per suite because agents-cli runs every metric on every case (skill, dataset_schema.md). It also writes
  `eval/golden/eval_config.yaml` = every metric (X plus L, F, V) for a traces dir that mixes suites; agents-cli's own
  `mean_score` then averages the `applicable: false` zeros too, so decisions always read `summary.py`. `--check` fails if
  a generated file differs from what the library would produce.
- Why self-contained: agents-cli 1.7.0 execs `custom_function_file` source with no `__file__`, `__name__ == "builtins"`
  and `sys.path[0]` = its own tool bin dir, so a metric file cannot import a sibling module (probe, section 11). It runs
  in the agents-cli uv Python 3.12, so no swegemma, no .venv packages.
- The instance a metric receives: the trace case's fields `agent_data`, `eval_case_id`, `response` (singular, the
  `responses[0]` content), `reference`, and our extra `golden` block.
- A "live event" is an event whose author is in `golden.live_agents`, inside that agent's first stage-run (a maximal run
  of consecutive events by that author). `llm_calls` with `live: true` and `served: "upstream"|"oracle"|"null"` are the
  live calls.

### 7.2 Metric registry (constants live in the library: `CAP_S=300`, `L_T_MAX=90`, `L_CALLS_MAX=12`, `PLAN_WORDS_MAX=120`,
`NOTES_WORDS_MAX=60`, `F_FIRST_EDIT_T=150`, `COMPACTION_LINE=14336`, `RUNAWAY_FRAC=0.95`)

64 metrics: the 59 of the original spec plus five added on 2026-09-30 by docs/v10/SPEC_v10_2.md section 8 (E2
`l_l4_s`, `f_l4_s`, `v_l4_s`; E3 `l_files_named_n`, `l_gold_files_in_files_line`).

X (all suites, live events and live calls only):

| name | kind | definition |
|---|---|---|
| `x_invented_tool_calls` | count, lower | exactly replay_l4's `parsed_invented + unparsed_invented`: parsed `function_call` names not in `replay_l4.TOOLS` (helper-like names included), plus text replies whose `replay_l4._call_name` is not in `TOOLS` |
| `x_bare_helper_calls` | count, lower | the helper-like subset of the above (name matches `^(call:)?(install\|locate\|grep\|view\|edit\|run\|verify\|finalize\|status)(\.py)?$`) plus replay_l4's `helper_shell` (run_command whose first line matches `HELPER_SHELL`); it overlaps `x_invented_tool_calls` on purpose, each is its own check |
| `x_malformed_calls` | count, lower | tool results containing `mandatory input parameters are not present` |
| `x_forbidden_edit_tools` | count, lower | `edit_file` or `write_file` calls |
| `x_edit_helper_failures` | count, lower | edit.py results containing `REFUSED`, `NO MATCH` or `REVERTED` |
| `x_text_tool_calls` | count, lower | text replies containing `<\|tool_call>` |
| `x_compaction_exceedances` | count, lower | live calls with `prompt_tokens >= 14336` |
| `x_compactions` | count, lower | `_summarizer` calls whose `t_in` lies inside the live stage-run |
| `x_runaway_outputs` | count, lower | live calls with `finish_reason == "length"` or `completion_tokens >= 0.95 * max_output_tokens[agent]` |
| `x_cant_open_file` | count, lower | live run_command calls whose command contains `/tmp/swe/` and whose result contains `can't open file` (replay_l4 `run_kpis` rule) |
| `x_crash` | binary, lower | `golden.crash_class` is not null |
| `x_live_restarts` | count, lower | `llm_calls` with `served == "done_after_end"` for a live agent |
| `x_capped` | binary, lower | any `llm_calls` record with `served == "cap"` (the live stage reached helper t=300) |
| `x_clean` | binary, higher | all of the above except `x_capped` are 0 (running out of time is a pacing result, reported apart) |

L (live agent `locator`; `plan` = its final reply):

| name | kind | definition |
|---|---|---|
| `l_all_gold_files_named` (headline) | binary | every `gold_files` path occurs in the plan (exact relative path, a leading `./` or `/workspace/` tolerated) |
| `l_gold_files_named` | numeric 0-1 | fraction of gold files named |
| `l_gold_functions_named` | numeric 0-1 | fraction of `gold_functions` whose `name` occurs as a whole word; `applicable: false` when there are none |
| `l_plan_format` | binary | reply starts with `FILES:` and has lines starting `CAUSE`, `FIX`, `REPRO`, `TESTS` |
| `l_plan_words` / `l_plan_within_words` | numeric / binary | whitespace tokens; <= 120 |
| `l_repro_fails_on_original` | binary | the locator's last `--repro-only` result says `fails on original` or `hangs on original`; summary also reports it on `reproducible == true` |
| `l_repro_valid` | binary | `exec_checks.repro_fails_orig and exec_checks.repro_passes_gold` |
| `l_ended_by_text` | binary | the stage-run's last event is a text event without `<\|tool_call>` |
| `l_t_end` / `l_within_time` | numeric / binary | last footer t of the stage-run; <= 90 |
| `l_calls` / `l_within_calls` | count / binary | tool calls in the stage-run; <= 12 |
| `l_llm_calls`, `l_prompt_tokens` | count | from live calls |
| `l_l4_s` | numeric, lower | modelled L4 seconds of the live stage-run: sum over its answered live calls of `0.102 + 0.02815 c + 0.000921 u` (u = uncached prompt tokens) plus the tool gaps between them; `applicable: false` without an answered live call (added by SPEC_v10_2 E2) |
| `l_files_named_n` | count, lower | distinct `.py`/`.pyi` path tokens in the plan; descriptive, guards the headline against file lists; `applicable: false` without a reply (SPEC_v10_2 E3) |
| `l_gold_files_in_files_line` | binary | every gold file is named in the plan's `FILES:` section (up to the next ALSO, CAUSE, FIX, REPRO or TESTS line; ALSO excluded) (SPEC_v10_2 E3) |

F (live agent `fixer`; gradable cases only, else `applicable: false`):

| name | kind | definition |
|---|---|---|
| `f_hidden_pass` (headline) | binary | `exec_checks.hidden_pass` |
| `f_touches_all_gold_files` / `f_gold_files_touched` | binary / numeric | from `patch_files` vs `gold_files` |
| `f_nonempty` | binary | `patch_files` holds a source file that is neither protected (`replay_l4.is_protected`) nor scratch (`replay_l4.scratch_files` rules) |
| `f_applies`, `f_compiles` | binary | exec checks |
| `f_no_protected`, `f_no_scratch` | binary | from `patch_files` |
| `f_notes_format` | binary | reply has a `CHANGED:` line and a `VERIFY:` line and <= 60 words |
| `f_ended_by_text` | binary | as L |
| `f_first_edit_t` / `f_first_edit_in_time` | numeric / binary | footer t of the first edit.py result starting `OK`; <= 150; `applicable: false` when no edit succeeded |
| `f_verify_rounds` | count | fixer run_commands running `/tmp/swe/verify.py` without `--repro-only` |
| `f_t_end`, `f_calls`, `f_llm_calls`, `f_prompt_tokens` | numeric / count | as L |
| `f_l4_s` | numeric, lower | as `l_l4_s` (SPEC_v10_2 E2) |

V (live agent `verifier`; gradable cases only):

| name | kind | definition |
|---|---|---|
| `v_variant_goal` (headline) | binary | gold: `hidden_pass`; wrong: `hidden_pass`; empty: `f_nonempty` rule on the final patch |
| `v_hidden_pass` | binary | `exec_checks.hidden_pass` |
| `v_not_worse` | binary | `hidden_nodes_pass >= pre_hidden_nodes_pass` and `applies` and `compiles` |
| `v_hidden_nodes_delta` | numeric | `hidden_nodes_pass - pre_hidden_nodes_pass` |
| `v_submitted_by_verifier` | binary | a `submit_patch` call in the verifier's first stage-run |
| `v_finalize_before_submit` | binary | a `/tmp/swe/finalize.py` run precedes the verifier's first `submit_patch`; `applicable: false` if it never submitted |
| `v_no_protected`, `v_no_scratch`, `v_ended_by_text` | binary | as F |
| `v_t_end`, `v_calls`, `v_llm_calls`, `v_prompt_tokens` | numeric / count | as L |
| `v_l4_s` | numeric, lower | as `l_l4_s` (SPEC_v10_2 E2) |

## 8. Summary and comparison (component c, `scripts/golden/summary.py`)

- `summary.py RUN_DIR`: loads `traces/*.json` and `cases/*.json`, computes every metric with the SAME library
  (imported normally from `eval/golden/golden_metrics.py`), and, when `grade/results_*.json` exists, asserts that
  agents-cli's per-case scores equal ours (map `eval_case_index` to `evaluation_dataset[0].eval_cases[index].eval_case_id`;
  agents-cli merges all trace files of a directory into one dataset). Per metric over applicable cases: n, mean;
  binary metrics get a Wilson 95 % interval (z = 1.96; `eval/compare.py` formula; n = 0 gives (0, 0)); numeric metrics
  get median and p90. With `samples > 1`: per-case mean first, and a case-cluster bootstrap 95 % interval (2,000
  resamples, `random.Random(20260929)`). Slices: repo, stratum, variant (V), `reproducible` (L). Header: label
  (PROXY / FAITHFUL / CONTROL), model, provider(s), bundle sha, population sentence (for example
  `F dev: 29 gradable of 30 runnable of 55 tasks (rich 28, requests 1); fastapi 0 of 24 runnable: snapshots missing`),
  cost, wall time, holdout looks. Writes `summary.json` and `summary.md`.
- `summary.py compare BASE_RUN CAND_RUN`: pairs by `dataset_case_id`. Refuses (exit 2) when suites or splits differ,
  when labels differ (unless `--allow-mixed`), or when either run has > 5 % `infra_error`. Cases whose `fixture_sha`
  differs are dropped and listed. Per metric: paired n, per-case difference of means, wins / losses / ties, exact sign
  test on wins vs losses (ties dropped) one-sided `P(W >= wins | n, 0.5)` (`ab_l4_decide.sign_p`) and two-sided
  `min(1, 2 * min tail)`, mean difference (bootstrap interval when samples > 1), verdict `better` / `worse` /
  `no evidence` at two-sided p <= 0.05 (direction from the metric's `better`). Writes `compare.json` and `compare.md`.
- `agents-cli eval compare A.json B.json` is still run (skill workflow), but it is a key-level JSON diff with no pairing
  or statistics (probe, section 11); decisions use `summary.py compare`.
- Pre-registered decision rule for a prompt change (docs, not code): adopt a candidate on PROXY evidence only if, on
  the dev split, the target suite's headline improves with one-sided sign-test p <= 0.10 and wins - losses >= 3, no X
  count metric has a higher total, and the other suites' headlines have no `worse` verdict; then confirm once on the
  holdout (and FAITHFUL when an L4 is available) before shipping.

## 9. Commands, cost and time

```bash
cd /Users/carson/Projects/gemma-swe-agent
# 0. once: kpar venvs rich + requests exist (scripts/build_kpar.sh). fastapi needs network (Carson's go):
#    snapshots: see tasks.fetch_cmd(tid); venv: G4_KPAR_ONLINE=1 scripts/build_kpar.sh fastapi
# 1. fixtures (cold about 10 min at -j 6, warm seconds), then prove they are reproducible
.venv/bin/python scripts/golden/build_fixtures.py -j 6
.venv/bin/python scripts/golden/build_fixtures.py --check
.venv/bin/python scripts/golden/gen_config.py && .venv/bin/python scripts/golden/gen_config.py --check
# 2. free controls (must pass before any paid run)
.venv/bin/python scripts/golden/run_suite.py controls --suite F --split dev -j 6
# 3. a paid PROXY run
.venv/bin/python scripts/golden/run_suite.py run --suite F --split dev --endpoint openrouter -j 6 --max-usd 1.00 \
    --bundle submissions/v10 --run-id F_dev_v10_or_s1
# 4. grade (run_suite --grade does 4 and 5), summary, compare
agents-cli eval grade --traces eval/golden/runs/F_dev_v10_or_s1/traces --config eval/golden/eval_config_F.yaml \
    --output eval/golden/runs/F_dev_v10_or_s1/grade --qps 500
.venv/bin/python scripts/golden/summary.py eval/golden/runs/F_dev_v10_or_s1
.venv/bin/python scripts/golden/summary.py compare eval/golden/runs/F_dev_v10_or_s1 eval/golden/runs/F_dev_cand_or_s1
agents-cli eval compare eval/golden/runs/F_dev_v10_or_s1/grade/results_<ts>.json eval/golden/runs/F_dev_cand_or_s1/grade/results_<ts>.json
# holdout, once per final candidate
.venv/bin/python scripts/golden/run_suite.py run --suite F --split holdout --endpoint openrouter --holdout-reason "v11 final"
```
`--qps 500`: the default 15/s would take over 2 minutes for 2,000 local metric computations; local metrics are cheap.

Smoke (the ONLY paid step of this workflow; hard cap $0.40, workflow cap $0.50): `run_suite.py smoke` first runs the
oracle and null controls on the chosen cases, then OpenRouter on 2 L + 2 F + 3 V (gold, wrong, empty of one task)
DEV cases: runnable, gradable, rich, smallest `gold_lines_changed` (V: smallest with a `wrong` case), ties by id. It
prints the estimate before starting, then the measured cost, per-call latency, reasoning tokens, the providers seen,
and asserts that every live request succeeded and every trace grades with 0 agents-cli errors. Expected about $0.08.
If the smoke sees `reasoning_tokens > 0`, OpenRouter is thinking where the Kaggle vLLM run does not show thoughts
(`thinking_config.include_thoughts: false` in every `configs/gen_*.yaml`); the smoke then prints the
`--upstream-extra` value that disables reasoning and every later PROXY run passes it (recorded in run.json).

Estimates (to be replaced by the smoke's measured numbers in `docs/eval/GOLDEN_EVALS.md`). Cost per case = r2_v10_1
per-stage tokens x OpenRouter prices ($0.09/M in, $0.34/M out): locator mean $0.010 (median 0.008, p90 0.019), fixer
$0.011 (0.005, 0.041), verifier $0.0065 (0.002, 0.015). Time per case = child and sandbox overhead about 10 s + LLM calls
x about 3 s + helper time; checks about 15 s per case, parallel.

| run (dev, runnable today, 1 sample) | cases | OpenRouter cost | OpenRouter wall at -j 6 | L4 FAITHFUL wall at -j 4 (projection) |
|---|---|---|---|---|
| L | 30 | about $0.30 | 8-10 min | 12-15 min |
| F | 29 gradable | about $0.33 | 8-10 min | 12-15 min |
| V (3 variants) | about 80 | about $0.55-0.80 | 15-20 min | 35-45 min |
| controls (oracle + null, one suite) | 2 x n | $0 | 6-10 min | n/a |
| holdout (any suite) | about 1/3 of dev (10 of 30 runnable) | about 1/3 of dev | about 1/3 of dev | |

These replace a 3.5 h, 74-task faithful run for one stage-level question; they are estimates until the smoke measures
per-call latency and cost.

Power: with about 29 paired dev cases at 1 sample, a sign test needs at least 5 wins and 0 losses (one-sided p = 0.031)
or 8 wins to 1 loss (p = 0.020) to call a change; a single-sample binary headline on 29 cases has a Wilson 95 %
interval about +-0.17 wide at 0.5. Three stages run at temperature 1.0, so use `--samples 3` for decisions (3x cost,
about $1 per F dev run) and report the population every time.

## 10. Known deviations (stated in every summary header)
1. PROXY runs use a different quantization and tool-call parser; X metrics on PROXY are indicative; PROXY time
   metrics are not comparable to L4 unless `--l4-scale` is set to the measured latency ratio (the summary prints
   `mean_live_latency_s` next to the Kaggle L4 reference from `eval/kaggle/*` traces).
2. Journal times of scripted steps are compressed (they run in seconds); only the handoff clock is exact.
3. Scripted stages consume fewer of the 100 tool calls / 200 turns than real ones.
4. The baseline commit is dated one day back (visible only through `git log`).
5. A compaction summary during the live stage summarises scripted events, not a real locator's.
6. The golden plan is better than a real locator's by construction; F measures the fixer's ceiling, not the pipeline.
7. Race-2 repros came from v10.0 helpers; they are re-validated with the v10.1 bundle helpers at build time.
8. fastapi is runnable since 2026-09-30 (all 74 snapshots local; its kpar venv is the 41-package Kaggle-freeze closure, built online once). Runs made before that date cover rich and requests only: compare them on the cases both have (summary.py compare pairs by case id). (Was: fastapi (31 tasks) is not runnable until its snapshots and venv exist.)
9. The live stage ends at helper t=300 by the router's cap (at its next LLM request), not by the harness killing the
   task mid-call; after the cap the scripted next stage calls `submit_patch`, which runs `git add -N .` and so includes
   new files, while a real timeout takes the harness fallback diff, which omits untracked files
   (agent_runner.py:758-776). Only capped cases on tasks that need a new file differ (`capped` is in the flat JSON).
10. Kaggle's grader runs with the full Kaggle image; our exec checks run the hidden tests in the kpar venv
   (versions pinned to the Kaggle pip freeze). `requests_6644` is the known case where they differ (`KNOWN_FREE`).

## 11. Gotchas found while writing this spec (each needs a regression test in the owning component)
1. agents-cli local custom metrics fail every case with `No response found for candidate 0 in EvalCase ...` when a
   trace case has `agent_data` but no `responses`; `prompt` is not needed; empty text is fine. (b: writer test.)
2. `custom_function_file` source is exec'd without `__file__`, with `__name__ == "builtins"` and `sys.path[0]` = the
   agents-cli bin dir: sibling imports fail. (c: generated files are self-contained; test execs each in a bare namespace.)
3. Extra case fields (our `golden` block) reach `instance`; `responses[0]` arrives as `instance["response"]`. (c.)
4. `agents-cli eval compare` diffs JSON keys; it pairs nothing and tests nothing. (c: our compare.)
5. With several trace files in `--traces DIR`, agents-cli merges them (sorted by file name) into ONE
   `evaluation_dataset[0]`; `eval_case_index` indexes that merged list. (c: index mapping test.)
6. The subprocess sandbox rewrites `/tmp`, `/workspace`, `/wheels`, `/usr/local/bin` in COMMAND TEXT, so a replayed
   patch body containing them is corrupted. (a: base64 git-apply fallback test.)
7. Helper time zero comes from the baseline commit time or tag mtime when 0-900 s old; the handoff needs the
   baseline-date hook AND the tag mtime change, else `t0()` picks the fresh tag file. (b: clock test.)
8. `include_contents: none` shows a stage only `[prev] said: <text>`; `{fix_notes?}` is unused by v10 prompts. (b: parity.)
9. A pass without `submit_patch` restarts the whole SequentialAgent (up to 3 nudges, reset by any tool call). (b: router
   `done_after_end` test with a scripted restart.)
10. `submit_patch` accepts an empty diff. (b: L suite ends in one pass.)
11. race-2 v10 traces print `swe-tools v10.0`; repro extraction keys on `fails on original`, not on the banner. (a.)
12. `tests/v10_support/tasks.py` calls `pytest.skip` when a snapshot or venv is missing; scripts must guard with
    `has_snapshot` / `kpar_ok` first. (a, b.)
13. `verify_task` is what saves the ATIF trace (`save_trace_artifact`); a verification stub must save it itself, and the
    patch file comes from `results.py` via `TaskResult.agent_patch`. (b.)
14. The OpenRouter key must never reach a child process, a sandbox or a log. (b: env and log test.)

Found in the v1.1 re-verification (each also needs its regression test):

15. `CLOCK` is the pre-stage's last tool call, so a reactive PLAN/NOTES step that reads `last_tool_result()` sees the
    clock write and always emits `REPRO: none` / `VERIFY: not run`. (b: stage-script test with a fake request whose
    newest tool result is the clock write and an older one holds `fails on original` / `VERIFY: GREEN`.)
16. The harness wall budget starts before the scripted pre-stages; the V pre-stage's `verify.py` alone can take 60 s,
    so a fixed 20 s allowance cuts the live verifier short. (b: router-cap test with a fake clock; child test that a
    slow pre-stage within `pre_s` leaves the live stage its full `(300 - t0) / scale`.)
17. `setup_container_wheels` skips the `/wheels` copy whenever `hasattr(docker, 'extract_archive_to_container')`
    (container_setup.py:405-408); a class-level cached-extraction method would silently empty `/wheels` on a pod.
    (b: after the hook, `hasattr(SubprocessManager(...), 'extract_archive_to_container')` is False, and the wrapped
    `extract_snapshot` leaves no attribute behind even when extraction raises.)
18. `site` reads `.pth` files in sorted order; the sandbox venv already holds `_host_env.pth`; the kpar file must sort
    before it (`_g4_kpar.pth`) or the host versions win. (b: in a sandbox, `python3 -c "import pygments;
    print(pygments.__file__)"` resolves under the kpar venv.)
19. `evaluate.py` inspects `verify_task`'s signature before passing `base_snapshot_path`; a stub without `**kw` gets
    fewer arguments than the original. An empty `test_patch` is not a safe way to skip verification (secret-bundle
    re-hydration, evaluate.py:166-175). (b: stub test through the real Evaluator on the calc task.)
20. A replay body line equal to `EOF` ends the heredoc; a body line matching `tasks._MARKER` (for example an RST
    `=======` underline) turns a `--lines` edit into a SEARCH/REPLACE parse. Both force the `git_apply` fallback. (a.)
21. `mini_verify`'s default timeout is 20 s; the grader's is `command_timeout_seconds` = 180 s. (a, b: pass 180.)
22. `r2_v10_1` has 69 verifier starts, not 73: the verifier's start clock is not the fixer's last footer over all
    tasks. (a: t0 recomputation test on two synthetic traces, one where the verifier never starts.)
23. `replay_l4.load` reads only the first tool call of a step (`tcs[0]`); the metrics count every call. The agreement
    test compares on steps with one tool call and reports multi-call steps separately. (c.)

## 12. Build plan: three components with disjoint files

Shared rules for all three: stdlib or existing `.venv` packages only; `.venv/bin/python -m pytest tests/test_golden_*.py`
passes with no network, no model and no GPU; default-tier tests finish in under 90 s per file (heavier ones behind
`G4_NIGHTLY=1`); tests that need local snapshots or kpar venvs skip with the fetch/build command; every bug found gets a
regression test; never edit `submissions/`, `tests/v10_support/*`, `scripts/run_eval.py`, `scripts/replay_l4.py`,
`tests/test_v10_flow.py`; never run anything inside `submissions/`; no OpenRouter calls in tests; no Kaggle, no pods.
Interfaces between components are the schemas in 4.6 (a -> b, c), 5.7 and 6.2-6.3 (b -> c). Each component tests
against synthetic data built in its own tests, so the three can be built in parallel.

### (a) fixtures: split + golden data builder
Files: `scripts/golden/fixture_lib.py`, `scripts/golden/build_fixtures.py`, `eval/golden/split.json`,
`eval/golden/fixtures/task_fixtures.json`, `eval/golden/fixtures/plan_overrides.json`,
`eval/golden/fixtures/MANIFEST.json`, `eval/golden/datasets/{L,F,V}_{dev,holdout}.json`, `tests/test_golden_fixtures.py`.
Acceptance: split equals section 2 exactly; `--check` byte-identical; zero leak violations after overrides; for every
runnable task: gold passes 2/2 and empty fails (or `gradable: false` with the measured reason), replay validated or
`git_apply` with the reason, repro validated or null with the reason; datasets are valid inference-input
EvaluationDatasets; cold build under 15 min at -j 6.
Tests (base and edge): split determinism, per-stratum k (n = 1 gives 0, n = 2 gives 1), disjoint and complete, committed
file equals recomputation; plan format, word cap, new-file entry, module-level change, merged hunks, >6 places, the 9
known leaks caught by rule 1, a gold-only identifier caught by rule 2, override applied and re-checked; replay steps on
synthetic repos (create, delete, insert-after, trailing blank line, no newline at EOF) reproduce changed lines exactly;
rewrite-sensitive body forces base64 fallback (gotcha 6); a body line `EOF`, an RST `=======` line, a file deletion and
a rename each force the fallback (gotcha 20); wrong-patch selection order and rejections (empty, test-only,
equals gold, does not apply, passes), protected sections stripped before qualification; a stdlib name (`inspect.unwrap`)
passes rule 2 while a gold-only repository name fails it; repro extraction picks the last `fails on original` heredoc
from a synthetic ATIF trace (gotcha 11); t0 recomputation counts only tasks where the stage ran (gotcha 22);
gradability calls mini_verify with timeout 180 (gotcha 21); `pytest.skip` never leaks out of the builder (gotcha 12);
NIGHTLY: gradability on 3 real rich tasks.

### (b) runner: stage router, child hooks, suite CLI, trace writer, exec checks
Files: `scripts/golden/router.py`, `scripts/golden/stage_scripts.py`, `scripts/golden/stage_child.py`,
`scripts/golden/run_suite.py`, `scripts/golden/trace_writer.py`, `scripts/golden/checks.py`, `.gitignore` (append the
run-dir patterns), `tests/test_golden_runner.py`, `tests/test_golden_trace.py`, `tests/golden_data/` (small trimmed
ATIF samples copied from `r2_v10_1` for writer tests).
Acceptance: parity test (5.10) passes for F and V; controls (5.9) pass on the synthetic calc task in the default tier
and on 3 real rich dev tasks per suite in NIGHTLY; every written trace grades in agents-cli with 0 errors (skip when the
binary is absent); `-j` runs cases concurrently with isolated routes, one failing case does not stop others, `--resume`
is idempotent; `smoke` exists and is not run by tests.
Tests (base and edge): router scripted steps, LIVE forwarding to a fake upstream (model rewrite, auth header added,
body otherwise verbatim), 429 retry, budget refusal and parent stop, `done_after_end` after a scripted restart (gotcha 9),
summariser forwarding, unknown request -> infra_error, key absent from child env and logs (gotcha 14); stage scripts per
suite and variant; `CLOCK` command with scale; baseline-date hook makes the first live footer read t0 +- 2 (gotcha 7);
cached extraction yields a tree identical to the harness tar extraction (file bytes, modes, `git ls-files -s`);
kpar `.pth` present in the agent sandbox; verification stub still writes patch and trace (gotcha 13); L suite ends in
one pass with an empty submit (gotcha 10); writer on real ATIF samples: sequential turns, authors valid,
call/response pairing, thinking dropped, system observation attributed, `responses` present (gotcha 1); checks on the
calc task: pass, fail, garbage patch does not apply, syntax error does not compile, protected and scratch paths listed;
flat JSON status rules (infra vs model error). v1.1 additions: PLAN and NOTES read the REPRO / VERIFY result even when
the clock write is the newest tool result (gotcha 15); router cap at `(300 - t0) / scale` with an injectable clock,
`served: "cap"`, and a slow pre-stage within `pre_s` that still leaves the live stage its full budget (gotcha 16); no
`extract_archive_to_container` attribute survives the extraction hook, on success or on exception (gotcha 17); the kpar
`.pth` shadows `_host_env.pth` inside a real sandbox (gotcha 18); the verify stub keeps `**kw` and runs through the
real Evaluator (gotcha 19); exec checks pass `timeout=180` (gotcha 21); `--agent-env kpar` with `--faithful-env` is
refused.

### (c) metrics: library, generated agents-cli configs, summary and compare, user docs
Files: `eval/golden/golden_metrics.py`, `scripts/golden/gen_config.py`, `eval/golden/eval_config_L.yaml`,
`eval/golden/eval_config_F.yaml`, `eval/golden/eval_config_V.yaml`, `eval/golden/eval_config.yaml` (union, generated),
`eval/golden/metrics/*.py` (generated),
`scripts/golden/summary.py`, `docs/eval/GOLDEN_EVALS.md`, `tests/test_golden_metrics.py`, `tests/test_golden_summary.py`.
Acceptance: every metric of 7.2 implemented with base and edge tests; generated files in sync (`--check`) and each
execs standalone (gotcha 2); X metrics agree with `scripts/replay_l4.py` counters on all 74 `r2_v10_1` traces,
converted to instances by a small converter inside the test, with the exact mapping `x_invented_tool_calls` =
`parsed_invented + unparsed_invented`, the shell part of `x_bare_helper_calls` = `helper_shell`, `x_malformed_calls` =
steps of kind `malformed`, `x_cant_open_file` = `run_kpis`' `cant_open` rule, on single-call steps (gotcha 23);
`x_capped` counts `served: "cap"` and stays out of `x_clean`; agents-cli grades a synthetic trace set with the generated configs with 0 errors and scores equal to the
library's (skip when absent; gotchas 3 and 5); summary and compare implement section 8.
Tests (base and edge): each metric on synthetic instances, including empty `agent_data`, no live events, missing
`exec_checks` (applicable false), vacuous functions, a plan without `FILES:`, unparsed tool-call text, restarts; Wilson
known values (5/10 -> 0.2366-0.7634, 0/10, 10/10, n = 0); sign test known values (6 wins 5 losses one-sided 0.5; 8-0 ->
0.0039; two-sided capped at 1; ties dropped); bootstrap deterministic; samples > 1 aggregated per case; compare refuses
mismatched suite, split, label and > 5 % infra errors, drops changed `fixture_sha`; index mapping across merged trace files
(gotcha 5); `agents-cli eval compare` noted as non-statistical (gotcha 4). `docs/eval/GOLDEN_EVALS.md`: the user guide
(what each suite means, the commands of section 9, the decision rule, how to read PROXY vs FAITHFUL, the measured cost
and time table once the smoke has run).

After the three components: integration = `controls` on the dev split for L, F and V (free), then the smoke (<= $0.40).

## 13. Revision notes: v1 -> v1.1 (2026-09-29)

v1 was written earlier the same day. v1.1 re-checked it against the installed harness, the bundle, the race-2 traces
and a fresh local agents-cli probe (free: local metrics only, no model calls). Confirmed unchanged: the split of
section 2 (recomputed independently: 19 holdout, runnable dev 30 and holdout 10), the `include_contents: none` context
rule (contents.py:542-677), the nudge loop (agent_runner.py:498-740), the helper clock (`_swe_common.t0`, `clock`,
`_t0_file`), `submit_patch` accepting an empty diff (execution.py:72-98), agents-cli gotchas 1-5 (re-probed: missing
`responses` errors the case, `__name__ == "builtins"` with no `__file__`, the `golden` block and `reference` reach
`instance`, merged trace files are ordered by file name, `eval compare` is a key diff), and the cost figures of
section 9 (recomputed from `r2_v10_1` usage: $0.0102 / $0.0115 / $0.0070 mean per locator / fixer / verifier).

Changed:

| # | Where | v1 | v1.1 | Evidence |
|---|---|---|---|---|
| 1 | 5.3 PLAN, NOTES | read `last_tool_result()` | scan all tool results of the request | `CLOCK` is the stage's last call, so the last result is the clock write (gotcha 15) |
| 2 | 5.4, 5.5 | harness budget = live time + 20 s | + `pre_s` = 150 s, and the router caps the live stage at helper t=300 | the harness budget starts before the scripted pre-stages; V's `verify.py` alone may take 60 s (gotcha 16) |
| 3 | 5.5 extraction hook | class-level `SubprocessManager.extract_archive_to_container` | per-call instance attribute on `agent_runner.extract_snapshot` | container_setup.py:405-408 skips `/wheels` when the attribute exists (gotcha 17) |
| 4 | 4.5, 5.3 | V t0 = 101 s, L t0 = 3 s | V 91 s, L 2 s, defined over tasks in which the stage ran | 69 verifier starts in `r2_v10_1` (gotcha 22) |
| 5 | 4.5, 6.3 | `mini_verify` default timeout (20 s) | `timeout=180` | grader timeout = `command_timeout_seconds` (verification.py:502) |
| 6 | 4.4 | fallback only for sandbox-rewritten substrings | also for `EOF` lines, SEARCH/REPLACE marker lines, deletes, renames, mode-only and binary changes | heredoc framing; edit.py:846 (gotcha 20) |
| 7 | 5.5 agent env | `.pth` name and composition order unstated | `_g4_kpar.pth` sorts before `_host_env.pth`; hook installed before `run_eval.main`; refused with `--faithful-env` | subprocess.py:389-400; run_eval `_harness_original` (gotcha 18) |
| 8 | 5.5 verify stub | signature unstated | `(docker, config, task, snapshot_path, **kw)`; blanking `test_patch` rejected | evaluate.py:165-175 and 365-370 (gotcha 19) |
| 9 | 4.1 leak rule 2 | only issue or repository names | also Python 3.12 builtins and stdlib names | a real locator may name `inspect.unwrap`; the builder imports stdlib only |
| 10 | 4.3 | wrong patches replayed as recorded | protected file sections dropped first | the v10.1 submit guard makes them unsubmittable |
| 11 | 7.2 | X definitions near replay_l4 | exact replay_l4 mapping; `x_capped` added outside `x_clean` | replay_l4.py:380-497, 515-545 (gotcha 23) |
| 12 | 7.1 | per-suite configs only | plus the union `eval/golden/eval_config.yaml` | the computed task names that path |
| 13 | 5.8, 9 | `-j 8` in examples | default and examples `-j 6` | 10 cores, 16 GB; one harness child per case |
| 14 | 9 | smoke reports reasoning tokens | and derives the `--upstream-extra` that turns reasoning off when present | Kaggle stages run with `include_thoughts: false` |
