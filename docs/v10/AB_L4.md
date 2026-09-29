# Next faithful Kaggle-L4 A/B: v10.1 control against three one-lever arms

Written 2026-09-29, before any of these kernels exists. Nothing here was pushed, queued or submitted; pushing is
Carson's call. The decision rule in section 5 is pre-registered: it may not change after the first kernel is queued.
A change goes into a dated addendum at the end, with the reason, and the original text stays.

Inputs: `docs/v10/v10_1_diag_5.md` (the fix-quality diagnosis and its levers A-D), `eval/race2/round1_kpis.txt`
(race 2 round 1: v10 25 against v9_eog 24, paired 6-5), `eval/kaggle/g4-l4-v4` and `g4-l4-v9-eog` (Kaggle-L4 faithful
runs, 29/74 each), `research/org_update_0928.md` (the host notebook as of its 2026-09-27 19:50 UTC run).

## 0. Bottom line

- **Four kernels on the same 74 ids** (`data/kaggle_valid_ids.txt`), one run each: the control is v10.1
  (`submissions/v10`), and each arm is v10.1 plus exactly one lever: `v10_1_flip` (lever A), `v10_1_sweep` (lever B)
  and `v10_1_t02` (lever D).
- **Two levers were left out.** Thinking in the fixer costs +79 to +143 s per task, which breaks the 1.1 x wall rule on
  its own (diag 5 section 4). Lever C (read the nearest test first, plus 2 gate fixes) has only "possible" flips, so it
  is the next arm if a slot opens.
- **About 3.5 h of 4 x L4 session time per kernel, about 14-15 h for all four** (section 3). Queueing is bound by the
  14 h rule (section 4). In practice the A/B needs one skipped daily submission.
- **Ship rule, per arm:** at least +4 paired against the control, no new crash class, and wall time at most 1.1 x the
  control. `scripts/ab_l4_decide.py` applies it mechanically.
- **What a pass is worth:** with about 11 discordant tasks, a lever with no effect still reaches +4 in 11-19% of runs,
  and at least one of three null arms does so in 30-47%. A real +3 lever reaches +4 only about 40-50% of the time
  (section 5.3). One run can confirm only a large lever.

## 1. Arms

| arm | bundle | lever (diag 5) | what changes | L4 cost per public task | likely / possible flips | mechanism to read in its traces |
|---|---|---|---|---|---|---|
| control | `submissions/v10` (v10.1) | none | nothing | 0 | n/a | baseline for every row |
| flip | `submissions/v10_1_flip` | A, repro-must-flip | `_swe_gate.verdict`: on AMBER "no reproduction saved" or "the reproduction passes on original" before FINISH (t < 210 s), the NEXT line asks the fixer for a claim that fails on original: the issue's literal inputs, one claim per behaviour including the return value, a loop over every position and example input for invariants, and the heredoc and `# CLAIM 1:` form. A claim guides the fix and never vetoes it. `_swe_common`: the locator phase gets `CONTEXT_TOKENS_LOCATOR` 7,000 while t < 75 s (4,700 elsewhere). `fixer.md` step 3 gains "AMBER: follow its NEXT line." (5 words; the fixer is at 369 of 370 words). | +8 to +14 s | rich_3506, fastapi_9425 / rich_4075, rich_3052, rich_3777, rich_4006, fastapi_9753 | AMBER-without-flip share (race 2: 23/74 = 31%, target under 15%); repro calls per stage; GREEN precision (12/20) |
| sweep | `submissions/v10_1_sweep` | B, completeness sweep (its mechanical part) | `edit.py` prints `SAME CODE ELSEWHERE` after each edit: up to 3 unchanged lines that repeat, at word boundaries, a whole line the diff removed from that file, rarer patterns before lines copied many times (about +50 ms per edit, section 6). Generic lines (`width=width,`, `options=options)`, bare returns, imports) are dropped. `_swe_gate.siblings` is that scan, plus a same-named def only when its body repeats a removed line (same-name defs whose code differs, 9 of 17 race-2 SIBLINGS lists, are dropped), and verify runs the scan even when a hanging claim ate the quick-mode deadline (rich_3480). Diag 5's prompt parts of B are not in this arm (section 1.1). | about +2 s | fastapi_5077, rich_3480 / none (diag 5's possible flips for B came from its prompt parts) | SAME CODE / SIBLINGS fire rate and whether the next edit touches the listed line; hidden-test hangs, exit 124 (race 2: 3) |
| t02 | `submissions/v10_1_t02` | D, temperature | `temperature: 0.2` in `gen_{locator,fixer,verifier}.yaml` (setup and submitter already run at 0.2); top_p 0.95 and top_k 64 are unchanged | 0 s direct | none named (every public bundle scoring 0.12 or more uses T 0.2; our sweep1 found no effect, p > 0.45) | identical-call repeats per task (race 2: 5.4); leaked tool-call text |

