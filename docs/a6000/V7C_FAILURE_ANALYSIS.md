# v7c failure analysis and fix plan (A6000 box, 2026-10-08)

Source: stored ATIF-v1.7 traces, hidden-test logs and the gold patches of the v7c probe (4 items) and 31 finished items of the 50-id run
(35 items, 12 solved), read while the run was still going. The gold patches were used for diagnosis only. They must not go into prompts,
SKILL.md or training data. Numbers are A6000 screens, never Kaggle results. Everything below is read from the files under
`~/g4/runs/p2/items/v7c` and `~/g4/runs/p2/probe_v7c_T2/v7c` on the box. The scripts that produced it are in `docs/a6000/v7c_analysis/`
(ad-hoc, not unit-tested; run with `python3 -I <script> ...`).

## 1. Why the 4 probe items are 0/4

| item | cause | evidence |
|---|---|---|
| trio_34e7a2e | locator searched `tests/`, but trio's tests are in `src/trio/_core/_tests/`; the empty `git grep -ln "AsyncGenerator" tests/ \| head -n 20` was repeated 52 times (steps 10-61), 60 of 70 calls gone before the fixer started. The fix then replaced the `f_locals` marker with `agen in self.alive`, which is wrong. | hidden test `test_guest_mode_asyncgens*`: `('trio','asyncio',True)` where `('trio','trio',True)` is expected. The verifier ran `pytest tests/test_async_generators.py` (file does not exist), then submitted. |
| trio_ac7b93f | hidden test imports `trio._tools.sync_requirements`; the model wrote `sync_pre_commit.py`. Its own repro exited 1 twice (steps 31, 34) and it submitted anyway. `yaml.dump` rewrote all of `.pre-commit-config.yaml` (167-line diff). | collection error: `No module named 'trio._tools.sync_requirements'` |
| typer_42196d4 | fixer looped 30x on `git grep -n get_usage_pieces` (steps 34-63, ~67 s), then rewrote `.upper()` / bracket handling in 3 files; never ran the real suite (only test files that do not exist). | 123 failed, 478 passed |
| typer_8e75bc3 | the locator's final-answer call generated 4096 tokens in 172 s (of a 300 s budget) and produced a rambling root cause; it then patched `typer/_click/_termui_impl.py`, the gold patch is in `typer/main.py`. Visible `tests/test_launch.py` passed, the hidden test did not. | `assert <Mock wait()> == 0` |

## 2. Causes across the 35 items, ranked

1. **Cross-stage "ALREADY SHOWN" refusals (our helper).** `view.py` keeps one ledger of viewed ranges for the whole sandbox. The fixer is a fresh
   agent that only has the locator's text summary, so its first view of the same range gets `ALREADY SHOWN: ... edit now` and it asks again,
   up to 44 times. Example attrs_c2824ac: locator step 18 views `_make.py 660-680`; fixer steps 20-41 repeat the same view 22 times.
   10 of 35 items begin the fixer with a refused view: 1 solved, versus 11 of 25 for the rest. v7 shows the same: 7 of 50, 1 solved,
   versus 18 of 43. Items: arrow_1278a21, arrow_7bb5c60, arrow_97695bf, arrow_e521f27, attrs_c2824ac, attrs_dbb25ce (empty patch, 113 repeated calls).
   This is a correlation; the mechanism is visible in the traces. v7c's "outline on every 3rd identical re-read" does not remove it.
   Side effect to watch: with the read cap gone the locator now refuses itself (54 ALREADY SHOWN replies in the locator, 1 in v7).
2. **Unguarded identical `run_command` repeats.** 351 of 1300 tool calls (27%) are identical consecutive repeats, all `run_command`.
   Non-view examples: trio_34e7a2e 52x empty grep, arrow_06fe693 34x `python -c ... tzutc()`, typer_42196d4 30x grep, arrow_fe1afe2 44x (solved anyway).
   Loop items: 8 of 33, 1 solved.
3. **Tasks that cannot be solved from the repo.** "Add X locale" tasks need exact translations (arrow_384fb74 Maltese: model wrote `sigra`,
   test wants `siegħa`; arrow_85964d0 Lithuanian: `sekundę` vs `sekundės`; arrow_4d1aa4f and arrow_f1df58b also change `locales.py`, not read in detail).
   attrs_a819155 asserts on generated source text (`_setattr = _cached_setattr_get(self)`). Harness changes will not fix these. Treat as noise.
