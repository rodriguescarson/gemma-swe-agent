# Forum update: gemma-4-developer-agent + paper track (new since the 2026-09-27 sweep)

Sweep taken 2026-09-28 16:17 IST. All times are IST (UTC+5:30). The previous sweep (`research/forum.md`) ended 2026-09-27 21:45 IST, and its newest reply was 21:25 IST. This file reports only what is new since then, and what the 2026-09-27 files did not already cover.

**Method.** Read-only throughout.
- Kaggle API (kaggle 2.2.4): topics listed under 5 sort orders, then every message tree fetched.
  - Main track: 45 topics (39 at the last sweep).
  - Paper track: 7 topics, not covered before.
  - Every topic's message count matched its `commentCount`, so the dump is complete.
  - No message from the previous dump was edited (content diffed by message id).
- Authors come from `kaggle competitions topics show`, because this API build returns `authorName: None` on messages.
- Chrome: the tab loaded, but every Kaggle page exposes only the cookie-consent overlay to `get_page_text`/`find`. I did not accept the banner, so the browser added nothing.
- Nothing was posted, voted, submitted or pushed. No running kernel was touched.
- Notebook sources were fetched with `kernels pull` (text only; Kaggle strips outputs). No kernel outputs, wheels or data files were downloaded.

Raw evidence, in the session scratchpad (`SP = /private/tmp/claude-501/-Users-carson-Projects/654244a3-b38c-45a0-96af-d7e5f0aac6ce/scratchpad`):

| What | Path |
|---|---|
| Full message trees, both tracks | `SP/forum7/dump.json` |
| Every new message with context | `SP/forum7/new_msgs.txt` |
| Authored trees | `SP/forum7/show/<id>.txt` |
| Topic lists | `SP/forum7/all_gemma-4-developer-agent*.json` |
| Leaderboard (732 teams, API view) | `SP/forum7/lb_all.json` |
| Competition file listing (524 files) | `SP/forum7/comp_files.json` |
| Wheelhouse metadata | `SP/forum7/wh_dataset.json` |
| Notebook sources and flattened text | `SP/forum7/nb/<author>_<slug>/` |

---

## 0. Bottom line

1. **One new staff post on either track: Ryan Holbrook in 743964 (2026-09-28 16:02 IST).**
   - The 12 h overrun fix has **not** landed. A run that hits 12 h still errors the whole submission. His advice: budget per task with `eval_config.yaml`.
   - **Parallel calls are not supported.** His exact words: "I we don't support parallel calls".
   - **He applied a LoRA loading fix "yesterday" (2026-09-27).** This matches the +62 B vLLM wheel in wheelhouse v23 (2026-09-27 16:07 IST) that the last sweep flagged.
     - Limits: `max_lora_rank=128`, `max_loras=8` (Getting Started notebook), 3 GiB total bundle (`swegemma/config.py:19`).
   - **Training a LoRA on gemma-4-31b's own trajectories is allowed.** There is still no ruling on outputs from other models.
   - https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743964
2. **Org update without a forum post: the host's Getting Started notebook was re-run at 2026-09-28 01:20 IST with three changes** (diffed against the 09-27 16:09 IST copy):
   - `default_chat_template_kwargs={'enable_thinking': True}` is removed from the vLLM server config.
   - The budget now comes from the bundle's `eval_config.yaml`. The fallbacks are 100 calls, 300 s and 60 min; before, 5 min and 100 calls were hard-coded.
   - The sentence saying the "only enforced constraint" is the 12 h runtime is deleted.
   - Compaction (`token_threshold=14336, compaction_interval=15, overlap_size=2, event_retention_size=5`) and `sandbox='subprocess'` are unchanged.
   - https://www.kaggle.com/code/ryanholbrook/getting-started-gemma-4-developer-agent
3. **Nothing new on the questions that matter most for sub4.** 743456 (compaction before overflow), 743752 (scorer compaction value, Docker vs subprocess), 743508 (LoRA wipe) and 743063 (budgets) have no new replies. The forum neither confirms nor refutes our hypothesis that 14,336-token compaction wipes `include_contents: none` stages.
4. **Leaderboard (API view, 16:15 IST):** 732 teams (607 at the last sweep).
   - Makus is still alone at 0.15 (9/58). Their newest submission is still 2026-09-26 19:28 IST.
   - The 0.13 group grew from 7 to 12 teams. Nobody is above 0.15.
   - We are rank 55 at 0.12 (sub3). sub4 (`56622442`) scored **0.06** (4/58).
   - sub2 (`56563379`) still has no score. The host's promised "Monday" rerun of the resource-error failures (743683) has not happened yet.
