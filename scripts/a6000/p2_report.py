"""Summary and health check of a scripts/a6000/p2_race.py output dir (pre-registered reading rule: docs/v4h/GATE.md, 'P2').

    python scripts/a6000/p2_report.py OUT [--arms v4h2 v6p v6p-think] [--base v4h2]

Per arm: finished tasks, solved (Wilson 95%), empty patches, errored rows (neither cap nor budget), cap hits, median task seconds,
loops (a stage's identical tool call >= 5 times in a row), helper reachability. Health flags: median under 60 s, more than 10% of rows
errored. Per contrast against --base: paired wins/losses on tasks valid in both arms, sign test, cap-hit gap, verdict."""
import argparse, glob, json, os, statistics, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent))
from p2_lib import sign_p, verdict, wilson  # noqa: E402
from autopilot_lib import is_infra_error  # noqa: E402

CAP_TEXT, BUDGET_TEXT, VERIFY_TEXT = "session timeout", "budget", "Failed to apply test_patch"


def classify(r):
    tags, err = set(), r.get("error")
    if r.get("resolved"):
        tags.add("solved")
    if err:
        if CAP_TEXT in err:
            tags.add("cap")
        elif BUDGET_TEXT in err:
            tags.add("budget")
        elif VERIFY_TEXT in err:
            tags.add("verify")           # the agent's patch collides with the test patch: the scorer counts it unsolved
        else:
            tags.add("error")
            if is_infra_error(err) or err.startswith("EXC"):
                tags.add("infra")        # model server / network / harness exception: re-run, and excluded from the pairing
    if not r.get("agent_patch_size"):
        tags.add("empty")
    return tags


def load_rows(out, arm, ids=None):
    rows = {}
    for f in sorted(glob.glob(os.path.join(out, "items", arm, "*", "task_results.jsonl"))):
        for line in open(f):
            if line.strip():
                r = json.loads(line)
                if ids is None or r["instance_id"] in ids:
                    rows[r["instance_id"]] = r
    return rows


def _calls(step):
    tc = step.get("tool_calls") or []
    return [(c.get("function_name"), json.dumps(c.get("arguments"), sort_keys=True, default=str)) for c in tc]


def has_loop(trace, n=5):
    last, run, author = None, 0, None
    for s in trace.get("steps", []):
        for c in _calls(s):
            a = (s.get("extra") or {}).get("author")
            run = run + 1 if (c == last and a == author) else 1
            last, author = c, a
            if run >= n:
                return True
    return False


def loops(out, arm):
    k = 0
    for f in glob.glob(os.path.join(out, "items", arm, "*", "traces", "trace_*.json")):
        try:
            k += has_loop(json.load(open(f)))
        except Exception:
            pass
    return k


def helper_report(out, arm):
    """scripts/analyze_helper_reachability.py reads <run>/results/traces; link the per-task trace dirs into one such tree."""
    root = Path(out) / "report_links" / arm / "results" / "traces"
    root.mkdir(parents=True, exist_ok=True)
    for f in glob.glob(os.path.join(out, "items", arm, "*", "traces", "trace_*.json")):
        dst = root / os.path.basename(f)
        if not dst.exists():
            os.symlink(f, dst)
    try:
        import analyze_helper_reachability as ahr
        rep = ahr.analyse(str(Path(out) / "report_links" / arm))
        return {"tasks": rep["tasks"], "tasks_with_failure": rep["tasks_with_failure"]}
    except Exception as e:                                   # the analyzer is optional for the health check
        return {"error": repr(e)[:80]}


def summarize(out, arms, ids=None):
    res = {}
    ids = set(ids) if ids is not None else None
    for arm in arms:
        rows = load_rows(out, arm, ids)
        tags = {t: classify(r) for t, r in rows.items()}
        n = len(rows)
        secs = [float(r.get("duration_seconds") or 0) for r in rows.values()]
        d = {"n": n, "solved": sum("solved" in t for t in tags.values()), "empty": sum("empty" in t for t in tags.values()),
             "errors": sum("error" in t for t in tags.values()), "infra": sum("infra" in t for t in tags.values()),
             "verify": sum("verify" in t for t in tags.values()), "cap": sum("cap" in t for t in tags.values()),
             "budget": sum("budget" in t for t in tags.values()), "median_s": statistics.median(secs) if secs else None,
             "loops": loops(out, arm)}
        d["ci"] = wilson(d["solved"], n)
        d["flags"] = []
        if secs and d["median_s"] < 60:
            d["flags"].append("median under 60 s")
        if n and d["errors"] / n > 0.10:
            d["flags"].append(f"{d['errors']}/{n} errored (>10%)")
        res[arm] = d
    return res


def contrast(out, arm, base, ids=None):
    ids = set(ids) if ids is not None else None
    a, b = load_rows(out, arm, ids), load_rows(out, base, ids)
    bad = lambda r: "infra" in classify(r)
    common = [t for t in a if t in b and not bad(a[t]) and not bad(b[t])]
    wins = sum(bool(a[t].get("resolved")) and not b[t].get("resolved") for t in common)
    losses = sum(bool(b[t].get("resolved")) and not a[t].get("resolved") for t in common)
    cap = lambda rows: sum("cap" in classify(r) for r in rows.values()) / max(1, len(rows))
    gap = cap(a) - cap(b)
    nc = [t for t in common if "cap" not in classify(a[t]) and "cap" not in classify(b[t])]
    return {"arm": arm, "base": base, "n": len(common), "wins": wins, "losses": losses, "p": sign_p(wins, losses), "cap_gap": gap,
            "verdict": verdict(wins, losses, gap), "n_nocap": len(nc),
            "wins_nocap": sum(bool(a[t].get("resolved")) and not b[t].get("resolved") for t in nc),
            "losses_nocap": sum(bool(b[t].get("resolved")) and not a[t].get("resolved") for t in nc)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out"); ap.add_argument("--arms", nargs="+", default=["v4h2", "v6p", "v6p-think"]); ap.add_argument("--base", default="v4h2")
    a = ap.parse_args(argv)
    s = summarize(a.out, a.arms)
    print(f"{'arm':10s} {'done':>5s} {'solved':>7s} {'CI95':>13s} {'empty':>6s} {'err':>4s} {'cap':>4s} {'budget':>6s} {'median_s':>8s} {'loops':>5s}  helper")
    for arm, d in s.items():
        h = helper_report(a.out, arm)
        print(f"{arm:10s} {d['n']:5d} {d['solved']:7d} {d['ci'][0]:.3f}-{d['ci'][1]:.3f} {d['empty']:6d} {d['errors']:4d} {d['cap']:4d} "
              f"{d['budget']:6d} {(d['median_s'] or 0):8.1f} {d['loops']:5d}  {h}  " + ("FLAGS: " + "; ".join(d["flags"]) if d["flags"] else ""))
    for arm in a.arms:
        if arm != a.base:
            c = contrast(a.out, arm, a.base)
            print(f"{arm} vs {a.base}: n={c['n']} wins {c['wins']} losses {c['losses']} sign p={c['p']:.3f} cap gap {c['cap_gap']:+.2f} "
                  f"-> {c['verdict']}  (no-cap tasks: n={c['n_nocap']} {c['wins_nocap']}/{c['losses_nocap']})")


if __name__ == "__main__":
    main()
