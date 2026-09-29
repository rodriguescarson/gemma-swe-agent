---
name: swe-tools
description: Repository helpers for this task. Install once with run_skill_script(file_path="install.py", skill_name="swe-tools"), then run each helper with run_command as python3 /tmp/swe/NAME.py.
---
# swe-tools
Install: run_skill_script(file_path="install.py", skill_name="swe-tools")
Any helper run through run_skill_script also installs all of them. Options work as args, for example file, start and end.
- python3 /tmp/swe/locate.py "QUERY"
- python3 /tmp/swe/grep.py "REGEX" [PATH ...] [--tests] [--max N]
- python3 /tmp/swe/view.py FILE [START END | NAME] | --obj DOTTED.NAME
- python3 /tmp/swe/edit.py FILE [--lines A-B [--delete] | --insert-after N | --create] <<'EOF' ... EOF
- python3 /tmp/swe/run.py [--timeout N] "COMMAND"
- python3 /tmp/swe/verify.py [--repro-only] [--tests FILE ...] [--list-tests]
- python3 /tmp/swe/finalize.py
- python3 /tmp/swe/status.py
