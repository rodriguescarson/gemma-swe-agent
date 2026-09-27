---
name: swe-tools
description: Installs repository helpers into /tmp/swe (locate, targeted test, preflight/checkpoint).
---
# swe-tools
Run once: `run_skill_script(skill_name="swe-tools", file_path="install.py")`. Afterwards use the helpers with `run_command`:
- `python3 /tmp/swe/locate.py "<identifiers, error text, keywords>"` ranks files and functions (incl. async) with line ranges.
- `python3 /tmp/swe/test.py --target tests/test_x.py::test_name` runs one target, compact output.
- `python3 /tmp/swe/check.py --mode preflight` before submit; `--mode save` after a verified fix; `--mode restore` to go back to it.
