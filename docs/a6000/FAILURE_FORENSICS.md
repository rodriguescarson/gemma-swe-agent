# Failure forensics: what is failing and why (P5, 2026-10-07)

Read-only analysis of the traces on disk, done while stage 1b ran; nothing in any bundle was changed. Inputs: stage 1a (v4h2, v6p, v6p-think: 50 tasks each, `~/g4/runs/p2/items/`),
P4 (v5h2 on the public 74, `~/g4/runs/p4/`, the 21 contaminated rows excluded and re-run), the v6p-b probe (4 tasks), and the Kaggle L4 traces of v4h2g (`eval/kaggle/g4-l4-v4h2g-p312`).
Every tool call of every trace (10,461 calls) was classified by `scripts/a6000/forensics_lib.py` (tests/test_a6000_forensics.py, 13 tests); the generated tables are in
[forensics_generated.md](forensics_generated.md) (`scripts/a6000/forensics.py`), the prompt-vs-reality runs in [forensics_prompts.md](forensics_prompts.md) (`scripts/a6000/forensics_prompts.py`,
tests/test_a6000_forensics_prompts.py, 7 tests), the full test suite in [forensics_pytest.md](forensics_pytest.md). GATE.md "P2 addendum 10" (the locator spends the budget) is taken as read and not redone.

Owner legend: **ours** = our helper scripts, prompts or bundle wiring; **harness** = the competition harness, ADK, or the vLLM gemma4 tool-call parser; **model** = the model's own choices.
"Tasks" = tasks in which the mechanism occurred at least once (v4h2 / v6p / v6p-think of 50 each; v5h2 of 74 in P4).

## Ranked table

