"""Stratified sample of heldout1k ids (data/heldout1k/sample200_ids.txt).

  .venv/bin/python scripts/heldout/sample_ids.py [--n 200] [--cap 15] [--title-share 0.2] [--seed 20261006]
                                                 [--out data/heldout1k/sample200_ids.txt]

Per repo: proportional to the repo's task count (largest remainder), at most --cap, at least 1 (every repo appears).
Within the sample, round(n * title_share) title-only rows (statement_title_only), spread over repos in proportion to
their own title-only rows and re-scaled where a repo has too few (or too few with a body). Rows are then drawn per
(repo, title-only) stratum with random.Random(seed) over sorted ids. Output: ids sorted.
"""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEED = 20261006


def _largest_remainder(quota: dict, total: int, lo: dict, hi: dict) -> dict:
    """Integers in [lo, hi] per key summing to total, closest to the real-valued quota."""
    out = {k: min(hi[k], max(lo[k], int(q))) for k, q in quota.items()}
    while sum(out.values()) != total:
        if sum(out.values()) < total:
            ks = [k for k in out if out[k] < hi[k]]
            if not ks:
                raise ValueError("allocation impossible: every stratum is at its upper bound")
            k = max(ks, key=lambda k: (quota[k] - out[k], k))
            out[k] += 1
        else:
            ks = [k for k in out if out[k] > lo[k]]
            if not ks:
                raise ValueError("allocation impossible: every stratum is at its lower bound")
            k = min(ks, key=lambda k: (quota[k] - out[k], k))
            out[k] -= 1
    return out


def _scaled(weights: dict, total: int, lo: dict, hi: dict) -> dict:
    """quota_k = clamp(f * w_k, lo, hi) with f found by bisection so the quotas sum to total."""
    if sum(hi.values()) < total or sum(lo.values()) > total:
        raise ValueError(f"cannot place {total} within bounds (lo {sum(lo.values())}, hi {sum(hi.values())})")
    f_lo, f_hi = 0.0, 1.0
    while sum(min(hi[k], max(lo[k], f_hi * w)) for k, w in weights.items()) < total:
        f_hi *= 2
        if f_hi > 1e9:
            break
    for _ in range(200):
        f = (f_lo + f_hi) / 2
        s = sum(min(hi[k], max(lo[k], f * w)) for k, w in weights.items())
        f_lo, f_hi = (f, f_hi) if s < total else (f_lo, f)
    quota = {k: min(hi[k], max(lo[k], f_hi * w)) for k, w in weights.items()}
    return _largest_remainder(quota, total, lo, hi)


def allocate(sizes: Counter, n: int, cap: int) -> dict:
    lo = {k: 1 for k in sizes}
    hi = {k: min(cap, v) for k, v in sizes.items()}
    return _scaled({k: float(v) for k, v in sizes.items()}, n, lo, hi)


def sample(rows: list, n: int = 200, cap: int = 15, title_share: float = 0.2, seed: int = SEED) -> list:
    by = {}
    for r in rows:
        by.setdefault(r["repo"], {True: [], False: []})[bool(r.get("statement_title_only"))].append(r["instance_id"])
    sizes = Counter({k: len(v[True]) + len(v[False]) for k, v in by.items()})
    alloc = allocate(sizes, n, cap)
    t_total = round(n * title_share)
    lo = {k: max(0, alloc[k] - len(by[k][False])) for k in by}
    hi = {k: min(alloc[k], len(by[k][True])) for k in by}
    w = {k: alloc[k] * len(by[k][True]) / sizes[k] for k in by}
    t_alloc = _scaled(w, t_total, lo, hi)
    rng = random.Random(seed)
    out = []
    for repo in sorted(by):
        for flag, k in ((True, t_alloc[repo]), (False, alloc[repo] - t_alloc[repo])):
            pool = sorted(by[repo][flag])
            out += rng.sample(pool, k)
    return sorted(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=str(ROOT / "data" / "heldout1k" / "tasks.jsonl"))
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--cap", type=int, default=15)
    ap.add_argument("--title-share", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--out", default=str(ROOT / "data" / "heldout1k" / "sample200_ids.txt"))
    a = ap.parse_args()
    rows = [json.loads(ln) for ln in open(a.tasks) if ln.strip()]
    ids = sample(rows, a.n, a.cap, a.title_share, a.seed)
    Path(a.out).write_text("".join(i + "\n" for i in ids))
    by = {r["instance_id"]: r for r in rows}
    per = Counter(by[i]["repo"] for i in ids)
    t = sum(1 for i in ids if by[i].get("statement_title_only"))
    print(f"sample_ids: {len(ids)} ids from {len(per)} repos (max {max(per.values())}/repo), title-only {t} "
          f"({t / len(ids):.0%}) -> {a.out}")
    for repo, k in per.most_common():
        print(f"  {repo:32s} {k:3d}  title-only {sum(1 for i in ids if by[i]['repo'] == repo and by[i].get('statement_title_only'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
