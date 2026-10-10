#!/usr/bin/env bash
# The A6000 training launcher (plan ~/.claude/plans/nifty-sleeping-liskov.md; docs/a6000/TRAIN_LOCAL.md). Everything under ~/g4;
# the GPU must be idle (vLLM and the supervisor down): training and serving never overlap on this one card.
#
#   bash scripts/a6000/train.sh env                       # build ~/g4/train-venv (scripts/a6000/train_env.sh)
#   bash scripts/a6000/train.sh dequant                   # ~/g4/model (W4A16) -> ~/g4/model-bf16 (train/dequant_ct.py, ~10 min, 63 GB)
#   bash scripts/a6000/train.sh stitch  <p3_out> <name>   # <p3_out>/rows.jsonl -> ~/g4/runs/train_<name>/{seqs,holdout,seqs_probe}.jsonl + validation
#   bash scripts/a6000/train.sh probe   <name>            # the 1-hour feasibility probe (background; tail its log)
#   bash scripts/a6000/train.sh full    <name> [args...]  # the run (background, resumable: run again with the same name)
#   bash scripts/a6000/train.sh status  <name>            # last log lines, cursor, GPU
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); ROOT=$(cd "$HERE/../.." && pwd)
VENV=${TRAIN_VENV:-$HOME/g4/train-venv}; PY="$VENV/bin/python"
MODEL=${MODEL_DIR:-$HOME/g4/model}; BF16=${BF16_DIR:-$HOME/g4/model-bf16}
PATH=$(echo "$PATH" | tr ':' '\n' | grep -v '^/mnt/' | paste -sd: -); export PATH
unset PYTORCH_CUDA_ALLOC_CONF
export TOKENIZERS_PARALLELISM=false

gpu_idle() {
  if pgrep -af "autopilot.py|vllm|or_proxy|pace_proxy|p2_race|qlora_train" | grep -v "$$" | grep -q .; then echo "REFUSED: a serving/supervisor/training process is alive:"; pgrep -af "autopilot.py|vllm|or_proxy|pace_proxy|p2_race|qlora_train" | grep -v "$$"; return 1; fi
  used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1 | tr -d ' ')
  if [ "${used:-0}" -gt 1024 ]; then echo "REFUSED: nvidia-smi shows ${used} MiB used with no process of ours (stale WSL VRAM: wsl --shutdown from Windows, reopen, retry)"; return 1; fi
  if (echo > /dev/tcp/127.0.0.1/8000) 2>/dev/null; then echo "REFUSED: port 8000 answers (vLLM up)"; return 1; fi
  return 0
}

cmd=${1:-}; shift || true
case "$cmd" in
  env) bash "$HERE/train_env.sh" "$VENV" ;;
  dequant)
    [ -x "$PY" ] || { echo "no train venv at $VENV: run train.sh env"; exit 2; }
    [ -f "$BF16/DEQUANT.json" ] && { echo "already there: $BF16"; cat "$BF16/DEQUANT.json"; exit 0; }
    "$PY" "$ROOT/train/dequant_ct.py" "$MODEL" --out "$BF16" --check 3 ;;
  stitch)
    P3=${1:?p3_out}; NAME=${2:?name}; shift 2; RUN="$HOME/g4/runs/train_$NAME"; mkdir -p "$RUN"     # extra args go to train/stitch_rows.py (e.g. --max-seqs-per-task-stage 6)
    TOK="$MODEL/tokenizer.json"; [ -f "$TOK" ] || TOK="$ROOT/adapters/v11b/tokenizer.json"
    "$PY" "$ROOT/train/stitch_rows.py" "$P3/rows.jsonl" --out "$RUN/seqs.jsonl" --report "$RUN/stitch_report.json" --tokenizer-json "$TOK" \
      --holdout-tasks "$ROOT/data/v11/v11b_holdout_tasks.txt" --holdout-out "$RUN/holdout.jsonl" --holdout-auto 5 --max-tokens 14336 "$@"
    # the probe's copy keeps sequences up to 16,384 tokens so the top memory bucket exists
    HOLD="$ROOT/data/v11/v11b_holdout_tasks.txt"; [ -f "$RUN/seqs.jsonl.holdout_tasks.txt" ] && HOLD="$RUN/seqs.jsonl.holdout_tasks.txt"
    "$PY" "$ROOT/train/stitch_rows.py" "$P3/rows.jsonl" --out "$RUN/seqs_probe.jsonl" --report "$RUN/stitch_probe_report.json" --tokenizer-json "$TOK" \
      --holdout-tasks "$HOLD" --max-tokens 16384 "$@" >/dev/null
    "$PY" "$ROOT/train/validate_rows.py" --stitched "$RUN/seqs.jsonl" --min-rows 500 --max-tokens 14336 --no-tokenizer --require-thought --report "$RUN/validate_stitched.json" \
      --exclude-ids "$ROOT/data/heldout1k/sample200_ids.txt" --exclude-ids "$ROOT/data/heldout1k/s200_valid_ids.txt" | tail -12 ;;
  probe|full)
    NAME=${1:?name}; shift || true; RUN="$HOME/g4/runs/train_$NAME"; mkdir -p "$RUN"
    [ -x "$PY" ] || { echo "no train venv at $VENV: run train.sh env"; exit 2; }
    [ -f "$BF16/DEQUANT.json" ] || { echo "no dequantised base at $BF16: run train.sh dequant"; exit 2; }
    [ -f "$RUN/seqs.jsonl" ] || { echo "no $RUN/seqs.jsonl: run train.sh stitch <p3_out> $NAME"; exit 2; }
    gpu_idle || exit 3
    if [ "$cmd" = probe ]; then
      OUT="$RUN/probe"; ARGS=(--probe --seqs "$RUN/seqs_probe.jsonl" --holdout "$RUN/holdout.jsonl" --max-tokens 16384)
    else
      OUT="$RUN/run"; ARGS=(--seqs "$RUN/seqs.jsonl" --holdout "$RUN/holdout.jsonl" --max-tokens 14336 --resume)
    fi
    mkdir -p "$OUT"; LOG="$OUT/train.out"
    echo "$PY $ROOT/train/qlora_train.py ${ARGS[*]} --base $BF16 --out $OUT $*" > "$OUT/CMD"
    cd "$ROOT" && setsid nohup "$PY" "$ROOT/train/qlora_train.py" "${ARGS[@]}" --base "$BF16" --out "$OUT" "$@" >> "$LOG" 2>&1 < /dev/null &
    echo $! > "$OUT/PID"; disown || true
    echo "started $cmd $NAME pid $(cat "$OUT/PID"); log: tail -f $LOG; status: bash scripts/a6000/train.sh status $NAME" ;;
  status)
    NAME=${1:?name}; RUN="$HOME/g4/runs/train_$NAME"
    for d in probe run; do [ -d "$RUN/$d" ] || continue; echo "== $d (pid $(cat "$RUN/$d/PID" 2>/dev/null || echo -), alive: $(pgrep -f "qlora_train.py.*$RUN/$d" >/dev/null && echo yes || echo no))"
      [ -f "$RUN/$d/cursor.json" ] && cat "$RUN/$d/cursor.json" && echo; [ -f "$RUN/$d/probe_report.json" ] && grep -E '"verdict"|"tok_s"|"peak' "$RUN/$d/probe_report.json"
      tail -5 "$RUN/$d/train.out" 2>/dev/null; done
    nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader ;;
  *) sed -n 2,12p "$0"; exit 2 ;;
esac
