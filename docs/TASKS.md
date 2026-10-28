# Gemma 4 Developer Agent: task list and experiment plan

Living list, updated 2026-10-29 IST. Goal: more hidden tasks solved under the scorer's 5-minute cap, with changes we can
actually show are better. Every experiment gets its own pre-registration in `docs/GAPS_2026-10-06.md` before any row exists;
this file only orders the work.

## Now

- [ ] **sub27 = v12b_ctx** (context rules against compaction): chain `eval/arm_sub27_ctx.sh`, log `eval/arm_sub27_ctx.out`.
  Scores about 19 h after it lands. Bands (GAPS "sub27 pre-registration"): 0.19+ candidate for final pick 1, 0.15-0.18
  neutral, 0.14 or less dropped.
- [ ] **v12b_ctx on all 74 public tasks, Kaggle 4x L4**, after the weekly GPU quota resets and no submission is scoring
  (`scripts/ship.sh submissions/v12b_ctx g4-l4-v12b-ctx-p312 eval --ids data/kaggle_valid_ids.txt --pin original --kernel-id g4-eval74-v3`,
  then `KAGGLE_BIN=.venv/bin/kaggle bash scripts/kaggle_push_wait.sh g4-l4-v12b-ctx-p312`).
- [ ] **Final picks**: two, by hand, before 3 Dec 05:29 IST (merger cutoff 25 Nov). Pick 1 is v12b (0.17) until a candidate
  beats it by its rule.
- [ ] **Paper track**: writeup editable until 13 Nov 05:29 IST; the compaction mechanism and the run audit are new material.

## What limits the score (our data)

Sources: `eval/analysis/run_audit.py` (2,442 agent runs, 33 configs, table in `eval/analysis/out/run_audit.md`) and
`eval/analysis/compaction_l4.py`.

1. **Time.** Decoding is 77% of wall time (28 ms per output token); thinking-on calls average about 260 output tokens, so a
   task holds about 22 calls. 44% of thinking-on runs (615 of 1,406) hit the 5-minute cap and none solved (the grader did
   test their patches, so these were failing anyway).
2. **Fix quality.** The model's own last check is a weak signal: passed 61% solved, no check after the last edit 52%,
   failed 43% (740 runs). Earlier taxonomy: right file, wrong fix is the largest failure class (32%).
3. **No edit.** 205 of 740 thinking-on runs (28%) never made a successful edit; 3% of them solved.
4. **Context.** 39-42 of 74 runs compact; the summary keeps only reasoning text, dropping every tool output and the task.
5. **Measurement.** Local screens have never ordered hidden scores; one hidden read resolves about one task (0.017);
   27 of 74 public tasks were never solved by any run, 22 are contested. Capacity is about 15 h of 4x L4 a week (30 quota
   hours, counted double) and one submission a day.

## How the pasted advice maps onto our scorer

The framework fits (one variable, a baseline, paired comparison, a decision rule set before the run; screen, validation and
full sets; observability first). Several levers do not exist for a submission, which can change only the prompt,
agent.yaml (tools, sub-agents), sampling, the budget and optional skills or a LoRA:

| Advice | Here |
|---|---|
| Low reasoning for routine calls, high for hard ones | Not per call. Possible per sub-agent: each agent in a SequentialAgent has its own thinking budget (E-T3). |
| Execution-first prompt, fewer calls | v12b already plans 12 calls. Shorter thinking read 0.10 (sub15b) and edit-early 0.13 (sub26) on hidden, so this needs a measured test, not a rewrite. |
| Parallel attempts, plan cache across tasks | No: the scorer serves no parallel calls (thread 743964) and every task starts a fresh session. A fixed playbook in the prompt is the only cache. |
| Truncation markers, tool changes, structured compaction | The tools and the compaction are the scorer's. Only the prompt can work around them (v12b_ctx does). |
| LangGraph, smolagents, Deep Agents, OpenHands | Cannot run in the scorer; only ideas transfer (100-line read windows from SWE-agent, keeping the task message as OpenHands' condenser does, bash-first minimalism). |
| Compare latest models | Gemma 4 12B is allowed since 13 Oct and never tested by us (E-T1). |

## Plan by area

Status: [ ] open, [~] running, [x] done. Cost is in 4x L4 wall hours (quota hours are double) or submission slots.

### 1. Evaluation (first, because it decides everything else)

Budget rule: slots are plentiful (one a day, about 35 left) and 4x L4 hours are scarce (about 15 a week). Large effects
(a model swap) go straight to a hidden read; small effects (prompt rules) need paired L4 runs, because one hidden read
resolves about one task.

- [ ] **V1 AWS GPU quota.** The G-instance quota requests have sat at CASE_OPENED since 24 Oct (0 vCPU). One reply on the
  support case is the owner's to send. If granted, a g6.12xlarge (4x L4, the scorer's hardware, $4.60/h, about $23 per
  74-task run, from the $1,100 credits) removes the weekly cap on faithful runs.
