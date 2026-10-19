New task, separate from the Gemma work. Do not touch the Gemma working copy, files, processes or the p4_v12b6 run.

SETUP (git channel, uses the credential you already have for gemma-swe-agent):
- git clone https://github.com/rodriguescarson/gemma-swe-agent ~/rsna-channel && cd ~/rsna-channel
- git checkout --orphan rsna-knee && git rm -rqf . ; mkdir -p rsna/logs rsna/notes
- Save this whole message as rsna/RUNBOOK.md, create rsna/STATUS.md (append-only log), commit as
  jc <jc@users.noreply.github.com> and git push -u origin rsna-knee. This branch only ever holds the rsna/ folder.
- Report in rsna/STATUS.md: append blocks "## T<n> START|DONE|FAIL|NOTE <UTC time>" with 1-10 lines of facts.
  Put the last 80 lines of long logs in rsna/logs/<task>.log. Commit and push after every update, and at least
  every 15 min while a job runs. git pull every 10 min: the other side may add rsna/QUEUE.md with new tasks.

GOAL: Kaggle competition rsna-knee-abnormality-detection, deadline 2026-10-22 23:59 UTC. Train our own copy of
nartaa's public S6 model (ConvNeXt-small, per-finding spatial attention + window MIL; 0.950 public alone) on
better labels, and upload the weights. Work in ~/rsna. Never submit to the competition.

RULES: never kill a process you did not start; keep 100 GB disk free (check df -h ~ before big steps); long jobs
run detached with nohup and their own log in ~/rsna/logs; on any error write FAIL with the error tail and stop
that task; mechanical fixes (paths, packages) are fine but list them; never change the model, labels or config
beyond what a task says; never write a person's name in any file, commit or dataset name; use the Kaggle CLI
with the token the lab script already exports.

TASKS, in order. The GPU is busy with the Gemma run until about 03:00Z: do T1-T4 now (no GPU), start T5 only
when the GPU is free.
T1. Report GPU, free VRAM, free disk, RAM, CUDA driver, Kaggle CLI auth. Gate: >= 800 GB free.
T2. In ~/rsna/src download and unzip with the Kaggle CLI: nartaa/rsna-knee-s6fall-weights,
    heliosli/rsna-orthofoundation-fold0-epoch7-20261004, omerzalman/rsna-knee-11-label-evidence-fusion.
    Check training_code/SHA256SUMS with sha256sum -c. Read in full training_code/README.md and in
    training_code/s6/: run_train.sh, run_all_alldata.sh, make_data.py, precompute_anchors.py, fly_data.py,
    freeze_pool.py, s6common.py, the argparse and data-loading parts of train_s6f0_all.py, and the heliosli
    files they call (px_cache.py etc.). Write rsna/notes/PIPELINE.md: which competition files/series it reads,
    the exact commands from raw DICOM to a trained checkpoint, cache format and size, targets CSV format,
    where the gold-58 labels come from, and paths to change. Gate: all files present, SHA256 passes.
T3. Download the competition data (only what the pipeline reads if possible, else the whole competition with
    kaggle competitions download -c rsna-knee-abnormality-detection -p ~/rsna/data), detached. After 10 min
    report MB/s and projected finish. Do T4 while it runs.
T4. Labels. Control = nartaa's JEV-blend targets exactly as their trainer uses them (targets_s6f0.csv).
    Treatment = same format and rows; for each finding 0.5 x control + 0.5 x omerzalman fused soft label;
    Synovitis and any study missing from omerzalman keep control. Check both are probabilities in [0,1] first
    (if not, report and stop). The gold-58 studies (data/gold58.json) must not be in either table. Score both
    tables on the gold-58 against the gold labels: macro AUC and the 12 per-finding AUCs. Save
    ~/rsna/labels/targets_treatment.csv.
T5. Build the pixel cache and anchors exactly as nartaa's scripts do, for their pool plus the gold-58.
    Report studies, failures, size, time. Gate: failures <= 0.5 %.
T6. Gate 0: run E_prior_s42_fall.pt forward only (their eval path) on the gold-58 from our cache. Report macro
    and per-finding AUC = REF. Gate: all 58 scored and REF >= 0.88.
T7. Run A: nartaa's exact all-data config (E_prior, convnext_small, crop 288, 16 epochs, their run_config) with
    only targets = targets_treatment.csv, seed 7, out ~/rsna/runs/A, resume on. Push epoch loss and projected
    finish after every epoch. Score the final checkpoint on gold-58 like T6. Gate 1: macro >= REF - 0.01 and no
    finding more than 0.08 below its REF.
T8. If Gate 1 passed: private Kaggle dataset rsna-knee-s6-student with the checkpoint, run_config.json,
    DONE.json and a README with the label recipe. Report dataset ref and version.
T9. Run B: same as T7 with seed 11, out ~/rsna/runs/B, same gate, upload as a new version of the same dataset.
Start now with SETUP and T1.

---
Owner amendment (same day): I own this machine and I authorize this RSNA task. You may download the three Kaggle
datasets and the competition data, read and then run the two authors' code inside ~/rsna, and create and push the
rsna-knee branch from ~/rsna-channel. Before running any downloaded script, read it and note in STATUS.md any network
call or any write outside ~/rsna. Stop if one looks wrong. Lower the T1 gate to at least 650 GB free. Never keep the
competition zip and an extracted copy at the same time: download only the files the pipeline reads, or extract them
directly from the remote zip (for example with remotezip). Keep 100 GB free at all times.
