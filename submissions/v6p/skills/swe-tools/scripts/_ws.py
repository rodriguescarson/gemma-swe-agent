import os
def ws():
    """The repository a helper works on. v6p: a cwd that is itself a git root comes before /workspace, so that
    `cd /tmp/wK && python3 /tmp/swe/<helper>.py` works on fixer K's copy (three fixers share one sandbox)."""
    cwd = os.getcwd()
    for c in (os.environ.get("SWE_WS"), cwd if os.path.isdir(os.path.join(cwd, ".git")) else None,
              "/workspace", os.environ.get("PWD"), cwd):
        if c and os.path.isdir(os.path.join(c, ".git")):
            return c
    return "/workspace"
