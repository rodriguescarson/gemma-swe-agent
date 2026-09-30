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
