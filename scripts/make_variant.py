"""Build a race variant from a base bundle by switching on independent levers (2026-09-27 diagnosis).
  --edit   replace.py (line-range edit, syntax-checked, auto-revert) + edit-failure rules      [EDIT_TOOL_FAILURE]
  --output run.py (timeout, ANSI strip, head+tail) + test.py timeout 45 s and ANSI strip       [context overflow, hangs]
  (default) install helpers into $TMPDIR/swe so sandbox commands can reach them       [helpers never ran]
  --gate   gate.py regression gate + repro rule in the verifier                               [never ran tests, regressions]
Usage: python scripts/make_variant.py <base_bundle> <out_dir> [--edit] [--output] [--gate]"""
import argparse, os, re, shutil
ap = argparse.ArgumentParser(); ap.add_argument("base"); ap.add_argument("out")
for f in ("edit", "output", "gate"): ap.add_argument("--" + f, action="store_true")
ap.add_argument("--keep-tmp-bug", action="store_true", help="do NOT apply the $TMPDIR install fix (reproduces v4 as submitted)")
a = ap.parse_args()
H = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "helpers_v9")
if os.path.exists(a.out): shutil.rmtree(a.out)
shutil.copytree(a.base, a.out, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "._*", ".DS_Store"))
SK = os.path.join(a.out, "skills/swe-tools"); SC = os.path.join(SK, "scripts")
def edit(rel, fn):
    p = os.path.join(a.out, rel); s = open(p).read(); t = fn(s)
    assert t != s, f"lever did not change {rel}"; open(p, "w").write(t)
usage = []
if not a.keep_tmp_bug:  # helpers were installed to the host /tmp, unreachable from sandbox commands (81/85 locate calls failed in v4)
    for f in ("_ws.py", "install.py"): shutil.copy(os.path.join(H, f), SC)
if a.edit:
    shutil.copy(os.path.join(H, "replace.py"), SC)
    rule = ("\nEditing: if `edit_file` fails ONCE, do not retry it; instead replace whole lines by number (raw text, no escaping):\n"
            "`python3 /tmp/swe/replace.py --file <path> --start <first line> --end <last line> <<'EOF'` + newline + the new lines + newline + `EOF` "
            "(run it with run_command). It syntax-checks and reverts bad edits. Read the exact line numbers with read_file first. "
            "Never rewrite a whole file with write_file.\n")
    for r in ("prompts/fixer.md", "prompts/verifier.md"):
        edit(r, lambda s: s.replace("\nTools you can call:", rule + "\nTools you can call:", 1))
    usage.append("python3 /tmp/swe/replace.py --file F --start N --end M <<'EOF' ... EOF")
if a.output:
    shutil.copy(os.path.join(H, "run.py"), SC)
    edit("skills/swe-tools/scripts/test.py", lambda s: s.replace('int(opt.get("timeout", 150))', 'int(opt.get("timeout", 45))')
         .replace('out = r.stdout + r.stderr;', 'out = re.sub(r"\\x1b\\[[0-9;?]*[ -/]*[@-~]", "", r.stdout + r.stderr);'))
    rule = ("\nCommands: run anything that may print a lot or may hang through `python3 /tmp/swe/run.py --timeout 20 \"<command>\"` "
            "(colour stripped, long output cut, full log in /tmp/swe/last.log for grep). Never cat large files; use read_file with line ranges.\n")
    for r in ("prompts/locator.md", "prompts/fixer.md", "prompts/verifier.md"):
        edit(r, lambda s: s.replace("\nTools you can call:", rule + "\nTools you can call:", 1))
    usage.append('python3 /tmp/swe/run.py --timeout 20 "<cmd>"')
if a.gate:
    shutil.copy(os.path.join(H, "gate.py"), SC)
    step = ("2. Run `python3 /tmp/swe/gate.py` (add `--target <test file>` if the plan names one). It runs the related existing tests on your "
            "version and on the original code. If it lists REGRESSIONS, the change is wrong: fix it (or undo the offending part) and run gate.py again, "
            "at most twice. Then check the issue's own example: `cat > /tmp/repro.py <<'EOF'` ... `EOF` and `python3 /tmp/repro.py`; "
            "if it still shows the bug, fix it.")
    edit("prompts/verifier.md", lambda s: re.sub(r"^2\. Run the relevant test:.*$", step.replace("\\", r"\\"), s, count=1, flags=re.M))
    usage.append("python3 /tmp/swe/gate.py [--target tests/test_x.py]")
if usage:
    edit("skills/swe-tools/SKILL.md", lambda s: s.rstrip("\n") + "\n" + "\n".join(f"- `{u}`" for u in usage) + "\n")
print(a.out, "tmpfix:", not a.keep_tmp_bug, "levers:", [f for f in ("edit", "output", "gate") if getattr(a, f)])
