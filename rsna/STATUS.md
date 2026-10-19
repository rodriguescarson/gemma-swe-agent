# rsna-knee STATUS (append-only)

## SETUP DONE 2026-10-19T19:44:52Z
- orphan branch rsna-knee in ~/rsna-channel; holds rsna/ only; work dir ~/rsna
- rsna/RUNBOOK.md = the task message plus the owner amendment (T1 gate 650 GB; no zip + extracted copy at once; read scripts before running)

## T1 DONE 2026-10-19T19:44:52Z
- GPU: NVIDIA RTX A6000, 49140 MiB, 3683 MiB, 572.61 (CUDA Version: 12.8); free VRAM is low because the Gemma run's vLLM holds the card until about 03:00Z
- disk free: 726G on / (gate >= 650 GB per owner amendment): PASS
- RAM: 94 GB total, 87 GB available
- Kaggle CLI: ~/g4/venv/bin/kaggle, KAGGLE_USERNAME exported; API call (datasets list): ok

## T2 START 2026-10-19T19:45:17Z
- downloading 3 Kaggle datasets into ~/rsna/src with the Kaggle CLI (--unzip)

## T2 FAIL 2026-10-19T21:00:48Z
- downloaded (Kaggle CLI, --unzip, ~/rsna/src): weights 195 MB/33 files 17 s; orthofoundation 1.4 GB/837 files 89 s; evidence-fusion 29 MB/27 files 5 s; disk free 725 GB
- training_code/SHA256SUMS: sha256sum -c 25/25 OK; every listed s6 file present; rsna/notes/PIPELINE.md written
- GATE FAILED (files missing): the six sources every s6 script imports and checks by sha256 at start-up are in none of the three datasets: px_cache.py, compact_train.py, compact_infer.py, probe_infer.py, knee_anchor_bank_v2.py, side_common.py (pinned in s6/heliosli.SHA256SUMS; they are the public 0.954 notebook's sources). The orthofoundation dataset has only cloud_code/training, anatomy.pt, weight parts and dependencies.
- also missing for training: folds_v0.json (--folds-json, from the hpo-assets dataset, sha256 12bebc89...) and the timm convnext_small.fb_in22k_ft_in1k init weights (HF hub); oof_step.py (their gold-58 step) is not shipped
- network scan: s6 scripts make no network calls; cloud_code has download/network modules that the s6 path does not import (details in notes/PIPELINE.md)
- stopped here per the runbook; need: where to get the six pinned sources (their notebook ref) and permission to fetch folds_v0.json and the timm init
