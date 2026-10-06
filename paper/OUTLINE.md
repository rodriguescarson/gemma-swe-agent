# Paper track outline (gemma-4-developer-agent-paper, due 2026-11-12 23:59 UTC)

Status: outline only (2026-10-06). Prose under Carson's name goes through the ai-writing-detection skill and
voice-dna.md before it is entered (no em dashes, no slop). Carson must click "Join" on the paper track before
the first entry; ties go to the earlier entry, so a short honest v1 goes in early and is resubmitted.

Judging (0-5 each): Novelty, Quality (generality beyond this competition), Relevance, Verifiability, Clarity.
Prizes: Best Paper $15k, Best New Resource $10k, Best New Application $10k. Limit 3,000 words per writeup.

## Writeup A (Best Paper): "Your local score is a claim: what transfers when you build a small offline coding agent"

Thesis: under a fixed model and a wall-clock budget, most measured local gains are artefacts of the evaluation
set; the changes that transfer are the ones that remove a failure mechanism, not the ones that win a leaderboard
of four repos.

| # | Claim | Evidence (where) | Status |
|---|---|---|---|
| A1 | Public-74 gains did not transfer: L4 public v4h2 25 < v4 27 < v4h2g 34, hidden v4 3 < v4h2g 5 <= v4h2 6/5 | GATE.md sub9-sub12 | measured |
| A2 | An off-repo set agreed with hidden where the public set did not: Pallets 97 tasks v4h2 29 vs v4h2g 20 (paired 10-1, p=0.012) | GATE.md holdout57 + dev40 | measured |
| A3 | The "can't open file" failures came from the model skipping its own first instruction (install) in every case; a stage whose only tool is the installer removed them (54/74 and 44/74 tasks before; 0/5 smoke after) | GATE.md root cause; scripts/analyze_helper_reachability.py | smoke measured, L4 pending (v6p run) |
| A4 | Docker emulation hides the scorer's /tmp rewrite: v4h2's helpers worked offline and were dead on the scorer (locate 145/151 calls failed) | GATE.md v5h2 rebase note | measured |
| A5 | pass@6 = 41 vs pass@1 = 34 on L4 at half the time budget: best-of-3 with a fail-first repro selector | eval/kaggle results; AC-B2 | v6p L4 run pending |
| A6 | Thinking on vs off (no budget: a budget silently fails every task) | forum 746250, 745059; v6p-think | pending |
| A7 | Negative results: sampling penalties do not break tool loops (apply within one completion); prompt rules stop holding once a loop starts; a naive LoRA on 49 solved tasks caused a read loop | GATE.md, V4H2G_MISSES.md, GA_PROBE.md | measured |
| A8 | Unreachable share: ~22 public tasks are title-only or test hidden details; 6 import names that exist only in the gold patch | V4H2G_MISSES.md; forum 745855 | measured |

Method notes to state: pre-registered pass rules before each run (GATE.md timestamps), paired sign tests,
Wilson CIs, full population (all 74 / all 97 / all 1,044), every number next to the script that produced it.

## Writeup B (Best New Resource): "heldout1k: 1,044 execution-verified Python SWE tasks from 31 repos in the competition's format"

| # | Claim | Evidence | Status |
|---|---|---|---|
| B1 | 1,046 mined, 1,044 gold-verified under the grader's own pytest ini and command line (gold x2, empty patch fails) | data/heldout1k/PROGRESS.md, preflight_all_summary.json | measured |
| B2 | Coverage tags (routes, edge/zero/boundary, state, inputs, structure, surface, statement) with the gap report; 20% title-only | train/task_coverage.py | measured |
| B3 | Which repos/suites cannot be graded under the competition grader (ini replaced, -p no:anyio, py3.12 era) and why | PROGRESS.md rejection reasons | measured |
| B4 | Drop-in runnable: same layout as the public tasks, deterministic snapshots + graphs, one-line race command | data/heldout1k/README.md | measured |
| B5 | Usefulness: it ranks bundles the way the hidden split did (A2 extended to s200), and the locator's recall there (R@8 94%) vs public (R@1 0.49 vs 0.71) | research/2026-10-06_locate_recall_and_forum.md; A6000 P2 | partly pending |
| B6 | Packing bugs that would have silently invalidated tasks (isort metadata, installed-package shadowing, dropped wheels) | commits 38a977a.. | measured |

Release questions for Carson before B is entered: licence of the metadata (repos are under their own licences;
we ship ids, commits and patches, not code), where to host (Kaggle Dataset + GitHub), and timing (the competition
playbook says hold derived full-population results until submission; a resource paper is only useful if released).

## Open
- Which writeup first? (recommend B: the resource exists today and is measurably useful; A needs v6p results)
- Results needed from the A6000 (P2) and the Kaggle queue (v6p, v6p-think) before A is final.
