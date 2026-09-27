"""Rank source files and symbols (incl. async defs, methods, classes) for a query. Stdlib only.
Usage: python3 /tmp/swe/locate.py "<identifiers, error text, keywords>" """
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ws import ws
import repoindex as ri
args = sys.argv[1:]; q = ""
if "--query" in args: q = args[args.index("--query") + 1]
elif args: q = " ".join(a for a in args if a != "--")
if not q: q = sys.stdin.read() if not sys.stdin.isatty() else ""
ROOT = ws(); idx = ri.build(ROOT); files = ri.rank(idx, q)
print(f"workspace={ROOT} symbols={len(idx['docs'])}")
for i, (f, lst) in enumerate(files[:8]):
    tag = " [test]" if lst[0][1][5] else ""
    print(f"{i+1}. {f}{tag}  score={lst[0][0]:.1f}")
    for s, d in lst[:4]:
        if d[1] != "<module>": print(f"     {d[4]} {d[1]}  L{d[2]}-{d[3]}")
if not files: print("no matches; try other identifiers or `git grep -n <word>`")
