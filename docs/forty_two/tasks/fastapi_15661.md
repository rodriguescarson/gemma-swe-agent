# fastapi_15661: "Automate release preparation" (a new `scripts/prepare_release.py`)

Sources:
- `docs/forty_two/ground_truth/fastapi_15661.json`: the ground truth, from `gt_fastapi.py`.
- `docs/forty_two/ground_truth/fastapi_tools/trace_timing/fastapi_15661.json`: the per-run timing, from `tr_fastapi.py`.

"Measured" means taken from those files. "Inferred" means a reading of them.

## Problem

- **Issue:** the PR template, essentially empty.
  - Title "Automate release preparation" and an AI disclaimer that points at an asyncer PR.
  - The description is blank, and no checklist item is ticked.
- **Gold:** one new file, `scripts/prepare_release.py`, +216 lines. A typer CLI with:
  - `BumpType`, `bump_version`, `update_version_file`, `get_release_notes_body` and `update_release_notes`.
  - `RELEASE_NOTES_HEADER` and an `app`.
  - Version and heading regexes, plus error messages ("must be greater", "already contain", ...).
- **FAIL_TO_PASS (16, measured):** every test in the new `tests/test_prepare_release.py`.
  - It imports the 7 names above from `scripts.prepare_release`, so at base the whole file is one collection error (pytest exit 2).
  - The tests pin exact version arithmetic, exact rewritten release-notes text, error substrings and CLI outputs (`CliRunner`, environment variables).
  - The `FAIL_BOTH` entry in the JSON is the module-level collection-error item of the base run. It is an artifact, not a test.

## Constraints

- **Budget:** 5 minutes. 40 calls (v12-b1024, v0-think) or 70 calls (older bundles). 180 s per command.
- **Hidden spec:** everything. The module path, the 7 public names, the CLI options and every output string exist only in the test.
- **Gold in a clean environment: yes (measured).**
  - Before: 1 collection error. After: 16 passed.
  - typer 0.24.2 is in the parity pins, needed by the gold import.
  - The Kaggle oracle resolves it too (12.6 s).
- **Test cost (indicative):**

  | Step | Time |
  |---|---|
  | install | 0.4 s |
  | the 16 F2P tests | 0.29 s |
  | full `tests/` | 6.3 s |

## What the six box runs did

| run (bundle) | secs / calls | model s (calls) | tools s | final patch | clean env |
|---|---|---|---|---|---|
| p4 (v5h2) | 82 / 21 | 74.9 (26) | 1.9 | a new `.github/workflows/release.yml` | collection error |
| p4_v7 (v7) | 82 / 17 | 72.4 (22) | 1.7 | an edit to `.github/workflows/publish.yml` | collection error |
| p4_v7c (v7c) | 171 / 68 | 160.6 (73) | 4.5 | a new `scripts/release.py` (wrong name) | collection error |
| p4_v7d (v7d) | 87 / 18 | 77.5 (23) | 1.5 | an edit to `.github/workflows/publish.yml` | collection error |
| p4_b1024 (v12-b1024) | 302 / 25 (time cap) | 292.7 (27) | 0.4 | empty: 16 reads, 9 searches | collection error |
| p4_v0t2 (v0-think) | 302 / 31 (time cap) | 224.1 (28) | 1.0 (+74.2 cut off at the cap) | empty: 18 reads and 11 code-graph calls | collection error |

- **v7c** repeated one `git grep -rn "release" . | grep "scripts/" ...` pipeline **48 times**.
- **b1024** had two compaction-like calls of 33.9 and 34.2 s. Its prompt peaked at 16,013 tokens.
- **v0t2**'s prompt reached 23,782 tokens, the largest in the batch, after 11 code-graph calls and a sub-agent call.
- **L4:** 0 of 12 L4 runs with 74 rows solved it. The two traces wrote a workflow and a `scripts/release_preparation.py`.

**Where the time went (measured, six runs, 1,027.6 s):**

| | Seconds |
|---|---|
| model | 902.2 |
| tools | 11.0 |
| tail cut off by the cap | 77.4 |
| other | 37.0 |

## Root cause, feasibility, lever

- **Root cause: FEATURE_TOO_LARGE** on an UNDERSPECIFIED_ISSUE, with a HIDDEN_SPEC API. A 216-line new module whose module path, names and outputs are defined only by the test.
  - This agrees with the old diagnosis.
- **Feasible in 5 minutes: no.**
- **Lever: none realistic.** Writing a guessed CLI module cannot match 7 imported names and the exact strings. Spend nothing on this task.
