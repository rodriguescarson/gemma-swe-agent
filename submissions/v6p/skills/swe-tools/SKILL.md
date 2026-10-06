---
name: swe-tools
description: Installs repository helpers into /tmp/swe (edit, view, locate, targeted test, repro, preflight/checkpoint, best-of-3 selection).
---
# swe-tools
Run once: `run_skill_script(skill_name="swe-tools", file_path="install.py")`. Afterwards use the helpers with `run_command`:
- `python3 /tmp/swe/edit.py FILE <<'EOF'` with a `<<<<<<< SEARCH` / `=======` / `>>>>>>> REPLACE` block (or `--lines A-B`, or `--create`) edits a file as raw code; the only way to edit.
- `python3 /tmp/swe/locate.py "<identifiers, error text, keywords>"` ranks files and functions (incl. async) with line ranges.
- `python3 /tmp/swe/test.py --target tests/test_x.py::test_name` runs one target, compact output.
- `python3 /tmp/swe/check.py --mode preflight` before submit; `--mode save` after a verified fix; `--mode restore` to go back to it.
- `python3 /tmp/swe/repro.py` runs the locator's /tmp/repro.py against the current repo (prints REPRO PASS / REPRO FAIL).
- Every helper works on the repo it is started in: `cd /tmp/wa && python3 /tmp/swe/view.py ...` reads fixer A's copy.
- `run_skill_script(skill_name="swe-tools", file_path="select_best.py", args={"test": "tests/test_x.py"})` tests the fixers' candidates /tmp/wa, /tmp/wb, /tmp/wc and applies the best one to /workspace (selector stage only).
