# Assumption audit, 30-31 Oct 2026: why we are not scoring better

The owner asked: "continue testing, question all assumptions, check why we are not performing well". Five read-only tests ran
in parallel: the field and the statistics, hidden runtime, transfer to other repos, scorer fidelity, and how close our failing
patches are. None used a GPU, submitted anything or spent money. The strongest claim from each test was then re-checked by a
separate agent told to refute it. The scripts and small outputs are in this folder. Local paths are scrubbed. Third-party
notebook sources and the scripts that read our own session transcripts were not kept.

Labels: MEASURED (a script here and its output), CODE (file:line), HOST (competition page or organiser), INFERENCE.

## The answer

1. **We are not behind the field's bulk.** The board has 4,195 teams and 28,170 submissions and shows each team's best read.
   Its ladder (917, 305, 62 and 7 teams at 11, 12, 13 and 14 of 58 or more) is reproduced by a common per-read mean of about
   8.1/58 with a per-read SD of 1.5 tasks (MEASURED, `field/common_mu.py`, `field/mixfit.py`). Our 31B line averages 8.0-8.7
   (0.14-0.15). The 0.17 on our row is the best of 26 submissions; expect the private score near 0.14.
2. **We are probably 1-2 tasks behind the best public lineages.** The public file sets with three or more scored draws average
   9.25-10.0 of 58 (pooled later draws 9.57 over 21). All of them run an 8-minute cap with 28 calls, 80 turns and 240-300 s
   per command. Prompt length, tool count and sampling do not separate them; the budget is the one common difference
   (INFERENCE, medium confidence, `field/extract_bundles.py`).
3. **Hidden is a third of local because of the tasks, not our prompt.** The v12 prompt scores 0.93-1.11 times its public rate
   on 15 other open-source repos (468 stored runs). No open-source proxy reproduces the hidden drop (MEASURED,
   `transfer/out/solve_by_feature.txt`). Statements under 25 words solve 22% against 39%, and gold patches touching two or more
   files 15% against 43%.
4. **Our decision rule could not see effects of the size we tested.** Byte-identical resubmissions pool to an SD of 1.50 tasks
   per read (95% CI 1.18-2.04). One read is plus or minus 3 tasks. A candidate with no real change is dropped by the
   "0.14 or less" band 55% of the time. So "every change since v12b read lower" is not evidence that the changes were worse.
   Detecting +1.5 tasks at 80% power needs about 16 reads per arm (MEASURED, `field/line_stats.py`).

## Corrections to our own records

| Claim in our notes | What the files show |
|---|---|
| "v12b's repeats are 0.17, 0.15, 0.17" (OPTIMISE_RANKING, line 74) | v12b has one hidden read, 0.17 (sub20). The 0.15 is v12b6 at 6 min. |
| "pub024_6m failed on runtime" (premise of the 5-minute gate) | It was never submitted. It failed our own box gate on 18 Oct (`eval/arm_sub20_chain.out`). No 6-minute bundle has failed on hidden; v12b6 at 6 min scored 0.15. |
| "Every capped public run scored 0 (123/123)" | A labelling artefact. CODE: `swegemma/harness/verification.py` sets `error=None` on resolved rows, so capped solves lost their cap label. On the L4 runs, 4 of 32 (v12) and 3 of 28 (v12b) clock-ended runs solved, and 14-17% of all solves land at the cap. |
| "120 x cap must stay under 10 h" | HOST: the 12 hours are "inclusive of sandbox setup time, but excluding time for patch validation". The verified projection is below. |
| "Kernel grades can only err low (Phase 2 at 180 s vs 300 s)" (my note of 29 Oct) | Only for the 11 Oct wheelhouse. The build served since 12 Oct defaults `verification_timeout_seconds` to 300, as the host notebook passes it. Fixed in `scripts/make_eval_kernel.py`. |
| "Hidden tasks take 1.6-1.8x public time" (v4, thinking off) | Does not hold for the current line: a run cannot exceed its cap plus overhead, at most about 1.3x local. |

## What the time budget is worth

- **Local (MEASURED, `runtime/out/a7.out`, `a8.out`).** About 7% of solves are lost per 30 s cut. Among runs still alive at
  240 s, 8% solve in the next 60 s. On the box, v12b6 at 6 min solved 29 of 71 against v12b's 26.
- **Projection, after the adversarial re-check (`verify-runtime/mc3.py`).** The re-check reweighted the box timeline to the
  hidden solve rate and widened the overhead ranges.
  - **5.5 min:** projected 10.5-11.3 h; breach probability about 0-1.5%; net about +0.5 task of 58 (range -0.5 to +1.0).
  - **6.0 min:** projected 11.1-11.9 h; breach probability 6-17% (central about 10%). As a sole final this roughly cancels its
    +1 to +2 task upside.
  - **8 min (pub024):** errored on runtime 2 of 2 for us.
- **Runtime risk may land on the slot, not on the final.** No competition page says finals are re-run. Each submission is
  scored once on the hidden set, so a submission that scored already carries its private score (INFERENCE). If that holds, a
  runtime failure costs one daily slot, not a final.

## What did not hold up, or does not pay

- **Near misses (MEASURED, `nearmiss/classified.json`).** Replayed 105 distinct patches; labels agree with Kaggle's on 120 of
  120 pairs.
  - Of 54 failing patches, none is a strict near miss.
  - A "run the module's existing tests" rule would flag 15 (28%) but flip about one.
  - py_compile would flag 5, all inside those 15.
  - 53% of failing pairs ended at the 5-minute wall without submitting.
  - The agent's last own check was green in 73% of submitted-wrong runs.
- **Repo conventions.** v12b's instructions are repo-agnostic (TR1, TR5). The "Google-style test conventions" inference does
  not survive; pytest collects `*_test.py` by default. Heavier dependencies and device or monorepo layouts remain a medium
  prior (the prune list names `google3` and `g3doc`).
- **Scorer fidelity.** Everything the agent sees matches the scorer:
  - the first message is byte-identical on all 74 tasks;
  - tool schemas, compaction and the vLLM flags are the same;
  - decode speed is 34.8 against 34.6 tok/s.

  The scorer probably runs Docker (Python 3.13, 2 vCPU) where the kernel runs a subprocess sandbox. The v12 line does not
  touch the differences: no run uses /tmp or pip.

## Open questions and the cheapest test for each

- **Scorer speed.** A scorer 25% slower than the kernel would cost 3-4 of 29 local solves. The CLI does not show a
  submission's run time. Submit-to-COMPLETE (13.5-33.5 h, `runtime/out/submissions_timeline.md`) includes the queue. The run
  time may show on the Kaggle submissions page in the owner's browser.
- **Whether finals are re-run.** Read the forum, or ask the host.
- **Edit-call garbling on non-public repos with the current stack.** One 4x L4 hour on 14 heldout tasks.

## Recommendation

- **Stop the v12b repeats.** A repeat has a standard error of about 1.1 tasks and P(read of 0.13 or less) = 0.55, so it cannot
  separate v12b from v12. This reverses my 30 Oct recommendation.
- **Spend slots on the time budget.** It is the only lever with a plausible effect of half a task or more, and the only
  systematic difference from the best public lineages. In order:
  - v12b at 5.5 min (safe);
  - 6 min, if a scored submission's private score is fixed;
  - an 8-minute public lineage byte-identical, which has the highest upside and the highest runtime risk.
- **Report the expected private score as about 0.14, not 0.17.**
