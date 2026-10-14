"""Replay a check script (written from the issue text alone) against a task's base code, every recorded box patch, the
L4 patches that resolved it, and the gold patch. Offline evidence for a "red first" rule: a useful check is red at base,
green on gold, and red on the wrong patches the agent submitted.

    python scripts/forty_two/check_replay.py fastapi_14986 docs/forty_two/evidence/fastapi_checks/fastapi_14986.py

Only the package directory of the snapshot (~/.cache/g4/ws/<id>/base/<pkg>, read only) is copied, into a temp dir per
variant; a patch is reduced to its hunks under <pkg>/ (tests, repro scripts and docs are dropped) and applied with
`patch -p1`. The check runs with the repo's offline venv (~/.cache/g4/kpar/<repo>/bin/python, PYTHONPATH = the variant
dir) under scripts/forty_two/bounded.py (1,500 MB, 60 s). Prints one line per variant: label, applied?, exit, the check's
ISSUE/ORDINARY lines."""
import argparse, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOX_RUNS = ["p4", "p4_v7", "p4_v7c", "p4_v7d", "p4_b1024", "p4_v0t2"]
WS = Path.home() / ".cache" / "g4" / "ws"
KPAR = Path.home() / ".cache" / "g4" / "kpar"


def package_only(patch, pkg):
    """The file sections of a unified diff whose path is under pkg/ (and not a test file)."""
    parts = re.split(r"(?m)^(?=diff --git )", patch)
    keep = []
    for p in parts:
        m = re.match(r"diff --git a/(\S+) b/(\S+)", p)
        if m and m.group(2).startswith(pkg + "/") and "/tests/" not in m.group(2):
            keep.append(p)
    if not keep and patch.startswith("--- a/"):          # gold patches in tasks.jsonl have no "diff --git" header
        for p in re.split(r"(?m)^(?=--- a/)", patch):
            m = re.match(r"--- a/(\S+)", p)
            if m and m.group(1).startswith(pkg + "/"):
                keep.append(p)
    return "".join(keep)


def variants(task_id):
    out = [("base", "")]
    for run in BOX_RUNS:
        f = ROOT / "eval" / "a6000" / "results" / run / "results.jsonl"
        for line in f.read_text().splitlines() if f.exists() else []:
            r = json.loads(line) if line.strip() else {}
            if r.get("id") == task_id:
                out.append((f"box:{run}{' RESOLVED' if r.get('resolved') else ''}", r.get("patch") or ""))
    for f in sorted((ROOT / "eval" / "kaggle").glob("*/results.jsonl")):
        if f.parent.name in ("oracle_all", "rescore_fair"):
            continue
        for line in f.read_text().splitlines():
            r = json.loads(line) if line.strip() else {}
            if (r.get("id") or r.get("instance_id")) == task_id and r.get("resolved"):
                out.append((f"l4:{f.parent.name} RESOLVED", r.get("patch") or ""))
    for line in (ROOT / "data" / "tasks.jsonl").read_text().splitlines():
        t = json.loads(line) if line.strip() else {}
        if t.get("instance_id") == task_id:
            out.append(("gold", t["patch"]))
    return out


def run_variant(task_id, pkg, patch, check, py, tmp):
    d = Path(tempfile.mkdtemp(dir=tmp))
    shutil.copytree(WS / task_id / "base" / pkg, d / pkg)
    body = package_only(patch, pkg)
    applied = "-"
    if body:
        r = subprocess.run(["patch", "-p1", "-s", "--forward", "--no-backup-if-mismatch"], input=body, text=True, cwd=d,
                           capture_output=True)
        applied = "yes" if r.returncode == 0 else "PARTIAL"
    env = dict(os.environ, PYTHONPATH=str(d))
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "forty_two" / "bounded.py"), "--mb", "1500", "--secs", "60",
                        "--", str(py), str(check)], cwd=d, env=env, capture_output=True, text=True)
    lines = [l for l in r.stdout.splitlines() if l.startswith(("ISSUE", "ORDINARY"))]
    err = "" if lines else (r.stderr.strip().splitlines() or [""])[-1][:160]
    shutil.rmtree(d, ignore_errors=True)
    return applied, r.returncode, lines, err


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("task_id"); ap.add_argument("check")
    ap.add_argument("--pkg", default=None)
    a = ap.parse_args()
    repo = a.task_id.rsplit("_", 1)[0]
    pkg = a.pkg or repo
    py = KPAR / repo / "bin" / "python"
    check = Path(a.check).resolve()
    with tempfile.TemporaryDirectory() as tmp:
        for label, patch in variants(a.task_id):
            applied, code, lines, err = run_variant(a.task_id, pkg, patch, check, py, tmp)
            state = "GREEN" if code == 0 else "red"
            print(f"{label:34s} applied={applied:7s} exit={code:<3d} {state:5s} | " + " | ".join(lines) + (f" {err}" if err else ""))


if __name__ == "__main__":
    main()
