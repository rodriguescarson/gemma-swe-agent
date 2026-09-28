# Update 2026-09-28: what is new, what it means for tonight, what v10 should change

Merged 2026-09-28 16:40 IST (11:10 UTC) from three read-only sweeps, plus checks I ran for this merge:
- `research/forum_update_0928.md` (forum, both tracks, 16:17 IST)
- `research/notebooks_update_0928.md` (notebooks + leaderboard, 16:05 IST)
- `research/org_update_0928.md` (wheelhouse, data, pages, host notebook, 16:25 IST)

Baseline: `research/forum.md` and `research/competitors.md` (both 2026-09-27, ~21:45 IST). Only items that are new since
then appear below. Times are IST; UTC in brackets where Kaggle defines the time. **UNVERIFIED** marks anything not
checked against source, data or a first-party statement.

Nothing was posted, voted, submitted or pushed. Our kernels were not touched; I only ran a read-only
`kaggle kernels status` on them.

---

## 0. Bottom line

1. **Nothing in the sweep shows that v10 will beat v4.** v10 has zero model-in-the-loop runs (no `eval/runs/r2_*`, no
   `docs/v10/race2_report.md`). Its own pre-registered ship rule says it replaces v9_eog only if every race-2 KPI passes
   (`docs/v10/race2_checklist.md` §4). The strongest new cross-team evidence is that lab gains often do not transfer:
   - Black Cat's T 1.0 variant "looked equal in the lab" over 209 runs, then scored 0.06 against their 0.10 anchor.
   - busyaprime predicted 34/119 locally and scored 4/58.
   v10 does target real, measured failure modes, which is a reason to race it soon. It is not yet a measurement.
2. **The sub3 → sub4 drop (7 → 4 of 58) is inside measured noise.** A GraphLoc agent run 3 times identically resolved
   31, 28 and 33 of 106 tasks. Scaled to 58 tasks, the SD of a two-run difference is about 2.5-2.7 tasks, so our drop
   is about 1.1 SD (p ≈ 0.25). Rozen's byte-identical bundle has scored 7, 5, 6 and 6 for four teams. sub3 and sub4
   also ran on different wheelhouse builds (confounder, not an explanation). No forum post confirms or refutes the
   "compaction wipes `include_contents: none` stages" hypothesis.
3. **Host, 2026-09-28 16:02 IST (743964):**
   - A 12 h overrun still errors the whole run ("Not yet").
   - "we don't support parallel calls".
   - A LoRA loading fix was applied 09-27. The wheel diff confirms it by code reading, but not on a GPU.
   - "Training on gemma-4-31b itself is fine". Outputs from other models are still unruled.
4. **Our 314-row SFT set is NOT cleared by that ruling.** It was converted from `nebius/SWE-rebench-openhands-trajectories`,
   whose teacher is Qwen3-Coder-480B (`train/convert_nebius.py:1`). Both sweeps said "check provenance"; this settles
   it.
5. **The paired Kaggle L4 kernels are QUEUED, not running.** The org report says they "started". Status at
   16:31 IST (11:01 UTC): `g4-l4-v4` and `g4-l4-v9-eog` both `KernelWorkerStatus.QUEUED`. Participants report
   4×L4 queues of 4-9 h (743600, 743901). They may not finish before tonight's slot.
6. **Tonight (00:01 UTC = 05:31 IST 09-29), recommended default: resubmit v4, unless race 2 passes first** (§2). If both
   paired kernels have finished, submit the higher of v4 and v9_eog; within 3 tasks, submit v4.
7. **Top v10 change: raise `timeout_seconds` from 120 back to 180** (§3.1). It also caps the whole hidden-test pytest run.
   SPEC assumed a ~10× margin over the public maximum of 12.6 s. Black Cat measured 73 s for one requests test file in a
   scorer-faithful lab, which leaves a 1.6× margin at 120 s. The cost is about 1.3 s per task.

---

## 1. What is new since 2026-09-27

### 1.1 Host and organiser