| # | mechanism | tasks affected (v4h2 / v6p / v6p-think / v5h2-P4) | calls | owner | example | proposed fix (not applied) | confidence |
|---|---|---|---|---|---|---|---|
| 1 | **view.py refuses the call shapes the model uses** (`FILE 30-40`, bare `FILE`): prints its usage line, exit 0, the model gets nothing | - / 24 / 6 / **33** | 139 | ours | v5h2 fastapi_15588 `view.py fastapi/sse.py 42-143`; v6p arrow_1278a21 `view.py arrow/util.py 30-40` | accept `A-B`, `A:B`, `A` (A..A+119) and bare `FILE` (1..120); say "START END or START-END" in the prompts | high |
| 2 | **the locator spends the 70-call budget** (BudgetExceeded then): tasks that hit 70 calls, with the locator the top spender in 4 / 14 / 5 / 10 of them | 9 / 21 / 5 / 13 | 362 | ours (design) | v6p arrow_1278a21 (selector refused at call 71); v5h2 fastapi_11194 (60 failed greps, 0-char patch) | the v6p-b ledger (addendum 10); the same cap for v5h2's and v4h2's locator; no forced extra calls (see 6) | high |
| 3 | **our call-shape wording is copied into the command** (`run_command(command="...")`, `run_command: ...`, `run_command "..."`, `submit_patch` as a shell line) -> bash error | 22 / 14 / 0 / 18 (+1 of 4 in the v6p-b probe) | 63 | ours | v4h2 arrow_0fe5f06 `run_skill_script(skill_name="swe-tools", file_path="install.py")` sent as a command; v5h2 fastapi_15588 `run_command: git grep ...` | reword: "call the tool `run_command`; its single argument `command` is the shell line"; never print `run_command(command=` in a prompt | high |
| 4 | **"write /tmp/repro.py" with a tool that cannot write outside the workspace** (`write_file` -> "Path traversal detected") | 2 / 4 / 8 / **28** | 47 | ours | v5h2 verifier step 2b: 29 refusals in 28 tasks; v6p locator 4, v6p-think 8 | say `run_command(command="cat > /tmp/repro.py <<'EOF' ... EOF")` (v6p's locator wording) and drop `write_file`/`edit_file` from the locator and verifier tool lists (v6p-b dropped them for the locator) | high |
| 5 | **the gemma4 tool parser corrupts or drops arguments**: read_file with the other arguments glued into the path (`params.py`,start_line:303,end_line:384`), run_skill_script with `{}` (INVALID_ARGUMENTS), skill names quoted as `「swe-tools」`, raw `<\|tool_call>call:read_file{...}` leaking into text | 23+18 / 6 / 1 / 17+37 | 335 (+14 leaked messages) | harness | v5h2 rich_3521: 10 corrupted read_file calls in a lost task; the fixer's forced first install call arrives with `{}` in 34 of 74 P4 tasks | expose no multi-argument tool to the model: read through `view.py` (single string; v6p-b does), drop the redundant forced install call (6) | mechanism high, root cause (parser vs model syntax) medium |
| 6 | **a forced install call where a setup stage already installed** ("Your first tool call is always run_skill_script(install.py)") - wasted, and the call that most often arrives with dropped arguments | v4h2 n/a / 50 / 50 / 74 (every task) | ~120 (1-2 per task) | ours | v5h2: 116 fixer run_skill_script calls, 41 of them `{}` | delete the sentence from fixer/verifier prompts of bundles with a setup stage | high |
| 7 | **the v6p repro-first contract does not hold**: the locator runs the file directly (44/50) instead of `/tmp/swe/repro.py` (0/50), writes try/except prints instead of a bare assert, and select_best then reports "passes before the fix: ignored" (16 of 28 reports); 25/50 tasks break at this step | - / 25 / 29 / - | n/a | ours (design + prompt) | v6p arrow_0fe5f06: repro "passes before the fix" so the ranking fell back to the test file | one helper call that writes and runs the script with the right PYTHONPATH and refuses a script without `assert`; or drop S3 and keep select_best on the test file only | high |
| 8 | **helpers never installed (v4h2 only)**: "can't open file" on check/locate/test/edit | **49** / 0 / 0 / 0 | 149 | ours (known) | v4h2 arrow_06fe693 `python3 /tmp/swe/check.py --mode preflight` | the setup stage (v5h2: 0 of 74; v6p: 0 of 50); the GATE helper finding stands | high |
| 9 | **loops on the same failing or useful command** (identical call >= 5 times in a row; locator mostly): `git grep` with no match x62, a useful `grep` x49, a corrupted read_file x50 | 7 / 9 / 6 / **25** | 54 loops | model (3 of 54 loops are ours: empty reply, usage line, the corrupted read_file) | v5h2 rich_4076 locator `git grep -n "preserve_newlines"` x62 then budget | our repeat refusal in view.py works (the ALREADY SHOWN loop stopped after 6); a shell-level "same command, same result" refusal is the harness's tool, not ours; the locator cap (2) bounds the damage | high |
| 10 | **verifier keeps calling after "budget exhausted" until the 150-turn cap** (`git diff` x58-63, every reply the same error) | 4 / 1 / 0 / 0 | 5 loops | harness + ours | v4h2 attrs_dbb25ce, v6p attrs_7804a68 (turn-budget error after 67 refused calls) | prompt line: "if a reply says budget exhausted, call submit_patch now" (submit_patch still succeeds after the budget: P4 fastapi_14616) | medium |
| 11 | **model edit failures** our edit.py catches: SYNTAX ERROR reverted 13/22/1/59 calls, NO CHANGE 4/11/0/122 (one P4 task 100+ times), NO MATCH, AMBIGUOUS, test-file edits REFUSED 8/14/7/6 | 9 / 6 / 1 / 4 (SYNTAX); 6 / 5 / 3 / 4 (REFUSED) | ~330 | model (13 reverts are the model pasting SEARCH/REPLACE markers into a `--lines` edit: prompt clarity, ours) | v5h2 fastapi_14306 `--lines 637-640` with `<<<<<<< SEARCH` inside | edit.py: refuse a `--lines`/`--create` body containing the markers with a one-line hint; on NO CHANGE say "already in the file: run the test" | high |
| 12 | **sandbox environment differs from the wheelhouse**: the race container installs `harness/wheels/*.whl` (an older copy) without `--no-deps`: adk-submission 0.2.11 (wheelhouse 0.2.12), google-adk 1.39.1 (1.36.1), litellm 1.104.0 (Kaggle 1.82.4), Python 3.12.15 (3.12.3) | every task of every A6000 race | n/a | ours (race script) | `docker exec g4-probe pip list` | install the wheelhouse set with `--no-deps --force-reinstall` exactly as the kernel's install cell does | medium (effect on results unknown) |
| 13 | **ADK crash in the parallel fixers** ("No function call event found for function responses ids", TaskGroup) | 0 / 2 / 0 / 0 | 2 tasks | harness | v6p boltons_814a5a7, cattrs_2ac6c03 | nothing on our side; report upstream; count as infrastructure rows (addendum 5) | medium |
| 14 | **graph tools declared in every stage, never used** (get_code_neighbors, get_code_subgraph, search_similar_code: 1 call in 10,461); `edit_file` declared for locators that must not edit (v6p-think's locator used it 16 times, 9 errors) | all | 0-16 | ours (wiring) | - | drop unused tools from the stage yamls (shorter tool schema per call); never declare edit_file/write_file for a locator | high |

Zero helper tracebacks in 10,461 calls: no helper of any bundle crashed. The helpers' failures are refusals of inputs the model sends (1, 11) and absence (8).

## 1. Tool and helper errors

Full tables per arm (mechanism, owner, calls, tasks, example task, the exact call and the first 300 characters of the reply): [forensics_generated.md section 1](forensics_generated.md).
Totals: v4h2 2,290 calls (1,515 ok), v6p 3,185 (2,342 ok), v6p-think 1,617 (1,144 ok), v5h2-P4 3,188 (2,109 ok), v6p-b probe 181 (136 ok).

Distinct helper usage/argument errors (every one is ours), all arms:

| helper | call shape | calls | tasks | example | the prompt line that leads there |
|---|---|---|---|---|---|
| view.py | `FILE N-N` | 115 | 53 | `cd /tmp/wa && python3 /tmp/swe/view.py arrow/util.py 30-40` | the fixer prompts show `view.py path/to/file.py START END` two lines above `edit.py path/to/file.py --lines 120-135`; the model carries the dash form over |
| view.py | bare `FILE` (and `FILE` with no numbers) | 24 | 13 | `cd /tmp/wb && python3 /tmp/swe/view.py arrow/arrow.py` | same; `read_file(filepath)` with no range is legal in the same prompts, so a bare file name looks legal too |
| edit.py | `--help` | 1 | 1 | `python3 /tmp/swe/edit.py --help` | none (the usage line answers it) |

Helper tracebacks: none. "can't open file": v4h2 only (149 calls, 49 of 50 tasks; check.py 60, locate.py 53, test.py 23, edit.py 11, install.py 2), the mechanism GATE.md documents; v5h2's setup stage removed it (0 of 74).
Harness rejections: INVALID_ARGUMENTS (run_skill_script called with `{}`) 29 calls v4h2, 41 v5h2 (the fixer stage, 34 times its first call; 30 of those were retried successfully on the next call); SKILL_NOT_FOUND / SCRIPT_NOT_FOUND with quoted or bracketed names (`"swe-tools"`, `「swe-tools」`, `":"`) 6; FileReadError with the other arguments glued into the path 158 (stage 1a) + 76 (P4); `Invalid integer for end_line: '390<|"|>'` 1; raw tool-call syntax leaking into the model's text 9 / 2 / 0 / 3 messages. Command timeouts: 1 (P4 rich_3480, a 180 s `python3 -c`), 3 in stage 1a. Sandbox execution errors: 2 (v6p, ADK TaskGroup).
Verification failures (the agent's patch collides with the test patch, counted unsolved, addendum 5): v4h2 boltons_805c803, v6p-think arrow_1278a21.

## 2. Prompt vs reality

Every helper invocation written in the prompts and SKILL.md of v4h2, v5h2, v6p, v6p-think and v6p-b was extracted and run with placeholder arguments against the bundle's own scripts in a scratch git repo
(`scripts/a6000/forensics_prompts.py`, table in [forensics_prompts.md](forensics_prompts.md)): **all 43 literal invocations run and print what the prompt says** (view.py numbered lines, edit.py `OK`, test.py `exit=`, check.py `DIFF:`/`PROBLEMS:`, locate.py `workspace=... symbols=`, install.py `installed:`, select_best `select_best:`/`PICK`; 15 further mentions are bare names, not invocations).
No prompt names a tool its stage yaml does not declare. The mismatches are between what the prompts imply and what the harness or the helpers accept:

1. `view.py path/to/file.py START END` (two numbers) is shown next to `edit.py ... --lines 120-135` (a range): the model sends `view.py FILE 30-40` or a bare file name in 63 tasks; view.py answers with its usage line and exit 0 (finding 1).
2. v5h2 verifier step 2b "write /tmp/repro.py" names no mechanism; the verifier's tool list has `write_file`, which refuses any path outside the workspace: 29 refusals in 28 of 74 P4 tasks. v6p's locator says `cat > /tmp/repro.py <<'EOF'` and still gets 4 (v6p) and 8 (v6p-think) `write_file` refusals because `write_file` is declared (finding 4).
3. The locator prompts instruct `read_file(filepath, start_line, end_line)`, a three-argument call; 238 of 1,672 read_file calls (14%) arrive with the arguments glued into the path and fail (finding 5). v6p-b reads through view.py (one string) instead.
4. "Your first tool call is always run_skill_script(install.py)" in the fixer and verifier prompts of v5h2 and v6p, whose setup stage already installed: redundant (116 fixer install calls in P4) and the call that most often arrives with `{}` (finding 6).
5. "The ONLY correct call shape is run_command(command="python3 /tmp/swe/edit.py ...")" is read as text to type: 63 commands in 55 tasks begin with `run_command(`, `run_command:`, `run_command "` or are a tool name (`submit_patch`, `read_file{filepath:`) (finding 3).
6. `edit.py` has two forms in one paragraph (SEARCH/REPLACE block, `--lines A-B` with plain lines); 13 of the 95 SYNTAX-ERROR reverts are a `--lines` edit whose body carries `<<<<<<< SEARCH`/`=======` (7 tasks) (finding 11).
7. Tools declared but never used by any stage of any arm: get_code_neighbors, get_code_subgraph, search_similar_code (1 call in 10,461); `edit_file` declared for the locators of v4h2, v5h2, v6p (never used there) and used by v6p-think's locator 16 times (9 "old_string not found"); `write_file` declared for v6p's locator, never used, and for v6p-think's, used 8 times, all refused (finding 14).
8. Stale text that the model does not see but we maintain: v5h2's SKILL.md does not list `view.py` although v5h2 ships it and its fixer prompt relies on it; locate.py's docstring says `skill_name="swe_tools"` (the skill is `swe-tools`).
9. Claims that hold: "a range you already saw is refused" (ALREADY SHOWN: 56 refusals in 8 P4 tasks, 2 in v6p); "REPRO PASS/FAIL" when the helper is used (it was used 0 times by the locator, see 5 below; the fixers' copies produced 339 REPRO FAIL / 316 REPRO PASS lines); check.py preflight (122 DIFF reports); select_best's report and PICK line (33 reports).

## 3. Loops

[forensics_generated.md section 3](forensics_generated.md). 54 loops (>= 5 identical consecutive calls) in 47 tasks: v4h2 9 loops / 7 tasks, v6p 12 / 9, v6p-think 7 / 6, v5h2-P4 26 / 25. By what the tool returned:

| reply repeated | loops | reading |
|---|---|---|
| a CommandError (grep/git grep with no match, exit 1, empty details) | 22 | model: it repeats a failing search (rich_4076 x62, attrs_6e3786c x50); 4 of 22 had byte-identical replies |
| a normal, useful result | 23 | model: the same `grep -n` or `python3 -c` x46-49 with the useful answer each time (arrow_85964d0, rich_3063) |
| BudgetExceeded (identical) | 5 | harness + ours: after call 70 every call is refused and the verifier repeats `git diff` until the 150-turn cap (x58, x63) |
| a parser-corrupted read_file (identical FileReadError) | 1 | harness: boltons_efff866's locator sent the glued-argument call 50 times |
| our ALREADY SHOWN refusal | 1 | model, x6 then it stopped: the refusal works |
| empty output | 1 | ours to make informative: `grep -rn ... \| head` with no hit, x36 (fastapi_15800) |

No agent text between the repeated calls in any loop (the model emits the next call directly). Ours to fix: 3 of 54 (the empty reply, the usage line, the corrupted read_file bound by finding 5); harness: 6; model: 45. The locator cap (finding 2) bounds every locator loop at the share.

## 4. Empty patches: which stage ended the task

[forensics_generated.md section 4](forensics_generated.md).

| arm | empty patches | budget exhausted (stage where call 70 fell) | time cap hit | verifier never ran | selector: all candidates empty | only test-file edits (refused) | submitted empty after successful edits | harness crash |
|---|---|---|---|---|---|---|---|---|
| v4h2 | 7 / 50 | 4 (verifier 3, fixer 1) | 1 (fixer) | 0 | n/a | 1 | 1 | 0 |
| v6p | 19 / 50 | 16 (fixer_a/b/c 15, selector 1; the locator was the top spender in 14 of the 21 budget tasks) | 2 (locator) | 0 | 0 | 0 | 0 | 1 |
| v6p-think | 41 / 50 | 1 | 40 (locator 22, fixers 14, verifier 3, selector 1) | 0 | 0 | 0 | 0 | 0 |
| v5h2-P4 | 9 / 74 | 5 (fixer 3, verifier 2) | 1 (fixer) | 0 | n/a | 0 | 3 | 0 |

Reading: v6p's empty patches are the budget (16 of 19), spent mostly by the locator before any fixer finished; v6p-think's are the time cap (40 of 41), 22 of them before the locator ended; v5h2's and v4h2's split between the budget and a verifier that submits an empty diff after at least one `OK` edit (the edits were reverted by check.py's preflight or made in a scratch copy: rich_3782, rich_3938, rich_3942, attrs_1c962d1).

## 5. v6p pipeline check

[forensics_generated.md section 5](forensics_generated.md), per task over the 50 v6p tasks (v6p-think in brackets):

| step | held in |
|---|---|
| locator wrote /tmp/repro.py | 37 / 50 [27] |
| the reproduction FAILS on the unedited code (required by S3) | 32 / 50 [28] |
| fixer_a / b / c made their copy | 45 / 46 / 45 [22 / 23 / 22] |
| at least one non-empty candidate diff | 32 / 50 [9] |
| selector ran select_best.py | 28 / 50 [5] |
| a candidate was picked and applied | 28 / 50 [5] |
| verifier called submit_patch | 40 / 50 [3] |

First broken step: repro written 13, repro fails before the fix 12 (together **25 of 50**), no non-empty diff 5, a fixer copy 3, selector 1, verifier 1; nothing broken 15.
How the locator ran its reproduction: `python3 /tmp/repro.py` directly 44, never 6, through the helper `/tmp/swe/repro.py` **0** (the prompt asks for the helper). select_best's own verdict on the reproduction in the 28 tasks it ran: fails before the fix 11, **passes before the fix: ignored 16**, none 1 (and no report in 22 tasks: the budget was gone, 21, or the ADK crash, 1). Candidate diffs: 0 non-empty in 18 tasks, 2 in 14, 3 in 18; PICK a 23, b 1, c 4.
The most-broken step is the reproduction contract (finding 7): the model writes `try/except` with prints, so the script exits 0 before the fix and the ranking falls back to the test file. The v6p-b probe (4 tasks, no repro by design) ran the fixers, the selector and the verifier in 4 of 4, with 3 of 4 picked and applied.

## 6. The L4 losses

[forensics_generated.md section 6](forensics_generated.md). Seven public tasks v4h2g solved on Kaggle L4 that v5h2 did not in P4 (fastapi_9753, rich_3718, fastapi_14616, fastapi_11194, requests_6644, rich_3521, rich_3063). The bundles differ (locator prompt, temperature 0.2 vs 1.0, the setup stage), so the trajectories diverge at the first locate query in 6 of 7 (at call 1 in rich_3718: L4 `grep -rn "Panel"`, P4 `read_file rich/panel.py 110-123`) and the comparison is of outcomes, not of a shared prefix. What the P4 traces show in each loss: dropped-argument install calls in 6 of 7; parser-corrupted read_file in rich_3521 (10 of 27 calls) and fastapi_14616 (5); `write_file /tmp/repro.py` refused twice in requests_6644; view.py usage errors in fastapi_9753 (4) and rich_3521 (3); the budget exhausted by failing greps in fastapi_11194 (60 failed `git grep` calls, 0-char patch), fastapi_14616 and rich_3063. Six of the seven P4 runs still produced a patch (376-2,423 chars): wrong fixes, not missing ones. On the L4 side the same tasks were solved with locate.py unreachable in 5 of 7 (v4h2g's known helper state), i.e. by grep and read_file alone.
Stage 1a, the five tasks v4h2 solved and v6p did not: arrow_1278a21 (v6p: 4 refused test-file edits, then the budget; 0-char patch), arrow_3f9837e (3 refused test-file edits, 2 repro tracebacks; a 1,441-char patch that is wrong), attrs_7804a68 (the budget at call 70, then 67 refused calls until the 150-turn error), black_315a796 (the budget after 22 empty and 21 failing search replies; a 7,979-char patch), black_d7587ce (the budget; 287-char patch). Three of five are the budget (finding 2), two are edits aimed at test files (model, refused by design).

## 7. Environment and the full test suite

Versions in play against the Kaggle wheelhouse (`metric/gemma-4-developer-agent-wheelhouse`, `eval/kaggle/g4-l4-v4/pip_freeze.txt`):

| component | wheelhouse / Kaggle | A6000 venv (vLLM, kernel run cell, P4) | race container (stage 1a / 1b sandboxes) |
|---|---|---|---|
| Python | 3.12.3 (Kaggle image at the time) | 3.12.3 | **3.12.15** (python:3.12-slim) |
| vllm / transformers | 0.19.1 / 5.13.1 | 0.19.1 / 5.13.1 | n/a (the model is served from the venv) |
| google-adk | 1.36.1 | 1.36.1 | **1.39.1** (pulled from PyPI by `pip install harness/wheels/*.whl` without `--no-deps`) |
| adk-submission | 0.2.12 (Kaggle's freeze of 2026-09-29 had 0.2.11) | 0.2.12 | **0.2.11** (`harness/wheels` is the older copy) |
| adk-eval-core / swegemma | 0.1.0 / 0.2.7 | 0.1.0 / 0.2.7 | 0.1.0 / 0.2.7 |
| litellm | 1.82.4 (Kaggle) | 1.82.4 | **1.104.0** |
| pytest in the task sandboxes | 8.4.2 | 8.4.2 | 8.4.2 (from the pack's wheels) |

So the compiler that builds the agents and the LiteLLM client that talks to vLLM differ between P4 (venv, = Kaggle) and the stage 1a/1b races (container, newer google-adk and litellm, older adk-submission). Whether that changes tool-call parsing or ADK's parallel-agent behaviour is not measured; the ADK crash of finding 13 happened in the container (finding 12).
Everything `docs/a6000/DEVIATIONS.md` and GATE.md record as different from the Kaggle notebook: one GPU (tensor_parallel_size 1); a PyPI-built base environment (numba 0.61.2, pydantic 2.13.5, aiohttp 3.14.4, opentelemetry-sdk 1.41.1 differ); `PYTORCH_CUDA_ALLOC_CONF` unset; Windows PATH entries removed; python3.12-dev installed; gpu_memory_utilization 0.95 instead of 0.90 (addendum 4; fp8 KV impossible on Ampere, addendum 3); the per-arm stretched caps in the P2 races (400 / 487 / 418 s) and C = 2; the Docker-emulated subprocess sandbox of or_race.sh for stage 1a/1b (P4 uses the kernel's own run cell); the external-GPU-contention guard; and the sandbox package versions above (new finding).

Full test suite (`PYTHONDONTWRITEBYTECODE=1 venv/bin/python -m pytest -q tests -p no:cacheprovider`, 2026-10-07 13:55-14:09 UTC): **49 failed, 2,636 passed, 861 skipped in 13 min 50 s**; every failure with its first assertion line is in [forensics_pytest.md](forensics_pytest.md). None is in the a6000 scripts, the bundles that ran, or their tests. Groups:

| group | failures | first line | reading |
|---|---|---|---|
| tests/test_v10_integration.py, tests/test_v10_sandbox.py | 32 | `TypeError: the JSON object must be str, bytes or bytearray, not dict` | the wheelhouse's swegemma returns tool results as dicts where the v10-era tests `json.loads` a string: stale tests of the historical v10 bundles (not run on this box) |
| tests/test_bundles.py `test_bundle_compiles_with_official_compiler[v4_lora_test, v4h2_v11a, v4h2_v11a_probe, v4h2g_v11b, v4h2g_v11b_probe]` | 5 | `AdapterNotFoundError: Adapter 'v11a' not found in discovered adapters. Available adapters: none` | adapter weights are gitignored (`adapters/`), absent on this box |
| tests/test_v5h2_bundle.py, test_v6p_bundle.py, test_v6p_think_bundle.py (eval-kernel tests) | 4 | `FileNotFoundError: kernels/g4-l4-v5h2-p312/kernel-metadata.json` | `kernels/*/` is gitignored; the kernels were generated on the Mac |
| tests/test_heldout_miner.py | 2 | `FileNotFoundError: '/System/Volumes/Data'` | macOS-only path in the test |
| tests/test_adaption_train.py | 2 | `zstd CLI needed for this test`; `assert (1 != 0 and '10000' in ... Traceback` (the CLI crashes before its size check) | zstd not installed here; the second needs a look on the Mac |
| tests/test_make_eval_kernel.py | 1 | `eval/golden/arms/v4_lora_probe has no eval_config.yaml` | `eval/golden/arms/` is gitignored |
| tests/test_golden_fixtures.py | 1 | `AssertionError: fastapi_11194` | a golden-evidence bookkeeping gap for one task |
| tests/test_overnight_gate.py, tests/test_train_when_ready.py | 2 | `assert (0 != 0)` | the gate scripts return 0 where the tests expect a refusal (stale marker / stale report): needs a look, Mac-side tooling |

## 8. The top findings in plain words

Carson's suspicion is right in part: in call counts, our own helpers, prompts and wiring account for more of the failed tool calls than the model's judgement does, and the harness's tool-call parser adds a third share. The helpers themselves never crashed (zero tracebacks); they refuse inputs the model sends, and the prompts invite those inputs.

1. **view.py refuses the way the model most often calls it.** `view.py file.py 30-40` or a bare file name gets a usage line and nothing else: 139 calls in 63 tasks, in 33 of the 74 P4 tasks and 24 of 50 v6p tasks. Those tasks solve less often (P4: 11 of 33 against 18 of 41). Ours; a few lines in view.py plus one word in the prompts.
2. **The locator spends the 70-call budget, then everything downstream is refused.** 43 tasks hit the budget (9 v4h2, 21 v6p, 5 v6p-think, 13 v5h2), the locator the top spender in 28 of them; 25 empty patches follow directly. Ours by design; v6p-b's ledger addresses it, v5h2 and v4h2 still need it.
3. **Our prompt wording becomes the command.** "The ONLY correct call shape is run_command(command=...)" is typed literally into 63 commands in 55 tasks, and `submit_patch`/`read_file{` arrive as shell lines. Ours; reword.
4. **The reproduction design does not hold.** The verifier and locator are told to write /tmp/repro.py but their `write_file` tool cannot write outside the workspace (47 refusals, 28 of 74 P4 tasks); v6p's locator never uses the repro helper, runs the file directly in 44 of 50 tasks, and select_best finds the reproduction "passes before the fix" in 16 of its 28 reports; 25 of 50 v6p tasks break at this step. Ours.
5. **The vLLM gemma4 tool parser corrupts multi-argument calls.** read_file arrives with the other arguments glued into the path in 14% of its calls (238), run_skill_script arrives with no arguments in 37 of 74 P4 tasks (on the forced install call that a setup stage had already made), and raw call syntax leaks into the text 14 times. Harness, but we expose it: every multi-argument tool the prompt pushes is a chance for it; single-string helpers (v6p-b's locator) and dropping the redundant install call remove most of the exposure.

What is the model's: repeating a failing or a useful search 40-60 times (45 of 54 loops, bounded by the locator cap), edits aimed at test files, SEARCH blocks that do not match, and wrong fixes that look complete (six of the seven P4 losses carry a patch). The sandbox package drift (finding 12) is ours and unmeasured; fix it before the next race.
