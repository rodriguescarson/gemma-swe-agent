#!/usr/bin/env bash
# Coverage loop (Carson, 2026-10-03 04:35 IST: "24/159 should increase to 159/159, run parallel agents and stitch this,
# while keeping track of disk size"). Rounds of TWO concurrent passes with different licence-clean models over the tasks
# no pass has solved yet; all solved trajectories are stitched by train/build_sft.py (success-only, per-pass verdicts).
# Tasks the pre-flight proves unsolvable in our environment are excluded from the target. Disk is logged before every
# pass and a pass waits while free space is under MIN_FREE_GB; scripts/collect/watchdog.sh still kills containers under 3 GB.
#
#   [MAX_ROUNDS=4] [MIN_FREE_GB=6] [TARGET_IDS=data/pallets/train_ids.txt] scripts/collect/coverage.sh
# Log: eval/collect/coverage.log. Stitched rows: data/v11/rows_stitched.jsonl (+ validation report).
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
LOG=eval/collect/coverage.log; export TARGET_IDS=${TARGET_IDS:-data/pallets/train_ids.txt}
step() { echo "$(date -u +%FT%TZ) [$(TZ=Asia/Kolkata date +%H:%M)IST] $*" | tee -a "$LOG"; }
free_gb() { df -g /System/Volumes/Data | awk 'NR==2{print $4}'; }
# bundle|model|provider. Open-weight, permissive licences only (Apache-2.0 / MIT / modified MIT); Gemma for on-policy data.
# 2026-10-03 09:12 IST: openai/gpt-oss-120b dropped: 8 of 179 tool calls carried malformed JSON arguments ('"]' glitch) and
# ADK's json.loads ends the task on the first one (0 of 8 tasks solved). Gemma appears twice: on-policy data is what the
# LoRA needs most, and sampling at the bundle temperature gives a new attempt per pass.
# 10:10 IST: deepseek-v4-pro dropped too: 11 of 12 finished tasks timed out in the locator (completion p50 118 tokens
# under L4 pacing). Rotation = the two teachers that produce patches in 5 min (kimi untested, qwen 14 solved on 10-02) + Gemma.
MODELS=("v4h2|moonshotai/kimi-k2.6|any" "v4h2|qwen/qwen3-coder|any" "v4h2|google/gemma-4-31b-it|parasail/fp8"
        "v4h2|moonshotai/kimi-k2.6|any" "v4h2|google/gemma-4-31b-it|parasail/fp8" "v4h2|qwen/qwen3-coder|any")
remaining() {   # stdout: remaining ids; stderr: the COVERAGE line
  python3 - <<'PY'
import json, glob, os, sys
target = open(os.environ["TARGET_IDS"]).read().split()
harness = set(open("data/pallets/harness_train/ids.txt").read().split())
solved = set()
for f in glob.glob("eval/collect/*/s1/task_results.jsonl"):
    for l in open(f):
        if l.strip():
            r = json.loads(l)
            if str(r.get("resolved")) == "True":
                solved.add(r["instance_id"])
invalid = set()
if os.path.exists("eval/preflight/train159/invalid.txt"):
    invalid = {l.split("\t")[0] for l in open("eval/preflight/train159/invalid.txt") if l.strip()}
pool = [t for t in target if t in harness]
rem = [t for t in pool if t not in solved and t not in invalid]
print(" ".join(rem))
print(f"COVERAGE solved={len(solved & set(pool))}/{len(pool)} invalid={len(invalid & set(pool))} remaining={len(rem)}", file=sys.stderr)
PY
}
step "coverage start (free $(free_gb)GB)"
# 0. let the passes already running finish (no emulation container left)
until [ "$(docker ps -q --filter ancestor=g4-pallets-linux:local | wc -l | tr -d ' ')" = 0 ]; do sleep 120; done
# 1. pre-flight of the target, alone, if not done
if [ ! -s eval/preflight/train159/report.txt ]; then
  step "preflight start (free $(free_gb)GB)"; rm -rf eval/preflight/train159
  CONC=4 HARNESS=data/pallets/harness_train bash scripts/collect/preflight.sh "$TARGET_IDS" train159 > eval/preflight_train159.out 2>&1
  step "preflight: $(head -1 eval/preflight/train159/report.txt 2>/dev/null || echo FAILED)"
fi
# 2. rounds of two concurrent passes
for round in $(seq 1 "${MAX_ROUNDS:-4}"); do
  rem=$(remaining 2>>"$LOG"); n=$(echo "$rem" | wc -w | tr -d ' ')
  step "round $round: $n tasks remaining (free $(free_gb)GB)"
  [ "$n" = 0 ] && break
  while [ "$(free_gb)" -lt "${MIN_FREE_GB:-6}" ]; do step "waiting for disk: $(free_gb)GB free"; sleep 300; done
  echo "$rem" | tr ' ' '\n' > "eval/collect/cov_r${round}_ids.txt"
  i=$(( (round - 1) * 2 )); A=${MODELS[$(( i % ${#MODELS[@]} ))]}; B=${MODELS[$(( (i + 1) % ${#MODELS[@]} ))]}
  for slot in A B; do
    spec=${!slot}; bundle=${spec%%|*}; rest=${spec#*|}; model=${rest%%|*}; prov=${rest#*|}
    tag="cov_r${round}_${slot}_$(echo "$model" | tr '/.:' '___')"; port=8794; [ "$slot" = B ] && port=8795
    step "round $round slot $slot: $bundle via $model ($prov) -> $tag (free $(free_gb)GB)"
    SAMPLES=1 CONC=4 MAX_USD=${PASS_USD:-10} PORT=$port MODEL=$model PROVIDER=$prov HARNESS=data/pallets/harness_train \
      bash scripts/collect/collect.sh "$bundle" "eval/collect/cov_r${round}_ids.txt" "$tag" > "eval/collect/$tag.out" 2>&1 &
    sleep 90
  done
  wait
  step "round $round done: $(remaining 2>&1 >/dev/null) (free $(free_gb)GB)"
done
# 3. stitch every pass, all samples (scripts/collect/stitch.sh: pairs.py + build_sft + validate_rows)
bash scripts/collect/stitch.sh
step "COVERAGE DONE: $(remaining 2>&1 >/dev/null) (free $(free_gb)GB)"
