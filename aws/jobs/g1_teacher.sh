#!/usr/bin/env bash
# G1 teacher pilot (docs/GAPS_2026-10-06.md "G1 pre-registration"), the job of aws/launch.py's teacher role on one
# g6e.12xlarge (4x L40S 48 GB). It runs in /root/g4 after aws/bootstrap.sh's setup (docker, /wheels, /root/hvenv):
#   1 the NVMe instance store at $NVME (weights and the HF cache live there, not on EBS)
#   2 a teacher vLLM venv /root/tvllm on the latest stable vLLM, NOT the scorer's patched 0.19.1 (/root/venv, Gemma only)
#   3 weights from Hugging Face; both teachers are Apache-2.0 and not gated, so no token is needed
#   4 the scratch bundle: v12b with max_time_minutes 20 and max_tool_calls 100 (aws/jobs/g1_race.py bundle; never submissions/)
#   5 vLLM: Devstral-Small-2-24B on GPU0 (TP1, mistral tool parser); gpt-oss-120b on GPUs 2-3 (TP2, openai parsers)
#   6 per teacher: scripts/or_proxy.py --upstream vllm --capture $OUT/capture_<teacher>.jsonl --max-usd 1000, probed first
#   7 per teacher, in parallel: aws/jobs/g1_race.py over data/distill/g1_ids.txt -> $OUT/<teacher>/items/<arm>/<task>/
#   8 $OUT/status.json; bootstrap.sh then syncs eval/g1 to S3 and the machine terminates itself
# A teacher whose download, server or probe fails is skipped and recorded; the job fails only if no teacher ran.
#   python aws/launch.py teacher --hours 3.75 --max-usd 40 --run s3://B/runs/g1 --job 'bash aws/jobs/g1_teacher.sh' [--yes]
# Scoring happens on the Mac afterwards: scripts/distill/usable.py on the fetched eval/g1.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd); cd "$ROOT" || exit 2
OUT=${G1_OUT:-$ROOT/eval/g1}; IDS=${G1_IDS:-data/distill/g1_ids.txt}; HARNESS=${G1_HARNESS:-data/heldout1k/harness_g1}
NVME=${G1_NVME:-/opt/dlami/nvme}; TV=${TEACHER_VENV:-/root/tvllm}; VLLM_VERSION=${TEACHER_VLLM:-0.31.0}
PY=${G1_PY:-/root/hvenv/bin/python}; SCRATCH=${G1_SCRATCH:-/opt/g4/scratch}; ARM=g1_v12b_t20
CONC=${G1_CONC:-6}; CPUS=${G1_CPUS:-20}; TEACHERS=${G1_TEACHERS:-devstral gptoss}; RATE_USD_H=10.49264
mkdir -p "$OUT"

step() { echo "$(date -u +%FT%TZ) $*" | tee -a "$OUT/job.log"; }
repo_id() { case $1 in devstral) echo mistralai/Devstral-Small-2-24B-Instruct-2512 ;; gptoss) echo openai/gpt-oss-120b ;; esac; }
served() { case $1 in devstral) echo devstral-small-2-24b ;; gptoss) echo gpt-oss-120b ;; esac; }
gpus() { case $1 in devstral) echo "${DEVSTRAL_GPUS:-0}" ;; gptoss) echo "${GPTOSS_GPUS:-2,3}" ;; esac; }
tp() { case $1 in devstral) echo "${DEVSTRAL_TP:-1}" ;; gptoss) echo "${GPTOSS_TP:-2}" ;; esac; }
vport() { case $1 in devstral) echo 8101 ;; gptoss) echo 8102 ;; esac; }
pport() { case $1 in devstral) echo 8201 ;; gptoss) echo 8202 ;; esac; }
serve_flags() {   # the model cards' tool flags; *_EXTRA appends (e.g. DEVSTRAL_EXTRA="--kv-cache-dtype fp8")
  case $1 in
    devstral) echo "--tool-call-parser mistral --enable-auto-tool-choice --max-model-len ${DEVSTRAL_LEN:-65536} ${DEVSTRAL_EXTRA:-}" ;;
    gptoss) echo "--tool-call-parser openai --enable-auto-tool-choice --reasoning-parser openai_gptoss --max-model-len ${GPTOSS_LEN:-65536} ${GPTOSS_EXTRA:-}" ;;
  esac
}

