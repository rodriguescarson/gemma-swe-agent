# Kaggle forum sweep: gemma-4-developer-agent (2026-09-23 to 2026-09-27 ~16:15 UTC)

Scope: every topic in https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion (39 topics, first 2026-09-23 15:38 UTC, last 2026-09-27 08:11 UTC, newest reply 2026-09-27 15:55 UTC). Host answers first.

Method: Claude-in-Chrome was unavailable ("Browser extension is not connected"), so I used the official Kaggle API read-only (kaggle 2.2.4, `competition_list_topics` over 5 sort orders, then `forums_topic_show` with full paging for authored, nested replies). Every topic's reply count matched its `commentCount`, so the dump is complete. Nothing was posted, voted, submitted or downloaded (only metadata listings).

Raw evidence (scratchpad, session-local):
- `/private/tmp/claude-501/-Users-carson-Projects/654244a3-b38c-45a0-96af-d7e5f0aac6ce/scratchpad/forum5/forum_all.txt`: full text of every thread with author, UTC time and comment id. "[id]" below refers to the comment ids in this file.
- `.../forum5/show_all.json`, `.../forum5/msgs.json`: raw API responses.
- `.../forum5/wh_dataset.json`, `.../forum5/wh_v25_files.json`: wheelhouse version history and current file sizes. `.../forum/wh_versions.json` holds v21-v24 sizes from an earlier sweep today.
- `.../forum5/kernels.json`: 57 public competition notebooks, metadata only.

Host = Ryan Holbrook (Kaggle staff) unless noted. Elan Markowitz (Google) posted only the welcome. Ashley Oldacre (Kaggle) posted only the Discord/newbie post.

---

## 1. Direct answers to the investigation questions

### 1.1 LoRA adapter wiping bug (thread 743508)
- Report (Whisper Last, 2026-09-26 06:03 UTC): the patched vLLM 0.19.1 in the wheelhouse registers each Gemma4 decoder layer twice, as `layers.N` and again under the YOCO alias `self_decoder.decoder_layers.N`. `activate_adapter` sets the LoRA under the first name and then calls `reset_lora` under the alias, which zeroes it. The adapter output is identical to the base model. https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743508
- Host reply [3528725], 2026-09-26 11:19 UTC: "Thanks for the report. I will address." There is no later host post in the forum saying it is fixed.
- **New signal (not in the forum): the vLLM wheel in the wheelhouse changed on 2026-09-27.**
  - Wheelhouse v22 (2026-09-25 13:34 UTC) had `vllm-0.19.1-cp38-abi3-manylinux_2_31_x86_64.whl` = 433,132,444 B.
  - v23 (2026-09-27 10:37 UTC) has 433,132,506 B, 62 B more. v24 (11:32 UTC) and v25 (11:49 UTC, current) keep the v23 size.
  - The host's Getting Started notebook was re-run at 2026-09-27 10:39 UTC, two minutes after v23.
  - Evidence: `wh_dataset.json` (version list with dates), `wh_versions.json` (v21-v24 sizes), `wh_v25_files.json`.
  - Whether this new build fixes the double registration is **UNVERIFIED**: the 433 MB wheel was not downloaded. The version notes only say "Update 2026-09-27".
- Earlier state, for context: the PyPI vLLM 0.19.1 refuses `--enable-lora` for Gemma4 ("does not support LoRA yet"). Only the wheelhouse build adds `SupportsLoRA` (Carson Rodrigues [3528695] in 743213).
- The host's scorer-like setup in the notebook runs vLLM with `enable_lora=True, max_loras=8, max_lora_rank=128` (Getting Started cell 7).

### 1.2 Distillation ruling (thread 742807)
- No ruling yet. Host [3527657], 2026-09-24 10:46 UTC: "We are confering and will have an answer for you soon." The last reply is "any updates? :)" (whoami, 2026-09-27 12:02 UTC), with no host answer after it. https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/742807
- The question asks whether proprietary teacher models are allowed, and what Sections 2.5/2.8 licensing means for adapters trained on their output. It has 37 votes, the most-voted topic.
- Participants raise provider-ToS risk (xz [3528227], Justin Scott [3528232]). Justin Scott plans open-weight KD.

