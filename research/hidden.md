# The hidden set: what it is, why we score 12% there, and what transfers

Written 2026-09-30 01:40 IST (2026-09-29 20:10 UTC). Read-only for everything the scorer or the bundle touches. No
submission, kernel push, pod or OpenRouter call. Network use: one public leaderboard download, one Kaggle notebook
listing, the Gemma 4 model card (HF) and one arXiv page. Repo files written: this report and
`research/hidden_probes/` (scripts, their outputs and the leaderboard CSV they read).

Evidence labels: **HOST** (organiser statement or competition page), **CODE** (installed harness or bundle source,
file:line), **MEASURED** (a script in `research/hidden_probes/` or an earlier research file, with its output),
**ESTIMATE** (arithmetic on measured inputs, assumptions stated), **INFERENCE** (a reading of indirect evidence),
**UNVERIFIED**. `SP` = `.venv/lib/python3.12/site-packages`. `HP` = `research/hidden_probes`.

---

## 0. Answers in one screen

1. **The public LB is 58 tasks, and 0.20 means 12 of them.** Today's LB (964 teams, `HP/lb_2026-09-29T19-48Z.csv`)
   shows only the scores {0.00, 0.01, 0.03, 0.05, 0.06, 0.08, 0.10, 0.12, 0.13, 0.15, 0.17}. That is exactly
   floor(100·k/58)/100; n = 57, 59 and 60 each predict a value that is absent (0.14 or 0.11). **MEASURED.**
   11/58 is 0.18, so the goal needs 12. The leader moved to **0.17 (10/58)** (Statistical Science by Lasme,
   2026-09-29 05:32 IST), with five teams at 0.15. None of the top 6 has a public notebook for this competition.
   We are rank 64 at 0.12.
2. **Repo types (INFERENCE, medium confidence).** The hidden repos are private and need a different dependency set
   (HOST). The harness was built for a corpus the public four repos do not explain:
   - Google-internal vocabulary: CL numbers (`SP/swegemma/deduplication.py:48-80`), "large-scale automated changes
     (LSCs)" (data page), `fake_gfile` in the mock detector (`SP/swegemma/difficulty.py:26`).
   - Google test conventions: `TEST_TMPDIR=/tmp` (absltest/Bazel), `python_classes="Test* *Test"`, `*_test.py`.
   - `protobuf-compiler` in the base image.
   - An `imp` shim "specifically for flasgger" (a Flask/Swagger app) and a `telnetlib` shim.
   - A ≥20 MB "large wheel" install path and a "1.7 GB /wheels" comment, against a 27 MB public wheelhouse whose
     largest wheel is 3.4 MB.
   None of these markers occurs in the public code (0 hits in 127 public graphs). Expect heavier numeric or ML
   dependencies, protobuf, colocated `*_test.py` unittest/absltest suites, and possibly 2-space indentation.
3. **Time per hidden task is 1.6-1.8× public, not 1.9×.** v4 used about 243-273 s in-clock per hidden task
   (gap_5), against 154.6 s on the faithful public L4 run. A uniform-slowdown fit puts **36-66% of hidden tasks at the
   5-min cap** (`HP/timek.out`). "Nearly all hit the cap" is too strong. sub4 (v9_eog) finished 9.99-10.07 h after
   submission, 0.3-0.5 h sooner than sub3, even though v9_eog is 15% slower than v4 on public L4.
4. **The gap: public 39% → hidden 12% (ratio 0.31) is normal for private repos.** SWE-Bench Pro reports the same
   frontier models at 42.7% → 9.1% (Claude Sonnet 4) and 41.8% → 15.7% (GPT-5 high) from public to commercial repos,
   a ratio of 0.21-0.38. busyaprime's 34/119 locally became 4/58 (0.24).
   - Our decomposition (§3, ESTIMATE): ×0.92 for run noise and selection on the dev set, and ×0.5-1.0 for the time cap.
   - That leaves a **residual ×0.34-0.65 from the tasks themselves**: harder specifications or changes, and
     unfamiliar code.
   - Field evidence says the cap is the smaller part. Bundles with a 60-min default cap (our v0, Rozen, Zhukov)
     score 0.08-0.12, the same as 5-min bundles.
5. **About 10-12 of the 58 are within reach of bundles like ours (ESTIMATE, three independent estimators agree, §3.5).**
   0.20 = 12/58 therefore needs close to the whole reachable pool in a single run, or new capability.
   - With v4's hidden rate, P(≥12/58) = 4%. It reaches 50% only at a true rate of 0.20, i.e. 11.6 expected tasks
     (+4.6 over v4).
   - Reliability work alone is marginal. It has to come with levers that open tasks we never solve: multi-file
     changes, fix completeness, short specifications.
