"""Scratch inputs for rankexp.py/stemexp.py: a copy of the v10 helper scripts (never imported from the bundle) and the
dev-split snapshots with a local tgz, extracted under ws/ (about 3.8 GB; delete ws/ afterwards)."""
import os, shutil, subprocess, json
ROOT = "/Users/carson/Projects/gemma-swe-agent"
def helpers(sp):
    d = os.path.join(sp, "scripts")
    if not os.path.isdir(d):
        shutil.copytree(os.path.join(ROOT, "submissions/v10/skills/swe-tools/scripts"), d, ignore=shutil.ignore_patterns("__pycache__"))
def workspaces(sp):
    split = json.load(open(os.path.join(ROOT, "eval/golden/split.json")))["tasks"]
    snaps = os.path.join(ROOT, "data/raw/snapshots")
    for tid, v in sorted(split.items()):
        if v["split"] != "dev":
            continue          # never the holdout split
        tgz = os.path.join(snaps, tid + ".tgz")
        dst = os.path.join(sp, "ws", tid)
        if os.path.exists(tgz) and not os.path.isdir(dst):
            os.makedirs(dst)
            subprocess.run(["tar", "xzf", tgz, "-C", dst], check=True)
