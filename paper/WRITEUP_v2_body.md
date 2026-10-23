## Abstract

The Gemma 4 Developer Agent competition fixes the model, the tools and the scorer. Entrants control only an agent configuration: the prompt, the limits and the sampling settings. Most of us choose between configurations by running them on the 74 public tasks before spending one of our rare hidden submissions. We did this on two local setups, Kaggle's own four-L4 machines and a GPU paced to the same speed, and compared the hidden results of eleven configurations. Neither local screen ordered them. On the L4s, a change that beat its parent on 9 tasks and lost none scored lower on the hidden set. On the paced GPU, three configurations that each solved 28 locally scored 0.10, 0.10 and 0.17, the rank correlation between local and hidden scores was +0.49 (exact permutation p = 0.32, seven configurations), and a public configuration that scored 0.24 for its author failed the 12-hour limit twice for us. Three measurements explain much of this. Between 91 and 97 percent of each task's time is the model writing text, so the per-task cap is a token budget. Solves arrive late, so a longer cap buys local solves that the 12-hour limit cannot pay for. And rules that each fixed one task lost when merged. We wrote down how we would read every run before it ran, and we report the reads that went against us.

## 1. The setting

The model is Gemma 4 31B, quantised to 4 bits, with a 32k context. The scorer runs our agent once on each of about 120 hidden tasks, one task at a time, on four L4 GPUs. Each task is a real issue in a real Python repository, and the agent must edit the source so that hidden tests pass. The whole run must finish in 12 hours or it scores nothing. About 58 of the hidden tasks make up the public leaderboard, so one task moves the public score by about 0.017.

We cannot change the model, the tools, the scorer or the hardware. We can change what the model is told, how long it may work on each task, how many tool calls it may make, and how it samples. Every idea has to be paid for in the model's own time.

The public tasks come from four repositories. The hidden tasks come from private repositories that no entrant has seen. So the daily question is whether a change that helps on the public tasks also helps on the hidden ones.

## 2. How we measured

We used two local screens. Early on we ran configurations on Kaggle's own four-L4 machines, the scorer's hardware. Later we moved to a shared A6000 at a university lab with the same weights and serving stack. A small proxy holds every model reply on the A6000 until the time it would have taken on four L4s has passed, using a timing model we fitted to 6,730 model calls timed on Kaggle's L4s. So a five-minute cap buys the same amount of model work on both.

Every local screen ran all 74 public tasks, once each. We never judged a change on a subset.

We compared configurations in pairs, task by task: how many tasks only A solved, how many only B solved, and a sign test on those two counts. A difference in the totals means little unless the per-task flips agree.

To see how much a repeat moves, we ran two configurations twice each, unchanged, on the A6000, and we submitted some configurations to the hidden set twice.

Before each run we wrote down, in an append-only log, what result would make us ship, drop or retest the configuration. The log lives in git, so the order of rule and result can be checked from commit history. Results we only noticed afterwards are marked post hoc.

## 3. Results

### 3.1 How much a repeat moves

We ran two configurations twice each on the A6000, unchanged. They solved 31 and 29 of 74, and 27 and 29. Between the two runs, 4 and 6 tasks flipped, and because flips go both ways, the totals moved by only two each time. Only 13 and 4 of the 74 runs replayed step for step; the agent usually reached the same outcome by a different path. We had written down before the second repeat that more than 8 flips would widen our noise floor. It stayed at 6.

Four configurations that scored went to the hidden set twice (the first three post hoc, the last pre-registered). They came back 0.12 and 0.12, 0.08 and 0.08, 0.10 and 0.08, and 0.15 and 0.13, so zero to one task apart. That fits the local repeats: when a few tasks flip in each direction, two totals land close together. A small gap between two totals does not mean few tasks changed, and one hidden draw cannot show which tasks did.

### 3.2 Neither local screen ordered the hidden scores

On Kaggle's L4s, four configurations had both a full local screen and a hidden score on the same scorer version.

| configuration | local solves on 4xL4 (of 74) | hidden public score |
|---|---|---|
| staged locate, fix and verify agent | 27 | 0.05 |
| the same with a stdlib edit helper | 25 | 0.10, 0.08 |
| the same with a recovery step for failed helper calls | 34 | 0.08 |
| one agent with thinking on, five-minute cap (our baseline) | 32 | 0.15 |

The recovery step looked like a clean win. Against its parent it solved 9 more tasks and lost none (p = 0.004). On the hidden set it scored 0.08, against its parent's 0.10 and 0.08. We had written down before submitting it that anything between 5 and 7 hidden tasks would read as noise, and it got 5. The local best was the hidden third.

On the paced A6000, eight configurations had a full local screen.

