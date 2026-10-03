"""Which target tasks any collection pass has solved (resampling) and which remain (coverage).

    python scripts/collect/solved_ids.py solved|remaining [--target data/pallets/train_ids.txt]
        [--harness-ids data/pallets/harness_train/ids.txt] [--collect-dir eval/collect] [--invalid eval/preflight/train159/invalid.txt]
Prints ids one per line, in target order. A pass counts a task as solved when its s1/task_results.jsonl row has
resolved True (bool or the Pallets runner's "True" string). tests/test_solved_ids.py.
"""
import argparse, glob, json, os, sys


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["solved", "remaining"])
    ap.add_argument("--target", default="data/pallets/train_ids.txt")
    ap.add_argument("--harness-ids", default="data/pallets/harness_train/ids.txt")
    ap.add_argument("--collect-dir", default="eval/collect")
    ap.add_argument("--invalid", default=None)
    a = ap.parse_args(argv)
    target = open(a.target).read().split()
    harness = set(open(a.harness_ids).read().split())
    solved = set()
    for f in glob.glob(os.path.join(a.collect_dir, "*", "s1", "task_results.jsonl")):
        for l in open(f):
            if l.strip():
                r = json.loads(l)
                if str(r.get("resolved")).lower() == "true":
                    solved.add(r["instance_id"])
    invalid = set()
    if a.invalid and os.path.exists(a.invalid):
        invalid = {l.split("\t")[0] for l in open(a.invalid) if l.strip()}
    pool = [t for t in target if t in harness]
    ids = [t for t in pool if t in solved] if a.what == "solved" else [t for t in pool if t not in solved and t not in invalid]
    print("\n".join(ids))
    print(f"{a.what}: {len(ids)} of {len(pool)} packed targets (solved {len(solved & set(pool))}, invalid {len(invalid & set(pool))})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
