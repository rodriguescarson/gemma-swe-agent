# Triage of research/2026-10-05_deep_research.txt (Carson's deep-research report), 2026-10-05

## LoRA (corrected with the live forum, Carson's push-back)
- Broken before 2026-09-30: zero-reset alias bug (thread 743508, fixed v23) and the KV-cache collapse to ~7.6k tokens
  with enable_lora (thread 744331). Ryan Holbrook patched the LoRA parameters on 2026-09-30 (wheelhouse v28);
  participants confirm a rank-16 adapter serves 28k-token prompts. Our G-A2 (v28): loud_all 20/20 outputs changed,
  24k prompt through an adapter in 18 s. The report's "LoRA is wiped / 7.6k" describes the pre-fix state. LoRA stays on.

## Already covered in our bundles
double-JSON escaping (edit.py matches JSON-unescaped text, fixer has no edit_file); syntax-validated editor with
rollback (edit.py py_compile); undeclared-tool crash (prompt rule); temperature 0.1-0.2 (v5all); thinking off; 5 min.

## New, to build (v5b on v5all)
1. Test-driven exploration for title-only issues (locator runs nearby tests, reads tracebacks as the spec).
2. AST repo map skill (signatures, compact) for navigation.
3. Prompt guard: run_skill_script file_path must be a string, never a list (sandbox crash).
4. LoRA data: SWE-Gym OpenHands-SFT-Trajectories (491, open teachers) for v11c; SWE-smith trajectories are Claude-made:
   distillation risk, excluded.

## New forum facts (2026-10-05)
745855 fastapi_15661 unsolvable from the prompt (hidden tests import names absent from the task); 745775/745850
missing FastAPI test deps and inline_snapshot wheel in the eval sandbox; 745774 baseline repeats one command up to 69x.

## Correction 2026-10-05 15:00 IST: SWE-Gym trajectories are NOT open-teacher
SWE-Gym/OpenHands-SFT-Trajectories (MIT) were sampled from gpt-4o-2024-08-06 and claude-3-5-sonnet-20241022 (SWE-Gym
paper arXiv 2412.21139 App. B.4), i.e. closed commercial models: the same distillation class as SWE-smith
(research/distill.md 2.3, "doubtful"). The report's "open-weight teachers" claim is wrong. Converted rows
(data/v11/rows_swegym.jsonl, 2,978 rows / 214 tasks, train/convert_swegym.py, tests 30) are QUARANTINED: not used in
any submitted adapter unless the organizers rule closed-model distillation acceptable. v11c data = Gemma on-policy
collection + open-weight teachers (Qwen3-Coder, Kimi, DeepSeek) only. Also: those rows include submit_patch calls the
real fixer cannot make; drop them if the quarantine is ever lifted.
