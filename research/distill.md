# Distillation readiness: rules, trajectory sources, teacher cost, expected gain

Written 2026-09-30 (IST). Read-only for the project: no Kaggle submission or kernel push, no pod, no forum post,
$0 OpenRouter spend. Network reads were the Kaggle forum API, Hugging Face dataset and model cards, arXiv and two blog
pages, the public OpenRouter price list and two API-terms pages. Kaggle API times are UTC and are shown with IST.

Labels:
- **VERIFIED**: read from a primary source this session (path, URL or command given).
- **DATA**: counted in our own run artifacts.
- **ESTIMATE**: my arithmetic on the numbers shown. Not measured.
- **UNVERIFIED**: secondary source or not checked.
- **INFERENCE**: my reading of verified facts.

Evidence copies (the scratchpad is temporary): `research/distill_evidence/`, holding the three forum threads as JSON,
the OpenRouter price extract of 2026-09-30, `cost.py` and `cost.out`, `tokstats.py`, `cachestats.py`, `toolmix.py`
and `toolmix_cachestats.out`. Other keys: FI = `docs/v11/facts_internal.md`, FE = `docs/v11/facts_external.md`,
PLAN = `docs/v11/PLAN.md`. The forum draft is `docs/v11/forum_question_distillation.md`.

---

## 0. Bottom line, ranked by how much it changes the plan

1. **The host has already answered the distillation question, one day after the 09-28 "soon".** (VERIFIED)
   - 742807, comment 3530102, Ashley Oldacre (Kaggle Competitions Program Manager), 2026-09-29 14:58 UTC (20:28 IST).
     Quote: "As long as you are using those models in accordance with their model license terms, and the output
     you're using to submit to that competition doesn't 'conflict with the license requirement of the rules of this
     competition, you may use them."
   - My reading (INFERENCE): teachers under permissive licences (Qwen3-Coder: Apache-2.0; DeepSeek-V4: MIT; gpt-oss:
     Apache-2.0) look cleared. Claude, Gemini and probably GPT look excluded, because their API terms bar using the
     service to train competing models (quotes in section 2.2). One participant already reads it that way. No host
     has confirmed that reading.
   - The forum draft is therefore a short follow-up with four precise questions, not the original question.
2. **Nobody has yet shown an adapter changing outputs on the current wheelhouse.** (VERIFIED, forum)
   - 743508, Abdul Muiz, 2026-09-29 10:55 UTC (16:25 IST), on Kaggle 4×L4. With the sample adapter's `lora_B` set to
     N(0,1), base and adapter outputs were identical, logprobs included. `/v1/models` listed no adapter.
   - His own caveat: if the sample's `lora_A` is all zeros, that alone explains it. A re-run is promised. The host has
     not replied.
   - Every distillation plan is still gated on PLAN's G-A probe. It cannot run until the Kaggle GPU quota resets.
3. **Public trajectory datasets do not match v10.1's action space.** (DATA)
   - In the 27 resolved v10.1 runs (pod pair, `eval/pair1/eval/runs/p1_v10`), 85.2% of 765 calls are `/tmp/swe`
     helper commands sent through `run_command`. The native file tools (`read_file`, `edit_file`, `write_file`) are 4.7%.
   - Every public dataset is in an OpenHands, SWE-agent or mini-swe-agent format. `convert_nebius.py` maps those onto
     the native tool schema, i.e. onto the ~5% of what v10.1 actually does.
   - So public data fits a v4-style bundle, or needs replay (re-running every action in a real environment) to become
     v10.1 data. Once environments exist for replay, running a teacher through v10.1 itself is cheaper and exact.
4. **The best-fitting data is a permissively licensed teacher run through our own v10.1 pipeline.** (ESTIMATE)
   - Per task-run: $0.012 (gpt-oss-120b) to $0.04 (Qwen3-Coder-480B) to $0.19 (Claude Sonnet 5.5, likely not allowed),
     with prompt caching. Details in section 4.
   - Per 1,000 verified, L4-feasible trajectories: about $25-70 (DeepSeek-V4.1-Flash), $67-157 (Qwen3-Coder-480B),
     or $318-833 (Claude Sonnet 5.5).
   - Dollars are not the constraint: **task supply and environments are.** SWE-Pallets-X (476 tasks, about 390 trainable)
     yields roughly 400-600 verified trajectories at most 3 per task. 1k needs SWE-rebench or SWE-Gym environments;
     5k needs about 3,000-5,000 tasks, i.e. SWE-rebench at scale.
   - The golden-eval router already forwards harness calls to any OpenRouter model (`scripts/golden/router.py:511-527`,
     `--upstream-model`, `--max-usd`). It is being built by another workflow, so I did not touch it.
