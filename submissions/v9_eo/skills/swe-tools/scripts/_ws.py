import os
# The subprocess sandbox rewrites "/tmp" in COMMAND TEXT to its private tmp dir and exports that dir as TMPDIR.
# Python code is not rewritten, so helpers must use $TMPDIR to land where `python3 /tmp/swe/...` resolves.
SWE = os.path.join(os.environ.get("TMPDIR") or "/tmp", "swe")
def ws():
    for c in (os.environ.get("SWE_WS"), "/workspace", os.environ.get("PWD"), os.getcwd()):
        if c and os.path.isdir(os.path.join(c, ".git")):
            return c
    return "/workspace"
