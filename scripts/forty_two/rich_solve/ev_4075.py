"""rich_4075: is p4_b1024's own diagnosis (call 11, 52 s: "if not objects: objects = (NewLine(),)" ignores end) enough to
solve it, through v13's edit template? Writes the edit it named at 263 s (objects = ("",)) on the base snapshot, first with
the two-line block it wrote (it occurs twice: Console.print and Console.log), then with one more line of context for print
only, then for print and log; runs the hidden test file each time. Setup as in ev_modtests.py.

    .venv/bin/python scripts/forty_two/rich_solve/ev_4075.py $WT $VENV/bin/python"""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ev_jsonesc import fill, sh, template  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
TID = "rich_4075"
BLOCK = "        if not objects:\n            objects = (NewLine(),)\n"
NEW = "        if not objects:\n            objects = (\"\",)\n"
PRINT_CTX = "            new_line_start (bool, False): Insert a new line at the start if the output contains more than one line. Defaults to ``False``.\n        \"\"\"\n"
LOG_CTX = "            _stack_offset (int, optional): Offset of caller from end of call stack. Defaults to 1.\n        \"\"\"\n"


def main():
    wt, py = Path(sys.argv[1]) / TID, sys.argv[2]
    rows = [json.loads(l) for l in open(ROOT / "data/tasks.jsonl") if l.strip()]
    tp = [t for t in rows if t["instance_id"] == TID][0]["test_patch"]
    cases = [("the two-line block p4_b1024 wrote", [(BLOCK, NEW)]),
             ("print only, one docstring line of context", [(PRINT_CTX + BLOCK, PRINT_CTX + NEW)]),
             ("print and log", [(PRINT_CTX + BLOCK, PRINT_CTX + NEW), (LOG_CTX + BLOCK, LOG_CTX + NEW)])]
    for label, edits in cases:
        sh("git checkout -q -- . && git clean -fdq", wt)
        outs, ok = [], True
        for old, new in edits:
            r = sh(fill(template(), "rich/console.py", old, new), wt, py)
            outs.append(r.stdout.strip() or r.stderr.strip().splitlines()[-1])
            ok = ok and r.returncode == 0
        res = "; ".join(outs)
        if ok:
            (wt / "_tp.diff").write_text(tp if tp.endswith("\n") else tp + "\n")
            assert sh("git apply _tp.diff && rm _tp.diff", wt).returncode == 0
            t = sh(f"PYTHONPATH=. {py} -m pytest -q -p no:cacheprovider tests/test_console.py", wt)
            res += " | tests/test_console.py with the hidden test: " + t.stdout.strip().splitlines()[-1]
        print(f"{label}: {res}")
        sh("git checkout -q -- . && git clean -fdq", wt)


if __name__ == "__main__":
    main()
