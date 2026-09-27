#!/usr/bin/env bash
# Run the suite in a Linux Python 3.12 container (the pod/Kaggle OS). macOS-only passes once hid a stdlib-shadowing bug.
set -euo pipefail
cd "$(dirname "$0")/.."
docker run --rm -v "$PWD":/g4:ro -w /tmp python:3.12-slim bash -c "apt-get -qq update >/dev/null && apt-get -qq install -y git >/dev/null 2>&1; \
  cp -r /g4 /tmp/g4 && cd /tmp/g4 && rm -rf .venv && pip -q install pytest pyarrow >/dev/null 2>&1; \
  git config --global user.email a@b; git config --global user.name a; \
  PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests -k 'not shellcheck and not official_compiler' -rf 2>&1 | tail -5"
