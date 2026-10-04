#!/usr/bin/env bash
# Retry scripts/kaggle_push_wait.sh while Kaggle refuses the push for the account's 2-GPU-session cap; any other
# outcome ends the loop (tests/test_kaggle_push_retry.py). [RETRY_S=600] [RETRY_MAX=0=forever] [PUSH_WAIT_SH=...]
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
slug=${1:?slug}; PUSH=${PUSH_WAIT_SH:-scripts/kaggle_push_wait.sh}; n=0
while :; do
  n=$((n + 1)); out=$(bash "$PUSH" "$slug" 2>&1); st=$?
  echo "$out"
  if [ $st -ne 0 ] && echo "$out" | grep -qE "Maximum batch GPU session count|Maximum weekly GPU quota"; then
    echo "$(date -u) $slug: GPU session cap or weekly quota reached (attempt $n); retry in ${RETRY_S:-600}s"
    if [ "${RETRY_MAX:-0}" -gt 0 ] && [ "$n" -ge "${RETRY_MAX:-0}" ]; then exit 1; fi
    sleep "${RETRY_S:-600}"; continue
  fi
  exit $st
done
