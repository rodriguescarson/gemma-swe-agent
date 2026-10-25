# Architecture review, 25 Oct 2026: where the 31B line loses tasks, and what to change

The owner asked for a fresh look at the agent architecture, checked against what is online, with the goal of improving the
0.17 line (v12b) rather than side lines. Three sources: the competition itself (leaderboard and public notebooks), the
published literature on agent scaffolds, and our own v12b traces.

## 1. The leaderboard is mostly noise above about 0.17

- Main leaderboard on 25 Oct: 3,698 teams; 0.24 x4, 0.22 x37, 0.20 x178, 0.18 x491, 0.17 x612 (us), 0.15 x520.
- Public notebook evidence (dmitriigluzdov, "Public Agent Ideas and Evidence", catalogue of 187 notebooks): identical files
  of the 0.22-0.24 lineage (flexonafft's budget-aware bundle) solved 7, 7, 9, 11 and 13 of the 58 public tasks across five
  runs; the budget-fit reference solved 8 to 11 over seven runs, a mean of about 10 (0.17). Repeated runs of identical files
  differ by up to six tasks. Third-party numbers, not reproduced here.
- So 0.17 is the field's mean, not a deficit; the public top is the upper tail of many draws, and the private board will
  reshuffle it. Only a change in the mean helps, and a single hidden read cannot show a one- or two-task gain.

## 2. What the leaders run

One agent on the official starter prompt; 28 tool calls, an 8-minute cap, 240 s per command, 80 turns; temperature 0.2,
top-p 0.95, thinking budget 4,096, output 8,192; graph tools discouraged; prompt rules such as "edit by the 12th call". The
catalogue found no public notebook that wins with sub-agents, skills or adapters. Their 8-minute cap projects to 11.6-12.0 h
for 120 tasks on their own measurements, which is why it failed the 12-hour limit for us twice.

## 3. Literature (background survey, primary sources; links in the survey's working copy)

- Scaffold choice moves 20-40B open models by 7-16 points on SWE-bench (e.g. Qwen3-Coder-480B 69.6 in OpenHands vs 55.4 in
  mini-SWE-agent and 53.4 in SWE-agent; CWM-32B 53.9 own harness vs 37.6 mini-SWE-agent).
- No published method fits about 8,700 generated tokens per task; the strong numbers use 50-100+ turns, long context or
  best-of-k selection. Tree search, multi-agent reviewers, LLM history summaries and anti-repetition warnings do not transfer
  (SWE-smith: repetition warnings cut repeats but lowered the score, 40.2 -> 38.4).
- Failures concentrate before any edit: SWE-smith reports 53% of failures hit step or cost limits, often before any source
  file was edited; SWE-Effi finds failed runs use about 4.8x the tokens of solved ones.
- Top single changes the survey ranks for a fixed token budget: (1) gate the time on progress (stop runs with no edit, give
  editing runs longer; our eval_config cannot express this, a prompt rule can approximate it); (2) a one-call localization
  skill printing ranked files and class/def skeletons (SWE-agent summarized search 18.0 vs 12.0; AutoCodeRover 37k vs 245k
  tokens); (3) syntax-checked minimal edits (SWE-agent lint +3.0); (4) less thinking on navigation turns (not configurable
  per call in our config); (5) run existing tests before submitting rather than self-review.

## 4. Our own traces (v12b, 74 public tasks, A6000 paced to L4)

| First source edit | Solved |
|---|---|
| within 60 s | 12 of 16 |
| 60-120 s | 12 of 20 |
| 120-240 s | 4 of 16 |
| after 240 s | 0 of 5 |
| never | 0 of 17 |

By tool call: first edit by call 6 solved 14 of 17; calls 7-10, 6 of 15; 11-15, 6 of 13; after 15, 2 of 12. 21 of 74 runs
ended with an empty patch (28%, the same share third-party data shows over 692 runs). The 17 runs that never edited split
into long search/read loops (21-37 calls of grep and read_file) and short runs that spent 6,000-8,000 generated tokens on
thinking and reproduction scripts. Early editing is partly a sign of an easy task, so the table is not a causal estimate.

## 5. Decision

- sub26 = v12b_edit6: v12b plus one paragraph, "first source edit by the 6th tool call; no reproduction scripts before it;
  never stop without an edit". One variable; pre-registered in GAPS 'sub26 pre-registration'.
- Queued, each as its own single change after sub26 reads: the one-call localization skill; a py_compile check after edits.
- Distillation (teacher LoRA) stays gated on G1, waiting on the AWS GPU quota.
- A local paired read on the 205-task repo-disjoint EVAL set (data/distill) on 4x L4 is the right instrument for any change
  below about four tasks; it needs the AWS quota and the owner's go on its cost.
