# Notebooks + leaderboard update: Gemma 4 Developer Agent (snapshot 2026-09-28 10:35 UTC / 16:05 IST)

Read-only. Nothing was posted, voted, submitted or pushed, and none of our kernels was touched. This note covers only
what is **new since the 2026-09-27 snapshots** in `research/forum.md` and `research/competitors.md`.
`NB3` = `/private/tmp/claude-501/-Users-carson-Projects/654244a3-b38c-45a0-96af-d7e5f0aac6ce/scratchpad/nb3`,
`NB2` = the 09-27 pull next to it. Every claim carries a path, URL or command. **UNVERIFIED** marks anything not
checked against source or data.

## 0. Bottom line

1. **The top of the board did not move.** Makus is still alone at 0.15 (9/58), with 2 submissions and none since
   09-26 13:58 UTC. The 0.13 tier grew from 7 teams to 12: three new one-submission teams, plus two that jumped from
   0.10. The 0.12 tier grew from 45 to 59. At least 10 of the top-30 teams submitted again after the 09-27 snapshot,
   and none of them got past 0.13. Nobody new at 0.13 has any public notebook or dataset. We are 0.12, rank 55
   (was 50). §2.
2. **The sub3 to sub4 drop (7 to 4 tasks) is inside measured run-to-run noise.**
   - zzgtylors published **three identical runs of the same agent** on 106 public tasks. They resolved 31, 28 and 33.
     Per task: 22 always solved, 20 sometimes, 64 never.
   - Their implied SD of the difference between two runs of one bundle is 3.4 pp. On 58 tasks that is about
     **2.5 to 2.7 tasks**, so our 3-task drop is about 1.1 SD (two-sided p ≈ 0.25). That agent ran at T 0.2. At our
     T 1.0 the noise is probably larger.
   - Rozen's byte-identical bundle has now scored 7, 5, 6 and 6 tasks for four different teams. §5.1.
3. **New lead on the malformed `edit_file` problem: thinking-ON traces show far fewer malformed arguments.**
   - In public competitor traces with thinking on, `edit_file` came back "mandatory input parameters are not present"
     in **1/25 calls (DCV)** and **70/497 (GraphLoc run 1)**.
   - Thinking-off runs show 23% (Shape of Doubt), and **52 to 67%** in ours.
   - The comparison is confounded by prompts, tasks and temperature. It fits vLLM #39043 ("tool calls leak with
     thinking off"), already cited in `pain_points.md:347`. It is worth a free local probe. §4.1, §6.2.
4. **Thinking on is still unaffordable as a global setting.** New evidence: `thinking_budget` is **not enforced**.
   - The direct-code-verifier run set `thinking_budget: 384`, and a single turn still produced **6,144 completion
     tokens in 170 s**, with no tool call.
   - Thinking-on turns average 316 to 376 completion tokens, against about 95 in our thinking-off runs.
   - That notebook resolved **1/16** in both arms, and 10/16 tasks ended with no patch at the 4.5 min cap. §3.2.
5. **The organisers changed three things** (found in passing; the forum sweep is a separate task):
   - **(a) LoRA:** "I applied a fix for LoRA loading yesterday", and training on gemma-4-31b's own outputs is allowed.
     Ryan Holbrook, forum 743964, 2026-09-28 10:32 UTC / 16:02 IST. This unblocks our SFT path, but only after a
     wipe-repro check.
   - **(b) Getting Started notebook:** it **no longer sets the vLLM server default `enable_thinking: True`**, and it
     now reads budgets from eval_config with defaults of 300 s / 100 calls / 60 min.
   - **(c) Overruns and parallelism:** a run over 12 h is still not scored as 0 ("Not yet"), and "we don't support
     parallel calls".
   - The wheelhouse (v25) and the competition data (09-25 18:40 UTC) are unchanged. §4.
6. **Why more tooling can score lower:** four independent public results point the same way.
   - More budget brought more loops and no extra solves (Black Cat).
   - A leaner agent that tied in the lab lost 3 tasks on the LB (Black Cat).
   - A better localizer made no difference over three runs: +0.9 pp, CI −4.1 to +6.3 (GraphLoc).
   - The public bundle family has a 3-task spread with no design change at all.
   - For v9 the most defensible reading is **noise plus T 1.0 variance**, not a proven helper regression. §5.
7. **Cheapest untried levers, ranked** (§6):
   1. A/B T 0.2 / top_k 40 against our T 1.0.
   2. Probe thinking on in the fixer only, with a hard output cap.
   3. Black Cat's anti-loop prompt kit.
   4. Cap `read_file` at 80 lines, and list tests before reading them.
   5. A `git restore -- tests/` guard before submit.
   6. A LoRA re-check now that the host says it is fixed.

## 1. Method and evidence

