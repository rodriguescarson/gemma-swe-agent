#!/usr/bin/env bash
# Keep the Linux-gate pod's heartbeat fresh for as long as process $1 lives (the sub28 chain across its two ships: the second
# ship's Mac suite takes 27-38 min, close to the watchdog's 40-minute idle limit). It dies with that process, so a dead chain
# still leaves the pod to the idle limit. Usage: G4_POD_SSH=<ip>:<port> bash scripts/runpod/keepalive.sh <pid> &
set -o pipefail
parent=${1:?usage: keepalive.sh <pid>}
KEY=${G4_POD_KEY:-$HOME/.ssh/id_ed25519}; KH=${G4_POD_KNOWN_HOSTS:-$HOME/.ssh/known_hosts_runpod}
while kill -0 "$parent" 2>/dev/null; do
  ssh -p "${G4_POD_SSH##*:}" -i "$KEY" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o "UserKnownHostsFile=$KH" \
    -o ConnectTimeout=15 "root@${G4_POD_SSH%:*}" "touch /root/g4m/heartbeat" > /dev/null 2>&1
  sleep "${G4_POD_KEEPALIVE_S:-240}"
done
