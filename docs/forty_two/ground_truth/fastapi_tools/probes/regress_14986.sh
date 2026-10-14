#!/bin/bash
# Would existing root_path tests have caught the box patches' deletion of root_path-in-servers? (fastapi_14986)
SCR=${SCR:?set SCR to the scratch dir used by gt_fastapi.py}
WS=$SCR/ws/fastapi_14986
PY=$SCR/venv/fastapi_14986-ws/bin/python
cd "$WS" || exit 1
TESTS=$(grep -rl "root_path" tests | grep "\.py$" | sort | tr "\n" " ")
echo "existing tests mentioning root_path: $TESTS"
for p in base box_p4 box_p4_v7 box_p4_b1024; do
  git checkout -q -f 2f9c914d44 && git clean -fdxq
  if [ "$p" != base ]; then git apply "$SCR/logs/fastapi_14986/ws_$p.diff" || echo "apply failed $p"; fi
  out=$(PYTHONSAFEPATH=1 PYTHONNOUSERSITE=1 "$PY" -s -m pytest $TESTS -p no:anyio -q --continue-on-collection-errors 2>&1 | tail -1)
  echo "$p: $out"
done
git checkout -q -f 2f9c914d44 && git clean -fdxq
