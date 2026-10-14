"""Which tasks each run solved, compared across runs: the tasks every run solves (core), none solves (never), some solve (flaky),
the union, each run's unique solves, and a pairwise table. Compared on the ids every run has (a partial run narrows the set).

    python scripts/solve_overlap.py RUN [RUN ...] [--focus NAME]   # RUN = a results dir or a results.jsonl; name = its dir"""
import argparse, itertools, json
from collections import Counter
from pathlib import Path


def load(path):
    p = Path(path); p = p / "results.jsonl" if p.is_dir() else p
    out = {}
    for line in p.read_text().splitlines():
        if line.strip():
            r = json.loads(line); out[r["id"]] = bool(r["resolved"])  # the last row per id wins (a resumed run rewrites it)
    return out


def overlap(runs):
    ids = sorted(set.intersection(*(set(v) for v in runs.values())))
    solved = {n: {i for i in ids if v[i]} for n, v in runs.items()}
    count = {i: sum(i in s for s in solved.values()) for i in ids}
    rep = {"n": len(ids), "dropped": {n: sorted(set(v) - set(ids)) for n, v in runs.items() if set(v) - set(ids)},
           "core": [i for i in ids if count[i] == len(runs)], "never": [i for i in ids if count[i] == 0],
           "flaky": [i for i in ids if 0 < count[i] < len(runs)], "union": sum(c > 0 for c in count.values()),
           "by_count": dict(sorted(Counter(count.values()).items())), "count": count, "solved": solved, "runs": {}, "pairs": {}}
    for n, s in solved.items():
        others = set().union(*(solved[m] for m in solved if m != n))
        rep["runs"][n] = {"solved": len(s), "unique": sorted(s - others)}
    for a, b in itertools.combinations(solved, 2):
        rep["pairs"][(a, b)] = {"both": len(solved[a] & solved[b]), "a_only": len(solved[a] - solved[b]),
                                "b_only": len(solved[b] - solved[a]), "union": len(solved[a] | solved[b])}
    return rep


def name_of(path):
    p = Path(path)
    return (p.parent if p.name == "results.jsonl" else p).name


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("runs", nargs="+"); ap.add_argument("--focus")
    a = ap.parse_args()
    r = overlap({name_of(p): load(p) for p in a.runs})
    w = max(len(n) for n in r["runs"])
    print(f"tasks compared {r['n']} | union {r['union']} | core {len(r['core'])} | never {len(r['never'])} | flaky {len(r['flaky'])}")
    for n, d in r["dropped"].items():
        print(f"  {n}: {len(d)} ids left out (not in every run)")
    print("tasks by number of runs solving them:", " ".join(f"{k}:{v}" for k, v in r["by_count"].items()))
    for n, d in r["runs"].items():
        print(f"{n:{w}s} solved {d['solved']:3d} | unique {len(d['unique'])}{' ' + ' '.join(d['unique']) if d['unique'] else ''}")
    print(f"{'':{w}s} {'':{w}s} both a_only b_only union")
    for (x, y), d in r["pairs"].items():
        print(f"{x:{w}s} {y:{w}s} {d['both']:4d} {d['a_only']:6d} {d['b_only']:6d} {d['union']:5d}")
    if a.focus:
        s, k = r["solved"][a.focus], len(r["runs"]) - 1
        print(f"{a.focus} only: {' '.join(r['runs'][a.focus]['unique']) or '-'}")
        missed = [i for i in sorted(r["count"]) if i not in s and r["count"][i] >= min(2, k)]
        print(f"{a.focus} missed, solved by >= {min(2, k)} others: {' '.join(missed) or '-'}")


if __name__ == "__main__":
    main()
