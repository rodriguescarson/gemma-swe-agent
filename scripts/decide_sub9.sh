#!/bin/bash
# Pre-registered choice for the 2026-10-03 00:01 UTC slot (Carson, 03 Oct 00:58 IST: "lets not waste the round").
# At DECIDE_AT (IST HHMM) read collection sample 2 (v4h2 on the 159 Pallets training tasks, eval/collect/pallets_v4h2_s2):
#   submit v4h2 (g4agent-v4h2 v1) iff rows >= 80 AND heredoc-as-tool-name crash rows <= 2 AND no other non-timeout crash class
#   else submit v4 (g4agent-sub3 v1) as the new-scorer control.
# Then hands over to submit_at.sh for the next 00:01 UTC. Logs to eval/submit_log.txt and eval/overnight/progress.log.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
DECIDE_AT=${DECIDE_AT:-0525}
until [ "$(TZ=Asia/Kolkata date +%H%M)" -ge "$DECIDE_AT" ]; do sleep 30; done
R=eval/collect/pallets_v4h2_s2/s1/task_results.jsonl
verdict=$(python3 - "$R" <<'PY'
import json, sys, os, collections
p = sys.argv[1]
if not os.path.exists(p): print("v4 no-sample2"); sys.exit()
rows = [json.loads(l) for l in open(p) if l.strip()]
heredoc = sum("Tool 'python3" in str(r.get("error") or "") for r in rows)
other = collections.Counter(str(r.get("error"))[:50] for r in rows if r.get("error") and "timeout" not in str(r["error"]).lower()
                            and "Tool 'python3" not in str(r["error"]) and "tool call budget" not in str(r["error"]))
ok = len(rows) >= 80 and heredoc <= 2 and not other
print(("v4h2" if ok else "v4") + f" rows={len(rows)} heredoc={heredoc} other={dict(other)}")
PY
)
choice=${verdict%% *}
echo "$(date -u) [$(hostname -s)] decide_sub9: $verdict" | tee -a eval/submit_log.txt >> eval/overnight/progress.log
if [ "$choice" = v4h2 ]; then
  KERNEL_VERSION=1 exec bash scripts/submit_at.sh g4agent-v4h2 0001 "sub9: v4h2 = v4 + edit helper + explicit run_command call shape (74 public: 0 crashes; Pallets s2: $verdict)"
else
  KERNEL_VERSION=1 exec bash scripts/submit_at.sh g4agent-sub3 0001 "sub9: v4 control on the rebuilt scorer (v4 0.12 x2 old scorer; v10.1 0.08 x2)"
fi