Each lever is an exact-once text patch in `scripts/make_variant.py`: `--flip`, `--sweep`, or `--work-temp 0.2`. An arm
changes only the files listed above (`tests/test_make_variant_v10.py::test_arm_changes_only_its_lever`). Every
committed arm is byte-identical to a fresh build from today's `submissions/v10` (`::test_committed_arm_is_fresh`). If
v10 changes before the push, that test fails, and every arm and kernel has to be rebuilt with section 2's commands.
If a patched text disappears from the base, make_variant exits 2 and leaves no bundle.

### 1.1 What did not fit, and why

- **Diag 5's prompt parts of lever B** are left out: a FILES entry and claim per linked issue and per "X and Y" part, the
  data model plus the renderer for a new attribute, and every loop branch for a hang.
  - `prompts/locator.md` is at 369 of the 370 words R91 allows (`tests/test_v10_prompts.py::test_prompt_sizes`).
  - The rule alone is 56 words. Making room would mean cutting other locator rules, which is a second lever.
  - The sweep arm therefore tests the mechanical sweep only. The parts could be carried by helper output instead, in a
    later arm.
- **Lever A's claim rules live in verify's NEXT line**, where the fixer meets them at the moment they apply. The prompt
  gets only 5 words, for the same cap (the fixer is at 369 words) and for R95's worst-decile margin. In R95 check B
  (p95 statement, p90 handoffs, 2.3 chars/token, outputs at their caps), the flip fixer clears the 14,336 compaction
  line by 1,029 tokens, against 1,000 required (v10.1: 1,038).
- **The price of the locator's 7,000 threshold.** The flip locator's margin in the same check falls from 2,693 to
  1,079 tokens. There the prompt's permitted call mix (about 8 calls) binds, not the meter, so a locator that goes past
  that mix before t=75 s is bounded only at 7,000 estimated tokens. Diag 5 accepted this: a 3.5-4k start plus 7,000
  still leaves about 3k under the compaction line in estimated tokens.

The P0 fix from diag 5 (helpers named only as `python3 /tmp/swe/NAME.py`, R89b/R89c) is already in v10.1. So it sits in
the control and in every arm, and it is not an arm.

## 2. Exact build commands

Run from the repo root. The bundles below are already built. Rebuild them only when `submissions/v10` changes.

```
python scripts/make_variant.py submissions/v10 submissions/v10_1_flip --flip
python scripts/make_variant.py submissions/v10 submissions/v10_1_sweep --sweep
python scripts/make_variant.py submissions/v10 submissions/v10_1_t02 --work-temp 0.2
python scripts/validate.py submissions/v10_1_flip      # each prints OK model=gemma-4-31b-it-qat-w4a16-ct
python scripts/validate.py submissions/v10_1_sweep
python scripts/validate.py submissions/v10_1_t02
```

Kernels, already built under `kernels/g4-l4-v101*`; rebuild them whenever a bundle is rebuilt. All four print
`budget {"max_time_minutes": 5.0, "max_tool_calls": 100, "max_turns": 200, "timeout_seconds": 180} from
eval_config.yaml`: the bundles share one `eval_config.yaml`, and no flag overrides it.

