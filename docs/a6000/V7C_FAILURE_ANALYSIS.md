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
