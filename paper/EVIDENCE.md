# Paper evidence index (gemma-4-developer-agent-paper, due 2026-11-12 23:59 UTC = 13 Nov 05:29 IST)

Every claim the paper may make, the file that holds its data, the script that produces the number, and the pre-registration
it was read against (docs/GAPS_2026-10-06.md, by section title). Extends paper/OUTLINE.md (6 Oct, claims A1-A8, B1-B6).
Rule: no number enters the paper unless it is regenerated from a file listed here. Started 18 Oct 2026; append, never edit
past rows (correct with a new row).

## C. A local screen does not rank hidden scores, and the 12-hour limit is a per-run gate (measured 13-18 Oct)

| # | Claim | Data | Produced by | Pre-registration |
|---|---|---|---|---|
| C1 | Box 74-task solves (26-31) do not order hidden public scores (0.10-0.15, and RUNTIME for the 0.24 public bundle) | eval/a6000/results/p4_*/results.jsonl; eval/analysis/out/kaggle_submissions_2026-10-18.json | eval/analysis/calibration.py -> eval/analysis/out/calibration.md | 'v13 replicate (A/A) result', 'pub024 control result' |
| C2 | The box's run-to-run noise on one 74-read: same bundle twice, 31 vs 29, 4 flips | eval/a6000/results/p4_v13, p4_v13r | channel B-105; recompute with the paired script in calibration.py's style | 'v13 replicate (A/A) pre-registration' |
| C3 | The public LB-0.24 bundle (8-min cap, 346 s/task on the box) exceeded Kaggle's 12-h limit on 2 of 2 of our draws; worst case 120 x cap must be <= 10 h | kaggle_submissions_2026-10-18.json (57280385, 57304025 error_description) | calibration.md | 'sub18 ERRORED on runtime', 'sub19 also RUNTIME' |
| C4 | 92-97% of a task's wall time is model generation; tools and harness 3-9% (10 box runs) | eval/a6000/results/p4_*/results/traces, p4_*_proxy.jsonl | eval/analysis/time_split.py -> eval/analysis/out/time_split_2026-10-18.txt | 'sub19 also RUNTIME ... deadline curve' |
| C5 | The session timeout is enforced (1-2 rows per run past cap+5 s, mostly one task); solves pile up just under every cap (v12: 27 at 300 s, 19 at 270 s) | same | eval/analysis/overrun.py -> out/overrun_2026-10-18.txt; deadline curve in GAPS | same |
| C6 | Per-task "lever" wins do not merge: two levers each solving its target task 3/3 lost 7 net on the full 74 (v14) | eval/a6000/results/p4_v14 vs p4_v13 | channel B-098 | 'v14 pre-registration', 'v14 result' |
| C7 | One-variable ablations toward the public bundle are neutral on the 74 (v12a 8-min +2, v12b temp 0.2 +1; pub024_6m -6 vs pub024) | eval/a6000/results/p4_v12a, p4_v12b, p4_pub024_6m, p4_v12c | channel B-158, B-168, B-177 | 'v12 ablations pre-registration' |
| C8 | Infrastructure contamination on a shared GPU (WDDM paging under a foreign process) produced 0-call rows; the stalled-row rule and the 0.88 headroom fix | eval/a6000/results/p4_v16a (stopped 57/74) | channel B-145..B-151 | 'p4_v16a stopped as CONTAMINATED', 'Stalled-row rule' |

## D. Harness² with a fixed small solver: improver choice, spend, transfer (running from 19 Oct)

| # | Claim (to be read, not assumed) | Data (pushed by the box) | Produced by | Pre-registration |
|---|---|---|---|---|
| D1 | Does Propose-Probe-Compose with Gemma as its own improver beat the unedited harness on 8 arrow tasks? | eval/a6000/results/h2_gemma/ | python -m h2g4.run <root> --judge | 'Harness² pilot pre-registration' |
| D2 | Same with frontier improvers (Gemini 4 Argon, Claude Fable 5.1, GPT-6 Astra), dollars per extra solve | eval/a6000/results/h2_argon/, h2_fable/, h2_astra/ (adapt/_spend.jsonl) | same | 'Harness² Phase 2 pre-registration' + amendments 1-2 |
| D3 | Do adopted harnesses transfer to repositories never used for refinement (12 tasks, boltons + attrs, base twice)? | eval/a6000/results/h2_transfer/ (eval_*.json, frozen/) | python -m h2g4.run ~/g4/h2/transfer --evaluate ... | 'Harness² Phase 2 amendment' (transfer test) |
| D4 | What the improvers change (general vs repository-specific edits) and what their sessions read | h2_*/root/library/, h2_*/root/adapt/_audit/ | diff against h2_*/root/base_tree | same |
| D5 | The spend guard held (per-session cost, budget stops) | h2_*/root/adapt/_spend.jsonl, _sweeps/budget-stop-*.json | tests/test_h2g4.py (runaway + concurrency simulations) | 'amendment 2' |

