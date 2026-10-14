"""The per-task box queue for the forty_two levers: group the runnable docs/forty_two/queue/<id>.json files by bundle and lay out
k samples per bundle, interleaved (sample 1 of every bundle, then sample 2, ...) so a run cut short still has a sample of every
task. tests/test_forty_two_queue.py.

    python scripts/forty_two/queue_plan.py docs/forty_two/queue [--override id=submissions/v13_x ...] [--write data/forty_two_queue]"""
import argparse, json
from pathlib import Path


def plan(qdir, override=None):
    groups, skipped, k = {}, [], 3
    for f in sorted(Path(qdir).glob("*.json")):
        q = json.loads(f.read_text()); b = (override or {}).get(q["id"], q.get("bundle"))
        if not b:
            skipped.append(q["id"]); continue
        groups.setdefault(Path(b).name, []).append(q["id"]); k = max(k, int(q.get("k", 3)))
    groups = {b: sorted(ids) for b, ids in sorted(groups.items())}
    steps = [{"bundle": b, "sample": s, "out": f"q_{b}_s{s}", "ids": ids} for s in range(1, k + 1) for b, ids in groups.items()]
    return {"groups": groups, "skipped": sorted(skipped), "k": k, "steps": steps}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("qdir"); ap.add_argument("--override", nargs="*", default=[]); ap.add_argument("--write")
    a = ap.parse_args()
    p = plan(a.qdir, dict(o.split("=", 1) for o in a.override))
    if a.write:
        d = Path(a.write); d.mkdir(parents=True, exist_ok=True)
        for b, ids in p["groups"].items():
            (d / f"{b}.txt").write_text("\n".join(ids) + "\n")
        (d / "plan.json").write_text(json.dumps(p, indent=1) + "\n")
    print(f"{sum(len(v) for v in p['groups'].values())} tasks in {len(p['groups'])} bundles, k={p['k']}, {len(p['steps'])} steps; "
          f"not runnable: {len(p['skipped'])}")
    for b, ids in p["groups"].items():
        print(f"  {b:20s} {' '.join(ids)}")


if __name__ == "__main__":
    main()
