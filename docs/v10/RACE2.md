# Race 2 arms and the pre-race integration record

Integrator, 2026-09-28. The race itself (pod, GPU spend) and any Kaggle push are Carson's call; nothing here starts one.
The pre-registered pass, kill and ship rules live in `docs/v10/race2_checklist.md` and are not changed by this file.

## 1. Arms

| arm | bundle | how it is built | in `pod/chain_race2.sh` |
|---|---|---|---|
| `r2_v9_eog` (control) | `submissions/v9_eog` (sub4 as shipped) | nothing to build; frozen, R84 tree sha256 `41db23fc...` | yes, runs 1 and 2 |
| `r2_v10` (treatment) | `submissions/v10` | nothing to build; the bundle is hand-written (SPEC 12.1) | yes, runs 1 and 2 |
| `r2_v10_t06` (optional, SPEC 10.1) | a copy of v10 with the locator, fixer and verifier at temperature 0.6 | `python scripts/make_variant.py submissions/v10 submissions/v10_t06 --work-temp 0.6` | no: add it only if the budget allows (Carson) |

The t06 recipe changes exactly three lines (`configs/gen_{locator,fixer,verifier}.yaml`, `temperature: 1.0` to `0.6`).
`tests/test_v10_integration.py::test_make_variant_v10_work_temp_arm` pins that, and the built copy compiles with the
official compiler (`OK model=gemma-4-31b-it-qat-w4a16-ct unpacked=0.32 MB`). Build it at race time: a `submissions/v10_t06`
directory is picked up by `tests/test_bundles.py` like every other bundle, so it must only exist when it is used.

`scripts/make_variant.py` was written for v4/v9 bundles. Before this integration, running it on v10 without flags
silently replaced v10's `install.py` with `helpers_v9/install.py` and added `_ws.py` (the v9 `$TMPDIR` fix), which would
have broken helper installation in the arm. It now detects a v10 bundle (`scripts/_swe_common.py`), never applies the v9
fix to it, refuses the v9 levers (`--edit`, `--output`, `--gate`, exit 2, nothing written) and only accepts
`--work-temp` for v10. Regression tests: `test_make_variant_v10_keeps_v10_helpers`, `test_make_variant_v10_refuses_v9_levers`.

## 2. What the bundle is (deterministic pack)

`scripts/pack_bundle.py submissions/v10 out.zip` gives the same bytes on repeated runs:
`98920550845c54a9990600fe401dba59275971c2274bf5c028723d03cf72c482`, 31 files, 108,834 bytes. Any later edit of the
bundle changes this hash; re-pack and re-record it before the race.

## 3. Pre-race gates run by the integrator (checklist section 1)

Filled in section 5 with the exact result lines.

1. CI tier: `.venv/bin/python -m pytest -q tests`.
2. Official compiler: `.venv/bin/python scripts/validate.py submissions/v10`.
3. Linux parity (R119): `V10_ONLY=1 bash scripts/linux_test.sh` (python:3.12-slim, `--cpus 2 --memory 4g`, `TMPDIR` unset,
   `TEST_TMPDIR=/tmp`).
4. Real-sandbox channel parity for every helper (new, `tests/test_v10_integration.py::test_channel_parity`, CI tier): in a
   real `SubprocessManager` sandbox prepared by the harness's own setup functions, each of 18 cases covering all 9
   helpers runs twice from a reset tree: (a) `run_skill_script(install.py)` through the real ADK wrapper, then
   `run_command("python3 /tmp/swe/<x>.py ...")` with the literal path and heredoc stdin; (b) `run_skill_script(<x>.py,
   args={...})` with nothing installed, so the helper has to bootstrap the install itself. Both channels must give the
   same output (clock readings masked, and the journal line of the explicit install) and the same workspace bytes.
5. Real snapshots (new, `tests/test_v10_integration.py::test_real_snapshot_helpers`, NIGHTLY tier): every helper on four
   real repositories, with an empty diff and with the gold patch applied on top of the hidden tests.
6. `bash -n` and `shellcheck` on `pod/chain_race2.sh`, `scripts/build_kpar.sh`, `scripts/linux_test.sh`; replay sanity
   (R116).

## 4. Snapshot substitution

