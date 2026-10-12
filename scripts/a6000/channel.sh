#!/usr/bin/env bash
# The Mac <-> A6000 box channel through git (docs/a6000/channel/README.md): two append-only files, one per direction, on the
# current branch. Both sides run this script; the side is detected (WSL => box, else mac; CHANNEL_SIDE=mac|box overrides).
#   channel.sh send "<text>" [--re <id>]   # append M-<n> (mac) or B-<n> (box) to this side's file, commit, pull --rebase, push
#   channel.sh read                        # pull; print the other side's messages newer than the last read mark
#   channel.sh wait [secs] [max_min]       # fetch every <secs> (180) until the other side's file changed on origin or max_min
#                                          # (720) passed; then pull and print the new messages. Exit 0 message, 2 time limit.
#   channel.sh pending                     # the other side's message ids this side has not answered (no "re: <id>" of ours)
#   channel.sh tail [n]                    # the last n (3) messages of each file
# Text may be a file: send @path/to/file.md. Never edit the files by hand; never put secrets or the owner's name in them.
set -euo pipefail
ROOT=$(git rev-parse --show-toplevel); cd "$ROOT"
DIR=docs/a6000/channel; BR=$(git rev-parse --abbrev-ref HEAD)
SIDE=${CHANNEL_SIDE:-}
if [ -z "$SIDE" ]; then if grep -qi microsoft /proc/version 2>/dev/null || [ -d /mnt/c ]; then SIDE=box; else SIDE=mac; fi; fi
if [ "$SIDE" = mac ]; then MINE=$DIR/mac_to_box.md; THEIRS=$DIR/box_to_mac.md; TAG=M; else MINE=$DIR/box_to_mac.md; THEIRS=$DIR/mac_to_box.md; TAG=B; fi
MARK=$(git rev-parse --git-dir)/channel_read_$SIDE
now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
sync() { git pull -q --rebase --autostash origin "$BR"; }
new_since_mark() {                                   # THEIRS is append-only: print the lines after the last read mark, advance it
  local n=0; [ -f "$MARK" ] && n=$(cat "$MARK")
  tail -n +"$((n + 1))" "$THEIRS"
  wc -l < "$THEIRS" | tr -d ' ' > "$MARK"
}
cmd=${1:-}; shift || true
case "$cmd" in
  send)
    text=${1:?text}; shift || true
    case "$text" in @*) text=$(cat "${text#@}") ;; esac
    re=""; if [ "${1:-}" = --re ]; then re=${2:?id}; fi
    sync
    n=$(grep -c "^### $TAG-" "$MINE" || true); id=$(printf '%s-%03d' "$TAG" "$((n + 1))")
    { printf '\n### %s | %s%s\n' "$id" "$(now)" "${re:+ | re: $re}"; printf '%s\n' "$text"; } >> "$MINE"
    git add "$MINE"; git commit -q -m "channel: $id${re:+ re $re}"; sync; git push -q origin "$BR"
    echo "$id sent" ;;
  read) sync; new_since_mark ;;
  wait)
    every=${1:-180}; max=${2:-720}; t0=$(date +%s)
    while :; do
      git fetch -q origin "$BR"
      if ! git diff --quiet HEAD "origin/$BR" -- "$THEIRS"; then sync; new_since_mark; exit 0; fi
      if [ $(( ($(date +%s) - t0) / 60 )) -ge "$max" ]; then echo "no message in $max min"; exit 2; fi
      sleep "$every"
    done ;;
  pending)
    sync
    for id in $(grep -o "^### [MB]-[0-9]*" "$THEIRS" | awk '{print $2}'); do grep -qE "re: $id( |$)" "$MINE" || echo "$id"; done ;;
  tail)
    n=${1:-3}
    for f in "$DIR/mac_to_box.md" "$DIR/box_to_mac.md"; do
      echo "== $f"; python3 - "$f" "$n" <<'PY'
import re, sys
parts = re.split(r"(?m)^(?=### )", open(sys.argv[1]).read())
print("".join(parts[-int(sys.argv[2]):]).rstrip() if len(parts) > 1 else "(no messages)")
PY
    done ;;
  *) sed -n '2,10p' "$0"; exit 1 ;;
esac
