#!/usr/bin/env bash
# Harness venv separate from vLLM. Host site-packages leak into every subprocess sandbox (system_site_packages=True),
# so it must carry pytest + repo test deps like the Kaggle scoring host does.
set -e
export UV_LINK_MODE=copy
[ -d /root/hvenv ] || uv venv -q -p 3.12 /root/hvenv
source /root/hvenv/bin/activate
cd /root/g4
uv pip install -q "google-adk==1.36.1" litellm pyyaml "transformers==5.13.1" \
  harness/wheels/adk_submission-0.2.13-py3-none-any.whl harness/wheels/adk_eval_core-0.1.0-py3-none-any.whl harness/wheels/swegemma-0.2.11-py3-none-any.whl
python - <<'PY' > /tmp/newest_wheels.txt
import os, re
from packaging.version import Version
best = {}
for f in os.listdir("/wheels"):
    if not f.endswith(".whl") or "cp313" in f or "cp311" in f: continue
    name, ver = f.split("-")[0].lower().replace("_", "-"), f.split("-")[1]
    try: v = Version(ver)
    except Exception: continue
    if name not in best or v > best[name][0]: best[name] = (v, f)
for n, (v, f) in sorted(best.items()):
    if n in ("fastapi", "rich", "requests", "httpx"): continue   # the repos under test come from /workspace
    print("/wheels/" + f)
PY
wc -l < /tmp/newest_wheels.txt
uv pip install -q --no-deps $(cat /tmp/newest_wheels.txt) 2>&1 | tail -3
python -c "import pytest, anyio, starlette, pydantic; print('pytest', pytest.__version__, 'starlette', starlette.__version__, 'pydantic', pydantic.__version__)"
echo HENV DONE
