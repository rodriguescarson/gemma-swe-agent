# Thinking LOW timing check (pre-registered 2026-10-02 11:00 IST, before any run)

Why: thinking was silently broken on the scorer until the Sep 30 wheelhouse (vLLM read `reasoning` but ADK sent
`reasoning_content`, forum 744354), so every "thinking on" measurement anyone made, including the council's "stop
testing thinking" verdict, was made on a feature that dropped its own thoughts between tool calls. Nobody has measured
its cost on the real 4xL4 stack since the fix. One competitor's pre-fix preview: 18 of 33 tasks overflowed context.

Bundle: `scripts/make_think_variant.py submissions/v4h eval/golden/arms/v4h_think_low --level LOW` (only the
thinking_config block of configs/sampling.yaml changes; `max_output_tokens: 4096` is the only cap on reasoning length).
Kernel: `scripts/make_eval_kernel.py eval/golden/arms/v4h_think_low g4-l4-v4h-think --ids <10 public ids>`, Kaggle 4xL4,
faithful (compaction on, bundle budgets). Runs on Saturday's quota AFTER the G-A probe, never while a submission scores.
Cost: about 1 GPU-hour of the free quota. Control: the same 10 tasks from v4's faithful L4 run of 2026-09-28
(eval/kaggle/g4-l4-v4/results.jsonl; mean 154.6 s/task over 74).

## Enters the slot queue only if ALL hold on the 10 tasks

1. Mean wall time per task <= 155 s (v4's faithful mean; a bundle slower than that cannot keep the 12 h budget on the
   1.6-1.8x slower hidden set).
2. Context overflow (`ContextWindowExceeded` / "maximum context length") on fewer than 10% of tasks (0 of 10).
3. Zero non-timeout crash rows.
4. Reported, not gated: solved count vs v4's on the same 10 ids; completion tokens per task; whether `reasoning_effort`
   had any visible effect (reasoning token counts in the traces).

PASS: "thinking LOW" becomes queue item 3, run as one slot after the v4h second read. FAIL on 1 or 2: thinking stays off
and the queue moves on; a MINIMAL-level retest is allowed once if the mean time is within 20% of the bar.

Result (appended after the run, never edited above this line):
