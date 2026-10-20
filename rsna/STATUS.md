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

## T5 START 2026-10-20T06:59:55Z
- GPU free (Gemma queue finished; no vLLM / autopilot running)
- working copy ~/rsna/s6; mechanical path patches (diff in ~/rsna/s6/LOCAL_PATCHES.diff): s6common.ANATOMY -> the orthofoundation dataset's anatomy.pt (sha256 5904dd16..., = ANATOMY_SHA256), s6common.DATA -> ~/rsna/data, train_s6f0_all.py's S6F0 import dir -> ~/rsna/s6. data/precompute_order.json (not shipped) = pool_ok.json's 4,321 studies (4,263 train + 58 gold), same order
- before running (owner amendment): precompute_anchors.py / s6common / fly_data / the six sources make no network calls; their writes go to --out (~/rsna/s6/anchors) and --tmp (set to ~/rsna/work/anchors_tmp, not /tmp); the cloud_code network modules are not imported (s6common stubs training.download_data)
- smoke first: 4 studies into ~/rsna/s6/anchors_smoke, then the full run detached

## T5 NOTE 2026-10-20T07:03:55Z
- first smoke (4 studies) ran with 0 "errors" but EVERY anchor fell back to slab_prior: each series failed with "cuDNN error: CUDNN_STATUS_NOT_INITIALIZED". Cause: the earlier accidental torch 2.14/cu130 install had left CUDA 13 libraries (nvidia-cudnn-cu13 9.24 shadowed cudnn 9.10). That run's output was discarded
- mechanical fixes: removed the CUDA 13 nvidia packages, force-reinstalled torch 2.8.0+cu128 / torchvision 0.23.0+cu128 (cudnn 9.10.02 now), pinned numpy 2.3.5 (<2.4); GPU conv2d/conv3d tests pass; pip check clean
- second smoke (8 studies): 0 errors; methods skm_tea_joint 5, skm_tea_joint_avg3 1, slab_prior 2 (data reasons: "mass<250", "far_from_prior", "implausible"), 0.54 studies/s at 2 workers, GPU peak 1.9 GB
- full precompute launched detached: 4,321 studies (pool_ok.json), 8 workers, out ~/rsna/s6/anchors, tmp ~/rsna/work/anchors_tmp, log ~/rsna/logs/T5_anchors.log

## T5 DONE 2026-10-20T07:40:06Z
- anchors (no pixel cache exists in this pipeline: studies are rendered from DICOM at load time, so "cache" = the anchor precompute + the frozen pool): precompute_anchors.py, 8 workers, 07:03:54Z -> 07:39:28Z (35.6 min, 2.03 studies/s, GPU peak 10.6 GB)
- studies 4,321 (4,263 train + 58 gold): ok 4,321, errors 0, missing 0. Methods: skm_tea_joint 3,024, skm_tea_joint_avg2 595, skm_tea_joint_avg3 82, skm_tea_joint_avg4 2, slab_prior 618 (the bank's own fallback, per-study reasons recorded). rows mean 592.9, stride-1 eval windows 2,529,749, train candidates min 248 (none < 64)
- freeze_pool.py --final: "pool already frozen and identical" to the shipped data/pool_ok.json (4,321); failed_by_group train 0 / fold0 0 / gold 0
- size: ~/rsna/s6/anchors 19 MB (4,321 anchor JSONs + manifest.jsonl + summary.json)
- GATE PASS: failures 0 of 4,321 (0.0% <= 0.5%)
- log: rsna/logs/T5.log

## T6 START 2026-10-20T07:40:25Z
- forward only, their eval path: heliosli compact_infer.py (pinned 34f433fe) with run_config's settings: convnext_small, size 320, crop 288, views v4, slices 3, phys-mm 3.5, eval-stride 3, anchor-weights = anatomy.pt (it recomputes each study's anchor inline from DICOM, by the same AnchorBank as T5), amp auto (bf16), side check off; --assignment s6/data/gold58.json, --split train
- before running: compact_infer.py makes no network calls; writes only --output (~/rsna/eval/T6) and --tmp (~/rsna/work/infer_tmp)
- scoring: ~/rsna/tools/score_gold.py (mechanical addition; oof_step.py is not shipped): roc_auc_score per finding vs train.csv gold rows, macro = mean of 12

## T6 DONE 2026-10-20T07:42:06Z
- E_prior_s42_fall.pt (sha256 0c7297d5...) forward only via compact_infer.py on the gold-58 (data from ~/rsna/data): 58/58 scored, fallback 0, 71.9 s, bf16 on the RTX A6000; anchors recomputed inline: skm_tea_joint 46, avg2 6, avg3 1, slab_prior 5
- REF macro AUC = 0.9313 (12 findings)
- REF per finding: ACL 0.9792, MCL 0.9660, Medial Meniscus 0.9603, Lateral Meniscus 0.9317, Medial OA 0.9891, Lateral OA 0.8588, PF OA 0.8919, Effusion 0.9540, Synovitis 0.8387, Baker's 0.9801, Contusion 0.9339, Fracture 0.8917
- GATE PASS: all 58 scored and REF 0.9313 >= 0.88
- outputs: ~/rsna/eval/T6/{predictions.csv, receipt.json, gold58_auc.json}; log rsna/logs/T6.log