## Code that produced the evidence (cite by commit)

- h2g4/ (Harness² substrate + SWE adapter + CLI; Harness² pinned at google-research/harness2@1cfe254), tests/test_h2g4.py
- scripts/a6000/ (box autopilot, pace proxy, race runner, serve.sh), scripts/box_p4_gate.py, scripts/forty_two/screen_read.py
- eval/analysis/ (calibration.py, time_split.py, overrun.py) and eval/analysis/out/ (their saved outputs)
- the bundles themselves: submissions/<name>/, each pinned by a test in tests/test_<name>_bundle.py

## Not evidence (do not cite)

- Outside reviews pasted into the session (18 Oct) named related work (Self-Harness, MESH-Harness, Meta-Harness) and model
  release dates; none has been read or verified here yet. Verify each paper before it enters related work.

## Integrity rules (18 Oct, after an outside review)

1. **Present, not listed.** An archive counts as saved only after `python eval/analysis/verify_h2_archive.py <archive>
   --prereg "<GAPS heading>"` prints VERIFIED (manifest hashes, env with the harness2 pin and pip freeze, per-call proxy rows,
   summaries + improver transcripts + library + rollouts with traces + judge files, or for transfer both base runs and a
   frozen tree per candidate, and no key material). tests/test_verify_h2_archive.py. Each verification output is saved
   next to the archive as VERIFY.txt.
2. **Pre-registered vs observed.** GAPS sections are append-only. A reading rule changes only by a new, dated amendment
   committed before the result it governs; the verifier's `prereg` check proves the order from git ancestry. Results that no
   rule anticipated are labelled "observed, not pre-registered" in the paper (example: sub18's RUNTIME outcome, a state the
   sub18 rule did not foresee).
