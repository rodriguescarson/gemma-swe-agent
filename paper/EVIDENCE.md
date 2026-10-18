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