4. **Incomplete fix, no variant check.** attrs_fd7538f converts lists to tuples; the hidden test passes a set (`TypeError: unhashable type: 'set'`).
5. **Verifier does not verify.** trio_ac7b93f submits after its own failed repro; trio_34e7a2e and typer_42196d4 run pytest on guessed file names.
6. **Locator answer blow-up.** typer_8e75bc3: 4096 completion tokens, 172 s. Only one instance found in the 4 probe items; my detector found none in the 31 others (it checks `completion_tokens >= 4000`), so this is not yet shown to be common.

Classification of the 38 items seen at the time (script `classify_failures.py`): 14 right file but wrong fix, 11 solved, 7 budget burned by a loop,
2 budget exhausted without loop, 2 collect/import errors, 1 empty patch, 1 localization miss.

## 3. Plan (Mac side owns the bundle; nothing here was changed on the box)

Order is by expected gain per effort. Each step needs a test first (tests/test_v7*_helpers.py style) and a re-probe before the next A6000 run.

1. **Per-stage view ledger.** In `view.py` (installed helper), reset or namespace the "already shown" ledger at the locator-to-fixer handoff
   (a stage id env var or marker file written by the handoff), or always return real content for the first view in a new stage. Never answer a
   re-read with a bare refusal; after 2 repeats in the same stage return the content plus a one-line note.
   Test: locator views A, fixer views A, fixer gets content. Same stage, 3rd identical view gets content plus the note.
2. **Generic repeat guard for `run_command`.** After 3 identical consecutive calls with identical output, return the output plus
   "this exact command already returned this N times; change the command or edit". Do not count the repeats as new information. Test with an empty-output grep.
3. **Empty search hint.** When `git grep` over `tests/` is empty, say tests may live elsewhere and suggest `git grep -l <term>` across the repo
   (trio: `src/trio/**/_tests`). Optionally let `locate.py` list test files near the located symbols.
4. **Verifier rules.** Own repro that exits non-zero means not done; do not `submit_patch` until it passes or the reason is stated. Look up test files with
   `git ls-files | grep test` before running pytest on a path.
5. **Locator final answer.** Cap or disable thinking for the locator's summary turn; first confirm how common the 4096-token case is across the full 50 and the public 74
   (run `aggregate_failures.py`, it prints items with a cap-length completion).
6. **Fixer discipline (prompt).** Before editing a spec-like task, list the variants named in the issue (lists, sets, tuples ...) and test each; do not rewrite whole config files
   with a YAML dumper; use targeted edits.
7. **Evaluation hygiene.** Report solved counts with and without the locale and source-text-coupled tasks, so these do not mask changes. Keep gold patches out of every prompt.

Re-measure after steps 1 and 2 with `cross_stage_refusals.py` (target: first-fixer-view refusals 0 of N, wasted-repeat share well below 27%) before
spending a public-74 run.

## 4. Open questions

* Whether fixing item 1 raises the solve rate or only moves the failures to the wrong-fix class. The 10 affected items were mostly multi-file or large-range tasks.
* The public-74 traces were not analysed here (their layout differs: `runs/p4_v7c/results/traces`); the same scripts need a path change.
* The v7c P3 pass (training data) will contain these loops. Filter successes only, as planned, but check that solved trajectories with 40+ repeated calls (arrow_fe1afe2) are dropped or deduplicated.

## 5. Run state when this was written

Supervisor running v7c on the 50 stage-1a ids (started 16:41 UTC, 24 h hard stop 2026-10-09 16:26:49 UTC), then the public 74, then one P3 pass.
The A6000 results, counters and verdicts follow in `P2_LOG.md` and `GATE.md` as each step ends.

## 6. Tools and formats

