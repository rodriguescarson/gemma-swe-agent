# h2g4: Harness² with the competition's agent

[Harness²](https://github.com/google-research/harness2) (Google Research, Apache-2.0, pinned at `1cfe254`) adapts an agent's
harness per task by Propose → Probe → Compose and keeps a per-domain library of adopted harnesses and lessons. Here its
executor is our own agent (the ADK bundle, Gemma 4 31B on the A6000 box, through the race runner and pace proxy), so the
harness it evolves can be shipped as a static bundle. The method cannot run inside a submission (5-minute static bundle).

- `adk.py`: the substrate. Editable surface = `systemprompt.md`, `guardrails.md`, `LongTermMEMORY.md`,
  `tool_descriptions/tool_guidance.md` (joined in that order into `prompts/system.md`) and `skills/<name>/` (ADK skills).
  `agent.yaml`, `eval_config.yaml`, `configs/sampling.yaml` come from `submissions/v12` and are never editable.
- `swe.py`: the benchmark adapter. Refinement tasks = `data/heldout1k` (other repositories, never the public 74); domain =
  repository; the improver sees only the issue text; `score()` is the box's test verdict, used only by the judge stage.
- `run.py`: `python -m h2g4.run RUNS_ROOT --only-domains arrow --max-tasks 8 --k 1 --modes sequential [--dry-run|--smoke|--judge]`.
- `box_setup.sh`: installs harness2, its patched OpenCode and bun on the box, and an OpenCode provider for the box's vLLM.

Improver: `HARNESS2_IMPROVER_MODEL` (provider/model for OpenCode, bare id for the Claude CLI). Phase 1 = `boxvllm/gemma4`
(Gemma improves its own harness, $0, needs `SERVED_ALIAS=gemma4` on serve.sh and `H2G4_MAX_CHARS=20000`). Phase 2 = an
OpenRouter model through OpenCode, capped (the key's own limit must be raised first). Tests: `tests/test_h2g4.py`.
