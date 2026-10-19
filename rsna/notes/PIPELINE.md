# S6 all-data pipeline (from rsna-knee-s6fall-weights/training_code; read 2026-10-19)

Author paths below are written as `<author-root>` (the scripts hard-code a home directory).

## Competition data it reads
- `<DATA>/train_series/<StudyInstanceUID>/<SeriesInstanceUID>/*.dcm` (DICOM directory; `native_cache.prepare(..., source_directory=True)`; `s6common.DATA` = `<author-root>/raw`, `SPLIT = "train"`). No pixel cache is kept: every study is rendered from DICOM on the fly each time it is loaded.
- `<DATA>/train.csv`: only to cross-check the 58 gold ids (rows with all 12 labels) in `make_data.py`; their gold labels for scoring come from the same rows.
- Studies needed: `data/pool_ok.json` = 4,321 (4,263 training + 58 gold). `train_ids.json` 3,408 and `fold0_ondisk.json` 855 belong to the earlier fold-0 run.

## Inputs shipped in the dataset (all in SHA256SUMS: pass)
- `s6/data/targets_s6f0.csv`: header `StudyInstanceUID,is_gold,review_holdout,fold,<12 x L|prior>,<12 x L|strict>`, 4,407 rows. `L|prior` = labels_v1_blendjev soft labels for non-gold rows; `L|strict` blank everywhere; gold rows have `is_gold=1`, fold -1 and all labels blank (the trainer asserts that). Arm `E_prior` reads `L|prior` (weight-normalised BCE, unit weights).
- `s6/data/pool_ok.json` (4,321), `gold58.json` (58), `train_ids.json`, `fold0_ondisk.json`, `pool_ok.counts.json`.
- Labels for 12 findings in this order: ACL, MCL, Medial Meniscus, Lateral Meniscus, Medial OA, Lateral OA, PF OA, Effusion, Synovitis, Baker's, Contusion, Fracture.
- `E_prior_s42_fall.pt` (200 MB), `E_prior_s42_fall.run_config.json`, `.DONE.json`.

## Inputs NOT in the three T2 datasets
1. The six heliosli sources imported by every script (pinned in `s6/heliosli.SHA256SUMS`, checked at start-up by `s6common.verify_copies`): `px_cache.py` b13e38a7..., `compact_train.py` 14767c7a..., `compact_infer.py` 34f433fe..., `probe_infer.py` a6cc3144..., `knee_anchor_bank_v2.py` e564807a..., `side_common.py` bbcc5d02.... The heliosli dataset holds only `cloud_code/training/` (161 files), `anatomy.pt`, `weights.part*` and `dependencies/`. The sources belong to the public "0.954" Kaggle notebook (its SOURCE_SHA).
2. `folds_v0.json` (from the nartaa/rsna-knee-hpo-assets dataset; sha256 12bebc89...): `--folds-json` is required. In all-data mode every pool fold value must be 0..4.
3. ConvNeXt-small init: timm `convnext_small.fb_in22k_ft_in1k` `model.safetensors` (Hugging Face hub snapshot fe6b358a...); their scripts run with HF_HUB_OFFLINE=1.
4. `oof_step.py` (their gold-58 inference step) is not shipped; the gold-58 path would use the heliosli `compact_infer.py` (from 1.).

## Commands, raw DICOM -> checkpoint (their order)
1. `python make_data.py` -> data/targets_s6f0.csv, train_ids.json, fold0_*.json, gold58.json, precompute_order.json. Needs labels_v1_blendjev.parquet, folds_v0.json, raw/train.csv and a DELETED list. The shipped data/ files replace this step; precompute_order.json is not shipped and would be pool_ok.json's order.
2. `python -u precompute_anchors.py --order data/precompute_order.json --workers 8 --out anchors --tmp <tmp>`: per study, lean `native.prepare` -> `training.geometry_bank.build` -> `knee_anchor_bank_v2.AnchorBank.record` (anatomy.pt VNet on CUDA in every spawn worker) -> `anchors/<sha256(uid)[:24]>.json`, plus `anchors/manifest.jsonl` and `summary.json`. Resumable. Needs a GPU.
3. `python freeze_pool.py --final` -> data/pool_ok.json + pool_ok.counts.json (from the manifest; refuses if incomplete or different).
4. Train (run_all_alldata.sh step 5): `python -B -u train_s6f0_all.py --pool data/pool_ok.json --folds-json folds_v0.json --targets data/targets_s6f0.csv --out runs/train --arms E_prior --backbone convnext_small --init <model.safetensors> --seeds 1 --seed-base 42 --folds 5 --only-folds 0 --expect-train 4263 --expect-holdout 0 --all-data --epochs 16 --batch 2 --train-windows 64 --size 320 --views v4 --crop 288 --slices 3 --phys-mm 3.5 --spatial-attn --grad-ckpt --lr 1e-4 --head-lr 1e-3 --wd 0.05 --aug crop --train-sampling uniform --ema 0 --workers 8 --loader-timeout 600 --max-fail-frac 0.005 --log-every 200 --work-tmp <tmp> --resume --no-final-predict --i-have-user-authorisation-to-finetune` (env PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True). Output: runs/train/models/E_prior_s42_fall.pt + DONE_E_prior_s42_fall.json; a checkpoint per epoch in runs/train/ckpt/. `--check-targets` on CPU validates first. Seed for T7/T9: `--seed-base 7` / `11`.
5. Gold-58: `oof_step.py --sets gold58:...` (not shipped) -> compact_infer path.

## Cache format and size
- No pixel cache. Anchors: one JSON per study (`anchors/<sha24>.json`) + manifest.jsonl. Size to be measured in T5 (small JSONs).
- Work dirs: per-study tmp dirs under `--work-tmp` (wiped at start), removed after each study.

## Paths to change
- `s6common.py`: `ANATOMY` (-> heliosli dataset anatomy.pt, sha 5904dd16... matches the receipt), `DATA` (-> ~/rsna/data), `HELIOS_SRC` = `<s6 dir>/heliosli` (needs the six sources) and `CODE` = `<s6 dir>/heliosli/cloud_code` (-> the heliosli dataset's cloud_code).
- `train_s6f0_all.py` line 590: hard-coded S6F0 import directory (ALLDATA A1); `--work-tmp`; `--init`; `--folds-json`.
- `precompute_anchors.py` `--tmp`; `fly_data.py` default tmp.

## Network calls / writes outside ~/rsna (owner amendment)
- S6 scripts: no network calls. Writes go only to their own data/anchors/runs dirs and to the tmp work dirs (`/tmp/s6f0_work`, `/tmp/s6f0_anchors_work` by default; both are arguments and will be set under ~/rsna).
- heliosli cloud_code/training has network-capable modules (download_data.py, direct_network.py, proxy_network.py, fastmri_download.py, kneemri_reference_fetch.py, fetch_pretrained.py with an HF mirror). The S6 path imports only native_cache / geometry_bank, and s6common stubs `training.download_data`, so none of these run.
