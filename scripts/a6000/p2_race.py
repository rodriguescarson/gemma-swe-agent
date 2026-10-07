"""P2 race runner (docs/v4h/GATE.md, 'P2 pre-registration'): the pods' faithful environment emulated in one long-lived Docker container
exactly as scripts/pallets/or_race.sh does, with the model at the host's pace proxy; (task, arm) items from p2_lib.build_items run C
at a time, each through scripts/pallets/run_eval_pallets.py with the bundle's own budgets.

    python scripts/a6000/p2_race.py OUT --harness data/heldout1k/harness_s200 --ids data/heldout1k/s200_valid_ids.txt [--n 100]
        --arms v4h2 v6p v6p-think --conc 2 [--scale 1.0] [--port 8001] [--ids-from-end 4] [--label NAME]

Output: OUT/items/<arm>/<task>/{task_results.jsonl, traces...}, OUT/items.jsonl (one line per finished item: arm, task, start/end wall
seconds, docker exit code), OUT/race.log. Re-running with the same OUT skips items that already have a task_results.jsonl."""
import argparse, json, os, subprocess, sys, threading, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_eval_kernel import read_budget  # noqa: E402
from p2_lib import arm_scale, build_items  # noqa: E402

DOCKER = "/usr/bin/docker"
IMAGE = "python:3.12-slim"

SETUP = r'''
set -euo pipefail
apt-get -qq update >/dev/null 2>&1 && apt-get -qq install -y git patch >/dev/null 2>&1
pip -q install uv >/dev/null 2>&1
pip -q install /g4/harness/wheels/*.whl >/dev/null 2>&1
export PYTHONDONTWRITEBYTECODE=1 UV_LINK_MODE=copy
ln -sfn /g4/data/raw/wheels /wheels
python - <<'PY' > /tmp/newest.txt
import os
from packaging.version import Version
best = {}
for f in os.listdir("/wheels"):
    if not f.endswith("-none-any.whl"):
        continue
    name, ver = f.split("-")[0].lower().replace("_", "-"), f.split("-")[1]
    try:
        v = Version(ver)
    except Exception:
        continue
    if name not in best or v > best[name][0]:
        best[name] = (v, f)
for n, (v, f) in sorted(best.items()):
    if n in ("click", "flask", "werkzeug", "jinja2", "itsdangerous"):
        print("/wheels/" + f)
PY
uv pip install -q --system --no-deps $(cat /tmp/newest.txt)
bash /g4/pod/buildenv.sh > /out/buildenv.log 2>&1
cp -r "/g4/$HARNESS" /root/h
for a in $ARMS; do cp -r /g4/submissions/$a /tmp/bundle_$a; done
echo SETUP_DONE
'''


def parse_arm_scales(items):
    return {k: float(v) for k, _, v in (i.partition("=") for i in (items or []))}


def scale_from_probe(path, arm, fallback):
    """Cap scale of an arm from the arm-pure probe at T = 2 (probe_summary.json): 1 / S when S > 1.15, else 1.0; the fallback when there is no usable probe."""
    try:
        rs = [r for r in json.loads(Path(path).read_text())["results"] if r["arm"] == arm and r["T"] == 2]
        s = rs[-1]["S"]
        return fallback if not s == s else arm_scale(s)
    except (FileNotFoundError, ValueError, KeyError, IndexError, TypeError):
        return fallback


def drop_failed_arms(arms, gate_path, required):
    """Arms listed in `required` that have no passing probe gate are dropped from the race (addendum 7): -> (kept, dropped)."""
    try:
        g = json.loads(Path(gate_path).read_text())
    except (FileNotFoundError, ValueError):
        g = {}
    dropped = [a for a in arms if a in required and not g.get(a, {}).get("ok", False)]
    return [a for a in arms if a not in dropped], dropped


def scale_for(arm, scales, default):
    return scales.get(arm, default)


def budget_flags(bundle):
    b = read_budget(bundle)[0]
    return (f"--max-time-minutes {b['max_time_minutes']} --max-tool-calls {b['max_tool_calls']} "
            f"--max-turns {b['max_turns']} --timeout-seconds {b['timeout_seconds']}")


