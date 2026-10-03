#!/usr/bin/env bash
# Refuse to start a collection pass when the Mac is under MIN_FREE_GB (E7, docs/PLAN_TO_FINISH.txt;
# tests/test_coverage_disk.py). Exit 0 when free >= MIN_FREE_GB, 3 otherwise. The watchdog (scripts/collect/watchdog.sh)
# still kills containers under 3 GB; this guard keeps a pass from starting into that.
set -uo pipefail
MIN=${MIN_FREE_GB:-6}
free=$(df -g /System/Volumes/Data 2>/dev/null | awk 'NR==2{print $4}')
[ -n "$free" ] || free=$(df -g / | awk 'NR==2{print $4}')
if [ "$free" -lt "$MIN" ]; then echo "disk: ${free}GB free, below MIN_FREE_GB=$MIN; not starting"; exit 3; fi
echo "disk: ${free}GB free (min $MIN)"
