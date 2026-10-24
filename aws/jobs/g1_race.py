"""G1 teacher pilot runner (GAPS "G1 pre-registration"): scripts/a6000/p2_race.py's faithful container, one arm, one sample per
task, with the bundle read from a SCRATCH copy instead of submissions/ (the pilot's caps differ from v12b's own).

    python aws/jobs/g1_race.py bundle --base submissions/v12b --dest /opt/g4/scratch [--min 20] [--calls 100]
    python aws/jobs/g1_race.py race OUT --bundle /opt/g4/scratch/g1_v12b_t20 --harness data/heldout1k/harness_g1 \
        --ids data/distill/g1_ids.txt --port 8201 --conc 6 --label g1-devstral [--cpus 20] [--mem 64g]

`bundle` copies the base bundle and changes only max_time_minutes and max_tool_calls in eval_config.yaml (read back with
make_eval_kernel.read_budget); it refuses a destination under submissions/. `race` writes p2_race's layout, so
scripts/distill/usable.py reads it as is: OUT/items/<arm>/<task>/task_results.jsonl, OUT/items.jsonl, OUT/race.log,
OUT/ids.txt. Re-running with the same OUT skips finished tasks. The model sits behind scripts/or_proxy.py on --port; the
harness keeps its own model name and the proxy rewrites it. G4_L4_SCALE=1.0: no pacing.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "a6000")); sys.path.insert(0, str(ROOT / "scripts"))
import p2_race  # noqa: E402
from make_eval_kernel import read_budget  # noqa: E402
from p2_lib import build_items  # noqa: E402

ARM = "g1_v12b_t20"


def make_bundle(base, dest, max_min=20, max_calls=100, name=ARM):
    """dest/<name> = base with the two caps changed; nothing else differs. Returns (path, budget)."""
    subs = (ROOT / "submissions").resolve()
    d = Path(dest).resolve() / name
    if d == subs or subs in d.parents:
        raise SystemExit(f"refusing to write a scratch bundle under submissions/: {d}")
    if d.exists():
        shutil.rmtree(d)
    shutil.copytree(base, d, ignore=shutil.ignore_patterns("__pycache__"))
    p = d / "eval_config.yaml"
    s = p.read_text()
    t = re.sub(r"(?m)^(\s*max_time_minutes\s*:\s*)\S+", lambda m: m.group(1) + str(max_min), s)
    t = re.sub(r"(?m)^(\s*max_tool_calls\s*:\s*)\S+", lambda m: m.group(1) + str(max_calls), t)
    p.write_text(t)
    budget = read_budget(str(d))[0]
    if budget["max_time_minutes"] != float(max_min) or budget["max_tool_calls"] != int(max_calls):
        raise SystemExit(f"scratch bundle budget did not take: {budget}")
    return d, budget


def budget_flags(bundle):
    b = read_budget(str(bundle))[0]
    return (f"--max-time-minutes {b['max_time_minutes']} --max-tool-calls {b['max_tool_calls']} "
            f"--max-turns {b['max_turns']} --timeout-seconds {b['timeout_seconds']}")


def item_script(arm, task, port, flags, src="/scratch", scale=1.0, items="items", rdir=None):
    """p2_race.item_script with the bundle copied from `src` (the scratch mount) and its budget passed in; a test holds the
    two byte-equal for src=/g4/submissions."""
    rdir = rdir or task
    return (f"set -u; [ -d /tmp/bundle_{arm} ] || cp -r {src}/{arm} /tmp/bundle_{arm}; mkdir -p /tmp/sbx_{arm}_{rdir} /tmp/run_{arm}_{rdir} /out/{items}/{arm}; cd /tmp/run_{arm}_{rdir}; "
            f"export PYTHONDONTWRITEBYTECODE=1 UV_LINK_MODE=copy G4_WHEELHOUSE=/root/h/wheels G4_COMPACTION=1 G4_L4_SCALE={scale} "
            f"G4_NO_EDITABLE=1 LITELLM_LOCAL_MODEL_COST_MAP=True OPENAI_API_KEY=EMPTY OPENAI_BASE_URL=http://host.docker.internal:{port}/v1 TMPDIR=/tmp/sbx_{arm}_{rdir}; "
            f"python /g4/scripts/pallets/run_eval_pallets.py eval --tasks /root/h/tasks.jsonl --snapshots-dir /root/h/snapshots "
            f"--submission-dir /tmp/bundle_{arm} --results-dir /out/{items}/{arm}/{rdir} --sandbox subprocess {flags} --concurrency 1 "
            f"--display quiet --task-ids {task} > /out/{items}/{arm}/{rdir}.out 2>&1; rc=$?; "
            f"L=$(find /tmp/sbx_{arm}_{rdir} -type d -path '*swe/budget' 2>/dev/null | head -1); [ -n \"$L\" ] && cp -r \"$L\" /out/{items}/{arm}/{rdir}.ledger; "
            f"rm -rf /tmp/sbx_{arm}_{rdir} /tmp/run_{arm}_{rdir}; exit $rc")


def docker_run(name, out, bundle, harness, cpus, mem, docker=p2_race.DOCKER):
    """p2_race's container (repo read-only at /g4, OUT at /out, shared pip/uv caches) plus the scratch bundle's parent at /scratch."""
    env = {"HARNESS": harness, "ARMS": ""}   # ARMS empty: p2_race.SETUP copies no submissions/ bundle
    return [docker, "run", "-d", "--name", name, "--cpus", str(cpus), "--memory", mem, "--add-host", "host.docker.internal:host-gateway",
            *sum((["-e", f"{k}={v}"] for k, v in env.items()), []), "-v", f"{ROOT}:/g4:ro", "-v", f"{out}:/out",
            "-v", f"{Path(bundle).resolve().parent}:/scratch:ro",
            "-v", "g4-pip-cache:/root/.cache/pip", "-v", "g4-uv-cache:/root/.cache/uv", "-w", "/tmp", p2_race.IMAGE, "sleep", "infinity"]


def race(out, bundle, harness, ids_file, port, conc, label, cpus="20", mem="64g", n=None, docker=p2_race.DOCKER, run=subprocess.run):
    out = Path(out).resolve(); out.mkdir(parents=True, exist_ok=True)
    arm, flags = Path(bundle).name, budget_flags(bundle)
    ids = p2_race.ids_list(ids_file, n)
    items = p2_race.pending(build_items(ids, [arm]), str(out))
    (out / "ids.txt").write_text("".join(i + "\n" for i in ids))
    name = f"g4-{label}"
    log = open(out / "race.log", "a")
    log.write(f"START {time.strftime('%FT%TZ', time.gmtime())} arm={arm} port={port} conc={conc} {flags} pending={len(items)}/{len(ids)}\n")
    run([docker, "rm", "-f", name], capture_output=True)
    run(docker_run(name, out, bundle, harness, cpus, mem, docker), check=True, capture_output=True)
    r = run([docker, "exec", name, "bash", "-c", p2_race.SETUP], capture_output=True, text=True)
    log.write((r.stdout or "") + (r.stderr or "")); log.flush()
    if "SETUP_DONE" not in (r.stdout or ""):
        log.write("SETUP_FAILED\n"); log.close()
        run([docker, "rm", "-f", name], capture_output=True)
        return 2
    lock, idx, done, t_start = threading.Lock(), [0], [0], time.time()

    def worker():
        while True:
            with lock:
                if idx[0] >= len(items):
                    return
                task, a = items[idx[0]]; idx[0] += 1
            t0 = time.time()
            p = run([docker, "exec", name, "bash", "-c", item_script(a, task, port, flags)], capture_output=True, text=True)
            t1 = time.time()
            with lock:
                done[0] += 1
                with open(out / "items.jsonl", "a") as f:
                    f.write(json.dumps({"arm": a, "task": task, "pass": 1, "t0": round(t0, 1), "t1": round(t1, 1), "wall_s": round(t1 - t0, 1), "rc": p.returncode}) + "\n")
                log.write(f"{time.strftime('%H:%M:%S')} {done[0]}/{len(items)} {a} {task} rc={p.returncode} {t1 - t0:.0f}s\n"); log.flush()

    ths = [threading.Thread(target=worker) for _ in range(conc)]
    [t.start() for t in ths]; [t.join() for t in ths]
    log.write(f"ALL_DONE {len(items)} items in {time.time() - t_start:.0f}s\n"); log.close()
    run([docker, "rm", "-f", name], capture_output=True)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bundle"); b.add_argument("--base", default=str(ROOT / "submissions" / "v12b")); b.add_argument("--dest", required=True)
    b.add_argument("--min", type=float, default=20); b.add_argument("--calls", type=int, default=100)
    r = sub.add_parser("race"); r.add_argument("out"); r.add_argument("--bundle", required=True); r.add_argument("--harness", required=True)
    r.add_argument("--ids", required=True); r.add_argument("--port", type=int, required=True); r.add_argument("--conc", type=int, default=6)
    r.add_argument("--label", required=True); r.add_argument("--cpus", default="20"); r.add_argument("--mem", default="64g")
    r.add_argument("--n", type=int)
    a = ap.parse_args(argv)
    if a.cmd == "bundle":
        mm = int(a.min) if float(a.min).is_integer() else a.min
        d, budget = make_bundle(a.base, a.dest, mm, a.calls)
        print(d)
        print(json.dumps(budget))
        return 0
    if not os.path.isfile(os.path.join(ROOT, a.harness, "tasks.jsonl")) and not os.path.isfile(os.path.join(a.harness, "tasks.jsonl")):
        raise SystemExit(f"no tasks.jsonl in {a.harness} (stage it: python aws/jobs/g1_stage.py)")
    return race(a.out, a.bundle, a.harness, a.ids, a.port, a.conc, a.label, a.cpus, a.mem, a.n)


if __name__ == "__main__":
    sys.exit(main())
