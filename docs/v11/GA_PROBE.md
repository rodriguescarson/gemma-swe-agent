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

### Result 2026-10-03 20:01 IST: G-A FAIL (probe sha 25f5edd7209a)
checks {"P1_applied": false, "P2_zero_b_harmless": true, "P3_listed": true, "P4_decode_tax_le_10pct": false, "P5_long_ctx_returns": true}; P6 True; diff_vs_base {"loud": null, "loud2": null, "zb": null}; prefix none. LoRA track closed until a new wheelhouse version says otherwise (rule above).

#### Addendum 2026-10-03 20:05 IST (numbers behind the FAIL line above; written before any follow-up run)
Kernel g4-l4-v4 v3 (4xL4, Python 3.12 pin, wheelhouse of 2026-09-30), 20 prompts, greedy, 32 tokens:
`loud` (plan_A prefix) differs from base on **6 of 20**; `loud2` **0**; `zb` **0**; base-vs-base noise floor **0**.
P2 PASS, P3 PASS (all three listed), P4 FAIL-as-reported (32.6 -> 28.6 tok/s = 12% decode tax, inside the
0.75-0.9 "continue" band), P5 PASS (24k-token prompt through zb in 18.5 s), P6 PASS (5/5 rows, 0 crashes, fixer on :zb).
Reading: adapters under the plan_A prefix ARE applied (6 vs 0 is above the floor and prefix-specific: the loud2 prefix
maps to nothing), but a random r=4 adapter on layer 0's q_proj alone perturbs greedy top-1 on only 6 prompts, so the
>= 18 threshold measured the adapter's loudness, not application. P1 stays FAIL as pre-registered; the threshold did
not transfer (the Vesuvius lesson). The packager key style is `loud` (plan_A) if the follow-up confirms application.

**G-A2 (pre-registered here, before the run):** same kernel, adapters `zb`, `loud` (unchanged controls) plus
`loud_all` = N(0,1) A and B, r=4, on q_proj/k_proj/v_proj/o_proj of ALL 60 layers under the plan_A prefix, and
`loud3` (`base_model.model.language_model.model.layers.N`, Gemma-3 HF style) / `loud4`
(`base_model.model.model.layers.N`, Llama/Together style), each q_proj layer 0 only.
PASS = `loud_all` differs on >= 18/20 (an adapter touching every attention projection in every layer cannot leave
greedy outputs alone if it is applied) AND `zb` <= noise + 1. Then the LoRA track is open with key style `loud`
(or loud3/loud4 if one of those alone reaches >= 18 and loud_all does not). FAIL (`loud_all` < 18) = the stack applies
adapters only partially (a scorer-side defect to report on the forum) and the LoRA track is closed.

**G-A2 amendment 2026-10-03 20:20 IST (before the build, before the run):** `loud_all` = q_proj of ALL 60 layers at
r=1 (not q/k/v/o): the adapters travel base64-embedded in the notebook and the largest notebook ever pushed is 0.5 MB;
q/k/v/o at r=4 would embed ~13 MB. A random r=1 adapter on every layer's q_proj still perturbs every layer's attention,
which is what the >= 18/20 test needs. Everything else in the G-A2 block stands. Runs as a new version of the Sep-28
slug g4-l4-v9-eog (3.12 image) so it does not disturb the v4h2/v4/v4h3 sequence on g4-l4-v4.