```
python scripts/make_eval_kernel.py submissions/v10 g4-l4-v101 --ids data/kaggle_valid_ids.txt
python scripts/make_eval_kernel.py submissions/v10_1_flip g4-l4-v101-flip --ids data/kaggle_valid_ids.txt
python scripts/make_eval_kernel.py submissions/v10_1_sweep g4-l4-v101-sweep --ids data/kaggle_valid_ids.txt
python scripts/make_eval_kernel.py submissions/v10_1_t02 g4-l4-v101-t02 --ids data/kaggle_valid_ids.txt
```

`python` means the project interpreter (`.venv/bin/python`). The builder falls back to a stdlib reader when PyYAML is
missing, and the two readers agree on every bundle (`tests/test_make_eval_kernel.py`). Each slug starts with `g4-l4-`,
so the GPU-overlap guard in `scripts/submit_at.sh` sees it. Each arm has its own slug, because saving a new version of a
queued kernel can cancel the queued one (osama133, UNVERIFIED).

What the kernel builder now does (2026-09-29, `tests/test_make_eval_kernel.py`, 19 tests):
- **Budget.** The four budget keys come from the bundle's `eval_config.yaml`, read with the host notebook's own code:
  the `evaluation:` section or the top level; defaults 300 s / 100 calls / 60 min / no turn limit; `max_llm_calls` as
  the turns fallback. `--min/--calls/--turns/--timeout` override single keys only.
  - The old defaults were 6 / 60 / 80 / 180, which matched no bundle.
  - The kernel re-reads the file with the host's code and stops before vLLM starts if its reading differs from the
    builder's, so a mismatch costs no GPU startup.
  - A bundle without `eval_config.yaml` is refused unless all four flags are given, because the host notebook would
    crash reading it.
- **Mirrors the host's current notebook.**
  - There is no `default_chat_template_kwargs={'enable_thinking': True}` any more.
  - `VllmConfig`, `EventsCompactionConfig` (15 / 2 / 14,336 / 5) and `ContextCacheConfig` (2048 / 1800 / 10) take the
    same keywords and literal values as the host's 2026-09-27 19:50 UTC run. It is kept at
    `ref/getting_started_20260927/` (sha256 `0c54c3ba...`), and the tests compare the two by AST.
- **Records the wheel set by content** (`wheelhouse_sha256.txt`). vLLM and adk_submission were rebuilt in place under
  unchanged version strings on 2026-09-27, so version strings cannot identify them.

Pushing (Carson, never this workflow), then fetching and deciding:

```
scripts/push_after_scoring.sh kernels/g4-l4-v101          # pushes only when no submission is PENDING
kaggle kernels output carsonrodrigues/g4-l4-v101 -p eval/kaggle/g4-l4-v101
python scripts/ab_l4_decide.py eval/kaggle/g4-l4-v101 eval/kaggle/g4-l4-v101-flip eval/kaggle/g4-l4-v101-sweep \
    eval/kaggle/g4-l4-v101-t02 --ids data/kaggle_valid_ids.txt
```

## 3. GPU hours per arm

Measured anchor: `g4-l4-v4` used 11,882 s of session time (3.30 h). Of that, 11,442 s was the 74-task loop, about 60 s
was wheel install, and 335 s was vLLM startup. `g4-l4-v9-eog` used 13,562 s (3.77 h). These are one 4 x L4 session each.