- [ ] **V2 Grow the benchmark.** The competition's task file has 129 tasks; our kernel graded the 55 new ones 0/55. Run the
  gold-patch oracle on all 129 in a CPU kernel (no GPU quota). Gradable new tasks become the validation set: no config
  was ever tuned on them.
- [ ] **V3 Validate the 32-task screen out of sample** (`data/screen32_ids.txt`: 22 contested + 10 rare). On the next two
  full runs, check that the flips still fall inside the 32; until then it screens, it never gates.
- [ ] **V4 Decision rule.** Paired sign test on discordant tasks (the existing `scripts/a6000/p2_report.py`), a candidate
  adopted only if it wins on the screen, holds on the full 74, and its hidden read is not below its band.

### 2. Observability (no GPU)

- [x] **O1 Compaction log**: `scripts/run_eval.py` writes `compactions.jsonl` (events in, characters seen, summary text) for
  every local run; tested in `tests/test_v12b_ctx_flow.py`.
- [x] **O2 Run audit**: `eval/analysis/run_audit.py` counts timeouts, empty patches, compactions, unranged reads, truncated
  outputs, edit misses, parser rejections, swallowed tool calls, nudges, test-file edits, command timeouts, budget-outs.
- [ ] **O3 Gate counters**: the L4 gate reports the run_audit counters next to crash rows and flags any that rise against
  the base config.
- [ ] **O4 Failure classes per run**: extend run_audit with the outcome class (timeout, wrong fix in the right file, wrong
  file, no edit, tool failure, context loss after compaction, scorer issue) using the known fix files.
- [ ] **O5 Step viewer**: render a trace step by step with adk_eval_core's viewer for the runs a counter flags.

### 3. Performance (the time bottleneck)

- [ ] **E-T1 Gemma 4 12B**: demoted. Thread 750974 ran the same files on 31 tasks: 31B 9-11 solved, 12B 4, E4B 0, and
  the 12B at an 8-minute cap broke the 12-hour limit. Not worth a slot unless new evidence appears.
- [ ] **E-T2 Lean-run prompt**: fewer calls without less thinking (one search, one ranged read, edit, one check). Only
  after sub27 reads, since v12b_ctx already moves reads and output.
- [ ] **E-T3 Thinking budget per stage**: SequentialAgent of a navigator (budget 1,024, read and search tools, ends by
  naming file and lines) and a fixer (4,096, all tools). Risk: our earlier multi-stage bundles read 0.06-0.08 on hidden.

### 4. Context (running)

- [~] **E-C1 v12b_ctx** (sub27): ranged reads of at most 80 lines, trimmed output, the edit plan in the reasoning, the issue
  pinned in the system instruction.
- [ ] **E-C2 Read what the summaries keep** (O1 on a local run of compaction-heavy tasks) before any further context rule.

### 5. Fix quality

- [ ] **E-Q1 Close the check gap**: 269 of 740 runs edited and never checked afterwards. A rule that the last call before
  submit_patch is a check of the edited code, and a failed check gets one fix. Evidence: passed 61% vs none 52%.