| What | Command / path | Result |
|---|---|---|
| Notebook list by run date | `kaggle kernels list --competition gemma-4-developer-agent --sort-by dateRun --page-size 100 --csv` → `NB3/_lists/date_p1.csv` (page 2 empty) | 64 notebooks (57 on 09-27) |
| Notebook list by votes | same with `--sort-by voteCount --page-size 50` → `NB3/_lists/votes_p1.csv` | every ref also appears in the date list |
| Run or updated since 09-27 00:00 UTC | diff against `NB2/_lists/date2141_p1.csv` | 15 refs (13 run since 00:00, 2 zzgtylors repeat runs newly public); all pulled |
| Also pulled (claim ≥ 0.12) | romanrozen, mizeroluckygall (Pathfinder) | both byte-identical text to NB2 (0 diff lines) |
| Sources | `kaggle kernels pull <ref> -p NB3/pull/<slug> -m`; flattened to `NB3/txt/<slug>.txt` by `NB3/flatten.py` | pull strips outputs, so outputs came from `kaggle kernels output` |
| Outputs (bundles, traces, cards) | `NB3/out/<slug>/` for direct-code-verifier, black-cat-pack-instinct, eval-errors, survival-kit; `NB3/out/graphloc-fa/` | 32 DCV traces, 10 gold-patch traces, GraphLoc `e2e_analysis.json` + `e2e_runs.csv` |
| Leaderboard | `kaggle competitions leaderboard gemma-4-developer-agent --download` → `NB3/_lists/lb/gemma-4-developer-agent-publicleaderboard-2026-09-28T10:35:50.csv`; `-s` view in `NB3/_lists/lb_show.txt` | 732 teams (606 on 09-27) |
| New 0.13 teams' public work | `kaggle kernels list --user`, `kaggle datasets list --user` → `NB3/_lists/new013_users.txt` | none for this competition |
| Org artifacts | `kaggle datasets files metric/gemma-4-developer-agent-wheelhouse` → `NB3/_lists/wh_files_now.csv`; `kaggle competitions files` (all 524, paged) → `NB3/_lists/comp_files.csv` | wheelhouse identical to v25 (41 files, 0 size diffs); newest data file 2026-09-25 18:40 UTC |
| Forum deltas (incidental) | `kaggle competitions topics list` p1-3 + `topics show <id> --format json` → `NB3/_lists/disc/t_<id>.json` | 45 topics (39 on 09-27); 6 new, 4 with new replies |
| Malformed-argument counts | `NB3/malformed.py` over competitor traces | §4.1 |

## 2. Leaderboard (2026-09-28 10:35 UTC) vs 0.15 / 0.13

Score = floor(100·k/58)/100 (`competitors.md` §2.1), so 0.15 = 9, 0.13 = 8, 0.12 = 7, 0.10 = 6, 0.06 = 4.
"Last sub" is each team's latest submission, not its best.