| configuration | local solves (of 74) | hidden public score |
|---|---|---|
| our baseline (run twice locally, submitted twice) | 27, 29 | 0.15, 0.13 |
| baseline with a 1,024-token thinking budget | 28 | 0.10 |
| an earlier thinking-only variant | 26 | 0.10 |
| baseline plus two prompt rules (run twice locally) | 31, 29 | 0.13 |
| the public 0.24 notebook, unchanged, eight-minute cap | 31 | failed: 12-hour limit, twice |
| baseline with the notebook's sampling (temperature 0.2, no seed) | 28 | 0.17 |
| that, plus heredoc edits and 60 s commands | 28 | 0.10 |
| that, with a six-minute cap | 31 | 0.15 |

Three configurations solved exactly 28 locally and scored 0.10, 0.10 and 0.17, the lowest and highest hidden scores on this GPU. The two local leaders, at 31, scored 0.13 and 0.15. Over the seven configurations with scores, the rank correlation between local and hidden was +0.49, with an exact permutation p of 0.32: positive, but indistinguishable from no relation at this size.

This does not prove the local screen wrong and the hidden score right. A 0.05 gap on the public leaderboard is three tasks, and most configurations have one hidden draw. What the tables show is narrower: inside the band where our configurations live, neither local screen carried usable information about the hidden order, and that held on the scorer's own hardware as well as on the paced GPU. (The A6000 comparison is post hoc; the L4 reading was written down first.)

### 3.3 The time cap is a token budget (post hoc)

We split each task's wall time into model calls and everything else, from the traces of ten A6000 runs. The model's own generation took 91 to 97 percent; our earlier traces from Kaggle's L4s gave 91 to 93. Tools, the sandbox and the harness took the rest. A typical task made about 22 model calls and generated about 7,500 tokens.

At the 29 tokens a second we see during a task, a five-minute cap is a budget of about 8,700 generated tokens. Anything that makes the model write more spends it: longer thinking, a longer prompt to re-read, a wordier edit format. Faster tools would save almost nothing.

### 3.4 Solves arrive late (post hoc)

In our baseline, 41 of 74 tasks ran until the five-minute cap. Seven of its 27 solves ended in the last 30 seconds, and four were still running when the cap hit; the scorer grades whatever edit exists at that moment.

The public 0.24 prompt makes this much stronger. Given eight minutes, it solved 31 tasks locally, but only 19 of those ended before the five-minute mark. The same prompt on our tools did the same: 32 solves at eight minutes, 16 by five. A thorough prompt pays for its solves in minutes.

### 3.5 The 12-hour limit is per run

The public notebook averaged 346 seconds per task on our A6000. Over 120 tasks that is 11.5 hours, inside the limit on paper. Both of our hidden draws of it ran out of time and scored nothing. Its author's draw scored 0.24, so the same configuration can pass or fail. Our rule for that submission had not anticipated a failure at all.

The mechanism follows from 3.3 and 3.4. A configuration whose solves come late spends most of its cap on many tasks, and a hidden set with slower or harder tasks than the public one pushes the total past 12 hours. We replaced our "mean time" gate with a worst-case one: 120 tasks times the per-task cap must fit in 10 hours. Only five-minute configurations pass it. Later, by a deliberate amendment, we sent one six-minute configuration whose mean was 280 s per task; it finished inside the limit and scored 0.15. Its extra minute had added three local solves, four of the five tasks it gained ending after the five-minute mark, and none on the hidden set.

### 3.6 Fixes that worked one task at a time lost when merged

We tried a per-task approach: find a task the agent fails, write one prompt rule aimed at that failure, and keep the rule only if it solves its target in at least two of three tries. Two rules passed: one solved its target three times out of three, the other two out of two. Merged into one configuration, they lost 7 tasks net on the full 74 (gained 1, lost 8; p = 0.04). Each rule fixed its own task. Together they cost more elsewhere than they fixed, and only the full 74 showed it.

### 3.7 Moving toward the public best, one change at a time

Our baseline and the public 0.24 notebook differ in three ways: limits, sampling and prompt. We moved our baseline toward it one difference at a time, each a full local screen paired against the baseline.

| change to our baseline | local solves | net vs baseline |
|---|---|---|
| the notebook's limits (eight minutes, 28 calls) | 29 | +2 |
| the notebook's sampling (temperature 0.2) | 28 | +1 |
| the notebook's limits and its prompt | 32 | +5 (p = 0.18) |
| the notebook's prompt, restated for five minutes | 22 | -5 |

Our rule called a change real at a net of 3 or more. By that rule only the prompt passed (+5 with the limits against +2 for the limits alone), and only together with the eight minutes it was written for. Restated for five minutes, the same prompt lost 10 tasks against the eight-minute version (p = 0.006). Cutting the notebook itself from eight minutes to six lost 6 tasks (p = 0.07). The public prompt needs its eight minutes, and eight minutes fails our 12-hour gate.

The hidden set then ranked the same levers differently. The sampling change, neutral locally (+1), gave our best hidden score, 0.17. Adding heredoc edits and 60 s commands to it, neutral locally (28 against 28, three tasks gained and three lost), dropped the hidden score to 0.10.

