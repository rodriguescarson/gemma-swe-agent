---
name: swe-tools
description: Fast repository localization, compact targeted test runs, and patch hygiene checks for fixing an issue in /workspace.
---
# swe-tools

Call scripts with `run_skill_script(skill_name="swe-tools", file_path="<script>", args={...})`.

- `locate.py` args `{"query": "<identifiers, error messages, keywords from the issue>"}`: ranks source files and symbols (functions, async functions, methods, classes) with line ranges. Use it first.
- `test.py` args `{"target": "tests/test_file.py::test_name"}` (optional `"k": "expr"`): runs only that target and prints a compact pass/fail summary.
- `check.py` args `{"mode": "preflight"}`: shows the diff stat, flags edited test/config files, scratch files and syntax errors. Run it before `submit_patch`.
- `check.py` args `{"mode": "save"}` after a verified fix; `{"mode": "restore"}` to return to the saved fix if later edits break it.