The computed task named `rich_3894`, `fastapi_14077` and `rich_4077`. Only `rich_3894` exists locally:
`fastapi_14077.tgz` and `rich_4077.tgz` are among the 34 snapshots not fetched yet (SPEC section 8; fetching needs network
and Carson's go: `source /Users/carson/Projects/kaggriculture/.venv/bin/activate && python scripts/fetch_data.py
snapshots/<tid>.tgz`). Substitutes, chosen for coverage: `requests_6644` (a different repository with a `src/` layout,
the only non-rich snapshot here), `rich_4075` (the nearest rich task, a 2,689-line module) and `rich_3930` (the largest
gold patch: 26 files, +12,170 -544, 6 hidden-test claims). No fastapi snapshot and no fastapi venv exist locally, so fastapi
is untested offline.

## 5. Results (2026-09-28, Mac under load average 8-13 from other sessions)

| gate | command | result line |
|---|---|---|
| CI tier, whole suite | `.venv/bin/python -m pytest -q tests -p no:cacheprovider` | `1234 passed, 555 skipped, 6 xfailed in 347.24s (0:05:47)` (final run, after every fix below) |
| official compiler | `.venv/bin/python scripts/validate.py submissions/v10` | `OK model=gemma-4-31b-it-qat-w4a16-ct unpacked=0.32 MB` (5 LlmAgents, `submit_patch` on verifier and submitter only) |
| Linux parity, R119 | `V10_ONLY=1 bash scripts/linux_test.sh` | `599 passed, 762 skipped in 192.36s (0:03:12)` (exit 0, 312 s wall) |
| Linux, whole suite | `bash scripts/linux_test.sh` | `982 passed, 762 skipped, 51 deselected in 174.54s (0:02:54)` (exit 0, 524 s wall; see fix 5) |
| channel parity, 18 cases, 9 helpers | `pytest tests/test_v10_integration.py -k parity` | all pass (part of the CI line) |
| real snapshots, 4 tasks, 100 helper calls | `G4_NIGHTLY=1 pytest tests/test_v10_integration.py -k real_snapshot` | `4 passed`; max output 2,265 chars; max call 1,896 ms |
| nightly tier | `G4_NIGHTLY=1 pytest tests/test_v10_tasks.py tests/test_v10_flow.py tests/test_v10_integration.py` | `566 passed, 342 skipped, 45 xfailed in 357.63s (0:05:57)` (skips: snapshots not fetched; xfails: the declared known cases, e.g. the six known locate misses and the harness F1 loss) |
| shell | `bash -n` and `shellcheck` on the three `.sh` files | clean (after one SC2086 directive in `pod/chain_race2.sh`) |
| replay, R116 | `scripts/replay_l4.py --baseline` / `--design final` | `150.2 s/task (n=51)` / `154.0 s/task (n=51), 1.03 x v4 as-is` |
| pack | `scripts/pack_bundle.py submissions/v10` twice | same sha256 `98920550...c482` |

Skips in the CI line: 375 nightly-tier task tests, 170 task tests whose snapshot is not fetched, 4 real-snapshot tests
(nightly), 3 flow tests (nightly), and the REPLAY, RACE and one NIGHTLY runner test (no race-2 data yet).

Real snapshots, per helper over the four tasks (empty diff and gold; `SWE_FAKE_CLOCK=20`; the kpar venvs):

| helper | calls | median ms | max ms | max chars |
|---|---|---|---|---|
| install | 8 | 116 | 127 | 100 |
| locate | 12 | 233 | 443 | 1,476 |
| grep | 8 | 72 | 126 | 1,581 |
| view | 20 | 49 | 176 | 2,265 |
| edit | 4 | 41 | 44 | 53 |
| run | 4 | 68 | 185 | 24 |
| verify | 24 | 379 | 1,896 | 1,291 |
| finalize | 8 | 158 | 247 | 589 |
| status | 12 | 96 | 165 | 2,109 |

Verdicts: gold is `VERIFY: GREEN` on the three rich tasks and `AMBER` on requests_6644, where the kpar venv's
site-packages copy of requests shadows the workspace (the known F10 case; the helper says so). The hidden-test claims give
`REPRO: fails on original` then `k/k claims fixed` (1/1, 1/1, 6/6); requests_6644's hidden test passes on the original
for the same F10 reason. The empty diff gives `VERIFY: NO SOURCE CHANGE` (78 chars, under 0.12 s) and `NOT READY: EMPTY`.
The first locate on a cold index took 1,327 ms on rich_3894 in an earlier run (budget 3 s); cached calls are 120-155 ms.

## 6. Fixed during integration

1. `tests/test_v10_bundle.py` pinned `helpers_v9` at `ed996c63...`, a tree from before Carson's committed gate fix
   26dd7b9 (13:21; the SPEC was written at 13:12). Re-pinned to the committed tree `c40b410b...`, and the new
   `test_frozen_pins_match_git` checks the pin against that commit and that no frozen tree has uncommitted edits. SPEC R84
   records the change. v9_eog and v4 pins are unchanged and still match.
2. `submissions/v9_eog/skills/swe-tools/scripts/__pycache__/_ws.cpython-312.pyc` (created 13:28 by something that
   imported the shipped `_ws.py` in place) made the official compiler reject the control arm (`disallowed extension
   '.pyc'`). It is a git-ignored cache file, not bundle content; removed. The tracked tree is unchanged (R84 hash equal).
   Race 2's preflight would have aborted on it.
3. `scripts/make_variant.py` on a v10 bundle (section 1).
4. Linux gate: `scripts/build_kpar.sh` checked for uv before validating its arguments (regression case added to
   `test_build_kpar_script_contract`); `test_run_kills_the_whole_group` called `ps`, which python:3.12-slim lacks (now the
   /proc-aware `v10_support.repo.list_processes`); `v10_support.tasks._build_base` extracted snapshots as root with the
   archive's uid, and git refused the tree as "dubious ownership" (now `tar --no-same-owner`; the Linux gate's
   `test_base_ws_is_harness_exact` is its regression test, since the Mac never extracts as root).
5. `scripts/linux_test.sh` whole-suite mode piped pytest into `tail -5`, so it always exited 0: its first run here
   printed `152 failed, 777 passed, 789 skipped, 51 deselected, 2 errors` and still returned success. The failures were
   `ModuleNotFoundError: swegemma` (the mode never installed the harness wheels the v10 tests import) plus one edit.py
   p95 timing flake under host load (passed on rerun and in both other runs). The mode now installs the wheels and
   exits with pytest's status; `test_linux_test_script_full_mode_static` pins both.
