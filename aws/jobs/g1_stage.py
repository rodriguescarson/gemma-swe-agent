"""Stage the G1 teacher pilot's inputs in S3: the plan only, unless --upload.

    python aws/jobs/g1_stage.py --run s3://B/runs/g1 [--shared s3://B/shared] [--ref wip/gemma-agent] [--keep-dir DIR] [--upload]

Uploads (each verified by size on the far side, aws/stage.py):
  1. RUN/in/code.tgz: `git archive` of --ref, which must contain aws/jobs/g1_teacher.sh (commit aws/ first). The box
     gets this archive instead of a git clone, so it needs no GitHub credentials.
  2. RUN/in/overlay/data/heldout1k/harness_g1/: the 30 G1 tasks cut from data/heldout1k/harness_all: tasks.jsonl, ids.txt,
     env.json and manifest.json for those ids, snapshots/<id>.tgz byte-identical, and the whole wheels/ directory
     (every task installs from it with --find-links, so it is not trimmed). No graphs or embeddings.
  3. SHARED/raw/wheels/: the competition's data/raw/wheels (pod/harness_env.sh and the race container read /wheels).
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "aws"))
IDS = ROOT / "data" / "distill" / "g1_ids.txt"
HARNESS = ROOT / "data" / "heldout1k" / "harness_all"
OVERLAY = "data/heldout1k/harness_g1"


def build_subset(dest, ids_file=IDS, harness=HARNESS):
    """dest/ = the harness cut to the ids; refuses if any id lacks a task, an env entry or a snapshot. Returns a summary."""
    ids = [ln.strip() for ln in open(ids_file) if ln.strip()]
    want = set(ids)
    dest, harness = Path(dest), Path(harness)
    (dest / "snapshots").mkdir(parents=True, exist_ok=True)
    tasks = [ln for ln in open(harness / "tasks.jsonl") if ln.strip() and json.loads(ln)["instance_id"] in want]
    env = json.loads((harness / "env.json").read_text())
    missing = {"tasks": sorted(want - {json.loads(t)["instance_id"] for t in tasks}), "env": sorted(i for i in ids if i not in env),
               "snapshots": sorted(i for i in ids if not (harness / "snapshots" / f"{i}.tgz").is_file())}
    if any(missing.values()):
        raise SystemExit(f"G1 ids missing from {harness}: {missing}")
    (dest / "tasks.jsonl").write_text("".join(tasks))
    (dest / "ids.txt").write_text("".join(i + "\n" for i in ids))
    (dest / "env.json").write_text(json.dumps({i: env[i] for i in ids}, indent=1))
    man = json.loads((harness / "manifest.json").read_text()) if (harness / "manifest.json").is_file() else {}
    man["g1_subset"] = {"from": str(harness.relative_to(ROOT)) if ROOT in harness.parents else str(harness), "ids": len(ids)}
    (dest / "manifest.json").write_text(json.dumps(man, indent=1))
    for i in ids:
        shutil.copy2(harness / "snapshots" / f"{i}.tgz", dest / "snapshots" / f"{i}.tgz")
    if (dest / "wheels").exists():
        shutil.rmtree(dest / "wheels")
    shutil.copytree(harness / "wheels", dest / "wheels")
    size = sum(f.stat().st_size for f in dest.rglob("*") if f.is_file())
    return {"ids": len(ids), "tasks": len(tasks), "snapshots": len(ids), "wheels": len(list((dest / "wheels").iterdir())), "bytes": size}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--run", required=True); ap.add_argument("--shared")
    ap.add_argument("--ref", default="HEAD"); ap.add_argument("--keep-dir", help="build the subset here and keep it (default: a temp dir)")
    ap.add_argument("--upload", action="store_true", help="really upload (creates S3 objects)")
    a = ap.parse_args(argv)
    from launch import parse_s3
    bucket, prefix = parse_s3(a.run, "--run")
    shared = (a.shared or f"s3://{bucket}/shared").rstrip("/")
    sb, sp = parse_s3(shared, "--shared")
    sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", a.ref], capture_output=True, text=True, check=True).stdout.strip()
    has_job = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", f"{sha}:aws/jobs/g1_teacher.sh"], capture_output=True).returncode == 0
    with tempfile.TemporaryDirectory() as td:
        dest = Path(a.keep_dir or td) / "harness_g1"
        info = build_subset(dest)
        wheels = ROOT / "data" / "raw" / "wheels"
        print(f"1. code   {a.run}/in/code.tgz  <- git archive {sha[:10]} ({a.ref})"
              + ("" if has_job else "  ** that commit has no aws/jobs/g1_teacher.sh: commit aws/ first **"))
        print(f"2. subset {a.run}/in/overlay/{OVERLAY}/  <- {info['tasks']} tasks, {info['snapshots']} snapshots, "
              f"{info['wheels']} wheel files, {info['bytes'] / 1e6:.0f} MB")
        print(f"3. wheels {shared}/raw/wheels/  <- data/raw/wheels ({len(list(wheels.iterdir())) if wheels.is_dir() else 0} files)")
        if not a.upload:
            print("plan only: nothing was uploaded; add --upload")
            return 0 if has_job else 1
        if not has_job:
            raise SystemExit(f"refusing: {a.ref} has no aws/jobs/g1_teacher.sh")
        import g4aws
        import stage
        s3 = g4aws.session().client("s3")
        with tempfile.TemporaryDirectory() as t2:
            tgz = Path(t2) / "code.tgz"
            subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar.gz", "-o", str(tgz), sha], check=True)
            stage.upload(s3, tgz, bucket, f"{prefix}/in/code.tgz")
        stage.upload(s3, dest, bucket, f"{prefix}/in/overlay/{OVERLAY}")
        stage.upload(s3, wheels, sb, f"{sp}/raw/wheels")
    return 0


if __name__ == "__main__":
    sys.exit(main())
