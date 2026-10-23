#!/usr/bin/env bash
# Rebuild the paper from saved results: figures, tables, then the PDF (needs python3 with matplotlib, and tectonic).
set -euo pipefail
cd "$(dirname "$0")"
python3 make_figures.py
python3 make_tex_tables.py
tectonic -X compile main.tex
echo "built $(pwd)/main.pdf"
