#!/usr/bin/env bash
# Stop running eval chains/lanes. Patterns are anchored to the start of the command line, so they can never match
# the ssh shell that invokes this script (an unanchored `pgrep -f <pattern>` killed its own caller twice).
for pat in '^bash pod/chain_' '^bash pod/run_eval.sh' '^python scripts/run_eval.py'; do
  for p in $(pgrep -f "$pat"); do [ "$p" != "$$" ] && kill "$p" 2>/dev/null; done
done
sleep 2; pgrep -fa '^(bash pod/|python scripts/run_eval)' || echo "no eval processes"
