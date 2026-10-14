"""Read the per-task box queue (queue_plan.py): per task, solved in how many of k samples; PASS at >= 2 of 3 (ceil(2k/3)), FAIL
otherwise, INCOMPLETE when a sample is missing or errored (an err that is neither the session timeout nor a budget stop, the
definition of scripts/box_p4_gate.py). A lever is ACCEPT when any of its tasks passes and none is INCOMPLETE, INCOMPLETE when any
task is, REJECT otherwise.
With base=<bundle> (the control, e.g. v13): a lever's PASS on a task where the base also PASSES is not credited to the lever
(amendment 2026-10-15, before any queue row). tests/test_forty_two_queue.py.

    python scripts/forty_two/queue_read.py eval/a6000/results --plan data/forty_two_queue/plan.json"""
import argparse, json, math
from pathlib import Path


def errored(e):
    return bool(e) and "session timeout" not in e and "budget" not in e


def read(root, groups, k=3, base=None):
    need = math.ceil(2 * k / 3); tasks, levers, by, credited = {}, {}, {}, {}
    for b, ids in groups.items():
        rows = {}
        for s in range(1, k + 1):
            f = Path(root) / f"q_{b}_s{s}" / "results.jsonl"
            if f.exists():
                for line in f.read_text().splitlines():
                    if line.strip():
                        r = json.loads(line); rows.setdefault(r["id"], {})[s] = r   # the last row per id and sample counts
        for i in ids:
            got = rows.get(i, {}); solved = sum(bool(r.get("resolved")) for r in got.values())
            bad = len(got) < k or any(errored(r.get("err") or "") for r in got.values())
            v = "PASS" if solved >= need and not any(errored(r.get("err") or "") for r in got.values()) else "INCOMPLETE" if bad else "FAIL"
            by.setdefault(b, {})[i] = {"solved": solved, "samples": len(got), "verdict": v}
            if b != base or i not in tasks:
                tasks[i] = by[b][i]
    for b, ids in groups.items():
        base_pass = {i for i, t in by.get(base, {}).items() if t["verdict"] == "PASS"} if base and b != base else set()
        credited[b] = [i for i in ids if by[b][i]["verdict"] == "PASS" and i not in base_pass]
        vs = [by[b][i]["verdict"] for i in ids]
        levers[b] = "INCOMPLETE" if "INCOMPLETE" in vs else "ACCEPT" if credited[b] else "REJECT"
    return {"tasks": tasks, "levers": levers, "by": by, "credited": credited}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("root"); ap.add_argument("--plan"); ap.add_argument("--groups-json"); ap.add_argument("--base")
    a = ap.parse_args()
    p = json.loads(Path(a.plan).read_text()) if a.plan else {"groups": json.loads(a.groups_json), "k": 3}
    r = read(a.root, p["groups"], p.get("k", 3), a.base or p.get("base"))
    for b, ids in p["groups"].items():
        print(f"{b:20s} {r['levers'][b]}  credited: {' '.join(r['credited'][b]) or '-'}")
        for i in ids:
            t = r["by"][b][i]; print(f"    {i:16s} {t['solved']}/{t['samples']} {t['verdict']}")


if __name__ == "__main__":
    main()