6. **v10.1 helpers on unfamiliar layouts (MEASURED on Python 3.13, Docker-like env, §5).**
   - They work on src/, namespace packages, a `python/` root, colocated camelCase unittest files, 2-space
     indentation, and a 20k-file repo.
   - They have **three defects** the public set never exercised:
     - **E**: an import that takes ≥10 s turns into a false "RED - import error (HANG)", and the reproduction is
       mislabelled "hangs on original".
     - **F/I**: a new root module whose name starts with `temp`/`tmp`/`try`/`demo`/`debug`/`repro`/`scratch` (for
       example `templates_engine.py`) is deleted by finalize, and the submit guard keeps it out of `git add -N .`.
       The shipped patch then imports a missing module.
     - **K**: the import check is blind outside flat and `src/` packages that have `__init__.py`.
   - Two risks are unprobed: a full base worktree under `/tmp` (tmpfs, 4 GiB) on big repos, and CI parity pinned to
     Python 3.12 while the scorer runs 3.13.
7. **What transfers.** Transfer is ≈1 for repo-agnostic mechanics: no crashes, no lost patches, a valid edit channel,
   hygiene. Transfer is less than 1 for timing tuned to public pacing, and ≈0 for anything that guesses repo
   conventions. The host screened hidden tasks for "information given suffices" (743817), so hidden losses are
   capability losses, not unfair specifications.

---

## 1. What we know about the hidden set, by source

### 1.1 Host statements (HOST)
| Fact | Source |
|---|---|
| About 120 tasks, split evenly public/private; "curated from a set of private repositories" | Data page (`scratchpad/kaggle_pages.md:81`) |
| Same pipeline as the public set: commit/PR mining for commits that change `.py` logic and `test_*.py` / `*_test.py`; issue linking; LSCs, refactors and ambiguous issues excluded; fail-to-pass and pass-to-pass; "a larger frontier model must pass the case or get within a single test case of passing" | Data page, pipeline section |
| Test tasks had "much more extensive reviewing and editing". "Impossible" tasks removed. A failing test of the frontier model's patch was checked to be gettable "with the information given" | Ryan Holbrook, 743817 (2026-09-27) |
| "The private Docker sandbox uses the same base image but installs a different set of dependencies because the test issues come from a different set of repos" | 742882 [3529110] |
| Gold patches validate at 100% on the scorer | 742882 [3528750] |
| Graphs are generated identically; async defs are missing from graphs and embeddings, with no ETA | Data page; 742911 [3528743] |
| Tasks run sequentially; 12 h overrun still errors; no parallel calls | 743063, 743964 |
| Python only ("real-world Python bug fixes and feature requests") | Data page, 744020 |

### 1.2 Harness and image artefacts that point past the public four repos (CODE, INFERENCE)
| Artefact | Where | Why it matters |
|---|---|---|
| Base image installs `protobuf-compiler`, `pytest-timeout==2.1.0`, and ships `imp` + `telnetlib` shims for Python 3.13 | `data/raw/docker/Dockerfile.sandbox:3-11` | fastapi, rich, requests and httpx use none of them. The `imp` shim says "specifically for flasgger" (`imp.py:1`). **Some pipeline repo is a Flask/flasgger app and some uses telnetlib** |
| `ENV TEST_TMPDIR=/tmp` | `Dockerfile.sandbox:18`, `SP/swegemma/sandbox/docker.py:93` | TEST_TMPDIR is the absltest/Bazel convention |
| Verification forces `-o python_classes="Test* *Test"` | `SP/swegemma/harness/verification.py:498-503` | pytest's default is `Test*`. `*Test` is the Google class naming (`FooTest`) |
| Pipeline mines `test_*.py` / `*_test.py` | Data page | `*_test.py` colocated next to source is Google style |
| `get_task_cl`: "earliest CL (integer)" | `SP/swegemma/deduplication.py:48-80` | CL = changelist (Piper/Critique). The task schema allows a `cl` field |
| `MOCK_PATTERN` counts `fake_gfile` | `SP/swegemma/difficulty.py:25-28` | gfile is Google's file API. Splits named `public_test`, `private_test`, `broken`, `untracked` (`:101`) |
| Large-wheel path: wheels ≥20 MB are streamed per task only when workspace code imports them; comment "avoiding a 1.7 GB /wheels tar copy per task" | `SP/swegemma/harness/container_setup.py:137, 318-395, 406` | Public wheelhouse: 124 files, 27 MB, largest 3.4 MB (`du -sh data/raw/wheels`). The mechanism only matters for a private wheelhouse with big packages (numeric/ML stack likely; UNVERIFIED which) |
| "zero private wheels or internal code artifacts" in the public image | `Dockerfile.public:24` | Implies a private twin with private wheels, i.e. **internal dependencies installed in site-packages, not in `/workspace`** |
| README: pytest.ini "ignoring hardware/device/example directories", "configures synthetic hardware stubs", protected `_swegemma_stubs.py`; the public code does none of this | `data/HARNESS_README.md:279, 582, 591`; `container_setup.py:859-861` delegates to "the bundle's sandbox/setup.py" | The private `sandbox/setup.py` probably stubs hardware or device modules. **Some hidden repos likely touch devices/hardware** (INFERENCE, low-medium) |
| Container: 2 vCPU, 4 GiB, no network, Python 3.13, possibly gVisor with `/tmp` on tmpfs | `docker.py:84-93, 387`; gap_1 §1-2 | Heavy imports and test suites are slower than on our pod. A base-tree copy under `/tmp` may count against RAM |

Public cross-check (MEASURED): 0 of 127 public graph files mention `flasgger`, `telnetlib`, `imp.find_module`, `_pb2`,
`absl`, `gfile`, `protobuf` or `TEST_TMPDIR`. The same holds in 3 sampled public snapshots (rich, requests, httpx).