def results_name(task, k, passes=1):
    """The results dir of pass k of a task: the task id alone for a single pass, <task>__s<k> when there are several."""
    return task if passes <= 1 else f"{task}__s{k}"


def port_for(base, k, pass_ports):
    return pass_ports[k - 1] if pass_ports and k - 1 < len(pass_ports) else base


def item_script(arm, task, port, scale, items="items", rdir=None):
    """One (task, arm) item inside the container; the model name stays the harness's own (the proxy rewrites it). rdir: the results dir name (a pass of the task)."""
    rdir = rdir or task
    flags = budget_flags(str(ROOT / "submissions" / arm))
    return (f"set -u; [ -d /tmp/bundle_{arm} ] || cp -r /g4/submissions/{arm} /tmp/bundle_{arm}; mkdir -p /tmp/sbx_{arm}_{rdir} /tmp/run_{arm}_{rdir} /out/{items}/{arm}; cd /tmp/run_{arm}_{rdir}; "
            f"export PYTHONDONTWRITEBYTECODE=1 UV_LINK_MODE=copy G4_WHEELHOUSE=/root/h/wheels G4_COMPACTION=1 G4_L4_SCALE={scale} "
            f"G4_NO_EDITABLE=1 LITELLM_LOCAL_MODEL_COST_MAP=True OPENAI_API_KEY=EMPTY OPENAI_BASE_URL=http://host.docker.internal:{port}/v1 TMPDIR=/tmp/sbx_{arm}_{rdir}; "
            f"python /g4/scripts/pallets/run_eval_pallets.py eval --tasks /root/h/tasks.jsonl --snapshots-dir /root/h/snapshots "
            f"--submission-dir /tmp/bundle_{arm} --results-dir /out/{items}/{arm}/{rdir} --sandbox subprocess {flags} --concurrency 1 "
            f"--display quiet --task-ids {task} > /out/{items}/{arm}/{rdir}.out 2>&1; rc=$?; "
            f"L=$(find /tmp/sbx_{arm}_{rdir} -type d -path '*swe/budget' 2>/dev/null | head -1); [ -n \"$L\" ] && cp -r \"$L\" /out/{items}/{arm}/{rdir}.ledger; "
            f"rm -rf /tmp/sbx_{arm}_{rdir} /tmp/run_{arm}_{rdir}; exit $rc")


def pending(items, out, items_dir="items", passes=1):
    out = Path(out)
    if passes > 1:
        return [it for it in items if not (out / items_dir / it[1] / results_name(it[0], it[2], passes) / "task_results.jsonl").is_file()]
    return [(t, a) for t, a in items if not (out / items_dir / a / t / "task_results.jsonl").is_file()]