### 1.3 Scoring-run facts from hosts
| Fact | Source |
|---|---|
| Hidden tasks run **sequentially** | 743063 [3527819], 2026-09-24 19:48 UTC |
| The scorer reads **only** `timeout_seconds`, `max_tool_calls`, `max_time_minutes`, `max_turns`. **Default: no limit** | same |
| Hitting 12 h currently **errors** (no score). A fix to score unfinished tasks as 0 is only "planning". Host advice: set `max_time_minutes` "to something moderate as a failsafe" | same. No later confirmation that the fix shipped. On 2026-09-26 07:29 UTC Chandram Dutta [3528559] still reports a 12 h error with no score |
| **Patch validation is excluded from the 12 h** and takes "around two hours" if every task gets a patch. A task with no patch skips validation and scores 0. A no-patch run takes ~10 min | 743663 [3528731], 2026-09-26 11:24 UTC. The Evaluation page also says the 12 h covers sandbox setup but not validation (`kaggle_pages.md:128`) |
| The displayed submission runtime is total wall clock (the asker's premise, not contradicted) | 743663 |
| An unchanged fork of romanrozen's baseline (no eval_config, thinking off) took **14.5 h** wall and **did not error**, scoring 0.08 | Geremie Yeo [3528322] in 743140. Consistent with ~2 h of validation being outside the 12 h |
| "Notebook Exceeded Allowed Compute / requested more CPU, GPU or TPU resources" failures on 09-25/26 were platform-side. Host says it is resolved and he will **rerun affected submissions on Monday** (2026-09-28) | 743683, 2026-09-26 12:01 UTC. Our sub2 `56563379` still shows no score and that error (CLI check 2026-09-27) |
| Scoring sandbox: "The private Docker sandbox uses the same base image but installs a different set of dependencies because the test issues come from a different set of repos." The public failures "may be a problem with the subprocess sandbox" | 742882 [3529110], 2026-09-27 11:12 UTC |
| The metric validates a gold-patch submission at 100% | 742882 [3528750] |
| Custom tools: "Include them as scripts in a skill. They will be available in the sandbox" | 743573 [3528747] |
| ADK: the wheelhouse is the authoritative package set. **No ADK 2.x**. The scoring environment's packages cannot be modified. "Almost any kind of ADK 1.x configuration is allowed". Anything allowing arbitrary code execution is blocked | 743800 [3529108], 2026-09-27 11:05 UTC |
| Only LoRA adapters are accepted. Full fine-tunes are not against the rules, but the system cannot run them and would error | 743383 [3528316], [3528749] |
| Only `gemma-4-31b-it-qat-w4a16-ct` is supported now (the HARNESS_README list of variants is not what is live) | 743056 [3528134] |
| Support for e2b, e4b and 12b, and possibly the 26b MoE and diffusion models, is "hopefully working early next week" (said 2026-09-25) | 743316 [3528212] |
| 4xL4 machines are provided to participants. RTX PRO 6000 is "unlikely" | 743316 [3528212], 743353 [3528277] |

**The 2026-09-25 JUnit pass criterion is not announced in the forum.** It arrived with the silent data re-issue (2026-09-25 18:36-18:40 UTC per busyaprime's notebook `119-of-129-sound-the-gemma-4-grader-rebuilt`). Where it lives:
- `data/HARNESS_README.md:606-609`. `resolved` requires pytest exit code 0 **and** a JUnit XML with `passed_tests > 0`, `failures == 0`, `errors == 0`, and every required node (FAIL_TO_PASS, PASS_TO_PASS, or tests extracted from `test_patch`) passed explicitly, **not skipped**.
- Code: `swegemma/harness/verification.py:144-181` (`_validate_junit_xml`) and `:528-542`.
- busyaprime re-scored 645 agent patches under the old and new rules and found 0 disagreements. 119 of 129 public tasks are "sound" under both rules.
- Test-file edits are discarded before `test_patch` is applied (`HARNESS_README.md:596-597`).

**Phase-2 verification timeout = eval_config `timeout_seconds`.** First raised by Oleksii Zhukov in 743365 and **verified in public code**:
- `swegemma/harness/verification.py:498-503` runs pytest with `timeout=config.harness.command_timeout_seconds`.
- `swegemma/config.py:179-188` sets that value from `timeout_seconds`.
- Agent commands get `min(timeout_seconds, remaining task time)` (`swegemma/tools/execution.py:27-36`).
- So our 180 s also caps the hidden test run of every correct patch. Whether the private scorer script does the same is UNVERIFIED (it is not in the wheelhouse), but it reads the same field.

### 1.4 Hidden test set characteristics
- The test set is "curated from a set of private repositories", ~120 tasks split evenly public/private (Data page, `kaggle_pages.md:81`). The host confirms "a different set of repos" with different dependencies ([3529110]).
- **The public LB has exactly 58 tasks** (Geremie Yeo, 743506). His argument: only n = 58 fits the observed floor-rounded score set {0, 1, 3, 5, 6, 8, 10, 12, 13}. Today's leader, 0.15, is consistent with 9/58 = 0.155. By the host's even split, private ≈ 58-62.
- **The test tasks were reviewed for feasibility; the training tasks were not** (743817 [3529102], 2026-09-27 10:58 UTC):
  - The test set got "much more extensive reviewing and editing". "Impossible" tasks were screened out.
  - The host also checked that a frontier model's failing test case "could have gotten correct with the information given".
  - The training set got no such review, for time and resource reasons.
  - The Data page adds that a frontier model passes, or comes within one test case of passing, each test task (`kaggle_pages.md:79`).
- **Graphs have the same generation as the test set** (Data page line 8), so the public graph defects carry over:
  - **Async functions are absent**: 0 of 305 async defs appear as nodes (Jason Wold, 742911). The host says it is still missing with no ETA ([3528743], 2026-09-26 11:37 UTC).
  - The embeddings share the graph's node set, so `search_similar_code` cannot surface async code either (Oleksii Zhukov [3527552]).
  - There is a single edge type, `calls`, and no module-level nodes.
  - The empty-embedding-file problem is fixed ([3528743]).

### 1.5 eval_config advice
- Host: the four fields only, default unlimited. Set `max_time_minutes` moderate as a failsafe (743063).
- Getting Started notebook: "The only enforced constraint in this competition is a 12 hour inference runtime." Its local demo hardcodes 5 min / 100 calls / 300 s.
- Competitor configs seen:
  - Saltice: 300 s / 35 calls / 12 min / 30 turns. It failed with the platform resource error, not a timeout.
  - Oleksii Zhukov: queued 12 min / 300 s, result not posted.

### 1.6 Thinking, context, tools, time (host side)
- **Host notebook (current, re-run 2026-09-27 10:39 UTC)**:
  - `default_chat_template_kwargs={'enable_thinking': True}`, `max_model_len=32768`, parsers `gemma4`, `gpu_memory_utilization=0.90`, TP=4.
  - Sampling: `temperature 0.2, top_p 0.95, max_output_tokens 16384, thinking_budget 4096, include_thoughts true`.
  - It explicitly removes `thinking_level` because it is "mapped to OpenAI reasoning_effort by LiteLLM".
  - Evidence: `scratchpad/nb2/txt/getting-started-gemma-4-developer-agent.txt:78-86,176-193`.
- **Compaction is unresolved**:
  - HARNESS_README §7.2 says the scorer uses `EventsCompactionConfig(compaction_interval=15, overlap_size=2, token_threshold=32768, event_retention_size=5)`. The notebook uses `token_threshold=14336` (`...txt:269-275`).
  - Two unanswered questions: 743456 (a 32768 threshold equals `max_model_len`, so can compaction ever fire before overflow?) and 743752 (which value the scorer uses, and Docker/gVisor vs subprocess).
  - Treat scorer-side compaction as not rescuing long sessions.
- Competitor claims from reading swegemma 0.2.7 (Oleksii Zhukov, 743365):
  - `include_thoughts: false` sends `enable_thinking: false`. Consistent with our setup.
  - `thinking_budget` is never forwarded to vLLM, so with thinking on only `max_output_tokens` bounds reasoning. **UNVERIFIED by me.**
  - The time cap cancels the in-flight model call. **Verified for the command side**: the command timeout shrinks to the time left (`execution.py:27-36`).

### 1.7 What competitors revealed (scores and techniques)
The LB was read with `kaggle competitions leaderboard --show` on 2026-09-27. The date column is each team's latest submission, not its best.

| Team / source | Public score (tasks/58) | Setup disclosed |
|---|---|---|
| Makus | 0.15 (9) | nothing posted |
| 7 teams incl. Alperen ÖZ, Chandan Ranjan, 暗黑AGI, Daniel Olajide, Jeki Wan Taufik, Daniel Du, I Zaznov | 0.13 (8) | Alperen: plain YAML, no adapters. His 0.13 bundle differs from a later one "only in the thinking settings in sampling.yaml and timeout_seconds" (743213 [3528648]). Which thinking setting got 0.13 is not stated |
| 12 teams incl. us (sub3), Roman Rozen, Whisper Last, Radek, Rahul Rathnavel K, mahmoud al-ghraibeh | 0.12 (7) | Roman Rozen's public notebook: analyzer + coder, temp 0.2, thinking off (`include_thoughts: false`), 8192 output tokens, no eval_config |
| Unchanged fork of Roman Rozen (Geremie Yeo) | 0.08 (5) | Same bundle as the 0.12 above, 14.5 h wall. **The same bundle scored 7 vs 5 tasks**, confounded by the 09-25 data re-issue |
| Oleksii Zhukov | 0.10 (6) | Own coder + read-only analyzer sub-agent, thinking off, no eval_config, no error. Averaged under ~6 min/task over ~120 tasks |
| Oleksii Zhukov | 0.00 | Starter kit minus adapters, `max_time_minutes 5`, **thinking on (thinking_level high)**, scored ~80 min after submit. Tasks likely died early |
| nihilisticneuralnet notebook "[0.10]" | 0.10 | public notebook (not read here) |
| TwangyGarlic449, Narendar Kumar Ale | 0.08 | bare-bones YAML |
| nursrijan starter kit | 0.05 | per ISAKA Tsuyoshi (743140) |
| Official sample_submission as-is | FAILED | Violet Notes 743213. The host said a fix was incoming (09-25 10:55 UTC) |

No competitor has posted a working LoRA result, an RL result, or anything above 0.15. New public notebooks since the last pull, all metadata only and not read:
- tharunkumar369 "Top 1 Master Baseline" (2026-09-27 15:26 UTC)
- tomaszszyrowski "Day1 Baseline" (14:39 UTC)
- cocoyachi "Zero to First Valid Submission" (12:44 UTC)
- norikazuhaji "GTUA - Graph-Tool Utility Audit" (12:24 UTC)
- hitarthjain0 "What Moves the Leaderboard" (09-26)

Source: `kernels.json`.

### 1.8 Other environment facts (public dev path)
- Public wheels lack `typing-inspection`, `inline-snapshot`, `dirty-equals` and `pytest-httpbin`. Released `requests`/`httpx` in site-packages shadows `/workspace`.
- As a result, only 2 of 6 gold controls pass on the public CPU/subprocess path (rdeschamps [3528924]):
  - fastapi_14786 and rich_3043 pass.
  - fastapi_14356 and fastapi_15745 fail collection.
  - requests_7309 and httpx_3672 run the installed package instead of the workspace.
- Host: the private Docker sandbox differs, and he will look at a more reliable notebook setup ([3529110]).
- 4xL4 queue waits of 4-5 h were reported on 2026-09-27 (743600: Kinance [3529170], Penguin [3529197]). CPU sessions start immediately.

---

## 2. Implications for v10 (ranked)

1. **The scorer probably runs the Docker sandbox, where the `/tmp` command-text rewrite does not exist.**
   - The rewrite lives only in the subprocess backend (`swegemma/sandbox/subprocess.py:434-481`). The Docker backend treats `/tmp` as the container's own directory (`swegemma/sandbox/docker.py:220-240`).
   - So the v2-v8 `/tmp/swe` helpers most likely **worked in the scored run**, even though they failed in our pod and Kaggle-notebook runs, which use subprocess.
   - Consequences:
     - (a) sub3's 0.12 probably already reflects working helpers. The v9 path fix alone should not move the LB. The pod gap v4 18 vs v9_c 15 is a subprocess artifact plus noise.
     - (b) The faithful local proxy is v9-style helpers under subprocess, or any helpers under Docker.
     - (c) `helpers_v9/_ws.py:4` already uses `TMPDIR or /tmp`, which is correct for both backends. Keep it.
     - (d) The subprocess backend also rewrites `/workspace`, `/usr/local/bin` and `/wheels` in command text (`subprocess.py:435-479`), while `docker.py` has no `re.sub`/`.replace` rewriting at all. Helper Python code must therefore resolve the repo from its cwd or an argument, never from a hardcoded `/workspace`, to work under both backends.
   - Confidence: medium. The host said "private Docker sandbox" in passing, and htn's direct question in 743752 is unanswered.
2. **Raise `timeout_seconds` from 180 to about 300.**
   - It also bounds the hidden-test pytest run of every correct patch (verified in public code). The hidden repos are private and new, so their test durations are unknown.
   - Raising it costs almost nothing in agent time: commands already get `min(timeout_seconds, time left)`, and our `run.py` applies its own shorter timeouts.
   - The trade-off: a raw hanging command can now eat the rest of a task. Mitigate this by routing test runs through `run.py --timeout`.
3. **Re-derive the 12 h budget with validation excluded.**
   - If sub3's "10.4 h" is the displayed runtime, it is total wall clock including ~2 h of validation, so the agent phase was ≈8.4 h (≈4.2 min/task over ~120 tasks).
   - Worst case at a 6 min cap: 8.4 h + 120 × 1 min = 10.4 h, still under 12 h. At 6.5 min it is ≈11.4 h, which is too tight while overruns still error.
   - So `max_time_minutes: 6` is the most that is defensible, and only if the 10.4 h figure includes validation. UNVERIFIED which it is; check how 10.4 h was measured before changing the cap.
4. **The hidden tasks are cleaner than the public ones.**
   - The host screened out impossible tasks and tasks whose failing test could not be inferred from the issue. That removes most of what our never-solved diagnosis calls "hidden spec" (9) and "underspecified issue" (6), 15 of 39.
   - Take those tasks out of the arena, or report them separately. Otherwise they add noise and push prompt work toward guessing hidden API names.
   - Put effort into execution evidence the issue text supports: a repro test written from the issue, run on the edited and original code, plus a regression gate.
5. **Assume no useful compaction at 32 k.** It is unresolved in the forum, and at `token_threshold = max_model_len` compaction cannot fire before overflow. Keep context under control inside our own stages: `include_contents: none` per stage, head+tail truncated outputs (`run.py`), short file reads. This is aimed at the 13 context overflows in `eval/diagnosis.md`.
6. **Keep helpers and prompts repo-agnostic.**
   - The hidden set comes from different private repos with different dependencies, so drop any fastapi/rich-specific hints.
   - Handle `src/` layouts, missing `tests/` directories, and an installed copy of the package shadowing the workspace. Our `gate.py` should run with the workspace first on `sys.path` (`PYTHONSAFEPATH=1` as in the grader).
   - Graph tools cannot see async code, so the locator should fall back to grep/AST for `async def`.
7. **Grader rules to encode in the fixer and verifier:**
   - Skipped required tests fail the task, so never add skips or `xfail`.
   - Existing (PASS_TO_PASS) tests must pass explicitly.
   - Test-file edits are discarded. In `eval/kaggle/rescore_fair/results.jsonl` they broke `test_patch` application 4 times, so strip test-file hunks from the final patch.
8. **LoRA: a wait-and-verify item, with a new lead.**
   - The vLLM wheel changed on 2026-09-27 10:37 UTC (+62 B). If Carson approves the 433 MB download, check two things: whether `Gemma4SelfDecoderLayers` still registers `decoder_layers` as a submodule, and whether Whisper Last's repro (random `lora_B`, compare base vs adapter logprobs at T=0) still gives identical outputs.
   - Until that is checked, a LoRA scores like the base model.
   - Training data must avoid proprietary-teacher distillation until the host rules. Use open-weight teachers or Gemma's own verified trajectories.
9. **Single-submission comparisons are noise.** The same bundle scored 7/58 and 5/58. Leader 0.15 vs our 0.12 is 2 tasks. Rely on paired local arenas, and treat any LB delta under about 3 tasks as noise.
10. **Wheelhouse drift.**
    - `adk_submission-0.2.11` changed on 2026-09-27 (v24: 62,356 to 62,404 B). Our local copy (`harness/wheels/adk_submission-0.2.11-py3-none-any.whl`, 62,356 B) predates it.
    - Re-sync and diff before the next local validation. What changed is UNVERIFIED; it needs a 62 KB download, which requires Carson's approval.
11. **Model menu may widen next week** (26B-A4B MoE, 12B, e4b, e2b). A 4B-active MoE could be several times faster on L4. That would make best-of-N with execution-based selection affordable inside 12 h, which is the most plausible path to 0.30. The host has not said whether one base model per submission still applies (the README rule says yes).
12. Expect sub2 (`56563379`, the v2 bundle) to be rerun on Monday 2026-09-28 at no cost. That gives one more scored data point.

## 3. Open questions (unanswered in the forum as of 2026-09-27 16:15 UTC)
- 743752: which compaction threshold the scorer uses (32768 or 14336); whether it passes `default_chat_template_kwargs` `enable_thinking`; Docker/gVisor vs subprocess.
- 743456: can compaction ever fire before `ContextWindowExceededError`?
- 742807: distillation from proprietary models.
- 743063 follow-up: has "score unfinished tasks as 0" shipped?
- 743508: is the 2026-09-27 vLLM wheel the LoRA fix?
- 743751: sub-agent count and depth limits; whether sub-agent calls count against the task time (by construction they do, since the task timer is wall clock).
- 742911: an ETA for async nodes in the graphs.

## 4. Thread index (all 39)
| id | posted (UTC) | title (short) | host reply? |
|---|---|---|---|
| 742807 | 09-23 15:38 | Distillation from external LLMs | "conferring", no ruling |
| 742815 | 09-23 16:34 | Getting started + Discord (Kaggle) | host post |
| 742882 | 09-23 21:47 | swegemma harness for local eval | wheelhouse, notebook, Docker vs subprocess |
| 742911 | 09-24 03:08 | Empty graph/embedding files; no async | embeddings fixed; async missing |
| 743007 | 09-24 15:59 | Welcome (Google) | host post |
| 743056 | 09-24 19:01 | Allowed Gemma variants | only 31B QAT |
| 743063 | 09-24 19:22 | Concurrency, eval_config keys, 12 h | sequential; 4 keys; errors at 12 h |
| 743106 | 09-24 22:52 | GPU access | no |
| 743140 | 09-25 02:09 | Representative submission results | no |
| 743162 | 09-25 04:19 | 12 h limit behaviour | no (points to 743063) |
| 743186 | 09-25 06:08 | Post-training infra | no |
| 743213 | 09-25 08:40 | Sample submission FAILED / resource errors | fix incoming; resolved |
| 743241 | 09-25 10:36 | Accessibility email request | no |
| 743263 | 09-25 12:42 | Minor eligibility | no |
| 743275 | 09-25 13:53 | Past competition references | no |
| 743297 | 09-25 14:50 | Russia prize payout | no |
| 743308 | 09-25 16:08 | VRAM to run locally | no |
| 743316 | 09-25 16:31 | "$65k cheaper than GPUs" | more variants next week; 4xL4 provided |
| 743353 | 09-25 18:09 | Cannot download data | re-uploading; RTX PRO unlikely |
| 743365 | 09-25 18:40 | Budgeting the 12 h run (Oleksii) | no |
| 743383 | 09-25 20:22 | Only LoRA? | LoRA only |
| 743456 | 09-26 04:45 | Compaction before context limit? | **no** |
| 743457 | 09-26 04:46 | First scored run 0.08 | no |
| 743506 | 09-26 06:00 | Public LB has 58 tasks | no |
| 743508 | 09-26 06:03 | LoRA silently wiped | "I will address" |
| 743531 | 09-26 06:45 | Small-model LB? | no |
| 743566 | 09-26 08:23 | Docker local eval missing typing_inspection | no |
| 743573 | 09-26 08:40 | Custom Python tools | scripts in a skill |
| 743600 | 09-26 09:13 | L4x4 queued / system error | no |
| 743661 | 09-26 10:41 | "Notebook Exceeded Allowed Compute" | (see 743683) |
| 743663 | 09-26 10:43 | Patch validation time | ~2 h, excluded; no patch skips it |
| 743683 | 09-26 12:01 | Rerunning failed submissions (host) | rerun Monday |
| 743687 | 09-26 12:22 | Off-topic (climate) | no |
| 743715 | 09-26 14:58 | Computing resources | no |
| 743743 | 09-26 18:55 | llama.cpp GGUF locally | no |
| 743751 | 09-26 19:32 | Architecture + graph questions | **no** |
| 743752 | 09-26 19:39 | Scorer config (compaction, sandbox) | **no** |
| 743800 | 09-27 06:28 | ADK versions / YAML features | wheelhouse authoritative; ADK 1.x only |
| 743817 | 09-27 08:11 | Task verification (infeasible train task) | test set reviewed; train not |
