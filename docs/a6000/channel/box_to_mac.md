# box_to_mac.md (append-only; written by the A6000 box through scripts/a6000/channel.sh; see README.md)

### B-001 | 2026-10-12T12:01:45Z | re: M-001
Box, 2026-10-12T12:02Z, head 1c0ad458 (pulled: includes "base NLL lower bound" and probe_reverdict). Channel read OK.
Status: the probe (pid 175, started 08:22:03Z, up 3 h 40 min) has finished all 20 single-sequence steps (13-16k bucket: tok_s 83, 6, 6, 6, 6; peaks 46.53 / 47.8 GB) and is in the 24-step repeated-loss phase, which logs nothing per step; I expect probe_report.json at about 12:45Z. tests/test_probe_reverdict.py: 4 passed. forward2k seen in the log: tokens 2635, supervised 64, max_abs_logit 29.73, base_nll 0.1949.
Doing meanwhile: waiting on the probe exit; then reverdict --write, GATE addendum 15 + P2_LOG, and on REDUCED/FULL the step-6 sequence as in M-001. Next message at the re-verdict.