setup_nvme() {   # the DLAMI usually mounts the instance store at /opt/dlami/nvme; otherwise format and mount the first disk
  mountpoint -q "$NVME" && { step "NVMe at $NVME: $(df -h "$NVME" | tail -1)"; return 0; }
  local dev; dev=$(lsblk -dpno NAME,MODEL | awk '/Instance Storage/ {print $1; exit}')
  [ -n "$dev" ] || { step "no NVMe instance store found"; return 1; }
  mkfs.ext4 -q -F "$dev" && mkdir -p "$NVME" && mount "$dev" "$NVME" && step "NVMe $dev mounted at $NVME: $(df -h "$NVME" | tail -1)"
}
setup_venv() {
  [ -x "$TV/bin/vllm" ] || { uv venv -q -p 3.12 "$TV" && VIRTUAL_ENV="$TV" uv pip install -q "vllm==$VLLM_VERSION" "huggingface_hub[cli]" "mistral_common>=1.8.6"; } || return 1
  "$TV/bin/python" -c "import vllm, mistral_common; print('teacher vllm', vllm.__version__, 'mistral_common', mistral_common.__version__)" | tee -a "$OUT/job.log"
}
download() {   # $1 teacher -> $NVME/models/$1; gpt-oss skips its duplicate original/ and metal/ copies (130 -> 65 GB)
  local t=$1 d="$NVME/models/$1" extra=()
  [ "$t" = gptoss ] && extra=(--exclude "original/*" "metal/*")
  HF_HOME="$NVME/hf" "$TV/bin/hf" download "$(repo_id "$t")" --local-dir "$d" "${extra[@]}" > "$OUT/$t/download.log" 2>&1 &&
    [ -f "$d/config.json" ] && ls "$d"/*.safetensors > /dev/null 2>&1
}
serve() {   # background, in the job's process group (bootstrap.sh's finish kills it with the job)
  local t=$1
  # shellcheck disable=SC2046
  CUDA_VISIBLE_DEVICES=$(gpus "$t") nohup "$TV/bin/vllm" serve "$NVME/models/$t" --served-model-name "$(served "$t")" \
    --tensor-parallel-size "$(tp "$t")" --gpu-memory-utilization 0.92 $(serve_flags "$t") \
    --host 127.0.0.1 --port "$(vport "$t")" > "$OUT/$t/vllm.log" 2>&1 < /dev/null &
  echo $! > "$OUT/$t/vllm.pid"
}
wait_up() {   # up to 40 min for load + compile; a dead server ends the wait at once
  local t=$1 i
  for i in $(seq 1 240); do
    curl -sf -m 5 "localhost:$(vport "$t")/v1/models" > /dev/null && { step "$t vLLM up after $((i * 10)) s"; return 0; }
    kill -0 "$(cat "$OUT/$t/vllm.pid")" 2> /dev/null || { step "$t vLLM died: $(grep -iE 'error|exception' "$OUT/$t/vllm.log" | tail -1 | cut -c1-200)"; return 1; }
    sleep 10
  done
  step "$t vLLM not up after 40 min"; return 1
}
start_proxy() {   # one real upstream call first (no capture), then the capturing proxy the harness talks to
  local t=$1 i base
  base="http://127.0.0.1:$(vport "$t")/v1"
  "$PY" scripts/or_proxy.py --upstream vllm --base "$base" --model "$(served "$t")" --probe > "$OUT/$t/probe.out" 2>&1 ||
    { step "$t probe FAILED: $(tail -1 "$OUT/$t/probe.out")"; return 1; }
  "$PY" scripts/or_proxy.py --upstream vllm --base "$base" --model "$(served "$t")" --capture "$OUT/capture_$t.jsonl" \
    --max-usd 1000 --port "$(pport "$t")" --log "$OUT/$t/proxy.jsonl" > "$OUT/$t/proxy.out" 2>&1 < /dev/null &
  echo $! > "$OUT/$t/proxy.pid"
  for i in $(seq 1 30); do (echo > "/dev/tcp/127.0.0.1/$(pport "$t")") 2> /dev/null && return 0; sleep 1; done
  step "$t proxy did not open port $(pport "$t") ($i s)"; return 1
}
write_status() {   # what the Mac needs to score: per teacher served/probed/raced and result counts, wall time, EC2 $ estimate
  G1_TEACHERS_OK="${1:-}" "$PY" - "$OUT" "$RATE_USD_H" "$TEACHERS" <<'PY'
import glob, json, os, sys, time
out, rate, teachers = sys.argv[1], float(sys.argv[2]), sys.argv[3].split()
ok = os.environ.get("G1_TEACHERS_OK", "").split()
boot = os.path.getmtime("/opt/g4/out/BOOT") if os.path.exists("/opt/g4/out/BOOT") else None
st = {"ended": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "boot_epoch": boot, "rate_usd_h": rate,
      "ec2_usd_so_far": round((time.time() - boot) / 3600 * rate, 2) if boot else None, "teachers": {}}
for t in teachers:
    rows = [json.loads(l) for f in glob.glob(f"{out}/{t}/items/*/*/task_results.jsonl") for l in open(f) if l.strip()]
    cap = f"{out}/capture_{t}.jsonl"
    st["teachers"][t] = {"ran": t in ok, "results": len(rows), "resolved": sum(1 for r in rows if r.get("resolved")),
                         "capture_rows": sum(1 for _ in open(cap)) if os.path.exists(cap) else 0,
                         "downloaded": os.path.exists(f"{out}/{t}/DOWNLOADED")}
open(f"{out}/status.json", "w").write(json.dumps(st, indent=1))
print(json.dumps(st))
PY
}
cleanup() {
  local f
  for f in "$OUT"/*/proxy.pid "$OUT"/*/vllm.pid; do [ -f "$f" ] && kill "$(cat "$f")" 2> /dev/null; done
  return 0
}