**Reading.** The harness authors built for Google-internal-style Python: CLs, LSCs, gfile, absltest, `*_test.py`,
protobuf. They also built for at least one Flask/flasgger app and one telnet or device-control codebase. The public
four are ordinary GitHub libraries. Whether every hidden repo looks like this is UNVERIFIED. The markers could be
pipeline heritage, but the Flask/telnet shims are repo-specific and do not serve the public four.

### 1.3 Leaderboard and score history
| Item | Value | Source |
|---|---|---|
| Public LB size | 58 (score set; §0.1) | `HP/lb_2026-09-29T19-48Z.csv` |
| Score distribution, 964 teams | 0.17 ×1, 0.15 ×5, 0.13 ×17, 0.12 ×88, 0.10 ×154, 0.08 ×183, 0.06 ×162, 0.05 ×122, 0.03 ×41, 0.01 ×59, 0.00 ×132 | same |
| Ours | v0 0.10 (6); v4 0.12 (7) twice (sub3, sub5); v9_eog 0.06 (4); sub6 = v10.1 armed for 2026-09-30 05:31 IST | `kaggle competitions submissions` (read 2026-09-30 01:18 IST) |
| Same-bundle repeatability | v4: 7 and 7. Rozen: 7 and 5 (a fork) | ledger; forum 743140 |
| Time-uncapped bundles | v0 (no eval_config: 60 min / 100 calls / 300 s defaults) 0.10; Rozen (no eval_config) 0.12 / 0.08; Zhukov (no eval_config) 0.10 | gap_5 §1.2, competitors.md §2 |
| Other public→LB transfers | busyaprime 34/119 local → 4/58; Shape of Doubt 5/16 local → 0.08; Black Cat lab 3/19 → 0.10 | competitors.md:161-162, notebooks_update_0928 §5 |

---

## 2. Characterisation of the hidden tasks

**Repo types.** See §1.2 (INFERENCE). Most likely:
- Google-style Python packages: absltest or unittest suites in colocated `*_test.py`, `FooTest` classes, often
  camelCase `testX` methods, protobuf messages, gfile-style I/O mocked in tests.
- Plus a Flask service (flasgger) and telnet or device code.
- Heavier third-party dependencies than the public set.
- Some repos may depend on internal packages that are installed as wheels, so their source sits in site-packages,
  not `/workspace`.

**Statement style (unknown; the most important unknown).**
- Public statements are "PR title, blank line, PR body" (129/129, pain_points §1). The hidden ones went through the
  same extraction from "problem description, issue tracker thread, or bug report", and then through host editing.
