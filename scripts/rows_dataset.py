#!/usr/bin/env python3
"""Stage JSONL row files as a flat private Kaggle dataset and push it (the Invent rows for the think2 arm, GAPS 2026-10-11; the box
pulls them with `kaggle datasets download -d carsonrodrigues/g4-invent-rows --unzip`). Rows never enter git.

    python scripts/rows_dataset.py FILE.jsonl [FILE2 ...] --slug g4-invent-rows --out /tmp/ds [--push] [--kaggle .venv/bin/kaggle]
Writes dataset-metadata.json (as scripts/adapters_dataset.py) and MANIFEST.json {files: {name: {rows, sha256, bytes}}}; the
create-vs-version decision and the CLI command are adapters_dataset.cli_command. tests/test_rows_dataset.py."""
import argparse, hashlib, json, os, shutil, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from adapters_dataset import cli_command  # noqa: E402


def stage(files, out, owner, slug):
    os.makedirs(out, exist_ok=True)
    manifest, counts = {}, {}
    for f in files:
        name = os.path.basename(f)
        dst = os.path.join(out, name)
        shutil.copyfile(f, dst)
        data = open(dst, "rb").read()
        rows = sum(1 for l in data.split(b"\n") if l.strip())
        manifest[name] = {"rows": rows, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
        counts[name] = rows
    with open(os.path.join(out, "dataset-metadata.json"), "w") as fh:
        json.dump({"title": slug, "id": f"{owner}/{slug}", "licenses": [{"name": "CC0-1.0"}]}, fh, indent=2)
    with open(os.path.join(out, "MANIFEST.json"), "w") as fh:
        json.dump({"slug": f"{owner}/{slug}", "files": manifest}, fh, indent=2)
    return counts


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+"); ap.add_argument("--slug", required=True); ap.add_argument("--owner", default="carsonrodrigues")
    ap.add_argument("--out", required=True); ap.add_argument("--push", action="store_true"); ap.add_argument("--kaggle", default=".venv/bin/kaggle")
    a = ap.parse_args(argv)
    counts = stage(a.files, a.out, a.owner, a.slug)
    print(f"staged {counts} in {a.out} as {a.owner}/{a.slug}")
    if a.push:
        r = subprocess.run([a.kaggle, "datasets", "status", f"{a.owner}/{a.slug}"], capture_output=True, text=True)
        exists = r.returncode == 0 and "not found" not in (r.stdout + r.stderr).lower() and "404" not in (r.stdout + r.stderr)
        cmd = cli_command(a.kaggle, a.out, exists)
        print("pushing:", " ".join(cmd)); out = subprocess.run(cmd, capture_output=True, text=True); print((out.stdout + out.stderr).strip()[-600:])
        if out.returncode != 0:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
