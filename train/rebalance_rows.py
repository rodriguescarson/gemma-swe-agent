"""Reshape build_sft rows for the next adapter (v11b): the V-1 probe showed v11a learned a read_file repeat loop from
rows that are 92% tool-call continuations with 24% read_file calls (docs/v11/GA_PROBE.md).

    python train/rebalance_rows.py rows.jsonl --out rows_v11b.jsonl --report rep.json [--seed 1]
        [--drop-repeats] [--max-tool-share read_file=0.15 ...] [--max-per-task 200]
        [--holdout-tasks ids.txt --holdout-out holdout.jsonl]
Order: holdout split -> drop repeats (a completion already emitted for the same task) -> per-tool share cap (random,
seeded; text-reply rows never dropped) -> per-task cap (random, seeded; text-reply rows never dropped).
tests/test_rebalance_rows.py.
"""
import argparse, collections, json, random, sys


def profile(rows):
    return {"rows": len(rows), "tasks": len({r["meta"]["task"] for r in rows}),
            "tools": dict(collections.Counter(r["meta"].get("tool") for r in rows).most_common(10)),
            "stages": dict(collections.Counter(r["meta"].get("stage") for r in rows)),
            "replies": sum(1 for r in rows if r["meta"].get("tool") is None)}


def rebalance(rows, drop_repeats=False, tool_share=None, max_per_task=None, holdout=frozenset(), seed=1, drop_unknown=False):
    rng = random.Random(seed); dropped = collections.Counter()
    if drop_unknown:
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
        from validate_rows import KNOWN_TOOLS
        n0 = len(rows); rows = [r for r in rows if r["meta"].get("tool") is None or r["meta"].get("tool") in KNOWN_TOOLS]
        dropped["unknown_tool"] = n0 - len(rows)
    held = [r for r in rows if r["meta"]["task"] in holdout]
    rows = [r for r in rows if r["meta"]["task"] not in holdout]
    if drop_repeats:
        seen, kept = set(), []
        for r in rows:
            key = (r["meta"].get("traj") or r["meta"]["task"], r["completion"])   # within one run when known
            if r["meta"].get("tool") is not None and key in seen:
                dropped["repeats"] += 1; continue
            seen.add(key); kept.append(r)
        rows = kept
    for tool, share in (tool_share or {}).items():
        idx = [i for i, r in enumerate(rows) if r["meta"].get("tool") == tool]
        others = len(rows) - len(idx)
        allowed = int(share * others / max(1e-9, 1 - share))        # n_tool / (n_tool + others) <= share
        if len(idx) > allowed:
            drop = set(rng.sample(idx, len(idx) - allowed)); dropped["tool_share"] += len(drop)
            rows = [r for i, r in enumerate(rows) if i not in drop]
    if max_per_task:
        by_task = collections.defaultdict(list)
        for i, r in enumerate(rows): by_task[r["meta"]["task"]].append(i)
        drop = set()
        for t, idx in by_task.items():
            if len(idx) <= max_per_task: continue
            replies = [i for i in idx if rows[i]["meta"].get("tool") is None]
            pool = [i for i in idx if rows[i]["meta"].get("tool") is not None]
            keep_n = max(0, max_per_task - len(replies))
            drop |= set(rng.sample(pool, len(pool) - keep_n)) if len(pool) > keep_n else set()
        dropped["per_task"] += len(drop)
        rows = [r for i, r in enumerate(rows) if i not in drop]
    return rows, held, dict(dropped)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("rows"); ap.add_argument("--out", required=True); ap.add_argument("--report", required=True)
    ap.add_argument("--seed", type=int, default=1); ap.add_argument("--drop-repeats", action="store_true")
    ap.add_argument("--drop-unknown-tools", action="store_true")
    ap.add_argument("--max-tool-share", action="append", default=[], metavar="TOOL=SHARE")
    ap.add_argument("--max-per-task", type=int, default=None)
    ap.add_argument("--holdout-tasks", default=None); ap.add_argument("--holdout-out", default=None)
    a = ap.parse_args(argv)
    rows = [json.loads(l) for l in open(a.rows) if l.strip()]
    share = {k: float(v) for k, v in (s.split("=") for s in a.max_tool_share)}
    hold = frozenset(l.strip() for l in open(a.holdout_tasks) if l.strip()) if a.holdout_tasks else frozenset()
    before = profile(rows)
    out, held, dropped = rebalance(rows, a.drop_repeats, share, a.max_per_task, hold, a.seed, a.drop_unknown_tools)
    with open(a.out, "w") as f:
        for r in out: f.write(json.dumps(r) + "\n")
    if a.holdout_out:
        with open(a.holdout_out, "w") as f:
            for r in held: f.write(json.dumps(r) + "\n")
    rep = {"before": before, "after": profile(out), "held_out_rows": len(held), "dropped": dropped,
           "options": {"drop_repeats": a.drop_repeats, "max_tool_share": share, "max_per_task": a.max_per_task, "seed": a.seed}}
    json.dump(rep, open(a.report, "w"), indent=1)
    print(json.dumps({k: rep[k] for k in ("before", "after", "dropped", "held_out_rows")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
