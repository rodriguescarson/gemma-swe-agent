# Live slot: v4h-think (pre-registered 2026-10-02 16:45 IST, before the smoke and before the read)

Why a live slot instead of waiting for Saturday's L4 timing kernel: a new leader scored 0.24 (14/58) at 03:09 UTC
today, the first high score since the Sep 30 scorer rebuild, which is when thinking started working (the
`reasoning_content` fix) and LoRA adapters started applying. Carson's call: use what started working in the next
submissions. Thinking is usable now; a LoRA is not (no trained adapter exists).

Bundle: `submissions/v4h_think` = `submissions/v4h` with exactly two changes:
1. `configs/sampling.yaml`: `thinking_config: include_thoughts: true, thinking_level: LOW` (all three stages share it).
2. `eval_config.yaml`: `max_time_minutes: 4.0` instead of 5. This is not a second hypothesis; it is the 12 h bound.
   v4 runs 10.3-10.5 h on the hidden set at 5 min; thinking makes every step slower, so more tasks would hit the cap
   and the run could cross 12 h, which scores nothing and is not rerun. At 4 min the worst case is about 9.7 h.
   Everything else (prompts, helpers, tools, locator) is byte-identical to v4h (tests/test_think_variant.py).

Known risks accepted for this read: with thoughts now kept between tool calls, context grows faster, compaction
(14,336 tokens) fires more often, and overflow discards the patch; a step can spend its 4,096 output tokens on thoughts
and emit no tool call; the 4-minute cap cuts v4's late solves (2 of 29 L4 solves took over 3 minutes).

## Smoke gate (10 Pallets tasks on OpenRouter, v4h vs v4h_think, same hour): ship only if
- 0 non-timeout crash rows in the v4h_think arm;
- 0 context-overflow rows;
- at least 8 of 10 tasks produce a non-empty patch OR solved >= v4h's solved - 1 (a thinking bundle that stops
  acting is the failure to catch);
- reported, not gated: calls per task, mean completion tokens per call, mean task seconds.
The proxy cannot reproduce the scorer's thinking path exactly (OpenRouter's reasoning handling differs from the
patched vLLM), so this smoke catches breakage, not the real time cost. That cost is measured on Saturday's L4 kernel
(docs/v4h/THINK_TIMING.md) regardless of this slot's outcome.

## Reading the hidden score (one read; SD about 1.9 tasks)
- >= 10/58 (0.17): thinking is the lever; it becomes the base and gets its second read next; the 4-minute cap is then
  tested upward only with the L4 timing numbers in hand.
- 8-9/58 (0.13-0.15): promising but within noise of v4h; second read before any decision.
- <= 7/58: no gain at this cost; thinking goes back behind the Saturday measurement; v4h stays the base.
- ERROR: if it is the 12 h cap (run time near 12 h), the cap insurance was insufficient: no retry without an L4 timing
  read. If it is a platform error, rerun request as for sub7.

Slot: 2026-10-04 00:01 UTC (05:31 IST) as sub10, armed after sub9 fires on 2026-10-03.

Result (appended after the smoke and after the read, never edited above this line):
