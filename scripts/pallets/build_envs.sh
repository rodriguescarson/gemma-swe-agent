#!/usr/bin/env bash
# Build the per-repo test venvs for the SWE-Pallets-X oracle and dev set (research/pallets.md section 3).
#
#   scripts/pallets/build_envs.sh [click flask flask-wz2 flask-2022 werkzeug jinja2 markupsafe itsdangerous pytest sympy]  (no arg: all)
#
# Venvs live OUTSIDE the repo at ${G4_PALLETS:-~/.cache/g4/pallets}/<repo> (like scripts/build_kpar.sh's kpar venvs).
# Rules, so the environment matches the scorer as closely as the dev set allows:
#   * python 3.12 (Kaggle and pod), pytest 8.4.2 (Kaggle's pip_freeze), except for the pytest repo, which tests itself
#   * every package that Kaggle's image has is pinned to Kaggle's version (eval/kaggle/rescore_fair/pip_freeze.txt)
#   * test-only deps that Kaggle lacks (EXTRA_*) are pinned to the versions below and listed in the stamp's "extra" line,
#     so a pod run can ship the same wheels (research/pallets.md section 7)
#   * the repo's code is imported from the workspace (PYTHONPATH=<ws>:<ws>/src, which precedes site-packages), the
#     stand-in for the pod's `pip install -e /workspace` (scripts/run_eval.py) on these src-layout repos. The repo's OWN
#     package is also installed at Kaggle's version (OWN), as on Kaggle's image, only so importlib.metadata finds it
#     (flask's `--version` and click's __version__ read it; 5 tasks fail without it). pytest and sympy: not installed.
#   * era venvs (NAME-suffix) serve tasks whose base commit cannot run on Kaggle's versions; they use only versions that
#     the competition wheels also ship (data/raw/wheels: werkzeug-2.3.8, flask-2.3.3), so a pod run can reproduce them:
#       flask-wz2   Werkzeug 2.3.8 for flask base commits of 2022-2023 (werkzeug.urls.url_quote, werkzeug.__version__)
#       flask-2022  Werkzeug 2.2.3 + click 8.1.8 for the flask tasks flask-wz2 still fails (cookie Domain dot,
#                   Client._update_cookies_from_response signature, CliRunner(mix_stderr=)). NOT in the competition
#                   wheels. Measured 2026-09-30: +1 valid task of 8 (flask_91044c4), so the dev set does NOT use it
#                   (finalize.py is run without results_era2.jsonl); kept for the record.
# Needs the network once (uv resolves from PyPI); a finished venv gets .g4_pallets_ok = its `uv pip freeze`.
set -euo pipefail

DEST_ROOT="${G4_PALLETS:-$HOME/.cache/g4/pallets}"

