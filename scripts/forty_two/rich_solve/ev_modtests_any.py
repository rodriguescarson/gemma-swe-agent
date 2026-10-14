"""v13_modtests on any (task, box run): apply the run's final patch (source files only) to the base snapshot and run
tests/test_<module>.py for every rich/<module>.py it edits, without the hidden test_patch; then the same at base for
comparison. Extracts the snapshot into $WT/<id> if it is not there; delete $WT when done.

    [SNAPSHOTS=<dir>] python scripts/forty_two/rich_solve/ev_modtests_any.py $WT $VENV/bin/python rich_3676:p4_b1024 rich_3521:p4_v0t2"""
import json, os, re, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ev_modtests import src_only  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
SNAP = ROOT / "data/raw/snapshots"          # override with SNAPSHOTS=<dir> when data/raw is not in this checkout


def sh(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True, timeout=110)


def summary(wt, py, files):
    r = sh(f"PYTHONPATH=. {py} -m pytest -q -p no:cacheprovider -o python_classes='Test* *Test' {files}", wt)
    out = r.stdout.strip().splitlines()
    return out[-1] if out else r.stderr.strip()[-160:]


def main():
    wt_root, py = Path(sys.argv[1]), sys.argv[2]
    snap = Path(os.environ.get("SNAPSHOTS", str(SNAP)))
    for spec in sys.argv[3:]:
        tid, run = spec.split(":")
        wt = wt_root / tid
        if not wt.exists():
            wt.mkdir(parents=True)
            subprocess.run(["tar", "-xzf", str(snap / f"{tid}.tgz"), "-C", str(wt)], check=True)
        row = [json.loads(l) for l in (ROOT / "eval/a6000/results" / run / "results.jsonl").read_text().splitlines()
               if l.strip() and json.loads(l)["id"] == tid][-1]
        patch = src_only(row["patch"])
        mods = sorted(set(re.findall(r"^diff --git a/rich/(\w+)\.py", patch, re.M)))
        files = " ".join(f"tests/test_{m}.py" for m in mods if (wt / f"tests/test_{m}.py").exists())
        sh("git checkout -q -- . && git clean -fdq", wt)
        base = summary(wt, py, files) if files else "no module test file"
        (wt / "_p.diff").write_text(patch)
        ok = sh("git apply _p.diff && rm _p.diff", wt).returncode == 0
        after = summary(wt, py, files) if (files and ok) else ("patch did not apply" if not ok else "no module test file")
        print(f"{tid} {run} resolved={row['resolved']} edits {mods} -> {files or '-'}\n    base: {base}\n    with the run's patch: {after}")
        sh("git checkout -q -- . && git clean -fdq", wt)


if __name__ == "__main__":
    main()
