#!/usr/bin/env python3
"""The full-population gate a box 74-task run (scripts/a6000/p4_run.py results.jsonl) must pass before the Mac submits
(GAPS "sub15b pre-registration" (b), 2026-10-13): every public id has a row (the last row per id counts), 0 crash rows (the
crash classes of scripts/decide_or_skip.sh), 0 errored rows (scripts/a6000/p4_judge.py's definition: an err that is neither
the 5-minute session timeout nor a budget stop), and solved >= --floor. tests/test_box_p4_gate.py.

    python scripts/box_p4_gate.py RESULTS.jsonl [--ids data/kaggle_valid_ids.txt] [--floor 26]
stdout: one line "PASS|FAIL solved S/N crash C errored E cap H missing M secs T"; exit 0 PASS, 1 FAIL."""
import argparse, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRASH = re.compile(r"not found\.|Tool '[^']+' not found|ContextWindowExceeded|maximum context length|prompt contains at least|"
                   r"KeyError|Context variable not found|No LlmAgent model available")


def judge(rows, ids, floor=26):
    last = {}
    for r in rows:
        if r.get("id") in ids:
            last[r["id"]] = r
    got = [last[i] for i in ids if i in last]
    err = lambda r: str(r.get("err") or "")  # noqa: E731
    rep = {"rows": len(got), "missing": [i for i in ids if i not in last],
           "solved": sum(bool(r.get("resolved")) for r in got),
           "crash_rows": sum(bool(CRASH.search(err(r))) for r in got),
           "errored_rows": sum(bool(err(r)) and "session timeout" not in err(r) and "budget" not in err(r) and not CRASH.search(err(r)) for r in got),
           "cap_hits": sum("session timeout" in err(r) for r in got),
           "secs": round(sum(float(r.get("secs") or 0) for r in got))}
    ok = not rep["missing"] and rep["crash_rows"] == 0 and rep["errored_rows"] == 0 and rep["solved"] >= floor
    return ok, rep


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("results"); ap.add_argument("--ids", default=str(ROOT / "data" / "kaggle_valid_ids.txt")); ap.add_argument("--floor", type=int, default=26)
    a = ap.parse_args(argv)
    ids = [l.strip() for l in open(a.ids) if l.strip()]
    try:
        rows = [json.loads(l) for l in open(a.results) if l.strip()]
    except OSError:
        print(f"FAIL no results at {a.results}")
        return 1
    ok, rep = judge(rows, ids, a.floor)
    print(f"{'PASS' if ok else 'FAIL'} solved {rep['solved']}/{len(ids)} crash {rep['crash_rows']} errored {rep['errored_rows']} cap {rep['cap_hits']} "
          f"missing {len(rep['missing'])} secs {rep['secs']} (floor {a.floor})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
