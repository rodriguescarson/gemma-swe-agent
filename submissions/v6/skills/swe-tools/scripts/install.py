"""Copy the swe-tools helpers into /tmp/swe so they can be run with plain `python3 /tmp/swe/<tool>.py`."""
import os, shutil, sys
here = os.path.dirname(os.path.abspath(__file__)); dst = "/tmp/swe"
os.makedirs(dst, exist_ok=True)
for f in os.listdir(here):
    if f.endswith(".py") and f != "install.py": shutil.copy(os.path.join(here, f), os.path.join(dst, f))
print("installed:", sorted(os.listdir(dst)))
print('usage: python3 /tmp/swe/locate.py "<identifiers and keywords>" | python3 /tmp/swe/test.py --target tests/test_x.py[::name] | python3 /tmp/swe/check.py --mode preflight|save|restore')