| What | Evidence | Status |
|---|---|---|
| Ryan Holbrook's only new post on either track answers four points. 12 h overrun: "Not yet. Budget per task using eval_config.yaml." Parallelism: "I we don't support parallel calls." LoRA: "I applied a fix for LoRA loading yesterday … total submission limit of 3GB." Data: "Training on gemma-4-31b itself is fine. We'll try to have an answer for outputs from other models soon." | https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743964 (comment 3529469, 2026-09-28 16:02 IST (10:32 UTC)) | First-party |
| **Wheelhouse v23** (2026-09-27 16:07 IST) rebuilt `vllm-0.19.1` in place. Only `models/gemma4.py` and `lora/model_manager.py` changed. The diff removes the duplicate `decoder_layers` registration, and `activate_adapter` no longer resets a module it has already loaded. That is exactly the 743508 wipe. | Per-member CRC32 diff of v22 vs v25 by HTTP range reads: `org_update_0928.md` §1.1-1.2; https://www.kaggle.com/datasets/metric/gemma-4-developer-agent-wheelhouse | Verified by code reading. **UNVERIFIED on GPU**: nobody, including the reporter Whisper Last, has shown adapter logprobs differing from base |
| **Wheelhouse v24** (2026-09-27 17:02 IST) rebuilt `adk_submission-0.2.11` in place. `thinking_budget` now switches thinking (≤0 off, >0 on). `include_thoughts: false` is checked first and still wins. | `org_update_0928.md` §1.3 (`resolvers/generation.py:94-107`) | No effect on v4/v9/v10: every stage sets `include_thoughts: false`. Competitor configs dated before this that used `thinking_budget: 0` alone did **not** turn thinking off |
| Version strings are not identifiers: vLLM and adk_submission were rebuilt without a version bump. Current wheelhouse is v25 (same content as v24); no v26 exists. | `org_update_0928.md` §1.1 | Compare hashes, not names |
| **Getting Started notebook re-run** 2026-09-28 01:20 IST (2026-09-27 19:50 UTC) with three changes. (a) `default_chat_template_kwargs={'enable_thinking': True}` is removed. (b) The budget is read from the bundle's `eval_config.yaml`, with fallbacks of 300 s / 100 calls / 60 min / turns None; it used to hard-code 5 min / 100 calls. (c) The "only enforced constraint is 12 h" sentence is deleted. Compaction (15 / 2 / 14,336 / 5), context cache, `gpu_memory_utilization` 0.90 and `sandbox='subprocess'` are unchanged. | https://www.kaggle.com/code/ryanholbrook/getting-started-gemma-4-developer-agent ; diffs in `forum_update_0928.md` §0.2 and `org_update_0928.md` §2 | Whether the scorer mirrors (a) is **UNVERIFIED**. It does not matter for us: all our stages set `include_thoughts: false` and all four eval_config keys |
| Budget defaults now conflict. The host said "the default is no limit" (743063, 09-24); the README and notebook say 60 min / 100 calls / 300 s. | `org_update_0928.md` §2.1 | Irrelevant while we set every key. It matters only when reading competitors that ship no eval_config (Rozen) |
| **Unchanged since the 09-25 re-issue:** all 524 data files (`HARNESS_README.md` sha256 `3d6e57a1…`, `tasks.jsonl`, `sandbox/setup.py`, `docker/*`); every Overview/Rules/Timeline/Evaluation page on both tracks; every other wheel (swegemma 0.2.7, adk_eval_core 0.1.0, google_adk 1.36.1). The promised `sample_submission` fix has not shipped. | `org_update_0928.md` §3-4 | Local data and README are current |
| Kaggle Models lists W4A16 instances for 12B, E4B and E2B besides 31B, but none for 26B-A4B. The host has not opened the smaller models. | `kaggle models get google/gemma-4`; `org_update_0928.md` §6 | Still 31B-only as far as public evidence goes (**UNVERIFIED**) |
| No host reply on 743752 / 743456 (scorer compaction interval, Docker vs subprocess), 742911 (async graph nodes), 743973 (dead public tasks), 743683 (the Monday rerun), or anywhere on the paper track. | `forum_update_0928.md` §3-4, §7 | Open |

### 1.2 Leaderboard (2026-09-28 16:05 IST (10:35 UTC))

- 732 teams on the LB CSV (733 in `kaggle competitions list` ten minutes later; 607 on 09-27). Source:
  `NB3/_lists/lb/gemma-4-developer-agent-publicleaderboard-2026-09-28T10:35:50.csv`.
- Makus is still alone at 0.15 (9/58), with no submission since 2026-09-26 19:28 IST.
- The 0.13 tier grew from 7 to 12 teams: Howon Kang, DoRA, Pawan Bishnoi, Sukhendu Sain and Ingenhousz are new there.
  None of them has public work for this competition (`NB3/_lists/new013_users.txt`). "DoRA" is only a team name.
- At least 10 top-30 teams resubmitted since 09-27, and nobody reached 9/58. The 9/58 ceiling holds.
- The distribution is 0.15 ×1, 0.13 ×12, 0.12 ×59-60, 0.10 ×93, 0.08 ×138-139, 0.06 ×142. The two sweeps differ by one
  team in a few bins because their snapshots were ten minutes apart.
