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