- [x] **E-Q2 The 27 never-solved tasks, task by task** (29 Oct; four reviewers replayed every distinct agent patch and the
  gold patch against the hidden tests on scratch copies and searched the repository at base, its docs and git history).
  - **Infeasible, 13**: the hidden test pins a name, message or design no source gives. fastapi_14258 (exact message),
    14306 (`endpoint_ctx` kwarg and `Endpoint:` label), 14479 (the issue quotes a different message than the test), 14487
    (two exact labels), 15280 (April-fool `vibe` raising a fixed sentence), 15661 (a new release script's whole API),
    15800 (private names and six docs files); rich_3061 (`extend_style` absent everywhere), 3105 (issue is "Fix #3104",
    offline), 3930 (new module and version tables), 3938 (`Segment.split_lines_terminator`), 3942 (a markdown restyle),
    3944 (private-use code points, title "fix fonts").
  - **Agent failure, 6**: fastapi_13920 (alias from `typing_extensions` never tried through TestClient), 14448 (28-route
    cross product; 14 patches reach 24/28), 14986 (36 patches delete a documented feature that existing tests pin);
    rich_3052 (returns the typed value; the sibling test asserts the declared choice), 3782 (2-line fix in `_get_syntax`;
    two correct patches exist but were graded under a different Pygments), 3935 (fix is in table.py; all 25 patches
    edited padding.py).
  - **Partly feasible, 8**: fastapi_15588 (behaviour right in 30 of 36 patches, only the message is unknowable); rich_3468,
    3472, 3535, 3934, 3953, 4006, 4076 (location or behaviour inferable, one element needs a guess).
  - **Repeated mistakes behind the 14 that are not infeasible** (candidate rules, see E-Q3): checks that already pass before
    the edit (a test that is green on the old code proves nothing); reverting or dismissing a fix because an old test that
    encodes the old behaviour goes red; editing the first plausible site without listing every consumer of the option or
    function; repro scripts with no `timeout` (16 of 39 runs on rich_4006 lost 180 s); identical commands repeated.
  - **Eval-fidelity defects found on the way**: the box sandbox had network (a rich_3105 run fetched the issue), and
    rich_3782's correct patches failed on the box's Pygments 2.21 against the scorer's 2.20.
- [ ] **E-Q3 Verification discipline, one prompt change**: before editing, make a check that fails on the current code
  (clone the nearest existing test with only the issue's change, or one script crossing the dimensions the issue lists);
  after editing, run the touched module's existing test file, keep a fix whose only red tests encode the old behaviour the
  issue changes, fix anything else; `timeout 10` on every repro. Evidence: the 6 agent failures above plus the solved vs
  failed contrast on the 32 screen tasks (workflow running).

### 6. Models and research

From the online scan (29 Oct, about 60 forum threads, public notebooks, papers; nothing found beats noise):
- **Final picks: the private score is the better of the two finals** (thread 752220). Two decorrelated 31B finals add
  about 0.56 of a run's spread (about two tasks, +0.02) at no slot cost, but that gives up an E4B pick (decision R2).
- **12-hour cliff**: breaching it fails the whole submission (752017), and scorer speed varies run to run (753058: a
  byte-identical zip scored, then timed out at about 25 h). Keep worst-case runtime well under 12 h.
- **Parser prevention** (746336, 747168): vLLM 0.19.1's gemma4 parser mishandles plain-quoted strings and hangs on a `]`
  inside a plain-quoted array (fixed in 0.21, scorer pins 0.19.1). One edit_file example written with Gemma's string
  delimiters could prevent garbles, where v12b_garble only tried to recover from them.
- **No visible text beside a tool call** (744844, scorer's June template closes the turn): small expected gain, no risk.
- **Thinking budget 2,048** (746250: 50 vs 48 of 129); our 1,024 read 0.10 against 0.15, so only with an L4 run first.
- **Better dev sets**: FreshSWE-Py and OOD-45 (750573) are out-of-repo task sets closer to the hidden repos than the 74.
- **Papers** on pruning stale observations (AgentDiet 2509.23586, ACON 2510.00615, SWE-Pruner 2601.16746) need harness
  control we do not have; their prompt-level form is what v12b_ctx tries. Overthinking lowers SWE-bench resolve
  (2502.08235).
- **LoRA**: every public report since 20 Oct is flat or negative against the base (751596, 750713). Stays dropped.

- [~] **R1 Online scan**: forum since 18 Oct, public notebooks, 2025-2026 papers on efficient small-model agents, context
  pruning, verification; Gemma 4 and vLLM news.
- [ ] **R2 Small-model bonus ($10k, E2B or E4B, must be one of the two finals)**: our E4B entry reads 0.08, level with the
  small-model board on 22 Oct. Thread 753277 reports a training-free one-tensor fix for E4B's copying bug (copy test: the
  unmodified model failed 15 of 18 inputs, the fixed one 1). Parked by the owner on 28 Oct; a decision for the final picks.

## Calendar (5 weeks)

| Week | Faithful runs (about 15 h of 4x L4) | Slots |
|---|---|---|
| 29 Oct - 1 Nov | V2 oracle (CPU); quota nearly spent | sub27 v12b_ctx |
| 2 - 8 Nov | v12b_ctx full 74 (mechanism); E-T1 probe + screen | E-T1 if its screen passes |
| 9 - 15 Nov | the week-1 winner on the full 74; E-Q1 screen | paper v3 by 13 Nov |
| 16 - 22 Nov | confirmations; E-T3 only if time is still the main loss | 1-2 reads of the leader |
| 23 - 30 Nov | no new mechanisms; repeat reads of the two final candidates | finals chosen by 30 Nov |

## Dropped lines (pruned, with the reason)

- Distillation from teachers: G1 failed (Devstral 10/30 usable, 1 new solve); stopped by its rule.
- LoRA on our own trajectories: v11a/v11b and think adapters lost to the base; thread 750713 reports the same.
- Harness² prompt evolution: Phase 1 adopted nothing; the box that ran it is closed.
- Helper-script pipelines (v9, v10, v4h): read 0.06-0.10 on hidden; the single thinking-on agent (v12 line) reads 0.10-0.17.
- Parser-garble rule (v12b_garble): failed its own rule on 28 Oct.
- Patch reranking and best-of-k: no parallel calls, and a second attempt does not fit the 5-minute cap.