def ids_list(path, n=None, from_end=None):
    ids = [l.strip() for l in open(path) if l.strip()]
    if from_end:
        return ids[-from_end:]
    return ids[:n] if n else ids


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out"); ap.add_argument("--harness", required=True); ap.add_argument("--ids", required=True)
    ap.add_argument("--n", type=int); ap.add_argument("--ids-from-end", type=int)
    ap.add_argument("--arms", nargs="+", default=["v4h2", "v6p", "v6p-think"])
    ap.add_argument("--conc", type=int, required=True); ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--arm-scale", nargs="*", default=[], help="ARM=SCALE per arm (G4_L4_SCALE); --scale is the default")
    ap.add_argument("--require-probe-ok", nargs="*", default=[], metavar="ARM", help="drop these arms unless OUT/probe_gate.json says their probe passed")
    ap.add_argument("--arm-scale-from-probe", nargs="*", default=[], metavar="ARM[=FALLBACK]", help="take the arm's scale from OUT/probe_summary.json (T = 2)")
    ap.add_argument("--port", type=int, default=8001); ap.add_argument("--label", default="p2")
    ap.add_argument("--passes", type=int, default=1, help="samples per task (P3): results dirs <task>__s<k>")
    ap.add_argument("--pass-ports", type=int, nargs="*", default=[], help="proxy port per pass (one proxy per pass: its own seed and capture)")
    ap.add_argument("--items-dir", default="items"); ap.add_argument("--keep", action="store_true", help="reuse a running container, leave it running")
    ap.add_argument("--cpus", default="24"); ap.add_argument("--mem", default="64g")
    a = ap.parse_args(argv)
    arm_scales = parse_arm_scales(a.arm_scale)
    out = Path(a.out).resolve(); out.mkdir(parents=True, exist_ok=True)
    a.arms, dropped = drop_failed_arms(a.arms, str(out / "probe_gate.json"), a.require_probe_ok)
    if dropped:
        (out / "race.log").open("a").write(f"DROPPED arms without a passing probe gate: {dropped}\n")
    for spec in a.arm_scale_from_probe:
        arm, _, fb = spec.partition("=")
        arm_scales[arm] = scale_from_probe(str(out / "probe_summary.json"), arm, float(fb) if fb else a.scale)
    ids = ids_list(a.ids, a.n, a.ids_from_end)
    items = pending(build_items(ids, a.arms, a.passes), str(out), a.items_dir, a.passes)
    (out / "ids.txt").write_text("".join(i + "\n" for i in ids))
    name = f"g4-{a.label}"
    live = subprocess.run([DOCKER, "exec", name, "test", "-d", "/root/h"], capture_output=True).returncode == 0
    if not (a.keep and live):
        subprocess.run([DOCKER, "rm", "-f", name], capture_output=True)
    pallets = Path.home() / "g4" / "pallets_cache"; pallets.mkdir(exist_ok=True)
    env = {"HARNESS": a.harness, "ARMS": " ".join(a.arms)}
    run = [DOCKER, "run", "-d", "--name", name, "--cpus", a.cpus, "--memory", a.mem, "--add-host", "host.docker.internal:host-gateway",
           *sum((["-e", f"{k}={v}"] for k, v in env.items()), []), "-v", f"{ROOT}:/g4:ro", "-v", f"{out}:/out",
           "-v", "g4-pip-cache:/root/.cache/pip", "-v", "g4-uv-cache:/root/.cache/uv", "-w", "/tmp", IMAGE, "sleep", "infinity"]
    log = open(out / "race.log", "a")
    if a.keep and live:
        r = subprocess.CompletedProcess([], 0, "SETUP_DONE (reused container)", "")
    else:
        subprocess.run(run, check=True, capture_output=True)
        r = subprocess.run([DOCKER, "exec", name, "bash", "-c", SETUP], capture_output=True, text=True)
    log.write(r.stdout + r.stderr); log.flush()
    if "SETUP_DONE" not in r.stdout:
        print("container setup failed; see", out / "race.log"); subprocess.run([DOCKER, "rm", "-f", name]); return 2
    lock, idx, done = threading.Lock(), [0], [0]
    t_start = time.time()

    def worker():
        while True:
            with lock:
                if idx[0] >= len(items):
                    return
                it = items[idx[0]]; idx[0] += 1
            task, arm = it[0], it[1]
            k = it[2] if len(it) > 2 else 1
            rdir = results_name(task, k, a.passes)
            t0 = time.time()
            p = subprocess.run([DOCKER, "exec", name, "bash", "-c", item_script(arm, task, port_for(a.port, k, a.pass_ports), scale_for(arm, arm_scales, a.scale), a.items_dir, rdir)],
                               capture_output=True, text=True)
            t1 = time.time()
            with lock:
                done[0] += 1
                with open(out / ("items.jsonl" if a.items_dir == "items" else a.items_dir + ".jsonl"), "a") as f:
                    f.write(json.dumps({"arm": arm, "task": task, "pass": k, "t0": round(t0, 1), "t1": round(t1, 1), "wall_s": round(t1 - t0, 1), "rc": p.returncode}) + "\n")
                log.write(f"{time.strftime('%H:%M:%S')} {done[0]}/{len(items)} {arm} {rdir} rc={p.returncode} {t1 - t0:.0f}s\n"); log.flush()

    ths = [threading.Thread(target=worker) for _ in range(a.conc)]
    [t.start() for t in ths]; [t.join() for t in ths]
    log.write(f"ALL_DONE {len(items)} items in {time.time() - t_start:.0f}s\n"); log.close()
    if not a.keep:
        subprocess.run([DOCKER, "rm", "-f", name], capture_output=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