| # | team | user(s) | score | /58 | 09-27 16:11 (rank) | subs | last sub (UTC) |
|---|---|---|---|---|---|---|---|
| 1 | Makus | alexmartinez75 | 0.15 | 9 | 0.15 (#1) | 2 -> 2 | 2026-09-26 13:58 |
| 2 | Chandan Ranjan | chandanranjan | 0.13 | 8 | 0.13 (#2) | 2 -> 2 | 2026-09-26 14:51 |
| 3 | 暗黑AGI | boristown | 0.13 | 8 | 0.13 (#3) | 4 -> 5 | 2026-09-28 00:00 |
| 4 | Alperen ÖZ | alperenzfddg | 0.13 | 8 | 0.13 (#4) | 3 -> 5 | 2026-09-28 00:02 |
| 5 | Daniel Olajide | danielolajide | 0.13 | 8 | 0.13 (#5) | 3 -> 3 | 2026-09-27 00:25 |
| 6 | Jeki Wan Taufik | jek1wantaufik | 0.13 | 8 | 0.13 (#6) | 1 -> 1 | 2026-09-26 03:36 |
| 7 | Daniel Du | nghongnhn | 0.13 | 8 | 0.13 (#7) | 4 -> 4 | 2026-09-27 01:05 |
| 8 | I Zaznov | izaznov | 0.13 | 8 | 0.13 (#8) | 1 -> 1 | 2026-09-27 01:14 |
| 9 | Howon Kang | howonkang | 0.13 | 8 | new team | - -> 1 | 2026-09-27 08:02 |
| 10 | DoRA | iztanmaymohan | 0.13 | 8 | 0.10 (#61) | 3 -> 4 | 2026-09-27 08:05 |
| 11 | Pawan Bishnoi | pawan0912 | 0.13 | 8 | new team | - -> 1 | 2026-09-27 13:18 |
| 12 | Sukhendu Sain | ssain18 | 0.13 | 8 | 0.10 (#103) | 1 -> 2 | 2026-09-27 15:18 |
| 13 | Ingenhousz | ingenhousz | 0.13 | 8 | new team | - -> 1 | 2026-09-27 20:11 |
| 14 | Roman Rozen | romanrozen | 0.12 | 7 | 0.12 (#9) | 1 -> 1 | 2026-09-23 18:49 |
| 15 | daoviet | daoviet | 0.12 | 7 | 0.12 (#10) | 4 -> 4 | 2026-09-27 02:02 |
| 16 | Kawchar Husain | kawchar85 | 0.12 | 7 | 0.12 (#11) | 2 -> 2 | 2026-09-25 14:59 |
| 17 | Rahul Rathnavel K | rahulrathnavel | 0.12 | 7 | 0.12 (#12) | 3 -> 4 | 2026-09-27 20:13 |
| 18 | mahmoud al-ghraibeh | mahmoudalghraibeh | 0.12 | 7 | 0.12 (#13) | 4 -> 4 | 2026-09-27 00:06 |
| 19 | Mubin Shaikh | shaikhmubin | 0.12 | 7 | 0.12 (#14) | 4 -> 4 | 2026-09-27 00:13 |
| 20 | kwon yong deuk | kwonyongdeuk | 0.12 | 7 | 0.12 (#15) | 3 -> 4 | 2026-09-27 12:42 |
| 21 | Yuchen20 | yuchen2066 | 0.12 | 7 | 0.12 (#16) | 1 -> 1 | 2026-09-24 22:10 |
| 22 | Radek | rathko | 0.12 | 7 | 0.12 (#17) | 4 -> 5 | 2026-09-28 00:08 |
| 23 | Adarsh Varshney | adarshvarshney | 0.12 | 7 | 0.12 (#18) | 2 -> 3 | 2026-09-27 23:09 |
| 24 | Brian msw | brianmsw | 0.12 | 7 | 0.12 (#19) | 3 -> 4 | 2026-09-28 00:05 |
| 25 | Whisper Last | whisperlast | 0.12 | 7 | 0.12 (#20) | 3 -> 3 | 2026-09-26 00:53 |
| 26 | BokingChen | chenbaoying | 0.12 | 7 | 0.12 (#21) | 1 -> 1 | 2026-09-25 05:16 |
| 27 | Thomas | tommurakami | 0.12 | 7 | 0.12 (#22) | 3 -> 3 | 2026-09-27 01:30 |
| 28 | Chandram Dutta | chandramdutta | 0.12 | 7 | 0.12 (#23) | 2 -> 3 | 2026-09-27 08:30 |
| 29 | Leander Antony | leanderantony30 | 0.12 | 7 | 0.12 (#24) | 2 -> 3 | 2026-09-27 13:16 |
| 30 | Rapha | raphaabels | 0.12 | 7 | 0.12 (#25) | 2 -> 3 | 2026-09-27 17:26 |

Movements:
- **Distribution** (732 teams): 0.15 ×1, 0.13 ×12, 0.12 ×59, 0.10 ×93, 0.08 ×139, 0.06 ×142, 0.05 ×93, 0.03 ×31,
  0.01 ×43, 0.00 ×119. On 09-27 it was 1 / 7 / 45 / 67 / 104 / 106 / 86 / 32 / 39 / 119.
- **Ceiling:** 12 teams now sit at exactly 8/58 and one at 9. At least 10 top-30 teams made 12 more submissions since
  the last snapshot (subs column), and none reached 9. That fits `competitors.md` §2.3: outcomes are correlated because
  everyone solves the same easy tasks.
- **Mass jumps to 0.12**: 14 teams climbed to 0.12 overnight from 0.00 to 0.10. For example juliencst went 0.00 to 0.12
  (5 subs) and Harijs Ceriņš 0.05 to 0.12. That fits forks of the public Rozen/Pathfinder recipe plus noise
  (**UNVERIFIED** which bundle each used).
- **The new 0.13 teams publish nothing** for this competition: howonkang (3 unrelated "biohub" kernels), ssain18
  (2 kernels from 2025), iztanmaymohan, pawan0912, ingenhousz and alexmartinez75 ("Not found" / "No datasets found").
  Evidence: `NB3/_lists/new013_users.txt`.
- **Us**: rank 55, 0.12, 4 submissions (`kaggle competitions submissions`):
  - sub4 `56622442` (v9_eog) = **0.06**.
  - sub3 `56591871` (v4) = 0.12.
  - sub1 = 0.10.
  - **sub2 `56563379` is still COMPLETE with no score** at 10:35 UTC Monday. The host promised to rerun it Monday
    (forum 743683), and it has not happened yet.
- **Notebook authors on the board** (useful as calibration):
  - ahmadagbaria **0.10** with 1 submission at 19:46 UTC, 10 min after his notebook ran. That notebook is
    **byte-identical to Rozen's** (`cmp` on the two .ipynb files).
  - osama133: new at **0.12** (2 subs). His notebook is EDA only, so the bundle is unknown.
  - nihilisticneuralnet ("Gemminem"): still 0.10, now 4 subs.
  - lucifer19 ("Krizsó Gergely"): 0.10, 5 subs. The last sub was at 06:46 UTC, before Pack Instinct was built, so Pack
    Instinct is not yet scored.
  - leoprovorov 0.06, cocoyachi 0.05, bharat0 0.05, haideptry 0.00 (6 subs), tomaszszyrowski 0.00.
  - tharunkumar369 ("Top 1 Master Baseline") is **not on the LB**.

## 3. Notebooks run or updated since 2026-09-27 00:00 UTC

### 3.1 Summary table

| notebook (URL = kaggle.com/code/<ref>) | last run (UTC) | claimed / LB | architecture | eval_config | sampling / thinking | new? |
|---|---|---|---|---|---|---|
| tharunkumar369/gemma-4-developer-agent-top-1-master-baseline | 09-28 10:33 | claims "LB 0.12–0.15"; author not on LB | flipped from "flat single agent" (09-27) to coder + analyzer agent_tool | **90 s / 15 calls / 2 min** | T 0.2, top_k 40, 8192, thinking off | rewrite; claims unsupported (**UNVERIFIED**) |
| leoprovorov/gemma-4-the-complete-guide-expanded | 09-28 10:12 | LB 0.06 | official sample + "budget appendix" prompt | 60 s / 20 calls / 2 min / 100 turns | Getting Started sampling (thinking **on**, 16384) | rewrite; no outputs |
| bharat0/eval-errors-gemma-4-developer-agent | 09-28 05:57 | LB 0.05 | Evaluator patched to return the **gold patch** | n/a | n/a | new: gold patches 5/10 on public fastapi, subprocess sandbox |
| haideptry/gemma-develop-first-try | 09-28 02:04 | LB 0.00 (6 subs) | V12 coder + analyzer; V11 post-mortem | (V9 had 4 min / 35 / 60) | T 0.2, 8192, `include_thoughts: false` | new harness fact (snake_case skills) |
| osama133/gemma-4-dev-agent-task-anatomy-survival-kit | 09-28 00:00 | author LB 0.12 (bundle not shown) | EDA only | n/a | n/a | new EDA + queue notes |
| lucifer19/black-cat-swe-agent-pack-instinct | 09-27 23:31 | anchor 0.10; challenger pending | coder + read-only analyzer (agent_tool, `skip_summarization: true`) | **300 s / 100 / 8 min / 150** | coder T 0.2, top_k 40, 8192; analyzer T 0.1, 2048; thinking off | new: 209-run private lab, LB history |
| ryanholbrook/getting-started-gemma-4-developer-agent | 09-27 19:50 | host | sample | reads eval_config; defaults **300 s / 100 / 60 min** | T 0.2, 16384, thinking on; **server default `enable_thinking: True` removed** | host change, §4.2 |
| ahmadagbaria/gemma-4-baseline-reproduction | 09-27 19:36 | LB 0.10 | byte-identical to Rozen | none | T 0.2, 8192, thinking off | calibration point |
| nihilisticneuralnet/gemma-4-developer-agent-direct-code-verifier (DCV) | 09-27 17:37 | team 0.10 (4 subs) | single agent; "guard" arm has **no edit_file** (edits via `python3 - <<'PY'` with `count(old)==1`) | rapid 30 s / 32 / 4.5 min / 75; guard 30 s / 36 / 4.5 / 75 | T 0.05, **thinking on** with `thinking_budget` 384/512, out 6144/8192 | new traces, §3.2 |
| zzgtylors/graphloc-end-to-end-failure-analysis-resource (+ repeat-run-2, repeat-run-3) | 09-27 04:57 (runs 09-26) | no LB | sample prompt + all tools; skill arm adds BM25+PPR skill | 40 calls / 25 min / 60 turns / 120 s | T 0.2, thinking on (budget 4096, out 16384) | new: **3 identical runs**, failure taxonomy, §5.1 |
| tomaszszyrowski/gemma4-day1-baseline, cocoyachi/…zero-to-first-valid-submission, norikazuhaji/gtua-graph-tool-utility-audit | 09-27 12:24-14:39 | 0.00 / 0.05 / (none) | | | | unchanged since NB2 (0 diff lines) |

Compaction handling: every GPU notebook above that runs the Evaluator uses
`EventsCompactionConfig(compaction_interval=15, overlap_size=2, token_threshold=14336, event_retention_size=5)`
(host cell 10; DCV cell 12; leoprovorov cell 10; bharat0 cell 10). Nobody changed this. Black Cat is the only one that
prompts for it: "older tool outputs get summarized. After each important finding, write one line of plain text:
file:line, what it means, next step". It also notes that "the analyzer has no compaction of its own". That matches
our `harness_runtime.md:410`: AgentTool inner runners get no compaction.

Skills: none of the new bundles ships a skill except GraphLoc's `graph-localize` (unchanged). haideptry's V11 shipped
three snake_case skills and scored 0.00 (§4.3).

### 3.2 Direct Code Verifier (nihilisticneuralnet): hard evidence on thinking on
Evidence: `NB3/out/gemma-4-developer-agent-direct-code-verifier/experiment_card.json` (timestamp 2026-09-27 17:51 UTC),
32 traces under `results/*/traces/`.
- **Result:** 16 public tasks (fastapi 7, rich 6, requests 2, httpx 1), paired arms.
  - rapid **1/16**, guard **1/16**. Both solve only rich_3454.
  - 10/16 no-patch in each arm, mostly "Agent exceeded session timeout (4.5 min)".
  - Mean 257 s and 250 s per task. Selected: rapid.
- **thinking_budget is not enforced** (first hard evidence; previously only a forum claim, `forum.md:100`).
  - `trace_rich_3506` (rapid, `thinking_budget: 384`, `max_output_tokens: 6144`): 2 tool calls in 12 s, then **one turn
    of 6,144 completion tokens in 169.6 s** with no tool call. It hit the output cap and was followed by a
    `continuation_nudge`.
  - The guard arm on the same task: 6 calls in 17 s, then one turn of **6,631 tokens in 188 s**.
  - Completion tokens per turn: median 60 (rapid) and 96 (guard), p99 6,144 / 4,162.
  - Turns of 4,000 tokens or more are 1-2% of turns but **13-35% of all completion tokens**.
- **The guard arm (no `edit_file`, pathlib heredoc edits)** made 152 `run_command` calls with 0 malformed. It tied rapid,
  but under thinking on and a 4.5 min cap, so it says nothing about the edit channel with thinking off.
- **Loop seen:** `trace_fastapi_14605` (rapid) called `submit_patch` 41 times in a row after a successful submit, then
  died on "Agent exceeded turns budget (75 turns)". Its patch still went to verification (7,319 chars). This matches
  `harness_runtime.md:74`: submit only ends the task when followed by a text reply.

### 3.3 Black Cat "Pack Instinct" (lucifer19): LB history and lab
Evidence: `NB3/txt/black-cat-swe-agent-pack-instinct.txt` MD cells 0, 2, 4. Bundles:
`NB3/out/black-cat-swe-agent-pack-instinct/{submission,anchor_submission,fallback_submission}.zip`.
- **LB history, new**: First Strike (single agent, default budget) 0.06. Compact (single, 4 min / 24 calls) 0.08.
  Analyzer Challenger (coder + analyzer, 5 min / 40 calls) 0.10. **"Lab-Tuned Challenger (private): one lean agent,
  temperature 1.0, 100 calls → 0.06. It looked equal in the lab and lost about three tasks on the leaderboard."**
  Pack Instinct: pending.
- **Lab**: the official Evaluator on 4×L4 with scoring compaction, 209 runs, 19 tasks, 10 variants. "The outcome
  depended on the *task*, not the variant: three tasks passed in 32 of 33 runs and sixteen never did."
- **Smoke test on 19 tasks, anchor vs challenger**:

  | | anchor (5 min · 40 calls · 120 s) | challenger (8 min · 100 calls · 300 s) |
  |---|---|---|
  | resolved | 3/19 | 3/19 |
  | with a patch | 11 | 12 |
  | repeat loops (≥ 5×) | 9 | 13 |
  | crashes | 1 | 0 |
  | mean tool calls | 28 | 74 |
  | mean seconds | 158 | 258 |

- **Failure modes they measured** (thinking off, T 0.2):
  - (1) The same tool call is repeated 10 to 80 times. "`git grep` with no match exits with code 1 and returns an error
    with an empty message, which is a common trigger."
  - (2) One model call takes 1.5-2 s, so 40 calls last about 100 s, and the analyzer used 60% of them.
  - (3) Edit strings containing regex or backslashes came back "mandatory input parameters are not present".
  - (4) Reading one whole test file full of box-drawing characters added **about 18k tokens in one step**, then
    overflowed and discarded the patch.
  - (5) A requests test file took 73 s, so a 120 s `timeout_seconds` could fail a correct patch in verification.
- **Prompt rules we do not have** (the challenger's `prompts/system.md`, inside cell 5 `CHALLENGER`):
  - Search with `(git grep -n "text" -- '*.py' || echo "NO MATCHES") | head -20`.
  - "Empty output, NO MATCHES, or exit code 1 with an empty message … means the text does not exist. Do not retry it."
  - "If a tool reports missing mandatory parameters … Do not resend it: make a smaller edit whose strings avoid those
    characters at their edges."
  - "Always pass `start_line` and `end_line` … at most about 80 lines. Test files can be huge: list them first with
    `grep -n "def test_" …`."
  - "Git history stops at the base commit … Never search the history."
  - "Never use `python3 -c` for more than one statement."
  - Verify with `py_compile && pytest … -q -x -p no:anyio -o timeout=0 > /tmp/t1.log 2>&1; tail -n 25`.
  - "Use exactly the names and spelling the issue gives."
  - The analyzer gets `{problem_description?}`, at most 6 calls, and at most 200 words.
- Their claim "no eval_config = scorer defaults of 100 calls, 300 s, 60 min" agrees with `HARNESS_README.md:540-545`
  (already in `gap_5.md:21`). Nothing new there.

### 3.4 GraphLoc part 2 (zzgtylors): three repeat runs and a failure taxonomy
Evidence: `NB3/out/graphloc-fa/e2e_analysis.json`, `e2e_runs.csv`.
https://www.kaggle.com/code/zzgtylors/graphloc-end-to-end-failure-analysis-resource
- **Setup**: 106 public tasks whose gold patch passes in the subprocess sandbox. Two arms (base, +skill), each run 3
  times as identical notebook copies. Budget 40 calls / 25 min / 60 turns. Thinking on.
- **Resolved per run**: base 31 / 28 / 33, skill 30 / 30 / 35.
  - Per task (base): always 22, sometimes 20, never 64.
  - SD of one run: 2.44 pp (base) and 2.25 pp (skill).
  - SD between two runs: 3.44 pp and 3.18 pp; pooled 3.6 pp.
  - Skill minus base over all runs: **+0.9 pp, 95% CI −4.1 to +6.3**.
- **Where resolution is decided** (base, 318 runs):
  - Edits a gold function: resolved 82/143 (57%). Anything else: 10/175 (6%).
  - When a gold function was edited but the task failed: "target tests fail" 43, "only other tests fail" 13, other 5.
    So about 21-30% of these near-misses are **regressions in other tests**.
  - No patch: 67 runs, 47 of them from the time budget.
  - The agent ran tests itself in 17% of runs (resolved 28% vs 29% without).
  - It edited test files in 15-17% of runs.
- **Skill arm**:
  - The skill's top-15 list contains a gold function in 68% of tasks (top-5: 51%).
  - When the list has one, the agent edits a gold function 53% of the time, against 24% when it does not.
  - Even so, end-to-end resolution does not move.

### 3.5 Smaller items
- **haideptry V11 post-mortem** (`NB3/txt/gemma-develop-first-try.txt` cell 0): snake_case skill names
  (`smart_repo_map`, `patch_guard`, `locate_issue`) raise `SubmissionValidationError` on 100% of tasks, which is why
  V11 scored 0.00.
  - **Verified** in our ADK copy: `google/adk/skills/models.py:32,87-96` allows kebab-case only unless
    `SNAKE_CASE_SKILL_NAME` is on, and `google/adk/features/_feature_registry.py:176-178` sets it `default_on=False`.
  - Ours is `swe-tools` (`submissions/v9_eog/skills/swe-tools/SKILL.md`), so we are safe.
- **bharat0 gold-patch run** (09-28 05:57 UTC, log `NB3/out/eval-errors-gemma-4-developer-agent/*.log`): the Evaluator
  was patched to return the gold patch. 5 of the first 10 fastapi tasks resolve. The other 5 (15030, 14962, 14964,
  15023, 14978) exit 2 in the subprocess sandbox. The public path is still broken as of Monday (cf. `forum.md` §1.8).
- **osama133 survival kit** (cells 25, 28, 31, 42):
  - In 76% of public tasks the issue names neither the changed file nor the changed function.
  - No public task ships `hints_text`.
  - Issue length vs fix size has Spearman ρ = 0.07.
  - 21/129 fixes (16%) touch `async def`, which the graph tools cannot see.
  - Queue: at most **2 queued/running batch GPU sessions**. "Saving a new version while an older one is still queued
    can cancel the queued one."
- **tharunkumar369**: the text now recommends **15 calls / 2 min**, which contradicts every scored data point
  (Pathfinder's 4-min cap cost 0.12 to 0.08). The 09-27 version claimed the opposite architecture.
  Treat it as unreliable.

## 4. New harness and org facts

### 4.1 Malformed tool arguments by thinking mode (cross-team traces)
Script `NB3/malformed.py`. "Malformed" = the observation contains "mandatory input parameters are not present". The
GraphLoc numbers cover run 1 only (traces in `NB2/out/graphloc-end-to-end-gemma-4-agent-skill/e2e/results/`).
Our rows come from `competitors.md` §7.1.

| source | thinking | temperature | edit_file calls | malformed | rate | run_command malformed |
|---|---|---|---|---|---|---|
| DCV rapid | on | 0.05 | 25 | 1 | **4%** | 0/113 |
| GraphLoc base run 1 | on | 0.2 | 246 | 52 | **21%** | 0/1193 |
| GraphLoc skill run 1 | on | 0.2 | 251 | 18 | **7%** | 0/940 |
| Shape of Doubt sampling screen (09-26) | off (max 878 completion tokens) | per candidate (**UNVERIFIED** which) | 143 | 33 | 23% | 0/303 |
| ours, race1 total | off | 1.0 (0.5 in sw1_v1) | 5278 | 3535 | **67%** | 125/4977 (2.5%) |
| ours, Kaggle L4 e74_v3 | off | 1.0 | 698 | 360 | **52%** | |

Reading:
- Thinking-on sets are at 4-21%, and ours at 52-67%. Shape of Doubt (thinking off) sits between.
- Confounders: different prompts, task mixes and temperatures, and GraphLoc's runs used 12 concurrent workers.
- So this is a **lead, not a result**. It fits vLLM #39043 ("tool calls leak with thinking off" on 0.19.1rc1,
  `pain_points.md:347`).
- Even DCV's regex-heavy rich_3454 edit (`r"(?P<number>(?<!\w)\-?[0-9]+…`) parsed fine with thinking on, while our
  §7.1 failures cluster on exactly such strings.
- Cost side: thinking-on turns average **316-376 completion tokens** (GraphLoc, DCV), against about **95** in our
  r_v9_eog (252,393 over 2,667 turns). At about 34 tok/s single-stream that is roughly **+7 s per turn**, plus the
  rare 6k-token runaway (§3.2).

### 4.2 Getting Started notebook changed (host, re-run 2026-09-27 19:50 UTC / 2026-09-28 01:20 IST)
`diff NB2/txt/getting-started-gemma-4-developer-agent.txt NB3/txt/getting-started-gemma-4-developer-agent.txt`:
- **Removed** `default_chat_template_kwargs={'enable_thinking': True}` from `VllmConfig` (old cell 7, line 182).
  - Consequence if the scorer mirrors the notebook (**UNVERIFIED**): a bundle that sets **no** `include_thoughts` and no
    recognised `thinking_level` no longer gets thinking on by default. `adk_submission/resolvers/generation.py:92-107`
    only sends `enable_thinking` when one of those is set; otherwise the request carries no flag.
  - Row 2 of `config_space.md` ("a typo silently leaves thinking ON") may no longer hold.
  - **Ours is unaffected**: every LlmAgent sets `include_thoughts: false` explicitly (`submissions/v10/configs/gen_*.yaml`).
- Budgets are now read from `eval_config.yaml` with defaults `timeout_seconds 300`, `max_tool_calls 100`,
  `max_time_minutes 60.0`. The hard-coded `100` / `5.0` and the markdown sentence "The only enforced constraint … is a
  12 hour inference runtime" are gone. The defaults match `swegemma/budget.py:18,29` (60 min, 300 s) and README
  540-545.
- Compaction (`interval 15, overlap 2, threshold 14336, retention 5`) and `max_model_len 32768` are unchanged.

### 4.3 Org and forum deltas since 2026-09-27 16:15 UTC (incidental; the full forum sweep is a separate task)
- **743964, Ryan Holbrook, 2026-09-28 10:32 UTC / 16:02 IST** (https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743964):
  - "12h overrun: **Not yet.** Budget per task using eval_config.yaml." So an overrun still errors the whole run.
  - "Parallel: I we don't support parallel calls." That rules out ParallelAgent best-of-N concurrency. Whether a
    ParallelAgent still runs sequentially is **UNVERIFIED**.
  - "LoRA: **I applied a fix for LoRA loading yesterday.** You can see the limits on rank and size in the getting
    started notebook and also in the HARNESS_README.md. There's also a total submission limit of 3GB."
  - "Training data: **Training on gemma-4-31b itself is fine.** We'll try to have an answer for outputs from other
    models soon."
  - Linking the fix to the 09-27 vLLM wheel change (+62 B, `forum.md:22-27`) is my inference (**UNVERIFIED**). No
    public score with an adapter exists yet.
- **743973** (09-28 04:02 UTC), JohnParkerson [08:41 UTC]: 12 **public** tasks are unresolvable on Python 3.13
  (**UNVERIFIED** by us):
  - requests 6589, 6592, 6629, 6757, 7328, 7433, 7502, 7505: `VERIFY_X509_STRICT` vs the pytest-httpbin cert.
  - fastapi_14186, fastapi_15745, rich_3486: `@needs_py_lt_314` tuple-compare skips.
  - rich_3472: `__qualname__` drift in the error string.
  - The Docker sandbox is 3.13.15 (`gap_1.md:82`). If true, drop these from local arenas. The hidden set was reviewed
    for feasibility (`forum.md` §1.4).
- **743683**: participants report scoring taking "approximately 12 hours" and "timeout after 14 hours". GPU quota is
  charged for queue time as well ("showing 2x the notebook runtime"). No host reply since 09-26.
- **742807** (distillation): still no ruling. See 743964 above.
- **Wheelhouse**: v25 (2026-09-27 11:49 UTC) is still current. All 41 files have the same sizes as `forum5/wh_v25_files.json`.
  **Competition data**: newest file 2026-09-25 18:40 UTC (all 524 listed files).
- New topic 744029 (09-28 10:23 UTC): "swegemma 0.2.7: unpacked-wheel cache ignores the wheel set, so added wheels have
  no effect locally". The body was not in the API response; relevant only to local wheel experiments.

## 5. Why more tooling can score LOWER on the scorer

### 5.1 First, the drop may not be real
- **Same bundle, different teams**: Rozen 0.12 (7), Geremie Yeo fork 0.08 (5), msama01 clone 0.10 (6), ahmadagbaria
  clone 0.10 (6; the notebook is byte-identical to Rozen's, and linking it to his LB entry is timing-based,
  **UNVERIFIED**). Range 5-7, mean 6.
- **Same agent, three runs** (GraphLoc, §3.4): 28-33 of 106. Scaling its per-task Bernoulli variance to 58 tasks gives:
  - SD of one run's count ≈ 1.8-1.9 tasks.
  - SD of the difference between two runs ≈ **2.5-2.7 tasks**.
  - Our sub3 → sub4 difference (7 → 4) is about 1.1-1.2 SD, two-sided p ≈ 0.25.
  - That agent ran at T 0.2. At our T 1.0, more tasks fall in "sometimes", so the noise band is probably wider.
- **Conclusion**: one LB pair cannot separate v4 from v9_eog. The hypothesis "helpers hurt on the scorer" is
  **not established**.

### 5.2 Mechanisms with public evidence
1. **More budget means more loops, not more solves.** Black Cat's challenger roughly tripled mean tool calls
   (28 → 74) and raised mean time from 158 s to 258 s. Loops went from 9/19 to 13/19, and resolved stayed at 3/19.
   v9_eog's extra helpers (`replace.py`, `run.py`, `gate.py`) add calls and outputs in the same way.
2. **Lab parity does not transfer.** Black Cat's lean T 1.0 variant tied in a 209-run lab and lost about 3 tasks on the
   LB. Earlier, busyaprime's 34/119 locally became 4/58. Our race1 favoured v9_eog (21/51 against r_v4's 18/51), but
   `competitors.md` §7.2 already showed r_v4's helpers failing 86/93 on the subprocess sandbox. That race compared
   against a crippled v4.
3. **Better tools do not change what gets fixed.** GraphLoc's skill found the gold function in its top 15 in 68% of
   tasks and changed nothing end to end over three runs (+0.9 pp, CI −4.1 to +6.3). Resolution is decided at "edits a
   gold function" (57% vs 6%), and after that by semantics (43 target-test failures) and regressions (13).
4. **Large tool outputs are the crash path.** One whole-file read added about 18k tokens in one step (Black Cat), and
   any exception other than a timeout discards the patch (`competitors.md` §5.2). Helper output that is long
   (test logs, locate listings) pushes prompts past the 14,336 compaction line on the scorer. Our own measurement puts
   compaction's cost at about 7 s per event and roughly ±2-3 tasks per 60 (`gap_4.md:22-23`). This mechanism is real
   but small in our data.
5. **Test runs cost more on the scorer than on our pod** (**UNVERIFIED** for the hidden repos). Docker gives 2 vCPU /
   4 GiB. Black Cat saw a 73 s requests test file. With `max_time_minutes 5`, a `gate.py` or `run.py` test pass is a
   larger share of the task than on the pod. GraphLoc's agents that ran tests did no better in the base arm
   (28% vs 29%).
6. **T 1.0 is the odd one out.** Every public bundle at 0.12 or above uses T 0.2 / top_k 40. Both known T 1.0 entries
   other than ours scored low (Black Cat lean 0.06; Shape of Doubt 0.08). Our T 1.0 results are 0.12 (v4) and
   0.06 (v9_eog). Temperature has never been isolated by anyone.

## 6. Techniques we have not tried (ranked by value per cost)

1. **T 0.2 / top_k 40 on the locator and fixer.**
   - Why: this is the field consensus for every score of 0.12 or more (§5.2.6), and it should cut run-to-run variance.
   - Our v4, v9 and v10 all run T 1.0 / top_k 64 (`submissions/*/configs/*.yaml`).
   - How: paired local arena first, with compaction on, then one LB slot.
2. **Thinking on for the fixer stage only, as a free local probe of the malformed-edit rate.**
   - Why: §4.1 shows 4-21% malformed with thinking on against 52-67% for us.
   - Config route: `thinking_config: {thinking_level: MINIMAL}` with no `include_thoughts`. That maps to
     `enable_thinking: true` without `reasoning_effort` (`config_space.md:118`). Whether thoughts are then kept in the
     history is **UNVERIFIED**.
   - Hard cap: `max_output_tokens` at about 1536 on that stage, because `thinking_budget` is ignored (§3.2).
   - Measure: malformed rate, seconds per task and solves, paired, on the same tasks. Do not spend an LB slot until the
     probe shows the malformed rate falling without the 5-min cap eating the gain.
3. **Black Cat's anti-loop prompt kit** (§3.3), all zero-cost:
   - The `|| echo "NO MATCHES"` search idiom. Today we only have it inside `locate.py`, not in the prompts.
   - "Do not resend a malformed call; shrink the edit edges."
   - "Never search git log for the fix."
   - "No multi-statement `python3 -c`."
   - We already say "never repeat a call" (`submissions/v9_eog/prompts/fixer.md:9`).
4. **Force `read_file` ranges of at most 80 lines, and list tests (`grep -n "def test_"`) before reading them.** This
   removes the one-step 18k-token jump that compaction cannot stop (`gap_4.md:23`, guard (a)).
5. **A pre-submit test guard**: `git restore -- tests/ 2>/dev/null || true`, then `git status --short` cleanup (DCV guard
   prompt). Agents edit tests in 15-17% of runs (GraphLoc), and test edits have broken `test_patch` application for
   us 4 times (`forum.md:170`).
6. **A regression check on the touched module's existing tests before submit.** "Only other tests fail" is 21-30% of
   GraphLoc's gold-function near-misses (§3.4). Our `gate.py` does this already, so the change is to keep it cheap
   (one pytest call, `-x`, `tail -25`) rather than to remove it.
7. **Re-open LoRA** (host fix 09-27; self-generated training data allowed). First run Whisper Last's wipe repro
   (random `lora_B`, base vs adapter logprobs at T=0) on the current wheelhouse. That needs a GPU session and a 433 MB
   wheel, so it needs Carson's go-ahead. Our 314-row SFT set exists (`competitors.md` §6.10).
8. **No-`edit_file` surface** (DCV guard: `run_command` + pathlib with `count(old)==1`). It is already our §6.1 idea in
   `competitors.md`; now there is a public prompt to borrow. It is untested under thinking off. Try it only if item 2
   fails.

Dropped by today's evidence:
- ParallelAgent best-of-N (the host says no parallel calls).
- Short hard caps under 4 min (tharunkumar's 2 min contradicts Pathfinder).
- Global thinking on (runaway turns, §3.2).

## 7. Open / UNVERIFIED
- Whether the scorer's vLLM server also dropped the `enable_thinking: True` default (§4.2).
- Whether the 09-27 LoRA fix actually stops the `lora_B` wipe (§4.3).
- The mechanism behind the lower malformed rate with thinking on (§4.1): the model's formatting under the reasoning
  parser, or confounders.
- Which bundles the new 0.13 teams used (no public trace).
- Whether ahmadagbaria's and osama133's LB entries came from their notebooks.
- sub2 rerun: promised for Monday, not scored as of 2026-09-28 10:35 UTC.
