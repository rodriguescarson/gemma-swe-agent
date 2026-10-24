#!/usr/bin/env bash
# EC2 user-data body of the gemma4-agent kit (aws/README.md). aws/launch.py puts `shutdown -h +N` (the hard timer) and
# /opt/g4/job.env in front of it and runs it as root. Port of pod/bootstrap.sh + pod/backup.sh + pod/supervisor.sh:
# outputs go to S3 instead of HF, and the machine stops itself (InstanceInitiatedShutdownBehavior=terminate, so a stop
# is a terminate). The pod layout is kept (/root/g4 repo, /root/venv vLLM, /root/hvenv harness, /root/buildenv,
# /root/models/g4), so pod/{harness_env,buildenv,serve,run_eval,canary}.sh and scripts/a6000/train.sh run unchanged.
#   bash /opt/g4/bootstrap.sh          setup -> pull in/ -> job -> final sync -> shutdown -h now (always, via the EXIT trap)
#   bash /opt/g4/bootstrap.sh sync     copy outputs to S3 (systemd runs this when the machine stops)
# S3: $G4_RUN/in/{code.tgz,overlay/} -> /root/g4; /opt/g4/out -> $G4_RUN/out/box/<instance-id>/; each repo path in
# $G4_KEEP -> $G4_RUN/out/keep/<path> (pulled back at boot, so a relaunch of the same run resumes).
set -Eeuo pipefail
[ -f /opt/g4/job.env ] && [ "$(id -u)" = 0 ] || { echo "not a gemma4-agent EC2 job box (no /opt/g4/job.env or not root); refusing"; exit 2; }
# shellcheck disable=SC1091
source /opt/g4/job.env
export HOME=/root PATH=/opt/g4/bin:/root/.local/bin:$PATH UV_LINK_MODE=copy DEBIAN_FRONTEND=noninteractive
OUT=/opt/g4/out; REPO=/root/g4; mkdir -p "$OUT"
VLLM_WHEEL=vllm-0.19.1-cp38-abi3-manylinux_2_31_x86_64.whl
UV_VERSION=0.12.5

