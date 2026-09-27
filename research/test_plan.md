# v10 test plan: cover every failure case before any GPU spend

Date 2026-09-27. Read-only research. Nothing was pushed, submitted or started; no repo file was changed except this report.
Scratch work (scripts, raw JSONL, probe repos) is in
`/private/tmp/claude-501/-Users-carson-Projects/654244a3-b38c-45a0-96af-d7e5f0aac6ce/scratchpad/tpv10/`
(`measure2.py`, `measure2.jsonl`, `edge_probe.py`, `static_gold.py`, `static_gold.json`, `helper_stats.py`, `gate_dump.py`, `run_stats.py`, `task_table.md`).
The per-task measurement reuses the Kaggle-parity venv `scratchpad/tp/kpar` (Python 3.12.14, pytest 8.4.2, Pygments 2.20.0,
markdown-it-py 4.0.0, typing_extensions 4.15.0, attrs, urllib3 2.5.0) left by an earlier, unfinished run of this same task;
`measure2.py` is my corrected copy of that run's `tp/measure.py`. Every number below was recomputed today by me.

## 0. Summary

What already exists: 12 test files, 64 test functions, 380 collected items; `380 passed in 135.09s` on this Mac
(`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests`). About 110 s of that is
`scripts/validate.py` run once per bundle (21 bundles, 4.4 to 10.2 s each). Nothing in the suite touches a real task
repository. No test checks the gate on a real repo, locator recall, the harness reset logic or Kaggle-image parity.

What can run offline here today: 40 of the 74 Kaggle-valid tasks (rich 39/42, requests 1/1) have local snapshots and run
in the `kpar` venv. The other 34 (all 31 fastapi, plus rich_4076, rich_4077, rich_4079) are missing:
`data/raw/download.log` stops after the rich snapshots (lines 319 to 323). A fastapi environment that matches Kaggle cannot
be built offline. pydantic 2.12.3 / pydantic-core 2.41.4, anyio 4.13.0, python-multipart 0.0.26, orjson, ujson and Flask
are missing from both `~/.cache/uv` and `data/raw/wheels`. One online step (free) fixes both gaps; see section 2.

The measured baseline of the v9_eog helpers on those 40 tasks (section 3):

| Check | Result |
|---|---|
| Gold patch passes a mini `verify_task` | 39/40 (requests_6644 fails only because kpar has no installed `requests`, see F11) |
| Empty diff fails the hidden tests | 40/40, but 3 of them **hang** (rich_4006, rich_3772, rich_3480, killed at 300 s) |
| `replace.py` applies every gold hunk by line range, result byte-identical to `git apply` | 122/122 hunks, 50/50 files; 23 new-file hunks (rich_3930) unsupported |
| `gate.py` on empty diff | NO SOURCE CHANGE 40/40, 0.3 s |
| `gate.py` on gold, default test selection | PASS 37, FAIL 1 (rich_3942), no test found 2 (rich_3105, rich_3043) |
| `gate.py` on gold with `--target <test file the hidden test_patch edits>` | **FAIL 6/39 deterministically** (rich_3942, 3935, 3470, 3105, 3043, 3061), plus 1 flake under load (rich_3938) |
| Gate test discovery finds a test file that the hidden test_patch edits | 23/39 |
| Gate picks non-test helper modules as "tests" | 11/40 (tests/render.py, tests/_card_render.py, tools/stress_test_pretty.py) |
| `locate.py` puts a gold file at rank 1 / top 3 / top 8 | 21 / 28 / 34 of 40 |
| Agent edit inside a hidden-test hunk is undone by the harness before scoring | **0/39: never undone, the test_patch then fails to apply** |

Findings that change the v10 design. Each one becomes a requirement in section 5 and a test in section 6.

