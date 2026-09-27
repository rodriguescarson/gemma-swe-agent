"""Copy the swe-tools helpers into $TMPDIR/swe, which is where the sandbox maps `python3 /tmp/swe/<tool>.py`."""
import os, shutil
here = os.path.dirname(os.path.abspath(__file__)); dst = os.path.join(os.environ.get("TMPDIR") or "/tmp", "swe")
os.makedirs(dst, exist_ok=True)
for f in os.listdir(here):
    if f.endswith(".py") and f != "install.py": shutil.copy(os.path.join(here, f), os.path.join(dst, f))
print("installed:", sorted(f for f in os.listdir(dst) if f.endswith(".py")))
print('usage: python3 /tmp/swe/locate.py "<identifiers and keywords>" | python3 /tmp/swe/test.py --target tests/test_x.py[::name] | python3 /tmp/swe/check.py --mode preflight|save|restore')