## T7 START 2026-10-20T07:42:26Z
- Run A = run_all_alldata.sh's production argv (convnext_small, E_prior, crop 288, size 320, views v4, slices 3, phys-mm 3.5, 16 epochs, batch 2, 64 train windows, spatial-attn, grad-ckpt, lr 1e-4 / head 1e-3, wd 0.05, aug crop, uniform sampling, ema 0, --all-data, --only-folds 0, --resume, --no-final-predict) with ONLY: --targets ~/rsna/labels/targets_treatment.csv, --seed-base 7, --out ~/rsna/runs/A; plus the local paths (--pool, --folds-json, --init = the verified timm model.safetensors, --work-tmp ~/rsna/work/s6_work_A)
- CPU precheck (their --check-targets on this argv): "ALLDATA: train 4263 (every study of --pool 4321 minus gold 58 ...), held out 0, gold in training 0" and "check-targets OK"; 51,156 finite target cells; mean target per class [0.217, 0.136, 0.452, 0.241, 0.349, 0.283, 0.395, 0.471, 0.295, 0.319, 0.281, 0.142]
- before running: train_s6f0_all.py makes no network calls (timm pretrained only with --init timm; here a local file); writes go to --out and --work-tmp only
- disk free 228G; the original run took 54,148 s (15.0 h) on its machine; projected finish after epoch 1
- launched detached; log ~/rsna/logs/T7_train_A.log; per-epoch lines follow

## T7 NOTE 2026-10-20T07:45:17Z
- first launch exited at start-up (07:42:29Z, before any training step; no checkpoint written): "RuntimeError: CUDA driver error: unknown error" at the first tensor .to(cuda) (train_s6f0_all.py:745)
- cause: PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True (set by their launcher) makes every CUDA init fail under WSL2 on this driver; the same issue is documented on this machine for vLLM (scripts/a6000/serve.sh leaves it unset)
- mechanical fix: relaunch without that environment variable (allocator behaviour only; argv, model, labels and config unchanged); relaunching now

## T7 NOTE run A progress 2026-10-20T10:02:38Z
- run A, elapsed 137 min since 2026-10-20T07:45:19Z
- latest epoch: none finished yet
- latest step: Tue 13:01 step 1600/2131  loss(run mean) 0.4706  190.6 windows/s  loader wait 215s  failed 0  ETA fold end Tue 17:04

## T7 NOTE run A progress 2026-10-20T10:03:44Z
- run A: epoch 5/16 done, loss 0.4763, elapsed 138 min since 2026-10-20T07:45:19Z, projected finish 2026-10-20T15:08Z
- correction: the 10:02Z block said 'none finished yet'; that was this loop's pattern missing the epoch lines (5 epochs were done then). Epoch losses so far: epoch 1/16=0.5522 epoch 2/16=0.5117 epoch 3/16=0.4952 epoch 4/16=0.4837 epoch 5/16=0.4763 

## T4b DONE 2026-10-20T10:05:00Z
- gold truth: train.csv rows with all 12 labels = 58 (= data/gold58.json)
- JEV-blend (training_code/labels/labels_v1_blendjev.parquet, 4,349 rows): NO rows for any of the 58 gold ids (by construction; make_data.py asserts gold is not in it), so it cannot be scored on gold-58
- fused (soft_labels.csv, outer-held gold rows): n=58, macro AUC 0.9287 over its 11 findings; ACL 0.9681, MCL 0.9932, Medial Meniscus 0.9868, Lateral Meniscus 0.8783, Medial OA 0.9612, Lateral OA 0.8240, PF OA 0.9305, Effusion 0.9267, Baker's 0.9529, Contusion 0.9042, Fracture 0.8903; Synovitis not in the source
- 50/50 mix: not computable on gold-58 (needs JEV-blend rows for the gold ids, which do not exist)
- log: rsna/logs/T4b_T5c.log

## T5c DONE 2026-10-20T10:05:04Z
- ours over the 4,321 studies: skm_tea_joint 3,024 (70.0%), skm_tea_joint_avg2 595 (13.8%), skm_tea_joint_avg3 82 (1.9%), skm_tea_joint_avg4 2, slab_prior 618 (14.3%); failed outright 0; run time 35.6 min (07:03:54Z -> 07:39:28Z)
- theirs: no shipped file has anchor-method counts (pool_ok.counts.json has none; no shipped json/md/txt mentions slab_prior or skm_tea_joint), so the 5-point slab_prior check cannot be made directly
- what can be compared (shipped pool_ok.counts.json vs ours, both from freeze_pool.py): pool 4,321 / train 3,408 / fold0 855 / gold 58 SAME; stride-1 eval windows on the gold-58 35,148 vs 35,148 SAME (exact); train windows per epoch at 64 218,112 SAME (every study has >= 64 candidates, so this is only a floor check)

## T5c NOTE 2026-10-20T10:05:06Z
- RENDERS DIFFER OUTSIDE THE GOLD-58: stride-1 eval windows over the 855 fold-0 studies 493,359 (ours) vs 427,072 (theirs) = +15.5%, and the smallest train-candidate count 248 (ours) vs 231 (theirs). Window counts follow from each study's rendered rows (series, slices, views), so a part of the pool renders differently from what their model saw; the gold-58 renders match theirs exactly (35,148 windows each)
- likely cause, not verified: their local DICOM copy (they note deleted studies on 2026-09-29) may have had fewer series/slices for some studies than the full competition data we extracted; the anchor method mix is not comparable (no counts shipped)
- not a gate (Gate 0 = T6 passed at REF 0.9313 on the matching gold-58 renders); Run A continues. Run A loss tracks theirs (epoch 1..5: 0.5522 / 0.5117 / 0.4952 / 0.4837 / 0.4763 vs theirs 0.5517 / 0.5044 / 0.4824 / 0.4671 / 0.4564), with treatment labels rather than control, so the gap is not attributable to renders alone

## T7 NOTE run A progress 2026-10-20T10:18:47Z
- run A: epoch 6/16 done, loss 0.4709, elapsed 153 min since 2026-10-20T07:45:19Z, projected finish 2026-10-20T14:34Z
