# v11 plan C: schedule-first

Planner C, written 2026-09-28 17:40 IST (12:10 UTC). Angle: fit v11 into the calendar (daily slots, the 12 h scorer cap,
paper track 2026-11-12, main track 2026-12-02, Carson's other deadlines, the ~$500 cap), ordered by expected hidden-set
gain per dollar and per day. This file changes over time: §11 lists what triggers an update, and §13 is the changelog.

Nothing here has been run. Pod starts, Kaggle pushes, submissions, forum posts and downloads over 1 GB are Carson's
call. Every paid step below states its cost and its pre-registered gate before it runs.

Inputs: `docs/v11/facts_internal.md` (FI), `docs/v11/facts_external.md` (FE), `docs/v10/SPEC.md`,
`docs/v10/race2_checklist.md`, `research/update_0928.md`, `research/time_model.md`, `research/own_data.md`,
`eval/ledger.md`, `~/Projects/competition-tracker/data/competitions.json`, the approved plan
`~/.claude/plans/goofy-skipping-hearth.md`. Times are IST, with UTC in brackets where Kaggle defines the time.

---

## 0. Bottom line

1. **Kaggle eval windows are the scarcest resource, not money.** Carson's rule is that nothing runs on Kaggle while a
   submission is scoring, and a scored run takes about 10.4-12 h. So a day with a submission leaves about 12 h for eval
   kernels, while 4×L4 queues run 4-9 h. v11 therefore takes **eval blocks**: skip 1-2 daily slots and get a 36-60 h
   window with no scoring. 65 slots remain, and a single LB draw cannot rank bundles anyway (SD of a two-run difference is
   about 2.5-3.5 tasks), so a skipped slot is cheap and an eval window is not.
2. **The first three steps are gates that cost almost nothing and decide the rest.** G0 is the LoRA gate on the pod
   (about $10). K1 is a Kaggle 4×L4 probe (free quota): at TP4 it checks that adapters change outputs, measures the
   LoRA-mode speed tax, and compares TP4 with TP1 logprobs. Z is one submission slot with a zero-effect adapter, the only
   test of the real Docker scorer's adapter path and 12 h fit. Training money (about $60) is not spent until G0 and K1
   pass.
3. **Data generation is dual-use, which is why it comes before the training decision is certain.** v10 runs on
   SWE-Pallets-X (8 repos, CC0) give SFT data for v11 **and** the "Best New Resource" dataset for the paper track
   (2026-11-12). If LoRA dies, the data still has a buyer.
4. **The old 349 resolved trajectories cannot train v11-a.** 39 of their 43 tasks are in the 74-task evaluation set
   (checked against `data/kaggle_valid_ids.txt`), and none uses v10's action space (FI §4.6). Training on them would
   make the evaluation measure memorisation. v11-a trains only on Pallets-X repos, so the 74 public tasks are an unseen-repo
   test, like the hidden set.
5. **v11-a is one shared adapter on locator, fixer and verifier.** Setup and submitter stay on the base model. Per-stage
   adapters (v11-b) come only after v11-a shows an effect and each stage has at least 300 supervised segments.
6. **Honest expected gain.** Plain self-RFT at 32B gives 0 to +1 point in the literature (FE §3). Our lever is format and
   efficiency: malformed calls, repeats, and seconds per task on cap-bound hidden tasks. The estimate is about +1 hidden
   task of 58 if the gates pass (80% range −1 to +4), and about +0.01 LB unconditionally. v11 will not reach 0.30 by
   itself. The paper resource is the larger expected value of this spend.
7. **Critical path**, if v10 freezes by Sat 3 Oct: pod session 1 on 4-5 Oct, K1 on 4-5 Oct, the Z slot on 6 Oct, training
   on 7-8 Oct, paired Kaggle rounds R1 and R2 on 9-12 Oct, and the v11-a decision on **Mon 12 Oct**. The kill date for
   LoRA on the main track is **Sun 8 Nov**.
8. **Budget.** About $404 remains (FI §6: $96.09 billed through 09-28, against a ledger that shows about $51). Race 2
   takes about $35 of it. v11 is capped at **$250** (v11-a ≤ $160, v11-b ≤ $90 and conditional), which leaves about
   $119 for v10.x races and final checks.

---

## 1. Calendar constraints

### 1.1 Fixed dates

| date (IST) | what | effect on v11 |
|---|---|---|
| daily 05:31 (00:01 UTC) | submission slot (1/day), scoring about 10.4-12 h | no Kaggle kernels until it is COMPLETE (Carson's 09-27 rule) |
| Tue 29 Sep - Sat 3 Oct | v10 finishing: race 2 on the pod, v10's own faithful L4 gate, v10 ship | v11 is Mac-only and free here; it needs v10's prompts frozen ("T_freeze") |
| Wed 30 Sep - Thu 1 Oct | Kaggriculture (09-30 23:59 UTC), Vesuvius Sept (09-30 PT), Shipaton (10-01 12:15) | Carson has no attention for approvals |
| Fri 2 Oct | Adaption talk; ARC White-Box registration freeze (23:59 UTC) | same |
| Sun 4 Oct | Fatima Fellowship deadline | same |
| Fri 16 - Tue 20 Oct | Italy trip window (listed in the approved plan's calendar collisions) | only unattended, pre-approved chains |
| Sat 17 Oct (23:59 UTC) | ARC White-Box Phase 2 ends | same |
| Fri 23 Oct / Sat 24 Oct | Amazon hackathon (Oct 24 00:30 IST) / ARC write-up (Oct 25 05:29 IST) | same |
| Fri 30 Oct | Nebius (22:30 IST) | same |
| **Fri 13 Nov 05:29 (Thu 12 Nov 23:59 UTC)** | **paper track deadline** | v11 data and tools become the resource entry |
| Sun 15 Nov | Code for a Billion | Carson busy the week before |
| Wed 25 Nov | team merger deadline | last merger decision |
| **Thu 3 Dec 05:29 (Wed 2 Dec 23:59 UTC)** | **main track deadline**, 2 final submissions | freeze by Sat 28 Nov |

The approved plan says Gemma is top priority from 1 Oct to 2 Dec and other deadlines get minimum entries. Carson's
attention for approvals is still the bottleneck in the weeks above, so approvals are batched (§3.3) and every pod session
is a self-stopping chain.

### 1.2 Kaggle mechanics that set the pace

| fact | source | consequence |
|---|---|---|
| 1 submission per day; 65 slots from 29 Sep to 2 Dec | rules; `research/update_0928.md` §2.3 | slots are plentiful |
| a scored run takes about 10.4-12 h; SD of a two-run difference about 2.5-3.5 tasks of 58 | update_0928 §0.2 | one LB draw ranks nothing; it only catches catastrophic failures (≤ 0.03 or ERROR) |
| no Kaggle kernels while a submission is scoring | Carson 09-27 (memory) | eval kernels need windows with no scoring |
| at most 2 GPU sessions queued or running; saving a new version can cancel a queued one (UNVERIFIED) | osama133, update_0928 §1.3 | 2 kernels per window, with a distinct slug per arm and round |
| 4×L4 queue 4-9 h; queue time may be charged to quota (UNVERIFIED) | 743600, 743901, 743683 | plan about 12 h wall per kernel |
| one 74-task v10 kernel is about 3.2 h of tasks + 0.2 h startup + 0.2 h verification = about 3.6 h | `replay_l4.py --design final` 154 s/task; time_model §1 | 2 arms fit in parallel in one window |
| weekly GPU quota: amount for 4×L4 and reset day UNVERIFIED (the Kaggle standard is 30 h/week) | none | step V11-00 reads it; plan ≤ 20 GPU-h per quota week |
| RunPod 4×L4 as a Kaggle-faithful fallback: **out of stock** (get-capacity, 12:10 UTC 09-28) | RunPod MCP | not a plan dependency; re-check if Kaggle quota binds |

### 1.3 The slot and window rule

- **S-day**: a slot is used. Kaggle stays free of kernels from 00:01 UTC until the submission shows COMPLETE (about 12:00
  UTC, 17:30 IST). `scripts/push_after_scoring.sh` already waits for that.
- **E-block**: 1 or 2 consecutive slots are skipped. That gives a 36 h window (one skip) or a 60 h window (two skips),
  starting when the previous day's scoring completes.
- A slot is used only for: (a) the first scorer run of a new bundle class (the Z smoke; the first trained adapter),
  (b) a bundle that passed its faithful gate, or (c) redraws of finalists after 20 Nov, when eval blocks are no longer
  needed. Otherwise the day goes to eval kernels.
- v10.x work owns every window not claimed below. v11 claims E1, E2, E3 and E4 (§2).

---

## 2. Timeline

Dates assume T_freeze (v10's prompts, tool lists and helper interface frozen) by **Sat 3 Oct**. §11 says what moves when
that slips. Data generation does not wait past **Wed 7 Oct**: if v10 is not frozen by then, data is generated with the
current v10 bundle and re-rendered later (§6.3).

| week | dates | v11 steps (IDs from §4) | Kaggle | pod | Carson |
|---|---|---|---|---|---|
| W0 | Mon 28 Sep - Sat 3 Oct | V11-00 to V11-08: all free, Mac-only engineering and tests | v10's windows | race 2 (v10's budget) | one batched approval on Sat 3 Oct (A1) |
| W1 | Sun 4 - Sat 10 Oct | V11-09 pod session 1 (G0 + Pallets data), 4-5 Oct; V11-10 K1 in **E1** (skip the Mon 5 Oct slot: window Sun 4 Oct 17:30 to Tue 6 Oct 05:31); V11-11 **Z slot on Tue 6 Oct 05:31**; V11-12 SFT build, Tue 6 Oct; V11-13 pod session 2 (train + screen), Wed 7 - Thu 8 Oct; V11-14 adapter dataset upload, Thu 8 Oct | E1, then Z | s1, s2 | approvals A2 (Thu 8 Oct) |
| W2 | Fri 9 - Mon 12 Oct | V11-15 faithful R1 + R2 in **E2** (skip the Sat 10 and Sun 11 Oct slots: window Fri 9 Oct 17:30 to Mon 12 Oct 05:31) | E2 | none | decision D-v11a on **Mon 12 Oct** |
| W2-W3 | Tue 13 - Thu 22 Oct | V11-16 LB slot for v11-a (Tue 13 Oct 05:31) if PASS; V11-17 pod session 3 (v11-b data, conditional) on Wed 14 - Thu 15 Oct, before the Italy window; V11-18 pod session 4 (v11-b train + screen) on Wed 21 - Thu 22 Oct | slots free for v10.x | s3, s4 | approval A3 (Tue 13 Oct) covers s3, s4 and E3 |
| W4 | Fri 23 - Mon 26 Oct | V11-19 faithful v11-b R1 + R2 in **E3** (skip the Sat 24 and Sun 25 Oct slots) | E3 | none | decision D-v11b on Mon 26 Oct |
| W4-W6 | Sun 25 Oct - Thu 12 Nov | V11-20 paper resource: draft-save test by Sun 25 Oct, dataset card and release package from Mon 2 Nov, **first paper submission Fri 6 Nov** (ties go to the earlier entry), final Wed 11 Nov | slots free | none | approvals A4 (dataset release), A5 (paper text) |
| W6 | Sun 8 Nov | **LoRA kill date**: no variant has passed its faithful gate, so LoRA stops for the main track | | | |
| W7-W9 | Fri 13 Nov - Wed 2 Dec | V11-21: at most one more iteration (v11-c) only if v11-a or v11-b passed; **E4** (skip the Sat 21 and Sun 22 Nov slots) re-checks the two finalists pairwise; merger decision Wed 25 Nov; freeze Sat 28 Nov; select finals and deliver the Apache-2.0 reproducibility package by Wed 2 Dec | E4 | none, or 1 short session | A6 (finals) |

If the Kaggle quota resets on Saturday 00:00 UTC (UNVERIFIED), E2 and E3 each straddle a reset, so R1 and R2 land in
different quota weeks.

---

## 3. Gain per dollar and per day, and the approvals

### 3.1 Ranking

| # | option | $ | wall | what it buys | why it is in this position |
|---|---|---|---|---|---|
| 1 | G0 LoRA gate (pod) | 7-10 | 1.2 h | decides whether ~$200 of v11 spend can pay off; a bug report with public credit | cheapest decisive test |
| 2 | K1 Kaggle probe | 0 (about 2 GPU-h) | 1 E-window | TP4 correctness and LoRA-mode tax on the real hardware | pod numbers are not predictive of L4 |
| 3 | Z smoke slot | 0 (1 slot) | 1 day | real Docker scorer: an adapter bundle validates, loads and fits 12 h | nothing else tests the scorer |
| 4 | Pallets data, round 1 | 45-60 | 8 h | SFT data **and** the paper resource | dual use |
| 5 | Train + pod screen v11-a | 55-65 | 9 h | the first adapter and a catastrophic-regression screen | only after 1-3 pass |
| 6 | Faithful R1 + R2 | 0 (about 15 GPU-h, 2 slots) | 60 h block | the ship decision | the only ship instrument |
| 7 | v11-b (self-teacher data, per-stage adapters) | 80-90 | 2 sessions + 1 block | +0-2 tasks beyond v11-a, conditional | only if v11-a is PASS or INCONCLUSIVE+ |

### 3.2 What v11 does not do

- No v11 run uses the nebius/Qwen3-Coder set (the other-models ruling is pending, 742807).
- No training on the 129 public tasks while the 74 are the evaluation set.
- No run spends money on a step whose gate cannot fire: every paid step has a free or cheaper predecessor.

### 3.3 Batched approvals (one message each)

| id | when | what Carson approves |
|---|---|---|
| A1 | Sat 3 Oct | pod session 1 (cap $85, MAX_HOURS 12); downloads on the pod (wheelhouse v25 433 MB, w4a16 23 GB, Pallets-X 10.3 GB); K1 push in E1; skip the Mon 5 Oct slot; Z submission on Tue 6 Oct 05:31 |
| A2 | Thu 8 Oct (morning) | pod session 2 (cap $75); private Kaggle dataset upload of the v11-a bundle; E2 (skip the Sat 10 and Sun 11 Oct slots, 4 kernel pushes) |
| A3 | Tue 13 Oct | v11-a LB slot (if PASS); a post in 743508; pod sessions 3 and 4 (cap $90 together, conditional); E3 pushes, pre-approved to run while Carson is away |
| A4 | Sun 1 Nov | dataset release scope (Pallets part; the public-task part only if 743255 Q4 allows it) |
| A5 | Thu 5 Nov | paper text (through ai-writing-detection + voice-dna.md, per Carson's writing rule) |
| A6 | Fri 27 Nov | the two finals and E4 |

---

## 4. Steps

Each step lists the exact scripts, the gate (written now, before the run), the cost, the wall time and what happens on
failure. "Agent h" means build time on the Mac at no cost.

### Phase W0: free engineering (Mac only, before T_freeze)

**V11-00 Ledger and quota catch-up.** $0, 0.5 agent h.
- Add rows to `eval/ledger.md` for race 1 ($33.19), r02i1c2nbk4v6p ($28.18), 87kqp9osz3gn6o ($18.91) and the correction
  to $96.09 billed through 09-28 (source: RunPod `list-pod-billing`, FI §6). Add a `v11` budget line with the $250 cap
  and a running total.
- Record the Kaggle GPU quota (the kaggle.com settings page; Carson or Chrome, 1 min) and its reset day.
- Gate: the ledger total is within $1 of RunPod billing. On failure, the ledger is corrected before any v11 spend.

**V11-01 Scorer renderer promoted into `train/`.** $0, 3 agent h.
- Move `docs/v11/evidence/render.py` to `train/scorer_render.py`, and the June template to
  `train/templates/chat_template_kaggle_v2_june.jinja` (sha256 `94899c0f...`, 16,934 B), with
  `tokenizer_config_kaggle_v2.json`.
- New `tests/test_v11_render.py`:
  - CI tier: renders `EV/bodies_a.json`, `EV/bodies_d.json` and `EV/bodies_adapter.json`, and asserts the three scorer
    effects (FI §2.4): `trim(system) + ' '`, `For context:[setup] said:` with no separator, and the 26-char generation
    prompt only on first calls.
  - NIGHTLY tier: recomputes FI §3.3 with the HF tokenizer.
- Gate: 2,391/2,391 continuation increments exact on e74_v3, and 53/53 post-compaction first calls at −4. On failure,
  nothing downstream is built until they match.

**V11-02 SFT data builder `train/build_sft.py`.** $0, 8 agent h.
- Two input modes:
  - (a) **capture logs** from `pod/capture_proxy.py` (V11-05): exact request bodies, raw completions, and compaction
    summariser calls. This is the v11 path.
  - (b) traces plus bundle, the FI §3.2 fallback, for the paper dataset only.
- It does, in order:
  - rebuild the double-encoded tool results per tool (FI §2.4);
  - supervise the empty thought channel exactly where the model emitted it (raw tokens in mode a, the +4 rule in mode b);
  - render two sequences per stage segment (first call exact; final prompt with loss on completions 2..n; FI §2.5);
  - mask malformed calls and their echoes, validated against `EV/tool_schemas_v10.json`;
  - drop steps with parallel calls;
  - error-mask turns whose next observation is a tool or test error (SWE-Lego);
  - keep at most 2 trajectories per task, the shortest predicted L4 time first;
  - apply the L4 filter: 0.99 s per call + 26.5 ms per completion token + recorded tool time ≤ 250 s;
  - write a repo-held-out validation split (`--val-repo jinja2`);
  - write `manifest.jsonl` with sha256, source run, task, repo and bundle hash.
- **Leak guard:** hard exclusion of every task id in `data/tasks.jsonl` (all 129 public) and of the repos fastapi, rich,
  requests and httpx. The builder exits 2 if any sample matches.
- Command: `.venv/bin/python train/build_sft.py --captures eval/v11/s1/captures --bundle submissions/v10 --exclude-tasks data/tasks.jsonl --exclude-repos fastapi,rich,requests,httpx --cap-per-task 2 --l4-max-s 250 --val-repo jinja2 --out train/data/v11a`
- Tests `tests/test_v11_build_sft.py`, at least 12 cases: double encoding; empty-channel supervision; malformed masking;
  parallel-call drop; error masking; per-task cap; the L4 filter; the leak guard (it must fail on a planted public task id);
  the June template's stray `<turn|>` in a text-plus-tool-call turn (FE §2.2); deterministic output bytes.
- Gate: all tests pass, and a dry run on `EV/bodies_d.json` gives spans whose decoded text equals the recorded completions.

**V11-03 `train/sft.py` v2 and the train env.** $0, 6 agent h.
- Base: `google/gemma-4-31B-it-qat-w4a16-ct` loaded with `CompressedTensorsConfig(dequantize=True)` in bf16 (FE §2.1).
  Before writing it, check on the Mac for free whether transformers 5.13.1 has `dequantize`
  (`uv pip download transformers==5.13.1` and grep `quantization_config.py`). If not, pin the first version that has it
  in `pod/train_env.sh` and re-check that vLLM-side pins are unaffected (the train venv is separate).
- LoRA r16/α32 on q, k, v, o, gate, up and down of `language_model` only; sdpa; gradient checkpointing.
- Loss: gather hidden states at supervised positions only, then `lm_head`, softcap 30, then CE, in chunks of 1,024
  positions. That avoids the 17 GB full-vocabulary logits (FI §5.1 item 7).
- lr 1e-4 cosine, warmup 3%, max_norm 1.0, seed 0, at most 2 epochs. Validation NLL on the held-out repo every quarter
  epoch. Every step logs grad norm, max|logit| and tokens/s. No ZeRO-3.
- Tests: `tests/test_v11_sft_loss.py` (chunked CE equals full CE on a tiny random model on CPU, to 1e-5; softcap applied);
  update `tests/test_sft_masking.py` for the June renderer.
- Gate: tests pass. Everything about GPU memory stays UNVERIFIED until the V11-13 probe.

**V11-04 Export and bundle.** $0, 4 agent h.
- `train/export_adapter.py <peft_dir> <out_dir> --kv-mode dup`:
  - cast to bf16;
  - on the full-attention layers 5, 11, ..., 59, copy each `k_proj` LoRA pair to `v_proj`, because vLLM gives the V slot a
    `None` LoRA otherwise (FE §0.2). `--kv-mode exclude` drops `k_proj` on those layers instead;
  - key prefix `base_model.model.model.language_model.layers.N...`, no vision keys;
  - `base_model_name_or_path: google/gemma-4-31b-it-qat-w4a16-ct`;
  - `r` and `lora_alpha` match the tensor shapes; total bundle < 3 GiB.
- `scripts/make_v11_bundle.py submissions/v10 <adapter_dir> submissions/v11a --name v11_a --stages locator,fixer,verifier`
  adds only `adapter: v11_a` lines and `adapters/v11_a/`.
- Tests:
  - `tests/test_v11_export.py`: a synthetic PEFT dir goes through export; check keys, dtype, the duplicated `v_proj` on
    exactly 10 layers, sizes against FE §1.3.
  - `tests/test_v11_bundle.py`: the diff against v10 is only adapter lines plus `adapters/`; `scripts/validate.py` prints
    `OK model=`; adapter names match `^[a-zA-Z0-9_.-]+$`, contain no `gemma4`, and match neither `^o\d` nor `^gpt-5`
    (FI §1.5); no `.pyc`.
- Gate: tests pass.

**V11-05 Pod serving parity, LoRA gate, capture proxy.** $0, 6 agent h.
- `pod/bootstrap.sh`:
  - install the wheelhouse v25 vLLM and assert the CRCs `gemma4.py c8cefd56` and `model_manager.py e16a1908` (FE §1.1);
  - copy the June template and the Kaggle v2 `tokenizer_config.json` into the served model dir (FI §5.5).
- `pod/serve.sh`: `LORA_DIR=<dir>` expands to `--enable-lora --max-loras 8 --max-lora-rank 128 --lora-modules <name>=<path>...`.
- `pod/lora_gate.py`, the G0 checks of FE §1.5 steps 1-3:
  - random `lora_B` ~ N(0,1), top-1 at T=0 on 20 prompts, plus a count of DEBUG `No LoRA weights found ... self_decoder`
    lines;
  - per-family Δlogprob parity against HF, on 2k tokens of a real trace: q, k-sliding, k-full with dup, k-full without
    dup, v, o, gate+up, down. The HF reference is dequantized w4a16 on GPU 0; vLLM runs TP1 on GPU 1, then TP2 on both
    GPUs, to check LoRA sharding;
  - determinism by rank for r ∈ {16, 32, 64, 128}: 5 repeats + 1 restart, 256 tokens, 5 prompts;
  - whether vLLM 0.19.1 accepts `return_token_ids` (fallback: `logprobs`), so raw completions can be logged.
  - Output: `eval/v11/g0.json` with PASS or FAIL per check, and the TP1 Δlogprob reference `eval/v11/k1_ref.json` for K1.
- `pod/capture_proxy.py` (stdlib `http.server` and `urllib`):
  - sits between LiteLLM and vLLM, forwards bytes unchanged, and adds only `return_token_ids`/`logprobs`;
  - appends request body, response and raw completion tokens to `eval/v11/<run>/captures/*.jsonl`;
  - maps each request to its task by the sha256 of the first user message, which `run_eval.py` also logs.
- `pod/supervisor.sh`: add `python pod/lora_gate.py` to the active-job regex, and never `capture_proxy`, so the pod is
  neither stopped mid-gate nor kept alive by the proxy.
- Tests:
  - `tests/test_pod_scripts.py`: `bash -n`, shellcheck, LoRA flags, template install, both supervisor regex cases;
  - `tests/test_v11_capture_proxy.py`: against a fake upstream, bytes pass through unchanged; the log has one line per
    request; task mapping.
- Gate: tests pass on the Mac and in `scripts/linux_test.sh`.

**V11-06 SWE-Pallets-X adapter.** $0, 6 agent h.
- `scripts/pallets_env.py` builds per-instance uv venvs with era-matched Python, using the dataset's own
  `verify.py`/`era_pin.py` (CC0). `scripts/run_eval.py` gets `G4_ENV_MAP=<json task→venv>`, so the subprocess sandbox
  uses that interpreter and site-packages.
- `scripts/pallets_oracle.py` applies the gold patch and the empty patch per task, 8 in parallel, and writes
  `data/pallets/valid_ids.txt`.
- Mac smoke, free: 10 tasks from `EX/pallets/tasks.jsonl`. The full 10.3 GB download happens on the pod (A1).
- Gate on the Mac: gold passes on ≥ 8/10 and empty fails on 10/10. On failure, fix before A1, or fall back to SWE-rebench
  `install_config` venvs (CC-BY-4.0), which costs 1 more agent day and moves W1 by a day.

**V11-07 Kaggle kernel paths.** $0, 5 agent h.
- `scripts/make_eval_kernel.py`:
  - `--from-bundle-config` reads the four budgets from the bundle's `eval_config.yaml`, fixing the CLI-default mismatch of
    update_0928 §3.6;
  - `--bundle-dataset <owner/slug>` loads bundles too big to base64 (a 245 MB adapter) from a private dataset and asserts
    their sha256 in the kernel;
  - it prints the vLLM `gemma4.py` CRC and scrapes `/metrics` for `vllm:lora_requests_info` at the end;
  - `--probe k1` mode, described in V11-10.
- `scripts/make_kernel.py --adapters-dataset <owner/slug>`: the submission notebook copies the adapter from `/kaggle/input`
  into `submission.zip` and asserts its sha256.
- Tests: generated notebook JSON is valid; budgets are read from the bundle; the sha assertion fails on a flipped byte.
- Gate: tests pass.

**V11-08 Pre-registration.** $0, 2 agent h. Must be committed before V11-15 starts.
- `docs/v11/checklist.md` holds the §5 protocol verbatim.
- `scripts/v11_kpis.py` reuses `replay_l4` KPI definitions and holds the thresholds as constants.
- `tests/test_v11_kpis.py` fails if the constants differ from the checklist, the same way race 2 pins its KPIs.
- Changes after R1 starts go only into a dated addendum.

### Phase W1: gates and data

**V11-09 Pod session 1: G0, then Pallets data round 1.** Expected $71, **cap $85** (`MAX_HOURS=12`). About 10-12 h wall.
Sun 4 - Mon 5 Oct.
- Chain `pod/chain_v11_s1.sh`, started by `pod/chain_boot.sh` on pod 2wyl66nmji13p1 (or a fresh 2×H100):
  1. boot;
  2. G0 (`pod/lora_gate.py`) on the GPUs, **in parallel** with the Pallets download and the full oracle on the CPU (56
     vCPU), so no GPU sits idle;
  3. if G0 passes: v10 data generation with `pod/capture_proxy.py`:
     - bundle v10 at the frozen hash; `G4_COMPACTION=1 G4_L4_SCALE=1.7 G4_NO_EDITABLE=1 FAITHFUL=1`; 2 tasks per GPU;
     - adaptive sampling: every valid task once, then a second pass over all, then passes 3-4 only for tasks with fewer
       than 2 successes;
     - stop at 8 h of generation, or at the cap;
  4. `pod/backup.sh` (HF + GitHub), then `runpodctl stop`, on every exit path.
- **Gate G0 (pre-registered, FE §1.5):**
  - top-1 differs from base on ≥ 18/20 prompts, with 0 `self_decoder` reset lines;
  - parity r ≥ 0.9 for every family at TP1 and TP2. The k-full family must pass with `--kv-mode dup`; without dup it is
    expected to fail, and that confirms FE §0.2;
  - identical tokens across repeats and the restart at r16. The chosen rank is the largest that passes.
- **Data gate (K5):** ≥ 120 L4-feasible resolved v10 trajectories over ≥ 60 tasks from ≥ 5 repos, and a valid Pallets
  subset of ≥ 250 tasks.
- On failure:
  - G0 step 1 fails: record it, stop LoRA (K1), and run data generation at 1 sample per task only (≤ 3 h, ≤ $25), for the
    paper resource. Draft the 743508 repro (post on Carson's go).
  - Parity fails for one family only: drop that family from the targets and continue.
  - Data gate misses: go to the K5 rule (§7).
- Throughput basis: race 2's plan gives about 74 task-runs per hour on this pod. The ledger's v7/v8 chain gives about 148.
  The plan uses 75-100 per hour, so 8 h is about 600-800 task-runs over an estimated 250-350 valid tasks at a 15-25%
  per-attempt solve rate (UNVERIFIED for Pallets).

**V11-10 K1: Kaggle 4×L4 probe, in E1.** $0; about 2 GPU-h plus queue. Window Sun 4 Oct 17:30 to Tue 6 Oct 05:31.
- `python scripts/make_eval_kernel.py submissions/v10 g4-v11-k1 --probe k1 --ref eval/v11/k1_ref.json`. The kernel
  builds seeded random and zero adapters itself, so nothing large is uploaded.
- Phases:
  1. server without adapters: decode tok/s at concurrency 1, 20 prompts × 512 tokens at T=0; time to vLLM up;
  2. server with adapters (tiny zero r1 q_proj layer 0; full seeded random r16): the same benchmark via the base name,
     the tiny adapter and the r16 adapter; top-1 A/B on 20 prompts; Δlogprob of the r16 adapter against the pod's TP1
     reference.
- **Gate:**
  - top-1 differs on ≥ 18/20 at TP4;
  - TP4 against TP1 Δlogprob r ≥ 0.95;
  - decode slowdown ≤ 10%, for both adapter requests and base requests in LoRA mode;
  - startup delta ≤ +300 s;
  - tiny-adapter tax within 3 points of the r16 tax, which makes the tiny Z smoke representative.
- On failure:
  - tax 10-25%: continue, but the §5 time gate decides;
  - tax > 25%, or TP4 does not change outputs: K2 (§7);
  - the kernel does not run in E1: move Z by one day and rerun in the next window. It is 2 GPU-h.

**V11-11 Z: zero-effect adapter smoke submission.** $0; 1 slot, Tue 6 Oct 05:31 (00:01 UTC); about 12 h.
- Bundle `submissions/v11z` = v10 plus the tiny all-zero `lora_B` adapter on locator, fixer and verifier, so the behaviour
  is identical to v10 while the server is in LoRA mode.
- Command: `python scripts/make_kernel.py submissions/v11z g4agent-v11z`, then the existing `scripts/submit_at.sh` path
  with tag `v11z:`.
- **Gate:** the submission completes with no ERROR and scores ≥ 0.05. Only ≤ 0.03 or an ERROR counts as a finding: a
  single draw cannot rank it against v10.
- On failure: an ERROR or ≤ 0.03 means adapters break on the real scorer → K3 (§7), and a forum report drafted for Carson.

**V11-12 Build the v11-a SFT set.** $0, 1 agent h, Tue 6 Oct.
- `train/build_sft.py` (V11-02) on `eval/v11/s1/captures`.
- Gate: K5 counts hold after filtering; leak guard clean; token totals written to the manifest, which V11-13 uses to price
  training.

**V11-13 Pod session 2: train, export, screen.** Expected $60, **cap $75** (`MAX_HOURS=10.5`). About 9 h wall. Wed 7 -
Thu 8 Oct.
- Chain `pod/chain_v11_s2.sh`:
  1. train env and the dequantized base;
  2. **probe (10 min, about $2):** tokens/s, peak memory per GPU, finite loss, max|logit| ≤ 30, grad norm logged;
  3. train v11-a for 2 epochs if the probe projects ≤ 5 h, else 1 epoch, else a 50% subset;
  4. export with `--kv-mode dup`;
  5. parity of the **trained** adapter, HF against vLLM TP1;
  6. serve v10 + v11-a under LoRA mode with the June template;
  7. pod screen: arm A v10, arm B v11-a, one round over the 74 tasks, 2 per GPU, faithful switches;
  8. capture the summariser check;
  9. backup, then stop.
- **Gates (pre-registered):**
  - probe: projected cost ≤ $45 for the chosen epochs, max|logit| ≤ 30, no NaN;
  - validation NLL on held-out jinja2 improves ≥ 3% against the base;
  - trained-adapter parity r ≥ 0.9;
  - **screen:** B ≥ A − 3 resolved; malformed calls per task down ≥ 30% **or** exact-repeat share down ≥ 30%; 0 new crash
    classes (race 2 row 3);
  - summariser: on 20 captured compaction prompts the adapter's summary is non-empty, ≤ 1,024 tokens, contains no tool-call
    tokens, and names ≥ 1 edited file whenever the input has one.
- On failure:
  - probe over budget: 1 epoch on a 50% subset, or stop and re-plan;
  - NLL, parity or screen fails: one retry at lr 5e-5 in the same session if ≤ 2 h remain, else K6.
- Pod screens are not predictive of the LB (standing rule). This screen only removes catastrophic candidates before they
  cost two slots and about 15 GPU-h.

**V11-14 Adapter transport.** $0, 0.5 h. Thu 8 Oct.
- `kaggle datasets create -p <dir>` as a **private** dataset `carsonrodrigues/g4-v11a-bundle`, holding the full bundle
  (A2).
- Gate: a CPU kernel copy of the dataset reproduces the Mac sha256. Pushing it is A2.

### Phase W2: the faithful gate

**V11-15 Faithful paired evaluation, R1 and R2, in E2.** $0; about 15 GPU-h; window Fri 9 Oct 17:30 to Mon 12 Oct 05:31.
The protocol is §5.
- R1: `g4-v11a-ctl-r1` and `g4-v11a-trt-r1`, pushed within 10 minutes of each other.
- R2: `...-r2`, pushed as soon as R1 is complete.
- Download each with `kaggle kernels output` into `eval/kaggle/v11a_{ctl,trt}_r{1,2}/`, then run
  `scripts/v11_kpis.py eval/kaggle/v11a_*`.
- Gate: §5.4. On failure: §5.5 and §7.

**V11-16 v11-a to the LB.** $0; 1 slot, Tue 13 Oct 05:31, only if §5.4 passes.
- Gate: completes, ≥ 0.05. The LB is not a ship instrument.
- After it, v11-a is a finals candidate next to the best v10-family bundle.
- The G0 and K1 findings (k_eq_v V slot, LoRA-mode tax, whether the fix works) go to 743508 on A3. That is a live defect
  report, so it is published, not held (CLAUDE.md, disclosure rule).

### Phase W3-W4: v11-b (conditional)

Runs only if D-v11a is PASS, or INCONCLUSIVE with the format KPIs met (§5.5).

**V11-17 Pod session 3: v11-b data.** Expected $40, **cap $45**. Wed 14 - Thu 15 Oct, unattended, before the Italy window.
- A second Pallets pass, on tasks with fewer than 2 successes.
- A **privileged self-teacher** on tasks that no round-1 attempt solved:
  - same model, fixer and verifier with thinking on, 2× time cap, 2 samples;
  - thoughts are stripped at build time;
  - the L4 filter is applied to the non-thinking tokens.
- Rule basis: "Training on gemma-4-31b itself is fine" (743964). The teacher is the same checkpoint.
- Gate: ≥ 80 new L4-feasible trajectories, ≥ 30 of them on tasks that had none.
- On failure: v11-b trains on the round-1 data with per-stage adapters only, or is dropped.

**V11-18 Pod session 4: v11-b train and screen.** Expected $40, **cap $45**. Wed 21 - Thu 22 Oct.
- If each stage has ≥ 300 supervised segments: `v11_loc` for the locator and `v11_fix` for fixer and verifier. Otherwise
  one shared adapter on the larger data.
- Screen 2 stage maps (all three stages; fixer and verifier only) against v11-a on the pod.
- Gates: as V11-13, plus: at least one map ≥ v11-a − 2 resolved with better format KPIs.

**V11-19 Faithful evaluation of v11-b in E3.** $0; window Fri 23 Oct 17:30 to Mon 26 Oct 05:31. Pushes pre-approved in A3.
- Control is the current best (v11-a if it passed, else v10). Protocol §5.
- Decision D-v11b on Mon 26 Oct.

### Phase W4-W6: paper

**V11-20 Paper resource: "Gemma-4-31B agent trajectories under the official harness".** $0; about 3 agent days spread
over 25 Oct - 11 Nov.
- Carson joins the paper track (not yet joined as of 09-25) and saves a writeup draft by **Sun 25 Oct**, because of the
  save-404 bug in 743094. Check then whether a submitted writeup is public before the deadline (UNVERIFIED).
- Dataset contents are listed in §8. HF dataset stays private until release.
- Card, license table, and a reproduction notebook (render and verify on 20 sample trajectories on CPU).
- Submissions: first on **Fri 6 Nov**, final on **Wed 11 Nov** (Kaggle deadline Fri 13 Nov 05:29 IST).
- Gate: the verification notebook reproduces the exact-increment statistic on the released population, and every file
  carries a license row.

### Phase W7-W9: final

**V11-21 Finals.** Freeze Sat 28 Nov.
- E4 (skip the Sat 21 and Sun 22 Nov slots) runs one paired re-check of the two finalists under §5.
- Finals by Wed 2 Dec 23:59 UTC: the best v10-family bundle, plus the best v11 bundle if one passed; otherwise the two
  best v10-family bundles.
- Reproducibility package (Apache-2.0): `train/` with seeds, pins and data manifests with hashes; the adapter export;
  bundle build scripts; the exact commands from this plan.

---

## 5. Evaluation protocol (pre-registered; copied verbatim into `docs/v11/checklist.md` by V11-08)

### 5.1 Arms
- **CTL** = `submissions/v10` at the frozen hash H10, or the temperature arm race 2 shipped. No `adapters/`, so its kernel
  runs **without** LoRA mode, exactly as v10 would on the scorer.
- **TRT** = `submissions/v11a` = CTL + `adapter: v11_a` on locator, fixer and verifier + `adapters/v11_a/`.
  `tests/test_v11_bundle.py` enforces that this is the whole diff.

### 5.2 Tasks, hardware, recipe
- Tasks: the 74 ids of `data/kaggle_valid_ids.txt` (31 fastapi, 42 rich, 1 requests), in the same order in both arms. No
  v11 training sample comes from these tasks or their repos (the V11-02 leak guard).
- One Kaggle 4×L4 kernel per arm per round, built by `scripts/make_eval_kernel.py <bundle> <slug> --ids data/kaggle_valid_ids.txt --from-bundle-config [--bundle-dataset ...]`.
- The host notebook's recipe: wheelhouse at run time; vLLM TP4, gmu 0.90, max_len 32768, gemma4 parsers;
  `EventsCompactionConfig(15, 2, 14336, 5)`; `ContextCacheConfig(2048, 1800, 10)`; subprocess sandbox.
- Per-task budgets come from the bundle's `eval_config.yaml`.
- Both kernels of a round are pushed within 10 minutes of each other, in an E-block (no submission scoring).

### 5.3 Validity checks (a round that fails one is rerun, not analysed)
- Both kernels finished all 74 rows.
- The vLLM `gemma4.py` CRC and `pip_freeze.txt` are identical across the two kernels, so they ran on the same wheelhouse.
- TRT: the vLLM command contains `--enable-lora`; `/metrics` shows `v11_a` served; every task has ≥ 1 request to `v11_a`.
- CTL: no `--enable-lora`.

### 5.4 Endpoints and the ship rule

With d_k = resolved(TRT) − resolved(CTL) in round k, D = d_1 + d_2 over the 148 paired task-runs.

| # | gate | pass condition |
|---|---|---|
| 1 | resolved, pooled | **D ≥ +4** |
| 2 | resolved, per round | every d_k ≥ −2 |
| 3 | crashes | 0 in every crash class of race 2 row 3, over both TRT runs |
| 4 | time | mean s/task of TRT ≤ 1.05 × CTL; projected 130-task worst case (measured startup + 130 × (cap + 9.6 s)) ≤ 11.5 h |
| 5 | format | TRT malformed calls per task ≤ 0.7 × CTL **or** exact-repeat share ≤ 0.7 × CTL |
| 6 | empty patches | TRT ≤ CTL + 2 per round |

- Reported without a threshold: exact sign test on discordant task-runs, per round and pooled; a bootstrap 95% CI over
  tasks for D/148; results per repo (fastapi, rich); completion tokens per call; cap hits; compaction events per task;
  VERIFY verdict share; the summariser check.
- Power, stated before the run: between-round SD of d is about 3 tasks (GraphLoc repeat runs, scaled), so SD(D) is about
  4.2.
  - A true +3 per round gives P(pass #1) ≈ 0.68.
  - A true 0 gives P(false pass) ≈ 0.17.

  This is accepted because a false ship is bounded: v10-family stays one of the two finals.
- Probability the measurement lands: about 0.7 that both rounds finish inside E2, given 4-9 h queues. If they do not,
  E2 grows by one more skipped slot. It is not analysed on one round unless the §5.5 stop rule fires.

### 5.5 Stop and decide
- **Stop after R1** (no R2) if d_1 ≤ −4, a crash class is > 0, or the time gate fails.
- **PASS:** all six gates hold. v11-a goes to the LB once (V11-16) and becomes a finals candidate.
- **INCONCLUSIVE+:** 0 ≤ D < 4 with gates 3-6 met. No ship; v11-b is allowed.
- **FAIL:** D < 0, or any of gates 3-6 fails. v11-a is killed, and v11-b is allowed only under K7's exception.

---

## 6. How v10's pipeline and v11's adapter interact

### 6.1 Stage map

| v10 stage | T, max out | v11-a | v11-b (only if ≥ 300 segments per stage) | why |
|---|---|---|---|---|
| setup | 0.2, 256 | base | base | one install call; v10 already made it a dedicated stage (race 2 KPI 4 measures it) |
| locator | 1.0, 1,536 | `v11_a` | `v11_loc` | most calls (median 11 per segment) and most exact repeats |
| fixer | 1.0, 2,048 | `v11_a` | `v11_fix` | edit format; right file, wrong fix |
| verifier | 1.0, 2,048 | `v11_a` | `v11_fix` | runs `verify.py`, repairs, submits |
| submitter | 0.2, 1,024 | base | base | a single guarded call |
| compaction summariser | stage's model | inherits `v11_a` in adapted stages (FI §1.4 EXP) | inherits | summaries are written by the adapter, so captured summariser calls (base outputs) are ≤ 5% of the training mix, and V11-13 checks them |

Why one shared adapter first: about 120-150 trajectories split three ways leaves too little per stage, and each adapter
multiplies the parity tests. The stage identity is in each system prompt, so one adapter can still learn stage-specific
behaviour.

### 6.2 Coupling rules
- **Prompt freeze.** SFT samples are rendered from the exact bundle bytes at H10: system instruction, identity line,
  skill boilerplate, tool declarations and their order (FI §2.2). `tests/test_v11_bundle.py` checks that the bundle
  pinned in `train/data/v11a/manifest.jsonl` equals CTL.
- **Global LoRA mode.** Any adapter puts every stage, setup and submitter included, through LoRA mode (FI §1.4). The tax
  is measured by K1, and gate #4 carries it.
- **Adapter names:** `v11_a`, `v11_loc`, `v11_fix`. Never `gemma4`, `o<digit>...` or `gpt-5...` (FI §1.5).
- **Helpers stay stdlib and unchanged.** The adapter learns their CLI (`edit.py` SEARCH/REPLACE, `view`, `verify`,
  `finalize`, `status`). v10's claim gate, checkpoints, test-file revert and output caps stay the safety net, so the
  adapter cannot bypass them.
- **Sampling.** v10's per-stage temperatures and `max_output_tokens` are kept. Data is sampled at the same values.
- **Budget.** `eval_config.yaml` is unchanged (5 min / 100 calls / 200 turns / 120 or 180 s). Only the startup delta is
  added.

### 6.3 When v10 changes after data generation
- **Prompt text only** (no helper CLI or output change): re-render the captured trajectories under the new prompts
  (free). The actions become slightly off-policy; this is acceptable for a small edit.
- **Helper CLI, helper output or tool list:** regenerate data (a new pod session). Old captures go to the paper dataset
  only.
- **eval_config only:** nothing, since stage-2+ prompts do not contain budgets. The setup prompt does, and setup is not
  trained.

---

## 7. Kill criteria

| id | trigger | action |
|---|---|---|
| K1 | G0 step 1: top-1 differs on < 18/20, or any `self_decoder` reset line, on the v25 wheel | stop all LoRA spend; post the repro to 743508 (Carson's go); re-run G0 only if the host ships a new wheel (check the wheelhouse CRCs weekly) |
| K2 | K1 on 4×L4: TP4 does not change outputs, or the decode tax is > 25%, or startup is > +600 s | LoRA is dead for the main track (on cap-bound hidden tasks the tax turns directly into fewer tool calls per task) |
| K3 | Z submission errors or scores ≤ 0.03 | stop LoRA until the cause is found; report on the forum |
| K4 | G0 determinism fails at r16 as well as higher ranks | stop (the evaluation cannot be trusted); try r8 once |
| K5 | < 120 L4-feasible trajectories over < 60 tasks after round 1 | one extra data pass (≤ $30) in the same session if G0 passed; still short → no training; the data goes to the paper only |
| K6 | V11-13: screen B < A − 3 resolved, or validation NLL not down ≥ 3%, after the one allowed retry | kill v11-a |
| K7 | §5.5 FAIL (D < 0, or gates 3-6) | kill v11-a; v11-b only if the format KPIs improved ≥ 30% and D ≥ −2, i.e. the adapter helps format but costs solves |
| K8 | **Sun 8 Nov:** no v11 variant has passed §5.4 | stop LoRA for the main track; remaining effort goes to the v10 family and the paper |
| K9 | cumulative v11 pod spend reaches $160 without a v11-a PASS or INCONCLUSIVE+, or $250 at any point | stop v11 spending |
| K10 | race 2 or v10's L4 gate shows format loss is already spent (v10 malformed `edit_file` ≤ 0.3 per task **and** exact repeats ≤ 15% **and** ≤ 1 task per 74 lost to cap spirals) | cancel V11-13 onward; v11's plausible lever is gone. Data and paper steps continue |

---

## 8. What the paper track gets from v11

**Entry:** Best New Resource ($10k), "Gemma-4-31B agent trajectories under the official harness, with byte-exact
reconstruction".

**Contents:**
1. **Pallets-X trajectories.**
   - Every v10/v11 task-run from sessions 1 and 3: successes **and** failures.
   - Exact request bodies rendered with the scorer's June template; raw completions; compaction summaries (captured, which
     old traces lack).
   - Per-call prompt and completion tokens and timings; resolved labels; malformed-call and repeat labels; predicted L4
     time.
   - Licences: Pallets-X CC0; code BSD-3 (click, flask, jinja2, markupsafe, werkzeug, itsdangerous, sympy) and MIT
     (pytest).
2. **Public-task trajectories** (1,367 model-run traces), **only if 743255 Q4 allows** redistribution of data derived from
   the competition. Otherwise only statistics are published.
3. **Tools:** `train/scorer_render.py` with the exactness test (2,391/2,391 on e74_v3, recomputed over the full released
   population); `train/build_sft.py`; `train/export_adapter.py` with the k_eq_v fix; `pod/lora_gate.py`.
4. **Findings**, each with its command:
   - the k_eq_v V-slot mismatch;
   - whether the host's LoRA fix works, at TP1, TP2 and TP4;
   - the LoRA-mode tax on 4×L4;
   - the pre-registered self-RFT result on unseen repos (positive or negative, with its CI);
   - dataset statistics.

**Rigor, for "more than the others":** the full population, not a sample; the control arm in every comparison; the
negative result kept if RFT gives nothing; thresholds registered before the runs. SWE-Pallets-X is itself a rival resource
entry: ours builds on it, credits it, and adds what it lacks (model trajectories, exact prompts, a verified serving path).

**Disclosure timing** (CLAUDE.md):
- **Now or at verification:** bug reports (k_eq_v, LoRA-fix status, LoRA-mode tax) go to 743508. They are live defects
  and are never withheld.
- **Nov 6 / Nov 11:** the dataset, the tools and the findings, as the paper needs them for Verifiability.
- **Held until Thu 3 Dec:** the v11 adapter weights, the bundle, and the exact training hyperparameters and data mix. The
  paper describes the method but does not ship the trained adapter. Rivals get 20 days with the dataset; none has a
  working adapter pipeline today (FE §5).

**This part does not depend on LoRA surviving.** If K1-K3 fire, the paper still gets the dataset, the tools and a
documented negative LoRA result.

---

## 9. Budget

| line | expected | cap | when |
|---|---|---|---|
| billed through 09-28 | $96.09 | | done |
| race 2 (v10 plan, Carson's call) | ~$35 | | W0 |
| V11-09 session 1 (G0 + data) | $71 | $85 | Sun 4 - Mon 5 Oct |
| V11-13 session 2 (train + screen) | $60 | $75 | Wed 7 - Thu 8 Oct |
| **v11-a subtotal** | **$131** | **$160** | |
| V11-17 session 3 (v11-b data, conditional) | $40 | $45 | Wed 14 - Thu 15 Oct |
| V11-18 session 4 (v11-b train + screen, conditional) | $40 | $45 | Wed 21 - Thu 22 Oct |
| **v11 total** | **$211** | **$250** | |
| reserve for v10.x races and finals | ~$119 | | |
| Kaggle quota | K1 about 2 GPU-h; E2 about 15; E3 about 15; E4 about 15 | ≤ 20 GPU-h per quota week | |

Every pod session runs under `pod/supervisor.sh` with MAX_HOURS set to its cap divided by $6.98, and makes a verified
backup before it stops. Weights and checkpoints are named, with their sizes, in the ledger row before any teardown.

---

## 10. Risks

| risk | evidence | mitigation in this plan |
|---|---|---|
| the host's LoRA fix does not work, or only at TP1 | nobody has re-tested (FE §1.1); TP4 shards LoRA differently | G0 at TP1 and TP2; K1 at TP4 against the TP1 reference |
| silent V-slot mismatch on 10 layers | FE §0.2 | `--kv-mode dup` plus a per-family parity test |
| rank non-determinism on int4 bases | vLLM #50059 | r16 start; determinism check |
| the LoRA-mode tax eats the 5-min budget on cap-bound hidden tasks | 663 s against 383 s startup in different runs; decode tax unknown | K1 measures it; gate #4 |
| self-RFT gives about 0 at 32B | SWE-Gym 19.0 → 19.7; 15.3 → 8.7 | framed as a format lever; K6, K7, K10; v11-b self-teacher only if earned |
| too little Pallets data (unknown solve rate) | Qwen2.5-7B 4/181 on its subset | adaptive sampling; K5; SWE-rebench venv fallback |
| contamination of the 74-task eval | 39 of the 43 old resolved tasks are in the 74 | leak guard with a planted-id test |
| eval windows lost to queues or quota | 4-9 h queues; queue time may be charged | 60 h E-blocks; quota read in V11-00; R1 and R2 across quota weeks |
| v10 not frozen, or it fails race 2 | race 2 has not run | no waiting past Wed 7 Oct; re-render rule (§6.3) |
| adapter summaries break compaction | FI §1.4 | summariser samples in the training mix; the V11-13 check |
| train/serve numerics mismatch | int4 is RTN at amax/7.5, 6.7% from QAT bf16 (FE §2.1) | train on dequant(w4a16); parity of the trained adapter |
| 12 h cap at 130 tasks with the LoRA startup | v10 worst case 11.3 h at 130 | gate #4 at ≤ 11.5 h with measured startup |
| Carson's attention in Oct-Nov | §1.1 | 6 batched approvals; unattended, self-stopping chains |
| a 245 MB adapter cannot be base64-embedded in a notebook | `scripts/make_kernel.py` embeds every file | private dataset transport with a sha assertion (V11-07, V11-14) |
| rivals use the released dataset for Dec 2 | paper deadline 20 days before main | weights and recipe held until Dec 3 (§8) |

---

## 11. Update triggers (this plan is maintained until v10 is done, and as news arrives)

| trigger | where it arrives | change |
|---|---|---|
| race 2 report (`docs/v10/race2_report.md`) | pod race 2 | set T_freeze and H10; apply K10; if race 2 ships t06, CTL and the data use T 0.6 |
| v10's faithful L4 gate result | Kaggle | if v10 fails and v4 or v9_eog stays shipped, CTL stays v10 (the adapter effect) and a B* arm joins R2 (quota permitting) |
| any v10 prompt, helper or tool-list change | commits under `submissions/v10` | §6.3 rule; re-pin H10 |
| LoRA re-test posted by anyone (743508, 743964), or a new wheelhouse version | forum; wheelhouse CRCs | G0 can shrink to parity and determinism only; if the CRCs change, re-run G0 |
| ruling on other models' outputs (742807) | forum | if allowed: teacher data (nebius set re-rendered to v10 format) becomes v11-b's main lever, and the expected gain goes up (SWE-smith scale); if denied: no change |
| 743255 Q4 (redistribution) | paper forum | release scope of §8 item 2 |
| 743752 (scorer compaction interval, 5 or 15) | forum | kernel recipe in §5.2; data-generation compaction setting |
| Kaggle quota and reset day | V11-00 | E-block placement |
| RunPod 4×L4 back in stock | get-capacity | option: a validated L4-pod eval lane (one agreement run against Kaggle first) |
| a new LB leader, or a public adapter score | LB, notebooks | re-rank §3.1 |

---

## 12. Expected gain (stated before any run)

- **P(G0, K1 and Z all pass)** ≈ 0.6. The fix is in the code; TP4 and the tax are unknowns.
- **P(v11-a passes §5.4 | gates pass)** ≈ 0.35. This follows from the power figure and a modest true effect.
- **Effect if shipped:** about +1 hidden task of 58 (+0.015 LB), 80% range −1 to +4. The mechanism is format and
  efficiency on cap-bound hidden tasks, not new capability. **Unconditional:** about +0.01.
- **v11-b self-teacher:** conditional +0-2 tasks more. The only path to a larger step is teacher data, if the host allows
  other models' outputs (§11).
- **Paper:** the resource is produced whatever LoRA does. P(Best New Resource) is a rough guess of 0.1-0.2, which is
  $1-2k expected against about $211 of spend.
- **Not claimed:** v11 does not take the entry from 0.12 to 0.30.

---

## 13. Changelog

- 2026-09-28 17:40 IST: first version (Planner C). T_freeze assumed Sat 3 Oct. Kaggle quota and reset day not yet read.
  RunPod 4×L4 out of stock at 12:10 UTC. No pod running for this project (list-pods: 2wyl66nmji13p1 EXITED).
