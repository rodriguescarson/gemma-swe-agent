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

## T2b START 2026-10-20T05:43:06Z
- fetching the four missing inputs listed in QUEUE.md (s6_extras.bin, heliosli notebook SOURCES, folds_v0.json, timm init); gate = pinned sha256

## T2b DONE 2026-10-20T05:44:45Z
- s6_extras.bin = an 11-byte header "K1PAYLOAD1\n" followed by a plain ustar tar (21 members, no absolute or .. paths): 15 MONAI 0.6.0 files under cloud_code/training/vendor_runtime/monai060/ and ALL SIX heliosli sources (heliosli/*.py). Extracted to ~/rsna/src/s6_extras with python tarfile.
- the six sources: sha256sum -c s6/heliosli.SHA256SUMS: 6/6 OK (compact_train 14767c7a, compact_infer 34f433fe, px_cache b13e38a7, probe_infer a6cc3144, knee_anchor_bank_v2 e564807a, side_common bbcc5d02). The notebook pull (QUEUE item 2) was therefore not needed and not done.
- cloud_code: heliosli dataset cloud_code + the extras' monai060 files: sha256sum -c s6/cloud_code.SHA256SUMS: 272/272 OK
- folds_v0.json (nartaa/rsna-knee-hpo-assets, Kaggle CLI -f): sha256 12bebc897a549d660cf5e6ab597c9a8d8f84dc887b4abd4c99b67fb4a25cb3ae = the inputs.sha256 pin; ~/rsna/inputs/folds_v0.json
- timm convnext_small.fb_in22k_ft_in1k model.safetensors (huggingface.co resolve/main, 200,928,946 B): sha256 2457488bec2ffcb2061b9e3fdd63360114549615e3e35ef6dc5c5efe549cbbc9 = the init_sha256 pin; ~/rsna/inputs/model.safetensors
- eval path for gold-58 (QUEUE item 5): compact_infer.py (pinned) is present, so T6/T7 will use it; oof_step.py stays unshipped
- working copy ~/rsna/s6 = training_code/s6 + heliosli/ (six sources) + heliosli/cloud_code (272 verified files); path changes are made at T5 and listed then
- GATE PASS: every pinned file present with matching sha256

## T2 DONE 2026-10-20T05:44:48Z
- T2's missing inputs supplied by T2b (all pins match); T2 complete

## T3 START 2026-10-20T05:44:58Z
- competition data: listing files to choose per-file download vs remote-zip extraction (no zip + extracted copy at once)

## T3 NOTE 2026-10-20T05:50:43Z
- method: no zip is stored. Kaggle API download-all -> signed storage URL (HTTP range OK); remotezip reads the central directory (819,640 members, 265 GB compressed, 569.8 GB uncompressed); ~/rsna/tools/extract_pool.py fetches each pool study as ONE byte range and inflates its members locally (size + CRC32 checked per file, atomic rename), 16 threads, resumable, stops below 110 GB free
- scope: train.csv, train_series.csv + train_series of the 4,321 pool studies (785,068 files, 528.5 GB uncompressed, 249.7 GB compressed); all 4,321 are in the zip; test_series and the 86 non-pool studies are not fetched
- detached (nohup), pid 32230, log ~/rsna/logs/T3_extract.log; START studies 4321 files 785068 uncompressed GB 528.5 free GB 787.4 workers 16
- after about 10 min: 225/4321 studies, 28.3 GB of 528.5 GB written, 123.1 MB/s (uncompressed); projected finish 2026-10-20T06:58Z; disk free 707G
- mechanical additions: ~/rsna/venv (python3 venv: remotezip, requests, pandas, scikit-learn, pyarrow); ~/rsna/tools/extract_pool.py

## T4 DONE 2026-10-20T05:50:46Z
- control = s6/data/targets_s6f0.csv exactly (copied to ~/rsna/labels/targets_control.csv); treatment = ~/rsna/labels/targets_treatment.csv, same header, rows and order (4,407 = 4,349 non-gold + 58 gold)
- fused soft label = soft_labels.csv of the evidence-fusion dataset (the card's fusion output; 4,407 rows, 11 findings, Synovitis absent)
- [0,1] check before mixing: control non-gold prior 0.0036..0.9996, fused 0.0005..0.9746, no NaN: PASS. Treatment 0.0049..0.9917
- treatment = 0.5 x control + 0.5 x fused for the 11 fused findings on all 4,349 non-gold rows (47,839 cells); Synovitis = control; studies missing from the fused table: 0. Mean |treatment-control| per finding 0.033 (Fracture) .. 0.096 (Effusion)
- gold-58: kept as is_gold=1 rows with every label blank in BOTH tables (the trainer needs these rows: --all-data asserts pool == pool_ok minus gold); gold rows carrying any label: 0 in each table. No gold label enters training
- scoring on gold-58 as written is not possible: both tables are blank on the gold studies by construction, so neither has a value to score. What exists: the fused source's own outer-held gold rows score macro AUC 0.9287 over 11 findings (= its card's 0.9287); per finding ACL .968 MCL .993 MedMen .987 LatMen .878 MedOA .961 LatOA .824 PFOA .931 Effusion .927 Baker .953 Contusion .904 Fracture .890. The control source (blendjev) has no gold rows at all
- full output: rsna/logs/T4.log

## T3 DONE 2026-10-20T06:59:14Z
- "2026-10-20T06:58:50Z DONE studies 4321 written GB 528.5 in 4321 s" (mean 122.3 MB/s uncompressed); exit 0
- ~/rsna/data: train.csv, train_series.csv, train_series/ with 4,321 study dirs and 785068 .dcm files (expected 785,068), every file size- and CRC32-checked against the zip directory; 0 partial files; du 495G
- no zip was stored at any point; disk free after: 227G
- mechanical fix while waiting: pip had pulled torch 2.14.1+cu130 with timm's torchvision (CUDA unavailable on driver 572.61 / CUDA 12.8); reinstalled torch 2.8.0+cu128 + torchvision 0.23.0+cu128 (= the trainer's recorded torch 2.8.0+cu128); torch.cuda.is_available() True on the RTX A6000; pip check clean