- **Us: rank 55 (was 50), best 0.12.**
  - sub4 `56622442` (v9_eog, submitted 2026-09-28 05:31 IST) = **0.06**.
  - sub3 `56591871` (v4) = 0.12.
  - sub1 = 0.10.
  - sub2 `56563379` is still COMPLETE with no score. The host's promised Monday rerun (743683) has not reached it.
  - Today's quota is used (1 used, 0 remaining).

### 1.3 Competitor evidence

| Source | What is new | Weight |
|---|---|---|
| zzgtylors, GraphLoc end-to-end failure analysis (3 identical runs) https://www.kaggle.com/code/zzgtylors/graphloc-end-to-end-failure-analysis-resource | **The only public repeat-run measurement.** Base resolved 31/28/33 of 106 and skill 30/30/35. Per task: 22 always, 20 sometimes, 64 never. The between-run SD is 3.4 pp; skill minus base is +0.9 pp (95% CI −4.1 to +6.3). Editing a gold function resolves 57% (82/143) against 6% otherwise. Near-misses are 43 target-test failures and 13 "only other tests fail" (regressions). Agents edited tests in 15-17% of runs. The agent ran at T 0.2 with thinking on. | High: real repeat runs, public outputs (`NB3/out/graphloc-fa/e2e_analysis.json`) |
| lucifer19, Black Cat "Pack Instinct" https://www.kaggle.com/code/lucifer19/black-cat-swe-agent-pack-instinct | LB history: single agent 0.06, compact 0.08, coder + analyzer 0.10, and a private lean **T 1.0** agent at 0.06 that "looked equal in the lab". Their lab covered 209 runs, 10 variants and 19 tasks with scorer compaction. Outcome depended on the task, not the variant: 3 tasks passed 32/33 times and 16 never did. The challenger (8 min / 100 calls / 300 s) raised mean calls from 28 to 74, time from 158 to 258 s and loops from 9/19 to 13/19, and solved the same 3/19. Measured failure modes: `git grep` misses (exit 1, empty message) trigger 10-80 identical calls; one read of a box-drawing test file added ~18k tokens and discarded the patch; one requests test file took **73 s** under the verifier. | Medium: lab numbers are theirs, on 19 public tasks. The T 1.0 point is confounded with an architecture change |
| nihilisticneuralnet, Direct Code Verifier (DCV) https://www.kaggle.com/code/nihilisticneuralnet/gemma-4-developer-agent-direct-code-verifier | **`thinking_budget` is not enforced:** with budget 384, one turn produced 6,144 completion tokens in 169.6 s and no tool call (`trace_rich_3506`). A "guard" arm with no `edit_file`/`write_file` (edits via `python3 - <<'PY'` with `count(old)==1`) made 152 `run_command` calls with 0 malformed. Both arms resolved 1/16, with 10/16 no-patch at the 4.5 min cap. | Medium: 16 tasks, thinking on, so it says nothing about the edit channel with thinking off |
| Cross-team trace count (`NB3/malformed.py`) | Malformed `edit_file` ("mandatory input parameters are not present"): thinking on gives DCV 1/25 (4%) and GraphLoc run 1 52/246 (21%) and 18/251 (7%). Thinking off gives Shape of Doubt 33/143 (23%), ours 52-67%. Fits vLLM #39043 ("tool calls leak with thinking off"). | Lead only: prompts, tasks and temperature all differ |
| haideptry V11 post-mortem https://www.kaggle.com/code/haideptry/gemma-develop-first-try | 0.00 because ADK 1.36.1 rejects snake_case skill names (`SubmissionValidationError` on every task). Verified in `google/adk/skills/models.py:32,87-96` and `features/_feature_registry.py:176` (`SNAKE_CASE_SKILL_NAME` `default_on=False`). | Verified. Ours is `swe-tools` (kebab-case) |
| osama133 survival kit https://www.kaggle.com/code/osama133/gemma-4-dev-agent-task-anatomy-survival-kit | 57% of public fixes are single-file with ≤20 lines. 76% of issues name neither file nor function. 21/129 fixes (16%) touch `async def`, which the graph tools cannot see. At most 2 queued/running batch GPU sessions, and "saving a new version while an older one is still queued can cancel the queued one". | **UNVERIFIED** by us |
| bharat0, eval errors https://www.kaggle.com/code/bharat0/eval-errors-gemma-4-developer-agent | Gold patches resolve only 5/10 fastapi tasks on the public subprocess path. | Public path still broken; says nothing about the scorer |
| tharunkumar369 "Top 1 Master Baseline" | Rewritten again, now claiming "LB 0.12-0.15" at 15 calls / 2 min. The author is not on the LB. | Unreliable: contradicts Pathfinder (4-min cap cost 0.12 → 0.08) |
| ahmadagbaria baseline reproduction | Byte-identical to Rozen's notebook (`cmp`); the author's LB entry is 0.10. | Another draw of the Rozen bundle (linking it to his LB entry is timing-based, **UNVERIFIED**) |