| kernel | estimate | how |
|---|---|---|
| g4-l4-v101 (control) | 3.45-3.65 h | the loop is 74 x 154.6 s (v4 on Kaggle) x 1.048 (v10's race-2 replay against r_v4) = 11,990 s. Add P0's +8.5 s per task (leaked stages now run to completion, diag 5 section 4) = +630 s. Add 440 s of startup. |
| g4-l4-v101-flip | 3.6-3.95 h | control + 74 x (8 to 14 s) |
| g4-l4-v101-sweep | 3.5-3.7 h | control + 74 x about 2 s |
| g4-l4-v101-t02 | 3.45-3.65 h | control; more identical-call loops would lengthen it, and the 5-minute cap bounds each task |
| **all four** | **about 14-15 h** | |

Every row assumes Kaggle charges one 4 x L4 session as one session-hour. Two things are UNVERIFIED: whether Kaggle's
weekly GPU quota counts a 4 x L4 hour as 1 or 4, and whether it counts queue time. Participants report that queue time
is charged (743683), and a 10 h queue wait was observed on 2026-09-28. Check the quota page before queueing.

## 4. Queue rules (a kernel that overlaps scoring costs a submission day)

1. **No GPU kernel may be queued within 14 h of a 00:01 UTC (05:31 IST) submission.** A kernel queued on 2026-09-28
   waited about 10 h, then ran 3.5 h and overlapped sub5's scoring start. So queue a kernel only if the next submission
   is at least 14 h away: on a day with a submission the next morning, the latest queue time is 10:01 UTC (15:31 IST).
2. **Nothing is queued while a submission is PENDING** (Carson's rule of 2026-09-27; `scripts/push_after_scoring.sh`
   enforces it). Our submissions have finished scoring at about 10:30 UTC (16:00 IST); participants report 12-14 h
   (743683).
3. **Together, rules 1 and 2 leave no window on a day between two daily submissions.** Scoring ends after the 10:01 UTC
   deadline. The A/B therefore needs one skipped slot. Earliest example, if Carson skips the 2026-09-30 00:01 UTC
   (05:31 IST) slot:
   - Queue wave 1 once sub5 (submitted 2026-09-29 00:01 UTC) shows COMPLETE.
   - Queue wave 2 only after wave 1 finishes, and no later than 2026-09-30 10:01 UTC (15:31 IST). That is 14 h before
     the next slot, 2026-10-01 00:01 UTC.
   - If wave 2 misses that time, skip one more slot; never queue late.
4. **At most 2 queued or running GPU sessions** (osama133, UNVERIFIED). So the kernels go in two waves:
   - Wave 1: control and flip. The flip arm has the most likely flips, and it runs next to the control on the same day
     and the same wheels.
   - Wave 2: sweep and t02.
5. **Pairing check.** `ab_l4_decide.py` marks a pair INVALID when the two runs' `wheelhouse_sha256.txt` differ, or when
   either run misses ids. The host has rebuilt wheels between waves before (v23-v25 within 70 minutes on 2026-09-27).
   If wave 2 lands on a different wheel set, its arms need their own control run; they are never decided against
   wave 1's control.
6. Before arming a submission, run `kaggle kernels status` on all four slugs. `submit_at.sh` also waits for busy
   `g4-l4-` kernels until the end of the UTC day.

## 5. Pre-registered decision rule

### 5.1 The rule (as specified for this A/B, unchanged)

Each arm is paired against the v10.1 control on the same 74 ids, one run each. **An arm ships only if all three hold:**
1. resolved(arm) - resolved(control) is **at least +4**, counted on the paired ids;
2. **no new crash class**: no class has a row in the arm and none in the control. The classes are race2_checklist row 3
   (context overflow, unknown tool, KeyError, post-invocation ValueError), plus a kernel-loop exception (`EXC`), a
   sandbox execution error, and any other error text. A session timeout is not a crash;
3. **wall time at most 1.1 x the control**: the sum of per-task seconds in `results.jsonl`. vLLM startup is excluded;
   it does not depend on the arm.

If more than one arm is eligible: take the largest delta, then the lower wall ratio. A combination of eligible arms is
a new bundle, and it needs its own A/B against the control before it ships. It is never inferred from this one.

### 5.2 Validity (not part of the rule; a failed check means rerun, never decide)

- Both runs have results for all 74 ids.
- Both runs recorded the same wheel set, when both recorded one.
- The four kernels were built from the committed bundles (`test_committed_arm_is_fresh` and
  `test_built_kernels_carry_the_committed_bundles` green at push time).

### 5.3 What a pass does and does not show (computed before the run)

Race 2 round 1 had 11 discordant tasks (6-5), and the Kaggle-L4 v4 / v9_eog pair had 10 (5-5). Exact one-sided
binomial, `P(wins - losses >= 4)`:

| discordant tasks | lever has no effect | true net +2 | true net +3 | true net +5 |
|---|---|---|---|---|
| 11 | 0.11 | 0.28 | 0.39 | 0.65 |
| 12 | 0.19 | 0.39 | 0.51 | 0.75 |
| 13 | 0.13 | 0.29 | 0.40 | 0.63 |

- With three arms and no effect anywhere, the chance that at least one passes is 0.30-0.47.
- Diag 5's likely and possible flips, at its priors (0.7 likely, 0.35 possible), give about +3 for flip and +1.5 for
  this sweep arm (its 2 likely flips only). At those sizes each arm passes about as often as not.
- So a pass means "worth shipping under the rule". It does not measure the lever's size. A fail at +2 or +3 does not
  show the lever does nothing.
- The mechanism rows below are the evidence that can separate a real lever from noise at this N. They are reported
  for every arm. They never override the rule.

### 5.4 Reported with every decision (never deciding)

- **Every arm:** paired wins and losses with the exact sign-test p; session timeouts; mean seconds per task; wheels
  same or unrecorded. `ab_l4_decide.py` prints all of these.
- **Mechanism KPIs, from `traces.tar.gz` with `replay_l4`'s definitions:**
  - leaked tool-call text per task (target 0.05 or less);
  - AMBER-without-flip share (flip);
  - SAME CODE / SIBLINGS fired, and acted on (sweep);
  - hidden-test hangs, exit 124 (sweep);
  - identical-call repeats per task (t02);
  - GREEN precision.
- `replay_l4.load` expects `task_results.jsonl`, and the kernel writes `results.jsonl` beside the harness's `results/`
  tree. The small adapter this needs is **not built yet**.

## 6. What was checked locally (2026-09-29)

- `tests/test_make_eval_kernel.py` (19 tests): budget from `eval_config.yaml`, with overrides, host defaults and the
  fallback key; the stdlib and PyYAML readers agree; the kernel's in-notebook reading equals the builder's and stops on
  drift; AST parity with the host notebook; the wheel hashes.
- `tests/test_make_variant_v10.py` (39 tests):
  - the arms are fresh and each changes only its lever;
  - the levers compose, refuse non-v10 bases and fail closed on a stale patch;
  - flip: the CONTEXT limit by phase and time, through the real helpers; the NEXT line in both AMBER cases, never
    after FINISH; GREEN unchanged;
  - sweep: SAME CODE ELSEWHERE on the rich_3480 shape, with same-name defs and generic lines left out; ranking and
    rarity order; a same-named def kept only with the same code; SIBLINGS after a hanging claim at t=256 s; the scan
    takes under 0.5 s on a 3,000-file repo;
  - edit.py's scan uses whole removed lines only. The first build also grepped call fragments, and after 8 edits the
    scan took 0.44 s, because 4 `-F` patterns sharing a prefix cost git grep 0.24-0.39 s. Now the cost, measured
    paired over 30 edits on a 1,550-line fixture with the Mac loaded, is +50 ms per edit (median 248 ms against
    201 ms). verify keeps the call fragments;
  - every flip and sweep check has a control on the base that shows the old behaviour;
  - the Linux gate forwards `G4_BUNDLE` and runs this file (`::test_linux_gate_runs_the_arms`);
  - the four kernel dirs embed exactly the committed bundles, the 74 ids and the budget
    (`::test_built_kernels_carry_the_committed_bundles`).
- `tests/test_ab_l4_decide.py` (13 tests): the threshold edges; the pairing; crash classes; invalid pairs; the pick
  among eligible arms; and the real v4 / v9_eog runs (delta 0, so NO; v9_eog adds a context overflow).
- `tests/test_bundles.py` covers the three new bundles: the official compiler and clean files. `scripts/validate.py`
  prints `OK` for each.
- **The full v10 suite on each arm** (`G4_BUNDLE=submissions/<arm> pytest tests/test_v10_*.py`; the v10 test modules
  now honour `G4_BUNDLE`), including:
  - the R87-R96 prompt lints;
  - the R95 context budget, which now reads a bundle's `CONTEXT_TOKENS_LOCATOR` for the locator stage;
  - the R89b/R89c helper-naming lints;
  - the runtime output lints.
  Results are in section 7.
- **The whole suite** (`.venv/bin/python -m pytest -q -p no:cacheprovider tests`): 1,445 passed, 0 failed, 555
  skipped, 6 xfailed (14 min on a loaded Mac).
- **The Linux gate** (`G4_BUNDLE=submissions/<arm> V10_ONLY=1 scripts/linux_test.sh`: Docker python:3.12-slim with the
  scorer's 2 CPUs and 4 GB, TMPDIR unset) runs the v10 suite plus `tests/test_make_variant_v10.py` on the arms that
  change helper code.
  - sweep: 709 passed, 0 failed, 763 skipped.
  - flip: 706 passed, 2 failed, 763 skipped. The 2 failures are the SPEC-pinning tests of section 7.
  - The v10.1 base under the same gate: 707 passed, 1 failed, 763 skipped. The failure is
    `test_v10_edit.py::test_edit_output_and_perf`, whose 150 ms edit.py p95 is asserted inside a 2-CPU container, and
    both arms passed it. It is a timing flake on the unchanged base, not a lever effect.

## 7. Conformance of each arm to the v10 suite

Command: `G4_BUNDLE=submissions/<arm> .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_v10_*.py` (macOS,
2026-09-29). Every failure is a test that pins v10.1's own bytes to SPEC.md, so it fails by construction on the file
the lever changes. No other v10 test fails on any arm. The 555 skips are the same on every arm.

| arm | result | failures, and why each is the lever itself |
|---|---|---|
| flip | 870 passed, 2 failed, 555 skipped, 6 xfailed | `test_v10_bundle.py::test_bundle_files_equal_spec`: `prompts/fixer.md` differs from SPEC's byte-pinned text by the 5 added words. `test_v10_prompts.py::test_prompt_sizes`: the fixer's size is 369 words / 2,366 chars, against SPEC's pinned 364 / 2,337. The R91 caps (370 / 2,600) pass. |
| sweep | 872 passed, 0 failed, 555 skipped, 6 xfailed | none: the arm changes only helper code, and SPEC pins no helper bytes. |
| t02 | 870 passed, 2 failed, 555 skipped, 6 xfailed | `test_bundle_files_equal_spec` and `test_generation_configs`: the three working stages' temperature is 0.2, against SPEC's 1.0. |

What passes on every arm and matters most for a lever that changes helper text or prompts:
- the R87-R96 prompt lints, with the R95 worst-case context budget. For flip it runs with the 7,000 locator threshold;
  the margins are in section 1.1.
- the R89b/R89c helper-naming lints over every string a helper can print, including `FLIP_NEXT` and `SAME CODE
  ELSEWHERE`, and the runtime pass over real helper outputs.
- the flow, sandbox and integration tests through the real harness subprocess sandbox.
- `test_v10_verify.py::test_verdict_table_and_wording` on flip. An earlier `FLIP_NEXT` said "never undo the fix". That
  broke R62, which bans "undo" from verdict wording: test_plan F4 found that gate wording told the model to undo
  correct fixes in 6/39 tasks. It now says "change the code, not the claim".
- `test_v10_verify.py::test_siblings` on sweep, which lists a same-named def with the same code (B.render_row). The
  first sweep build dropped every same-name def and failed it. The shipped build keeps same-name defs whose body repeats
  a removed line, and drops only those whose code differs, which is what diag 5 asked for.

## Addenda

(none yet)
