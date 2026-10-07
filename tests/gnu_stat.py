"""GNU coreutils `stat` for tests on macOS, as far as scripts/overnight_gate.sh and scripts/train_when_ready.sh used it.

GNU's -f is --file-system and takes no argument, so in `stat -f %m FILE || stat -c %Y FILE` the `%m` is a second file
operand: FILE's file-system status goes to stdout, the missing '%m' fails the call, and the fallback's mtime is appended
to the captured text, which `[ ... -lt ... ]` cannot compare (checked against GNU coreutils 9.7 in python:3.12-slim on
2026-10-07; on the Linux A6000 box both scripts then ignored a stale marker / report)."""
import os
from pathlib import Path

GNU_STAT = r'''#!/usr/bin/env python3
import os, sys
fs, fmt, files, rc, args = False, None, [], 0, sys.argv[1:]
while args:
    a = args.pop(0)
    if a in ("-f", "--file-system"):
        fs = True
    elif a == "-c":
        fmt = args.pop(0)
    else:
        files.append(a)
for f in files:
    if not os.path.exists(f):
        what = "read file system information for" if fs else "statx"
        print(f"stat: cannot {what} '{f}': No such file or directory", file=sys.stderr)
        rc = 1
    elif fmt is not None:
        print(fmt.replace("%Y", str(int(os.stat(f).st_mtime))))
    elif fs:
        print(f'  File: "{f}"\n    ID: 0        Namelen: 255     Type: ext2/ext3\nBlock size: 4096       Fundamental block size: 4096')
    else:
        print(f"  File: {f}")
sys.exit(rc)
'''


def gnu_stat_path(tmp) -> str:
    """A PATH whose `stat` behaves like GNU coreutils' (the A6000 box), for a script's env."""
    d = Path(tmp) / "gnubin"
    d.mkdir(parents=True, exist_ok=True)
    (d / "stat").write_text(GNU_STAT)
    (d / "stat").chmod(0o755)
    return f"{d}{os.pathsep}{os.environ['PATH']}"