**Field consensus that is still true:** every public bundle at 0.12 or above uses T 0.2 / top_k 40 with thinking off.
Temperature has not been isolated by anyone. Our own pod sweep found no temperature effect (sweep1, 47 tasks, all paired
p > 0.45; `eval/ledger.md` 2026-09-25 23:27 UTC).

### 1.4 Harness facts

- **swegemma 0.2.7 wheel-cache bug** (744029, 2026-09-28 15:53 IST): unpacked wheels are cached at
  `$TMPDIR/swegemma_sp_cache_v8/{sp_base,sp_whl_<pkg>}.tar`, and the key ignores the wheel set.
  - Verified at `swegemma/harness/container_setup.py:244-248`.
  - Our Mac has `sp_base.tar` built 2026-09-28 03:38 IST. Any Mac or pod run since then that changed the wheel set ran
    on stale wheels.
  - Kaggle kernels start on fresh VMs and are unaffected.
- **Dead public tasks on Python 3.13** (743973, JohnParkerson, **UNVERIFIED**): 8 requests tasks (VERIFY_X509_STRICT
  vs the pytest-httpbin certificate); fastapi_14186, fastapi_15745 and rich_3486 (version-gated skips count as not
  passed); rich_3472.
  - 11 of the 12 are already outside our 74 Kaggle-valid tasks.
  - rich_3472 is in our 74, and our record shows a real `AttributeError`, not a message drift
    (`research/tasks/rich_3472.json`).
  - Hidden tasks were feasibility-screened (743817), so the LB is unaffected.
- **Verification timeout, re-verified today.** `swegemma/harness/verification.py:492-503` runs **one** pytest over all
  target files, with `timeout=config.harness.command_timeout_seconds`. `config.py:179-188` sets that from
  `timeout_seconds`. So the whole required-test run of a correct patch must finish inside `timeout_seconds`. The
  private scorer script is not public (**UNVERIFIED** that it does the same, but it reads the same key).
- **The post-invocation compaction crash path is not new.** The org report flags `apps/compaction.py:475-491`: with a
  `SequentialAgent` root and no summariser yet, it raises `ValueError('No LlmAgent model available')`.
  - `research/gap_4.md` §0/§3 already covered it: 0/74 on Kaggle L4 and 0/722 Sequential-root task-runs, and the window
    closes after the first in-flow compaction because one config object is shared.
  - I re-read the code for this merge. `agent_runner.py:566-578` breaks out of `runner.run_async` as soon as a submit
    plus a final text arrives, and `:635` stops the nudge loop once a patch is submitted. The post-invocation step
    (`google/adk/runners.py:598-610`) therefore only runs on invocations that end **without** a submit.
  - Race-2 KPI 3 already counts this crash class.

### 1.5 Paper track (first sweep of its forum)

- 7 topics and no staff replies, apart from the 09-24 welcome (Best Paper / Best New Resource / Best New Application,
  $35k).
- Still open:
  - Can one writeup win several awards?
  - Are the Resource and Application awards judged on the same 5 criteria?
  - May a dataset rebuilt from the public upstream repos be published under the no-redistribution rule (743255 Q4)?
  - Is the Google event archival (743310)?
- A writeup-save 404 bug (743094, 09-25) has no response.
- Deadline unchanged: 2026-11-13 05:29 IST (2026-11-12 23:59 UTC).
- Source: https://www.kaggle.com/competitions/gemma-4-developer-agent-paper/discussion

### 1.6 Corrections to the three sweep reports

