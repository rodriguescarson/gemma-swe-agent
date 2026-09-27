#!/usr/bin/env bash
# Sandbox base env mirroring the Kaggle scoring host's test tooling (Dockerfile.public list + packages Kaggle has that the wheels lack).
set -e
export UV_LINK_MODE=copy
[ -d /root/buildenv ] || uv venv -q -p 3.12 /root/buildenv
VIRTUAL_ENV=/root/buildenv uv pip install -q "pytest==8.3.4" "pytest-timeout==2.1.0" typer pdm-backend setuptools wheel poetry-core hatchling flit-core editables pip \
  typing-inspection inline-snapshot dirty-equals pytest-httpbin trustme pytest-asyncio anyio python-multipart
/root/buildenv/bin/python -c "import pytest, dirty_equals, inline_snapshot, pytest_httpbin, multipart; print('buildenv ok')"
# Pins read from the Kaggle scoring image (pip freeze from the rescore kernel), e.g. pygments.
PINS="$(dirname "$0")/../data/kaggle_pins.txt"
[ -s "$PINS" ] && VIRTUAL_ENV=/root/buildenv uv pip install -q -r "$PINS"
