# Council brief: Kaggle "Google - The Gemma 4 Developer Agent Competition" (as of 2026-09-30)

## The competition (hard constraints)
- Submission = a DECLARATIVE Google ADK agent bundle (YAML agents + markdown prompts + "skills" = stdlib-only Python helper scripts the agent runs in its sandbox + optional LoRA adapters). No custom Python in the orchestration; no network; no other model.
- Model fixed: gemma-4-31b-it-qat-w4a16-ct (Gemma 4 31B, int4 QAT) served by vLLM 0.19.1 on 4x NVIDIA L4 (TP=4), 32k context, gemma4 tool-call parser. Thinking can be on/off per agent.
- Scoring: ~120 hidden SWE-bench-style tasks from PRIVATE Python repos (issue text = the upstream PR description; graded by the PR's hidden tests), run SEQUENTIALLY; the whole run must finish in 12 h or it scores nothing. Per-task budget is set by us in eval_config.yaml (we use 5 min, 100 tool calls, 200 turns, 180 s per command). Public leaderboard = ~60 of the tasks (score = fraction solved), private = the rest. One submission per day; final ranking uses 2 selected submissions. Deadline 2026-12-02. Prize pool $65k main (+$35k paper track, deadline 2026-11-12).
- Harness facts that bite: ADK compacts a stage's history when its prompt reaches 14,336 tokens (wipes include_contents:none stages to their instruction); any exception except timeout discards the patch; the sandbox rewrites the literal "/tmp" in commands; run_command keeps only the first 5,000 chars; tool results are JSON-encoded twice; the gemma4 parser corrupts ~20% of multi-argument edit_file calls; test-file edits by the agent persist into grading and can break it; parallel tool calls unsupported. Hidden tasks take ~1.9x longer than public ones, so on the hidden set nearly every task runs into the 5-min cap; capped runs scored 0 in 123/123 of our records.
- Rulings: LoRA adapters allowed (a loading bug was fixed 2026-09-27 but a 2026-09-29 re-test still found the scorer's server listing no adapter; unverified if adapters really apply). Training on Gemma's own outputs allowed; other models' outputs allowed "as long as you use them in accordance with their model licence terms" (so open-weight teachers like Qwen3-Coder/DeepSeek are likely fine; Claude/GPT terms likely forbid).
- Kaggle GPU quota: 30 h/week (a 74-task faithful L4 eval run costs ~3.5 h); currently exhausted until the weekly reset.

## Leaderboard (public, 2026-09-30)
Leader 0.17 ("Statistical Science by Lasme"), 2nd 0.15 (Makus), several at 0.13, a crowd at 0.12. Carson's target: 0.20 (about 12 of ~60 public-LB tasks).

## Our submissions and hidden scores
| sub | bundle | public score |
|---|---|---|
| sub1 | v0 = the organisers' sample agent minus its dummy adapters | 0.10 |
| sub2 | v2 | error (platform-side resource error) |
| sub3 | v4 | 0.12 |
| sub4 | v9_eog = v4 + a working helper install + line-range edit/run/gate helpers | 0.06 |
| sub5 | v4 again | 0.12 |
| sub6 | v10.1 (the heavy "robustness-first" pipeline below) | 0.08 |
| sub7 (armed for 2026-10-01) | v4 again | pending |
Single-read noise: ~±0.03 (SD about 1.9 tasks of ~60).

## The bundles
- v4 (best hidden score, 0.12 twice): SequentialAgent locator -> fixer -> verifier, each stage a fresh context (include_contents none), handoff via state keys; thinking off; temperature 1.0; tools = harness built-ins (run_command, read_file, edit_file, write_file, submit_patch, graph tools). It ships a helper skill but, because of the /tmp rewrite bug, its helpers were unreachable in ~95% of calls; in effect v4 ran with plain built-in tools.
- v9_eog (0.06): v4 + fixed helper install + replace.py (line-range edits), run.py (timeout + bounded output), gate.py (regression gate; later found to report PASS on import crashes).
- v10.1 (0.08): 5 stages setup -> locator -> fixer -> verifier -> submitter; ~9 stdlib helpers (locate/grep/view/edit/run/verify/finalize/status/install); edit only via a SEARCH/REPLACE heredoc helper; claim-structured reproduction + regression gate (verify.py); checkpoints and best-version restore; clock-driven footer hints (EDIT NOW, FINISH, TIME, CONTEXT); prompts ~370 words per stage; 1,470 unit tests.

## Local / proxy evidence (public tasks: 74 Kaggle-valid, fastapi 31 + rich 42 + requests 1)
- Kaggle 4xL4 faithful (compaction on): v4 29/74, v9_eog 29/74 (tie).
- Pod faithful pair (H100, compaction on, L4 clock scale): v10 25 vs v9_eog 24 (race 2 round 1); v10.1 27 vs v4 24 (paired 10 wins 7 losses; empty patches 2 vs 12; 0 crashes; time 0.98x).
- So: local evals rank v10.1 >= v9_eog >= v4, but the HIDDEN set ranks v4 (0.12, 0.12) > v10.1 (0.08) > v9_eog (0.06). Local/pod/proxy evals have NOT predicted the hidden ranking. Public solve rate ~36-39% locally vs ~12% hidden.
- Golden stage-level evals (OpenRouter proxy google/gemma-4-31b-it bf16, rich tasks only so far):
  - Fixer given a GOLDEN plan (gold files/functions/cause, no gold code): passes 75-80% (21-23 of 28).
  - Repair-loop ablation (0 vs 2 repair rounds + noise arm): net +1 vs noise +2, repair costs +40% time and +70% tool calls; INCONCLUSIVE (no evidence repair helps).
  - Locator (v10.1): plan names all gold files 55.6%, gold functions 51.6%, valid failing reproduction 40.7%, mean locator end at t=129 s of the 300 s task, 18.5% of tasks capped inside the locator.
- Diagnosis of losses (earlier bundles): "right file, wrong or partial fix" dominated; ~15-19 of 74 tasks look infeasible from the issue text alone (hidden spec in tests, huge features, title-only issues).

## What is running / planned
- Pallets transfer test (running now on a pod): v4 vs v10.1 on 40 SWE-Pallets-X tasks (Flask/Werkzeug/Click; unseen repos in the same format, src/ layouts) to see whether the hidden ranking (v4 > v10.1) reproduces on unfamiliar repos.
- v10.2 build (in progress): targets the locator (faster, more accurate), trims repair, adds speed cuts and robustness for unfamiliar repo layouts.
- v11 (LoRA) track: free Kaggle probe that adapters really apply; then SFT on Gemma's own successful trajectories and/or licence-permitted open-weight teacher trajectories (6,395 Qwen3-Coder-480B OpenHands trajectories already converted to our tool schema); honest odds of shipping ~4-10%.
- The detailed ranked plan (docs/PATH_TO_020.md) is attached below; its central estimate for the best achievable bundle is ~0.16, with P(true 0.20) ~0.6% without distillation and ~3% with.
