# G-A: does a LoRA adapter actually apply on the scorer's stack? (pre-registered 2026-10-02, before any run)

Runs on Kaggle 4xL4 with the competition wheelhouse, through `adk_submission.VllmServer` exactly as the scorer starts
vLLM (TP=4, enable_lora, max_loras 8, max_lora_rank 128). Built by
`scripts/make_test_adapters.py --bundle submissions/v4 --out eval/golden/arms/v4_lora_probe` and
`scripts/make_eval_kernel.py eval/golden/arms/v4_lora_probe g4-l4-lora-probe --ids <5 ids> --probe lora`.
Cost: about 1.5-2 GPU-hours of the free weekly quota (resets Saturday 05:30 IST). No pods.

Why now: the forum says the adapter-zeroing bug was fixed in wheelhouse v23 and the LoRA KV starvation in v25
(threads 743508, 744331), and no team has a post-fix adapter score on the board. The 2026-09-29 re-test by another
participant found `/v1/models` listing no adapter through the harness path. This probe settles it for our stack.

## Adapters (numpy, float16, q_proj on layer 0, r=4 like the sample submission, sha recorded in adapters/MANIFEST.json)

| name | lora_A | lora_B | key prefix | purpose |
|---|---|---|---|---|
| loud | N(0,1) | N(0,1) | `base_model.model.model.language_model.layers.N...` | must change outputs if applied |
| loud2 | same | same | `base_model.model.language_model.layers.N...` | which prefix vLLM maps |
| zb | N(0,1) | zeros | first prefix | must NOT change outputs (the Z-slot adapter; the sample's shape) |

## Checks (20 fixed prompts, greedy, 32 tokens; base run twice for the noise floor)

| # | check | pass |
|---|---|---|
| P1 applied | top-1 text differs from base on >= 18 of 20 prompts for `loud` or `loud2` | required |
| P2 zero-B harmless | `zb` differs from base on at most (base-vs-base diffs + 1) prompts | required |
| P3 listed | every adapter name appears in `/v1/models` (as `<name>` or `<base>:<name>`) | reported |
| P4 decode tax | tokens/s with `zb` >= 0.9 x base (0.75-0.9: continue, the break-even rule absorbs it) | reported |
| P5 long context | a ~24k-token prompt through `zb` returns within 900 s | required |
| P6 agent smoke | 5 public tasks with the fixer on `zb`: 5 result rows, 0 crash rows, fixer calls routed to `:zb` | required |

**G-A PASS** = P1, P2, P5 and P6 all pass. Then the Z slot (v4h or v10.1 plus `zb` on the fixer) is queued, and the
35 remaining hours of the v11 pipeline are worth building.
**G-A FAIL on P1** (neither loud adapter changes outputs) = adapters are not applied on this stack; the LoRA track is
closed until a new wheelhouse version says otherwise. No further LoRA work.
**P1 passes only for `loud2`** = the key prefix in docs/v11/plan_A.md is wrong; every later adapter uses the loud2 prefix.

Result (appended after the run, never edited above this line):
