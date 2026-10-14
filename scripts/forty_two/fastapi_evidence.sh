#!/bin/bash
# Regenerate the offline evidence behind docs/forty_two/queue/fastapi_*.json (run from the repo root; about 2 minutes):
#   docs/forty_two/evidence/fastapi_check_replay.txt  issue-derived checks on base, every box patch, L4 solves, gold
#   docs/forty_two/evidence/fastapi_census.txt        where the levers fire in recorded traces, text-call leaks, greps
# Reads committed traces and the read-only task snapshots in ~/.cache/g4/ws; every python run goes through bounded.py.
set -u
PY=/Users/carson/Projects/gemma-swe-agent/.venv/bin/python
B="$PY $PWD/scripts/forty_two/bounded.py --mb 1500 --secs 120 --"
R=eval/a6000/results
IDS="fastapi_14616 fastapi_9753 fastapi_14419 fastapi_14448 fastapi_14986 fastapi_13920"

OUT=docs/forty_two/evidence/fastapi_check_replay.txt
{
  echo "# scripts/forty_two/check_replay.py for the six feasible fastapi tasks of the 42 ($(date '+%Y-%m-%d %H:%M IST'))."
  echo "# Each check is docs/forty_two/evidence/fastapi_checks/<id>.py, written from the issue text alone. GREEN = exit 0."
  for t in $IDS; do
    echo; echo "== $t"
    $PY scripts/forty_two/bounded.py --mb 3000 --secs 400 -- $PY scripts/forty_two/check_replay.py $t docs/forty_two/evidence/fastapi_checks/$t.py
  done
} > $OUT 2>&1
echo "wrote $OUT"

SOLVED=$($PY -c "import json; print(','.join(json.loads(l)['id'] for l in open('$R/p4_b1024/results.jsonl') if l.strip() and json.loads(l)['resolved']))")
OUT=docs/forty_two/evidence/fastapi_census.txt
{
  echo "# $(date '+%Y-%m-%d %H:%M IST'). Offline, committed traces and snapshots only. Regenerate: bash scripts/forty_two/fastapi_evidence.sh"
  echo
  echo "## 1. Where a red-first rule fires (thinking-on single-agent line; the older pipelines edit through helper scripts the census does not parse)"
  echo "\$ python scripts/forty_two/check_census.py $R/p4_b1024 $R/p4_v0t2 --ids <the six>"
  $B $PY scripts/forty_two/check_census.py $R/p4_b1024 $R/p4_v0t2 --ids ${IDS// /,}
  echo
  echo "## 2. Solved on p4_b1024: the tasks a red-first rule would add a step to (no failing check before the first source edit)"
  $B $PY scripts/forty_two/check_census.py $R/p4_b1024 --ids "$SOLVED" | grep -v "(red [1-9]" | tail -n +4
  echo
  echo "## 3. Tool calls written as text (Gemma native syntax in the message, no parsed call), all six box runs"
  echo "\$ python scripts/forty_two/text_call_leaks.py $R/{p4,p4_v7,p4_v7c,p4_v7d,p4_b1024,p4_v0t2}"
  $B $PY scripts/forty_two/text_call_leaks.py $R/p4 $R/p4_v7 $R/p4_v7c $R/p4_v7d $R/p4_b1024 $R/p4_v0t2
  echo
  echo "## 4. grepsites on fastapi_9753: every site of the expression the wrong-location runs changed, in the base snapshot"
  echo "\$ grep -rn 'inspect.unwrap(' ~/.cache/g4/ws/fastapi_9753/base/fastapi   (*.py)"
  grep -rn "inspect.unwrap(" "--include=*.py" ~/.cache/g4/ws/fastapi_9753/base/fastapi | sed "s#$HOME/.cache/g4/ws/fastapi_9753/base/##"
  echo "Gold site: fastapi/dependencies/models.py (Dependant._unwrapped_call). Runs that edited only the utils.py sites (box traces):"
  for r in p4 p4_v7 p4_v7c; do
    $PY - "$R/$r/results/traces/trace_fastapi_9753.json" "$r" <<'EOF'
import json, re, sys
d = json.load(open(sys.argv[1])); edits = []; sub = None
for s in d["steps"]:
    if s["source"] != "agent":
        continue
    for tc in s.get("tool_calls") or []:
        t = (tc.get("extra") or {}).get("elapsed_s") or 0
        c = (tc.get("arguments") or {}).get("command", "")
        if "edit.py fastapi/" in c:
            edits.append((round(t), re.search(r"edit.py (\S+)", c).group(1)))
        if tc.get("function_name") == "submit_patch":
            sub = round(t)
print(f"  {sys.argv[2]}: source edits (t s, file) {edits}; submit_patch at t={sub} s")
EOF
  done
  echo
  echo "## 5. fastapi_14986: the only check p4_b1024 ran (tests/test_local_docs.py) on the UNEDITED code"
  T=$(mktemp -d)
  mkdir -p "$T/tests" && cp -R ~/.cache/g4/ws/fastapi_14986/base/fastapi "$T/" \
    && cp ~/.cache/g4/ws/fastapi_14986/base/tests/test_local_docs.py ~/.cache/g4/ws/fastapi_14986/base/tests/__init__.py "$T/tests/"
  echo "\$ (copy of base fastapi/ + tests/test_local_docs.py) PYTHONPATH=. ~/.cache/g4/kpar/fastapi/bin/python -m pytest -q tests/test_local_docs.py"
  (cd "$T" && PYTHONPATH=. $B ~/.cache/g4/kpar/fastapi/bin/python -m pytest -q -p no:cacheprovider tests/test_local_docs.py 2>&1 | tail -1)
  rm -rf "$T"
} > $OUT 2>&1
echo "wrote $OUT"