3. **One in-place edit, disclosed.** On 16 Oct three GAPS headings had their IST timestamps corrected in place (11:40 /
   12:30 / 12:45 -> 11:20 / 11:28 / 11:31, matching the channel's UTC stamps); content unchanged; the correction is itself a
   GAPS entry ('v12 ablations pre-registration', clock note). No other pre-registration text has been edited.
4. **Frozen before transfer.** Transfer candidates are frozen copies with fingerprints; transfer outcomes feed no harness and
   no selection (h2g4/run.py evaluate; test_evaluate_freezes_the_harness_and_refuses_a_swap_under_the_same_label).
5. **Scope of claims.** C1-C8 are findings about THIS setup: one fixed model (Gemma 4 31B int4), this harness, the 74
   public tasks, one A6000 box paced to the scorer's 4xL4, and about 58 hidden public tasks. The paper states them as such
   ("in our setup, a 74-task local screen did not order hidden scores"), never as properties of agent benchmarks in general;
   the hidden-side n (one or two draws per bundle) is stated next to every comparison.

## Chronology and completeness, as checks (18 Oct, after a second outside review)

- **Completeness at task and rollout level:** eval/analysis/h2_expected.json (committed before any Harness² rollout) lists
  every pre-registered task, the minimum rollouts per task (4 for k = 1) and the transfer labels; verify_h2_archive.py checks
  each task's summary, rollouts with traces and judged row, and each transfer label x task pair, truncating to the finished
  tasks only when a budget-stop record says so (tests/test_verify_h2_archive.py, 6 tests).
- **Chronology per claim:** eval/analysis/claims.json maps every claim id to its governing GAPS section and its results;
  eval/analysis/check_claims.py resolves each section to the commit that first added it and proves it is an ancestor of the
  commit that first added each result (or older than each Kaggle submission). Output: eval/analysis/out/claims_chronology.md
  (18 Oct: C2, C3, C6, C7, C7b ok; C1, C4, C5, C8 post hoc; D1-D5 pending with their rules already committed). The 16 Oct
  timestamp correction is listed there as the one disclosed exception, with its commit.
- **Dependency drift record:** the 18 Oct Linux failure (litellm vs mcp under a fresh resolution), its pin (6e9ef737), the
  passing flow-test run (eval/linux_test_out/flow_check_2026-10-18.log: 12 passed), and from now on every Linux run's full
  resolved environment (eval/linux_test_out/pip_freeze_v10.txt, pip_freeze_full.txt).
- **Two evidence streams, joined only by claim ids:** submission and box-screen results are C claims; Harness² results are D
  claims. A verifier pass establishes integrity, not truth: negative results, failed submissions (sub18, sub19 RUNTIME), budget
  stops and transfer regressions are reported alongside any gain.

## Tables (regenerated, never typed)

`python paper/make_tables.py` rebuilds paper/tables/{box_runs, paired, aa, deadline, calibration}.md from the result files,
each stamped with the commit and inputs. Only complete 74-reads enter. First build 19 Oct 01:10 IST (12 of 13 runs; p4_v16
running). An observation from the first build, recorded here before any v16 row is final (post hoc, not a pre-registered
claim): the public prompt solves late. At a 300 s cutoff, v12 keeps 27 of 27 solves, while v12c (v12 + the public prompt,
8-min limits) keeps 16 of 32 and pub024 19 of 31 (conservative deadline table). That would explain both the public bundle's
12-hour RUNTIME failures (11.5 h projected) and a weak 5-minute v16, whose box read is due 19 Oct ~02:30 IST.

## Positioning after the related-work check (19 Oct, paper/RELATED_WORK.md)

- **Lead with A (the C claims).** No verified prior work reports, for a coding agent under hard runtime limits, that a local
  screen failed to order hidden-set scores, nor the late-solve mechanism behind the public bundle's RUNTIME failures. Nearest:
  HarnessOpt-Bench (validation optimistic vs test), "On Randomness in Agentic Evals" (pass@1 swings), Roelofs et al. (little
  holdout overfitting on Kaggle overall: a counterpoint to cite honestly).
- **B (the D claims) is a constrained-setting study, not a new question.** Harness², Self-Harness (same-model harness
  improvement on SWE-bench Verified), HarnessOpt-Bench (frontier models as optimizers, hidden split) and Better Harnesses,
  Smaller Models already cover improver choice and small targets. What our D runs add: a small int4 solver under a hard
  per-task wall clock and a 12-h total limit, the target model as its own improver against three frontier improvers at
  measured cost, and transfer to repositories never used for refinement. The design already answers "Rethinking"'s two
  protocol critiques: no benchmark tests reach the improver (Harness² is ground-truth-free; tests only grade after
  selection), and transfer is read on held-out repositories; its third (a compute-matched test-time-scaling baseline) is
  only partly answerable here, because the deliverable is a static harness, not test-time search: the in-sweep base
  reruns are reported as the matched no-evolution baseline.

Correction (19 Oct, 02:45 IST): the line above says the late-solve observation was "recorded here before any v16 row is final".
The chronology checker showed p4_v16 rows were already on origin (first added 16:06Z; 51 of 74 seen by the author) when it was
written (19:30Z). It is an observation, not a blind prediction; claim C9 in eval/analysis/claims.json says so.

## C, added 19 Oct (C9 and C10 are in eval/analysis/claims.json; C11 and C12 added here and there)

| # | Claim | Data | Produced by | Pre-registration |
|---|---|---|---|---|
| C11 | The same failure on Kaggle's own 4xL4, with no pacing proxy: v4h2g beat v4h2 9-0 on the 74 (sign p 0.004), then read 0.08 hidden against v4h2's 0.10 and 0.08; L4 34 -> 0.08 while L4 32 (v12) -> 0.15 | eval/kaggle/g4-l4-{v4-wh28,v4h2,v4h2g,v12}-p312/results.jsonl; kaggle 56837573 | paper/make_tables.py -> paper/tables/l4_screen.md | docs/v4h/GATE.md 'sub10 read' (sub11 reading rule, committed 4 Oct 22:58Z, before sub11) |
| C12 | Hidden repeats of one bundle came back 0-1 task apart (v4 0.12/0.12 old scorer; v10.1 0.08/0.08; v4h2 0.10/0.08), tighter than the box A/A (2 tasks, 4 flips). Probable reason, not tested: seeded sampling on a sequential scorer, so a repeat measures scorer repeatability, not how a small change reshuffles solves. sub21 (v12, seed 42, again) tests it | kaggle_submissions_2026-10-18.json | paper/make_tables.py -> paper/tables/hidden_repeats.md | none (observed, post hoc) |
| C13 | The box noise floor, measured twice: v13 twice 31/29 (4 flips), v12 twice 27/29 (6 flips, 4 gained 2 lost); exact replays 13 and 4 of 74; same outcome 70 and 68 of 74 | eval/a6000/results/p4_v12r, p4_v12, p4_v13, p4_v13r | paper/make_tables.py -> paper/tables/aa.md | 'v12 local replicate (box A/A) pre-registration' (CONFIRMED) |

Correction to C12 (19 Oct 16:30 IST): its "probable reason" (seeded sampling replays samples) is withdrawn. Cross-day trajectories
rarely replay on the box (C13: 4 and 13 exact of 74), and two box repeats moved their totals by 2 while flipping 4-6 tasks, so
close hidden totals (0-1 task) are what ordinary flip noise with cancellation gives. The C12 observation itself stands.

## Entered versions (Kaggle paper track)

- v1, submitted 2026-10-20 01:08 IST: https://www.kaggle.com/competitions/gemma-4-developer-agent-paper/writeups/what-a-local-screen-could-not-tell-us-about-a-smal
  Title "What a local screen could not tell us about a small offline coding agent"; body = paper/WRITEUP_v1_body.md
  (sha256 9dc7f67bd47544e3fc4e8383008914373f4b24a9b761917842bcdd885c190bb4, verified in the page's editor before submit; Kaggle
  counts 2,848 words); card image paper/card_v1_small.png; project link = the repository (private until the final version).
  Kaggle shows it as "Submitted", hidden from others until the hackathon closes, editable and resubmittable until the deadline;
  licence on the writeup page: CC BY 4.0 (Kaggle's default). Pending for v2: sub21's hidden repeat, Harness² Phase 2 + transfer,
  the repository made public.

Status (20 Oct): the A6000 box is closed (channel B-247). D2, D3 and D5 were never run and have no data; D4 covers Phase 1
only. The transfer base_a run (4/12) survives only as the per-task list in channel B-218, without traces. v1's section 5 says
the frontier sweeps are "still running"; that is no longer true and must be corrected in the next entered version.

- v2, updated 2026-10-23 15:05 IST with "Update Submission" (same URL as v1; the entry stays "Submitted", it was never unsubmitted).
  Body = paper/WRITEUP_v2_body.md (sha256 e035992177e27e27d3201ca4749fa268c404c9f30ee8bc2e69c84a811305bb18, 2,957 words,
  16,542 chars, verified in the page's editor before saving). Subtitle changed from "Two local screens, eight hidden submissions
  of a Gemma 4 agent, and why the screen could not rank them" to "Two local screens, eleven Gemma 4 agent configurations scored on
  the hidden set, and why neither screen could rank them". Project link = the repository, public since 2026-10-23. Section 5 now
  says the frontier sweeps and the transfer test did not run; adds the four newer hidden reads (sub20-sub23), the A6000 rank
  correlation (Spearman +0.49, exact permutation p 0.32, n 7) and a link to paper/arxiv/main.pdf. Checked after a reload: the
  live page carries the v2 phrases and no longer has the v1 subtitle.

## Full paper (paper/arxiv/)

- Zenodo, published 2026-10-23 15:11 IST: https://doi.org/10.5281/zenodo.23592038 (concept DOI 10.5281/zenodo.23592037),
  preprint, CC BY 4.0, creator Rodrigues, Carson (Celabe Research, ORCID 0009-0001-7195-6742), file
  local-screen-small-coding-agent.pdf = paper/arxiv/main.pdf (sha256 78c5cbed..., 11 pages, 3 figures, 5 tables; upload md5
  checked by Zenodo). Related identifier: isSupplementedBy the repository. Checked after publishing: the public record API
  shows the metadata above, doi.org redirects to the record, the file downloads (HTTP 200).
- Kaggle writeup v2, edited 2026-10-23 15:13 IST (Update Submission): section 8's link to the long version now points at the
  DOI instead of the branch PDF. Body sha256 8f55afc5639e083bda7d4ae8823cfa09ddadaa655674a06dec451336662b56c1 (16,489 chars),
  verified in the editor before saving and on the live page after a reload.
- arXiv: source package built (paper/arxiv/arxiv-source.tar.gz, gitignored; recipe in paper/arxiv/SUBMIT.md), not submitted yet.