| Report says | Actually | Evidence |
|---|---|---|
| org §0.4 / §7.1: `g4-l4-v4` and `g4-l4-v9-eog` "started 15:59 IST … both run on v25" | Pushed at 15:59 IST, but **still QUEUED** at 16:31 IST. They will attach whatever wheelhouse is current when they start (`dataset_sources` is unpinned) | `kaggle kernels status carsonrodrigues/g4-l4-v4` and `…/g4-l4-v9-eog`, 11:01 UTC; `kernels/g4-l4-v4/kernel-metadata.json` |
| forum §2.2, notebooks §6.7: the 314-row SFT set "qualifies only if every row came from gemma-4-31b; check provenance" | It came from Qwen3-Coder-480B trajectories, so it is **not** cleared | `train/convert_nebius.py:1`; `eval/ledger.md` 2026-09-26 08:30 UTC |
| notebooks §6.3: add Black Cat's `NO MATCHES` grep idiom | v10 already prints "NOTE: no match … Try a shorter regex" from `grep.py`, flags repeated identical calls (`_swe_common.py:49-53`), caps views at 100 lines / 4,000 chars, runs the grader's exact pytest flags (`_swe_gate.py:1100`, `_swe_common.py:1365`), and reverts protected test/config edits before submit (`finalize.py` → `hygiene_revert`, `_swe_common.py:1315`) | `submissions/v10/skills/swe-tools/scripts/` |

---

## 2. What it means for tonight's slot (2026-09-29 05:31 IST = 00:01 UTC)

### 2.1 The three candidates against the evidence

| | v4 (sub3) | v9_eog (sub4) | v10 |
|---|---|---|---|
| Scored draws | 1 draw: 7/58 (0.12), pre-v23 wheels | 1 draw: 4/58 (0.06), v25 wheels | none |
| Local model-in-loop evidence | Kaggle L4 v4 26/74 (pod, 09-26); race1 r_v4 18/51, but with helpers failing 86/93 on the subprocess sandbox, so crippled | race1 21/51 (no compaction); Kaggle L4 paired run queued | only offline tests (`eval/offline/v10_*.json`, `tests/test_v10_*.py`); race 2 not started |
| 12 h safety | 5 min cap; sub3 finished | same config as v4 | 5 min cap. Worst case 600 + 120 × (300 + 9.6) = 37,752 s = 10.5 h, or 11.3 h at 130 tasks. Validation is outside the 12 h (743663) |
| Differs from v4 by | n/a | helpers path fix + `replace.py`/`run.py`/`gate.py`; identical sampling and eval_config (`submissions/v4` vs `submissions/v9_eog`) | new 5-stage pipeline, new helper suite, per-stage output caps, T 0.2 on setup/submitter, 120 s / 100 calls / 200 turns |
| Gate before an LB slot | none needed | none needed | pre-registered: every row of `race2_checklist.md` §2 must pass |

What the new evidence says about the choice:
- **No LB slot can rank these bundles.** The SD of the difference between two runs is about 2.5-3.5 tasks
  (GraphLoc scaling; binomial at p ≈ 0.12). The only instruments that can rank them are paired runs: the queued Kaggle
  L4 kernels (v4 vs v9_eog, with scorer compaction 15/2/14,336/5) and race 2 (v10 vs v9_eog).
