#!/usr/bin/env bash
# G1 autorun (Carson, 2026-10-24: "run everything ... strictly don't wait for me"). A launchd agent runs one `tick` every
# 10 minutes, so the pilot launches as soon as AWS grants the G-family quota, with or without an open Claude session, and
# the results are fetched and scored once the box has terminated itself. Each tick is short and idempotent:
#   not launched:     quota >= 48 vCPU (on-demand; spot only if only spot is granted) -> aws/launch.py teacher --hours 3.75
#                     --max-usd 40 ... --yes, trying each AZ on a capacity error; at most once
#   launched, live:   nothing (the box ends itself: job done or its 3.75 h timer); alarm if it outlives launch + 5 h
#   launched, gone:   s3 RUN/out -> eval/aws/g1, scripts/distill/usable.py per teacher -> DONE; the agent removes itself
#   past the deadline without a launch, or 3 non-capacity launch failures: the agent removes itself
#
#   bash aws/jobs/g1_autorun.sh install [hours]   # load the agent (deadline default 72 h)
#   bash aws/jobs/g1_autorun.sh status            # state, last log lines, the agent
#   bash aws/jobs/g1_autorun.sh uninstall         # stop: remove the agent (never touches an instance)
#   bash aws/jobs/g1_autorun.sh tick              # what the agent runs
# State and log: ~/.local/state/g4-g1-autorun/. Keys stay in-process (aws/g4aws.py reads ~/Projects/.env).
set -uo pipefail
REPO=$(cd "$(dirname "$0")/../.." && pwd)
STATE=${G1A_STATE:-$HOME/.local/state/g4-g1-autorun}; PY=${G1A_PY:-$REPO/.venv/bin/python}
LAUNCHCTL=${G1A_LAUNCHCTL:-launchctl}; LABEL=com.carson.g4-g1-autorun; PLIST=${G1A_PLIST:-$HOME/Library/LaunchAgents/$LABEL.plist}
DEST=${G1A_DEST:-$REPO/eval/aws/g1}; RATE_USD_H=10.54   # g6e.12xlarge on-demand + EBS + IPv4: an upper bound for spot too
mkdir -p "$STATE"; LOG=$STATE/log
export PYTHONDONTWRITEBYTECODE=1
cd "$REPO" || exit 2

say() { echo "$(TZ=Asia/Kolkata date '+%F %H:%M IST') $*" >> "$LOG"; }
notify() {
  say "NOTIFY $*"
  [ "${G1A_NOTIFY:-1}" = 1 ] && command -v osascript > /dev/null && osascript -e "display notification \"$*\" with title \"G1 autorun\"" > /dev/null 2>&1
  return 0
}
remove_agent() {   # the plist first, launchctl last: booting out the running job ends this very process
  say "removing the agent ($*)"
  rm -f "$PLIST"; rmdir "$STATE/lock" 2> /dev/null
  "$LAUNCHCTL" bootout "gui/$(id -u)/$LABEL" > /dev/null 2>&1
  return 0
}
run_uri() {
  [ -s "$STATE/run" ] || "$PY" -c "import sys; sys.path.insert(0,'aws'); import g4aws; print('s3://gemma4-agent-' + g4aws.session().client('sts').get_caller_identity()['Account'] + '/runs/g1')" > "$STATE/run" 2>> "$LOG" || { rm -f "$STATE/run"; return 1; }
  cat "$STATE/run"
}
quota() { "$PY" -c "import sys; sys.path.insert(0,'aws'); import g4aws; print(int(g4aws.session().client('service-quotas').get_service_quota(ServiceCode='ec2', QuotaCode='$1')['Quota']['Value']))" 2> /dev/null || echo -1; }
instance_state() { "$PY" aws/status.py --all --json 2> /dev/null | "$PY" -c "import json,sys; r=[x for x in json.load(sys.stdin) if x['id']==sys.argv[1]]; print(r[0]['state'] if r else 'gone')" "$1" 2> /dev/null || echo unknown; }

try_launch() {
  local q qs mkt="" az out iid run
  run=$(run_uri) || { say "cannot resolve the run prefix (network?); next tick"; return 0; }
  q=$(quota L-DB2E81BA); qs=$(quota L-3819A6DF)
  echo "$(date -u +%FT%TZ) on-demand=$q spot=$qs" > "$STATE/last_check"
  if [ "$q" -lt 48 ] && [ "$qs" -lt 48 ]; then return 0; fi
  if [ "$q" -lt 48 ]; then mkt=--spot; fi   # only spot granted: spot, its price capped at the on-demand price
  say "quota granted (on-demand $q, spot $qs vCPU); launching ${mkt:-on-demand}"
  for az in auto us-east-1a us-east-1b us-east-1c us-east-1d; do
    out=$("$PY" aws/launch.py teacher --hours 3.75 --max-usd 40 --run "$run" --job 'bash aws/jobs/g1_teacher.sh' --az "$az" ${mkt:+"$mkt"} --yes 2>&1)
    echo "$out" | sed -E 's/[0-9]{12}/<acct>/g' >> "$LOG"
    iid=$(echo "$out" | sed -n 's/^LAUNCHED \(i-[0-9a-f]*\).*/\1/p')
    if [ -n "$iid" ]; then
      echo "$iid $az $(date +%s)" > "$STATE/launched"; rm -f "$STATE/failures"
      notify "G1 pilot launched: $iid ($az, ${mkt:-on-demand}); it stops itself within 3.75 h"; return 0
    fi
    if ! echo "$out" | grep -q "InsufficientInstanceCapacity\|Unsupported\|MaxSpotInstanceCountExceeded\|SpotMaxPriceTooLow\|InsufficientCapacity"; then
      n=$(( $(cat "$STATE/failures" 2> /dev/null || echo 0) + 1 )); echo "$n" > "$STATE/failures"
      say "launch refused, not a capacity error (failure $n of 3)"
      [ "$n" -ge 3 ] && { notify "G1 launch refused 3 times; autorun stopped, see $LOG"; remove_agent "3 launch failures"; }
      return 0
    fi
    say "no capacity in $az"
  done
  return 0
}

