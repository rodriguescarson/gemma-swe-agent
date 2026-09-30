"""Summary of an or_race.sh run: per arm solved / rows / empty patches / errors / time, paired table, sign test, spend.

    python scripts/pallets/or_race_summary.py OUT CONTROL TREAT
"""
import json, math, sys
from pathlib import Path


def rows(p: Path) -> dict:
    return {(r := json.loads(l))["instance_id"]: r for l in p.read_text().splitlines() if l.strip()} if p.exists() else {}


def proxy(p: Path) -> dict:
    rs = [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []
    return {"calls": len(rs), "non200": sum(r.get("status") != 200 for r in rs),
            "retries": sum(r.get("retries") or 0 for r in rs),
            "usd": round(max([r.get("spent_usd") or 0 for r in rs] or [0]), 3),
            "mean_latency_s": round(sum(r.get("latency_s") or 0 for r in rs) / max(1, len(rs)), 2)}


def sign_p(w: int, l: int) -> float:
    n = w + l
    if n == 0:
        return 1.0
    k = min(w, l)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def main(out: str, control: str, treat: str) -> str:
    o = Path(out)
    ids = o.joinpath("ids.txt").read_text().split()
    arms = {b: rows(o / f"pl_{b}" / "task_results.jsonl") for b in (control, treat)}
    lines = [f"Pallets OpenRouter race (PROXY), {len(ids)} tasks: {control} (control) vs {treat} (treatment)"]
    for b, rs in arms.items():
        solved = sum(str(r.get("resolved")) == "True" for r in rs.values())
        empty = sum(str(r.get("agent_patch_size")) in ("0", "None") for r in rs.values())
        errs = sum(str(r.get("error")) not in ("None", "", "null") for r in rs.values())
        secs = [float(r.get("duration_seconds") or 0) for r in rs.values()]
        capped = sum(s >= 295 for s in secs)
        lines.append(f"  {b}: solved {solved}/{len(ids)} (rows {len(rs)}), empty patch {empty}, error rows {errs}, "
                     f"capped {capped}, mean {sum(secs) / max(1, len(secs)):.0f} s/task; proxy {proxy(o / f'proxy_{b}.jsonl')}")
    c, t = arms[control], arms[treat]
    ok = lambda r: r is not None and str(r.get("resolved")) == "True"  # noqa: E731
    w = sum(1 for i in ids if ok(t.get(i)) and not ok(c.get(i)))
    l = sum(1 for i in ids if ok(c.get(i)) and not ok(t.get(i)))
    both = sum(1 for i in ids if ok(c.get(i)) and ok(t.get(i)))
    lines.append(f"  paired: {treat} wins {w}, {control} wins {l}, both {both}; two-sided sign p = {sign_p(w, l):.3f}")
    missing = [i for i in ids if i not in c or i not in t]
    if missing:
        lines.append(f"  INCOMPLETE: {len(missing)} task(s) missing a row in an arm: {' '.join(missing[:10])}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(main(*sys.argv[1:4]))
