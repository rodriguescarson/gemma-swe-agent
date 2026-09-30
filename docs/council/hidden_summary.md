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
