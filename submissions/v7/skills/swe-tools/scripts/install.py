"""Copy the swe-tools helpers so `python3 /tmp/swe/<tool>.py` works inside the scorer's subprocess sandbox.

The sandbox rewrites the literal /tmp in command text to its own tmp dir (research/harness_runtime.md 2.3), so a
helper is reachable only if it sits in <sandbox tmp>/swe. v4h copied only edit.py there and left locate/test/check on
the host /tmp/swe: on 4xL4 (2026-10-03, g4-l4-v4 v4) locate.py then failed 145 of 151 calls, check.py 61 of 62,
test.py 19 of 19. v4h2f copies EVERY helper into every candidate tmp dir ($TEST_TMPDIR, $TMPDIR, tempfile.gettempdir(),
/tmp). Reachability is only ever proven on a Kaggle kernel (the Docker emulation resolves /tmp differently)."""
import os, shutil, sys, tempfile
here = os.path.dirname(os.path.abspath(__file__))
helpers = sorted(f for f in os.listdir(here) if f.endswith(".py") and f != "install.py")
dirs = []
for base in (os.environ.get("TEST_TMPDIR"), os.environ.get("TMPDIR"), tempfile.gettempdir(), "/tmp"):
    if base and os.path.isdir(base):
        d = os.path.join(base, "swe")
        if os.path.realpath(d) not in [os.path.realpath(x) for x in dirs]: dirs.append(d)
done = []
for d in dirs:
    try:
        os.makedirs(d, exist_ok=True)
        for f in helpers: shutil.copy(os.path.join(here, f), os.path.join(d, f))
        done.append(d)
    except OSError as e:
        print("helpers not installed to", d, "-", e)
print("installed:", helpers, "| helpers in", done)
print('usage: python3 /tmp/swe/edit.py FILE <<\'EOF\' (SEARCH/REPLACE block) | python3 /tmp/swe/locate.py "<identifiers and keywords>" | python3 /tmp/swe/test.py --target tests/test_x.py[::name] | python3 /tmp/swe/check.py --mode preflight|save|restore')
