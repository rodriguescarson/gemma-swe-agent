# v10.1 diagnosis 3: patch hygiene (race 2 round 1, KPI 7 and 8)

Scope: read-only diagnosis of the two hygiene failures in `eval/race2/eval/runs/r2_v10_1`. Nothing in
`submissions/` was changed. Traces are `eval/race2/eval/runs/r2_v10_1/traces/trace_<id>.json`; step numbers are ATIF
`step_id`s.

## Which tasks

`replay_l4.run_kpis` over `r2_v10_1`:

| KPI | tasks | patch |
|---|---|---|
| 7 protected-file patches (1) | `fastapi_14077` (resolved) | 4 files, including `pyproject.toml` (`starlette<0.48.0` to `<0.49.0`) |
| 8 scratch/vendored patches (1) | `fastapi_14258` (not resolved, session timeout) | only a new root `repro.py` (526 bytes), no source change |

For comparison, `r2_v9_eog_1` had 9 and 10. v10's hygiene works whenever a helper runs after the bad write. Across the
74 v10 traces, native `write_file`/`edit_file` hit a protected or scratch path in 7 tasks (10 calls). A later
helper cleaned 5 of them:

- `fastapi_11194` step 26, finalize: `CLEANED: removed reproduce_issue.py`
- `fastapi_14463` step 32, finalize: `CLEANED: removed reproduce_issue.py`
- `fastapi_14492` step 24, verify: `HYGIENE: reverted tests/test_tutorial/.../test_tutorial001_1.py`
- `fastapi_9555` step 31, finalize: `CLEANED: removed repro.py`
- `rich_3894` step 29, finalize: `CLEANED: removed repro.py, repro_bug.py`

The two leaks happened at the only two ends that no helper covers.

## fastapi_14077: protected file edited after finalize, then submitted

