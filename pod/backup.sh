#!/usr/bin/env bash
# Back up everything worth keeping to a PRIVATE HF dataset repo, then verify the upload landed. Exit 1 on any failure
# (callers must NOT stop the pod when this fails). Usage: bash pod/backup.sh <label>
set -uo pipefail
LABEL=${1:-manual}; REPO=rodriguescarson/gemma4-agent-artifacts; TS=$(date -u +%Y%m%dT%H%M%SZ)
source /root/venv/bin/activate
STAGE=/root/backup_stage/$TS-$LABEL; mkdir -p $STAGE
cd /root/g4
tar czf $STAGE/eval_runs.tgz eval/runs eval/progress.log 2>/dev/null
[ -d /root/data ] && find /root/data -maxdepth 1 -name "*.jsonl" -size -3G -exec cp {} $STAGE/ \; 2>/dev/null
for d in /root/train_out /root/g4/train/out; do [ -d $d ] && tar czf $STAGE/$(basename $d)_adapters.tgz -C $d . ; done
cp /root/*.log /root/*.out $STAGE/ 2>/dev/null
ls -la $STAGE > $STAGE/MANIFEST.txt
hf repo create $REPO --repo-type dataset --private >/dev/null 2>&1 || true
hf upload $REPO $STAGE backups/$TS-$LABEL --repo-type dataset --commit-message "backup $LABEL $TS" > /root/backup_upload.log 2>&1 || { echo "BACKUP_FAILED upload $TS" >> eval/progress.log; exit 1; }
python - "$REPO" "backups/$TS-$LABEL" "$STAGE" <<'PY' || { echo "BACKUP_FAILED verify $TS" >> eval/progress.log; exit 1; }
import os, sys
from huggingface_hub import HfApi
repo, prefix, stage = sys.argv[1:4]
remote = {f.path.split("/")[-1]: f.size for f in HfApi().list_repo_tree(repo, path_in_repo=prefix, repo_type="dataset", recursive=True) if hasattr(f, "size")}
for f in os.listdir(stage):
    assert remote.get(f) == os.path.getsize(os.path.join(stage, f)), f"missing or wrong size: {f}"
print("verified", len(remote), "files")
PY
echo "BACKUP_OK $TS-$LABEL $(du -sh $STAGE | cut -f1)" >> eval/progress.log
