"""Step 1 of the P2 pre-registration (docs/v4h/GATE.md): the concurrency probe. v6p on the last 4 ids at T = 4, 2, 1, 3 task-runs in flight, a fresh
pace proxy (and log) per level, one container for all levels. Prints S(T), the chosen C and scale, the projection and the stage.

    python scripts/a6000/p2_probe.py OUT --harness data/heldout1k/harness_s200 --ids data/heldout1k/s200_valid_ids.txt [--levels 4 2 1 3]

Writes OUT/probe_summary.json."""
import argparse, json, os, subprocess, sys, time, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import p2_lib, p2_race  # noqa: E402

BRIDGE = "172.18.0.1"      # docker0: where the container's host.docker.internal (host-gateway) points


def run_level(out, T, a, py):
    log = Path(out) / f"proxy_T{T}.jsonl"
    log.unlink(missing_ok=True)
    proxy = subprocess.Popen([py, str(HERE / "pace_proxy.py"), "--listen", str(a.port), "--host", BRIDGE, "--rewrite-model", "--log", str(log)],
                             stdout=open(Path(out) / f"proxy_T{T}.out", "w"), stderr=subprocess.STDOUT)
    try:
        for _ in range(30):
            try:
                urllib.request.urlopen(f"http://{BRIDGE}:{a.port}/v1/models", timeout=3); break
            except Exception:
                time.sleep(1)
        t0 = time.time()
        rc = p2_race.main([str(out), "--harness", a.harness, "--ids", a.ids, "--ids-from-end", str(a.n_tasks), "--arms", "v6p", "--conc", str(T),
                           "--port", str(a.port), "--label", "probe", "--items-dir", f"probe_T{T}", "--keep"])
        wall = time.time() - t0
    finally:
        proxy.terminate(); proxy.wait(timeout=30)
    rows = [json.loads(l) for l in open(log)] if log.exists() else []
    items = [json.loads(l) for l in open(Path(out) / f"probe_T{T}.jsonl")] if (Path(out) / f"probe_T{T}.jsonl").exists() else []
    s = p2_lib.slowdown(rows)
    return {"T": T, "rc": rc, "level_wall_s": round(wall, 1), "calls": s["calls"], "S_effective": s["effective"], "S_raw": s["raw"],
            "items": len(items), "mean_item_wall_s": (sum(i["wall_s"] for i in items) / len(items)) if items else None,
            "max_item_wall_s": max((i["wall_s"] for i in items), default=None),
            "load1": os.getloadavg()[0]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out"); ap.add_argument("--harness", required=True); ap.add_argument("--ids", required=True)
    ap.add_argument("--levels", type=int, nargs="+", default=[4, 2, 1, 3]); ap.add_argument("--n-tasks", type=int, default=4)
    ap.add_argument("--port", type=int, default=8001)
    a = ap.parse_args(argv)
    out = Path(a.out).resolve(); out.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    levels = {}
    for T in a.levels:
        levels[T] = run_level(out, T, a, py)
        print(json.dumps(levels[T]), flush=True)
    S = {T: v["S_effective"] for T, v in levels.items()}
    C, scale = p2_lib.choose_concurrency(S)
    m = levels[C]["mean_item_wall_s"] if C in levels else None
    hours = p2_lib.project_hours(m, C, scale, 200) if m else None
    res = {"levels": levels, "S": S, "C": C, "scale": scale, "m_seconds": m, "projected_hours_200": hours,
           "stage_tasks": p2_lib.plan_stage(hours) if hours else None}
    (out / "probe_summary.json").write_text(json.dumps(res, indent=1))
    print("PROBE", json.dumps({k: v for k, v in res.items() if k != "levels"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
