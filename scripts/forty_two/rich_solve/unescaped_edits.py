"""How often the edit_file engine's unescape fallback rescued an edit whose text the model had copied with JSON escapes
(observation "strategy": "unescaped"), per box run, and in which tasks (solved or not). v13 drops edit_file, so these edits
would meet v13's exact-match template without that fallback. Run from the repository root.

    python scripts/forty_two/rich_solve/unescaped_edits.py p4_b1024,p4_v0t2"""
import json, sys, collections
from pathlib import Path

for run in sys.argv[1].split(","):
    base = Path("eval/a6000/results") / run
    solved = {json.loads(l)["id"] for l in (base / "results.jsonl").read_text().splitlines()
              if l.strip() and json.loads(l)["resolved"]}
    per = collections.Counter()
    strategies = collections.Counter()
    for p in sorted((base / "results/traces").glob("trace_*.json")):
        tid = p.stem[len("trace_"):]
        for s in json.loads(p.read_text())["steps"]:
            for tc in s.get("tool_calls") or []:
                if tc.get("function_name") != "edit_file":
                    continue
                o = (s.get("observation") or {}).get("content", "") or ""
                try:
                    st = json.loads(o).get("strategy")
                except Exception:
                    st = None
                if st:
                    strategies[st] += 1
                if st == "unescaped":
                    per[tid] += 1
    print(f"{run}: successful edit_file strategies {dict(strategies)}")
    print(f"   unescaped rescues: {sum(per.values())} edits in {len(per)} tasks; in solved tasks: "
          f"{sum(v for k, v in per.items() if k in solved)} edits in {len([k for k in per if k in solved])} tasks")
    print("   ", ", ".join(f"{k}{'*' if k in solved else ''}:{v}" for k, v in sorted(per.items())), "(* = solved)")