PYTEST_BASE=(pytest==8.4.2 pluggy==1.6.0 iniconfig==2.3.0 packaging==26.1 Pygments==2.20.0)
declare -a PINS EXTRA OWN
pins_for() {
  PINS=(); EXTRA=(); OWN=()
  case "$1" in
    click)        PINS=("${PYTEST_BASE[@]}"); OWN=(click==8.3.3) ;;
    flask)        PINS=("${PYTEST_BASE[@]}" Werkzeug==3.1.8 Jinja2==3.1.6 MarkupSafe==3.0.3 itsdangerous==2.2.0
                        click==8.3.3 blinker==1.9.0 python-dotenv==1.2.2 greenlet==3.4.0)
                  EXTRA=(asgiref==3.12.1); OWN=(Flask==3.1.3) ;;
    flask-wz2)    PINS=("${PYTEST_BASE[@]}" Werkzeug==2.3.8 Jinja2==3.1.6 MarkupSafe==3.0.3 itsdangerous==2.2.0
                        click==8.3.3 blinker==1.9.0 python-dotenv==1.2.2 greenlet==3.4.0)
                  EXTRA=(asgiref==3.12.1); OWN=(Flask==2.3.3) ;;
    flask-2022)   PINS=("${PYTEST_BASE[@]}" Werkzeug==2.2.3 Jinja2==3.1.6 MarkupSafe==3.0.3 itsdangerous==2.2.0
                        click==8.1.8 blinker==1.9.0 python-dotenv==1.2.2 greenlet==3.4.0)
                  EXTRA=(asgiref==3.12.1); OWN=(Flask==2.2.5) ;;
    werkzeug)     PINS=("${PYTEST_BASE[@]}" MarkupSafe==3.0.3 cffi==2.0.0 cryptography==43.0.3 watchdog==6.0.0)
                  EXTRA=(ephemeral-port-reserve==1.1.4); OWN=(Werkzeug==3.1.8) ;;
    jinja2)       PINS=("${PYTEST_BASE[@]}" MarkupSafe==3.0.3)
                  EXTRA=(trio==0.34.0); OWN=(Jinja2==3.1.6) ;;
    markupsafe)   PINS=("${PYTEST_BASE[@]}"); OWN=(MarkupSafe==3.0.3) ;;
    itsdangerous) PINS=("${PYTEST_BASE[@]}")
                  EXTRA=(freezegun==1.5.5); OWN=(itsdangerous==2.2.0) ;;
    pytest)       PINS=(pluggy==1.6.0 iniconfig==2.3.0 packaging==26.1 Pygments==2.20.0 attrs==26.1.0
                        requests==2.32.4 setuptools==81.0.0 numpy==2.0.2 decorator==5.3.1 pexpect==4.9.0)
                  EXTRA=(argcomplete==3.7.2 hypothesis==6.168.3 mock==5.2.0 xmlschema==4.3.2 py==1.11.0 toml==0.10.2) ;;
    sympy)        PINS=("${PYTEST_BASE[@]}" mpmath==1.3.0 numpy==2.0.2 setuptools==81.0.0)
                  EXTRA=(hypothesis==6.168.3) ;;
    sympy-kx)     # sympy + the optional packages Kaggle's image has at Kaggle's versions that sympy's tests auto-detect
                  # (import_module): a probe of how a Kaggle-L4 sandbox (host site-packages visible) grades sympy. Not
                  # jax/tensorflow/pytensor (too heavy for the Mac probe). Not used by the dev set (research/pallets.md 4.5)
                  PINS=("${PYTEST_BASE[@]}" mpmath==1.3.0 numpy==2.0.2 setuptools==81.0.0 scipy==1.16.3 matplotlib==3.10.0
                        numexpr==2.14.1 Cython==3.0.12 lxml==6.1.0 antlr4-python3-runtime==4.9.3 numba==0.60.0
                        llvmlite==0.43.0 networkx==3.6.1)
                  EXTRA=(hypothesis==6.168.3) ;;
    *) echo "build_envs: unknown repo '$1'" >&2; exit 2 ;;
  esac
}

command -v uv >/dev/null 2>&1 || { echo "build_envs: uv not found" >&2; exit 2; }
targets=("$@")
[ ${#targets[@]} -eq 0 ] && targets=(click flask flask-wz2 flask-2022 werkzeug jinja2 markupsafe itsdangerous pytest sympy)
for t in "${targets[@]}"; do
  pins_for "$t"
  dest="$DEST_ROOT/$t"
  mkdir -p "$DEST_ROOT"
  rm -f "$dest/.g4_pallets_ok"
  echo "build_envs: $t -> $dest"
  uv venv -q --clear -p 3.12 "$dest"
  VIRTUAL_ENV="$dest" uv pip install -q "${PINS[@]}" ${EXTRA[@]+"${EXTRA[@]}"} ${OWN[@]+"${OWN[@]}"}
  if [ "$t" != pytest ]; then
    "$dest/bin/python" -c "import pytest, sys; sys.exit(0 if pytest.__version__ == '8.4.2' else 1)" \
      || { echo "build_envs: $t: pytest is not 8.4.2" >&2; exit 1; }
  fi
  {
    echo "# built $(date -u +%Y-%m-%dT%H:%M:%SZ) by scripts/pallets/build_envs.sh; python $("$dest/bin/python" -V 2>&1)"
    echo "# pins: ${PINS[*]}"
    echo "# extra (not in Kaggle's image): ${EXTRA[*]:-none}"
    echo "# own package (metadata only; code comes from the workspace): ${OWN[*]:-none}"
    VIRTUAL_ENV="$dest" uv pip freeze
  } > "$dest/.g4_pallets_ok"
  echo "build_envs: $t ok ($(grep -vc '^#' "$dest/.g4_pallets_ok") packages)"
done
