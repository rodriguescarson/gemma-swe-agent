"""Offline evidence for v13_modtests: what one run of the edited module's own test file would have shown the agent.

For each (task, box run, test files): apply that run's final patch (source files only, as the harness would leave them) to a
fresh copy of the base snapshot, WITHOUT the task's test_patch (the agent never sees the hidden tests), and run the module's
existing test file. Then the same with the test_patch, for the score. Measured on the Mac with the Kaggle pins.

Setup (once): tar -xzf data/raw/snapshots/<id>.tgz -C $WT/<id>; uv venv -p 3.12 $VENV && VIRTUAL_ENV=$VENV uv pip install
--offline --find-links data/raw/wheels pytest==8.4.2 Pygments==2.20.0 markdown-it-py==4.0.0 mdurl==0.1.2
typing_extensions==4.15.0 attrs==26.1.0 iniconfig==2.3.0 pluggy==1.6.0

    python scripts/forty_two/rich_solve/ev_modtests.py $WT $VENV/bin/python"""
import json, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CASES = [("rich_3777", "p4_b1024", "tests/test_console.py"),
         ("rich_3278", "p4_v0t2", "tests/test_ansi.py"),
         ("rich_3180", "p4_v7d", "tests/test_cells.py tests/test_text.py")]
tasks = {json.loads(l)["instance_id"]: json.loads(l) for l in open(ROOT / "data/tasks.jsonl") if l.strip()}


def sh(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True, timeout=110)


def src_only(patch):
    parts = re.split(r"(?=^diff --git )", patch, flags=re.M)
    keep = []
    for p in parts:
        m = re.match(r"diff --git a/(\S+)", p)
        if not m or "new file mode" in p or re.search(r"(^|/)(tests?/|test_[^/]*\.py$|conftest\.py$)", m.group(1)):
            continue
        keep.append(p)
    s = "".join(keep)
    return s if s.endswith("\n") else s + "\n"


def run_tests(wt, files, py):
    r = sh(f"PYTHONPATH=. {py} -m pytest -q -p no:cacheprovider -o python_classes='Test* *Test' {files}", wt)
    out = r.stdout.strip().splitlines()
    first = next((l for l in out if l.startswith("E ")), "")
    return out[-1] if out else r.stderr[-200:], first


def main():
    wt_root, py = Path(sys.argv[1]), sys.argv[2]
    for tid, run, files in CASES:
        wt = wt_root / tid
        row = [json.loads(l) for l in (ROOT / "eval/a6000/results" / run / "results.jsonl").read_text().splitlines()
               if l.strip() and json.loads(l)["id"] == tid][-1]
        sh("git checkout -q -- . && git clean -fdq", wt)
        (wt / "_p.diff").write_text(src_only(row["patch"]))
        r = sh("git apply _p.diff && rm _p.diff", wt)
        assert r.returncode == 0, r.stderr
        base_summary, first = run_tests(wt, files, py)
        tp = tasks[tid]["test_patch"]
        (wt / "_tp.diff").write_text(tp if tp.endswith("\n") else tp + "\n")
        assert sh("git apply _tp.diff && rm _tp.diff", wt).returncode == 0
        scored, _ = run_tests(wt, files, py)
        print(f"{tid} {run}: existing tests with the run's patch -> {base_summary}")
        print(f"    first error line: {first[:160]}")
        print(f"    with the hidden test_patch (the score) -> {scored}")
        sh("git checkout -q -- . && git clean -fdq", wt)


if __name__ == "__main__":
    main()
