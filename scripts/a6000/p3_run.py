"""P3 pass (docs/v4h/GATE.md, 'P2 addendum 4', step 4): ONE pass of the chosen bundle over data/heldout1k/p3_ids.txt (all_valid_ids minus the 200 sample ids) with every
model call captured through a pace proxy started here; resumable (finished items are skipped); stops when the supervisor stops it (hard stop).

    python scripts/a6000/p3_run.py [--out ~/g4/runs/p3] [--port 8003]
The arm is ~/g4/runs/autopilot_choice.json {"p3_arm"} (default v6p). Output: OUT/capture.jsonl, OUT/proxy.jsonl, OUT/items/<arm>/<task>/..."""
import argparse, json, sys, threading, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(ROOT / "scripts" / "golden"))
import p2_lib  # noqa: E402

CHOICE = Path.home() / "g4" / "runs" / "autopilot_choice.json"
BRIDGE = "172.18.0.1"


def chosen_arm(path=str(CHOICE)):
    try:
        return json.loads(Path(path).read_text()).get("p3_arm") or "v6p"
    except (FileNotFoundError, ValueError):
        return "v6p"


def pass_seed(base, k):
    """Pass 1 keeps the bundle's own seed; pass k shifts it by k - 1 (one proxy per pass overrides the request's seed)."""
    return base + k - 1


def race_args(out, arm, port, passes=1, scale=None):
    scale = p2_lib.ARM_SCALE.get(arm) if scale is None else scale
    args = [out, "--harness", "data/heldout1k/harness_p3",   # repo-relative: p2_race mounts the repo at /g4 and copies /g4/$HARNESS
            "--ids", str(ROOT / "data" / "heldout1k" / "p3_ids.txt"), "--arms", arm,
            "--conc", "2", "--arm-scale", f"{arm}={scale if scale is not None else 1.0}", "--port", str(port), "--label", "p3", "--keep"]
    if passes > 1:
        args += ["--passes", str(passes), "--pass-ports"] + [str(port + k) for k in range(passes)]
    return args


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=str(Path.home() / "g4" / "runs" / "p3")); ap.add_argument("--port", type=int, default=8003)
    ap.add_argument("--passes", type=int, default=1); ap.add_argument("--seed", type=int, default=42, help="the bundle's sampling seed; pass k uses seed + k - 1")
    ap.add_argument("--scale", type=float, default=None, help="G4_L4_SCALE of the arm (default: p2_lib.ARM_SCALE)")
    a = ap.parse_args(argv)
    import pace_proxy, p2_race
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    arm = chosen_arm()
    (out / "ARM").write_text(arm)
    um = json.load(urllib.request.urlopen("http://127.0.0.1:8000/v1/models", timeout=30))["data"][0]["id"]
    proxies = []
    if a.passes > 1:
        for k in range(1, a.passes + 1):        # one proxy per pass: its own seed, its own capture file, the shared pacing log
            px = pace_proxy.serve(a.port + k - 1, "http://127.0.0.1:8000", out / "proxy.jsonl", host=BRIDGE, upstream_model=um, capture_path=out / f"capture_s{k}.jsonl",
                                  seed_override=pass_seed(a.seed, k))
            threading.Thread(target=px.serve_forever, daemon=True).start(); proxies.append(px)
    else:
        px = pace_proxy.serve(a.port, "http://127.0.0.1:8000", out / "proxy.jsonl", host=BRIDGE, upstream_model=um, capture_path=out / "capture.jsonl")
        threading.Thread(target=px.serve_forever, daemon=True).start(); proxies.append(px)
    try:
        return p2_race.main(race_args(str(out), arm, a.port, a.passes, a.scale))
    finally:
        for px in proxies:
            px.shutdown()


if __name__ == "__main__":
    sys.exit(main())