finish_run() {   # the box is gone: fetch, score, done
  local iid t0 usd run t
  read -r iid _ t0 < "$STATE/launched"; run=$(run_uri) || return 0
  "$PY" aws/stage.py fetch "$run" "$DEST" >> "$LOG" 2>&1 || { say "fetch failed; next tick retries"; return 0; }
  usd=$("$PY" -c "import glob,sys,time,os
ends=[os.path.getmtime(f) for f in glob.glob(sys.argv[1] + '/box/*/RESULT')]
end=max(ends) if ends else time.time()
print(round((end - float(sys.argv[2])) / 3600 * float(sys.argv[3]), 2))" "$DEST" "$t0" "$RATE_USD_H")
  say "$iid gone; EC2 upper bound \$$usd (launch to RESULT at \$$RATE_USD_H/h)"
  for t in devstral gptoss; do
    if [ -s "$DEST/keep/eval/g1/capture_$t.jsonl" ]; then
      "$PY" scripts/distill/usable.py --capture "$DEST/keep/eval/g1/capture_$t.jsonl" --results "$DEST/keep/eval/g1/$t/items/*/*/task_results.jsonl" \
        --ids data/distill/g1_ids.txt --ec2-usd "$usd" --out "$DEST/usable_$t.json" >> "$LOG" 2>&1 || say "usable.py failed for $t"
    else
      say "$t: no capture (it did not run; see $DEST/keep/eval/g1/job.log)"
    fi
  done
  date -u +%FT%TZ > "$STATE/DONE"
  notify "G1 pilot finished: results and usable_*.json in eval/aws/g1"
  remove_agent "done"
}

tick() {
  if ! mkdir "$STATE/lock" 2> /dev/null; then   # another tick is running, unless its lock is stale (> 30 min)
    [ -n "$(find "$STATE/lock" -maxdepth 0 -mmin +30 2> /dev/null)" ] && rmdir "$STATE/lock" 2> /dev/null
    return 0
  fi
  trap 'rmdir "$STATE/lock" 2> /dev/null' EXIT
  if [ -f "$STATE/DONE" ]; then remove_agent "already done"; return 0; fi
  if [ ! -f "$STATE/launched" ]; then
    if [ "$(date +%s)" -ge "$(cat "$STATE/deadline" 2> /dev/null || echo 0)" ]; then
      notify "G1 autorun deadline passed without a GPU quota; nothing was launched"; remove_agent "deadline"; return 0
    fi
    try_launch; return 0
  fi
  local iid _az t0 s
  read -r iid _az t0 < "$STATE/launched"; s=$(instance_state "$iid")
  echo "$(date -u +%FT%TZ) $iid $s" > "$STATE/last_check"
  case $s in
    terminated|gone) finish_run ;;
    unknown) say "could not read $iid's state (network?); next tick" ;;
    *) if [ $(( $(date +%s) - t0 )) -gt 18000 ] && [ ! -f "$STATE/alarmed" ]; then
         touch "$STATE/alarmed"; notify "ALERT: $iid still $s 5 h after launch (timer 3.75 h); check python aws/status.py"
       fi ;;
  esac
}

install_agent() {
  local hours=${1:-72}
  echo $(( $(date +%s) + hours * 3600 )) > "$STATE/deadline"; rm -f "$STATE/DONE" "$STATE/failures"
  mkdir -p "$(dirname "$PLIST")"
  cat > "$PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$REPO/aws/jobs/g1_autorun.sh</string><string>tick</string></array>
  <key>StartInterval</key><integer>600</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$STATE/agent.out</string>
  <key>StandardErrorPath</key><string>$STATE/agent.err</string>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>/usr/bin:/bin:/usr/sbin:/sbin</string><key>HOME</key><string>$HOME</string></dict>
</dict></plist>
EOF
  "$LAUNCHCTL" bootout "gui/$(id -u)/$LABEL" > /dev/null 2>&1
  "$LAUNCHCTL" bootstrap "gui/$(id -u)" "$PLIST" || { echo "launchctl bootstrap failed"; return 1; }
  say "agent installed; deadline $(TZ=Asia/Kolkata date -r "$(cat "$STATE/deadline")" '+%F %H:%M IST')"
  echo "installed $LABEL; deadline $(TZ=Asia/Kolkata date -r "$(cat "$STATE/deadline")" '+%F %H:%M IST'); log $LOG"
}

case "${1:-}" in
  tick) tick ;;
  install) install_agent "${2:-72}" ;;
  uninstall) rm -f "$PLIST"; "$LAUNCHCTL" bootout "gui/$(id -u)/$LABEL" > /dev/null 2>&1; say "agent removed by hand"; echo "removed" ;;
  status)
    for f in deadline launched last_check failures DONE alarmed; do [ -f "$STATE/$f" ] && echo "$f: $(cat "$STATE/$f")"; done
    tail -8 "$LOG" 2> /dev/null
    "$LAUNCHCTL" print "gui/$(id -u)/$LABEL" 2> /dev/null | grep -E "state =|runs =|last exit" || echo "agent not loaded" ;;
  *) sed -n 2,17p "$0"; exit 2 ;;
esac