The traces are ATIF-v1.7 (Harbor: https://harborframework.com/docs/trajectory-format, which also documents a validator). TraceProbe
(arXiv 2607.06184, found by search, not read in full) compares successful and failed SWE trajectories with a detector catalogue; worth reading for more detectors.

## 7. Mac side, 2026-10-08/09: step 1 built as v7d; step 2 cannot live in a bundle

Read with the branch at 87e0bb7 (pulled twice, nothing of the box's touched). Everything below is on the Mac copies of the
traces that the hourly backup had pushed (24 of the 50 stage-1a items plus the 4 probe items), so the counts are a
subset of section 2's; `cross_stage_refusals.py` and `aggregate_failures.py` now take `LABEL=GLOB` / a directory argument
and run on either side.

### Step 1 -> `submissions/v7d` (= v7c + view.py; tests first)

* `view.py`: an identical re-read of an unchanged range prints its lines again, under one line that starts
  `SHOWN AGAIN:` and names the cause and the next action; the line comes first, so it arrives before run_command's
  5,000-char cut. No helper prints `ALREADY SHOWN` any more. v7c's run of identical re-reads is unchanged: the 3rd, 6th,
  9th ... in a row still gets the outline (new content) instead of the lines; any other view.py call and an OK edit end
  the run. A re-read that printed no lines the first time (PAST END, EMPTY FILE) prints that one line again, without the
  note. `_ws.py` changes in its docstring only (the ledger code and shape are v7c's).
* Why not a per-stage ledger (the plan's first option): nothing in the sandbox tells a helper which stage is calling. The
  stages share one TMPDIR, no env var or marker changes at the handoff, and a stage-id flag in the prompt's command shape
  would be dropped by the model as often as any other argument. So the safe form is the plan's third option: the lines
  come back whoever asks, and the note is stage-neutral ("shown earlier in this task").
* Prompts: the two spans that promised a refusal (locator.md "a range already shown is refused", fixer.md "a range you
  already saw is refused, so edit instead of re-reading") now say what happens ("comes back marked SHOWN AGAIN") and
  keep the instruction; one line each, the backticked shell lines untouched. The locator.yaml arithmetic comment is
  restated. setup.md, verifier.md, SKILL.md, the yamls and the other helpers are byte-identical to v7c's.
* Tooling: `scripts/a6000/forensics_lib.py` classifies the new reply (ours by design; a loop of them is the model's);
  `scripts/a6000/v7_counters.py` gets `repeat_reads` (the SHOWN AGAIN replies) right after `repeat_outlines`, reported
  and never gated, so the box's POST steps keep working across the pull; the Kaggle helper check
  (`scripts/make_eval_kernel.py`, HELPER_BODY) accepts either marker on the repeat and labels which one it saw;
  `scripts/a6000/p8_plan.py --arm v7d` writes the same four steps for v7d, its 50-id table paired against v4h2, v7 AND v7c.
* Tests (all written before the change): tests/test_v7d_bundle.py (v7d differs from v7c in exactly view.py, _ws.py,
  locator.md, fixer.md, locator.yaml; compiled tree = v7c's; install; the Kaggle helper check on the real
  SubprocessManager: PASS, repeat "shown again"), tests/test_v7d_helpers.py (the stage-crossing case, the again/again/
  outline sequence, the note first and one line, PAST END/EMPTY repeats, no helper says ALREADY SHOWN, the ledger shape,
  v7c's outline tests and refusal audit re-run on v7d, every other v7c helper test re-run), tests/test_v7d_sandbox.py
  (the same through swegemma's SubprocessManager and the /tmp rewrite), tests/test_v7d_prompts.py (exactly one line
  changes in each of the two prompts, inside the parenthesis; the prose promise holds; v7b's and v7's prompt tests
  re-run), tests/test_v7d_counters.py (forensics + counters), tests/test_a6000_p8_plan.py (--arm).
* Baseline for the re-measure, Mac copies (`python3 -I docs/a6000/v7c_analysis/cross_stage_refusals.py "v7c=eval/a6000/results/p2/items/v7c/*/traces/trace_*.json"`):
  v7c 24 items, 5 solved; bare refusals 175 (locator 52, fixer 123); items whose FIRST fixer view was refused 7 -> 1
  solved, the other 17 -> 4; fixer re-reads identical to a locator call 55. v7 (50 items, 19 solved): 81 refusals
  (fixer 80), first-fixer-view refused 7 -> 1 solved, others 43 -> 18. v7d's targets: bare refusals 0 of N (by
  construction); the first-fixer-view items' solve rate against the rest (7 -> 1 vs 17 -> 4 is the number to move); the
  identical-repeat share (`aggregate_failures.py`: v7c 215 of 931 calls on the 24 items, 23%; section 2: 27%) and the
  loop items (6 of 24).

### Step 2: a run_command repeat guard has nowhere to live

Checked in the installed scorer stack (adk_eval_core 0.1.0, adk_submission 0.2.11, swegemma 0.2.7), not assumed:

* `adk_eval_core/sandbox/subprocess_sandbox.py`: `run_command` is `subprocess.Popen(command, shell=True, cwd=..., env=sanitized)`,
  i.e. `/bin/sh -c` with an env built from a fixed whitelist (PATH, LANG, LC_ALL, TERM, USER, LOGNAME, SYSTEMROOT,
  LD_LIBRARY_PATH, TMPDIR, TEST_TMPDIR) plus HOME = TMPDIR = the sandbox tmp and PYTHONNOUSERSITE=1. A non-interactive
  `sh -c` reads no startup file, BASH_ENV/ENV are not passed, and PATH is the scorer's own: no shell hook, no wrapper
  binary, no `git` alias (builtins cannot be aliased) and no `sitecustomize` (that would also run inside the hidden
  tests) can see or count a raw command.
* `adk_submission/registry.py`: before/after-tool callbacks exist in the YAML schema but resolve against a CLOSED
  `CallbackRegistry`, and `swegemma` registers none (`grep -rn callback .venv/lib/python3.12/site-packages/swegemma`
  finds no registration). A bundle cannot add one.
* So the only guard a bundle can carry is inside our helpers, and on the 28 local items the helpers other than view.py
  account for 1 of the 299 identical consecutive repeats (edit.py, once); the raw loops are `git grep` (84 wasted calls),
  `timeout 30 python3 -c ...` (44) and `python3 -c ...` (33). In 3 of the 4 raw loops of 5+ the repeated reply was
  NON-EMPTY and informative (arrow_06fe693 `tzutc()` x34, arrow_fe1afe2 the caught AttributeError x44, typer_42196d4 the
  grep hits x30); only trio_34e7a2e's grep (x53) was empty. A note appended to the reply would not have changed what
  the model saw in those three, and v7c's own experiment (the refusal, then the outline every 3rd time) shows a changed
  reply does not reliably end a run either.
* What remains of step 2, deferred until a helper-side loop shows up in a trace: a generic identical-call note in `_ws.py`
  for locate/test/check. Not built now: no observed mass, and it would be a second mechanism in the v7d cycle.
* The nearest buildable lever for the raw loops is step 3, routing the locator's test-file search through locate.py
  (whole-repo search for test files that name the symbol, an empty-result hint, a repeat note): that is the trio loop.
  It is a prompt change and its own cycle, after v7d's probe.

### Next

1. On the box, after the P8 run ends (hard stop 2026-10-09 16:26:49 UTC = 21:56 IST): PROMPTS P9 (v7d probe -> 50 ids
   paired vs v4h2/v7/v7c -> public 74), pre-registered as GATE addendum 13; the re-measure above after (a).
2. The Kaggle queue (v7c -> v5h2 -> v11b probe) is unchanged; v7d replaces v7c in it only on Carson's call after (a).
3. Step 3 (test-file search through locate.py) next, test-first, in its own bundle directory.

## 8. 2026-10-10: the scorer moved under us on 2026-10-09 (wheelhouse swegemma 0.2.11 + adk_submission 0.2.13)

Found when the three Saturday Kaggle kernels (v7c on g4-eval-v2-smoke, v5h2 on g4-eval74-v4, the v11b probe on g4-eval74-v2)
all died two minutes in, at 06:28, 07:27 and 07:34 IST, on `ModuleNotFoundError: No module named 'swegemma.models.discovery'`
(eval/overnight/progress.log, the kernel logs). No GPU time was spent. The wheelhouse dataset was republished at 2026-10-09
14:43 UTC: adk_submission 0.2.12 -> 0.2.13, swegemma 0.2.7 -> 0.2.11 (the only two wheels whose sha changed against the
2026-10-04 listing). Checked by unpacking both wheels, not from the forum.

**What broke, and the fix (commit after this one).** swegemma 0.2.11 deleted `swegemma/models/discovery.py`
(`validate_single_declared_model`) and `swegemma/models/registry.py` (`setup_gemma_model_registry`). Our kernel template
(scripts/make_eval_kernel.py), scripts/validate.py, scripts/a6000/run_eval.py and four bundle tests imported them; so does
the organisers' Getting Started notebook (last run 2026-10-01), which would fail the same way today. `scripts/swe_compat.py`
now gives `declared_model()` (the old helper, else `adk_submission.discovery.discover_declared_models` with the one-model
check) and `compile_only_model_registry()` (the old helper, else a ModelRegistry of LiteLlm clients for the declared name);
the kernel template inlines the same two fallbacks (tests/test_swe_compat.py keeps them in step). The Mac venv now carries
the new wheels (uv pip install of the two wheelhouse files); all nine local kernel dirs were regenerated and differ from the
previous notebooks only in the two template cells.

**What changed in the scorer, read from the new code.**
1. **Thinking is ON for every bundle that turned it off the old way.** The organisers' generation constraints
   (`swegemma.config.build_submission_limits`, unchanged since 0.2.7) merge a default `thinking_config: {thinking_budget: 4096}`
   into every bundle. adk_submission 0.2.12's resolver read `include_thoughts: false` as enable_thinking False and ignored the
   budget; 0.2.13's `apply_thinking_config_to_model` reads a positive budget as enable_thinking True BEFORE it looks at
   include_thoughts. Compiling v7d on the new stack: every stage gets `chat_template_kwargs.enable_thinking: True,
   thinking_token_budget: 4096`. The same release lowered the schema floor to `thinking_budget >= 0` ("0 disables thinking").
   So every one of our bundles (v4h2, v5h2, v7c, v7d, the adapter bundles; all `include_thoughts: false`) now thinks on the
   scorer, with up to 4,096 reasoning tokens per call, inside the same 5-minute cap. This holds for every submission scored
   since 2026-10-09 and for every competitor who relied on include_thoughts. **Fix: `thinking_budget: 0`** in the sampling
   yaml (`scripts/make_t0.py SRC DST` makes the copy, one line added; tests/test_make_t0.py shows the untouched source
   compiles to thinking on and the copy to off). `thinking_level: none` also turns it off but is not a google.genai
   ThinkingLevel value (a warning today). The old compiler (the A6000 box's venv) refuses a 0 budget (schema `>= 1`), so
   a -t0 bundle runs only on the new stack; its behaviour on the old stack is the twin's (thinking was already off there),
   so the box's screens of v7c/v7d stand for v7c-t0/v7d-t0. Bundles made: v7c-t0, v5h2-t0, v4h2g_v11b_probe-t0, v7d-t0.
2. **Undeclared or failing tool calls no longer kill the task** (`swegemma.harness.agent_runner.ToolErrorPlugin`: the error
   comes back as a tool response). Our "unknown tool -> patch discarded" class (R61, the "helpers are never tool names"
   sentences) is defused on the scorer; the sentences stay, they cost nothing.
3. **submit_patch strips test and runner-config files from the diff itself** (`strip_protected_files_from_patch` with the
   task's test files), so "Failed to apply test_patch" and our check.py revert are belt and braces now.
4. **Tool results are dicts, not JSON strings** (`parse_tool_response` in tools/execution.py and tools/workspace.py; JSON
   with ensure_ascii=False): the double-encoding of 09-27 finding 4 is gone; read_file coerces string line numbers.
5. vLLM server: `max_loras` default 8 -> 1, `max_lora_rank` inferred from the adapter (rounded up), `anthropic` wheel added.
   P3 trajectories captured on the box (old stack) differ from scorer-side tool-result shapes; a note for the SFT work.

**Today's plan, changed.** The Saturday queue re-runs as v7c-t0 -> v5h2-t0 -> v11b-probe-t0 on the same three slugs
(kernels g4-l4-v7c-t0-p312, g4-l4-v5h2-t0-p312, g4-l4-v11b-probe-t0-p312; recipes identical to the twins', only the bundle
payload differs). Without -t0 the runs would have measured thinking-on bundles and spent the week's GPU quota on an
unintended configuration. The next Kaggle submission must be a -t0 bundle for the same reason. The box's venv moves to the
new wheels only after its v7d run ends (its race containers pip-install harness/wheels on every task, so the repo's wheel
mirror cannot change while it runs); that is the P10 prompt. v7d-t0 is ready and has no kernel; whether it joins the queue
is Carson's call under the addendum 13 rule.
