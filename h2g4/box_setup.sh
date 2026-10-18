#!/usr/bin/env bash
# Harness² on the A6000 box (h2g4, GAPS "Harness² pilot pre-registration", 2026-10-18). Idempotent; no GPU use. Installs:
#  1. google-research/harness2 pinned at 1cfe254 into ~/g4/harness2, editable into the box venv (its config then finds
#     ~/g4/harness2/dependencies/ for OpenCode and bun);
#  2. its pinned OpenCode checkout + its compatibility patch, through harness2.install (the same calls harness2-setup makes),
#     and bun 1.3.11 under dependencies/tools, then `bun install` in the checkout;
#  3. an OpenCode provider "boxvllm" pointing at the box's own vLLM (127.0.0.1:8000) with model "gemma4", the alias serve.sh
#     adds when SERVED_ALIAS=gemma4 is set (scripts/a6000/serve.sh; the model path stays the first served name).
# Ends by printing the paths Harness² will use; `python -m h2g4.run <dir> --smoke` then proves an improver session works.
set -euo pipefail
G4=${G4:-$HOME/g4}
H2=$G4/harness2
PIN=1cfe254e8d25b15f37048c3730134686abe60335
PY=${G4_PY:-$G4/venv/bin/python}
command -v npm >/dev/null || { echo "npm missing: install Node.js >= 20 first (e.g. nvm install 20)"; exit 1; }
node -e 'process.exit(+process.versions.node.split(".")[0] >= 20 ? 0 : 1)' || { echo "Node.js >= 20 required, have $(node -v)"; exit 1; }
command -v uv >/dev/null || { echo "uv missing"; exit 1; }
[ -d "$H2/.git" ] || git clone -q https://github.com/google-research/harness2 "$H2"
git -C "$H2" fetch -q origin "$PIN"
git -C "$H2" checkout -q --detach "$PIN"
[ "$(git -C "$H2" rev-parse HEAD)" = "$PIN" ] || { echo "harness2 is not at $PIN"; exit 1; }
uv pip install --python "$PY" -q -e "$H2"
cd "$H2"
"$PY" -c "from harness2 import install; install.clone('opencode'); install.patch('opencode')"
npm install --silent --prefix "$H2/dependencies/tools" bun@1.3.11
(cd "$H2/dependencies/opencode" && "$H2/dependencies/tools/node_modules/.bin/bun" install --frozen-lockfile --ignore-scripts)
CFG="$HOME/.config/opencode/opencode.json"
mkdir -p "$(dirname "$CFG")"
if [ -f "$CFG" ] && ! grep -q '"boxvllm"' "$CFG"; then cp "$CFG" "$CFG.bak.$(date +%s)"; echo "backed up an existing $CFG"; fi
cat > "$CFG" <<'JSON'
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "boxvllm": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "box vLLM (Gemma 4 31B)",
      "options": { "baseURL": "http://127.0.0.1:8000/v1", "apiKey": "EMPTY" },
      "models": { "gemma4": { "name": "Gemma 4 31B on the box", "limit": { "context": 32768, "output": 8192 } } }
    }
  }
}
JSON
"$PY" - <<'PY'
from harness2 import config
oc = config.OPENCODE_DIR / "packages" / "opencode" / "src" / "index.ts"
print("OPENCODE", oc, oc.is_file())
print("BUN", config.BUN, config.BUN.is_file())
assert oc.is_file() and config.BUN.is_file(), "OpenCode or bun missing"
PY
echo "h2 setup OK (harness2 $PIN)"