- For internal repos the source text is plausibly a CL description or a tracker bug. Those range from terse ("Fix X
  when Y") to bug reports with tracebacks.
- Why it matters (MEASURED on public, `HP/strata.out`, pooled over 12 faithful runs):

| stratum | n | v4 on L4 | pooled p |
|---|---|---|---|
| statement < 25 words | 25 | 3/25 | **0.09** |
| 25-59 words | 11 | 5/11 | 0.33 |
| 60-149 words | 17 | 12/17 | **0.65** |
| ≥ 150 words | 21 | 9/21 | 0.38 |
| traceback or code in statement | 14 | 7/14 | 0.54 |
| gold touches 1 file / 2 files / 3+ | 57 / 14 / 3 | 24 / 4 / 1 | 0.39 / 0.15 / 0.25 |
| gold churn ≤10 / 11-40 / >40 lines | 42 / 16 / 16 | 21 / 5 / 3 | 0.48 / 0.26 / **0.05** |
| host difficulty tier Easy / Medium / Hard+Extreme (`swegemma.difficulty`) | 32 / 38 / 4 | 17 / 11 / 1 | 0.49 / 0.24 / 0.05 |
| gold touches async code | 11 | 4/11 | 0.25 |
| merged before / after the Gemma 4 data cutoff (Jan 2025) | 22 / 52 | 10 / 19 | 0.31 / **0.35** |

- A hidden set of short statements, or of multi-file or >40-line changes, reproduces the 12% on its own.
- **No memorisation effect.** Tasks merged after the Gemma 4 pretraining cutoff (January 2025, HF model card) solve
  as often as older ones. So public scores are not inflated by the model having seen the fixes. What private repos
  remove is general familiarity with the codebase and its APIs, which the public data cannot measure.

**Difficulty.** Two opposing filters:
- (a) Frontier-feasibility plus human review removes impossible and underspecified tasks. That is 15 of our 39
  never-solved public tasks (pain_points §1), so the screen makes hidden tasks *fairer*.
- (b) "Within a single test case of passing" admits tasks the frontier model did **not** fully solve. Those are near
  impossible for a 31B model in 5 minutes. Their share is unknown.

**Test style (CODE plus INFERENCE).** Verification runs the whole of every test file in `test_patch`. It needs pytest
exit 0, JUnit `passed>0`, no failures or errors, and no skips on required nodes (`verification.py:483-542`).
- So pass-to-pass tests in the same file must pass.
- Colocated `*_test.py` files and unittest-style classes are collected.
- Required-test extraction only recognises `def test_...` (`verification.py:86-92`). camelCase `testX` methods
  (absltest) are therefore not "required" by name. The file-level exit code still is.
- `timeout_seconds` (v10: 180) caps that pytest run in the public harness (`verification.py:498-503`). Heavy-import
  suites on 2 vCPU make 180 s the right side of the trade (gap_5 §6).

**Environment.** The private sandbox installs its own wheels (HOST). Gold passes at 100% there, so impossible
environments were removed.
- Free passes can still exist. In public Docker, 4 of 59 local snapshots pass with an empty patch because an
  installed copy of the package shadows the workspace (gap_1 §3).
- The agent runs on Python 3.13 with no network. `pip install` fails fast (gap_1 §2).

**Time per task (MEASURED plus ESTIMATE).**

| quantity | value | source |
|---|---|---|
| sub3 (v4) submit→COMPLETE | 10.33-10.50 h | gap_5 §1.1 |
| sub4 (v9_eog) submit→COMPLETE | **9.99-10.07 h** (PENDING at 15:30:24 IST, COMPLETE at 15:35:25 IST on 09-28) | `scratchpad/gap5c/sub4_poll.log` |
| sub3 in-clock per task (validation excluded) | 243-273 s, central 258 s | gap_5 §2 |
| public v4, faithful 4×L4 kernel | 154.6 s mean; 9/74 capped; solved tasks 110 s, unsolved 183 s | `eval/kaggle/g4-l4-v4/results.jsonl`; `HP/union.out` |
| uniform-slowdown fit (v4) | k = 1.9-2.8; **36-66% capped**; 52-86% of public solves would still land by 300 s | `HP/timek.out` |
| overhead bound | a near-null run (Zhukov) finished about 120 tasks in about 80 min including validation, so ≤ about 35 s/task of setup + early exit | gap_5 §3 |

- **Corrections.** own_data.md §2.4 ("1.9×", "nearly every hidden task runs to the cap") divides 10.4 h *including
  validation* by 120. With validation removed, the ratio is 1.6-1.8× and a third to two thirds of tasks cap.
  "Every capped public run scored 0 (123/123)" (own_data §0.3) still stands.
- **The sub4 anomaly.** v9_eog is 15% slower than v4 on public L4 (177.1 vs 154.6 s). On hidden it finished
  0.3-0.5 h sooner, while scoring 3 tasks lower.
  - A smaller validation phase cannot explain it: all of validation is about 2 h, so saving 0.5 h needs about 30
    fewer patches.
  - That leaves either queue-time noise (sub3's queue is unknown) or **hidden-specific early exits** (crashes, or a
    helper path that fails fast).
  - Weak evidence: the score gap alone has p ≈ 0.22 under a common rate (hypergeometric, 18 successes in 174 runs).

---

## 3. Public vs hidden: decomposing 39% → 12%

### 3.1 Ledger (ESTIMATE; central values, ranges in brackets)
| step | rate | factor | basis |
|---|---|---|---|
| v4, faithful public L4, one run | 39.2% (29/74) | | `eval/kaggle/g4-l4-v4` |
| v4-family mean over 3 faithful runs (L4 29, Kaggle-rescored pod 27, pair-1 pod 24) | 36.0% | ×0.92 | winner's curse from choosing v4 on these 74, plus run noise (SD about 2.5 tasks) |
| after the time cap | 25% [19-36%] | ×0.70 [0.52-1.00] | uniform slowdown gives 0.52-0.86 (`HP/timek.out`). The mixture model and the field evidence give about 1.0 |
| **hidden, observed** | **12.1%** (7/58, twice) | **residual ×0.48 [0.34-0.65]** | |

### 3.2 Why the time cap is the smaller factor
- **Public.** Solves happen early (v4 L4: solved 110 s vs unsolved 183 s mean). All 123 capped runs across 14 configs
  scored 0 (own_data §0.3), so the cap mostly ends tasks that were already failing.
- **Field.** Bundles running on the 60-min / 100-call defaults (our v0 0.10; Rozen 0.12/0.08; Zhukov 0.10) do no
  better than 5-min bundles (ours 0.12 ×2; Black Cat 0.10). Twelve times the time did not buy tasks.
- **Consequence.** The hidden tasks that run long are mostly ones the agent cannot solve (gap_5's mixture reading:
  about 0.33 public-like, 0.67 to the cap). Raising the cap to 5.5 min (safe per gap_5) is worth 0 to +3, central
  about +1, and only under the uniform reading.

### 3.3 What the residual ×0.34-0.65 is made of (INFERENCE; ranked by plausibility)
1. **Harder or less specified tasks for a 31B agent.**
   - Public strata show 0.05-0.09 solve rates for short statements, >40-line changes and Hard tiers (§2).
   - "Within one test case" admissions add near-impossible tasks.
   - The host's review removed *unfair* tasks, not *hard* ones.
2. **Unfamiliar private code.**
   - SWE-Bench Pro shows public→commercial ratios of 0.21-0.38 for frontier agents without our time cap.
   - The mechanisms there are enterprise layouts, internal APIs and no pretraining exposure. Our pre/post-cutoff
     check rules out fix memorisation on public, not API familiarity.
3. **Heavier environment per step.** Large wheels and likely ML/protobuf imports make each repro and test run slower
   on 2 vCPU. This feeds the time factor and the helper false alarms in §5 (probe E).
4. **Our tooling on unusual layouts.**
   - Measured defects exist (§5), but each is narrow. The layouts we probed mostly work.
   - The v9_eog −3 with an early finish (§2) is the only hidden-side hint, and it is weak.
5. **Environment differences.** On the public side our L4 numbers include about 1-2 environment free passes
   (fastapi_14851 passes at base in the Kaggle env, task_catalog). That is worth about ×0.95-0.98. On the hidden
   side the host's gold = 100% removes broken environments.

### 3.4 Sanity check against outside data
| system | public | private / hidden | ratio |
|---|---|---|---|
| Ours, v4 | 39.2% (L4) | 12.1% | 0.31 |
| busyaprime | 28.6% (34/119 local) | 6.9% (4/58) | 0.24 |
| SWE-Bench Pro, Claude Sonnet 4 | 42.7% | 9.1% (commercial) | 0.21 |
| SWE-Bench Pro, GPT-5 (high) | 41.8% | 15.7% (commercial) | 0.38 |

SWE-Bench Pro figures are from arxiv.org/html/2509.16941, read through a page summariser. The public and commercial
tables may come from different scaffold runs, so treat them as indicative.

### 3.5 The reachable pool (ESTIMATE): about 10-12 of 58
| estimator | result |
|---|---|
| LB ceiling: best of 964 teams | 10/58; 6 teams at 9 or more |
| Union of our runs. On public, the union of k random faithful runs is 1.46× a single run at k = 4 and 1.73× at k = 12 (`HP/union.out`). Applied to hidden 7 | 10.2-12.1 |
| Reachable-fraction model. On public, v4 solved 29 of the 43 tasks any of 12 runs ever solved (67%). Hidden 7 / 0.67 | 10.4 |

- Binomial check: P(≥12/58) is 0.04 at v4's rate, 0.50 at a true rate of 0.20 and 0.82 at 0.25.
- **So 0.20 needs more than making v4 reliable.** It needs a single run that harvests about the whole union, e.g.
  sequential retry with execution-based selection inside the cap (gap_2), *and* a lever that opens tasks outside the
  union.
- On public, the unopened tasks are the "right file, wrong or partial fix" bucket (19 of 30 v9_eog losses), multi-file
  changes and >40-line changes.
- This rests on the hidden set having the same success heterogeneity as the public one (a per-task p that is
  bimodal: 31 tasks at 0, 20 at ≥0.8; `HP/strata.out`). That is plausible, but it is an assumption.

---

## 4. What transfers, ranked
| lever class | expected transfer to hidden | why |
|---|---|---|
| Crash and patch-loss avoidance: unknown-tool crash, context overflow discarding the patch, empty patches, malformed `edit_file` | **≈1** | Repo-agnostic. It protects the 10-12 reachable tasks. v10.1 on the pod: 0 crashes, empty patches 2 vs 12 (PLAN changelog 09-30) |
| Patch hygiene (test/config/scratch files out of the patch) | ≈1, **except** the prefix rule in §5 F/I | Grader rules are identical |
| Variance reduction on reachable tasks (temperature, sequential retry with selection) | high | The pool is small, so reliability converts directly. Every public bundle at 0.12 or above runs T 0.2; ours runs T 1.0 (notebooks_update §5.2.6). Never isolated: an open measurement |
| Localisation (`locate.py` BM25 over identifiers) | 0.5-1 | Depends on hidden statements naming code. Query cleaning is tuned to GitHub PR templates (`locate.py:28-31`) |
| Clock schedule (locator done by 75-90 s, first edit by 150 s, stop editing by 210 s) | < 1 | Tuned on public pacing (solve mean 110 s). On hidden, each step costs more (slow imports and tests), so the same deadlines buy about half the exploration |
| More time (cap 5 → 5.5 min) | 0 to +3 tasks (central +1) | §3.2 |
| Levers that guess names or conventions only the test reveals | ≈0 | The host screened these out of hidden (743817) |
| Graph tools | ≈0 | Same generation; async missing; public recall R@1 0.04 (ledger 09-26) |
| LoRA SFT on our own trajectories (v11) | unknown; format and efficiency only | PLAN §1: P(ship) 0.04-0.10 |

---

## 5. v10.1 helpers and prompts on unfamiliar repos

### 5.1 Probes run for this report (MEASURED)
- **Setup.** v10.1 helpers were copied out of the bundle and run on **Python 3.13.11** with pytest 9.1.1.
- **Environment, Docker-like:** `TEST_TMPDIR` set; `TMPDIR` and `PYTHONPATH` unset; the package reachable only through
  a `workspace_paths.pth` written the way the public `sandbox/setup.py` fast path does (workspace plus every top-level
  dir, `data/sandbox_setup.py:307-316`); the scorer's `pytest.ini` (`--import-mode=importlib -p no:anyio`).
- **Flow.** Each probe runs the locator's `verify.py --repro-only`, then a correct fix plus a deliberate regression,
  then `verify.py`.
- **Scripts:** `HP/probe_layouts.py`, `HP/probe_more.py`, `HP/probe_imp.py`. **Outputs:** `HP/probe*.out`.

| probe | layout | result |
|---|---|---|
| A | flat `pkg/` (control) | repro fails on original; fix FIXED; regression caught (RED - regressions) |
| B | `src/pkg/` | same as A: correct |
| C | namespace package `nspkg/` (no `__init__.py`) | regression caught; `IMPORT: ok (no changed module inside a package)`, so the import check did not run |
| D | `python/pkg/` with colocated `geo_test.py` | regression caught through `python/pkg/geo_test.py`; import check skipped as in C |
| **E** | package whose import takes 12 s (a TF/JAX-class dependency) | Repro-only reports **"claim 1 hangs on original (expected for hang bugs)"**, which is false. `verify` reports **"VERIFY: RED - import error … HANG (the import did not finish in 10s)"** and tells the model to fix a non-existent error. Each call burns 10 s. finalize still says READY, so the patch survives |
| **F** | flat root-module repo; the fix adds `templates_engine.py`, imported by `app.py` | finalize: **"CLEANED: removed templates_engine.py"**. The harness diff has only `app.py`, which now imports a missing module, so a correct fix fails |
| **I** | same, without finalize: new root `template.py` | the submit guard (`core.excludesFile`) alone keeps it out of `git add -N .`, so the harness diff has only `app.py` |
| G | `pkg/geo_test.py` with `class GeoTest(unittest.TestCase)` and camelCase `testKeep` | discovered and run; regression caught as `pkg/geo_test.py::GeoTest::testKeep` |
| H | 2-space indented file; REPLACE body written with 4-space nesting | applied; the file parses; indentation is mixed (style drift only) |
| J | 20,203 `.py` files | locate first call 8.7 s (480k symbols); verify 4.5 s; grep 0.6 s, on an M-series Mac. On 2 vCPU x86, possibly gVisor, expect 2-4× (ESTIMATE), which is past `LOCATE_PARSE = 15` s and gives a partial index |
| **K** | a changed module that raises NameError at import | flat: RED import error (correct). Namespace and `python/`: **import check skipped**. The error surfaced only because the repro imported that module. A change the repro does not import would pass unnoticed |

### 5.2 Code-level risks (CODE; each needs a test in §6)
1. **Fixed small timeouts assume light imports.**
   - `IMPORT_CHECK = 10`, `CLAIM_TIMEOUT = 10`, `RUN_DEFAULT = 20`, `PYTEST_SIDE = 40`, `VERIFY_TOTAL = 60`
     (`_swe_common.py:28-29`).
   - An import hang is declared without comparing against the original (`_swe_gate.py:800-807`: `rc is None` →
     `hang=True` before any base comparison).
   - `run.py`'s 20 s default prints "TIMEOUT … this may be the bug" (`run.py`), which misleads on slow-import repos.
2. **Scratch-prefix rules have no word boundary.**
   - `_SCRATCH_ROOT = ^(repro|reproduce|scratch|debug|tmp|temp|try|demo)` (`_swe_common.py:1170`).
   - `ROOT_FILES` / `ROOT_DIRS` patterns (`_swe_ckpt.py:18-19`) and `GUARD_ROOT_PREFIXES` (`_swe_common.py:1515`).
   - They hit `template*`, `temperature*`, `tmpl*`, `demographics*`, `debugger*`, `trying*`, `reproducible*`, and a
     new root `templates/` directory. A Flask repo (the flasgger hint) adding root templates is exposed.
3. **Package detection covers only flat and `src/` with `__init__.py`.**
   - Code: `repo_tops` and `module_name` (`_swe_gate.py:168-213`), `locate.layout` (`locate.py:127-137`).
   - Namespace packages, `lib/` / `python/` / `packages/*/src` roots and Bazel-style trees get no import check, no
     origin probe and no LAYOUT line.
   - `NOT_PACKAGES` also drops a real package named `scripts` or `tools` (`locate.py:25-26`).
4. **The index skips `build`, `dist`, `vendor` and `_vendor` at any depth** (`_swe_index.py:38, 121-126`). Source
   under `mytool/build/` is invisible to locate and view. The harness also git-excludes `build/`, so a new file there
   never enters the patch (`HARNESS_README.md:264-268`).
5. **The base tree is a full worktree under `$TEST_TMPDIR/swe/base`** (`_swe_gate.py:250-270`).
   - On gVisor with `/tmp` on tmpfs, that copy counts against the 4 GiB container (gap_1 §1, UNVERIFIED).
   - A large repo plus two parallel pytest sides importing a heavy library (`MAX_PAR = 2`) is an OOM path.
   - Any non-timeout harness exception discards the patch (competitors §5.2).
6. **Python version.** The scorer runs 3.13. The v10 Linux parity job runs `python:3.12-slim`
   (`scripts/linux_test.sh:40`, SPEC R119). The probes above are the only 3.13 runs of v10.1 helpers I know of.
7. **Hard-coded 300 s.**
   - `CAP_S = 300` and the stage deadlines (`_swe_common.py:21-22`), plus "the task stops at t=300s" in every prompt.
   - Changing `max_time_minutes` (gap_5 recommends 5.5) without changing these leaves time unused, or makes the TIME
     and FINAL lines fire early.
8. **Locator query cleaning is GitHub-specific** (`locate.py:28-36`: stopwords, PR checklist, `#123`). Internal tracker
   boilerplate (`BUG=b/…`, `TESTED=`, `PiperOrigin-RevId:`, `Change-Id:`, `Reviewed-by:`) is not stripped.
9. **Protected-path parity.**
   - v10 protects `testing/` only at the root and `tests`/`test` at any depth, in exact case (`_swe_common.py:1421-1436`).
   - The grader resets `.py` under `tests`/`test`/`testing` at any depth, any case (`verification.py:60-83`).
   - v10.1 documents the tracked-file consequence (`_swe_common.py:1712-1717`). Google-style `pkg/testing/` fakes are
     common, so this path will be hit on hidden.
10. **Prompt rules that could misfire on unfamiliar repos.**
    - "Never edit … pyproject.toml, setup.cfg, tox.ini": fine, because the grader resets them.
    - The locator's examples are rich-flavoured: harmless.
    - "about 8 tool calls; reply by t=90s": tight when each repro costs 10-20 s of imports.
    - "A name the repository does not define comes from a dependency: `view.py --obj`": good for private dependencies
      that live in site-packages. Keep it.

---

## 6. Robustness tests to add (ranked; none written to the repo's `tests/`, because a golden-eval build is running)

Each row is one parametrised test on a toy repo. `HP/probe_*.py` builds these repos in the Docker-like env.

| # | test | setup | pass condition | status today |
|---|---|---|---|---|
| T1 | slow import is not a hang | `pkg/__init__.py` sleeps 12 s (and 30 s); repro, fix, verify | no "RED - import error", no "hangs on original". The timeout is calibrated from the baseline import time (for example `max(10, 2.5 × t_import(original))`), and a slow current import is compared with the original before calling it a hang | **FAILS** (probe E) |
| T2 | root module with a scratch-like prefix ships | flat repo; new root `template.py`, `templates_engine.py`, `tmpl.py`, `debugger.py`, `demo_data.py`, each imported by a changed tracked file; plus a new root `templates/` dir with a `.html` the code loads | the file is in `git add -N . && git diff _swegemma_baseline` after install (guard armed) and after finalize. `repro.py`, `tmp_check.py`, `scratch.py`, `debug_out.log` are still removed | **FAILS** (probes F, I) |
| T3 | import check covers namespace and non-src roots | `nspkg/` (no `__init__`), `python/pkg/`, `lib/pkg/`, `packages/a/src/a/`; changed module raises at import; the repro does *not* import it | verify is RED at import, or at least AMBER naming the unchecked module, never GREEN | **FAILS** for namespace and `python/` (probe K; import check skipped) |
| T4 | Python 3.13 parity | run all `tests/test_v10_*` in `python:3.13-slim` with `--cpus 2 --memory 4g`, `TEST_TMPDIR=/tmp`, `TMPDIR` unset | green | not run in CI (`linux_test.sh:40` uses 3.12). The probes here pass on 3.13.11 macOS |
| T5 | large repo under 2 vCPU | 20k-50k `.py` files, 1 GB of tracked non-Python data | locate first call ≤ 15 s; verify ≤ 20 s; the base tree does not copy non-`.py` bulk (sparse or tracked-`.py`-only), or is skipped above a size limit | 8.7 s / 4.5 s on Mac at 20k (probe J); CPU-limited and tmpfs cases not run |
| T6 | `/tmp` on tmpfs under 4 GiB | Docker `--memory 4g --tmpfs /tmp:size=…`, 1.5 GB repo, heavy-import tests on both sides | no OOM; verify degrades to UNKNOWN, not a crash | not run |
| T7 | colocated Google-style suites | `pkg/foo_test.py` with `FooTest(unittest.TestCase)`, camelCase methods, `absltest.main()` guard and `parameterized` (if absl is installable offline) | discovered; per-test outcomes; regressions named | camelCase unittest **passes** (probe G); absl not tested |
| T8 | code reading absl flags | a function reads `flags.FLAGS.x` at call time | repro classified BROKEN with a hint to parse flags, not STILL FAILS | not run |
| T9 | 2-space and tab indentation | 2-space file; tab-indented file; REPLACE in the other style | edit applies and compiles, or is undone with a clear message; optional warning on mixed widths | 2-space **passes** (probe H); tabs not run |
| T10 | internal-tracker statement | statement with `BUG=b/123`, `TESTED=unit`, `PiperOrigin-RevId: 1`, `Change-Id: I…`, `Reviewed-by:` plus one real identifier | locate ranks the identifier's file first; boilerplate tokens are dropped from the query | not run |
| T11 | source under skipped dir names | `tool/build/compiler.py`, `lib/vendor/x.py` holding the bug | locate and view find them; a new file there ships (note: the harness `build/` exclude makes that impossible, so the test should assert a warning) | not run (code shows skip) |
| T12 | nested `testing/` fakes | tracked `pkg/testing/fakes.py` needs a change | edit allowed; patch ships the edit; a *new* file there is refused (grader's `git clean`) | covered by `test_protection_one_rule_nested_testing` (test_v10_1.py:671) |
| T13 | cap parity | parse `eval_config.yaml` `max_time_minutes` | equals `CAP_S/60` and the "t=300s" prompt text | not run (all say 5 min today) |
| T14 | slow test file | chosen test file takes 60 s on 2 vCPU | verify reports tests UNKNOWN (AMBER), never RED; total verify ≤ `VERIFY_TOTAL` + 5 s | partly covered (`test_v10_verify.py` SLOW_TESTS, 22 s sleeps) |
| T15 | private dependency in site-packages | the repo imports `corp_lib`, installed only in site-packages | `view.py --obj corp_lib.X` shows its source; the repro's import resolves to site-packages; no "outside the workspace" AMBER when the changed module is in the workspace | partly covered (`test_import_origin_outside_workspace_is_amber`) |

Suggested fixes for the three failing rows. These are **not applied**: the v10.1 bundle is frozen and sub6 is armed.
- T1: measure `t_import` once per task on the base tree, then scale `IMPORT_CHECK`, `CLAIM_TIMEOUT` and the `run.py`
  default from it. Classify a current-side import hang as RED only when the original imports within the same budget.
- T2: require a separator after the prefix (`^(repro|scratch|debug|tmp|temp|try|demo)([_.-]|\d|$)`), and let
  `root_module_kept`'s "a changed tracked file imports it" test override the prefix. Mirror this in
  `GUARD_ROOT_PREFIXES` and `ROOT_DIRS`, and keep a new root dir when tracked code references it.
- T3: fall back to `importlib.util.find_spec` on dotted names derived from each `.pth` and `sys.path` root that
  contains the changed file (the fast-path `.pth` lists them). When no module name can be derived, say "import not
  checked" in the IMPORT line instead of "ok".

---

## 7. Recommendations
1. **Treat 0.20 as a capability target, not a reliability target (§3.5).**
   - Aim the next levers at tasks outside our public union: multi-file fixes, fix completeness, short specifications.
   - Pair them with in-cap sequential retry with execution-based selection to harvest the union.
   - Measure on the public tasks that no run ever solved (31 of 74) *and* on repos the model has not seen:
     SWE-Pallets-X / SWE-rebench non-public-org repos, as v11 plans. Public dev-set gains transfer at about 0.3.
2. **Build a "hidden-like" dev slice** from those external repos: private-style layouts, heavier dependencies, short
   statements. Weight KPI decisions toward it. The public 74 over-reward fastapi/rich familiarity.
3. **Fix T1-T3 in the next bundle version.** They are cheap, and T1 plausibly fires on hidden repos with ML
   dependencies (the ≥20 MB wheel path exists for a reason). Add T4 to the nightly job before any further LB slot.
4. **Isolate temperature (T 1.0 vs 0.2) on the faithful L4 pair.** It is the one field-wide difference nobody has
   tested, and on a small reachable pool it is a reliability lever.
5. **Record submit→COMPLETE for every submission** (the gap5c poller, read-only). With the score, it is the only
   hidden-set signal. sub6 (v10.1) is the first bundle with finalize and time discipline, so its wall time tells
   whether hidden tasks end early (crashes) or run to the cap.
6. **Do not probe the private set through the score** (for example bundles that behave differently by repo
   properties). Kaggle's rerun stagger exists "to limit private dataset probing" (gap_5 §10.2), and it would not
   survive review for a prize.

## 8. Open questions (UNVERIFIED)
- Statement length and style of hidden tasks. The host's editing is undocumented.
- How many hidden tasks were admitted "within a single test case" of a frontier pass.
- Whether the scorer sets `enable_sandbox_testing=False` (pytest masked in container A). v10 handles it; public
  helper KPIs would then overstate hidden verification.
- Whether `/tmp` is tmpfs on the scorer, and whether gVisor is used.
- Which ≥20 MB wheels the private wheelhouse holds (TF, JAX, torch, numpy/scipy/pandas?).
- Queue time of sub3 vs sub4, which decides whether sub4's early finish means early exits.
- Whether the "synthetic hardware stubs" (README) exist in the private `sandbox/setup.py`, and what they stub.

## 9. Reproduce
```bash
cd /Users/carson/Projects/gemma-swe-agent/research/hidden_probes
../../.venv/bin/python -B strata.py      # public strata, 12 faithful runs -> strata.out, feat.json
../../.venv/bin/python -B union.py       # union-of-runs curve, time by stratum -> union.out
../../.venv/bin/python -B timek.py       # uniform-slowdown fit vs gap_5 in-clock times -> timek.out
/opt/homebrew/bin/python3.13 -m venv v313 && v313/bin/pip install -q --no-index --find-links ../../data/raw/wheels pytest
../../.venv/bin/python -B probe_layouts.py   # probes A-H (PROBE_OUT defaults to $TMPDIR/g4_hidden_probe_out)
../../.venv/bin/python -B probe_more.py      # probes I, J (re-runs A-H on import)
../../.venv/bin/python -B probe_imp.py       # probe K
# LB size check: HP/lb_2026-09-29T19-48Z.csv (kaggle competitions leaderboard gemma-4-developer-agent -d)
```
Do not run `compileall` on `submissions/`. It writes `__pycache__` into the bundle, which the ship gate rejects.
The probes copy the helpers out of the bundle first.
