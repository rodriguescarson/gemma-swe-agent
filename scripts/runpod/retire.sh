#!/usr/bin/env bash
# Retire the Linux-gate pod: its watchdog (scripts/runpod/pod_watchdog.py) terminates it once /root/g4m/terminate_now exists.
# Usage: G4_POD_SSH=<ip>:<port> bash scripts/runpod/retire.sh
# It prints the watchdog log, then waits up to G4_POD_RETIRE_WAIT seconds (default 300) for ssh to stop answering. Only the
# RunPod API (MCP get-pod returning 404) proves the pod is gone, and this Mac has no API key, so the last line says what was
# seen; the idle and hard limits stay the backstop.
set -o pipefail
[ -n "${G4_POD_SSH:-}" ] || { echo "retire.sh: G4_POD_SSH (ip:port) is not set" >&2; exit 2; }
KEY=${G4_POD_KEY:-$HOME/.ssh/id_ed25519}; KH=${G4_POD_KNOWN_HOSTS:-$HOME/.ssh/known_hosts_runpod}
SSH=(ssh -p "${G4_POD_SSH##*:}" -i "$KEY" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o "UserKnownHostsFile=$KH"
     -o ConnectTimeout=15 "root@${G4_POD_SSH%:*}")
"${SSH[@]}" "rm -f /root/g4m/busy; touch /root/g4m/terminate_now" || { echo "retire.sh: could not reach the pod (already gone?)"; exit 0; }
echo "retire.sh: $(date -u) terminate_now set on ${G4_POD_SSH}"
end=$(( $(date +%s) + ${G4_POD_RETIRE_WAIT:-300} ))
while [ "$(date +%s)" -lt "$end" ]; do
  sleep 20
  if ! log=$("${SSH[@]}" "tail -4 /root/g4m/watchdog.log" 2>/dev/null); then
    echo "retire.sh: $(date -u) ssh no longer answers: the watchdog's call went through (confirm with get-pod)"; exit 0
  fi
done
echo "retire.sh: $(date -u) pod still answers after ${G4_POD_RETIRE_WAIT:-300} s; watchdog log:"; echo "$log"; exit 1
