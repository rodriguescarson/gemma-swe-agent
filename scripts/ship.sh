#!/usr/bin/env bash
# The only supported path from a bundle to a Kaggle notebook: full test suite first, then build. Refuses on any failure.
# Usage: scripts/ship.sh <bundle_dir> <slug> [eval|submit] [make_eval_kernel args...]
set -euo pipefail
cd "$(dirname "$0")/.."
B=$1; SLUG=$2; MODE=${3:-submit}; shift 3 2>/dev/null || shift $#
find submissions -name "__pycache__" -prune -exec rm -rf {} +
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests || { echo "SHIP REFUSED: tests failed"; exit 1; }
bash scripts/linux_test.sh | tee /tmp/linux_test.out; grep -qE "[0-9]+ passed" /tmp/linux_test.out && ! grep -qE "[0-9]+ failed" /tmp/linux_test.out || { echo "SHIP REFUSED: Linux tests failed"; exit 1; }
if [ "$MODE" = eval ]; then python3 scripts/make_eval_kernel.py "$B" "$SLUG" "$@"; else python3 scripts/make_kernel.py "$B" "$SLUG"; fi
echo "SHIP OK: kernels/$SLUG"