### 3.8 A shared GPU can fake a result (post hoc)

One local run was invalid for a reason unrelated to the agent. Another process on the shared A6000 took GPU memory and the model server stalled for minutes at a time: 11 of 56 rows recorded zero model calls, which the scoring script read as an agent giving up. We stopped the run, lowered the server's memory share, and added a rule: a row with no model calls while the server answered nothing is an infrastructure loss, rerun separately, never a result.

## 4. What we changed

The local screen keeps two jobs. It is a validity check (crashes, errors, leaks into the patch, malformed edits, how many tasks hit the cap) and a floor (nothing ships below 28). It no longer ranks candidates. Hidden reads do that, one a day, so each one carries a single change with a stated mechanism, never a change chosen because it won a local screen by two.

We also repeat configurations on the hidden set on purpose. A second draw of the same thing tells us how far apart two hidden scores must be before they mean something.

## 5. Letting a model improve the harness

Google's Harness² refines an agent's harness task by task. An improver model reads the agent's trajectories, proposes edits, tests them in fresh runs, composes a final harness and stores a lesson for the next task. We ran it with Gemma as the fixed solver on eight held-out tasks from one repository, with Gemma itself as the improver first, which is Harness²'s default. The task list, the reading rules and the spending caps were committed before the first run.

Gemma did not change the harness. It kept the original in 22 of 24 stages, the final harness was the original on all eight tasks, and no lesson was stored. Reading its sessions shows why (post hoc): 23 of the 30 ran past Gemma's 32k context and were cut down by the coding agent that hosts them, after which they summarised the task and stopped. One ended by asking whether it should begin. Of the seven that fit, four replied with the bare words "keep base" and one edited the repository instead of the harness. The chosen runs solved two tasks against one for the unchanged harness, but both solutions came from the unchanged harness itself, so that gap is noise.

Two further phases were pre-registered and did not run: the same eight tasks with three frontier improvers that have no 32k limit, and a transfer test on 12 tasks from two repositories they never saw. The lab GPU was returned before the API key for the frontier improvers was in place.

## 6. Related work

Our setting follows SWE-bench (Jimenez et al., 2024): an issue and a repository in, a patch out, judged by the repository's tests. SWE-agent (Yang et al., 2024) showed that the interface between model and repository changes an agent's score, which is the premise of this competition. Agentless (Xia et al., 2024) showed that a fixed, cheap pipeline can compete with free-form agents, and SWE-Effi (Fan et al., 2025) scores agents against token and time budgets; section 3.3 is a budget result of the same kind.

Bjarnason et al. (2026) ran 60,000 SWE-bench Verified trajectories and found that a single run's pass@1 moves by 2.2 to 6.0 points depending on which run is picked, with spread even at temperature 0; they recommend several runs per task and a power analysis. Kapoor et al. (2024) argue for reporting cost with accuracy and for holdout sets that agents cannot overfit, and Zhu et al. (2025) show that benchmark flaws can badly misstate agent performance. On leaderboards, Blum and Hardt (2015) show how repeated public queries overfit a holdout, while Roelofs et al. (2019) found little such overfitting across more than 100 Kaggle competitions. Our disagreement between a local screen and a hidden set is a different problem, closer to the private-repository split of SWE-Bench Pro (Deng et al., 2025) and the fresh-task benchmarks SWE-bench-Live (Zhang et al., 2025) and SWE-rebench (Badertdinov et al., 2025).

For automatic harness improvement (section 5): Harness² (Xu et al., 2026), Meta-Harness (Lee et al., 2026), Self-Harness (Zhang et al., 2026), MESH-Harness (Shang et al., 2026), Agentic Harness Engineering (Lin et al., 2026), HarnessOpt-Bench (Ursekar et al., 2026) and the adaptation of harnesses for small models by Yang et al. (2026). Wang et al. (2026) find that harness evolution does not beat simple test-time scaling at matched budgets on Terminal-Bench and warn against evolving on the benchmark's own tests; our adapter keeps the improver away from the tests, which only grade after selection.

## 7. Limits

Everything here is about one fixed model, one harness family and the 74 public tasks. The hidden columns have one or two draws per configuration on about 58 tasks. The pacing proxy models the scorer's speed; it is not the scorer, which is why the L4 table matters. The scorer was rebuilt by the organisers in late September, and we compare hidden scores only within one scorer version. Claims 3.3, 3.4, 3.8, the hidden repeats in 3.1, the A6000 half of 3.2 and the session audit in 5 were noticed after the runs; the rest were read against rules written before the run.

## 8. Reproducing the numbers

Every configuration, per-task result, trace, the reading-rule log and the scripts are public at https://github.com/rodriguescarson/gemma-swe-agent (Apache-2.0), and one command regenerates every table here from the saved results. A longer version of this paper, with figures, a full method and threats to validity, is at https://github.com/rodriguescarson/gemma-swe-agent/blob/wip/gemma-agent/paper/arxiv/main.pdf.
