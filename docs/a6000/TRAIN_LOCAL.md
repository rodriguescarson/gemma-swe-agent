# Training on the A6000: the thinking-on QLoRA (pre-registered 2026-10-11, Mac, before any training run)

Plan: `~/.claude/plans/nifty-sleeping-liskov.md` (Track C). Why: past 0.18 only LoRA post-training moved anyone on the public
board (forum 748051), and both of our adapters (v11a, v11b) were trained on thinking-OFF, loop-heavy rows and learned to keep
calling tools. The new data are the thinking-ON trajectories of the P10 collection pass (`~/g4/runs/p3_think`, successes only,
`reasoning_content` carried into every completion by `train/scorer_render.py`). One GPU: training and serving never overlap.

## Pipeline (all on the box, `scripts/a6000/train.sh`; nothing heavy on the Mac)

| step | command | writes | gate |
|---|---|---|---|
| rows | `~/g4/venv/bin/python scripts/a6000/p3_build.py --out ~/g4/runs/p3_think` | `rows.jsonl` (full history per call, thoughts inside) | build rc 0; the data report's `thoughts:` share >= 0.80 (rows whose completion starts with a non-empty thought channel) |
| env | `bash scripts/a6000/train.sh env` | `~/g4/train-venv` (torch 2.10.0+cu128, transformers 5.17.0, peft 0.21.0, bitsandbytes >= 0.47, accelerate 1.15.0, compressed-tensors) | prints `cuda ok` |
| dequant | `bash scripts/a6000/train.sh dequant` | `~/g4/model-bf16` (63 GB; `train/dequant_ct.py`, int4 g32 unpack checked against compressed-tensors on 3 tensors) | `DEQUANT.json` |
| stitch | `bash scripts/a6000/train.sh stitch ~/g4/runs/p3_think think1` | `~/g4/runs/train_think1/{seqs,holdout,seqs_probe}.jsonl`, `stitch_report.json`, `validate_stitched.json` | validator `ok: true` (incl. `thought_share >= 0.8`: model spans starting with a non-empty thought / model spans), `sequences_with_thought == sequences`, >= 40 sequences (re-registered 2026-10-11: one sequence per solved trajectory with the single-agent collector; the run's schedule scales with the count, `train.sh recipe N`) |
| probe | `bash scripts/a6000/train.sh probe think1` | `~/g4/runs/train_think1/probe/{train_log.jsonl,probe_report.json,probe_adapter_bf16}` | verdict below |
| full | `bash scripts/a6000/train.sh full think1 [--max-tokens 12288]` | `~/g4/runs/train_think1/run/{ckpt,best,adapter_bf16,summary.json}` | the stop rule below |
| status | `bash scripts/a6000/train.sh status think1` | | |

Stitching (`train/stitch_rows.py`): one sequence per (trajectory, stage) in capture order; exact chain with thoughts; the
harness's own re-rendering of a call (and its dropped empty thought channel) is healed by keeping the model's bytes; an ADK
compaction (`For context:[model] said:`) or any divergence inside the shared prefix starts a new sequence. Span weights
(`train/spans.py`): text replies 1; a call identical to an earlier one in the sequence 0; a call whose tool response is an
error 0; `read_file` calls over 15 % of the live tool calls 0 (seeded); <= 10 sequences per (task, stage), fewest calls
first; > 14,336 tokens dropped; 5 held-out tasks (`data/v11/v11b_holdout_tasks.txt`, or 5 drawn when none of those is in
the collection, written to `seqs.jsonl.holdout_tasks.txt`). Dry run on the old v11b rows (thinking off): 1,174 sequences,
7.8M tokens, 2.3M supervised chars, 887 breaks, 127 compactions.

Gate (a) extended (2026-10-11, GAPS "gate (a) extended"): the thought must reach the TRAINING data, not only the capture files.
Mid-run on the box, `scripts/a6000/think_share.py ~/g4/runs/p3_think --min-share 0.8 --render` runs this renderer and stitcher on
the captures (RENDER GATE: thinking flag on every call, completions with thought >= 0.80, exact chain pairs >= 0.80, breaks
<= 0.02, model spans with thought >= 0.80); then the rows gate above (`validate_rows.py --min-thought-share`), then the stitch
gate above. Stitch gate addition (pre-registered 2026-10-12 after the first real stitch: 3 of 159 sequences carried no non-empty
thought at all): `train.sh stitch` passes `--require-thought`, the stitcher drops such sequences and reports `dropped_no_thought`
with their tasks, and the gate allows at most 5% dropped (a sequence without a thought teaches calling without thinking, the v11
failure; above 5% the collection itself is suspect: stop). Reasonless calls (thinking on, empty thought) stay in the rows: dropping a row would not drop its span (the stitcher
re-includes the harness's rendering of that reply), keeping it keeps the model's own bytes. A span masked by the weight rules
masks its thought with it; `span_thought_masked` in the stitch report counts those.

## The 1-hour feasibility probe: pass/fail fixed before it runs

`train/qlora_train.py --probe` (vLLM down; `seqs_probe.jsonl` keeps sequences up to 16,384 tokens so the top bucket exists):

1. imports; `torch.zeros(1).cuda()` with `PYTORCH_CUDA_ALLOC_CONF` unset; bitsandbytes importable; GPU idle (< 1 GB used per nvidia-smi, read before the trainer's own CUDA context exists; torch's mem_get_info counts that context, ~1 GB, and is only the fallback).
2. NF4 base loaded: allocated <= 21 GB (`loaded.alloc_gb`).
3. PEFT attached (regex: q,v,o,gate,up,down on all 60 layers, k on the 50 sliding layers; the count of wrapped modules must
   equal the regex's matches); one 2k forward with the math SDPA kernel disabled: max |logit| <= 30 (the softcap), base
   supervised NLL in [0.3, 1.5]. Outside either range = the base is not the served model = FALLBACK.
   Amended 2026-10-12 after the first real probe read 0.1949 on 64 supervised tokens (single-sequence step losses 0.17-0.47
   agree): the check's purpose is a wrong base or a broken dequant, which reads HIGH; a low loss on the model's own samples
   cannot mean that, so only NLL > 1.5 is FALLBACK and NLL < 0.3 is reported as informational. Post-hoc, recorded in GAPS.
4. 20 single-sequence steps longest first (5 x <5k, 5 x 5-9k, 5 x 9-13k, 5 x 13-16k), then 24 steps on 8 sequences near 6k
   tokens with grad_accum 4:
   - peak reserved in the 9-13k bucket <= 44 GB; OOM at 13-16k but not at 9-13k = the run uses `--max-tokens 12288`;
   - throughput over the single-sequence steps (forward + backward + optimizer): >= 150 tok/s = FULL (the recipe below,
     ~9-10M tokens, <= 18 h); 100-150 = REDUCED (`--max-tokens 12288`, re-stitch with `--max-seqs-per-task-stage 6`);
     < 100 = FALLBACK;
   - the repeated-step loss must fall >= 30 % from its first two steps to its last two; no NaN; grad norm < 100.
5. bf16 export of the probe adapter: 2 tensors per wrapped module, all bf16, keys matching `train/package_adapter.py`'s rule.

Verdict and reasons land in `probe_report.json` and in GATE.md addendum 15 verbatim. FALLBACK = no local run; the Mac trains
the hosted way (`train/adaption_train.py`, Ross's credits, row-level rebalanced rows) with the same data.

## The real run (`train.sh full`)

LoRA r16, alpha 32, dropout 0.05; lr 5e-5 peak, 3 % warmup, cosine to 10 %; AdamW fp32 on the LoRA params, clip 1.0;
grad_accum 8 sequences (~50k tokens per step), 1 epoch (~160-190 steps) when the stitch gives >= 200 sequences; below that (the
single-agent collector: one sequence per solved trajectory, 40-150 expected by the hard stop) `train.sh full` applies
`train.sh recipe N` = grad_accum 2, epochs = min(6, ceil(360 / N)) (about 180 optimizer steps), held-out eval and checkpoint every
10 steps, the same stop rule (re-registered 2026-10-11 before any data existed; explicit flags after it still win); the loss of a step is the token mean over all its
supervised tokens (a 2,000-token reply weighs 50 one-line calls). Held-out NLL at step 0 and every 40 steps, split by span
kind (text replies vs tool calls); the best checkpoint by held-out TEXT NLL is exported to `best/`; stop when the text NLL
has been > 5 % above its minimum on two consecutive evals. Checkpoint + optimizer + cursor every 40 steps; `--resume`
(the launcher passes it) continues from the cursor. The log's `alarm_tok_s_halved` flags GPU contention (seen 2026-10-07).
More than 5 OOM steps abort (exit 4): lower `--max-tokens`.

## After training: the gates before any slot (unchanged from the plan)

1. On the box: `~/g4/venv/bin/python train/package_adapter.py ~/g4/runs/train_think1/run/best --bundle submissions/<collector>
   --out submissions/<collector>_think1 --name think1 --key-style loud --stages <the collector's stages>` (weights never enter
   git); `python scripts/adapters_dataset.py --bundle submissions/<collector>_think1 --slug g4-adapters-think1 --out ~/g4/ds --push`.
2. Mac: the probe kernel (`make_eval_kernel.py ... --probe lora --adapters-dataset carsonrodrigues/g4-adapters-think1`), the
   V-2 gate: applied >= 2/20, zero-B harmless, 5-task smoke solved >= the control's with <= 2 budget-outs, mean time <= 1.3x.
3. The 74-task L4 pair against the collector bundle: KEEP only if paired net >= +3. Then one pre-registered slot.

## WSL2 hygiene (docs/a6000/DEVIATIONS.md)

Never `PYTORCH_CUDA_ALLOC_CONF=expandable_segments` (CUDA init fails here); `/mnt/*` off PATH; everything under `~/g4`;
`train.sh` refuses to start when a serving/supervisor process is alive, nvidia-smi shows > 1 GB used (stale VRAM after a
hard stop: `wsl --shutdown` from Windows) or port 8000 answers; runs are `setsid nohup` with their own `train.out`.


**Probe rule added 2026-10-12 (before the rerun; the box's first probe is in GAPS "Probe: the 13-16k bucket thrashes").**
A bucket whose step crawls under 30 tok/s is "unusable" exactly like one that OOMs: the allocator is paging at the card's
limit (15,844 tokens: 83 tok/s and 46.5 GB on one step, 6 tok/s and 47.8 GB on the next). The run never trains at that
length (cap 12,288), so the probe's tok/s is computed over the usable buckets only and the excluded buckets are listed in
the report (`excluded_buckets`, `thrash_at_16k`); `cap_tokens` is 12,288 when the top bucket is unusable, when the verdict
is REDUCED, or when the probe itself ran with `--max-tokens 12288`. The FULL / REDUCED / FALLBACK thresholds (150 / 100
tok/s) and every other check are unchanged. The rerun on the box passes `--max-tokens 12288` so the top bucket's five steps
measure the longest contexts at the run's own cap instead of crawling for two hours.