- **F1. The harness "reset test files" step does nothing.** `verification.py:392-412` runs
  `git checkout HEAD -- <test files> conftest.py pytest.ini sitecustomize.py usercustomize.py _swegemma_stubs.py 2>/dev/null || true`.
  git aborts the whole checkout when any pathspec is unknown ("error: pathspec 'sitecustomize.py' did not match any
  file(s) known to git", rc=1, the file stays modified; reproduced in a scratch repo). So an agent edit to an existing
  test file survives. If the edit overlaps a test_patch hunk, the task is lost.
  Measured: 39/39 local tasks lost under that edit (`verify_tamper`, `reset_ok=False`).
  Exposure: 54/74 test_patches modify an existing test file.
  Observed in real runs: race1 `r_v9_c/fastapi_14077`, `r_v9_eo/fastapi_15588`, `r_v9_eo/fastapi_14077`
  (all "Failed to apply test_patch"), and Kaggle rescore `p_v6/rich_3454`.
  In race1 v9_eog, 10 of 47 non-empty patches touched protected files.
- **F2. The helpers were missing in 24 of the 51 v9_eog tasks.** In 20 tasks the locator's first call was `run_command`,
  so it never installed them. In 4 tasks the `run_skill_script` arguments were malformed: `"\"install.py\""`, `{}`,
  `"\":\""`, and `"install.py`,skill_name:"`. Across the run, 70 helper calls failed with "can't open file": locate 23,
  gate 20, check 19, replace 7, run 1. So the Race 1 v9 arms measured the levers with helpers present in about half the
  tasks.
- **F3. `gate.py` reports PASS when no test ran.** This happens when pytest prints no summary on both versions, or when the
  `--target` file exists only in the agent's version. Traced cases: `r_v9_eog` fastapi_14448, fastapi_5624 and
  fastapi_9753 ("ERROR: file or directory not found ... GATE: PASS"). My probe with a Python that has no pytest also gave
  GATE: PASS.
- **F4. The gate tells the model to undo correct fixes.** In 6/39 tasks the gold patch "regresses" existing tests. These are
  exactly the tests the hidden test_patch rewrites to the new behaviour; `rerun_gate.py` confirmed 2/2 serial runs each.
  The verifier prompt says REGRESSIONS mean "the change is wrong: fix it (or undo the offending part)".
- **F5. Gate and check use `HEAD` as the diff base, not the `_swegemma_baseline` tag.** After an agent `git commit`, gate
  prints NO SOURCE CHANGE and check prints "empty: nothing changed yet / NOT READY". `submit_patch` diffs against
  `_swegemma_baseline` (`tools/execution.py:83-86`). Probe: `edge_probe.py`.
- **F6. `replace.py` edge cases.**
  - A 1-line edit of a CRLF file rewrote all 5 lines (numstat 5/5).
  - Form feed and the other `str.splitlines` separators (\x0b, \x1c-\x1e, \x85,  ,  ) shift its line numbers
    away from `read_file`/git numbering. The probe edit landed on the wrong line and changed nothing.
  - A latin-1 source file raises a `UnicodeDecodeError` traceback.
  - It edits test files without complaint (see F1).
  - It writes absolute paths outside the workspace.
  - None of the 40 local gold files has CRLF or separator characters, so the 122/122 result does not cover these cases.
- **F7. `run.py` timeouts leak processes.** `sleep 30 &` and a grandchild `bash -c 'sleep 20'` were still alive after
  `run.py --timeout 3` returned. The harness kills the process group only on its own timeout
  (`adk_eval_core/sandbox/subprocess_sandbox.py:93-116`), and `SubprocessManager.stop` only runs `rmtree`
  (`swegemma/sandbox/subprocess.py:509-516`). On the sequential Kaggle run, a leaked busy loop would keep a CPU until the
  end (UNVERIFIED on Kaggle; the mechanism is in the code).
- **F8. Three failure modes kill the session and lose the working-tree patch.** These are: a hallucinated tool name, a
  context-window overflow, and a missing `{state}` variable in an instruction. `agent_runner.py:209` initialises
  `agent_patch = ''`. The generic `except` at `:801` skips the fallback `git diff` capture (`:760-780`).
  - Unknown tool: `e74_v2` rich_3676 (`git_grep`); `e74_v3` rich_4076 and fastapi_14419 (`search_similar_code`); patch 0
    each time.
  - Context overflow: race1 `litellm.ContextWindowExceeded` 2, 3, 1, 4 and 2 times in the r_v4, c, eo, eg and og arms
    (0 in eog).
  - Missing state variable: `google/adk/utils/instructions_utils.py:122` raises
    `KeyError('Context variable not found')`.
- **F9. Pod runs differ from Kaggle scoring.**
  - (a) The pod sandbox has network access. The verifier ran `pip install dirty-equals inline-snapshot --target .`, which
    downloaded from PyPI (`r_v9_eg` fastapi_14448) and produced a 9,230,785-byte patch that vendors `_pytest/`
    (831 new files).
  - (b) pytest versions differ. `pod/buildenv.sh:6` pins `pytest==8.3.4`; the pod agent's bare `pytest` resolved to
    pytest 9.1.1; Kaggle has pytest 8.4.2.
  - (c) The pod image has packages Kaggle lacks. It has dirty-equals and inline-snapshot; the Kaggle freeze
    (`eval/kaggle/rescore_fair/pip_freeze.txt`) has neither. 21 of the 36 Kaggle-invalid fastapi test_patches use them;
    0 of the 31 valid ones do.
  - (d) Installs differ. `scripts/run_eval.py:49` editable-installs `/workspace`; Kaggle's subprocess sandbox installs
    nothing (`container_setup.py:506-530` return early for `SubprocessManager`).
  - (e) Events compaction differs. The Kaggle kernel sets `EventsCompactionConfig(token_threshold=14336,
    event_retention_size=5)` (`scripts/make_eval_kernel.py:94-95`); the CLI path that `pod/run_eval.sh` uses leaves
    `events_compaction_config=None` (`swegemma/config.py:117`; `cli.py` never sets it).
- **F10. On Kaggle, src-layout repos import the host's installed copy.** The Kaggle sandbox puts `PYTHONPATH=/workspace`
  (`subprocess.py:483-488`) plus a `.pth` link to the host site-packages (`:389-399`). A src-layout package therefore
  imports the host copy, not the workspace. Reproduced: requests_6644's hidden test **passes on the empty patch** with
  `requests==2.33.0` in site-packages, and fails when `src/` is imported. The Kaggle image has `requests==2.32.4`.
  It follows that on Kaggle any patch "solves" requests_6644 (UNVERIFIED on Kaggle itself; all 7 Kaggle runs resolved it),
  and that a hidden src-layout repo tests the host copy, not the agent's edit.
- **F11. Pipeline bug in the rescore kernel.** `scripts/make_eval_kernel.py:44` writes `"PATCHES = " + json.dumps(PATCHES)`
  into Python source. `json.dumps` escapes astral characters as surrogate pairs, and a Python string literal keeps those as
  two lone surrogates (checked: `eval(json.dumps({'p':'x\U0001f4a9y'}))` gives `0xd83d 0xdca9`). So 3 rescore rows are
  artefacts, not agent failures: p_v7 rich_3930, p_v8 rich_3953 and p_v8 rich_3930
  ("Evaluation error: 'utf-8' codec can't encode ... surrogates not allowed"). The context line "4 runs failed because the
  agent edited a test file" is 1 test-edit failure plus these 3.
- **F12. Loops and stage overruns.**
  - In v9_eog, 24/51 tasks made an identical tool call at least 5 times; the maximum was 89 repeats. rich_3506 ran
    `gate.py` 16 times in a row on NO SOURCE CHANGE.
  - Stage caps written in the prompts are ignored. The locator averaged 19.4 calls against "at most 8"; the fixer averaged
    16.2 against "at most 12".

## 1. Inventory of the existing suite (`tests/`, 64 functions, 380 items, 135 s)

| File | Test function (items) | What it guards |
|---|---|---|
| conftest.py | (none) | `sys.dont_write_bytecode = True` |
| test_build.py | test_shell_syntax (27) | `bash -n` on every `pod/*.sh`, `scripts/*.sh` |
| | test_shellcheck_errors (27) | shellcheck error level |
| | test_python_compiles (139) | py_compile of every repo .py outside data/eval/kernels/ref/backups |
| | test_embedded_python_compiles (27) | `python -c` / heredoc Python inside shell scripts compiles |
| test_bundles.py | test_bundle_files_are_clean (21) | no __pycache__, ._*, .DS_Store, only allowed extensions |
| | test_skill_names_are_kebab_case (21) | SKILL.md `name:` kebab-case |
| | test_agents_only_use_real_tools (21) | yaml `tools:` subset of the 9 harness tools |
| | test_bundle_compiles_with_official_compiler (21) | `scripts/validate.py` = organisers' compile_submission + model check (the 110 s) |
| | test_make_kernel_skips_caches (1) | kernel notebook excludes .pyc and AppleDouble |
| | test_skill_scripts_do_not_shadow_stdlib (21) | no `select.py`-style shadowing (v5 regression) |
| test_convert.py | 8 tests | Nebius trajectory converter (training data), not the agent |
| test_helpers_v9.py | test_replace_edits_range_and_shows_context | replace.py basic edit, raw `\x1b` kept |
| | test_replace_reverts_on_syntax_error | auto-revert |
| | test_replace_insert_and_bad_range | insert with end=start-1, out-of-range error |
| | test_run_strips_ansi_truncates_and_times_out | run.py ANSI strip, middle cut, TIMEOUT |
| | test_gate_reports_regression_and_leaves_workspace | gate FAIL on a regression, workspace untouched |
| | test_gate_pass_and_no_change | NO SOURCE CHANGE, PASS on a benign edit |
| test_investigate.py | 2 tests | v7 `investigate.py` output under 5,000 chars (v7 only) |
| test_pod_scripts.py | 20 tests | pod hygiene: pins, health gates, self-stop, backup before stop, ports, preflight, canary, HF auth, `run_eval.sh` reads the bundle's eval_config (5/70/150/180) |
| test_rescore_env.py | 3 tests | buildenv has python-multipart; rescore kernel is CPU and carries all non-empty patches; helper-check cell guarded |
| test_sandbox_tmp_paths.py | test_v4_as_submitted_cannot_reach_helpers | documents the /tmp bug with the real `SubprocessManager` |
| | test_variant_helpers_reachable_in_sandbox | v9 variant: locate/test/run/gate reachable, last.log visible |
| test_sft_masking.py | 6 tests | SFT span masking |
| test_skill_scripts.py | 3 tests | v5 fork/pick_candidate |
| test_submit_at.py | 3 tests | submit_at.sh no double submit, no early fire |
| test_summary.py | 1 test | eval/summary.py counts and paired wins |

Gaps. Nothing tests any helper on a real repository, and there are no edge cases for replace, run, gate, check or locate
beyond the 6 toy cases above. No test covers:
- the harness verification logic (reset, test_patch apply, JUnit rules);
- prompt/tool consistency or instruction templating;
- context size;
- the 12 h time budget;
- Kaggle parity;
- trace KPIs.

## 2. Offline environment inventory

Snapshots.
- `data/raw/snapshots` holds 59 tgz: httpx 1, requests 13, rich 45.
- Of the 74 Kaggle-valid tasks, 40 are local.
- Missing: fastapi_{5077, 5624, 9425, 9555, 9753, 11194, 13537, 13920, 14077, 14258, 14301, 14306, 14372, 14419, 14448,
  14458, 14463, 14479, 14487, 14492, 14616, 14786, 14794, 14851, 14873, 14986, 15280, 15588, 15589, 15661, 15800},
  rich_4076, rich_4077, rich_4079.
- All 34 missing tasks have a local code graph (`data/raw/graphs/<repo>_<base_commit>.json`), which is enough for static
  checks only.
- Each snapshot contains `.git` and extracts in 0.38 s (97 MB tgz). An APFS clone (`cp -c -R`) of the extracted tree takes
  0.14 s, so a per-test fresh copy is cheap.

Per-repo needs (measured with the harness pytest command from `verification.py:493`):

| Repo | Layout | Offline here? | Env |
|---|---|---|---|
| rich (42 tasks) | flat `rich/` | yes | `kpar`: py3.12, pytest 8.4.2, Pygments 2.20.0, markdown-it-py 4.0.0, mdurl 0.1.2, typing_extensions 4.15.0, attrs 26.1.0, from `~/.cache/uv` plus `data/raw/wheels` (`uv pip install --offline`) |
| requests (1 task) | `src/requests` | yes | kpar plus an installed `requests` in site-packages (Kaggle has 2.32.4; offline only 2.33.0 or 2.34.2 exist), because on Kaggle the tests import site-packages (F10) |
| fastapi (31 tasks) | flat `fastapi/` | **no** | the Kaggle pins: pydantic 2.12.3, pydantic_core 2.41.4, starlette 0.52.1, anyio 4.13.0, httpx 0.28.1, python-multipart 0.0.26, email-validator 2.3.0, PyYAML 6.0.3, SQLAlchemy 2.0.49, orjson 3.11.8, ujson 5.13.0, Flask 3.1.3, Jinja2 3.1.6, typing-inspection 0.4.2, PyJWT 2.12.1, pytest 8.4.2. The cache has only pydantic 2.13.5 / core 2.46.5, anyio 4.15.1, python-multipart 0.0.32, SQLAlchemy 2.1.1, and no orjson, ujson or Flask. Deliberately **without** dirty-equals and inline-snapshot, to match Kaggle |

Docker (`docker 29.1.3`, arm64). Only `python:3.12-slim` (arm64) is local. Kaggle is x86_64, and `data/raw/wheels`
compiled wheels are x86_64 manylinux, so an offline Docker parity env is not possible without a one-time pull of
manylinux_aarch64 wheels (or an amd64 image under emulation).
Recommendation:
- macOS uv venvs for CI;
- a nightly `docker run --network none python:3.12-slim` job for Linux-only effects (the v5 `select.py` class) and
  guaranteed-offline behaviour;
- the Kaggle CPU rescore kernel as the final free parity check (Carson pushes it; this research did not).

One-time online preparation (free, Carson's call). This is the only way to cover all 74 tasks offline afterwards:
```bash
source /Users/carson/Projects/kaggriculture/.venv/bin/activate && cd /Users/carson/Projects/gemma-swe-agent
for id in $(cat data/kaggle_valid_ids.txt); do [ -f data/raw/snapshots/$id.tgz ] || python scripts/fetch_data.py snapshots/$id.tgz; done
# fastapi parity venv (pins copied from eval/kaggle/rescore_fair/pip_freeze.txt; cached by uv for offline reuse)
uv venv -p 3.12 .kpar/fastapi && VIRTUAL_ENV=.kpar/fastapi uv pip install "pytest==8.4.2" "pydantic==2.12.3" "pydantic-core==2.41.4" \
  "starlette==0.52.1" "anyio==4.13.0" "httpx==0.28.1" "python-multipart==0.0.26" "email-validator==2.3.0" "PyYAML==6.0.3" \
  "SQLAlchemy==2.0.49" "orjson==3.11.8" "ujson==5.13.0" "Flask==3.1.3" "Jinja2==3.1.6" "typing-inspection==0.4.2" "PyJWT==2.12.1" \
  "typing_extensions==4.15.0" "annotated-types==0.7.0" "Pygments==2.20.0"
uv venv -p 3.12 .kpar/rich && VIRTUAL_ENV=.kpar/rich uv pip install --offline --find-links data/raw/wheels "pytest==8.4.2" \
  "Pygments==2.20.0" "markdown-it-py==4.0.0" "mdurl==0.1.2" "typing_extensions==4.15.0" "attrs==26.1.0"
VIRTUAL_ENV=.kpar/rich uv pip install --offline --find-links data/raw/wheels "requests==2.33.0" urllib3 idna charset-normalizer certifi pysocks  # requests_6644 parity
```
The two `uv pip install` lines should live in a new `scripts/build_kpar.sh`, and `data/kaggle_freeze.txt` should be a
committed copy of the Kaggle pip freeze. `tests/v10/test_kpar_parity.py` then asserts that each kpar venv matches the
freeze for the packages it pins.

## 3. Measured baseline (v9_eog helpers, 40 local tasks, J=4)

Command: `cd scratchpad/tpv10 && J=4 /Users/carson/Projects/gemma-swe-agent/.venv/bin/python measure2.py` (writes
`measure2.jsonl`; ran in about 12 min wall; 2,149 task-seconds, 900 of them the three 300 s hangs).

For each task it extracts the snapshot seven times into scratch and applies the harness setup: git exclude, the harness
`pytest.ini`, the conftest hook, and a baseline commit plus `_swegemma_baseline` tag. Then it runs:
- `replace.py` bottom-up with each gold hunk, compared with `git apply`;
- `gate.py` on the empty diff, on gold, and on gold with `--target`;
- a mini `verify_task` on gold, on the empty diff, and on gold plus an agent edit inside the first test_patch hunk using
  the harness-exact reset list (reset, apply test_patch, harness pytest command, `_validate_junit_xml`);
- `locate.py --query <problem_statement>`.

Timings under 4-way contention (median / max):
- locate 2.0 / 3.7 s, output at most 1,635 chars;
- gate on gold 5.3 / 16.5 s;
- gold verify 1.5 / 4.5 s;
- replace 0.19 s per task.

Helper start-up on a tiny repo (5 runs, median):

| Helper | Start-up |
|---|---|
| install | 25 ms |
| locate | 31 ms |
| run | 39 ms |
| replace | 31 ms |
| gate | 68 ms |
| check | 99 ms (three git subprocesses) |
| test | 35 ms |

Start-up time is not the bottleneck: pytest runs and full-repo AST parsing are.

Locator misses (gold file not in the top 8): rich_3953, rich_3944 (rich/cells.py), rich_3468 (rich/console.py),
rich_3105 (rich/_export_format.py), rich_3067 (rich/highlighter.py), rich_3063 (rich/markup.py).
Discovery misses: 16 of the 39 tasks that have an existing target file (list in `measure2.jsonl`, key `discovery_hit`).

Static properties of all 74 gold/test patches (`static_gold.json`):
- Gold patches: none touches a protected file or a non-.py file. 4 add new files (fastapi_15661 1, fastapi_15280 1,
  rich_3930 23, fastapi_15800 6). 5 edit `docs_src/`. 17 change more than one .py file. Median 7 changed lines, maximum
  12,714; 7 exceed 100.
- test_patches: none touches a non-protected file. 54 modify an existing test file; 21 add a new one.
- Problem statements: median 468.5 chars, maximum 10,095; 27 are under 200 chars. No task has `hints_text`.
- Added gold lines: none contains a `/tmp`, `/workspace`, `/wheels` or `/usr/local/bin` token. 12 contain `\x`, `\u` or
  `\n` escapes (the double-escape edit_file failure class). 3 contain non-ASCII; 1 contains astral characters.

## 4. Trace evidence (Race 1, faithful 5 min / 70 calls / 150 turns / 180 s, 51 tasks)

| Arm | Solved | Empty patch | Mean s | p90 s | Max prompt tokens | ContextWindow crash | Test-patch apply fail |
|---|---|---|---|---|---|---|---|
| r_v4 | 18 | 9 | 111 | 195 | 28,596 | 2 | 0 |
| r_v9_c | 15 | 9 | 117 | 228 | 27,745 | 3 | 1 |
| r_v9_eo | 14 | 7 | 126 | 243 | 25,120 | 1 | 2 |
| r_v9_eg | 16 | 15 | 133 | 305 | 28,655 | 4 | 0 |
| r_v9_og | 14 | 9 | 142 | 305 | 28,579 | 2 | 0 |
| r_v9_eog | 21 | 4 | 135 | 238 | 25,352 | 0 | 0 |

Source: `run_stats.py` over `eval/race1/runs/*/task_results.jsonl` and `traces/`. The hard prompt limit is
32,768 - 4,096 = 28,672 tokens, and r_v9_eg peaked 17 tokens below it.

r_v9_eog details (`helper_stats.py`, `gate_dump.py`):
- install succeeded in 27/51 tasks.
- Helper calls:

  | Helper | Calls | "can't open file" |
  |---|---|---|
  | locate | 55 | 23 |
  | gate | 79 | 20 |
  | check | 44 | 19 |
  | replace | 36 | 7 |
  | run | 174 | 1 |

- Gate outcomes: PASS 22, FAIL 12, NO SOURCE CHANGE 23, false PASS with no summary 3.
- replace outcomes: OK 18, REVERTED 10, ERROR 1.
- edit_file: 411 calls, 151 errors.
- Tasks that never ran a test: 2/51 (v4: 14/51).
- Patches: 47 non-empty; 10 touch protected files (5 resolved anyway); 11 carry scratch files (repro.py,
  reproduce_issue*.py, repro_output.log).

Kaggle timing:
- `e74_v3`: the first result appears at 567 s into the kernel log (about 8.4 min of wheel install and vLLM start); 74 tasks
  took 12,561 s in total; mean 163 s per task; 13/74 reached at least 300 s.
- sub3: about 10.4 h for about 120 hidden tasks. That is roughly 5.1 min per task, i.e. mostly at the 5-minute cap.

## 5. Requirement registry

Tiers:
- CI: under 10 min on this Mac, no network, no GPU.
- NIGHTLY: longer, may use Docker or all 74 tasks.
- REPLAY: offline over recorded traces.
- CANARY: 1 to 3 tasks on a GPU; run only after CI and NIGHTLY are green.
- PRE-GPU: a free Kaggle CPU rescore, pushed by Carson.

Proposed test files live in `tests/v10/`.

### 5.1 Sandbox paths and environment
| ID | Requirement | Evidence | Test | Tier |
|---|---|---|---|---|
| R01 | Helpers install to `$TMPDIR/swe` and are reachable as `python3 /tmp/swe/<tool>.py` from `run_command` | v4 81/85 (pod) and 137/157 (L4) failed calls; `subprocess.py:441-443` rewrites `/tmp` | existing test_variant_helpers_reachable_in_sandbox, parametrized over every v10 bundle | CI |
| R02 | A helper run through `run_skill_script` (runpy in a tempdir, cwd = tempdir) resolves the workspace the same as through `run_command` | `google/adk/tools/skill_toolset.py:619-658` | test_install_paths.py::test_ws_resolution_skill_vs_command | CI |
| R03 | Helpers are usable even if the model never calls install.py. The first `run_skill_script` of any helper installs all of them, and "can't open file" output carries a one-line fix | F2: 24/51 tasks never installed; 70 failed calls | test_install_paths.py::test_any_helper_self_installs; REPLAY KPI cantopen == 0 | CI, CANARY |
| R04 | No helper writes into the workspace: no scratch, no `__pycache__`, `git status --porcelain` unchanged. The fallback diff captures untracked files (`agent_runner.py:760-780`) | 11/47 eog patches carry scratch files | test_helpers_contract.py::test_helper_leaves_git_status_clean[<helper>] | CI |
| R05 | Helper internals (checkpoint, pyc) live under `$TMPDIR/swe`, never the literal host `/tmp`. `check.py:7` `BEST="/tmp/_swe_best.diff"` and `replace.py:28` `cfile="/tmp/_pyc_replace"` collide across concurrent pod tasks | code | test_helpers_contract.py::test_no_host_tmp_literals (AST scan, docstrings excluded) | CI |
| R06 | Content sent through `run_command` (heredocs) has `/tmp`, `/workspace`, `/wheels` and `/usr/local/bin` tokens rewritten. replace.py must accept `--from <file>` or base64 content so code containing those tokens is not silently mutated | `subprocess.py:436-456`; 0/74 golds affected, hidden-set risk | test_install_paths.py::test_heredoc_tmp_token_roundtrip (real SubprocessManager) | CI |
| R07 | Workspace detection order: `SWE_WS`, then the git toplevel of cwd, then `$PWD`. Never silently use a non-git `/workspace` | `_ws.py:5-9` | test_install_paths.py::test_ws_fallbacks | CI |
| R08 | No skill script shadows a stdlib module | v5 select.py | existing test_skill_scripts_do_not_shadow_stdlib | CI |
| R09 | Helpers import only the stdlib and run on Python 3.10 to 3.13 | rules; Kaggle 3.12 | test_helpers_contract.py::test_stdlib_only_imports (AST vs `sys.stdlib_module_names`) | CI |
| R10 | Every diff helper uses `_swegemma_baseline` when the tag exists, else HEAD | F5 | test_helpers_contract.py::test_diff_base_after_agent_commit | CI |

### 5.2 install.py
| ID | Requirement | Evidence | Test | Tier |
|---|---|---|---|---|
| R11 | Idempotent, no more than 0.3 s, lists the installed tools | measured 25 ms | test_install_paths.py::test_install_idempotent_fast | CI |
| R12 | Works with `TMPDIR` unset or `$TMPDIR/swe` pre-existing; copies only `*.py` | `install.py:3-6` | test_install_paths.py::test_install_edge_dirs | CI |
| R13 | Output is 600 chars or fewer and shows the exact JSON form of the next call | 4/51 malformed calls | test_install_paths.py::test_install_output_budget | CI |

### 5.3 locate.py
| ID | Requirement | Evidence | Test | Tier |
|---|---|---|---|---|
| R14 | Output is 2,000 chars or fewer (hard harness cap 5,000, head kept: `tools/execution.py:49-51`) and ends with a next-step hint | max 1,635 | test_tasks_offline.py::test_locate_output_budget[tid] | CI |
| R15 | p95 runtime 3 s or less on a 2.2k-symbol repo. A second call on the same tree takes 0.3 s or less (index memoised in `$TMPDIR/swe`, keyed by HEAD plus the diff hash) | 2.0 / 3.7 s measured | test_locate_contract.py::test_locate_timing_and_cache | CI |
| R16 | Recall does not regress: gold file at rank 1 in at least 21/40, in the top 3 in at least 28/40, in the top 8 in at least 34/40 (local). Extend to 74 once snapshots exist | section 3 | test_tasks_offline.py::test_locator_recall[tid] plus aggregate | CI |
| R17 | Robust to PR-template boilerplate, bare "Fixes #NNNN" titles (27/74 statements under 200 chars), 10 kB statements and non-ASCII | static | test_locate_contract.py::test_query_edge_cases | CI |
| R18 | Never crashes on SyntaxError, Python 2, non-UTF-8, 1 MB-plus files or symlink loops; skips vendored and hidden dirs | `locate.py:10,32` | test_locate_contract.py::test_hostile_tree | CI |
| R19 | Deterministic: ties broken by path; identical output on repeated runs | code | test_locate_contract.py::test_deterministic | CI |
| R20 | Test files rank below source unless the query names them | `locate.py:59` | test_locate_contract.py::test_tests_ranked_low | CI |

### 5.4 run.py
| ID | Requirement | Evidence | Test | Tier |
|---|---|---|---|---|
| R21 | A timeout kills the whole process group (`start_new_session`, `killpg`), including background and grandchild processes | F7 | test_run_edges.py::test_timeout_kills_process_group (asserts no survivor via pgid) | CI |
| R22 | Body 3,500 chars or fewer; first 25 and last 45 lines kept; the pytest summary line is always visible; total under 5,000 after JSON escaping | `run.py:23-26` | existing test_run_strips_ansi..., plus test_tasks_offline.py::test_run_py_test_output[tid] | CI |
| R23 | Strips ANSI and OSC, normalises `\r`, survives binary or invalid UTF-8 output and a single 20 kB line | probe ok | test_run_edges.py::test_binary_and_long_line | CI |
| R24 | Full log at `$TMPDIR/swe/last.log` (seen by the model as `/tmp/swe/last.log`) | existing | existing test_variant_helpers_reachable_in_sandbox | CI |
| R25 | `--timeout` clamped to 1..120; a non-integer value gives a visible notice, not silent use of the default | probe: `abc` ignored silently | test_run_edges.py::test_timeout_arg_validation | CI |
| R26 | The exit code is printed first; stderr is kept | code | test_run_edges.py::test_exit_code_first_line | CI |

### 5.5 replace.py (edit robustness)
| ID | Requirement | Evidence | Test | Tier |
|---|---|---|---|---|
| R27 | Applying each gold hunk by line range, bottom-up, gives a file byte-identical to `git apply` | 122/122, 50/50 | test_tasks_offline.py::test_replace_gold_hunks[tid] | CI |
| R28 | CRLF files stay CRLF; only the edited lines change | F6: 5/5 lines rewritten | test_replace_edges.py::test_crlf_preserved | CI |
| R29 | Line numbers equal `read_file` and git numbering: split on `\n` only | F6: form feed shifted the edit | test_replace_edges.py::test_formfeed_and_unicode_separators | CI |
| R30 | A non-UTF-8 file gives a one-line error (or a byte-exact latin-1 round trip), never a traceback | F6 | test_replace_edges.py::test_non_utf8 | CI |
| R31 | BOM kept; a missing final newline stays missing unless the last line is edited | probe | test_replace_edges.py::test_bom_and_noeol | CI |
| R32 | Syntax check with in-memory `compile()`, auto-revert, error line reported relative to the edit | `replace.py:28-31` | existing revert test, plus test_replace_edges.py::test_error_line_relative | CI |
| R33 | Refuse protected paths (tests/, test_*.py, *_test.py, conftest.py, pytest.ini, pyproject.toml, setup.cfg, tox.ini) unless `--allow-test`; the message says why | F1 | test_replace_edges.py::test_refuses_protected | CI |
| R34 | Refuse paths outside the workspace (absolute or `..`) | probe wrote outside ws | test_replace_edges.py::test_refuses_outside_ws | CI |
| R35 | Accept content from `--from <file>` (content may contain a bare `EOF` line or path tokens). Empty content deletes lines and says so | R06 | test_replace_edges.py::test_from_file_and_delete | CI |
| R36 | `--create` for new files (4/74 golds add files; rich_3930 adds 23) | section 3 | test_tasks_offline.py::test_replace_gold_hunks[tid] covers new files | CI |
| R37 | Post-edit context of ±3 numbered lines, output 2,500 chars or fewer | `replace.py:32-34` | test_replace_edges.py::test_output_budget | CI |

### 5.6 gate.py: test discovery
| ID | Requirement | Evidence | Test | Tier |
|---|---|---|---|---|
| R38 | Pick only collectable test files (`test_*.py`, `*_test.py`); never `tests/render.py`, `tests/_card_render.py` or `tools/*.py` | 11/40 picked non-test files | test_tasks_offline.py::test_discovery_only_test_files[tid] | CI |
| R39 | Discovery recall: an existing test file of the hidden test_patch is picked in at least 23/39 (baseline); v10 target 30/39 using module-name, import-graph and changed-symbol signals | section 3 | test_tasks_offline.py::test_related_test_discovery[tid] plus aggregate | CI |
| R40 | Changed-symbol extraction covers methods, async defs, classes, module constants and `@@` hunk headers | `gate.py:18-20` | test_gate_edges.py::test_symbol_extraction | CI |
| R41 | New untracked test files are copied into the base copy, so "fails on original, passes on yours" confirms a repro | F3 traces | test_gate_edges.py::test_new_test_file_repro_semantics | CI |
| R42 | `--target` accepts `file::node` and `-k`; a missing target is an explicit error | trace fastapi_9753 | test_gate_edges.py::test_target_forms | CI |
| R43 | At most 3 files, total gate time 2×T + 3 s or less; the base copy is cached per HEAD | 5.3 s median | test_gate_edges.py::test_gate_timing_budget | CI |

### 5.7 gate.py: verdict correctness (regression gate)
| ID | Requirement | Evidence | Test | Tier |
|---|---|---|---|---|
| R44 | Verdict is PASS, FAIL or UNKNOWN. UNKNOWN when either run has no pytest summary, exit code 2, 4 or 5, a collection error in both, or a timeout | F3 | test_gate_edges.py::test_unknown_when_no_tests_ran (no-pytest python, missing file, collection error) | CI |
| R45 | On gold with default selection, no FAIL in at least 37/40 local tasks; rich_3942 listed as a known behaviour change | section 3 | test_tasks_offline.py::test_gate_gold[tid] | CI |
| R46 | On gold with `--target`, the known behaviour-change tasks (rich_3942, 3935, 3470, 3105, 3043, 3061) must not print "must fix" or "undo". They report the failures as "tests that encode the old behaviour: update only if the issue asks for it" | F4 | test_tasks_offline.py::test_gate_gold_target_wording[tid] | CI |
| R47 | Empty diff gives NO SOURCE CHANGE in under 1 s | 40/40, 0.3 s | test_tasks_offline.py::test_gate_empty[tid] | CI |
| R48 | The workspace is untouched by the gate | existing | existing test_gate_reports_regression_and_leaves_workspace | CI |
| R49 | Runs pytest with the scoring flags `-p no:anyio -o python_classes="Test* *Test"` and `PYTHONSAFEPATH=1 -s` (`verification.py:493`). Today `-o addopts=` removes the harness `-p no:anyio` | `gate.py:30` | test_gate_edges.py::test_uses_scoring_flags | CI |
| R50 | Failures come from JUnit XML, not the `^(FAILED|ERROR) (\S+)` regex, so parametrized ids with spaces or unicode are compared exactly | `gate.py:35` | test_gate_edges.py::test_param_ids_with_spaces | CI |
| R51 | Per-run timeout of 30 s with `killpg`. An original-version timeout is reported as "original hangs (expected for hang bugs)" | 3/40 hidden tests hang on unfixed code | test_gate_edges.py::test_hang_original | CI |
| R52 | Repeat guard: the same diff hash returns the cached verdict in one line, and the third identical call says STOP | F12, rich_3506 16× | test_gate_edges.py::test_memoised_verdict | CI |
| R53 | A regression is confirmed by one re-run before it is reported (de-flake) | rich_3938 flake under J=4 | test_gate_edges.py::test_deflake_rerun | CI |
| R54 | Output is 2,000 chars or fewer, and the verdict is on the first line | harness keeps the head | test_gate_edges.py::test_output_budget | CI |

### 5.8 check.py / test.py (patch hygiene, repro scripts)
| ID | Requirement | Evidence | Test | Tier |
|---|---|---|---|---|
| R55 | `check.py --mode preflight --fix` restores edited existing protected files from the baseline, deletes untracked scratch (repro*, scratch*, debug*, *.log, vendored packages), and prints the final diffstat | F1, 11/47 scratch | test_check_edges.py::test_fix_reverts_test_edits_and_scratch | CI |
| R56 | Reject (and on `--fix`, prune) patches over 200 kB or adding more than 20 files, and new top-level modules that shadow stdlib or installed distributions (`PYTHONPATH=/workspace` comes before stdlib) | 9.2 MB `_pytest` patch | test_check_edges.py::test_rejects_vendored_and_shadowing | CI |
| R57 | The final diff encodes as UTF-8 and passes `git apply --check` on a fresh `git archive` of the baseline | F11 class | test_check_edges.py::test_diff_roundtrip | CI |
| R58 | save and restore use `$TMPDIR/swe` per task; restore never ends with an empty tree when a checkpoint exists | `check.py:7-13` | test_check_edges.py::test_checkpoint_isolated | CI |
| R59 | Repro scripts live in `/tmp` (sandbox tmp) and run through `run.py` with a timeout; a repro in /workspace is flagged | 11/47 | test_check_edges.py::test_repro_in_workspace_flagged | CI |
| R60 | test.py uses the scoring flags, a 45 s timeout with `killpg`, and a JUnit summary | `test.py:13-15` | test_run_edges.py::test_testpy_flags | CI |

### 5.9 Prompts and agent tree
| ID | Requirement | Evidence | Test | Tier |
|---|---|---|---|---|
| R61 | Every tool named in a prompt exists in that agent's `tools:` (plus the skill tools when `skills:` is set). An unknown tool kills the session with patch 0 | F8: 3 e74 kills | test_prompts_rules.py::test_prompt_tools_exist | CI |
| R62 | Instruction templates contain only `{problem_description}`, `{hints?}`, `{plan?}` and `{fix_notes?}`. Any other `{identifier}` raises KeyError | `instructions_utils.py:122` | test_prompts_rules.py::test_state_vars_allowed | CI |
| R63 | The prompts forbid editing existing test and config files and name the reason (hidden test_patch) | F1 | test_prompts_rules.py::test_no_test_edit_rule | CI |
| R64 | `submit_patch` is the verifier's last call and is repeated after any later edit (only the final submission counts; the loop stops at submit, `agent_runner.py:635`) | code | test_prompts_rules.py::test_submit_last_rule | CI |
| R65 | The prompts show the exact JSON form of `run_skill_script` (4/51 malformed) | F2 | test_prompts_rules.py::test_skill_call_example_is_valid_json | CI |
| R66 | Each stage instruction is 1,500 tokens or fewer (chars / 3.5) | budget | test_prompts_rules.py::test_instruction_size | CI |
| R67 | Generation config: no `thinking_level`; `include_thoughts` is consistent; `max_output_tokens` is 4,096 or less; single model `gemma-4-31b-it-qat-w4a16-ct` | plan; validate.py | test_bundle_v10.py::test_generation_config | CI |
| R68 | Every stage that tells the model to use a helper either has `skills: [skills/swe-tools]` or gets the self-install fallback line | F2 | test_prompts_rules.py::test_helper_reachability_per_stage | CI |
| R69 | Stage call caps: the locator stays within its stated cap in at least 90% of canary tasks (today 19.4 calls on average against 8) | F12 | REPLAY test_trace_kpis.py::test_stage_call_caps | REPLAY, CANARY |

### 5.10 Budget and time
| ID | Requirement | Evidence | Test | Tier |
|---|---|---|---|---|
| R70 | eval_config has exactly the 4 scorer keys under `evaluation:` | forum; plan | existing test_run_eval_uses_bundle_eval_config, plus test_budget_time.py::test_eval_config_keys | CI |
| R71 | 12 h fit: 8.5 min start-up + N × (max_time_minutes + 0.3 min) ≤ 0.93 × 720 min with N = 125. This gives max_time_minutes ≤ 5.0 | e74_v3 567 s start-up; sub3 10.4 h | test_budget_time.py::test_fits_12h | CI |
| R72 | `timeout_seconds` also caps the scoring pytest (`verification.py:502`); keep it at 120 s or more and 180 s or less | code | test_budget_time.py::test_command_timeout_range | CI |
| R73 | The sum of helper-internal timeouts (gate 2 × 30 s plus discovery, test 45 s) stays under `timeout_seconds` | code | test_budget_time.py::test_helper_timeouts_under_command_timeout | CI |
| R74 | Projected Kaggle wall time from canary traces (H100-to-L4 factor 163/135 from e74_v3 vs r_v9_eog) is 11 h or less | section 4 | REPLAY test_trace_kpis.py::test_projected_wall | REPLAY |
| R75 | No task exceeds `max_time_minutes` plus 30 s | code | REPLAY test_trace_kpis.py::test_no_overrun | REPLAY |

### 5.11 Context size
| ID | Requirement | Evidence | Test | Tier |
|---|---|---|---|---|
| R76 | Each tool observation from our helpers is 2,500 chars or fewer, verdict first (the harness cuts the tail beyond 5,000) | `tools/execution.py:49-51` | test_helpers_contract.py::test_output_budgets | CI |
| R77 | Max prompt tokens per LLM call is 26,000 or fewer in canary traces (hard limit 28,672; r_v9_eg peaked at 28,655) | section 4 | REPLAY test_trace_kpis.py::test_prompt_tokens | REPLAY, CANARY |
| R78 | Worst-case static budget per stage: instruction + 10,095-char issue + cap × 2,500 chars ≤ 26k tokens | static | test_budget_time.py::test_worst_case_context | CI |
| R79 | Local runs use the kernel's events compaction (14,336 / 5) so pod behaviour matches Kaggle | F9(e) | test_parity.py::test_run_eval_sets_compaction | CI |

### 5.12 Empty-patch prevention and crash paths
| ID | Requirement | Evidence | Test | Tier |
|---|---|---|---|---|
| R80 | Empty-patch rate in canary: 2/51 or fewer (v9_eog 4, v4 9) | section 4 | REPLAY test_trace_kpis.py::test_empty_rate | REPLAY, CANARY |
| R81 | No helper ever resets the working tree to empty (`git checkout .`) except `check --mode restore` with a checkpoint | code | test_helpers_contract.py::test_no_destructive_git | CI |
| R82 | The three session-killing crash classes (R61, R62, R77) are statically impossible or bounded | F8 | covered by R61, R62, R78 | CI |
| R83 | The fixer leaves its best candidate on disk: the fallback diff is taken on timeout and budget exhaustion (`agent_runner.py:741-780`) | code | REPLAY test_trace_kpis.py::test_timeout_runs_have_patch | REPLAY |

### 5.13 Timeout and process safety
| ID | Requirement | Evidence | Test | Tier |
|---|---|---|---|---|
| R84 | No helper blocks longer than its timeout plus 2 s, including on a source tree with `while True:` at import | 3 hang tasks | test_helpers_contract.py::test_hang_fixture_bounded[<helper>] | CI |
| R85 | After each helper test, no process from its session survives (pgid check) | F7 | autouse fixture `no_orphans` in tests/v10/conftest.py | CI |
| R86 | The gold patch plus the hidden tests finish in under 30 s per task in parity (so a verify hang means "unfixed") | gold max 4.5 s | test_tasks_offline.py::test_gold_verifies[tid] timing | CI |

### 5.14 Submission packaging and bundle hygiene
| ID | Requirement | Evidence | Test | Tier |
|---|---|---|---|---|
| R87 | Compiles with the official compiler | existing | test_bundle_compiles_with_official_compiler, limited in CI to bundles listed in `submissions/ACTIVE` | CI |
| R88 | Allowed extensions only; no caches or AppleDouble | existing | existing | CI |
| R89 | The zip has `agent.yaml` at root; under 3 GiB; deterministic (sorted, fixed mtime); sha256 recorded in the ledger | plan | test_bundle_v10.py::test_zip_deterministic | CI |
| R90 | The shipped bundle equals the generator output (no hand-edit drift): rebuild with `make_variant.py`/v10 builder and diff | make_variant.py | test_bundle_v10.py::test_bundle_matches_generator | CI |
| R91 | SKILL.md usage lines match the scripts' real flags; description 1,024 chars or fewer | SKILL.md | test_bundle_v10.py::test_skill_usage_matches_scripts | CI |
| R92 | No network or external-model code in helpers (`socket`, `urllib`, `http.client`, `ssl` imports banned) | rules | test_helpers_contract.py::test_no_network_imports | CI |
| R93 | The rescore/eval kernel generator round-trips astral and non-ASCII patches | F11 | test_rescore_env.py::test_kernel_patches_roundtrip_astral (new) | CI |

### 5.15 Kaggle-image parity
| ID | Requirement | Evidence | Test | Tier |
|---|---|---|---|---|
| R94 | The local verifier env pins equal the Kaggle freeze for every package the 74 tasks import (`data/kaggle_freeze.txt`) | section 2 | test_parity.py::test_kpar_matches_freeze | CI (skip if venv absent) |
| R95 | No dirty-equals or inline-snapshot in the parity env | freeze; 21/36 vs 0/31 | test_parity.py::test_no_extra_test_libs | CI |
| R96 | Parity verifier: no editable install, `PYTHONPATH=/workspace`, host site-packages visible. requests_6644 empty patch passes in parity (documents F10) | F10 | test_tasks_offline.py::test_empty_fails[tid] with KNOWN_FREE={requests_6644} | NIGHTLY |
| R97 | The pod sandbox is offline (`PIP_NO_INDEX=1`, `PIP_FIND_LINKS=/wheels`, or `unshare -n`) | F9(a) | test_parity.py::test_pod_sandbox_offline (static on `pod/run_eval.sh`, `scripts/run_eval.py`) | CI |
| R98 | Pod buildenv pytest equals Kaggle (8.4.2, not 8.3.4); the agent's bare `pytest` resolves to the sandbox venv, not hvenv (9.1.1) | F9(b) | test_parity.py::test_pytest_version_parity | CI |
| R99 | Pod env installs nothing into /workspace (no editable install) when FAITHFUL=1 | F9(d) | test_parity.py::test_no_editable_install_in_faithful | CI |
| R100 | The harness wheels used locally equal the pins (google-adk 1.36.1, vllm 0.19.1, swegemma 0.2.7) | plan | test_parity.py::test_harness_versions | CI |
| R101 | Linux parity: helpers plus per-task verify inside `docker run --network none python:3.12-slim` | v5 select.py | tests/v10/docker/run_nightly.sh | NIGHTLY |
| R102 | Before any GPU run, the Kaggle CPU rescore of gold and empty patches over all 74 agrees with the local parity verifier | e74 / rescore kernels | `make_eval_kernel.py --patches` with gold and empty labels | PRE-GPU |

## 6. Per-task parametrized offline tests (no GPU)

New file `tests/v10/test_tasks_offline.py`, parametrized over `data/kaggle_valid_ids.txt` (74 ids).
Tasks without a snapshot skip with the exact fetch command.

Fixtures (`tests/v10/conftest.py`):
- `task(tid)`: the row from `data/tasks.jsonl`, plus `gold = parse_patch(patch)` (port `parse_patch` from `scratchpad/tpv10/measure2.py`, which handles `@@ -0,0` new files and blank context lines) and `test_files = extract_test_files_from_patch(test_patch)` from swegemma.
- `base_ws(tid)` (session scope): extracts `data/raw/snapshots/<tid>.tgz` once into `$G4_CACHE/<tid>/base` (default `~/.cache/g4/ws`) and applies the harness Container A setup exactly:
  - append the git exclude lines from `container_setup.py:498-504`;
  - write the harness `pytest.ini` and conftest hook;
  - `git add -A && git commit -qm baseline --allow-empty && git tag -f _swegemma_baseline`.
- `ws(base_ws)` (function scope): `cp -c -R` APFS clone (0.14 s).
- `kpar(repo)`: `.kpar/rich/bin/python` or `.kpar/fastapi/bin/python`; skips with the `build_kpar.sh` command if missing.
- `sandbox_env(ws)`: `HOME=TMPDIR=TEST_TMPDIR=<ws>_tmp`, `PYTHONPATH=<ws>`, `PYTHONNOUSERSITE=1`, `PYTHONDONTWRITEBYTECODE=1`, `PATH=<kpar>/bin:...`, `LANG=C.UTF-8`. This mirrors `build_sanitized_env` plus `subprocess.py:483-488`.
- `helpers`: a copy of `<bundle>/skills/swe-tools/scripts` in a tmp dir. Tests never run scripts inside `submissions/`.
- `no_orphans` (autouse): records the pgid before the test and fails if any process in it survives.
- `verify(ws, patch, *, tamper=None, timeout=20)`: a port of `verification.py:305-505`. It uses the harness-exact reset list (including `sitecustomize.py`), the harness apply order, the pytest command from `:493`, `_validate_junit_xml`, and the stdout checks from `:522`.

Tests. Measured baselines come from section 3; "aggregate" means a session-level test that reads the per-task results the
parametrized tests write to `eval/offline/<name>.json` and asserts the threshold.

| Test | Asserts | Baseline / known exceptions |
|---|---|---|
| test_locator_recall[tid] | rank of the first gold .py in `locate.py --query <problem_statement>`; aggregate @1 ≥ 21, @3 ≥ 28, @8 ≥ 34 (of 40) | misses: rich_3953, 3944, 3468, 3105, 3067, 3063 (xfail, not strict) |
| test_locate_output_budget[tid] | at most 2,000 chars, at most 3 s | max 1,635 chars, 3.7 s |
| test_related_test_discovery[tid] | `gate.py --list` (new flag: print the picked files and exit) intersects the existing test_patch files; aggregate ≥ 23/39, v10 target 30 | 16 misses listed in measure2.jsonl |
| test_discovery_only_test_files[tid] | every picked file matches `test_*.py` or `*_test.py` | 11 current failures (they must pass in v10) |
| test_gate_empty[tid] | NO SOURCE CHANGE, under 1 s | 40/40 |
| test_gate_gold[tid] | after `git apply` of gold, verdict is not FAIL | KNOWN_BEHAVIOUR_CHANGE = {rich_3942}; UNKNOWN allowed for {rich_3105, rich_3043} |
| test_gate_gold_target_wording[tid] | gold with `--target <first existing test_patch file>`: verdict PASS, or wording has no "must fix" or "undo" for KNOWN_BEHAVIOUR_CHANGE = {rich_3942, 3935, 3470, 3105, 3043, 3061} | 6 deterministic plus the rich_3938 flake (R53) |
| test_replace_gold_hunks[tid] | each hunk bottom-up via `replace.py --start --end` (and `--create` for `@@ -0,0`), byte-identical to `git apply` | 122/122, 50/50; rich_3930 needs --create |
| test_gold_verifies[tid] | `verify(gold)` resolved, runtime under 30 s | 39/40; requests_6644 needs installed requests (F10) |
| test_empty_fails[tid] | `verify("")` not resolved within 20 s (hang = not resolved) | hang: rich_4006, rich_3772, rich_3480; KNOWN_FREE (parity) = {requests_6644} |
| test_tamper_is_lost_under_harness[tid] | edit inside the first test_patch hunk, then the harness reset: `reset_ok` is False and the test_patch fails. `xfail(strict=True)` documents F1 and alerts if the harness is fixed | 39/39 |
| test_tamper_fixed_by_preflight[tid] | same edit, then `check.py --mode preflight --fix`, then `verify` passes | new (R55) |
| test_prompt_fits_context[tid] | each stage instruction rendered with this `problem_statement`: estimated tokens (chars/3.2) + tool schema overhead ≤ 8,000 | max statement 10,095 chars |
| test_run_py_test_output[tid] | `run.py --timeout 20 "python3 -m pytest <target> -q"`: first line is `exit=`, a summary line is present, 3,500 chars or fewer | new |
| test_gold_patch_hygiene[tid] | `check.py --mode preflight` on gold says READY with no false flags; gold plus a scratch `repro.py` is flagged | new |
| test_static_patch_facts[tid] (no snapshot needed, all 74) | parse_patch round-trip; protected-file and new-file classification equals `static_gold.json` | 74/74 run today |

Trace-KPI replay (`tests/v10/test_trace_kpis.py`): offline, parametrized over run directories. The default is every
`eval/race1/runs/r_*`; new canary runs are added by path.

| KPI | Threshold for a v10 canary | race1 v9_eog today |
|---|---|---|
| "can't open file" helper calls | 0 | 70 |
| tasks without a successful install | 0 | 24/51 |
| max prompt tokens | 26,000 or fewer | 25,352 |
| ContextWindow / unknown-tool / KeyError crashes | 0 | 0 (other arms up to 4) |
| empty patches | 2/51 or fewer | 4 |
| patches touching existing protected files | 0 | 10/47 |
| patches with scratch or vendored files | 0 | 11/47 |
| tasks with an identical call 5 or more times | 5/51 or fewer | 24/51 |
| gate false PASS (no summary) | 0 | 3 |
| locator mean calls | 8 or fewer | 19.4 |

Commands:
```bash
cd /Users/carson/Projects/gemma-swe-agent
# CI (target < 10 min)
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests -m "not nightly" --durations=20
# nightly (all 74, hang cap 20 s, Docker parity)
PYTHONDONTWRITEBYTECODE=1 G4_J=4 .venv/bin/python -m pytest -q -p no:cacheprovider tests/v10 -m nightly
bash tests/v10/docker/run_nightly.sh   # docker run --rm --network none -v $PWD:/g4:ro python:3.12-slim ...
# trace replay on a new canary run
.venv/bin/python -m pytest -q tests/v10/test_trace_kpis.py --runs eval/<canary>/runs/c_v10
```
Parallelism: pytest-xdist is not installed (`-n` rejected). Either add it to `.venv`, or run the per-task body inside one
test with a `ThreadPoolExecutor(G4_J)`, as `measure2.py` does. Keep at most 4 workers, and run gate verdicts serially or
with a re-run (the rich_3938 flake).

## 7. CI (< 10 min) versus nightly

Per-task costs come from section 3 at J=4. The hang cap is 20 s instead of 300 s.

| Group | Tests | Estimated wall | Tier |
|---|---|---|---|
| Existing suite, with bundle compilation limited to active bundles (v10*, sub*) | 380 items to about 250 | about 40 s (today 135 s, of which about 110 s is validate.py × 21) | CI |
| Helper unit and edge tests (sections 5.1 to 5.8), static prompt, bundle, budget and parity checks | about 90 new tests, each under 1 s except the process-group and hang fixtures (2 to 3 s) | about 60 s | CI |
| Per-task cheap group on every local snapshot: static facts, locate recall and budget, replace gold hunks, gate empty, discovery, prompt fit, gold hygiene | 40 tasks × about 3.5 s | about 45 s at J=4 (about 90 s with 74 tasks) | CI |
| Per-task gate on gold (default and `--target`), run.py output | 40 × about 11 s | about 2 min at J=4 (about 4 min with 74) | CI while at most 40 tasks; move to nightly when 74 are local |
| Per-task gold verify, empty verify (20 s hang cap), tamper both ways | 40 × about 5 s + 3 hangs × 20 s | about 70 s at J=4 (about 2.5 min with 74) | NIGHTLY (fast enough for CI, but it needs the kpar venvs) |
| Trace-KPI replay over race1 plus the latest canary | 6 to 8 run dirs | about 20 s | CI |
| Docker Linux parity (helpers plus per-task verify, `--network none`) | all | about 15 min (UNVERIFIED estimate) | NIGHTLY |
| Determinism: locate and gate run 3 times; flake detector | all | about 10 min | NIGHTLY |
| Kaggle CPU rescore of gold and empty over 74 (free, Carson pushes) | 74 | about 25 min kernel (UNVERIFIED) | PRE-GPU |
| GPU canary (1 to 3 tasks, then the 51-task race) | | paid | only after all of the above are green |

The CI total is about 5 to 6 min with the 40 local tasks, and about 8 to 9 min with 74 if the gate-on-gold group moves to
nightly.

## 8. Bugs found during this investigation (reproducible)

1. Harness reset is a no-op (F1). Repro: `measure2.py` `verify_tamper` on any rich task, or in a scratch git repo run
   `git checkout HEAD -- tests/test_x.py sitecustomize.py`. The result is rc=1 and `tests/test_x.py` is still modified.
   Worth reporting on the forum; per the rules this is a publish-now bug report.
2. Rescore kernel surrogate corruption (F11): `scripts/make_eval_kernel.py:44`. Fix it with `json.dumps(PATCHES, ensure_ascii=False)` or base64, then rescore p_v7/p_v8 rich_3930 and rich_3953.
3. Gate false PASS (F3), non-test file selection (R38), a wording that makes the model undo correct fixes (F4), the HEAD diff base (F5), and scoring-flag drift (R49).
4. replace.py: CRLF rewrite, separator line-shift, latin-1 traceback, edits to protected and outside paths (F6).
5. run.py orphan processes on timeout (F7).
6. Pod parity: network, pytest version, extra test libs, editable install, no compaction (F9).

## 9. Open questions and UNVERIFIED items

- Does the Kaggle scorer's own script set the same `EventsCompactionConfig` as `make_eval_kernel.py:94-95`? The plan says
  so (threshold 14,336, keep 5), but it is UNVERIFIED against the scorer source.
- Do leaked processes persist across tasks on the Kaggle scoring VM? The code says yes; not observed.
- On Kaggle, does requests_6644 pass with an empty patch? A local parity run with requests 2.33.0 says yes; UNVERIFIED on
  2.32.4 and on Kaggle.
- Hidden-set layout: if some private repos use a src layout without being installed on the host, their tests cannot
  import the package on Kaggle for anyone (F10). Unknowable offline.
- The fastapi numbers in this plan are extrapolated; none of the 31 fastapi tasks could be measured here without the
  one-time download.
- Kaggle L4 CPU speed for the gate and pytest is unmeasured. The H100-pod and Mac timings may understate it; the
  per-helper budgets should be re-measured in the PRE-GPU CPU kernel.

## Appendix A. The 74 Kaggle-valid tasks: local status and measured results (v9_eog helpers)

"Agent test edit" means an edit inside the first hidden-test hunk followed by the harness reset. "lost (no)" means the
reset did not happen and the test_patch failed to apply.

| # | task | snap | gold py files / lines | test_patch edits existing test file | new test file | locate rank | discovery hit | gate gold | gate gold+target | gold verify | empty verify | tamper (reset happened?) | offline needs |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | fastapi_5077 | MISSING | 1 / 6 | no | yes | - | - | - | - | - | - | - | snapshot download + fastapi parity env (network once) |
| 2 | fastapi_5624 | MISSING | 1 / 4 | no | yes | - | - | - | - | - | - | - | snapshot download + fastapi parity env (network once) |
| 3 | fastapi_9425 | MISSING | 1 / 2 | no | yes | - | - | - | - | - | - | - | snapshot download + fastapi parity env (network once) |
| 4 | fastapi_9555 | MISSING | 1 / 22 | no | yes | - | - | - | - | - | - | - | snapshot download + fastapi parity env (network once) |
| 5 | fastapi_9753 | MISSING | 1 / 7 | no | yes | - | - | - | - | - | - | - | snapshot download + fastapi parity env (network once) |
| 6 | fastapi_11194 | MISSING | 1 / 7 | no | yes | - | - | - | - | - | - | - | snapshot download + fastapi parity env (network once) |
| 7 | fastapi_13537 | MISSING | 1 / 3 | no | yes | - | - | - | - | - | - | - | snapshot download + fastapi parity env (network once) |
| 8 | fastapi_13920 | MISSING | 1 / 4 | no | yes | - | - | - | - | - | - | - | snapshot download + fastapi parity env (network once) |
| 9 | fastapi_14077 | MISSING | 3 / 11 | yes | no | - | - | - | - | - | - | - | snapshot download + fastapi parity env (network once) |
| 10 | fastapi_14258 | MISSING | 1 / 4 | no | yes | - | - | - | - | - | - | - | snapshot download + fastapi parity env (network once) |
| 11 | fastapi_14301 | MISSING | 1 / 5 | yes | no | - | - | - | - | - | - | - | snapshot download + fastapi parity env (network once) |
| 12 | fastapi_14306 | MISSING | 2 / 137 | no | yes | - | - | - | - | - | - | - | snapshot download + fastapi parity env (network once) |
| 13 | fastapi_14372 | MISSING | 2 / 7 | no | yes | - | - | - | - | - | - | - | snapshot download + fastapi parity env (network once) |
| 14 | fastapi_14419 | MISSING | 2 / 62 | no | yes | - | - | - | - | - | - | - | snapshot download + fastapi parity env (network once) |
| 15 | fastapi_14448 | MISSING | 2 / 106 | yes | no | - | - | - | - | - | - | - | snapshot download + fastapi parity env (network once) |
| 16 | fastapi_14458 | MISSING | 1 / 7 | yes | no | - | - | - | - | - | - | - | snapshot download + fastapi parity env (network once) |
| 17 | fastapi_14463 | MISSING | 1 / 3 | no | yes | - | - | - | - | - | - | - | snapshot download + fastapi parity env (network once) |
| 18 | fastapi_14479 | MISSING | 1 / 2 | yes | no | - | - | - | - | - | - | - | snapshot download + fastapi parity env (network once) |
| 19 | fastapi_14487 | MISSING | 1 / 7 | yes | no | - | - | - | - | - | - | - | snapshot download + fastapi parity env (network once) |
| 20 | fastapi_14492 | MISSING | 1 / 2 | yes | no | - | - | - | - | - | - | - | snapshot download + fastapi parity env (network once) |
| 21 | fastapi_14616 | MISSING | 1 / 12 | no | yes | - | - | - | - | - | - | - | snapshot download + fastapi parity env (network once) |
| 22 | fastapi_14786 | MISSING | 1 / 2 | yes | no | - | - | - | - | - | - | - | snapshot download + fastapi parity env (network once) |
| 23 | fastapi_14794 | MISSING | 1 / 5 | no | yes | - | - | - | - | - | - | - | snapshot download + fastapi parity env (network once) |
| 24 | fastapi_14851 | MISSING | 1 / 157 | yes | no | - | - | - | - | - | - | - | snapshot download + fastapi parity env (network once) |
| 25 | fastapi_14873 | MISSING | 1 / 21 | yes | no | - | - | - | - | - | - | - | snapshot download + fastapi parity env (network once) |
| 26 | fastapi_14986 | MISSING | 2 / 34 | no | yes | - | - | - | - | - | - | - | snapshot download + fastapi parity env (network once) |
| 27 | fastapi_15280 | MISSING | 2 / 72 | no | yes | - | - | - | - | - | - | - | snapshot download + fastapi parity env (network once) |
| 28 | fastapi_15588 | MISSING | 1 / 23 | yes | no | - | - | - | - | - | - | - | snapshot download + fastapi parity env (network once) |
| 29 | fastapi_15589 | MISSING | 1 / 4 | yes | no | - | - | - | - | - | - | - | snapshot download + fastapi parity env (network once) |
| 30 | fastapi_15661 | MISSING | 1 / 216 | no | yes | - | - | - | - | - | - | - | snapshot download + fastapi parity env (network once) |
| 31 | fastapi_15800 | MISSING | 8 / 654 | no | yes | - | - | - | - | - | - | - | snapshot download + fastapi parity env (network once) |
| 32 | requests_6644 | yes | 1 / 3 | no | yes | 6 | n/a | PASS | n/a | FAIL (kpar lacks installed requests) | fail locally; PASS with site-packages requests 2.33.0 | n/a | kpar + installed requests (site-packages shadow) |
| 33 | rich_2725 | yes | 1 / 10 | yes | no | 2 | yes | PASS | PASS | PASS | fail | lost (no) | kpar (offline OK) |
| 34 | rich_2943 | yes | 1 / 2 | yes | no | 1 | no | PASS | PASS | PASS | fail | lost (no) | kpar (offline OK) |
| 35 | rich_3006 | yes | 1 / 2 | yes | no | 1 | no | PASS | PASS | PASS | fail | lost (no) | kpar (offline OK) |
| 36 | rich_3043 | yes | 1 / 2 | yes | no | 5 | no | NONE | FAIL | PASS | fail | lost (no) | kpar (offline OK) |
| 37 | rich_3052 | yes | 1 / 34 | yes | no | 1 | yes | PASS | PASS | PASS | fail | lost (no) | kpar (offline OK) |
| 38 | rich_3061 | yes | 1 / 91 | yes | no | 1 | no | PASS | FAIL | PASS | fail | lost (no) | kpar (offline OK) |
| 39 | rich_3063 | yes | 1 / 4 | yes | no | miss | yes | PASS | PASS | PASS | fail | lost (no) | kpar (offline OK) |
| 40 | rich_3067 | yes | 1 / 2 | yes | no | miss | yes | PASS | PASS | PASS | fail | lost (no) | kpar (offline OK) |
| 41 | rich_3105 | yes | 1 / 2 | yes | no | miss | no | NONE | FAIL | PASS | fail | lost (no) | kpar (offline OK) |
| 42 | rich_3180 | yes | 2 / 127 | yes | no | 6 | yes | PASS | PASS | PASS | fail | lost (no) | kpar (offline OK) |
| 43 | rich_3278 | yes | 1 / 1 | yes | no | 8 | yes | PASS | PASS | PASS | fail | lost (no) | kpar (offline OK) |
| 44 | rich_3454 | yes | 1 / 2 | yes | no | 1 | yes | PASS | PASS | PASS | fail | lost (no) | kpar (offline OK) |
| 45 | rich_3468 | yes | 1 / 42 | yes | no | miss | no | PASS | PASS | PASS | fail | lost (no) | kpar (offline OK) |
| 46 | rich_3470 | yes | 1 / 2 | yes | no | 1 | no | PASS | FAIL | PASS | fail | lost (no) | kpar (offline OK) |
| 47 | rich_3471 | yes | 1 / 1 | yes | no | 1 | no | PASS | PASS | PASS | fail | lost (no) | kpar (offline OK) |
| 48 | rich_3472 | yes | 1 / 4 | yes | no | 1 | yes | PASS | PASS | PASS | fail | lost (no) | kpar (offline OK) |
| 49 | rich_3480 | yes | 1 / 4 | yes | no | 4 | no | PASS | PASS | PASS | HANG | lost (no) | kpar (offline OK) |
| 50 | rich_3506 | yes | 1 / 17 | yes | no | 1 | no | PASS | PASS | PASS | fail | lost (no) | kpar (offline OK) |
| 51 | rich_3518 | yes | 1 / 2 | yes | no | 1 | no | PASS | PASS | PASS | fail | lost (no) | kpar (offline OK) |
| 52 | rich_3521 | yes | 1 / 35 | yes | no | 1 | no | PASS | PASS | PASS | fail | lost (no) | kpar (offline OK) |
| 53 | rich_3535 | yes | 2 / 8 | yes | no | 3 | no | PASS | PASS | PASS | fail | lost (no) | kpar (offline OK) |
| 54 | rich_3675 | yes | 2 / 41 | yes | no | 1 | yes | PASS | PASS | PASS | fail | lost (no) | kpar (offline OK) |
| 55 | rich_3676 | yes | 2 / 13 | yes | no | 3 | yes | PASS | PASS | PASS | fail | lost (no) | kpar (offline OK) |
| 56 | rich_3718 | yes | 1 / 7 | yes | no | 1 | no | PASS | PASS | PASS | fail | lost (no) | kpar (offline OK) |
| 57 | rich_3772 | yes | 1 / 45 | yes | no | 1 | yes | PASS | PASS | PASS | HANG | lost (no) | kpar (offline OK) |
| 58 | rich_3777 | yes | 2 / 13 | yes | no | 2 | yes | PASS | PASS | PASS | fail | lost (no) | kpar (offline OK) |
| 59 | rich_3782 | yes | 1 / 29 | yes | no | 1 | yes | PASS | PASS | PASS | fail | lost (no) | kpar (offline OK) |
| 60 | rich_3882 | yes | 1 / 2 | yes | no | 1 | yes | PASS | PASS | PASS | fail | lost (no) | kpar (offline OK) |
| 61 | rich_3894 | yes | 1 / 4 | yes | no | 1 | yes | PASS | PASS | PASS | fail | lost (no) | kpar (offline OK) |
| 62 | rich_3905 | yes | 1 / 7 | yes | no | 1 | yes | PASS | PASS | PASS | fail | lost (no) | kpar (offline OK) |
| 63 | rich_3930 | yes | 26 / 12714 | yes | yes | 6 | yes | PASS | PASS | PASS | fail | lost (no) | kpar (offline OK) |
| 64 | rich_3934 | yes | 2 / 20 | yes | no | 1 | yes | PASS | PASS | PASS | fail | lost (no) | kpar (offline OK) |
| 65 | rich_3935 | yes | 1 / 16 | yes | no | 2 | no | PASS | FAIL | PASS | fail | lost (no) | kpar (offline OK) |
| 66 | rich_3938 | yes | 2 / 45 | yes | no | 2 | no | PASS | FAIL (flake under J=4; PASS 2/2 serial) | PASS | fail | lost (no) | kpar (offline OK) |
| 67 | rich_3942 | yes | 2 / 70 | yes | no | 1 | yes | FAIL | FAIL | PASS | fail | lost (no) | kpar (offline OK) |
| 68 | rich_3944 | yes | 1 / 2 | yes | no | miss | yes | PASS | PASS | PASS | fail | lost (no) | kpar (offline OK) |
| 69 | rich_3953 | yes | 1 / 26 | yes | no | miss | yes | PASS | PASS | PASS | fail | lost (no) | kpar (offline OK) |
| 70 | rich_4006 | yes | 1 / 45 | yes | no | 1 | yes | PASS | PASS | PASS | HANG | lost (no) | kpar (offline OK) |
| 71 | rich_4075 | yes | 1 / 15 | yes | no | 2 | yes | PASS | PASS | PASS | fail | lost (no) | kpar (offline OK) |
| 72 | rich_4076 | MISSING | 1 / 6 | yes | no | - | - | - | - | - | - | - | snapshot download (kpar OK) |
| 73 | rich_4077 | MISSING | 1 / 3 | yes | no | - | - | - | - | - | - | - | snapshot download (kpar OK) |
| 74 | rich_4079 | MISSING | 1 / 7 | yes | no | - | - | - | - | - | - | - | snapshot download (kpar OK) |

## Appendix B. Reproducing every number in this report

| Number | Command (from the scratch dir `scratchpad/tpv10/` unless noted) |
|---|---|
| Suite inventory and 135 s | `cd /Users/carson/Projects/gemma-swe-agent && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests --durations=15` |
| Section 3 per-task results | `J=4 /Users/carson/Projects/gemma-swe-agent/.venv/bin/python measure2.py` produces `measure2.jsonl` (40 rows) |
| Gate target re-runs (flake check) | `/Users/carson/Projects/gemma-swe-agent/.venv/bin/python rerun_gate.py rich_3938 rich_3935 rich_3061 rich_3470 rich_3942 rich_3105` |
| Static facts of 74 patches | `/Users/carson/Projects/gemma-swe-agent/.venv/bin/python static_gold.py static_gold.json` |
| Helper edge probes (CRLF, form feed, latin-1, orphans, gate UNKNOWN, git commit base) | `python3.12 edge_probe.py` |
| Race 1 helper availability and outcomes | `python3 helper_stats.py r_v9_eog r_v4 r_v9_eg`; `python3 gate_dump.py r_v9_eog "/tmp/swe/gate.py" 80` |
| Race 1 arm table | `python3 run_stats.py` |
| requests_6644 empty-patch parity | venv `kpar_req` (pytest 8.4.2 + requests 2.33.0 offline); snapshot at `rq/` with the test_patch applied; `PYTHONPATH=$PWD PYTHONSAFEPATH=1 PYTHONNOUSERSITE=1 ../kpar_req/bin/python -s -m pytest tests/test_adapters.py -p no:anyio -q` gives 1 passed; with `PYTHONPATH=$PWD/src` it gives 1 failed |
| git checkout pathspec abort | in any git repo: modify a tracked file, then `git checkout HEAD -- <file> sitecustomize.py; echo $?` gives 1, file still modified |
| Kaggle freeze facts | `grep -iE "^(pytest|Pygments|pydantic|starlette|anyio|requests|rich|fastapi)==" /Users/carson/Projects/gemma-swe-agent/eval/kaggle/rescore_fair/pip_freeze.txt` |