- **A v4 redraw is the most informative non-v10 slot.**
  - v4 is the only bundle scored before the v23/v24 wheel rebuilds. A second v4 draw on v25 wheels tests the one
    scorer-side confounder (the org report's §0.4) directly on the real Docker scorer, which no local run can
    replicate.
  - It is also our first same-bundle noise measurement on our own design.
  - A v9_eog redraw answers a narrower question, because v9_eog has no pre-change anchor.
- **v10 "probably better" is plausible but unmeasured.** v10 attacks our largest measured losses:
  - 67% malformed `edit_file` (competitors.md §7.1), handled by routing edits through `edit.py` over `run_command`,
    whose malformed rate is 2.5%.
  - 45% helper install (§7.2), handled by a dedicated setup stage.
  - 13 context-overflow patch losses, handled by output caps and checkpoints.

  Those are good reasons to race it tonight. Against that, three independent public results (Black Cat lab vs LB,
  busyaprime 34/119 → 4/58, GraphLoc +0.9 pp) say that tool-level improvements often do not move resolution. That is
  what race 2 is designed to catch.

### 2.2 Decision procedure (check at about 04:30 IST 09-29 = 23:00 UTC 09-28)

1. **Race 2 has run and every KPI row passes** (`tests/test_v10_runner.py::test_race_kpis`): submit v10, with the
   §3.1 timeout change if it was adopted **before** the race started.
   - Race 2 needs the pod, and starting it is Carson's call (`docs/v10/RACE2.md` §1).
   - By my estimate each round takes about 2 h (74 tasks at 2 tasks/GPU under the 1.7-scaled 176 s cap), plus
     bootstrap. Started this evening, it can finish before the slot (estimate, **UNVERIFIED**; the chain's own timing
     governs).
2. **Else, if both paired L4 kernels have finished:** submit the one with more resolved tasks. If they are within
   3 tasks, submit v4.
3. **Else: submit v4.**

An option only Carson can take: **submit v10 tonight as a scorer smoke test, without race 2.**
- For: about 65 daily slots remain before 2026-12-03 05:29 IST (2026-12-02 23:59 UTC), so slots are cheap. Only a
  scored run can reveal catastrophic Docker-only failures, such as helper install or `/tmp` behaviour, as a 0.00-0.03
  or an ERROR.
- Against: it breaks the pre-registered ship rule, which needs a dated addendum per `race2_checklist.md` (its header
  says changes go in an addendum). A 3-5/58 result would be uninterpretable and tempting to over-read.
- If taken, record in advance that only a score of 0.03 or less, or an ERROR, counts as a finding.

Operational notes for tonight:
- Do not push a v10 Kaggle L4 kernel while both paired kernels are queued. osama133 reports a cap of 2 queued/running
  GPU sessions, and that saving a new version can cancel a queued one (**UNVERIFIED**). Race v10 on the pod instead.
- The ledger's 09-26 rule "no GPU kernels during scoring" was later corrected: the sub2 failure was platform-side
  (`eval/ledger.md` 2026-09-26 11:00). Queued kernels are therefore not a known risk to tonight's scoring, but they
  are not proven safe either.
- Participants report that GPU quota is charged for queue time (743683, Dmitry Sokolevski, **UNVERIFIED**).

---

## 3. Changes v10 should adopt before it ships (ranked)

Each item gives the evidence, the files to change, and what it costs. Items v10 already covers are in §3.7 so they are
not re-done.

### 3.1 Raise `timeout_seconds` from 120 to 180
- **Evidence.**
  - The whole required-test pytest run is capped by this key (`verification.py:492-503`, re-verified today).
  - SPEC chose 120 for "about a 10x margin" over the public maximum of 12.6 s (`docs/v10/SPEC.md:1053`;
    `research/time_model.md:60`).
  - Black Cat measured one requests test file at **73 s** under the verifier, in a lab with the scorer's compaction on
    4×L4 (`notebooks_update_0928.md` §3.3). That is a 1.6× margin at 120 s.
  - Hidden repos differ (742882) and the scorer's Docker sandbox has 2 vCPU / 4 GiB.
  - A false negative on a correct patch is, in SPEC's own words, "the most expensive error".
- **Cost.** About 1.3 s per task against 120 (`research/gap_5.md:28`), or about 0.05 h per 120-task run.
  - Agent-side hangs are bounded by the helpers' own watchdog (`HELPER_LIMIT = 110`, `_swe_common.py:28`), so 180 binds
    only raw commands.
  - v4, which scored 0.12, used 180.
  - The existing guard `ev["timeout_seconds"] <= v4["timeout_seconds"]` (`tests/test_v10_bundle.py:722`) still passes.
- **Files.**
  - `submissions/v10/eval_config.yaml`
  - `tests/test_v10_bundle.py:31`
  - `tests/test_v10_runner.py:120` (120 → 180) and `:133` (71 → 106 under `G4_L4_SCALE` 1.7)
  - `docs/v10/SPEC.md:131,1053`
  - Re-pack and re-record the bundle hash in `docs/v10/RACE2.md` §2
- Must land **before** race 2 starts, so the race measures the shipped bundle.
- Why not 300: with a 5 min task cap, one raw hang could eat the whole task (`docs/v10/design_C.md:208`).

### 3.2 Race 2 with a lower-temperature arm; do not change temperature blind
- **Evidence.**
  - Every public bundle at 0.12 or above runs T 0.2 / top_k 40. Black Cat's only T 1.0 bundle lost about 3 tasks on the
    LB after tying in the lab (confounded).
  - GraphLoc's variance was measured at T 0.2, and at T 1.0 more tasks sit in the "sometimes solved" bucket.
  - Against that, our only direct test found no effect (sweep1, p > 0.45).
  - v10 runs locator, fixer and verifier at T 1.0 / top_k 64 (`submissions/v10/configs/gen_*.yaml`).
- **Change.** Run the pre-built optional arm `r2_v10_t06`. It is one command:
  `python scripts/make_variant.py submissions/v10 submissions/v10_t06 --work-temp 0.6` (`docs/v10/RACE2.md` §1).
  - Budget allowing, add a T 0.2 arm as well. That needs a `--work-temp 0.2` build; top_k stays 64 unless
    `make_variant.py` gains a flag.
  - Ship the arm that passes the KPIs with more solves.
- **Cost.** Pod time for one or two more arms (Carson's call).

### 3.3 Clean the local harness state before the race-2 gates
- **Clear the wheel cache.** Remove `$TMPDIR/swegemma_sp_cache_v8` on the Mac and on the pod (or run each gate with a
  fresh `TMPDIR`) before re-running the pre-race gates.
  - `tests/test_v10_integration.py::test_channel_parity` builds a real `SubprocessManager` sandbox with the harness's
    own setup functions (`docs/v10/RACE2.md` §3.4), so it goes through that cache.
  - The Mac cache predates any wheel change after 03:38 IST today (744029, verified).
- **Refresh `harness/wheels/adk_submission-0.2.11-py3-none-any.whl`** to the v24 build (62,404 B; ours is 62,356 B,
  sha prefix `b07a510d` against `e54d0995`). This is for parity only: no behaviour change for v10.
- **Re-bootstrap the pod's vLLM from wheelhouse v25** (`pod/bootstrap.sh:12-14`). Base-model numerics are unchanged by
  code reading, but it removes a known difference from the scorer.
- **Log the wheelhouse version** into every run's results (org §7.5).

### 3.4 Make the helper output caps token-aware (bytes, not characters)
- **Evidence.**
  - Black Cat saw about 18k tokens enter the context from one read of a box-drawing test file, followed by an overflow
    that discarded the patch (competitor claim; the tool used is not stated).
  - v10's caps are character counts: `emit()` and `cap_text()` use `len()` on `str` (`_swe_common.py:1620,1678`), with `CAPS` of view 4,000,
    run 2,500, status 2,200 and verify 2,000 (`_swe_common.py:25-26`).
  - Non-ASCII text costs more tokens per character than code does, so "bounded outputs under 14k tokens" is only
    guaranteed for mostly-ASCII output. rich, a public repo, is full of box-drawing tests; hidden repos are unknown.
- **Change.** Measure `len(s.encode("utf-8"))` in `emit()`/`cap_text()`. Box-drawing characters are 3 bytes each, so
  this over-counts them and keeps the cap conservative. Before relying on it, check the actual token cost with the
  Gemma tokenizer on one rich box-drawing test file (**UNVERIFIED** magnitude).
- **Cost.** A small edit in one module, plus test updates (`tests/test_v10_core.py`, `tests/test_v10_locate_view.py`).
  Lower priority than 3.1-3.3, because of regression risk this close to a race.

### 3.5 Two Black Cat prompt rules that fit v10's lint (low priority)
- Candidate rules for `prompts/locator.md` and `prompts/fixer.md`:
  - "Git history stops at the base commit; never search it."
  - "Run code only through run.py; never a multi-statement `python3 -c`."
- Both are zero-cost and name no graph tool, so they are compatible with R89 (`docs/v10/SPEC.md:1202`).
- Evidence: listed as failure modes in Black Cat's lab, but with no counts. Adopt only if the prompt tests
  (`tests/test_v10_prompts.py`) can be updated before the race.

### 3.6 Fix `scripts/make_eval_kernel.py` if v10 ever runs as a Kaggle L4 kernel
- It takes budgets from CLI flags (defaults 6 / 60 / 80 / 180), not from the bundle.
- The host notebook now reads `eval_config.yaml` (org §2.2). Race 2 is unaffected (`FAITHFUL=1` reads each bundle's
  eval_config).

### 3.7 Keep as is (new evidence supports the current choice)
| Setting | Why keep | Evidence |
|---|---|---|
| `max_time_minutes: 5` | Overrun is still fatal ("Not yet"). v10's worst case is 10.5 h at 120 tasks | 743964; arithmetic in §2.1 |
| `max_tool_calls: 100`, `max_turns: 200` | Black Cat's "more budget, more loops, no more solves" came with a 5 → 8 min time increase. With v10's 5 min cap, time binds first (1.5-2.2 s per call) | Black Cat lab; `eval/ledger.md` 2026-09-25 23:00 (~2.2 s per call on L4) |
| No ParallelAgent / concurrent best-of-N | "we don't support parallel calls" | 743964 |
| `include_thoughts: false` on every stage | Now also protects against the notebook's removed server default and against v24's `thinking_budget` switch | org §1.3, §2.1 |
| Skill name `swe-tools` (kebab-case) | Snake-case fails validation on every task. The official compiler run in `scripts/validate.py` should reject it too (**UNVERIFIED** that it raises the same error) | haideptry; ADK `skills/models.py:32,87-96` |
| Graph tools declared but never named (R89) | Black Cat bans `search_similar_code` by name; v10's no-mention policy is the stricter form. Note that SPEC's accepted-risk line cites 11,245 chars as the observed maximum, while `research/gap_4.md` §0 later measured up to **55,164 chars (+14,027 prompt tokens in one step)**, so v10's output bound does not cover a graph call | `docs/v10/SPEC.md:65`; `research/gap_4.md` §0 |
| Test-file revert, grader pytest flags, NO MATCH notes, repeat-call notes, 100-line views | These already cover the GraphLoc test-edit rate (15-17%), Black Cat's grep loops and the whole-file read | §1.6 table |

### 3.8 Not for v10 now
- **Thinking on in the fixer (malformed-edit probe).** The lead is real (4-21% malformed with thinking on against our
  52-67%), but v10 already moves edits off `edit_file`. Run the probe only if race-2 KPI 6 (malformed `edit_file` ≤1
  per task) fails. If it runs, cap `max_output_tokens` hard (~1,536), because `thinking_budget` is ignored (DCV trace).
- **LoRA.**
  - Our `g4-lora-test` result (2026-09-26 12:55 IST) is void: it ran on the pre-fix wheel.
  - Before any training, rerun Whisper Last's repro on v25: random `lora_B`, base vs adapter logprobs at T=0. This
    needs Carson's approval for a GPU session.
  - Training data must be gemma-4-31b's own trajectories. The existing Qwen3-derived 314-row set waits for the
    other-models ruling.
  - Limits: rank ≤128, ≤8 adapters, `.safetensors`, bundle ≤3 GiB.

---

## 4. Watch list (unanswered as of 2026-09-28 16:40 IST)

- 743683: the sub2 rerun (`56563379`). It would be a free extra data point.
- 743964 follow-up / 742807: the ruling on training with other models' outputs, which decides the fate of the 314-row
  set.
- 743508: any public confirmation that adapters now change outputs.
- 743752 / 743456: scorer compaction interval (README 5 vs notebook 15); Docker vs subprocess.
- 743973: whether the host confirms dead public tasks. Recheck rich_3472's gold result after clearing the wheel cache.
- 743255 / 743310 / 743094 (paper track): redistribution of rebuilt data, archival status, the writeup-save bug. Hold
  any public resource release until 743255 Q4 is answered, and test that a writeup draft saves well before
  2026-11-13 05:29 IST.
- Paired L4 kernels `g4-l4-v4` / `g4-l4-v9-eog`: queued as of 16:31 IST.

## 5. Sources

- Forum, main track: https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion (threads 743964, 743973,
  744029, 743683, 743901, 743957, 744020, 743140, 742807).
- Forum, paper track: https://www.kaggle.com/competitions/gemma-4-developer-agent-paper/discussion (743012, 743255,
  743310, 743094).
- Host notebook: https://www.kaggle.com/code/ryanholbrook/getting-started-gemma-4-developer-agent
- Wheelhouse: https://www.kaggle.com/datasets/metric/gemma-4-developer-agent-wheelhouse (v22 → v25 member diff in
  `scratchpad/org0928/wh_v22_v25_crcdiff.json`).
- Notebooks: GraphLoc (zzgtylors), Black Cat (lucifer19), DCV (nihilisticneuralnet), haideptry, osama133, bharat0,
  tharunkumar369, ahmadagbaria (URLs in §1.3).
- Sweep reports and evidence folders: `research/forum_update_0928.md` (`scratchpad/forum7/`),
  `research/notebooks_update_0928.md` (`scratchpad/nb3/`), `research/org_update_0928.md` (`scratchpad/org0928/`).
- Local code and data cited: `.venv/lib/python3.12/site-packages/swegemma/harness/{verification.py,agent_runner.py,container_setup.py}`,
  `.venv/.../google/adk/{apps/compaction.py,runners.py,flows/llm_flows/compaction.py}`, `submissions/{v4,v9_eog,v10}/`,
  `docs/v10/{SPEC.md,RACE2.md,race2_checklist.md,design_C.md}`, `train/convert_nebius.py`, `eval/ledger.md`,
  `research/{gap_4.md,gap_5.md,time_model.md}`.
- Commands run for this merge (read-only): `kaggle kernels status carsonrodrigues/g4-l4-v4` and
  `carsonrodrigues/g4-l4-v9-eog` (11:01 UTC).
