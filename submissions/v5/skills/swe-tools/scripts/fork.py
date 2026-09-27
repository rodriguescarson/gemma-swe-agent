"""Create hidden candidate copies /workspace/.cand_a/.cand_b/.cand_c (excluded from the patch via .git/info/exclude)."""
import os, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ws import ws
W = ws(); names = sys.argv[sys.argv.index("--names") + 1].split(",") if "--names" in sys.argv else ["a", "b", "c"]
ex = os.path.join(W, ".git", "info", "exclude")
if ".cand_*/" not in open(ex).read():
    open(ex, "a").write("\n.cand_*/\n")
ign = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".cand_*", ".pytest_cache", "*.egg-info", "docs", "*.png", "*.jpg", "*.gif", "*.svg", "*.ico", "*.woff*", "node_modules", "site", "*.min.js")
for n in names:
    d = os.path.join(W, f".cand_{n}")
    if os.path.exists(d): shutil.rmtree(d)
    shutil.copytree(W, d, ignore=ign, symlinks=True)
print("candidate copies:", ", ".join(f"/workspace/.cand_{n}" for n in names))