5. **Expected hidden-set gain of a LoRA SFT on 1k-5k verified teacher trajectories: about +1 to +2 public tasks.**
   (ESTIMATE, section 5)
   - Central: +1.6 tasks at 1k (0.12 → 0.15) and +2.2 at 5k (0.12 → 0.16).
   - Range: +0.7 to +3.5 at 1k (0.13-0.18); +0.9 to +4.8 at 5k (0.14-0.20).
   - 0.20 needs +5 tasks (7 → 12 of 58), a +71% relative gain. Only the most favourable end of the 5k range reaches it.
   - My odds of 0.20 from distillation alone (INFERENCE): ≤ 5% for 5k teacher data after the LoRA gate, about 2% for 1k,
     under 1% for self-RFT (PLAN's current v11).
   - Self-RFT on Gemma's own outputs stays near zero in the literature: 19.0 → 19.7 in one setting, 15.3 → 8.7 in the
     other (SWE-Gym).
6. **5k teacher trajectories do not fit the v11 training budget; 1k does.** (ESTIMATE from FE §2.5)
   - 1k × ~15k tokens is about $15-60 per epoch on the 2×H100 pod; 5k is $73-300 per epoch. The v11 cap is $250,
     and nothing of it is spent yet.

---

## 1. Readiness checklist

| item | state (2026-09-30 IST) | evidence | blocks |
|---|---|---|---|
| Ruling on own outputs | Allowed | 743964, Ryan Holbrook, 2026-09-28 10:32 UTC (16:02 IST) | — |
| Ruling on other models | Allowed "in accordance with their model license terms" and without conflicting with the rules' licence requirement | 742807 comment 3530102, 2026-09-29 14:58 UTC | Teacher choice. Follow-up drafted |
| LoRA changes outputs on the scorer | **Not shown.** One re-test on the current wheelhouse, 09-29: no change (caveat on `lora_A`) | 743508 comment by Abdul Muiz | Everything below |
| G-A probe (Kaggle 4×L4) | Not run. Weekly GPU quota exhausted 09-29 | project memory; PLAN §2 | LoRA gate |
| Scorer-exact renderer (P0.2) | Not built. `train/` holds only `sft.py`, `convert_nebius.py`, `harness_tools.json`, `sft_system.md` | `ls train/` | SFT data |
| SFT builder, trainer, exporter (P0.3-P0.5) | Not built. `sft.py` has never taken a training step | FI §5.1, §5.4 | Training |
| Teacher plumbing | Router with `--upstream-model` and a USD cap exists in the golden-eval build | `scripts/golden/router.py:511-527`, `docs/eval/GOLDEN_EVALS_SPEC.md:391-402` | — (reuse, don't edit) |
| Pallets tasks on disk | `data/pallets/tasks.jsonl` has 476 rows. 210 snapshot dirs present at 01:28 IST today (a download seems to be in progress) | `ls data/pallets/snapshots` | Env adapter (P0.8) not built |
| SWE-rebench / SWE-Gym envs | Not downloaded, no adapter | — | 1k+ trajectories |
| Converted public data | 6,395 rows from nebius (of 67,074), off-scorer format, pre-v10 tools | `backups/backups/20260926T095858Z-train1/convert_all.log`; FI §5.2 | Ruling Q2, format |
| Money | v11 cap $250, $0 spent; about $404 of the $500 total left (FI §6) | PLAN §0 | — |

---

## 2. The rules as of 2026-09-30

### 2.1 Host statements, in order

| when (UTC / IST) | who, where | what |
|---|---|---|
| 09-24 10:46 / 16:16 | Ryan Holbrook, 742807 | "We are confering and will have an answer for you soon." |
| 09-28 10:32 / 16:02 | Ryan Holbrook, 743964 | "Training on gemma-4-31b itself is fine. We'll try to have an answer for outputs from other models soon." |
| 09-29 14:58 / 20:28 | Ashley Oldacre, 742807 (comment 3530102) | Other models may be used "in accordance with their model license terms" if the output "doesn't 'conflict with the license requirement of the rules of this competition" |
| 09-29 15:10 / 20:40 | JohnParkerson (participant), 742807 | "So models like Claude and GPT are off the table, but Muse and Chinese aren't?" No host reply |

- Source: `kaggle competitions topics show gemma-4-developer-agent 742807 --format json` (copy in
  `research/distill_evidence/t742807.json`).
- Ashley Oldacre's role: web search returns her LinkedIn ("Kaggle Competitions Program Manager") and an X post about
  joining Kaggle's competitions team. The competition page is among the results. The API has no staff flag, so the
  badge still needs one look in the browser.

### 2.2 The rule text and the teacher terms that the ruling points to (VERIFIED)
- **Winner licence** (`SP/kaggle_pages.md:150`, `:178-186`): Apache 2.0. Winners license the submission and the code
  that generated it under an OSI licence "that in no event limits commercial use". Input data or pretrained models with
  an incompatible licence are exempt from that grant (`:186`). Winners must also represent that they "have the
  unrestricted right to grant that license" (`:218`).
- **External data** (`:192-198`): allowed if "publicly available and equally accessible ... at no cost", or if it meets
  the Reasonableness Standard. Buying data that costs more than a prize is the given example of "not reasonable".
- **Anthropic Commercial Terms**, D.4 (effective 2025-06-17): "Customer may not and must not attempt to (a) access the
  Services to build a competing product or service, including to train competing AI models ... except as expressly
  approved by Anthropic." https://www.anthropic.com/legal/commercial-terms
- **Gemini API Additional Terms** (modified 2026-04-28): "You may not use the Services to develop models that compete
  with the Services (e.g., Gemini API or Google AI Studio)." https://ai.google.dev/gemini-api/terms
- **OpenAI**: both terms pages returned HTTP 403 to the fetcher. The usual clause ("use Output to develop models that
  compete with OpenAI") is **UNVERIFIED** here.
- **Open-weight licences** (HF model cards, VERIFIED): Qwen3-Coder-480B-A35B-Instruct and Qwen3-Coder-Next are
  Apache-2.0. DeepSeek-V3-0324 and every DeepSeek-V4 / V4.1 card are MIT. gpt-oss-120b is Apache-2.0. GLM-4.6, GLM-5.2
  and GLM-5.3-Flash are MIT. **GLM-5.3, Kimi-K2 and MiniMax-M2 are "other"** (custom text, not read here). The original
  DeepSeek-V3 card has no licence tag.

### 2.3 Status by teacher class (INFERENCE unless noted)

| class | examples | status | what would settle it |
|---|---|---|---|
| Gemma-4-31B's own outputs, served checkpoint | our pod and Kaggle runs | **Allowed** (VERIFIED, 743964) | — |
| Gemma-4-31B bf16 (`google/gemma-4-31B-it`) with thinking on, as a privileged self-teacher | OpenRouter `google/gemma-4-31b-it` | Probably covered by "gemma-4-31b itself". Different checkpoint | Draft Q4 |
| Open-weight, Apache-2.0 or MIT | Qwen3-Coder-480B, Qwen3-Coder-Next, DeepSeek-V4, gpt-oss-120b, GLM-5.2 | Likely allowed. The licence places no limit on outputs, and the adapter can be Apache-2.0 | Draft Q1 |
| Open-weight, custom licence | Kimi-K2.x, MiniMax-M2/M3, GLM-5.3 | Read each licence first | Licence text |
| Public datasets made by other models | nebius, nvidia SWE-Hero (Qwen3-Coder-480B, CC-BY-4.0) | Likely allowed as external data, since the teacher is Apache-2.0 | Draft Q2 |
| Public datasets made by API models | SWE-smith, SWE-Gym, R2E-Gym, SWE-Next (Claude, GPT-4o, GPT-5-mini) | Doubtful. The dataset licence is MIT, but the teacher terms bar competing models | Draft Q3 |
| API models, directly | Claude, Gemini, GPT | Doubtful for the same reason | Draft Q3 |

A routing caveat (INFERENCE): calling an open-weight model through OpenRouter also puts the hosting provider's and
OpenRouter's terms in play. Pin a provider with `{"provider": {"order": [...], "allow_fallbacks": false}}`, which the
golden router already supports (`--or-provider`), and read that provider's terms once.

---

## 3. Survey of usable trajectory sources

### 3.1 Released trajectory datasets (VERIFIED from HF cards and the cited papers; counts are the cards' or the nebius comparison table's)

| dataset | trajectories (resolved) | licence | teacher (its licence) | scaffold, tool format | repos, task type | cleared? |
|---|---|---|---|---|---|---|
| `nebius/SWE-rebench-openhands-trajectories` | 67,074 (32,161 resolved; 3,792 issues resolved); avg 64.3 turns | CC-BY-4.0 | Qwen3-Coder-480B-A35B (Apache-2.0) | OpenHands 0.54, function calls: `execute_bash`, `str_replace_editor`, `think`, `finish`, `task_tracker` | 1,823 repos, real issues | Likely (Q2) |
| `nvidia/SWE-Hero-openhands-trajectories` | 34,269 on 11,766 issues. The card has no `resolved` field; "execution-based" per the paper title (UNVERIFIED per row) | CC-BY-4.0; per-row repo licence column (MIT, Apache-2.0, BSD only) | Qwen3-Coder-480B (Apache-2.0) | OpenHands, function calls | SWE-Gym, R2E-Gym-Subset, SWE-rebench issues; issue text partly rewritten by the teacher | Likely (Q2) |
| `nvidia/SWE-Zero-openhands-trajectories` | 318,100, **execution-free** (not verified) | CC-BY-4.0 | Qwen3-Coder-480B | OpenHands | many | Fails the verified-passing rule |
| `SWE-bench/SWE-smith-trajectories` | 76.0K rows over 3 format splits (`ticks`, `tool`, `xml`); per nebius table 49,897 (21,513 successful), 7,270 issues resolved; the SWE-agent-LM-32B set is 5,017 | MIT | claude-3-7-sonnet, claude-3-5-sonnet, gpt-4o (API terms) | SWE-agent; the `tool` split uses function calls | 129 repos, synthetic bugs, LM-written issues | Doubtful (Q3) |
| `SWE-Gym/OpenHands-SFT-Trajectories` | 491 (all successful), ~18.6k tokens each (Qwen tokenizer, paper Table 8) | MIT | gpt-4o-2024-08-06, claude-3-5-sonnet-20241022 | OpenHands CodeAct; `messages` are role/content only, so actions are in text | 11 repos, real | Doubtful (Q3) |
| `SWE-Gym/OpenHands-Sampled-Trajectories` | 6,055 raw (491 successful per nebius table) | none on card | same | OpenHands, function calls | 11 repos | Doubtful |
| `R2E-Gym/R2EGym-SFT-Trajectories` | 3,231 (paper: 3,321 successful on 2,048 tasks) | **none on card** | Claude 3.5 Sonnet v2 (API terms) | R2E-Gym (OpenHands-like), role/content only | ~10 repos, real commits with synthetic issue text | Doubtful |
| `TIGER-Lab/SWE-Next-SFT-Trajectories` | 3,693 on 2,308 tasks | MIT | Claude 4.5 Sonnet, GPT-5-mini (arXiv 2603.20691) | R2E-Gym scaffold, ShareGPT role/content | from 3,971 seed repos | Doubtful |
| `zai-org/SWE-Dev-train` | `sft` 17,871 **unevaluated** + `rft` 2,276 correct | **none on card** | DeepSeek-V3 (arXiv 2506.07636; which V3 release, and so which licence, is not stated) | OpenHands, 30 iterations | 38k instances, 4,413 repos (paper) | Only the 2.3k `rft` split is verified; licence unclear |
| `SWE-Factory/DeepSWE-Agent-Kimi-K2-Trajectories-2.8K` | 2.8K; card is empty | MIT | Kimi-K2 (custom licence) | DeepSWE / R2E-Gym, role/content | unknown | Read the Kimi licence |
| `Kwai-Klear/SWE-smith-mini_swe_agent_plus-trajectories-66k` | 65,994 (all successful per nebius table) | MIT | **undisclosed** | mini-swe-agent-plus: bash only, no function calls | 123 repos, synthetic | **No**: the teacher's licence cannot be checked |
| `nebius/SWE-agent-trajectories` | 80,036 (13,389 successful), 838 issues resolved | CC-BY-4.0 | Qwen2.5-72B-Instruct (custom), Llama3-70B-Instruct (Llama 3 licence; its clause on improving other LLMs is UNVERIFIED here) | SWE-agent, closed-source fork, no function calls | 1,202 repos | Doubtful and weak (2024 teachers) |
| Kimi-Dev | **no training data released** (repo README) | — | — | — | — | n/a |
| SWE-RL | **no data released**; code is CC BY-NC 4.0 (README) | — | — | — | — | n/a (NC also conflicts with Apache) |

### 3.2 Task sets for self-generated trajectories (VERIFIED unless marked)

| task set | tasks | repos | licence | environment | fit |
|---|---|---|---|---|---|
| SWE-Pallets-X v4 (on disk: `data/pallets/`) | 476: pytest 132, sympy 129, click 109, werkzeug 43, flask 29, jinja2 29, markupsafe 4, itsdangerous 1 | 8 | CC0-1.0 | per-instance `uv` venv with era-pinned deps (its `pipeline/`); competition format with graphs | Best first source. PLAN holds out werkzeug, leaving ~390 train tasks after a 10% val split |
| SWE-rebench (`nebius/SWE-rebench`) | 21,336 `test` + 6,542 `filtered` | 3,400+ | CC-BY-4.0 | `install_config` (python, pip packages, install, test_cmd) for Docker-free venvs; 7,500 Docker images | Scale source for 1k-5k |
| SWE-Gym | 2,438 | 11 | MIT | per-instance Docker images | Needs Docker |
| SWE-smith-py | 50,908 | 131 | MIT | Docker image per repo; LM-written issues | Needs Docker |
| R2E-Gym-Subset | 4.6k | ~10 | Apache-2.0 | Docker | Needs Docker |

Docker cannot run inside a RunPod pod container (UNVERIFIED, general RunPod behaviour). Teacher generation needs no
GPU, so the sandbox can run on the Mac or a CPU VM.

### 3.3 Conversion effort

**(a) To our harness tool schema (`train/harness_tools.json`: `run_command, read_file, write_file, edit_file,
submit_patch, get_status` + 3 graph tools).**

| source family | mapping | effort (ESTIMATE) |
|---|---|---|
| OpenHands function calls (nebius, SWE-Hero) | Done in `convert_nebius.py`: `execute_bash` → `run_command`, `str_replace_editor` view/str_replace/create → `read_file`/`edit_file`/`write_file`, `finish` → `submit_patch`. SWE-Hero needs a small change (no `resolved` column) | 0.5 h |
| SWE-agent `tool` split (SWE-smith) | `bash` → `run_command`, same editor mapping, `submit` → `submit_patch` | 0.5 day |
| Text-action formats (SWE-Gym SFT, R2E-Gym, SWE-Next, SWE-Dev, Kimi-K2 set) | Parse function calls out of message text, then as above | 1 day each |
| Bash-only (Kwai, mini-swe-agent) | Everything becomes `run_command`, including edits (sed/heredoc) | 0.5 day; teaches no `edit_file` |

Measured yield of (a) on nebius: 6,395 kept of 67,074 rows (about 20% of the 32,161 resolved). Rejections: `too_long`
12,248, `too_many_turns` (> 60) 10,289, `is_input` 2,146, no submit 1,020 (`convert_all.log`). Most nebius trajectories
are longer than our 5-minute L4 budget allows: they average 64.3 turns, against 32 calls in our resolved v10.1 runs.

**(b) To the scorer's exact prompt format.** Every external source also needs FI §5.2's list: the June template,
double-encoded tool results with `ensure_ascii=False`, OpenAI content parts, the first-call thought channel, and the
bundle's stage prompts and 12-13 tool declarations instead of `sft_system.md`. Those rules come from our own renderer,
which is not built yet (P0.2).

**(c) To v10.1's action space. This is the real gap.** (DATA, `research/distill_evidence/toolmix_cachestats.out`)

| run | helper calls (`python3 /tmp/swe/*.py` via `run_command`) | native file tools | `run_skill_script` + `submit_patch` | raw commands + pytest |
|---|---|---|---|---|
| v10.1, pod pair (`p1_v10`), 27 resolved, 765 calls | **85.2%**: run 21.2, view 19.9, verify 19.0, edit 8.4, grep 5.5, locate 3.8, status 3.7, finalize 3.5 | **4.7%** | 7.0% | 3.0% |
| v10.0, race 2 round 1 (`r2_v10_1`), 25 resolved, 719 calls | 65.1% | 18.8% | 7.0% | 9.2% |

- v10.1 also has 5 stages with `include_contents: none`: setup, locator, fixer, verifier and submitter. Each stage
  sees only the previous stage's final text.
- A monolithic OpenHands trajectory has no stage boundaries, no helper calls, and none of the helpers' outputs (the
  LOCATE ranking, the VIEWED line, `k/n claims fixed`, READY and so on).
- Rewriting it into v10.1 means splitting it into stages, mapping actions to helpers, and **re-executing** every action
  to get real helper output. That needs the task's environment.
- (INFERENCE) Once the environment exists, running the teacher through v10.1 directly costs cents per task and gives
  exact data. So replay only makes sense if the teacher itself is unavailable.
- Training v10.1's adapter on native-schema data risks pulling the model back toward `edit_file`. In older bundles that
  tool had a 67% malformed rate (race 1: 3,535 of 5,278 calls, `research/competitors.md:22`, `:329`), which v10's
  helpers were built to avoid.

### 3.4 Verdict per source (INFERENCE)

| use | best source | why |
|---|---|---|
| v10.1 adapter | A permissive teacher run through v10.1 on Pallets-X, then SWE-rebench | Exact format, verified by our own tests, L4-timed |
| Experiment with a v4-style bundle (native tools) | nebius + SWE-Hero, converted with `convert_nebius.py` | Largest cleared-looking sets (Qwen3-Coder, CC-BY-4.0) that need almost no code; still off-scorer-format per (b) |
| Paper-track resource | Our own v10.1 teacher and Gemma runs | Redistributable if the teacher is Apache/MIT and the tasks are CC0/CC-BY |
| Do not use | Kwai 66k (teacher unknown), SWE-Zero (unverified), SWE-RL / Kimi-Dev (no data), API-teacher sets until Q3 is answered | — |

---

## 4. Cost of a self-generated set (teacher through our v10.1 pipeline)

### 4.1 Token profile per task-run (DATA, Gemma tokenizer)
Source: 73 traced tasks of the v10.1 pod pair (`eval/pair1/eval/runs/p1_v10`); `cachestats.py`. "Cached" counts the
part of each call's prompt that equals the previous prompt plus completion of the same stage, i.e. what provider
prefix caching can reuse.

| population | calls | uncached prompt tokens | cacheable prompt tokens | completion tokens |
|---|---|---|---|---|
| all 73 tasks | 43.0 | 27,618 | 249,239 (90% of prompt) | 3,384 |
| 27 resolved | 32.2 | 23,518 | 167,770 | 2,821 |
| v10.0 race 2 round 1, 74 tasks (check) | 45.9 | 30,740 | 280,916 | 3,702 |

### 4.2 Price and cost per task-run (ESTIMATE; prices VERIFIED from `https://openrouter.ai/api/v1/models` on 2026-09-30)
Assumptions, each a guess:
- The teacher's call and token counts match Gemma's. A 2× completion column covers wordier teachers.
- Thinking is **off**. Reasoning tokens would multiply output cost, and the scorer runs Gemma without thoughts.
- Tokenizer factor vs Gemma's 262k vocabulary: 1.10 (UNVERIFIED), and 1.25 for Anthropic.
- Anthropic cache writes cost 1.25× input. Caching needs `cache_control` to reach Anthropic through LiteLLM and
  OpenRouter (UNVERIFIED), otherwise the no-cache column applies.

| teacher (licence) | in / out / cache-read $ per M | $/run cached | $/run, 2× output | $/run, no cache |
|---|---|---|---|---|
| google/gemma-4-31b-it bf16 (own family) | 0.09 / 0.34 / 0.05 | 0.016 | 0.017 | 0.026 |
| openai/gpt-oss-120b (Apache-2.0) | 0.037 / 0.17 / — | 0.012 | 0.013 | 0.012 |
| qwen/qwen3-coder-next (Apache-2.0) | 0.12 / 0.80 / 0.07 | 0.026 | 0.029 | 0.040 |
| qwen/qwen3-coder, 480B-A35B (Apache-2.0) | 0.30 / 1.00 / 0.10 | 0.040 | 0.044 | 0.095 |
| deepseek/deepseek-v4.1-flash (MIT) | 0.30 / 1.20 / 0.006 | 0.015 | 0.020 | 0.096 |
| deepseek/deepseek-v4-pro (MIT) | 0.924 / 1.849 / 0.077 | 0.056 | 0.063 | 0.288 |
| moonshotai/kimi-k2.7-code (custom) | 0.656 / 3.30 / 0.18 | 0.082 | 0.094 | 0.212 |
| z-ai/glm-5.3 (custom) | 1.40 / 4.40 / 0.26 | 0.130 | 0.147 | 0.443 |
| google/gemini-3.8-flash (API terms) | 0.75 / 3.75 / 0.075 | 0.057 | 0.071 | 0.242 |
| openai/gpt-5.6-sol (API terms) | 2.00 / 10.0 / 0.20 | 0.153 | 0.190 | 0.646 |
| anthropic/claude-sonnet-5.5 (API terms) | 2.00 / 10.0 / 0.20 | 0.191 | 0.233 | 0.734 |
| anthropic/claude-opus-5.5 (API terms) | 4.00 / 20.0 / 0.20 | 0.320 | 0.404 | 1.469 |

For scale: our own Gemma runs on the 2×H100 pod cost about $0.05 per task-run (FE §4, from the ledger). The cheap
open-weight teachers cost less than our own pod time.

### 4.3 Yield: runs per verified, L4-feasible trajectory (ESTIMATE)
- **Solve rate of a teacher inside v10.1: unmeasured.** Band 35-60%. Reference points, all in their own scaffolds with
  no 5-minute cap:
  - Qwen3-Coder-480B resolved 32,161 of 67,074 SWE-rebench attempts (48%).
  - Claude 3.7 in SWE-smith: 6,457 of 17,906 attempts (36%) (`SP/lit/pdfs/2504.21798.txt:366`).
  - Our own Gemma v10.1 on the public 74: 27 (36%).
- **L4-feasibility filter** (0.99 s/call + 26.5 ms per completion token ≤ 290 s, PLAN §4): all 27 resolved v10.1 runs
  pass (median 91 s, max 259 s) and 81% are under 150 s. Teachers may write longer trajectories: assume 80-100% pass.
- Runs per 1,000 kept trajectories: 1,667 to 3,571. For Gemma bf16 as self-teacher (solve 30-40%): 2,500 to 4,167.

| teacher | runs per 1k kept | **$ per 1k kept** | $ per 5k kept |
|---|---|---|---|
| gpt-oss-120b | 1,667-3,571 | 20-45 | 100-225 |
| DeepSeek-V4.1-Flash | 1,667-3,571 | 25-70 | 125-350 |
| Gemma-4-31B bf16 (self-teacher, thinking off) | 2,500-4,167 | 40-72 | 200-360 |
| Qwen3-Coder-480B | 1,667-3,571 | 67-157 | 335-785 |
| DeepSeek-V4-Pro | 1,667-3,571 | 94-225 | 470-1,125 |
| Gemini 3.8 Flash (if allowed) | 1,667-3,571 | 96-255 | 480-1,275 |
| Claude Sonnet 5.5 (if allowed) | 1,667-3,571 | 318-833 | 1,590-4,165 |

Without prompt caching, multiply the open-weight rows by about 2-6× and the API rows by about 4×. Pilot 40 tasks first
at $0.50-8 (Qwen3-Coder: about $1.60) to replace the solve-rate band with a measurement.

### 4.4 Task supply (ESTIMATE)
- **Pallets-X alone gives 400-600 kept trajectories, not 1k.** About 390 train tasks × 3 samples × 35-60% solve gives
  410-700 successes. Task-level correlation lowers that, and the cap is 3 per task (SWE-Gym and SWE-smith both found
  more repeats of easy tasks hurt).
- **1k** needs roughly 700-1,000 tasks: Pallets plus about 400-600 SWE-rebench `filtered` tasks (6,542 available).
- **5k** needs about 3,000-5,000 tasks with 2-3 samples each: SWE-rebench at scale (21,336 `test` tasks, 3,400+ repos).
  Repo diversity is the variable with the clearest transfer evidence: SWE-smith 7B, 4 → 100 repos, 10.3 → 15.1.
- Exclude fastapi, rich, requests and httpx from training. They are the public set and our only faithful yardstick.

### 4.5 Engineering and wall time (ESTIMATE)
- Pallets env adapter: 6 h (PLAN P0.8). SWE-rebench venv adapter plus snapshot and `tasks.jsonl` conversion: about 1-2
  days. Its `install_config` makes Docker-free venvs feasible (FE §4). No graphs ship with SWE-rebench, so the harness
  prompt would lack the "Code Intelligence Tools" section that graph-bearing tasks get (`agent_runner.py:144-183`).
  Either build graphs or accept that small prompt mismatch.
- Teacher runs through the golden router: reuse, not new code. Settings to pin:
  - `parallel_tool_calls` off (the scorer does not support parallel calls, 743964);
  - thinking off;
  - a provider pinned;
  - compaction threshold scaled by the tokenizer ratio, so compaction fires at the same Gemma-token context as the
    scorer's 14,336;
  - a generous time cap, with the L4 re-time filter applied afterwards.
- Wall: about 40 calls at 2-10 s each is 2-7 min per task. At `-j 6`, 1k runs take about 6-20 h on one CPU host.
  sympy and pytest test suites dominate sandbox time (UNVERIFIED). Respect the ≤ 2 local waiters rule while the
  golden-eval build runs.

### 4.6 Training cost (ESTIMATE, FE §2.5 throughput band 486-2,000 tok/s on 2×H100 at $6.98/h)
| kept trajectories | tokens per epoch (~15k each) | $ per epoch | fits v11 cap ($250 total)? |
|---|---|---|---|
| 1,000 | 15 M | 15-60 | Yes, with 2 epochs and eval |
| 5,000 | 75 M | 73-300 | Only at the fast end, 1 epoch |

---

## 5. Plausible hidden-set gain from an SFT adapter on 1k-5k verified trajectories

### 5.1 Published evidence (VERIFIED from the papers, cards and blog cited)

| work | student and base score | data | method | after | fresh or held-out tasks |
|---|---|---|---|---|---|
| SWE-Gym, arXiv 2412.21139 | Qwen2.5-Coder-32B, Verified 7.0, Lite 3.0 | 491 teacher (gpt-4o + claude-3.5) | OpenHands SFT | Verified 20.6, Lite 15.3 | — |
| SWE-Gym self-improvement | fine-tuned 32B | + own successes | RFT | MoatlessTools 19.0 → 19.7 → 19.7; OpenHands 15.3 → **8.7** | — |
| SWE-smith, arXiv 2504.21798 | Qwen2.5-Coder-32B, Verified 7.0 | 500 → 5,016 Claude trajectories (≤ 3 per task) | SWE-agent, full FT | 28.2 → 40.2 | repo diversity (7B): 4 → 100 repos: 10.3 → 15.1 |
| R2E-Gym, arXiv 2504.07164 | 32B | 3,321 Claude 3.5 | OpenHands | 34.4 | — |
| SWE-Next, arXiv 2603.20691 | 7B 1.8, 14B 4.0 | 3.7k (Claude 4.5 Sonnet, GPT-5-mini) | R2E-Gym | 17.4, 30.0 | — |
| SWE-Dev, arXiv 2506.07636 | Qwen2.5-Coder-32B | 2.3k verified + 17k unevaluated (DeepSeek-V3) | OpenHands | 36.6 | — |
| **Nebius blog** (openhands-trajectories-with-qwen3-coder-480b) | **Qwen3-30B-A3B-Instruct-2507**: Verified 25.7, SWE-rebench Sept 14.2 | ~32k resolved of 67k (Qwen3-Coder-480B) | OpenHands | Verified **50.3**; SWE-rebench Sept **28.1** | 49 fresh tasks: +13.9 (+98% relative) |
| same | **Qwen3-235B-A22B-Instruct-2507**: 46.2, rebench 25.3 | same | same | 61.7; **34.2** | +8.9 (+35% relative) |
| SWE-Lego, arXiv 2601.01426 | Qwen3-32B 23.2; Qwen3-8B 7.6 | 18k validated (Qwen3-Coder-480B) | full-parameter SFT | 52.6; 42.2 | error masking +2.2 (32B) |
| SWE-Zero → SWE-Hero, arXiv 2604.01496 | Qwen2.5-Coder 7B/14B/32B | Qwen3-Coder-480B | execution-free, then execution-based | 46.8/54.5/57.5 → 52.7/60.8/62.2 | 14B scaling, 4k → 150k PRs: 42.1 → 49.1 |
| Kwai-Klear card | Qwen3-8B | 1k → 66k trajectories | mini-swe-agent-plus | "approximately linearly with the logarithm of the data scale"; 39.0 at 66k | — |
| LoRA vs full FT: Biderman et al., arXiv 2405.09673 | — | code and math IFT / continued pretraining | LoRA | "LoRA substantially underperforms full finetuning", and forgets less | — |
| "LoRA Without Regret", Schulman / Thinking Machines, 2025-09-29 | — | SFT and RL | LoRA on all layers, MLP included | matches full FT until the adapter's capacity is exceeded; best LR about 10× full FT's | — |

What the table says for us (INFERENCE):
- The large jumps (7 → 20-40) come from bases that had never been trained on an agent scaffold. They do not transfer
  to Gemma-4-31B, which already solves 36% of the public set inside v10.1.
- The closest analogs are the nebius Qwen3 instruct models, measured on **fresh** tasks. The weaker base gained +98%
  relative, the stronger one +35%. Both used about 32k trajectories and presumably full FT. The fresh set has only 49
  tasks, so each number carries roughly ±6 points of sampling error.
- Data size follows a log curve. In SWE-smith 32B, the gain over base was 21.2 points at 500 trajectories and 33.2 at
  5,016, so one decade less data kept about 64% of the gain.
- Self-generated data from the same model gives about 0 (FE §3), matching PLAN's framing of v11 as a format lever.

### 5.2 Arithmetic (ESTIMATE; every factor is a stated guess)

| factor | low | central | high | basis |
|---|---|---|---|---|
| Relative gain on fresh tasks at ~32k trajectories | +35% (strong-base analog) | +59% (geometric mean) | +98% (weaker-base analog) | Nebius |
| Data size: 5k ≈ 0.8 decade below 32k | ×0.70 | ×0.70 | ×0.70 | 0.64 per decade, SWE-smith |
| Data size: 1k ≈ 1.5 decades below | ×0.51 | ×0.51 | ×0.51 | same |
| LoRA r16-64 instead of full FT | ×0.6 | ×0.8 | ×1.0 | Biderman (worse) vs Schulman (equal within capacity); ~2.4k supervised tokens per trajectory, so capacity is probably fine |
| LoRA-mode decode tax on cap-bound hidden tasks | ×0.9 | ×0.95 | ×1.0 | Unmeasured (FI §1.6); hidden tasks nearly all hit the 5-min cap |
| Format match (teacher through v10.1) | ×1.0 | ×1.0 | ×1.0 | Same scaffold as training, like the analogs |

| scenario | relative gain on the hidden set | hidden public tasks (base 7/58) | LB |
|---|---|---|---|
| 1k teacher trajectories through v10.1 | +10% / **+23%** / +50% | +0.7 / **+1.6** / +3.5 | 0.13 / **0.15** / 0.18 |
| 5k teacher trajectories through v10.1 | +13% / **+31%** / +69% | +0.9 / **+2.2** / +4.8 | 0.14 / **0.16** / 0.20 |
| Self-RFT, 120-250 own v10 trajectories (PLAN v11) | about 0 (PLAN / PC §12: +1 of 58, 80% range −1 to +4, if it ships) | +0 to +1 | 0.12-0.14 |
| Public OpenHands data converted to native tools, trained into v10.1 | ×0 to ×0.3 of the teacher rows, with a real chance of harm (drift back to `edit_file`) | −2 to +1 | 0.09-0.14 |

All of these are conditional on the adapter being applied on the scorer (section 0 item 2). PLAN's guess for that is
0.6, made before the 09-29 negative re-test.

### 5.3 What 0.20 would need
- 0.20 on ~58 public tasks is 12 solved: +5 over today's 7, a **+71% relative** gain.
- Only the high end of the 5k scenario reaches it. That high end assumes the weaker-base analog, full-FT-equal LoRA
  and no decode tax.
- My odds (INFERENCE): about 10% conditional on a working adapter and 5k clean trajectories, so ≤ 5% overall. About 2%
  for 1k. Under 1% for self-RFT.
- One LB read has SD ≈ 2.5 tasks at p ≈ 0.12 (forum_update_0928 §6.1). A true +2 would show up as anything from −1 to
  +5 on a single submission. The only instrument that can see it is PLAN §1's paired local rule (148 paired
  task-runs, D ≥ +6).

### 5.4 How to measure it cheaply (INFERENCE)
- Held-out repo: PLAN's werkzeug hold-out, plus the public 74 as the out-of-org test.
- The golden F suite (fixer given a golden plan) isolates fix quality, which is v10's binding constraint. It can run the
  adapter only through `--endpoint vllm` on a pod or Kaggle, because OpenRouter cannot serve our LoRA.
- Pre-register, as PLAN §1 does: paired D over 148 task-runs, format KPIs, s/task on L4.

---

## 6. Recommendations (INFERENCE, ranked)

1. **Carson posts the follow-up** (`docs/v11/forum_question_distillation.md`) under comment 3530102. Until an answer:
   use Gemma's own outputs, and treat Apache/MIT open-weight teachers as likely-allowed rather than cleared.
2. **Nothing trains before G-A passes.** The 09-29 re-test says adapters still do nothing on the current wheelhouse
   (with a caveat). When the quota resets, G-A's random-B test should randomise **both** `lora_A` and `lora_B` on all
   layers. That closes the caveat in 743508.
3. **If G-A passes, the data path is:** a 40-task teacher pilot on Pallets-X through v10.1 with Qwen3-Coder-480B or
   DeepSeek-V4.1-Flash (about $1-3), to measure solve rate, calls per task and L4 feasibility. Then all of Pallets
   (about 1,170 runs, $18-51), then SWE-rebench for the rest of 1k. Stop at 1k: that is what the v11 training budget can afford,
   and the literature curve gives about 70% of the 5k gain at a fifth of the cost.
4. **Swap self-RFT for teacher data in v11's data plan** (PLAN §4) once Q1 is answered yes. Keep everything else in
   PLAN (renderer, masks, gates) unchanged; the teacher rows go through the same `build_sft` path.
5. **Keep the converted nebius / SWE-Hero sets out of the v10.1 adapter.** If they are used at all, use them for a
   separate v4-style (native-tool) arm, after Q2 is answered.
6. **Do not plan on distillation alone reaching 0.20.** At the central estimate it adds about 1.5-2 hidden tasks. 0.20
   needs that to stack with non-training gains (v10.1 itself, sub6 tonight, and fix quality), each measured on the
   faithful L4 path.

## 7. What would change this report
- A host answer to the draft's Q1-Q4.
- A posted re-test in 743508 with both A and B randomised, or our own G-A result.
- sub6 (v10.1) scoring clearly above 0.12: the base rises, so the same relative gain buys more tasks.
- A measured teacher solve rate inside v10.1. The pilot replaces section 4.3's 35-60% band.
- Measured LoRA-mode decode tax on 4×L4 (G-A): above 10%, lower section 5.2's low end.

## 8. Sources
- Forum: 742807 https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/742807 · 743964 https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743964 · 743508 https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743508
- Terms: https://www.anthropic.com/legal/commercial-terms · https://ai.google.dev/gemini-api/terms · OpenRouter prices https://openrouter.ai/api/v1/models (extract in `research/distill_evidence/openrouter_prices_20260930.json`)
- Datasets: https://huggingface.co/datasets/nebius/SWE-rebench-openhands-trajectories · https://huggingface.co/datasets/nvidia/SWE-Hero-openhands-trajectories · https://huggingface.co/datasets/nvidia/SWE-Zero-openhands-trajectories · https://huggingface.co/datasets/SWE-bench/SWE-smith-trajectories · https://huggingface.co/datasets/SWE-Gym/OpenHands-SFT-Trajectories · https://huggingface.co/datasets/SWE-Gym/OpenHands-Sampled-Trajectories · https://huggingface.co/datasets/R2E-Gym/R2EGym-SFT-Trajectories · https://huggingface.co/datasets/TIGER-Lab/SWE-Next-SFT-Trajectories · https://huggingface.co/datasets/zai-org/SWE-Dev-train · https://huggingface.co/datasets/SWE-Factory/DeepSWE-Agent-Kimi-K2-Trajectories-2.8K · https://huggingface.co/datasets/Kwai-Klear/SWE-smith-mini_swe_agent_plus-trajectories-66k · https://huggingface.co/datasets/nebius/SWE-agent-trajectories · https://huggingface.co/datasets/nebius/SWE-rebench · https://www.kaggle.com/datasets/takumuhata/swe-pallets-x
- Code releases without data: https://github.com/facebookresearch/swe-rl · https://github.com/MoonshotAI/Kimi-Dev
- Papers and posts: SWE-Gym https://arxiv.org/abs/2412.21139 · SWE-smith https://arxiv.org/abs/2504.21798 · R2E-Gym https://arxiv.org/abs/2504.07164 · SWE-Dev https://arxiv.org/abs/2506.07636 · SWE-Next https://arxiv.org/abs/2603.20691 · SWE-Lego https://arxiv.org/abs/2601.01426 · SWE-Zero/Hero https://arxiv.org/abs/2604.01496 · Nebius https://nebius.com/blog/posts/openhands-trajectories-with-qwen3-coder-480b · LoRA Learns Less https://arxiv.org/abs/2405.09673 · LoRA Without Regret https://thinkingmachines.ai/blog/lora/
