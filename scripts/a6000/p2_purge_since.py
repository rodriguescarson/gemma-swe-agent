"""Remove p2_race items finished at or after EPOCH (their items.jsonl t1) and every partial item directory (no result file), so the queue re-runs them; used by the
GPU-contention guard. Item directories are written by root inside the container, so removal goes through `sudo -n rm -rf`.

    python scripts/a6000/p2_purge_since.py OUT ITEMS_DIR EPOCH        prints 'purged N'"""
import glob, json, os, subprocess, sys
from pathlib import Path


def _sudo_rm(p):
    subprocess.run(["sudo", "-n", "rm", "-rf", p], check=False)


def purge_since(out, items_dir, epoch, rm=_sudo_rm):
    n, base = 0, os.path.join(out, items_dir)
    jl = os.path.join(out, "items.jsonl" if items_dir == "items" else items_dir + ".jsonl")
    keep, drop = [], set()
    if os.path.exists(jl):
        for line in open(jl):
            if not line.strip():
                continue
            r = json.loads(line)
            (drop.add((r["arm"], r["task"])) if r.get("t1", 0) >= epoch else keep.append(line))
    for arm, task in sorted(drop):
        d = os.path.join(base, arm, task)
        if os.path.isdir(d):
            rm(d); n += 1
        rm(d + ".out"); rm(d + ".ledger")
    for d in glob.glob(os.path.join(base, "*", "*")):
        if os.path.isdir(d) and not os.path.isfile(os.path.join(d, "task_results.jsonl")):
            rm(d); rm(d + ".out"); n += 1
    if os.path.exists(jl):
        Path(jl).write_text("".join(l if l.endswith("\n") else l + "\n" for l in keep))
    return n


if __name__ == "__main__":
    print(f"purged {purge_since(sys.argv[1], sys.argv[2], float(sys.argv[3]))}")