| step | stage | call | result |
|---|---|---|---|
| 17 | fixer | `edit.py pyproject.toml` | `REFUSED: packaging/test configuration file (pyproject.toml)` (edit.py's guard works) |
| 40 | verifier | native `edit_file pyproject.toml` (`<0.48.0` to `<0.49.0`) | ok. The native tool skips edit.py's refusal |
| 41 | verifier | `verify.py` | `HYGIENE: reverted pyproject.toml` |
| 42 | verifier | `finalize.py` | `READY: 3 files changed (+4 -5) ... FINAL: the patch was finalized at t=98s` |
| 43 | verifier | `status.py` | FINAL banner shown again |
| 44 | verifier | native `edit_file pyproject.toml`, same edit | ok |
| 45 | verifier | `submit_patch` | `patch_size 2828, files_changed 4` |

Why finalize did not stop it: finalize did its job. Its hygiene is a point-in-time pass (`finalize.py:91-95`), and the
tree was clean when it printed READY. The edit came one step **after** finalize, through a harness tool that runs no
bundle code. `submit_patch` (`swegemma/tools/execution.py:81-86`) then diffs whatever is on disk. Nothing between
step 42 and step 45 belongs to us, so no active check could have run there.

Why the model did it: the problem statement's title is literally "Upgrade Starlette supported version range to
>=0.40.0,<0.49.0". The HYGIENE line at step 41 says only "reverted pyproject.toml", with no reason, so the model read
the revert as a lost edit and put it back. The public gold patch does not touch `pyproject.toml`
(`data/tasks.jsonl`), and the test_patch touches only `tests/test_enforce_once_required_parameter.py`. That is why
this leak cost nothing here. The same shape zeroes a task when the protected file is one the hidden test_patch
touches: "Failed to apply test_patch" (harness_runtime 7.2 records exactly this for fastapi_14077 in r_v9_eo and r_v9_c).

## fastapi_14258: scratch file captured by the timeout fallback, finalize never ran

| step | elapsed | stage | call | result |
|---|---|---|---|---|
| 16 | 45 s | locator | `verify.py --repro-only` | `claim 1 HANG: no result after 10s` (the bug is a hang) |
| 24 | 72 s | fixer | native `write_file repro.py` (root) | ok, 386 bytes |
| 25 | 72 s | fixer | raw `python3 repro.py` (not `run.py`) | `TimeoutExceeded: Command timed out after 106 seconds`, returned at 180 s |
| 26-27 | 180 s | fixer | `read_file`, raw `grep` | ok |
| end | 176.5 s budget (2.94 min) | | | `Agent exceeded session timeout`; no `submit_patch` |

Why finalize did not remove it: finalize never ran. The fixer stage consumed the whole session, and the verifier and
submitter never started. No helper ran after step 24 either (steps 25-27 are raw commands), so neither clean_scratch
nor any hygiene hook had a chance. On timeout the harness takes the fallback diff `git add -N . && git diff --binary
_swegemma_baseline` (`swegemma/harness/agent_runner.py:760-776`). That diff includes every untracked file that
`.gitignore`, `.git/info/exclude` or `core.excludesFile` does not ignore, so `repro.py` shipped.

Secondary cause (time, not hygiene): the fixer wrote the repro with `write_file` and ran it with a bare `python3`,
even though the locator had reported a hang at step 16. The prompt says to run code only with `run.py` (20 s
default). That one call burned 107 s of a 176 s budget.

## Root cause shared by both

All v10 hygiene is **active**: it runs only inside a helper call (`edit.py`, `verify.py`, `finalize.py`,
`_swe_ckpt.restore`). The harness snapshots the patch at moments the bundle does not control:

- `submit_patch` after any tool call, including native `edit_file`/`write_file` or raw `sed`/`echo >` after finalize
  (14077);
- the fallback diff at session timeout, turn limit, tool-budget exhaustion or three idle nudges, possibly before
  finalize ever ran (14258).

Every stage declares `edit_file` and `write_file` (BASE8, R79). Removing them risks the unknown-tool crash, which
returns an empty patch. So the only way to make "the submitted diff never contains either" true is to make the
harness's own `git add -N . && git diff --binary _swegemma_baseline` blind to those paths from the first tool call
onward.

## Fix (to implement in the next bundle; v4 and v9_eog stay frozen)

Both mechanisms below were probed with the harness's exact commands on git 2.50.1 (macOS) and git 2.47.3
(`python:3.12-slim`, the Linux gate image), and on the real `rich_3894` snapshot: arming took 24 ms (527 tracked,
69 flagged). After a `shutil.copy2` overwrite of `pyproject.toml` (the way `write_file` writes), an appended and
then deleted `tests/test_a.py`, a new root `repro.py` and a new `tests/new/test_q.py`, the harness diff held only
the source edit. New files under tracked `templates/` and `src/_pytest/` still shipped, through the re-includes.
`git checkout <baseline> -- p` still restored a flagged file and kept its flag.

1. **`_swe_common.arm_submit_guard()`** (new; stdlib only; idempotent). Called by `install.py` (the setup stage's
   first tool call, before any agent write) and again at the top of `finalize.py`. The second call covers a failed
   install and a `git reset`/`read-tree` that dropped the flags.
   - Write `<gitdir>/swe_exclude`. It sits inside `.git`, so it never enters a patch. Contents, generated from one
     shared pattern table:
     - root scratch: `/[Rr]epro*`, `/[Ss]cratch*`, `/[Dd]ebug*`, `/[Tt]mp*`, `/[Tt]emp*`, `/[Tt]ry*`, `/[Dd]emo*`
       (`reproduce*` is covered);
     - scratch anywhere: `*.log`, `*.orig`, `*.rej`, `*.bak`, `*.swp`, `.coverage`;
     - vendored: `site-packages/`, `_pytest/`, `*.dist-info/`;
     - new protected files, mirroring `swegemma/harness/verification.py:60-83`: `conftest.py`, `pytest.ini`,
       `.pytest.ini`, `tox.ini`, `setup.cfg`, `pyproject.toml`, `sitecustomize.py`, `usercustomize.py`,
       `_swegemma_stubs.py`, `*.pth`, `test_*.py`, `*_test.py`, `**/[Tt]ests/**/*.py`, `**/[Tt]est/**/*.py`,
       `**/[Tt]esting/**/*.py`;
     - then `!/<name>` (or `!/<name>/`) for every baseline root entry that matches a root pattern (for example a
       tracked `templates/`), and for every tracked directory that matches a vendored pattern (for example pytest's
       own `src/_pytest/`). This keeps the rule "untracked and not already in the baseline", which is the rule
       `clean_scratch` uses.
   - `git config core.excludesFile <abs path>`. The harness keeps its own `.git/info/exclude`
     (`container_setup.py:498-503`), and both apply. `HOME` is the sandbox tmp, so no global excludes file is
     displaced.
   - `git ls-files -z`, filtered by `_protected_git`, piped to `git update-index -z --assume-unchanged --stdin`.
     With CE_VALID set, `git add` and `git diff <tag>` treat the worktree copy as unchanged. Modifications and
     deletions of tracked test and config files from **any** tool then never reach `submit_patch` or the fallback
     diff. Use the bundle rule here, not the harness rule, so a tracked nested `pkg/testing/util.py` that edit.py
     allows is not hidden.
2. **Keep the helpers' own view unchanged**, so HYGIENE and CLEANED still fire and local tests stay faithful:
   - Pass `-c core.excludesFile=/dev/null` to the untracked listings used for hygiene and cleanup:
     `_swe_common.changes()` (`_swe_common.py:1267`), `_swe_ckpt.reset_to_baseline` (`_swe_ckpt.py:207`),
     `_swe_ckpt.clean_scratch` (`_swe_ckpt.py:297`), and in the gate `_swe_gate._copy_ignored`
     (`_swe_gate.py:273`). Without that last one, the guard would start copying excluded scratch and new tests
     into the ORIGINAL base tree. `diff_bytes()`/`tmp_index()` must **not** get the override: they must keep equal
     to what `submit_patch` produces (R21).
   - In `changes()`, report hidden tracked protected edits. On the `_tmp_index_env` copy (it keeps the index mtime,
     so racy same-second edits are still compared by content), run `update-index -z --no-assume-unchanged --stdin`
     for the `h` entries of `git ls-files -v`, then `diff --name-status <baseline>`. The M/D rows go to `protected`,
     and `hygiene_revert()` reverts them as today. The probe confirmed this lists the hidden `pyproject.toml` and
     `tests/test_a.py` edits.
3. **finalize.py**: re-arm first. Before printing READY, check the harness-view diff with a shared
   `C.patch_violations(diff)`, the same rules as `replay_l4.is_protected` plus `scratch_files`. If a path survives,
   revert or remove it and recompute. Never print READY with a violation. This closes a smaller gap:
   `_swe_ckpt.ROOT_FILES` uses case-sensitive `fnmatchcase`, while KPI 8's `SCRATCH_ROOT` is `re.I`, so a root
   `Repro.txt` passes finalize today and fails the KPI.
4. **Messages** (soft, secondary): give the HYGIENE line in verify and edit a reason, the way edit.py's REFUSED line
   does, for example `HYGIENE: reverted pyproject.toml (packaging/test configuration file: graders own it; the
   patch never carries it)`. 14077's verifier re-edited at step 44 because "reverted" alone read like an accident.
5. **Race gate (`scripts/replay_l4.py`)**: for each KPI 7/8 patch, print the mechanism, meaning the step of the last
   READY finalize and any later write, or "no READY finalize + end state". The next diagnosis then needs no manual
   trace reading.

Residual classes that no gitignore pattern can express stay finalize-only, because only finalize can judge them:
untracked files over 1 MB, root files that shadow stdlib or installed modules, and vendored trees recognised by a
nested `setup.py`. None of these is counted by KPI 7/8.

## Regression tests (one per bug, plus base and edge cases)

- `tests/test_v10_finalize.py::test_guard_post_finalize_native_edit` (14077): arm; edit.py source fix; finalize READY;
  then write `pyproject.toml` and `tests/test_core.py` with `shutil.copy2` from a temp file (as
  `swegemma/tools/workspace.py:143-176` does) and `rm setup.cfg`. Compute the patch with the exact submit_patch
  commands. Only `pkg/core.py` may appear.
- `::test_guard_scratch_without_finalize` (14258): arm; write `repro.py` plus every sample of
  `test_finalize_hygiene_matrix`'s `scratch` and `vendored` lists, `Repro.txt`, `tests/new/test_q.py` and
  `pkg/sub/conftest.py`; no finalize; run the `agent_runner.py:760-776` fallback commands. The patch must be empty.
- `::test_guard_keeps_real_changes`: tracked `templates/`, `src/_pytest/`, root `debug.py` and `tmp_data/`. New files
  inside them, an edit to `debug.py`, a new `pkg/tmp_utils.py` and a unicode path all still ship.
- `::test_guard_helpers_view_unchanged`: after arming, `C.changes()` lists the hidden test edit as protected, verify
  prints HYGIENE and reverts it, the reverted file keeps its flag (a re-edit stays hidden), `clean_scratch()` still
  deletes `repro.py`, and `_copy_ignored` copies no guard-matched file.
- `::test_guard_idempotent_and_fast`: install twice plus finalize leaves one exclude file, one config value and an
  unchanged flag count; arming takes under 100 ms on a 3,000-file repo; after `git read-tree <baseline>` (flags lost),
  finalize re-arms.
- `tests/test_v10_flow.py`, two new scenarios in the real Evaluator with the mock LLM:
  (g) verifier `finalize.py`, then `edit_file tests/test_ops.py`, then `submit_patch`: the submitted patch has no
  `tests/` path and the hidden test resolves;
  (h) fixer `write_file repro.py`, then three text replies with no tool call. The nudge end takes the same fallback
  diff as a timeout, and the patch must not contain `repro.py`.
- Run under `V10_ONLY=1 scripts/linux_test.sh`: the fix depends on git semantics (git 2.47 there).

Race-3 target: KPI 7 and KPI 8 at 0 in every v10 run. The expected score effect is about 0: both leaked tasks were
decided by other things (14077 resolved anyway, 14258 had no source change). The value is removing the
"Failed to apply test_patch" zero on hidden tasks.
