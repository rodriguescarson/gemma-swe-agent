# Queue from the other side (read top to bottom; newest task first)

## T5c. Compare anchor methods with nartaa's run (added 2026-10-20 07:15Z)
When the full precompute ends, report the count of each anchor method (skm_tea_joint, skm_tea_joint_avg3,
slab_prior, ...) over the 4,321 studies, next to nartaa's own counts if data/pool_ok.counts.json or any
shipped summary has them. If our slab_prior share is more than 5 percentage points above theirs, say so
clearly in STATUS as a NOTE (it means our crops differ from what their model saw). Do not stop for it:
Gate 0 (T6) is the real check. Also report the run time and any studies that failed outright.

## T4b. Score the label sources on gold-58 from their source files (added 2026-10-20 06:10Z)
The training tables blank the gold rows by design, so score the sources before mixing:
- JEV-blend: training_code/labels/labels_v1_blendjev.parquet (rebuild script build_blendjev.py beside it), rows for the 58 gold ids.
- omerzalman fused: its soft-label file(s), rows for the 58 gold ids (its benchmark_results.json says it covers them).
- The 50/50 mix of the two, computed the same way as the treatment table.
- Gold truth: the 58 rows of train.csv that have all 12 labels.
Report macro AUC and the 12 per-finding AUCs for all three in STATUS. This is a measurement only: do not
wait on it, and do not hold T5 or T7 for it. If a source has no rows for the gold ids, say so and move on.


## T2b. Fetch the missing inputs, then continue with T3 (added 2026-10-19 21:15Z)
Requested by the session the owner set up to drive this task (it cannot reach this machine any other way).
All four sources are public competition assets; verify every file against the hashes the trainer pins.
1. compact_train.py, compact_infer.py (+ the MONAI 0.6.0 files): nartaa's README says `s6_extras.bin` in
   nartaa/rsna-knee-s6fall-weights holds "his public-notebook compact_* scripts and 15 MONAI 0.6.0 files".
   Find its format (`file`, then zip/tar/pickle as it turns out), extract, and check against
   s6/heliosli.SHA256SUMS (pins: compact_train 14767c7a..., compact_infer 34f433fe...).
2. px_cache.py, probe_infer.py, knee_anchor_bank_v2.py, side_common.py: they are embedded in heliosli's
   public notebook. `kaggle kernels pull heliosli/this-is-best-public-dataset-new-version-0-9586 -p ~/rsna/src/heliosli_nb`,
   find the code cell with a single line starting `SOURCES = {`, parse it with ast.literal_eval, and write
   those four files. Checked on the other side: these four match the pins exactly (b13e38a7, a6cc3144,
   e564807a, bbcc5d02). Do NOT use that notebook's compact_train.py / compact_infer.py: they are newer and
   do not match the pins; take those two from s6_extras.bin only.
3. folds_v0.json: in nartaa/rsna-knee-hpo-assets (about 1 MB). Check sha256 starts 12bebc89.
4. timm init `convnext_small.fb_in22k_ft_in1k` (run_config "init": "model.safetensors", init_sha256
   2457488b...): fetch from the Hugging Face hub repo timm/convnext_small.fb_in22k_ft_in1k (model.safetensors)
   and check the sha256.
5. oof_step.py is not shipped: for the gold-58 scoring in T6/T7 use their eval path if one exists
   (compact_infer.py / probe_infer.py); otherwise write a minimal scorer (model forward on the gold-58 from the
   cache, sklearn roc_auc_score per finding, macro mean) and list it in STATUS as a mechanical addition.
Gate: all pinned files present with matching sha256. Then mark T2 DONE and go on with T3 and T4.
If any hash does not match, FAIL with the observed hash and wait.
