#!/usr/bin/env bash
# Build the Kaggle-parity ("kpar") uv venvs that the v10 per-task offline tests run repo tests with (SPEC section 8).
#
#   scripts/build_kpar.sh [rich|requests|fastapi ...]     (no argument: rich and requests)
#
# The venvs live OUTSIDE the repo, in ${G4_KPAR:-~/.cache/g4/kpar}/<repo>: a .kpar/ inside the repo would be swept by
# tests/test_build.py::test_python_compiles.
#   rich, requests  offline only: ~/.cache/uv plus data/raw/wheels, pins equal to eval/kaggle/rescore_fair/pip_freeze.txt
#                   (requests 2.33.0 is the nearest offline version to Kaggle's 2.32.4; it sits in site-packages because
#                   on Kaggle requests' src layout makes the tests import the installed copy, F10).
#   fastapi         needs the network ONCE (Carson's call). Without G4_KPAR_ONLINE=1 it only tries the offline cache and,
#                   when a pin is missing, prints the online command and exits 2. No dirty-equals, no inline-snapshot
#                   (Kaggle has neither).
# A finished venv gets a stamp file (.g4_kpar_ok) holding its pin list; tests treat a venv without it as absent.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KPAR="${G4_KPAR:-$HOME/.cache/g4/kpar}"
WHEELS="$ROOT/data/raw/wheels"

BASE_PINS=(pytest==8.4.2 Pygments==2.20.0 markdown-it-py==4.0.0 mdurl==0.1.2 typing_extensions==4.15.0 attrs==26.1.0)
REQUESTS_PINS=(requests==2.33.0 urllib3 idna charset-normalizer certifi pysocks)
FASTAPI_PINS=(pytest==8.4.2 pydantic==2.12.3 pydantic-core==2.41.4 starlette==0.52.1 anyio==4.13.0 httpx==0.28.1
  python-multipart==0.0.26 email-validator==2.3.0 PyYAML==6.0.3 SQLAlchemy==2.0.49 orjson==3.11.8 ujson==5.13.0
  Flask==3.1.3 Jinja2==3.1.6 typing-inspection==0.4.2 PyJWT==2.12.1 typing_extensions==4.15.0 annotated-types==0.7.0
  Pygments==2.20.0)

die() { echo "build_kpar: $*" >&2; exit 2; }
targets=("$@")
[ ${#targets[@]} -eq 0 ] && targets=(rich requests)
for t in "${targets[@]}"; do   # usage errors first, before any tool or path check (Linux gate: no uv there)
  case "$t" in rich|requests|fastapi) ;; *) die "unknown target '$t' (rich|requests|fastapi)" ;; esac
done
command -v uv >/dev/null 2>&1 || die "uv not found (brew install uv)"
[ -d "$WHEELS" ] || die "missing $WHEELS"

# build NAME OFFLINE(0|1) PIN...  ->  a fresh venv at $KPAR/NAME with exactly these requirements
build() {
  local name="$1" offline="$2"; shift 2
  local dest="$KPAR/$name"
  local -a net=()
  if [ "$offline" = 1 ]; then net=(--offline); export UV_OFFLINE=1; else unset UV_OFFLINE; fi
  mkdir -p "$KPAR"
  rm -f "$dest/.g4_kpar_ok"
  echo "build_kpar: $name -> $dest ($([ "$offline" = 1 ] && echo offline || echo ONLINE))"
  uv venv -q --clear -p 3.12 "$dest"
  if ! VIRTUAL_ENV="$dest" uv pip install -q ${net[@]+"${net[@]}"} --find-links "$WHEELS" "$@"; then
    return 1
  fi
  "$dest/bin/python" -c "import pytest, sys; sys.exit(0 if pytest.__version__ == '8.4.2' else 1)" \
    || die "$name: pytest in $dest is not 8.4.2"
  printf '%s\n' "$@" > "$dest/.g4_kpar_ok"
  echo "build_kpar: $name ok ($("$dest/bin/python" -V 2>&1))"
}

for t in "${targets[@]}"; do
  case "$t" in
    rich) build rich 1 "${BASE_PINS[@]}" || die "rich: offline install failed (pins must be in ~/.cache/uv or $WHEELS)" ;;
    requests) build requests 1 "${BASE_PINS[@]}" "${REQUESTS_PINS[@]}" || die "requests: offline install failed" ;;
    fastapi)
      if [ "${G4_KPAR_ONLINE:-0}" = 1 ]; then
        build fastapi 0 "${FASTAPI_PINS[@]}" || die "fastapi: online install failed"
      elif ! build fastapi 1 "${FASTAPI_PINS[@]}"; then
        rm -rf "$KPAR/fastapi"
        echo "build_kpar: the fastapi pins are not all in the offline cache. The one-time online build is Carson's call:" >&2
        echo "  G4_KPAR_ONLINE=1 $ROOT/scripts/build_kpar.sh fastapi" >&2
        exit 2
      fi ;;
    *) die "unknown target '$t' (rich|requests|fastapi)" ;;
  esac
done