5. **Competitor evidence relevant to sub4 and v10:**
   - Black Cat (team best 0.10) published a lab of 209 runs. Their main finding: outcome depended on the task, not the variant.
   - They also report a private T 1.0 single-agent bundle that "looked equal in the lab" and scored 0.06 on the board.
   - nihilisticneuralnet published a variant with no `edit_file`/`write_file`, where all edits go through `run_command` heredocs. No result was published.
   - haideptry's V11 scored 0.00 because ADK rejects snake_case skill names. Verified in ADK source; ours are kebab-case.

---

## 1. Staff and org activity since the last sweep

| When (IST) | Where | What | Source |
|---|---|---|---|
| 09-28 16:02 | Forum 743964, Ryan Holbrook, comment 3529469 | 12 h fix "Not yet"; budget via eval_config; no parallel calls; LoRA loading fix applied 09-27, limits in the Getting Started notebook and HARNESS_README, 3 GB total; training on gemma-4-31b itself is fine; other models' outputs "soon" | https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743964 |
| 09-28 01:20 | Getting Started notebook re-run | Diff in §0.2. Our local copies: old `SP/nb2/pull/getting-started-gemma-4-developer-agent/`, new `SP/forum7/nb/ryanholbrook_getting-started-gemma-4-developer-agent/` | https://www.kaggle.com/code/ryanholbrook/getting-started-gemma-4-developer-agent |
| none | Wheelhouse dataset | Still v25 (2026-09-27 17:19 IST). No new version after the v23 vLLM change | `SP/forum7/wh_dataset.json`, https://www.kaggle.com/datasets/metric/gemma-4-developer-agent-wheelhouse |
| none | Competition data | All 524 files still dated 2026-09-26 00:06-00:10 IST (the 09-25 UTC re-issue). `HARNESS_README.md` is unchanged at 49,356 B | `SP/forum7/comp_files.json` |
| none | Deadlines | Main 2026-12-03 05:29 IST (2026-12-02 23:59 UTC); paper 2026-11-13 05:29 IST (2026-11-12 23:59 UTC). Unchanged. Paper track has 61 teams, and Carson is entered | `kaggle competitions list -s gemma-4-developer-agent` |
| none | Paper track forum | No staff reply in any of its 7 topics. The only staff post is Elan Markowitz's welcome (743012, 09-24) | https://www.kaggle.com/competitions/gemma-4-developer-agent-paper/discussion |
| none | 743683 rerun promise | New replies, none from the host (§3). Our sub2 is still unscored (`kaggle competitions submissions`, 16:15 IST) | https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743683 |

---

## 2. The priority questions, one by one

