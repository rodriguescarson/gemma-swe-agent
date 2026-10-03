"""Fold task_results.prev.jsonl (the copy taken before a resumed run) back into task_results.jsonl.

    python scripts/collect/merge_results.py <sample dir, e.g. eval/collect/<tag>/s1>
swegemma/results.py appends one row per finished task but rewrites task_results.jsonl at the end of the run with only
that run's tasks, so every resumed pass dropped its earlier rows. One row per instance_id, the new run's row wins; the
prev file is removed afterwards. Stdlib only (runs inside the pod-emulation container). tests/test_merge_results.py.
"""
import json, os, sys


def main(argv=None):
    d = (argv or sys.argv[1:])[0]
    cur, prev = os.path.join(d, "task_results.jsonl"), os.path.join(d, "task_results.prev.jsonl")
    if not os.path.exists(prev):
        print(f"{d}: no prev file, nothing to merge"); return 0
    rows = {}
    for p in (prev, cur):
        if os.path.exists(p):
            for l in open(p):
                if l.strip():
                    r = json.loads(l); rows[r["instance_id"]] = r
    with open(cur, "w") as f:
        for r in rows.values():
            f.write(json.dumps(r) + "\n")
    os.remove(prev)
    print(f"{d}: {len(rows)} rows after merging prev into task_results.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
