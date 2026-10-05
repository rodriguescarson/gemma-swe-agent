---
name: swe-tools
description: Installs repository helpers into /tmp/swe (edit, locate, targeted test, preflight/checkpoint).
---
# swe-tools
Run once: `run_skill_script(skill_name="swe-tools", file_path="install.py")`. Afterwards use the helpers with `run_command`:
run_skill_script takes file_path as ONE string (file_path="install.py"), never a list: a list crashes the sandbox.
- `python3 /tmp/swe/edit.py FILE <<'EOF'` with a `<<<<<<< SEARCH` / `=======` / `>>>>>>> REPLACE` block (or `--lines A-B`, or `--create`) edits a file as raw code; the only way to edit.
- `python3 /tmp/swe/locate.py "<identifiers, error text, keywords>"` ranks files and functions (incl. async) with line ranges.
- `python3 /tmp/swe/repo_map.py [PATH_OR_PACKAGE] [--grep TERM]` maps classes, functions (signatures) and methods with line numbers.
- `python3 /tmp/swe/test.py --target tests/test_x.py::test_name` runs one target, compact output.
- `python3 /tmp/swe/check.py --mode preflight` before submit; `--mode save` after a verified fix; `--mode restore` to go back to it.
