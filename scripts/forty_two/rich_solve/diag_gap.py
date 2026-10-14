"""Gap between saying the cause is found and the first edit, per task, in recorded box traces. A 'diagnosis' is the first
agent message that matches DIAG (the model's own words: culprit, root cause, found the bug/issue/problem, this is the bug).
Prints the call and time of that message, of the first edit, the calls used, and the outcome. Run from the repository root.

    .venv/bin/python scripts/forty_two/rich_solve/diag_gap.py p4_b1024 [p4_v0t2]"""
import json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scan_runs import is_edit  # noqa: E402

DIAG = re.compile(r"(?i)\bculprit\b|\broot cause\b|found the (bug|issue|problem|cause)|this is the (bug|cause)|"
                  r"that's the (bug|cause)|the bug is (in|that|here)")

for run in sys.argv[1:]:
    base = Path("eval/a6000/results") / run
    res = {json.loads(l)["id"]: json.loads(l) for l in (base / "results.jsonl").read_text().splitlines() if l.strip()}
    rows = []
    for p in sorted((base / "results/traces").glob("trace_*.json")):
        tid = p.stem[len("trace_"):]
        n = 0
        diag = edit = None
        for s in json.loads(p.read_text())["steps"]:
            if s.get("source") != "agent":
                continue
            o = (s.get("observation") or {}).get("content", "") or ""
            msg = s.get("message") or ""
            if diag is None and DIAG.search(msg):
                diag = (n, round(((s.get("tool_calls") or [{}])[0].get("extra") or {}).get("elapsed_s") or 0))
            for tc in s.get("tool_calls") or []:
                fn, a = tc.get("function_name"), tc.get("arguments") or {}
                if fn in ("submit_patch", "get_status") or '"error": "Invoking' in o:
                    continue
                n += 1
                if edit is None and is_edit(fn, a, o):
                    edit = (n, round((tc.get("extra") or {}).get("elapsed_s") or 0))
        r = res.get(tid, {})
        if diag:
            gap = (edit[0] - diag[0]) if edit else None
            rows.append((tid, r.get("resolved"), diag, edit, n, gap))
    print(f"{run}: {len(rows)} tasks with a diagnosis message")
    for tid, ok, diag, edit, n, gap in sorted(rows, key=lambda x: (x[5] is not None, x[5] or 0), reverse=True):
        print(f"   {tid:15} {'SOLVED' if ok else 'failed'}  diagnosis at call {diag[0]} ({diag[1]} s)  first edit "
              f"{'call %d (%d s)' % edit if edit else 'none'}  calls {n}  gap {gap if gap is not None else '-'}")
