"""Per run x task, from the recorded box traces: calls (malformed calls not counted, as in the harness), first and last edit call,
first budget_warning call, BudgetExceeded call, pytest/unittest runs and those after the last edit, resolved. Run from the
repository root.

    python scripts/forty_two/rich_solve/scan_runs.py . p4_b1024,p4_v0t2 [rich_3777,rich_4075]"""
import json, re, sys
from pathlib import Path

ROOT = Path(sys.argv[1]) if __name__ == "__main__" else Path(".")
RUNS = sys.argv[2].split(",") if __name__ == "__main__" else []
NEVER = set((ROOT / "data/never_solved_box5_ids.txt").read_text().split())

EDIT_RE = re.compile(r"<<'EDIT'|/tmp/swe/edit\.py|\bsed -i\b|\.write_text\(|\.write_bytes\(|open\([^)]*['\"]w")


def is_edit(fn, args, obs):
    if fn in ("edit_file", "write_file"):
        return '"status": "ok"' in obs
    if fn == "run_command":
        c = str(args.get("command", ""))
        return bool(EDIT_RE.search(c)) and '"exit_code": 0' in obs and "/tmp/" not in c.split("\n")[0][:0]
    return False


def is_test(fn, args):
    if fn != "run_command":
        return False
    c = str(args.get("command", ""))
    return "pytest" in c or "/tmp/swe/test.py" in c or "unittest" in c


def rows(run):
    out = {}
    p = ROOT / "eval/a6000/results" / run / "results.jsonl"
    for l in p.read_text().splitlines():
        if l.strip():
            r = json.loads(l)
            out[r["id"]] = r
    return out


def scan(run, tid):
    tp = ROOT / "eval/a6000/results" / run / "results/traces" / f"trace_{tid}.json"
    if not tp.exists():
        return None
    d = json.loads(tp.read_text())
    n = 0
    first_edit = warn = exceeded = None
    edits = []
    tests = []
    for s in d["steps"]:
        if s["source"] != "agent":
            continue
        obs = (s.get("observation") or {}).get("content", "") or ""
        for tc in s.get("tool_calls") or []:
            fn = tc.get("function_name")
            a = tc.get("arguments") or {}
            if fn in ("submit_patch", "get_status", None):
                continue
            if "BudgetExceeded" in obs and exceeded is None:
                exceeded = n + 1
            if '"error": "Invoking' in obs:
                continue          # malformed: not counted by the harness
            n += 1
            if "budget_warning" in obs and warn is None:
                warn = n
            if is_edit(fn, a, obs):
                edits.append(n)
                if first_edit is None:
                    first_edit = n
            if is_test(fn, a):
                tests.append(n)
    last_edit = edits[-1] if edits else None
    tests_after = [t for t in tests if last_edit and t > last_edit]
    return dict(calls=n, first_edit=first_edit, last_edit=last_edit, warn=warn, exceeded=exceeded,
                n_tests=len(tests), tests_after_last_edit=len(tests_after))


if __name__ == "__main__":
    ids = sys.argv[3].split(",") if len(sys.argv) > 3 else None
    for run in RUNS:
        rr = rows(run)
        for tid in sorted(ids or rr):
            s = scan(run, tid)
            r = rr.get(tid, {})
            print(run, tid, "NEVER" if tid in NEVER else "solv?", "R" if r.get("resolved") else "-", r.get("calls"), round(r.get("secs") or 0), s)
