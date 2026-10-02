"""Copy the swe-tools helpers into /tmp/swe so they can be run with plain `python3 /tmp/swe/<tool>.py`.

v4h: edit.py is also copied into the sandbox's own tmp dirs ($TEST_TMPDIR, $TMPDIR, tempfile.gettempdir()). The
subprocess sandbox rewrites the literal /tmp in command text to its own tmp (research/harness_runtime.md 2.3), so a
`python3 /tmp/swe/edit.py` call resolves there; the other helpers stay exactly where v4 put them."""
import os, shutil, sys, tempfile
here = os.path.dirname(os.path.abspath(__file__)); dst = "/tmp/swe"
os.makedirs(dst, exist_ok=True)
for f in os.listdir(here):
    if f.endswith(".py") and f != "install.py": shutil.copy(os.path.join(here, f), os.path.join(dst, f))
edit_dirs = []
for base in (os.environ.get("TEST_TMPDIR"), os.environ.get("TMPDIR"), tempfile.gettempdir(), "/tmp"):
    if base and os.path.isdir(base):
        d = os.path.join(base, "swe")
        if os.path.realpath(d) not in [os.path.realpath(x) for x in edit_dirs]: edit_dirs.append(d)
done = []
for d in edit_dirs:
    try:
        os.makedirs(d, exist_ok=True); shutil.copy(os.path.join(here, "edit.py"), os.path.join(d, "edit.py")); done.append(d)
    except OSError as e:
        print("edit.py not installed to", d, "-", e)
print("installed:", sorted(os.listdir(dst)), "| edit.py in", done)
print('usage: python3 /tmp/swe/edit.py FILE <<\'EOF\' (SEARCH/REPLACE block) | python3 /tmp/swe/locate.py "<identifiers and keywords>" | python3 /tmp/swe/test.py --target tests/test_x.py[::name] | python3 /tmp/swe/check.py --mode preflight|save|restore')
