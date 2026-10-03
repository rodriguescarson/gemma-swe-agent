#!/usr/bin/env bash
# Wait for <slug>: COMPLETE|FAILED|ERROR in <log>, then summarise eval/kaggle/<slug>/results.jsonl against the two
# references (v4 09-29 and v4h2 10-03) into eval/overnight/<slug>_result.txt. Runs in tmux. 
#   scripts/l4_result_summary.sh <slug> <log>
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
slug=${1:?slug}; log=${2:?log}
until grep -qE "$slug: (KernelWorkerStatus\.)?(COMPLETE|FAILED|ERROR)" "$log" 2>/dev/null; do sleep 60; done
sleep 120
out="eval/overnight/${slug}_result.txt"
{
  echo "$(date '+%Y-%m-%d %H:%M IST') $slug: $(grep -E "$slug: (KernelWorkerStatus\.)?(COMPLETE|FAILED|ERROR)" "$log" | tail -1 | cut -c1-80)"
  f="eval/kaggle/$slug/results.jsonl"
  if [ -s "$f" ]; then
    python3 - "$f" <<'PY'
import json, sys, collections, os
rows = [json.loads(l) for l in open(sys.argv[1])]
solved = sum(bool(r.get("resolved")) for r in rows); crashes = [r for r in rows if r.get("err") and "timeout" not in str(r.get("err")).lower()]
print(f"solved {solved}/{len(rows)}; mean secs {sum(float(r.get('secs') or 0) for r in rows)/max(1,len(rows)):.1f}; non-timeout errors {len(crashes)}; timeouts {sum(1 for r in rows if 'timeout' in str(r.get('err')).lower())}; empty patches {sum(1 for r in rows if not (r.get('patch') or '').strip())}")
print("error classes:", collections.Counter(str(r.get("err"))[:60] for r in crashes).most_common(5))
for name, path in (("v4 09-29", "eval/kaggle/g4-l4-v4/results.jsonl"), ("v4h2 10-03", "eval/kaggle/g4-l4-v4h2-p312/results.jsonl")):
    if os.path.exists(path):
        ref = {json.loads(l)["id"]: json.loads(l)["resolved"] for l in open(path)}
        w = [r["id"] for r in rows if r.get("resolved") and not ref.get(r["id"])]; l = [r["id"] for r in rows if not r.get("resolved") and ref.get(r["id"])]
        print(f"paired vs {name}: only-this {len(w)} {w} | only-ref {len(l)} {l}")
PY
    if [ -s "eval/kaggle/$slug/traces.tar.gz" ]; then
      d=$(mktemp -d /private/tmp/claude-501/l4sum.XXXX); tar -xzf "eval/kaggle/$slug/traces.tar.gz" -C "$d" 2>/dev/null; ln -sf "$PWD/$f" "$d/results.jsonl"
      .venv/bin/python scripts/analyze_failures.py "$d" --tasks data/tasks.jsonl --out "eval/kaggle/$slug/failure_taxonomy.json" 2>/dev/null | sed -n 5,12p
      python3 - "$d" <<'PY'
import json, glob, re, collections, sys
cant = collections.Counter(); ok = collections.Counter()
for f in glob.glob(sys.argv[1] + "/traces/trace_*.json"):
    for s in json.load(open(f))["steps"]:
        obs = str((s.get("observation") or {}).get("content") or "")
        for tc in s.get("tool_calls") or []:
            m = re.search(r"/tmp/swe/(\w+)\.py", str((tc.get("arguments") or {}).get("command") or ""))
            if m: (cant if "can't open file" in obs else ok)[m.group(1)] += 1
print("helper can't-open-file:", dict(cant), "| worked:", dict(ok))
PY
      rm -rf "$d"
    fi
  else echo "no results.jsonl"; ls "eval/kaggle/$slug" 2>/dev/null; fi
} > "$out" 2>&1
echo "$(date -u +%FT%TZ) [$(TZ=Asia/Kolkata date +%H:%M)IST] RESULT $slug: $(sed -n 2p "$out")" >> eval/overnight/progress.log
