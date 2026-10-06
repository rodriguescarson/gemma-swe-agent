"""Step 1 of the P2 pre-registration + addendum 2 (docs/v4h/GATE.md): the arm-pure concurrency probe. Each (arm, T) runs the last 4 ids at T task-runs in
flight behind a fresh pace proxy (own log); one container for all of them. S(arm, T) = effective slowdown, m(arm, T) = mean item wall seconds.

    python scripts/a6000/p2_probe.py OUT --harness H --ids IDS [--arms v4h2 v6p] [--levels 1 2]     # measure; merges into OUT/probe_summary.json
    python scripts/a6000/p2_probe.py OUT --harness H --ids IDS --arms v6p-think --levels 2              # the think arm at the chosen C

After every run it prints the decision (p2_lib.decide: the C with the smaller projected hours, per-arm scales, stage 200/100/50)."""
import argparse, json, os, subprocess, sys, time, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import p2_lib, p2_race  # noqa: E402

BRIDGE = "172.18.0.1"      # docker0: where the container's host.docker.internal (host-gateway) points


def run_level(out, arm, T, a, py):
    tag = f"{arm}_T{T}"
    log = Path(out) / f"proxy_{tag}.jsonl"
    log.unlink(missing_ok=True)
    proxy = subprocess.Popen([py, str(HERE / "pace_proxy.py"), "--listen", str(a.port), "--host", BRIDGE, "--rewrite-model", "--log", str(log)],
                             stdout=open(Path(out) / f"proxy_{tag}.out", "w"), stderr=subprocess.STDOUT)
    try:
        for _ in range(30):
            try:
                urllib.request.urlopen(f"http://{BRIDGE}:{a.port}/v1/models", timeout=3); break
            except Exception:
                time.sleep(1)
        t0 = time.time()
        rc = p2_race.main([str(out), "--harness", a.harness, "--ids", a.ids, "--ids-from-end", str(a.n_tasks), "--arms", arm, "--conc", str(T),
                           "--port", str(a.port), "--label", "probe", "--items-dir", f"probe_{tag}", "--keep"])
        wall = time.time() - t0
    finally:
        proxy.terminate(); proxy.wait(timeout=30)
    rows = [json.loads(l) for l in open(log)] if log.exists() else []
    jl = Path(out) / f"probe_{tag}.jsonl"
    items = [json.loads(l) for l in open(jl)] if jl.exists() else []
    s = p2_lib.slowdown(rows)
    return {"arm": arm, "T": T, "rc": rc, "level_wall_s": round(wall, 1), "calls": s["calls"], "S": s["effective"], "S_raw": s["raw"],
            "items": len(items), "m": (sum(i["wall_s"] for i in items) / len(items)) if items else None,
            "max_item_wall_s": max((i["wall_s"] for i in items), default=None), "load1": os.getloadavg()[0]}


def per_level(results, only=None):
    out = {}
    for r in results:
        if r["m"] is None or r["S"] != r["S"] or (only and r["T"] not in only):
            continue
        out.setdefault(r["T"], {})[r["arm"]] = {"S": r["S"], "m": r["m"]}
    return {t: v for t, v in out.items() if "v4h2" in v and "v6p" in v}


def decision(results, only=None):
    pl = per_level(results, only)
    if not pl:
        return None
    d = p2_lib.decide(pl, 100)
    C = d["C"]
    h = {n: p2_lib.decide({C: pl[C]}, n)["H"][C] for n in (200, 100, 50)}
    return {"C": C, "scales": d["scales"], "H_by_level_100": d["H"], "H_at_C": h, "stage_tasks": p2_lib.plan_stage_ladder(h),
            "finish_utc_if_started_now": time.strftime("%FT%TZ", time.gmtime(time.time() + 3600 * h[p2_lib.plan_stage_ladder(h)]))}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out"); ap.add_argument("--harness", required=True); ap.add_argument("--ids", required=True)
    ap.add_argument("--arms", nargs="+", default=["v4h2", "v6p"]); ap.add_argument("--levels", type=int, nargs="+", default=[1, 2])
    ap.add_argument("--n-tasks", type=int, default=4); ap.add_argument("--port", type=int, default=8001)
    ap.add_argument("--decide-only", action="store_true")
    a = ap.parse_args(argv)
    out = Path(a.out).resolve(); out.mkdir(parents=True, exist_ok=True)
    sf = out / "probe_summary.json"
    results = json.loads(sf.read_text())["results"] if sf.exists() else []
    if not a.decide_only:
        order = [(arm, T) for T in a.levels for arm in a.arms]
        for arm, T in order:
            r = run_level(out, arm, T, a, sys.executable)
            results = [x for x in results if not (x["arm"] == arm and x["T"] == T)] + [r]
            print(json.dumps(r), flush=True)
            sf.write_text(json.dumps({"results": results}, indent=1))
    d = decision(results)
    sf.write_text(json.dumps({"results": results, "decision": d}, indent=1))
    print("DECISION", json.dumps(d), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
