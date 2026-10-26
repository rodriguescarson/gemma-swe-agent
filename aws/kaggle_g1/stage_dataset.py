"""Build and upload the PRIVATE Kaggle dataset the G1 kernels read: carsonrodrigues/g4-g1-harness. Plan only, unless --upload.

    python aws/kaggle_g1/stage_dataset.py [--ref HEAD] [--upload] [--kaggle .venv/bin/kaggle]

Contents (no secrets: tracked code and the open-source task snapshots and PyPI wheels):
  g1_code.tgz      git archive of --ref limited to what the kernels run (scripts/, pod/, harness/, aws/, data/distill/,
                   data/kaggle_pins.txt, submissions/v12b, tests/v10_support for or_proxy's router); the ref must contain
                   aws/kaggle_g1/g1_kaggle.py (commit first)
  harness_g1.tar   the 30 G1 tasks cut from data/heldout1k/harness_all by aws/jobs/g1_stage.build_subset, the same subset
                   the EC2 path staged to S3 (tasks.jsonl, ids.txt, env.json, manifest.json, 30 snapshots, all wheels)
The first upload creates the dataset (private: no --public); later ones add a version. Then it waits until Kaggle reports
the dataset ready.
"""
import argparse
import json
import re
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "aws" / "jobs"))
DATASET = "carsonrodrigues/g4-g1-harness"
CODE_PATHS = ["scripts", "pod", "harness", "aws", "data/distill", "data/kaggle_pins.txt", "submissions/v12b",
              "tests/v10_support"]   # scripts/golden/router.py (or_proxy) imports v10_support.mock_llm
SECRET_RE = re.compile(rb"AKIA[0-9A-Z]{16}|hf_[A-Za-z0-9]{30,}|sk-[A-Za-z0-9]{32,}|-----BEGIN [A-Z ]*PRIVATE KEY-----")


def build(stage, ref):
    sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", ref], capture_output=True, text=True, check=True).stdout.strip()
    if subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", f"{sha}:aws/kaggle_g1/g1_kaggle.py"], capture_output=True).returncode:
        raise SystemExit(f"{ref} has no aws/kaggle_g1/g1_kaggle.py: commit it first")
    code = stage / "g1_code.tgz"
    subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar.gz", "-o", str(code), sha, *CODE_PATHS], check=True)
    with tarfile.open(code) as t:
        hits = [m.name for m in t.getmembers() if m.isfile() and SECRET_RE.search(t.extractfile(m).read())]
    if hits:
        raise SystemExit(f"refusing: secret-looking strings in {hits[:5]}")
    import g1_stage
    with tempfile.TemporaryDirectory() as td:
        info = g1_stage.build_subset(Path(td) / "harness_g1")
        with tarfile.open(stage / "harness_g1.tar", "w") as t:
            t.add(Path(td) / "harness_g1", arcname=".")
    (stage / "dataset-metadata.json").write_text(json.dumps({"title": "g4-g1-harness", "id": DATASET, "licenses": [{"name": "other"}]}, indent=1))
    return sha, info


def kaggle_ok(kaggle, *args):
    r = subprocess.run([kaggle, *args], capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ref", default="HEAD"); ap.add_argument("--upload", action="store_true")
    ap.add_argument("--kaggle", default=str(ROOT / ".venv" / "bin" / "kaggle")); ap.add_argument("--stage")
    a = ap.parse_args(argv)
    with tempfile.TemporaryDirectory() as td:
        stage = Path(a.stage or td); stage.mkdir(parents=True, exist_ok=True)
        sha, info = build(stage, a.ref)
        sizes = {p.name: round(p.stat().st_size / 1e6, 1) for p in stage.iterdir()}
        print(f"dataset {DATASET} (private) from {sha[:10]}: {sizes} MB; subset {info['tasks']} tasks, {info['wheels']} wheel files")
        if not a.upload:
            print("plan only: nothing uploaded; add --upload")
            return 0
        rc, out = kaggle_ok(a.kaggle, "datasets", "status", DATASET)
        exists = rc == 0 and "ready" in out.lower()
        args = (["datasets", "version", "-p", str(stage), "-m", f"G1 subset + code {sha[:10]}"] if exists else ["datasets", "create", "-p", str(stage)])
        rc, out = kaggle_ok(a.kaggle, *args)
        print(out[-600:])
        if rc != 0:
            return 1
        for _ in range(60):
            time.sleep(20)
            rc, out = kaggle_ok(a.kaggle, "datasets", "status", DATASET)
            if "ready" in out.lower():
                print("dataset ready:", DATASET)
                return 0
        print("dataset not ready after 20 min:", out[-300:])
        return 1


if __name__ == "__main__":
    sys.exit(main())
