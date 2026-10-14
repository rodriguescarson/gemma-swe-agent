"""Offline evidence for v13_flagvals: the value convention the rule prescribes is sufficient for the hidden tests, and the
variants the box runs wrote are not. Applies a source change to the base snapshot, then the task's test_patch, then runs the
target test file. Setup as in ev_modtests.py.

    python scripts/forty_two/rich_solve/ev_flagvals.py . $WT $VENV/bin/python"""
import json, subprocess, sys
from pathlib import Path

repo, wt_root, py = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
tasks = {json.loads(l)["instance_id"]: json.loads(l) for l in open(repo / "data/tasks.jsonl") if l.strip()}

OLD_3777 = """        self.is_interactive = (
            (self.is_terminal and not self.is_dumb_terminal)
            if force_interactive is None
            else force_interactive
        )
"""
RULE_3777 = """        tty_interactive = self._environ.get("TTY_INTERACTIVE", "")
        if force_interactive is not None:
            self.is_interactive = force_interactive
        elif tty_interactive == "0":
            self.is_interactive = False
        elif tty_interactive == "1":
            self.is_interactive = True
        else:
            self.is_interactive = self.is_terminal and not self.is_dumb_terminal
"""
ZERO_ONLY_3777 = """        self.is_interactive = (
            (self.is_terminal and not self.is_dumb_terminal)
            if force_interactive is None
            else force_interactive
        ) and self._environ.get("TTY_INTERACTIVE") != "0"
"""
OLD_3675 = """        isatty: Optional[Callable[[], bool]] = getattr(self.file, "isatty", None)
"""
RULE_3675 = """        tty_compatible = self._environ.get("TTY_COMPATIBLE", "")
        if tty_compatible == "1":
            return True
        if tty_compatible == "0":
            return False

        isatty: Optional[Callable[[], bool]] = getattr(self.file, "isatty", None)
"""
ANY_3675 = """        if self._environ.get("TTY_COMPATIBLE") is not None:
            self._force_terminal = True
            return True

        isatty: Optional[Callable[[], bool]] = getattr(self.file, "isatty", None)
"""
CASES = [
    ("rich_3777", "rule: 0 off, 1 on, other values auto (copied from the named sibling)", OLD_3777, RULE_3777),
    ("rich_3777", "0-only (what p4 and p4_v7 wrote)", OLD_3777, ZERO_ONLY_3777),
    ("rich_3675", "rule: 1 on, 0 off, other values (unset, empty, unknown) keep auto-detect", OLD_3675, RULE_3675),
    ("rich_3675", "any value means terminal (what all six box runs wrote, FORCE_COLOR's shape)", OLD_3675, ANY_3675),
]


def sh(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True, timeout=110)


for tid, label, old, new in CASES:
    wt = wt_root / tid
    sh("git checkout -q -- . && git clean -fdq", wt)
    f = wt / "rich/console.py"
    s = f.read_text()
    assert s.count(old) == 1, (tid, s.count(old))
    f.write_text(s.replace(old, new, 1))
    tp = tasks[tid]["test_patch"]; (wt / "_tp.diff").write_text(tp if tp.endswith("\n") else tp + "\n")
    r = sh("git apply _tp.diff && rm _tp.diff", wt)
    assert r.returncode == 0, r.stderr
    f2p = json.loads((repo / f"docs/forty_two/ground_truth/{tid}.json").read_text())["FAIL_TO_PASS"]
    r = sh(f"PYTHONPATH=. {py} -m pytest -q -p no:cacheprovider tests/test_console.py", wt)
    r2 = sh(f"PYTHONPATH=. {py} -m pytest -q -p no:cacheprovider " + " ".join(f2p), wt)
    print(f"{tid} | {label}\n    test_console.py: {r.stdout.strip().splitlines()[-1]}\n    F2P {f2p}: {r2.stdout.strip().splitlines()[-1]}")
    sh("git checkout -q -- . && git clean -fdq", wt)
