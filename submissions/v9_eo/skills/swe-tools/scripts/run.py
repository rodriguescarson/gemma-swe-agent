"""Run a shell command with a timeout and compact, colour-free output (full log kept in /tmp/swe/last.log). Stdlib only.
Usage: python3 /tmp/swe/run.py [--timeout 20] "<shell command>" """
import os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ws import ws, SWE
a = sys.argv[1:]; t = 20
if len(a) >= 2 and a[0] == "--timeout":
    try: t = max(1, min(120, int(a[1])))
    except ValueError: pass
    a = a[2:]
if not a: print(__doc__); sys.exit(0)
cmd = " ".join(a); ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")
try:
    r = subprocess.run(cmd, shell=True, cwd=ws(), capture_output=True, text=True, errors="replace", timeout=t)
    out, head = r.stdout + r.stderr, f"exit={r.returncode}"
except subprocess.TimeoutExpired as e:
    out = ((e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")) + \
          ((e.stderr or b"").decode(errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or ""))
    head = f"TIMEOUT after {t}s (possible infinite loop or waiting for input; narrow the command)"
out = ANSI.sub("", out).replace("\r", "\n")
os.makedirs(SWE, exist_ok=True); open(os.path.join(SWE, "last.log"), "w").write(out)
lines = out.splitlines()
if len("\n".join(lines)) <= 3500: body = "\n".join(lines)
else:
    top, tail = "\n".join(lines[:25])[:1200], "\n".join(lines[-45:])[-2000:]
    body = f"{top}\n... [{len(lines)} lines total; middle cut, full output: grep/sed /tmp/swe/last.log] ...\n{tail}"
print(head); print(body)
