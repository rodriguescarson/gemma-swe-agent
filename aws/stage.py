"""Move files between this Mac and the kit's S3 prefixes, verifying sizes on the far side (no aws CLI: the keys stay in-process).

    python aws/stage.py code   s3://B/runs/ID [--ref HEAD]   # git archive of a commit -> in/code.tgz (commit first)
    python aws/stage.py put    s3://B/runs/ID PATH...        # repo-relative files/dirs -> in/overlay/PATH (job inputs)
    python aws/stage.py shared s3://B/shared LOCAL DEST      # once per bucket: data/raw -> raw, the patched vLLM wheel ->
                                                             #   wheelhouse/<name>.whl, model dirs -> models/g4[-bf16]
    python aws/stage.py fetch  s3://B/runs/ID [DEST]         # out/ -> DEST (default eval/aws/ID)

Uploads skip files already there at the same size, and every run ends by listing the far side and comparing sizes.
"""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import g4aws  # noqa: E402
from launch import parse_s3  # noqa: E402


def listing(s3, bucket, prefix):
    out = {}
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for o in page.get("Contents", []):
            out[o["Key"]] = o["Size"]
    return out


def local_files(path):
    p = Path(path)
    if p.is_file():
        return {"": p}
    return {str(f.relative_to(p)): f for f in sorted(p.rglob("*")) if f.is_file() and "__pycache__" not in f.parts}


def upload(s3, local, bucket, key):
    """local file or dir -> key (a dir's files land under key/). Returns (uploaded, skipped); raises on a size mismatch."""
    files = local_files(local)
    if not files:
        raise SystemExit(f"nothing to upload at {local}")
    keys = {(f"{key}/{rel}" if rel else key): f for rel, f in files.items()}
    have = listing(s3, bucket, key)
    up = 0
    for k, f in keys.items():
        if have.get(k) != f.stat().st_size:
            s3.upload_file(str(f), bucket, k)
            up += 1
    after = listing(s3, bucket, key)
    bad = [k for k, f in keys.items() if after.get(k) != f.stat().st_size]
    if bad:
        raise SystemExit(f"VERIFY FAILED: {len(bad)} object(s) missing or of the wrong size, e.g. {bad[:3]}")
    print(f"s3://{bucket}/{key}: {up} uploaded, {len(keys) - up} already there; {len(keys)} verified by size")
    return up, len(keys) - up


def download(s3, bucket, prefix, dest):
    objs = listing(s3, bucket, prefix.rstrip("/") + "/")
    if not objs:
        raise SystemExit(f"nothing under s3://{bucket}/{prefix}/")
    got = 0
    for k, size in objs.items():
        f = Path(dest) / k[len(prefix.rstrip("/")) + 1:]
        if f.is_file() and f.stat().st_size == size:
            continue
        f.parent.mkdir(parents=True, exist_ok=True)
        s3.download_file(bucket, k, str(f))
        got += 1
    bad = [k for k, size in objs.items() if (Path(dest) / k[len(prefix.rstrip("/")) + 1:]).stat().st_size != size]
    if bad:
        raise SystemExit(f"VERIFY FAILED: {bad[:3]}")
    print(f"{dest}: {got} downloaded, {len(objs) - got} already there; {len(objs)} verified by size")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("code"); c.add_argument("run"); c.add_argument("--ref", default="HEAD")
    p = sub.add_parser("put"); p.add_argument("run"); p.add_argument("paths", nargs="+")
    s = sub.add_parser("shared"); s.add_argument("shared"); s.add_argument("local"); s.add_argument("dest")
    f = sub.add_parser("fetch"); f.add_argument("run"); f.add_argument("dest", nargs="?")
    a = ap.parse_args(argv)
    s3 = g4aws.session().client("s3")
    if a.cmd == "code":
        bucket, prefix = parse_s3(a.run, "run")
        sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", a.ref], capture_output=True, text=True, check=True).stdout.strip()
        with tempfile.TemporaryDirectory() as td:
            tgz = os.path.join(td, "code.tgz")
            subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar.gz", "-o", tgz, sha], check=True)
            upload(s3, tgz, bucket, f"{prefix}/in/code.tgz")
        print(f"code: commit {sha[:10]} ({a.ref}); uncommitted changes are NOT in it")
    elif a.cmd == "put":
        bucket, prefix = parse_s3(a.run, "run")
        for rel in a.paths:
            src = (ROOT / rel).resolve()
            if ROOT not in src.parents:
                raise SystemExit(f"{rel} is outside the repo; overlay paths are repo-relative")
            upload(s3, src, bucket, f"{prefix}/in/overlay/{src.relative_to(ROOT)}")
    elif a.cmd == "shared":
        bucket, prefix = parse_s3(a.shared, "shared")
        upload(s3, a.local, bucket, f"{prefix}/{a.dest.strip('/')}")
    elif a.cmd == "fetch":
        bucket, prefix = parse_s3(a.run, "run")
        download(s3, bucket, f"{prefix}/out", a.dest or str(ROOT / "eval" / "aws" / prefix.rsplit("/", 1)[-1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