log() { echo "$(date -u +%FT%TZ) $*" | tee -a "$OUT/progress.log" >&2; }
imds() {
  local t; t=$(curl -sf -m 2 -X PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 300") &&
    curl -sf -m 2 -H "X-aws-ec2-metadata-token: $t" "http://169.254.169.254/latest/$1"
}

# --------------------------------------------------------------------------------------------------- outputs -> S3
keep_src() { case $1 in /*) echo "$1" ;; *) echo "$REPO/$1" ;; esac; }
box_dest() { echo "$G4_RUN/out/box/$(cat /opt/g4/IID 2>/dev/null || hostname)"; }
sync_out() {   # $1 = final|periodic|spot|stop. Verified like pod/backup.sh: a dry-run sync afterwards must find nothing left.
  exec 9>/opt/g4/sync.lock; flock -w 900 9 || { log "SYNC_SKIPPED $1 (lock)"; return 1; }
  local rc=0 p src dst left=0 box; box=$(box_dest)
  aws s3 sync "$OUT" "$box/" --only-show-errors || rc=1
  for p in $G4_KEEP; do
    src=$(keep_src "$p"); dst="$G4_RUN/out/keep/${p#/}"
    if [ -d "$src" ]; then aws s3 sync "$src" "$dst/" --only-show-errors || rc=1
    elif [ -f "$src" ]; then aws s3 cp "$src" "$dst" --only-show-errors || rc=1; fi
  done
  if [ "$1" = final ] && [ $rc = 0 ]; then
    left=$(aws s3 sync "$OUT" "$box/" --dryrun --exclude progress.log --exclude boot.log | grep -c "upload:" || true)
    for p in $G4_KEEP; do
      src=$(keep_src "$p"); [ -d "$src" ] && left=$((left + $(aws s3 sync "$src" "$G4_RUN/out/keep/${p#/}/" --dryrun | grep -c "upload:" || true)))
    done
    [ "$left" = 0 ] || rc=1
  fi
  if [ $rc = 0 ]; then log "SYNC_OK $1 $box"; else log "SYNC_FAILED $1 (files left: $left)"; fi
  flock -u 9; return $rc
}
final_sync() {   # retry for G4_FINAL_SYNC_MIN; after that the machine stops anyway (the periodic syncs hold the rest)
  local until=$(( $(date +%s) + 60 * ${G4_FINAL_SYNC_MIN:-20} ))
  until sync_out final; do
    [ "$(date +%s)" -ge "$until" ] && { log "ALERT FINAL_SYNC_FAILED: stopping anyway; see the last SYNC_OK"; return 1; }
    sleep 60
  done
}

# ------------------------------------------------------------------- watcher (port of pod/supervisor.sh's checks)
watch_loop() {   # periodic sync, spot-interruption notice, and the stall rule; the runtime ceiling is the hard timer
  set +e
  local last_sync; last_sync=$(date +%s); local quiet=0
  while sleep 15; do
    if imds meta-data/spot/instance-action >/dev/null 2>&1; then
      log "SPOT_INTERRUPTION notice: syncing now"; sync_out spot; sleep 150; continue
    fi
    if [ $(( $(date +%s) - last_sync )) -ge $(( 60 * G4_SYNC_MIN )) ]; then
      sync_out periodic || log "ALERT periodic sync failed"; last_sync=$(date +%s)
    fi
    [ -f /opt/g4/JOB_PID ] && [ "${G4_STALL_MIN:-0}" -gt 0 ] || continue
    local paths=("$OUT"); for p in $G4_KEEP; do [ -e "$(keep_src "$p")" ] && paths+=("$(keep_src "$p")"); done
    local fresh util=0
    fresh=$(find "${paths[@]}" -name progress.log -prune -o -type f -mmin "-$G4_STALL_MIN" -print -quit 2>/dev/null)
    command -v nvidia-smi >/dev/null && util=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits | awk '{s+=$1} END {print s+0}')
    if [ -z "$fresh" ] && [ "${util:-0}" -eq 0 ]; then quiet=$((quiet + 1)); else quiet=0; fi
    if [ $quiet -ge 4 ]; then   # a minute of samples on top of the window
      log "ALERT STALL: no output change for ${G4_STALL_MIN} min and GPUs idle; ending the job"
      kill -TERM -- "-$(cat /opt/g4/JOB_PID)" 2>/dev/null; quiet=0
    fi
  done
}

# ------------------------------------------------------------------------------------------------------- setup steps
install_awscli() {
  command -v aws >/dev/null && return
  snap install aws-cli --classic >/dev/null 2>&1 && return
  apt-get -qq update && apt-get -qq install -y unzip >/dev/null
  curl -fsSL -o /tmp/awscliv2.zip https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip
  (cd /tmp && unzip -q -o awscliv2.zip && ./aws/install --update)
}
install_uv() {   # a pinned release, checked against its published sha256
  command -v uv >/dev/null && return
  local f=uv-x86_64-unknown-linux-gnu.tar.gz base=https://github.com/astral-sh/uv/releases/download/$UV_VERSION
  curl -fsSL -o "/tmp/$f" "$base/$f" && curl -fsSL -o "/tmp/$f.sha256" "$base/$f.sha256"
  (cd /tmp && sha256sum -c "$f.sha256")
  mkdir -p /opt/g4/bin && tar xzf "/tmp/$f" -C /opt/g4/bin --strip-components 1
}
setup_docker() {
  command -v docker >/dev/null || { apt-get -qq update && apt-get -qq install -y docker.io >/dev/null; }
  systemctl enable --now docker >/dev/null 2>&1 || true
  docker info >/dev/null
}
setup_data() {   # the competition's data/raw (pod: scripts/fetch_data.py from Kaggle; here: staged once in S3)
  aws s3 sync "$G4_SHARED/raw/" "$REPO/data/raw/" --only-show-errors
  [ -n "$(ls "$REPO/data/raw/wheels" 2>/dev/null)" ] || { log "data/raw/wheels is empty after the pull"; return 1; }
  ln -sfn "$REPO/data/raw/wheels" /wheels
  ln -sfn "$REPO/data/raw/graphs" "$REPO/data/graphs"
  ln -sfn "$REPO/data/raw/embeddings" "$REPO/data/embeddings"
}
setup_wheels() {   # only the competition's data/raw/wheels (pod/harness_env.sh and the race container read /wheels)
  aws s3 sync "$G4_SHARED/raw/wheels/" "$REPO/data/raw/wheels/" --only-show-errors
  [ -n "$(ls "$REPO/data/raw/wheels" 2>/dev/null)" ] || { log "data/raw/wheels is empty after the pull"; return 1; }
  ln -sfn "$REPO/data/raw/wheels" /wheels
}
setup_vllm() {   # pod/bootstrap.sh's env, with the organiser-patched wheel from S3 instead of the Kaggle CLI
  [ -d /root/venv ] || uv venv -q -p 3.12 /root/venv
  VIRTUAL_ENV=/root/venv uv pip install -q "vllm==0.19.1" "huggingface_hub[cli]" pyyaml
  # The scorer uses a PATCHED vllm 0.19.1 (adds SupportsLoRA to Gemma4) from the competition wheelhouse; PyPI's build refuses LoRA.
  mkdir -p /root/wheelhouse && aws s3 cp "$G4_SHARED/wheelhouse/$VLLM_WHEEL" "/root/wheelhouse/$VLLM_WHEEL" --only-show-errors
  VIRTUAL_ENV=/root/venv uv pip install -q --no-deps --reinstall "/root/wheelhouse/$VLLM_WHEEL"
  /root/venv/bin/python -c "import vllm.model_executor.models.gemma4_mm as g; assert getattr(g.Gemma4ForConditionalGeneration, 'supports_lora', False), 'UNPATCHED vllm'; print('patched vllm OK')"
  VIRTUAL_ENV=/root/venv uv pip install -q --no-deps "transformers==5.13.1" "tokenizers==0.22.1" "fastapi==0.118.0" "starlette==0.48.0"
  /root/venv/bin/python -c "import vllm; print('vllm', vllm.__version__)"
}
pull_model() {   # $1 = S3 name under shared/models/, $2 = local dir, $3 = HF repo fallback (Apache-2.0, not gated)
  if aws s3 ls "$G4_SHARED/models/$1/config.json" >/dev/null 2>&1; then
    aws s3 sync "$G4_SHARED/models/$1/" "$2/" --only-show-errors
  elif [ -n "${3:-}" ]; then
    uvx --from "huggingface_hub[cli]" hf download "$3" --local-dir "$2"
  else
    return 1
  fi
  if ! { [ -f "$2/config.json" ] && ls "$2"/*.safetensors >/dev/null 2>&1; }; then log "model $1 incomplete in $2"; return 1; fi
}
setup_model() { pull_model g4 /root/models/g4 google/gemma-4-31B-it-qat-w4a16-ct; }
setup_harness() { bash "$REPO/pod/harness_env.sh"; }
setup_buildenv() { bash "$REPO/pod/buildenv.sh"; }
setup_trainenv() { bash "$REPO/scripts/a6000/train_env.sh" /root/tvenv; }
setup_bf16() {   # the dequantised base: from S3 when an earlier run left it there, else dequantise once and upload it
  pull_model g4-bf16 /root/models/g4-bf16 "" && [ -f /root/models/g4-bf16/DEQUANT.json ] && return
  setup_model
  TRAIN_VENV=/root/tvenv MODEL_DIR=/root/models/g4 BF16_DIR=/root/models/g4-bf16 bash "$REPO/scripts/a6000/train.sh" dequant
  aws s3 sync /root/models/g4-bf16/ "$G4_SHARED/models/g4-bf16/" --only-show-errors && log "bf16 base uploaded to $G4_SHARED/models/g4-bf16/"
}

# ---------------------------------------------------------------------------------------------------------- the run
finish() {
  local rc=$?
  trap - EXIT; set +e
  if [ -f /opt/g4/JOB_PID ]; then   # the job's whole process group, leftovers too (e.g. a nohup vLLM server)
    kill -TERM -- "-$(cat /opt/g4/JOB_PID)" 2>/dev/null; for _ in $(seq 1 60); do kill -0 -- "-$(cat /opt/g4/JOB_PID)" 2>/dev/null || break; sleep 1; done
  fi
  [ -n "${WATCH_PID:-}" ] && kill "$WATCH_PID" 2>/dev/null
  log "END rc=$rc"
  printf 'rc=%s\nstarted=%s\nended=%s\ninstance=%s\n' "$rc" "${STARTED:-}" "$(date -u +%FT%TZ)" "$(cat "$OUT/INSTANCE" 2>/dev/null | tr '\n' ' ')" > "$OUT/RESULT"
  if [ "${S3_OK:-0}" != 1 ]; then log "S3 was never reachable: nothing to sync"
  elif [ "${TERMINATED:-0}" = 1 ]; then timeout 300 bash /opt/g4/bootstrap.sh sync   # the OS is going down: one bounded try
  else final_sync; fi
  log "SHUTDOWN now"
  shutdown -h now
}

main() {
  exec >> "$OUT/boot.log" 2>&1
  STARTED=$(date -u +%FT%TZ)
  trap 'TERMINATED=1; exit 143' TERM INT HUP
  trap finish EXIT
  log "BOOT role=$G4_ROLE run=$G4_RUN hours=$G4_HOURS deadline=$G4_DEADLINE setup='$G4_SETUP'"
  if [ ! -e /run/systemd/shutdown/scheduled ]; then   # the user-data's first line sets it; never run without one
    left=$(( (G4_DEADLINE_EPOCH - $(date +%s)) / 60 )); [ "$left" -lt 1 ] && left=1
    log "ALERT hard timer not found; scheduling shutdown in $left min"; shutdown -h "+$left" "gemma4-agent hard timer"
  fi
  imds meta-data/instance-id > /opt/g4/IID || hostname > /opt/g4/IID
  { echo "id=$(cat /opt/g4/IID)"; echo "type=$(imds meta-data/instance-type)"; echo "az=$(imds meta-data/placement/availability-zone)"
    echo "market=$(imds meta-data/instance-life-cycle)"; } > "$OUT/INSTANCE" || true
  install_awscli
  date -u +%FT%TZ > "$OUT/BOOT"
  if aws s3 cp "$OUT/BOOT" "$(box_dest)/BOOT" --only-show-errors && aws s3 ls "$(box_dest)/BOOT" >/dev/null; then S3_OK=1
  else log "S3 not writable at $(box_dest)/ (bucket or instance profile); stopping before any work"; exit 3; fi
  cat > /etc/systemd/system/g4-sync-on-stop.service <<'UNIT'
[Unit]
Description=gemma4-agent: copy outputs to S3 before the machine stops
Wants=network-online.target
After=network-online.target
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/true
ExecStop=/bin/bash /opt/g4/bootstrap.sh sync
TimeoutStopSec=600
[Install]
WantedBy=multi-user.target
UNIT
  systemctl daemon-reload && systemctl enable --now g4-sync-on-stop.service
  watch_loop & WATCH_PID=$!
  mkdir -p "$REPO"
  aws s3 cp "$G4_RUN/in/code.tgz" /opt/g4/code.tgz --only-show-errors
  tar xzf /opt/g4/code.tgz -C "$REPO"
  aws s3 sync "$G4_RUN/in/overlay/" "$REPO/" --only-show-errors   # job inputs at their repo paths
  for p in $G4_KEEP; do   # resume: whatever an earlier (e.g. spot-interrupted) attempt of this run already synced
    case $p in /*) continue ;; esac
    if aws s3 cp "$G4_RUN/out/keep/$p" "$REPO/$p" --only-show-errors >/dev/null 2>&1; then :
    elif aws s3 ls "$G4_RUN/out/keep/$p/" >/dev/null 2>&1; then aws s3 sync "$G4_RUN/out/keep/$p/" "$REPO/$p/" --only-show-errors; fi
  done
  install_uv
  for step in docker data wheels vllm model harness buildenv trainenv bf16; do   # fixed order: wheels before harness, model before bf16
    case " $G4_SETUP " in *" $step "*) log "SETUP $step"; "setup_$step"; log "SETUP_OK $step" ;; esac
  done
  cd "$REPO"
  export G4_OUT=$OUT TRAIN_VENV=/root/tvenv MODEL_DIR=/root/models/g4 BF16_DIR=/root/models/g4-bf16
  log "JOB_START $G4_JOB"
  setsid bash -c "$G4_JOB" > "$OUT/job.out" 2>&1 < /dev/null &
  echo $! > /opt/g4/JOB_PID
  set +e; wait "$(cat /opt/g4/JOB_PID)"; rc=$?; set -e
  log "JOB_DONE rc=$rc"
  exit "$rc"
}

case "${1:-main}" in
  main) main ;;
  sync) sync_out stop ;;
  *) echo "usage: bootstrap.sh [sync]"; exit 2 ;;
esac
