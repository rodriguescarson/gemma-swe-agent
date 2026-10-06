#!/usr/bin/env bash
# Restart the autopilot supervisor without touching its children (it adopts the running step and proxy). Kept in a file so that the pattern below
# is not part of the invoking shell's own command line (an inline `pkill -f` kills the caller).
set -u
cd "$(dirname "$0")/../.."
old=$(pgrep -f "[a]utopilot.py" || true)
[ -n "$old" ] && kill $old
sleep 2
setsid nohup "$HOME/g4/venv/bin/python" scripts/a6000/autopilot.py >> "$HOME/g4/autopilot.log" 2>&1 < /dev/null &
sleep 20
tail -n 2 "$HOME/g4/autopilot.log" | cut -c1-140
