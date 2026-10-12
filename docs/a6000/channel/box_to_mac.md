# box_to_mac.md (append-only; written by the A6000 box through scripts/a6000/channel.sh; see README.md)

### B-001 | 2026-10-12T12:01:45Z | re: M-001
Box, 2026-10-12T12:02Z, head 1c0ad458 (pulled: includes "base NLL lower bound" and probe_reverdict). Channel read OK.
Status: the probe (pid 175, started 08:22:03Z, up 3 h 40 min) has finished all 20 single-sequence steps (13-16k bucket: tok_s 83, 6, 6, 6, 6; peaks 46.53 / 47.8 GB) and is in the 24-step repeated-loss phase, which logs nothing per step; I expect probe_report.json at about 12:45Z. tests/test_probe_reverdict.py: 4 passed. forward2k seen in the log: tokens 2635, supervised 64, max_abs_logit 29.73, base_nll 0.1949.
Doing meanwhile: waiting on the probe exit; then reverdict --write, GATE addendum 15 + P2_LOG, and on REDUCED/FULL the step-6 sequence as in M-001. Next message at the re-verdict.

### B-002 | 2026-10-12T12:06:15Z | re: M-001
Box, 2026-10-12T12:07Z. QUESTION (the rules are silent): the probe's repeated-loss phase is also thrashing.
Evidence (train_log.jsonl): probe_repeat step 0 at 11:56:10Z: loss 0.2378, grad_norm 0.533, tokens 24042, seconds 1561.1 (= 15 tok/s; the 5-9k bucket ran 130 tok/s, 9-13k ran 100-104). GPU 48487 MiB, 100 % util, ~135 W; the 13-16k steps left the allocator at peak_reserved 47.8 GB and it has stayed at the 48 GB cap since. At ~26 min per step the 24 steps would end around 22:30Z (10 more hours) before probe_report.json exists.
Hypothesis (unverified): the cache left by the 13-16k bucket keeps every later step in the spill zone; a fresh process that skips or caps that bucket (head 564c0925 "a bucket that thrashes is unusable ... excluded") would run the repeat phase at ~130 tok/s, ~25 min.
Options: (1) keep waiting for this process (no action from me). (2) kill pid 175 now and rerun `train.sh probe think1` on the current head (the 20 steps stay in train_log.jsonl; I rename it, nothing is lost); the new run should end in ~1-1.5 h. I recommend (2) but will not kill without your word.
Meanwhile: I keep the probe running and run `channel.sh wait`.

### B-003 | 2026-10-12T13:40:04Z | re: M-002
Box, 2026-10-12T13:39:58Z, head f9a3d40d. PROBE RESULT (capped rerun, started 12:09:58Z, ended 13:39:23Z; probe_report.json + probe_reverdict.json written).
VERDICT (new code) = REDUCED; probe_reverdict.py gives the same: REDUCED, old_verdict REDUCED, tok_s 115.5, excluded_buckets [], thrash_at_16k false, peak_gb_at_12k 40.58, oom_at_16k false, cap_tokens 12288, loss_first 0.2262, loss_last 0.0939, max_grad 46.338.
reasons: "116 tok/s in [100, 150): cap 12,288 and <= 6 segments per task-stage"; "base NLL 0.069 < 0.3 on 64 supervised tokens: the model is confident on its own samples (informational)".
Buckets (peak_reserved_gb / tok_s of the 5 steps): 0-5k 28.55 / 180,178,177,176,180; 5-9k 34.67 / 130,130,131,130,133; 9-13k 40.58 / 104 x5; top bucket (capped at 12288) 40.58 / 104 x5. No OOM, no thrash.
forward2k: tokens 2210, supervised 64, max_abs_logit 29.721, base_nll 0.0694 (alloc 17.67, peak 21.26 GB). load: 91.7 s, alloc 17.06 GB, reserved 21.02 GB; lora_modules 400, trainable_params 121241600; export tensors 800, all bfloat16.
repeat_losses (24): first two: step 0 loss 0.2373 148.3s, step 1 loss 0.215 144.9s | last two: step 22 loss 0.1058 148.3s, step 23 loss 0.0819 144.9s. Full series: 0.2373 0.215 0.2366 0.2133 0.2302 0.2065 0.2235 0.1962 0.2172 0.1851 0.208 0.1766 0.2004 0.1682 0.1882 0.1566 0.1728 0.1416 0.1529 0.1233 0.1303 0.1024 0.1058 0.0819 (first-2 mean 0.2262 -> last-2 mean 0.0939 = -58 %, gate >= 30 %: pass). max grad_norm 46.338 (step 10), under 100; no NaN.
heldout_eval: nll_text 0.4671542835235596, nll_tool 0.20342205271338373, nll_all 0.23129704077629043, n_text 800, n_tool 6769.
The thrashing first probe (20 single-sequence steps at 16k; 13-16k bucket tok_s 83, 6, 6, 6, 6, peak 46.53 -> 47.8 GB; repeat step 0 1561.1 s) is kept as train_log_thrash_16k.jsonl / train_thrash_16k.out. Both probes are in GATE addendum 15 and P2_LOG.
Next (per M-001/M-002): re-stitch with --max-seqs-per-task-stage 6, then train.sh full think1 --max-tokens 12288; reply B-004 with the stitch gate.

### B-004 | 2026-10-12T13:40:49Z | re: M-002
Box, re: M-002. RE-STITCH (step 6, REDUCED path) `train.sh stitch ~/g4/runs/p3_think think1 --max-seqs-per-task-stage 6`: exit 0, validate_stitched.json ok true, sequences_with_thought 156 == sequences 156, problems 0, dropped_no_thought 3 (arrow_f77aa1d, cattrs_b55fbe0, isort_61071d7) = 1.9 % of 159 (bound 5 %), >= 40 sequences: pass. Numbers identical to the first stitch because no task-stage had more than 6 sequences (capped_per_task_stage 0): sequences 156, tasks 149, tokens 1323176, breaks 10, healed 42, compactions 0, over_max_tokens 53 (stitched at 14336), thought_share 0.9537 (validator 0.9539, model_spans 1454, thought_spans 1387), span_thought 1422, span_thought_masked 454, span_tool 1330, span_text 161, span_error 160, span_repeat 122, span_read_over_share 182; holdout 5 tasks (arrow_cc1cbeb attrs_e048efc black_650983f boltons_ec1ff9f more_itertools_40cee34), holdout.jsonl 5 sequences. tokens_p50/p90/max 7976 / 13452 / 14244.
Launching now: `train.sh full think1 --max-tokens 12288` (session held open). Next message: the run's start event, first eval line and `train.sh status think1`; then hourly.
