"""Read the per-task box queue (queue_plan.py): per task, solved in how many of k samples; PASS at >= 2 of 3 (ceil(2k/3)), FAIL
otherwise, INCOMPLETE when a sample is missing or errored (an err that is neither the session timeout nor a budget stop, the
definition of scripts/box_p4_gate.py). A lever is ACCEPT when any of its tasks passes and none is INCOMPLETE, INCOMPLETE when any
task is, REJECT otherwise. tests/test_forty_two_queue.py.

    python scripts/forty_two/queue_read.py eval/a6000/results --plan data/forty_two_queue/plan.json"""
import argparse, json, math
from pathlib import Path


def errored(e):
    return bool(e) and "session timeout" not in e and "budget" not in e


def read(root, groups, k=3):
    need = math.ceil(2 * k / 3); tasks, levers = {}, {}
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
            tasks[i] = {"solved": solved, "samples": len(got), "verdict": v}
        vs = [tasks[i]["verdict"] for i in ids]
        levers[b] = "INCOMPLETE" if "INCOMPLETE" in vs else "ACCEPT" if "PASS" in vs else "REJECT"
    return {"tasks": tasks, "levers": levers}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("root"); ap.add_argument("--plan"); ap.add_argument("--groups-json")
    a = ap.parse_args()
    p = json.loads(Path(a.plan).read_text()) if a.plan else {"groups": json.loads(a.groups_json), "k": 3}
    r = read(a.root, p["groups"], p.get("k", 3))
    for b, ids in p["groups"].items():
        print(f"{b:20s} {r['levers'][b]}")
        for i in ids:
            t = r["tasks"][i]; print(f"    {i:16s} {t['solved']}/{t['samples']} {t['verdict']}")


if __name__ == "__main__":
    main()