### 2.1 LoRA adapter wiping (743508) and a fixed wheelhouse
- 743508 itself has no new reply since the host's "I will address" (2026-09-26 16:49 IST).
- **Now very likely fixed on the scorer side.** The host says he "applied a fix for LoRA loading yesterday" (743964, posted 09-28), which dates the fix to 09-27. Wheelhouse v23 (09-27 16:07 IST) changed only the vLLM wheel (433,132,444 B to 433,132,506 B, per the last sweep).
- **Still UNVERIFIED that adapters now change outputs.** Nobody, including Whisper Last who reported the bug, has posted a re-test. We have not downloaded the 433 MB wheel.
  - Verification plan (needs Carson's approval for the download): (a) check whether `Gemma4SelfDecoderLayers` still registers `decoder_layers` as a submodule; (b) rerun Whisper Last's repro (random `lora_B`, base vs adapter logprobs at T=0).
- Limits confirmed:
  - `max_lora_rank=128` and `max_loras=8`, in the host notebook's `VllmConfig`. `adk_submission/server.py:141` has the same default of 128.
  - 3 GiB total bundle (`MAX_SUBMISSION_SIZE_BYTES`, `swegemma/config.py:19`).
  - Only `.safetensors` adapters (`ALLOWED_ADAPTER_EXTENSIONS`, `config.py:31`).
- No competitor has posted a scored adapter. The LB team name "DoRA" (0.13, latest submission 09-27 13:35 IST) is only a name; nothing shows what they submitted.

### 2.2 Distillation ruling (742807)
- 742807 has one new reply, a non-substantive "thanks" from Aditya Sasidhar (09-27 23:06 IST).
- **Partial ruling in 743964:** self-generated gemma-4-31b trajectories are allowed. Outputs from other models, open-weight or proprietary, are still pending ("soon").
- So an SFT/RFT set built only from Gemma's own test-filtered trajectories is cleared now. Our 314-row SFT set qualifies only if every row came from gemma-4-31b; check its provenance before using it.

### 2.3 Scoring-run facts
| Topic | New information | Status |
|---|---|---|
| 12 h overrun | Host: fix "Not yet"; budget per task with eval_config (743964) | Still fatal to the whole submission. Unchanged from 743063 |
| Concurrency | Host: parallel calls not supported (743964). Tasks were already known to run sequentially (743063) | **A `ParallelAgent` buys no speed.** N candidates cost about N× wall time. Whether a `ParallelAgent` config errors or just serializes is UNVERIFIED |
| Default budgets | The host notebook now falls back to 100 calls / 300 s / 60 min when eval_config omits a key. The public harness defaults are **60 min per task, no call cap, 300 s commands** (`swegemma/budget.py:18-19, 29`). The host said on 09-24 that "the default is no limit" (743063) | The scorer's real default is UNVERIFIED. It does not matter for us, since all our bundles set all four keys |
| Thinking | The host notebook no longer sets `enable_thinking: True` server-wide | Our bundles send `include_thoughts: false`, which becomes `enable_thinking: false` (verified earlier, `adk_submission/resolvers/generation.py:92-107`). No effect expected on us. Whether the scorer mirrors the notebook is UNVERIFIED |
| Compaction | Host notebook still 14,336 / interval 15. 743456 and 743752 unanswered | Unchanged. Black Cat's lab (competitor claim, their setup): "the analyzer has no compaction of its own", because an AgentTool sub-agent runs in its own session |
| Timeouts / verification | Black Cat's lab: one requests test file took 73 s under the verifier, whose run is capped by `timeout_seconds` | Supports keeping `timeout_seconds` ≥180 (see §6.2) |
| Which errors void a task | Nothing new from the host. Black Cat's lab repeats that any non-timeout harness exception discards the patch, already verified by us (`agent_runner.py:209, 797-801`) | Unchanged |
| JUnit criterion | No host statement. JohnParkerson (743973) notes a consequence: required tests that are version-gated to skip on 3.13 can never pass, because a skip is not a pass | Relevant only if hidden tasks have such gates. The host says hidden tasks were reviewed for feasibility (743817), so the risk is low |
| Run determinism | RB asks whether T 0.2 results are deterministic (743140, 09-28 08:02 IST). Unanswered | Known: `seed` is never forwarded to vLLM (competitors.md §4), so runs are not deterministic |
| Scoring wall time | Participants: "a few hours" (Roko Torbarina), "approximately 12 hours" (Varun Ambadi), "timeout after 14 hours" (Nicu) in 743683 | Nicu's case is ambiguous: a 14 h scoring time can still succeed (Geremie Yeo 0.08 at 14.5 h) |
| GPU quota | Dmitry Sokolevski (743683, 09-28 14:46 IST): 5 h in the queue plus 5 h running cost 10 h of GPU quota. No host reply | Affects our Kaggle eval kernels if the 4×L4 queue is long |

### 2.4 Hidden test set characteristics
- **No new host statement.** 744020 (Aman Arora) asks whether the competition is Python-only. The only reply quotes the Data tab ("real-world Python bug fixes and feature requests"), not the host.
- Public-task statistics from osama133's onboarding post (743957, 09-28 05:52 IST), UNVERIFIED by us:
  - 57% of the 129 public fixes are single-file with ≤20 lines.
  - About 76% of issues name neither the file nor the function.
  - About 1 in 6 fixes touch async code, which the graphs cannot see.
  - https://www.kaggle.com/code/osama133/gemma-4-dev-agent-task-anatomy-survival-kit
- **Public tasks the gold patch cannot pass on Python 3.13.** Thread 743973 (wrath333*, 09-28 09:32 IST). The evidence notebook it mentions is not in either competition's listing and not findable by search, so its numbers are UNVERIFIED. JohnParkerson (14:11 IST) lists:
  - 8 requests tasks (6589, 6592, 6629, 6757, 7328, 7433, 7502, 7505). Python 3.13's `VERIFY_X509_STRICT` rejects pytest-httpbin's bundled certificate.
  - fastapi_14186, fastapi_15745 and rich_3486: their required tests are version-gated to skip on 3.13.
  - rich_3472: an error-message change in Python 3.13.
  - Cross-check against our data:
    - 11 of the 12 are already outside our 74 Kaggle-valid tasks (`research/task_catalog.md`).
    - **rich_3472 conflicts with our records.** It is in our 74, and all four configs failed it with a real `AttributeError` in `test_dataclass_no_attribute`, not a message mismatch (`research/tasks/rich_3472.json`).
  - These are public tasks. The hidden tasks come from other repos and were screened for feasibility (743817), so this does not bear on the LB.
- bharat0 reproduced gold-patch failures by stubbing the model in the host's notebook, but the notebook source has no saved outputs. https://www.kaggle.com/code/bharat0/eval-errors-gemma-4-developer-agent

### 2.5 What top teams reveal
- **Nothing.** None of the 13 teams at 0.13 or above has a notebook in either competition's listing (checked all 67 main-track and 4 paper-track notebook authors, `SP/forum7/k_*.csv`). None of them posted in the forum since the last sweep.
- New 0.13 teams since 09-27: Howon Kang, DoRA, Pawan Bishnoi, Sukhendu Sain, Ingenhousz. 暗黑AGI and Alperen ÖZ submitted again around 05:30 IST today and remain at 0.13.
- The distribution still shows a hard ceiling at 9/58: 0.15 ×1, 0.13 ×12, 0.12 ×60, 0.10 ×93, 0.08 ×138, 0.06 ×142, 0.05 ×94, 0.03 ×31, 0.01 ×43, 0.00 ×118 (`SP/forum7/lb_all.json`).

---

## 3. Every new or updated main-track thread

| Thread | New activity (IST) | Content | Relevance |
|---|---|---|---|
| [743964](https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743964) Clarifications on 12h overrun, ParallelAgent, LoRA, self-generated data (Tarun Singhal) | Q 09-28 07:07; **host answer 16:02** | §0.1 | High |
| [743973](https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743973) Gold patches fail offline for most FastAPI and requests tasks (wrath333*) | 09:32; Bharat 11:36; JohnParkerson 14:11 | §2.4. No host reply yet | Medium (local arena hygiene) |
| [744029](https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/744029) swegemma 0.2.7 unpacked-wheel cache ignores the wheel set (Francesco Simone) | 15:53 | The cache tar name is `sp_base` / `sp_whl_<pkg>`, independent of the wheel set, so added wheels have no effect until `$TMPDIR/swegemma_sp_cache_v8` is cleared. **Verified** in `swegemma/harness/container_setup.py:244-247`. Our Mac has `$TMPDIR/swegemma_sp_cache_v8/sp_base.tar` (42 MB, built 09-28 03:38 IST) | Medium: any local rescore that changed wheels after that time may have used stale wheels |
| [744020](https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/744020) Python only? (Aman Arora) | 15:09; replies 15:53 | Data tab quote only | Low |
| [743957](https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743957) Onboarding notebook: task anatomy + Kaggle survival kit (Osama Abdelaal) | 05:52 | §2.4. Also documents building `submission.zip` from a CPU notebook, which avoids the 4×L4 queue | Low |
| [743901](https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743901) L4×4 sessions queued 8+ h (Ahmed Almarwani) | 09-27 21:44; Chandram Dutta 22:19 (a TPU run started after 9 h, L4×4 still queued) | No host reply | Medium: local Kaggle-L4 validation is capacity-bound |
| [743683](https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743683) Rerunning Failed Submissions (host post) | +6: Seif Eddine Achour 00:32 (still failing); scoring-time answers 22:23, 12:56, 14:15; Dmitry Sokolevski 14:46 (quota); one deleted | No host reply since 09-26 | Watch for the sub2 rerun |
| [743140](https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743140) Representative submission results | RB 08:02: are T 0.2 results deterministic? | Unanswered | Low |
| [742807](https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/742807) Distillation | Aditya Sasidhar 09-27 23:06 ("thanks" to Justin Scott) | §2.2 | |
| [743007](https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743007) Welcome | one deleted comment, 09-28 02:31 | none | |

Unchanged since the last sweep, with no new replies: 743508 (LoRA wipe), 743063 (budgets), 743456 and 743752 (compaction and sandbox), 743751 (architecture), 742882 (harness), 743800 (ADK), 743817 (task verification), and the other 27 threads listed in `forum.md` §4. That makes 6 new topics, 4 with new replies and 35 unchanged, out of 45.

---

## 4. Paper track (all 7 topics; none were covered before)

https://www.kaggle.com/competitions/gemma-4-developer-agent-paper/discussion. No staff replies.

| Thread | Content | Relevance to us |
|---|---|---|
| [743012](https://www.kaggle.com/competitions/gemma-4-developer-agent-paper/discussion/743012) Welcome (Elan Markowitz, 09-24) | Topics: PEFT/RL for SWE agents, code comprehension and graph reasoning, new resources and benchmarks, novel applications. Prizes: Best Paper, Best New Resource, Best New Application, $35k total. Top entries are highlighted at a Google event "such as a NeurIPS expo workshop". Main-LB participation is not required | Scope |
| [743255](https://www.kaggle.com/competitions/gemma-4-developer-agent-paper/discussion/743255) Writeups per team and awards (Shiva Shankar, 09-25) | Unanswered: can a team submit one writeup per award or only two final submissions; can one writeup win several awards; are the Resource and Application awards judged on the same 5 criteria (novelty, quality, relevance, verifiability, clarity); may a dataset rebuilt from the public upstream repos be published despite the no-redistribution rule? | High for a Resource entry. Wait for the answer before publishing anything derived from competition data |
| [743310](https://www.kaggle.com/competitions/gemma-4-developer-agent-paper/discussion/743310) What counts as "top submissions"; is the event archival? | Unanswered | Paper 12/14 strategy: the archival status matters for resubmission elsewhere |
| [743094](https://www.kaggle.com/competitions/gemma-4-developer-agent-paper/discussion/743094) Writeup save broken: `CheckHackathonWriteupConflict` returns 404 (woldy, 09-25 03:31) | No replies. Status now unknown | Test that a writeup draft saves well before the deadline |
| [743314](https://www.kaggle.com/competitions/gemma-4-developer-agent-paper/discussion/743314) Under-18 eligibility | Participant answer only | none |
| [743681](https://www.kaggle.com/competitions/gemma-4-developer-agent-paper/discussion/743681), [743844](https://www.kaggle.com/competitions/gemma-4-developer-agent-paper/discussion/743844) Looking for team | Team-finding | none |

Paper-track notebooks (4 in the paper listing: jefferyjeromeharris, breycode, yash1425, and manuelgagofernandez from 09-25):
- jefferyjeromeharris ["Declarative Agents for Autonomous Software Engineering"](https://www.kaggle.com/code/jefferyjeromeharris/gemma-4-dev-agent-paper) (09-27 22:55). Claims thinking mode did not improve resolution within the time budget. Anecdotal, no numbers seen.
- breycode ["CORTEX-SWE"](https://www.kaggle.com/code/breycode/cortex-gemma-swe-paper) (09-27 21:31). Hyperbolic embeddings and spectral partitioning; no LB entry.
- Paper-track work attached to the **main** listing: zzgtylors ["GraphLoc end-to-end: failure analysis + resource"](https://www.kaggle.com/code/zzgtylors/graphloc-end-to-end-failure-analysis-resource) (09-27 10:27) plus repeat runs 2 and 3 (09-27 03:13 and 03:29).
  - It is the companion to their writeup "Where Does the Graph Help? A Localization Audit of Gemma 4 Agent Code Graphs".
  - It reports a failure taxonomy, run-to-run variance and a GraphLoc-129 label resource, but the numbers are in kernel outputs we did not download.
  - The variance figures would be the only public repeat-run measurement. Worth fetching the outputs if Carson approves the download.
- Three likely paper-track notebooks not attached to either competition turned up in search: itsmrz "Where Is the Bug? - paper companion", navin03 "Trust the Experiment: Coding Agent Evaluation", benadictinfanta "CodeGraph-Loc reproduction". Metadata only; not read.

---

## 5. New or re-run notebooks (64 in the main listing, 4 in the paper listing; 57 main-track at the last sweep)

| Notebook | What is new | Evidence quality |
|---|---|---|
| [lucifer19 "Black Cat SWE Agent / Pack Instinct"](https://www.kaggle.com/code/lucifer19/black-cat-swe-agent-pack-instinct) (09-28 05:01, 61 votes) | See the four points below | Lab numbers are the author's own (19 tasks, their harness copy). The LB points are real submissions but single runs |
| [nihilisticneuralnet "Direct Code Verifier"](https://www.kaggle.com/code/nihilisticneuralnet/gemma-4-developer-agent-direct-code-verifier) (09-27 23:07) | A "guard" candidate with tools `run_command, read_file, get_status, submit_patch` only, **no `edit_file`/`write_file`**. Edits are Python heredocs with `assert data.count(old)==1`. T 0.05, thinking on with small budgets (384-512, but `thinking_budget` is never forwarded), 30 s / 36 calls / 4.5 min. Guard is promoted only if it beats "rapid" by ≥2 of 16 paired tasks with no test edits. **No outputs saved; result unknown** | The first competitor to make run_command the only edit channel, which was our competitors.md §6.1 lever. Unproven |
| [haideptry "Gemma develop first try"](https://www.kaggle.com/code/haideptry/gemma-develop-first-try) (V12, 09-28 07:34) | Post-mortem: V11 scored **0.00** because snake_case skill names (`smart_repo_map`, …) fail validation in ADK 1.36.1. **Verified:** `google/adk/skills/models.py:32, 87-96` allows only kebab-case unless `SNAKE_CASE_SKILL_NAME` is on (`features/_feature_registry.py:176`, `default_on=False`). All 21 of our `SKILL.md` files use `name: swe-tools`, which is safe | Verified |
| [bharat0 "Eval errors"](https://www.kaggle.com/code/bharat0/eval-errors-gemma-4-developer-agent) (09-28 11:27) | Host notebook with the model stubbed to return gold patches (§2.4). No outputs saved | Method only |
| [osama133 "task anatomy + survival kit"](https://www.kaggle.com/code/osama133/gemma-4-dev-agent-task-anatomy-survival-kit) (09-28 05:30) | §2.4 | UNVERIFIED stats |
| [ahmadagbaria "Gemma 4 Baseline Reproduction"](https://www.kaggle.com/code/ahmadagbaria/gemma-4-baseline-reproduction) (09-28 01:06) | EDA starter; TF-IDF localization baseline; edit-simulator | Nothing new |
| [tharunkumar369 "Top 1 Master Baseline"](https://www.kaggle.com/code/tharunkumar369/gemma-4-developer-agent-top-1-master-baseline) (re-run 09-28 16:03) | Rewritten from "flat direct-tool v7" to a coder + analyzer design, now claiming "LB 0.12-0.15". The author is still not on the LB | UNVERIFIED marketing |
| [leoprovorov "Complete Guide. Expanded"](https://www.kaggle.com/code/leoprovorov/gemma-4-the-complete-guide-expanded) (re-run 09-28 16:11) | Organizer pipeline plus an A/B candidate, with the scorer compaction 14,336/15 | No results visible |
| yash1425 `notebook173e28b240` | LoRA r=8 on q/k/v with SWE-bench_Lite prompts | Toy, irrelevant |

**Black Cat, in detail:**
- **Lab-Tuned Challenger** (private): one lean agent, T 1.0, 100 calls. It "looked equal in the lab" and scored **0.06**, against their 0.10 anchor (coder + read-only analyzer, T 0.2, 5 min / 40 calls / 120 s).
- **Lab lessons** (209 runs, 10 variants, 19 public tasks, same 4×L4 image and scorer compaction):
  - Outcome depended on the task, not the variant: 3 tasks passed in 32 of 33 runs, 16 never did.
  - One model call takes 1.5-2 s, so 40 calls ran out in about 100 s.
  - `git grep` misses (exit 1, empty message) trigger repeat loops of 10-80 identical calls.
  - Reading a whole box-drawing test file added about 18k tokens and caused an overflow that discarded the patch.
  - A requests test file took 73 s under the verifier.
- **Pack Instinct:** the anchor's design with T 0.2, 8,192 output tokens, and 300 s / 100 calls / 8 min / 150 turns. The prompt adds a `|| echo "NO MATCHES"` grep idiom, "never repeat a call", mandatory `start_line`/`end_line` ≤80 lines, no `git log` searching, and a ban on `search_similar_code`.
  - Lab smoke test: 3/19 for both, 0 vs 1 crash, a mean of 258 s/task (about 8.6 h for 120 tasks).
  - LB score pending.
- **Claim to discount:** it lists "scorer defaults of 100 calls, 300 s commands, 60 min". That comes from the host notebook's fallbacks, not from the scorer (see §2.3).

---

## 6. Implications for us (inference from the above; ranked)

1. **Do not read sub4's 0.06 as a scorer-side mechanism without more evidence.**
   - v4 (sub3) and v9_eog (sub4) have identical `configs/sampling.yaml` (T 1.0, top_k 64, 4,096 out, thinking off) and `eval_config.yaml` (180 s / 70 / 5 min / 150). Checked in `submissions/v4` and `submissions/v9_eog`. So the 7 → 4 task drop comes from the helper and prompt changes, or from noise.
   - For one run at p ≈ 7/58 the binomial SD is 2.5 tasks; for the difference of two runs it is about 3.5. A 3-task drop is under 1 SD.
   - The only direct measure of scorer noise is still the same Rozen bundle scoring 7 vs 5 (743140).
   - Nothing in the forum confirms or rules out the compaction-wipes-`include_contents: none` hypothesis. It needs a local test with the scorer's compaction config (`EventsCompactionConfig(15, 2, 14336, 5)`, as in the host notebook).
2. **v10 lowers `timeout_seconds` to 120** (`submissions/v10/eval_config.yaml`), from 180 in v4/v9.
   - `timeout_seconds` also caps the hidden-test pytest run (verified earlier, `verification.py:498-503`).
   - Black Cat measured 73 s for one requests test file, and the hidden repos are unknown.
   - Raising it rather than lowering it is safer: 180-300 s, with our own shorter timeouts inside `run.py` for agent-side runs.
3. **Best-of-N via `ParallelAgent` is off the table as a speed play** (host: parallel calls not supported). Any multi-candidate design must fit N sequential attempts inside the per-task cap.
4. **12 h overrun is still fatal.** Keep the per-task `max_time_minutes` cap. sub3 finished inside 12 h with a 5 min cap, and whether its 10.4 h figure includes the ~2 h of validation is still UNVERIFIED (forum.md §2.3). Black Cat's lab estimate is about 8.6 h for 258 s/task.
5. **LoRA reopens as a real lever, pending one check.**
   - The fix is applied on the scorer, and self-generated trajectories are cleared.
   - Before training, verify the new vLLM wheel with Whisper Last's repro (needs Carson's approval for the 433 MB download).
   - Limits: rank ≤128, ≤8 adapters, `.safetensors`, bundle ≤3 GiB.
   - Nobody on the board has shown an adapter score, so a working one would be a differentiator.
6. **Local harness hygiene:**
   - Clear `$TMPDIR/swegemma_sp_cache_v8` (or use a fresh `TMPDIR`) whenever the wheel set changes (744029, verified).
   - The Mac copy was built 09-28 03:38 IST. Any Kaggle-env rescore since then that added wheels (for example `typing_inspection`) should be rerun.
7. **Edit channel:** nihilisticneuralnet is now testing the run_command-only edit channel from our §6.1 lever list, with no result yet. Their `assert count == 1` heredoc is the same shape as our `replace.py`, which argues for making it the primary edit path rather than a fallback. The measured basis is our 67% malformed `edit_file` rate (competitors.md §7.1).
8. **Loop control is the cheap fix both labs agree on.** Black Cat's `|| echo "NO MATCHES"` idiom and the no-repeat rule target the same repeat-read loops that caused most of our 13 overflows (competitors.md §7.1).
9. **Paper track:** before publishing any rebuilt graph or dataset resource, wait for the host's answer to 743255 Q4 (redistribution). Test that a writeup draft saves (743094) well before 2026-11-13 05:29 IST.

## 7. Still open (unanswered as of 16:17 IST 09-28)
- 743752 and 743456: scorer compaction value; Docker vs subprocess; whether compaction can fire before overflow.
- 743508: has anyone confirmed that adapters now change outputs?
- 742807 / 743964: distillation from non-Gemma models.
- 743973: does the scorer treat version-gated skips as failures? Host reply pending.
- 743683: when the promised rerun happens (our sub2 `56563379`).
- 743255 / 743310: paper-track award mechanics, redistribution of rebuilt data, archival status.
