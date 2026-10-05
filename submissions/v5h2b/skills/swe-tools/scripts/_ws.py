import os
def ws():
    for c in (os.environ.get("SWE_WS"), "/workspace", os.environ.get("PWD"), os.getcwd()):
        if c and os.path.isdir(os.path.join(c, ".git")):
            return c
    return "/workspace"