main() {
  local t ok=() pids=() n
  trap cleanup EXIT
  step "G1 START teachers='$TEACHERS' conc=$CONC vllm=$VLLM_VERSION nvme=$NVME"
  n=$(nvidia-smi -L | wc -l); nvidia-smi -L >> "$OUT/job.log"
  [ "$n" -ge 4 ] || { step "FAIL: $n GPUs, the layout needs 4"; exit 1; }
  [ -f "$HARNESS/tasks.jsonl" ] || { step "FAIL: no $HARNESS/tasks.jsonl (python aws/jobs/g1_stage.py --upload)"; exit 1; }
  setup_nvme || { step "FAIL: NVMe"; exit 1; }
  setup_venv || { step "FAIL: teacher vLLM venv"; exit 1; }
  "$PY" aws/jobs/g1_race.py bundle --dest "$SCRATCH" --min 20 --calls 100 > "$OUT/bundle.txt" 2>&1 || { step "FAIL: scratch bundle: $(tail -1 "$OUT/bundle.txt")"; exit 1; }
  step "bundle $(tr '\n' ' ' < "$OUT/bundle.txt")"
  for t in $TEACHERS; do mkdir -p "$OUT/$t"; (download "$t" && touch "$OUT/$t/DOWNLOADED") & done
  wait   # only the downloads run in the background here
  for t in $TEACHERS; do
    if [ -f "$OUT/$t/DOWNLOADED" ]; then step "$t weights: $(du -sh "$NVME/models/$t" | cut -f1)"; serve "$t"; else step "$t download FAILED: $(tail -1 "$OUT/$t/download.log")"; fi
  done
  for t in $TEACHERS; do
    if [ -f "$OUT/$t/DOWNLOADED" ] && wait_up "$t" && start_proxy "$t"; then ok+=("$t"); step "$t READY on proxy :$(pport "$t")"; else step "$t SKIPPED"; fi
  done
  [ ${#ok[@]} -gt 0 ] || { step "FAIL: no teacher came up"; write_status ""; exit 1; }
  for t in "${ok[@]}"; do
    "$PY" aws/jobs/g1_race.py race "$OUT/$t" --bundle "$SCRATCH/$ARM" --harness "$HARNESS" --ids "$IDS" --port "$(pport "$t")" \
      --conc "$CONC" --label "g1-$t" --cpus "$CPUS" > "$OUT/$t/race.out" 2>&1 &
    pids+=("$!"); step "$t race started (pid $!)"
  done
  for n in "${pids[@]}"; do wait "$n" || step "race pid $n exited $?"; done
  write_status "${ok[*]}" > /dev/null
  step "G1 DONE $(tr -d '\n ' < "$OUT/status.json" | cut -c1-400)"
  "$PY" -c "import json,sys; s=json.load(open(sys.argv[1])); sys.exit(0 if any(t['results'] for t in s['teachers'].values()) else 1)" "$OUT/status.json"
}

main "$@"
