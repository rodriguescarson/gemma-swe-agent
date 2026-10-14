"""Print the added/removed lines of each box run's final patch for one task that match a regex (results.jsonl 'patch').

    python scripts/forty_two/rich_solve/patch_lines.py rich_3777 "TTY_INTERACTIVE|tty_interactive" """
import json, re, sys
from pathlib import Path

RUNS = ["p4", "p4_v7", "p4_v7c", "p4_v7d", "p4_b1024", "p4_v0t2"]
tid, pat = sys.argv[1], re.compile(sys.argv[2])
runs = sys.argv[3].split(",") if len(sys.argv) > 3 else RUNS
for run in runs:
    rows = [json.loads(l) for l in (Path("eval/a6000/results") / run / "results.jsonl").read_text().splitlines() if l.strip()]
    rows = [r for r in rows if r["id"] == tid]
    if not rows:
        print(f"{run}: no row"); continue
    r = rows[-1]
    lines = [l for l in r["patch"].splitlines() if l[:1] in "+-" and not l.startswith(("+++", "---")) and pat.search(l)]
    print(f"{run} resolved={r['resolved']} files={re.findall(r'^diff --git a/(\S+)', r['patch'], re.M)}")
    for l in lines:
        print("   ", l[:200])
