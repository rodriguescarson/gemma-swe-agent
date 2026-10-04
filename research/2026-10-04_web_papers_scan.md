# Web/papers scan: what works for small/medium open models on SWE-bench under tight compute (2026-10-04)

**Budget reality check.** 5 min at ~30 tok/s is about 9k generated tokens per task. Published TTS gains assume 8 to 50 rollouts plus a separate verifier. Our rules also require gemma-4-31b-it-qat for every LlmAgent and sub-agent, so external critics (SWE-RM, R2E-Gym verifiers) are out. Best-of-k is mostly unaffordable, so the cheap single-trajectory versions are what's left. The "tasks gained" numbers are my estimates against the 74 public tasks, not measurements. Check each one with a paired run on all 74 before you trust it.

## Ranked by expected tasks gained

**1. Reproduce first, then check the fix against tests near the edit (est. +3 to +6).** This targets the 55% "right file, wrong fix" bucket.
- Agentless (Qwen-class/GPT-4o, Lite): majority vote alone gives 77. Adding regression-test filtering gives 81, and adding a generated reproduction test gives 96 (32.0%). So reproduction tests did most of the selection work. https://github.com/OpenAutoCoder/Agentless/blob/main/README_swebench.md
- TestPrune (FSE 2026) picks the minimal set of existing tests relevant to the issue, and those tests also seed the reproduction test. Issue resolution rises 8.0 to 12.9% relative in Agentless, SWE-agent and Trae (Lite and Verified). https://arxiv.org/abs/2510.18270
- **For us:** prompt or tool step: (a) grep the tests that import the localized module, (b) write a 10 to 20 line repro and run it, so it fails, (c) edit, (d) rerun the repro and the pruned tests. If budget is left, allow one revise loop. No second rollout. Cost: about 1 day of prompt and tool work, plus about 8 to 12 tool calls of budget.

**2. A forced-submission watchdog (est. +2 to +4).** This targets the 15% that produce no patch. It's not in any paper. It's a harness fix: at about 4:00 elapsed or 60 calls, auto-submit the current `git diff` if it's non-empty. If it's empty, inject "submit your best edit now." Every leaderboard scaffold (mini-swe-agent, SWE-agent) auto-submits on step limit. Cost: hours.

**3. Pre-localization injected into the first prompt (est. +2 to +4).** This targets the 20% wrong-file bucket.
- Agentless hierarchical localization (BM25/embedding, then file skeletons with signatures only, then functions) is cheap and works offline.
- CoSIL (Qwen2.5-Coder-32B, training-free call-graph search) reaches 43.3% Top-1 file/function localization on Lite and 44.6% on Verified, up to 96% better than prior methods. LocAgent (code-graph tools, Qwen-32B) has the best Top-1 file accuracy. https://arxiv.org/abs/2503.22424 , https://arxiv.org/abs/2503.09089
- **For us:** compute BM25 over file paths and symbols before turn 1, and put the top 5 files' skeletons (about 1.5k tokens) into the prompt. That saves 5 to 10 exploratory calls. Cost: about 1 day, and we already have code-graph tools.

**4. A finer-grained, error-tolerant edit tool (est. +1 to +3).**
- A Qwen3.6-27B ablation: an identical model scored 87.4% with the qwen-code CLI and 90.0% with claude-cli. The poster attributes the gap to the finer-grained str_replace Edit tool. The same model on mini-swe-agent scored 67.8%, so harness engineering alone was worth +22 pp. https://github.com/QwenLM/Qwen3/discussions/1846
- SWE-Edit gets +2.1 pp on Verified from splitting off viewer and editor roles. GRPO-training an 8B on edit-format choice gave +12.5 pp edit success. https://arxiv.org/abs/2604.26102
- **For us:** use str_replace with a unique-match requirement. Normalize whitespace and indentation before failing. On a miss, return the nearest-match snippet with line numbers. Run `python -m py_compile` automatically after each edit. Cost: about 0.5 day. Measure our malformed-edit rate first.

**5. LoRA rejection-sampling fine-tuning on our own successful trajectories (est. +2 to +6, high variance).**
- SWE-Gym: Qwen2.5-Coder-32B fine-tuned on only **491** successful trajectories gained +12.3 pp on Lite and +13.6 pp on Verified over zero-shot. Gains were still rising at 491, so the limit was sampling compute, not data. https://arxiv.org/abs/2412.21139
- SWE-smith: 5,016 Claude-3.7 trajectories (at most 3 per task) took Qwen2.5-Coder-32B to 40.2% on Verified with one attempt. https://arxiv.org/abs/2504.21798
- SWE-Lego: Qwen3-32B went from 23.2% to 52.6% with SFT only (Qwen3-8B reached 42.2%). Its error masking (no loss on failed or erroneous steps) plus a difficulty curriculum added +3.8 pp on top of the data. https://arxiv.org/abs/2601.01426
- **Caveats:** Gemma 4 is a stronger base than Qwen2.5-Coder, so expect smaller deltas. Our LoRA path broke on 09-25. Train on SWE-Gym or SWE-smith environments and keep the 74 held out. Cost: 3 to 5 days plus GPU. Do it only after items 1 to 4 are measured.

**6. Inferring intent for title-only issues (est. +1 to +2).** Ambig-SWE (ICLR 2026) finds that being able to ask clarifying questions improves results on underspecified issues by up to 74%. https://arxiv.org/abs/2502.13069 . We can't ask offline, so substitute cheap context before editing: `git log -5 --stat` on the target file, nearby test names and docstrings, and a one-line "expected vs actual" hypothesis. Cost: a prompt change.

**7. Self-verification as a final step (est. 0 to +2).** Open generative verifiers add 4.5 pp at 32B with K=32 (SWE-HERO, https://arxiv.org/abs/2604.01496). Execution-free RMs (SWE-RM, 30B-A3B) take Qwen3-Coder-Flash from 51.6% to 62.0%. Both need many candidates, which we can't afford. The affordable piece is one Gemma "review your diff against the issue and the repro output" turn before submit. Gains are unproven at k=1. https://arxiv.org/abs/2512.21919

## Not worth it under our constraints
- **Full RL**, too much compute: SWE-RL 70B 41.0% (https://arxiv.org/abs/2502.18449); DeepSWE 32B 42.2% (https://www.together.ai/blog/deepswe).
- **Best-of-k TTS**, since k ≥ 4 doesn't fit in 5 minutes: Satori-SWE 32B 35.8% to 41.6% at Best@50 (https://arxiv.org/abs/2505.23604).
- **SWE-Protégé**, which needs a second expert model the rules ban (https://arxiv.org/abs/2602.22124).

## Gemma-specific and competition chatter
- No Reddit or HN threads about the competition turned up. Public GitHub entries (ns-0437/gemma4-developer-agent, happyc0der/gemma-swe-agent, others) publish no scores.
- Third-party scaffolds list Gemma 4 31B at 52.0 (Qwen's scaffold) and 66.6 (Meta's) on Verified. That 15-point spread from harness alone backs ranking scaffold work above training.

## Suggested order
2 (hours), then 4, then 3, then 1, then 6. Run all 74 tasks as a paired comparison after each change. 5 only if time remains before the Nov 12 paper and Dec 2 final deadlines.
