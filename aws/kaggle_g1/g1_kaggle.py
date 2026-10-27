#!/usr/bin/env python3
"""G1 teacher pilot on a Kaggle 4x L4 notebook (docs/GAPS_2026-10-06.md 'G1 amendment 2' and its 'Correction'): the EC2
pilot's fallback while the AWS G quota is pending. Run by the thin notebooks that aws/kaggle_g1/make_kernels.py writes:

    python g1_kaggle.py gold      # CPU kernel: build the harness environment, run the 30 GOLD patches (is the env faithful?)
    python g1_kaggle.py teacher   # 4x L4 kernel: the same environment, Devstral on vLLM (TP=4), the 30 tasks via or_proxy

The harness side replicates scripts/a6000/p2_race.py's python:3.12-slim container on the Kaggle VM, which has no Docker and
whose own Python is 3.13: a uv-installed CPython 3.12 stands in for the container's system Python (swegemma builds each
sandbox venv from the running interpreter, and run_eval.py's _host_env.pth points at /root/buildenv/lib/python3.12), the
harness wheels go into it under harness/constraints/box_venv_2026-10-18.txt, /wheels is the competition's wheels, buildenv
comes from pod/buildenv.sh, and each task runs scripts/pallets/run_eval_pallets.py exactly as p2_race's item script does.
The teacher side is its own venv (vLLM 0.19.1 from PyPI, unpatched, on torch 2.10.0+cu128, the CUDA build proven on these
L4s; NOT the competition's patched 0.19.1 used for Gemma) serving the Mistral-format weights downloaded to a temp dir after
a free-disk check. Every model call goes through scripts/or_proxy.py --upstream vllm --capture. Caps: v12b's bundle with
max_time_minutes 20 and max_tool_calls 100 (scratch copy via aws/jobs/g1_race.py; submissions/ is never written); no pacing.

Writes to /kaggle/working: facts.json, timing.json, status.json, g1.log, logs/, results.jsonl, and per mode gold/... or
capture_devstral.jsonl + devstral/items/g1_v12b_t20/<task>/task_results.jsonl (the layout scripts/distill/usable.py reads).
Every failure is caught and written to status.json, so the notebook still ends COMPLETE and its output can be fetched.
Offline mode (the 4x L4 kernel: Kaggle gives that accelerator only with the competition attached, and then refuses internet):
when an input holds assets_manifest.json (the g4-g1-assets kernel's output), uv and CPython 3.12 come from it, every install
reads its wheel pool with --no-index, and the weights are the g4-g1-w1 / g4-g1-w2 kernels' outputs, symlinked, not downloaded.
Test hooks (tests/test_aws_kaggle_g1.py; never set on Kaggle): G1_PY312 (skip the harness install), G1_TV_VLLM (a vllm
executable instead of installing one), G1_SKIP_DOWNLOAD, G1_WEIGHTS_GB, G1_ALLOW_FEWER_GPUS, and the path variables G1_*.
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

E = os.environ.get
T0 = float(E("G1_T0") or time.time())
W = Path(E("G1_W", "/kaggle/working"))
ROOT = Path(E("G1_ROOT", "/root/g4"))           # the code archive; not under /tmp, /workspace, /usr/local/bin or /wheels
H = Path(E("G1_H", "/root/h"))                  # p2_race's /root/h: G4_WHEELHOUSE = H/wheels must avoid those prefixes too
SCRATCH = Path(E("G1_SCRATCH", "/root/g1_scratch"))
INPUT = Path(E("G1_INPUT", "/kaggle/input"))
ARM = "g1_v12b_t20"
VLLM_VERSION = E("G1_VLLM", "0.19.1")
# vLLM 0.19.1 only bounds transformers from below; 5.20 dropped PixtralRotaryEmbedding, which vllm/models/pixtral.py
# imports (offline run 2, 2026-10-26: "Model architectures ['PixtralForConditionalGeneration'] failed to be inspected").
# 5.13.1 is pod/bootstrap.sh's pairing for 0.19.1 and has every name pixtral.py imports (checked against the v5.13.1 tag).
TEACHER_PINS = ["transformers==5.13.1"]
VPORT, PPORT = int(E("G1_VPORT") or 8101), int(E("G1_PPORT") or 8201)
SPORT = int(E("G1_SPORT") or 8102)   # aws/kaggle_g1/strip_proxy.py: or_proxy -> strip_proxy -> vLLM
TEACHER = {
    "name": "devstral", "repo": "mistralai/Devstral-Small-2-24B-Instruct-2512", "served": "devstral-small-2-24b",
    "allow": ["consolidated-*.safetensors", "consolidated.safetensors.index.json", "params.json", "tekken.json"],
    "weights_gb": float(E("G1_WEIGHTS_GB") or 25.8),   # the two consolidated FP8 shards (19.84 + 5.95 GB, HF tree API 2026-10-26)
    "flags": ["--tokenizer-mode", "mistral", "--config-format", "mistral", "--load-format", "mistral",
              "--tool-call-parser", "mistral", "--enable-auto-tool-choice", "--max-model-len", E("G1_MAX_LEN", "65536"),
              # text only: Devstral carries a Pixtral vision tower, and vLLM 0.19.1's MistralCommonImageProcessor lacks the
              # fetch_images that transformers 5.13.1 calls while profiling a dummy image (offline run 3, 2026-10-26)
              "--language-model-only"],
}
TIMES, STATUS = {}, {"mode": None, "stage": "start", "ok": False}
# Variables of the Kaggle image that would send installs or imports somewhere other than the container's (2026-10-26 gold
# run: `VIRTUAL_ENV=/root/buildenv uv pip install pytest` exited 0 yet buildenv had no pytest; UV_SYSTEM_PYTHON overrides
# VIRTUAL_ENV). Scrubbed from every subprocess the harness side starts; facts.json records what was there.
SCRUB = ("UV_SYSTEM_PYTHON", "UV_PYTHON", "UV_BREAK_SYSTEM_PACKAGES", "UV_PROJECT_ENVIRONMENT", "UV_INDEX_URL", "UV_EXTRA_INDEX_URL",
         "UV_CONSTRAINT", "UV_BUILD_CONSTRAINT",   # gold run 2: Kaggle pins uv installs to its own image's versions
         "PIP_TARGET", "PIP_PREFIX", "PIP_USER", "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE",
         "VIRTUAL_ENV", "CONDA_PREFIX")


def clean_env(base=None):
    env = dict(os.environ if base is None else base)
    for k in SCRUB:
        env.pop(k, None)
    return env


def log(*a):
    line = time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a)
    print(line, flush=True)
    with open(W / "g1.log", "a") as f:
        f.write(line + "\n")


def save():
    TIMES["wall_s"] = round(time.time() - T0, 1)
    TIMES["notebook_hours"] = round(TIMES["wall_s"] / 3600, 4)
    (W / "timing.json").write_text(json.dumps(TIMES, indent=1))
    (W / "status.json").write_text(json.dumps(STATUS, indent=1))


def mark(key):
    TIMES[key] = round(time.time() - T0, 1)
    STATUS["stage"] = key
    save()
    log("MARK", key, TIMES[key], "s")


def sh(cmd, name, env=None, check=True, timeout=None, cwd=None):
    """Run cmd (list or shell string), its output to W/logs/<name>.log; raise on failure when check. The environment is
    clean_env() unless one is given."""
    env = clean_env() if env is None else env
    (W / "logs").mkdir(parents=True, exist_ok=True)
    with open(W / "logs" / f"{name}.log", "a") as out:
        r = subprocess.run(cmd, shell=isinstance(cmd, str), stdout=out, stderr=subprocess.STDOUT, env=env, timeout=timeout, cwd=cwd)
    if check and r.returncode != 0:
        tail = (W / "logs" / f"{name}.log").read_text()[-1500:]
        raise RuntimeError(f"{name} failed (exit {r.returncode}): ...{tail}")
    return r.returncode


def free_gb(path):
    p = Path(path)
    while not p.exists():
        p = p.parent
    return round(shutil.disk_usage(p).free / 1e9, 1)


def facts():
    f = {"python": sys.version.split()[0], "cpus": os.cpu_count(), "free_gb": {},
         "scrubbed_env": {k: os.environ[k] for k in SCRUB if k in os.environ},
         "uv_pip_env": sorted(k for k in os.environ if k.startswith(("UV_", "PIP_")))}
    for k in ("UV_CONSTRAINT", "UV_BUILD_CONSTRAINT"):   # what the scrub keeps out, for the record
        path = os.environ.get(k, "")
        if path and os.path.isfile(path):
            f.setdefault("kaggle_constraints", {})[k] = open(path).read().splitlines()[:400]
    for p in ("/", "/tmp", "/root", "/kaggle/working"):
        try:
            f["free_gb"][p] = free_gb(p)
        except OSError:
            pass
    try:
        f["mem_gb"] = round(int(next(ln.split()[1] for ln in open("/proc/meminfo") if ln.startswith("MemTotal"))) / 1e6, 1)
    except (OSError, StopIteration):
        pass
    if shutil.which("nvidia-smi"):
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"], capture_output=True, text=True)
        f["gpus"] = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
        r = subprocess.run(["nvidia-smi"], capture_output=True, text=True)
        f["cuda_driver_max"] = next((ln.split("CUDA Version:")[1].split()[0] for ln in r.stdout.splitlines() if "CUDA Version:" in ln), None)
    (W / "facts.json").write_text(json.dumps(f, indent=1))
    log("FACTS", json.dumps(f))
    return f


def find_input(name):
    """A dataset file or directory under /kaggle/input, whichever form Kaggle mounted it in."""
    hits = sorted(glob.glob(str(INPUT / "**" / name), recursive=True))
    return Path(hits[0]) if hits else None


def unpack(name, dest, marker="tasks.jsonl"):
    """name.tgz/.tar, or whatever directory Kaggle unpacked it to, -> dest (the directory that holds `marker`)."""
    src = next((p for p in (find_input(c) for c in (name + ".tgz", name + ".tar", name)) if p is not None), None)
    if src is None:   # unpacked at the dataset root, or under another name: the directory holding the marker and snapshots/
        src = next((Path(m).parent for m in sorted(glob.glob(str(INPUT / "**" / marker), recursive=True))
                    if (Path(m).parent / "snapshots").is_dir()), None)
    if src is None:
        raise FileNotFoundError(f"{name}(.tgz|.tar) not under {INPUT}: {sorted(glob.glob(str(INPUT / '*' / '*')))[:20]}")
    dest.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dest, dirs_exist_ok=True)
    else:
        sh(["tar", "xf", str(src), "-C", str(dest)], "unpack")
    if not (dest / marker).exists():   # the archive held one top-level folder: lift it
        inner = next((Path(m).parent for m in sorted(glob.glob(str(dest / "**" / marker), recursive=True))), None)
        if inner is None:
            raise FileNotFoundError(f"no {marker} in {src}")
        for item in inner.iterdir():
            shutil.move(str(item), str(dest / item.name))
    log("unpacked", src, "->", dest)
    return src


def check_tasks():
    ids = [ln.strip() for ln in open(ROOT / "data" / "distill" / "g1_ids.txt") if ln.strip()]
    rows = [json.loads(ln) for ln in open(H / "tasks.jsonl") if ln.strip()]
    have = {r["instance_id"] for r in rows}
    missing = [i for i in ids if i not in have or not (H / "snapshots" / f"{i}.tgz").is_file()]
    if missing or len(ids) != 30:
        raise RuntimeError(f"harness subset incomplete: {len(ids)} ids, missing {missing}")
    log("tasks ok:", len(ids), "ids, wheels:", len(list((H / "wheels").iterdir())))
    return ids


OFF = {}   # offline mode: assets dir, wheel pool, python, uv (prepare_offline)
WEIGHT_FILES = ["consolidated-00001-of-00002.safetensors", "consolidated-00002-of-00002.safetensors",
                "consolidated.safetensors.index.json", "params.json", "tekken.json"]


def prepare_offline():
    """Offline mode when an input holds assets_manifest.json: uv and CPython 3.12 from the assets kernel's output."""
    hits = sorted(glob.glob(str(INPUT / "**" / "assets_manifest.json"), recursive=True))
    if not hits:
        return False
    a = Path(hits[0]).parent
    bind, pyroot = Path(E("G1_BIN", "/root/g1bin")), Path(E("G1_PYROOT", "/root/py312"))
    bind.mkdir(parents=True, exist_ok=True)
    shutil.copy(a / "bin" / "uv", bind / "uv"); os.chmod(bind / "uv", 0o755)
    if not (pyroot / "bin").is_dir():
        pyroot.parent.mkdir(parents=True, exist_ok=True)
        sh(["tar", "xzf", str(a / "py312.tgz"), "-C", str(pyroot.parent)], "py312")   # the archive's top folder is py312/
    py = pyroot / "bin" / "python3.12"
    os.environ["PATH"] = f"{bind}{os.pathsep}{pyroot / 'bin'}{os.pathsep}{os.environ['PATH']}"
    OFF.update(assets=str(a), wheels=str(a / "wheels"), py=str(py), uv=str(bind / "uv"))
    man = json.loads((a / "assets_manifest.json").read_text())
    STATUS["offline"] = {"assets": str(a), "wheels": man.get("wheels"), "torch": man.get("torch"), "vllm": man.get("vllm")}
    log("OFFLINE: assets", a, "|", man.get("wheels"), "wheels |", man.get("vllm"))
    return True


def offline_env():
    """uv reads only the asset wheel pool (buildenv.sh's own `uv pip install` takes these from the environment). UV_OFFLINE +
    UV_FIND_LINKS resolve from the folder with an empty cache (checked 2026-10-26, uv 0.12.5); uv has no UV_NO_INDEX."""
    return dict(clean_env(), UV_OFFLINE="1", UV_FIND_LINKS=OFF["wheels"], UV_LOCK_TIMEOUT="1800") if OFF else clean_env()


def link_weights(dest):
    """The weight files from the inputs (the g4-g1-w1 / g4-g1-w2 kernel outputs), symlinked into one model dir."""
    found = {n: sorted(glob.glob(str(INPUT / "**" / n), recursive=True)) for n in WEIGHT_FILES}
    missing = [n for n, h in found.items() if not h]
    if missing:
        return None, missing
    dest.mkdir(parents=True, exist_ok=True)
    for n, h in found.items():
        if (dest / n).is_symlink() or (dest / n).exists():
            (dest / n).unlink()
        os.symlink(h[0], dest / n)
    return {n: os.path.getsize(h[0]) for n, h in found.items()}, []


def ensure_uv():
    if OFF:
        return OFF["uv"]
    uv = shutil.which("uv")
    if not uv:
        sh([sys.executable, "-m", "pip", "install", "-q", "uv"], "uv")
        uv = shutil.which("uv") or str(Path(sys.executable).parent / "uv")
    return uv


def competition_wheels():
    """The competition's wheels/ when the competition is attached (CPU kernel), else the dataset's raw_wheels copy (the
    4x L4 kernel cannot attach the competition with internet on; same 124 files, checked by name and size)."""
    for pat in ("**/gemma-4-developer-agent/wheels", "**/gemma-4-developer-agent/**/wheels", "**/raw_wheels"):
        for d in sorted(glob.glob(str(INPUT / pat), recursive=True)):
            if len(glob.glob(d + "/*.whl")) >= 100:
                return Path(d)
    tar = find_input("raw_wheels.tar")
    if tar is not None:
        dest = Path(E("G1_RAW_WHEELS", "/root/raw_wheels_x"))
        dest.mkdir(parents=True, exist_ok=True)
        sh(["tar", "xf", str(tar), "-C", str(dest)], "unpack")
        return dest / "raw_wheels"
    raise FileNotFoundError("no competition wheels and no raw_wheels(.tar) under /kaggle/input")


def setup_harness():
    """p2_race.SETUP on this VM, with a uv CPython 3.12 as the container's system Python."""
    if E("G1_PY312"):
        return E("G1_PY312")
    uv = ensure_uv()
    os.environ["PATH"] = str(Path(uv).parent) + os.pathsep + os.environ["PATH"]
    os.environ.update({"UV_LINK_MODE": "copy", "PYTHONDONTWRITEBYTECODE": "1"})
    if OFF:
        py = OFF["py"]
    else:
        sh([uv, "python", "install", "3.12"], "py312")
        py = subprocess.run([uv, "python", "find", "3.12"], capture_output=True, text=True, check=True, env=clean_env()).stdout.strip()
    index = (["--no-index", "--find-links", OFF["wheels"]] if OFF else
             ["--index-strategy", "unsafe-best-match", "--extra-index-url", "https://download.pytorch.org/whl/cu128"])
    if not shutil.which("patch"):
        sh("apt-get -qq update && apt-get -qq install -y patch", "apt", check=False)
    wheels = sorted(str(p) for p in (ROOT / "harness" / "wheels").glob("*.whl"))
    sh([uv, "pip", "install", "-q", "--python", py, "--system", "--break-system-packages", *index,
        "-c", str(ROOT / "harness/constraints/box_venv_2026-10-18.txt"), *wheels], "harness_install", env=offline_env())
    cw = competition_wheels()
    if Path("/wheels").is_symlink() or not Path("/wheels").exists():
        if Path("/wheels").is_symlink():
            Path("/wheels").unlink()
        os.symlink(cw, "/wheels")
    newest = subprocess.run([py, "-c", NEWEST], capture_output=True, text=True, check=True, env=clean_env()).stdout.split()
    if newest:
        sh([uv, "pip", "install", "-q", "--python", py, "--system", "--break-system-packages", "--no-deps", *newest], "newest_wheels")
    sh(["bash", "-x", str(ROOT / "pod" / "buildenv.sh")], "buildenv", env=offline_env())   # -x: the log shows which step failed
    sh([py, "-c", "import swegemma, adk_submission, google.adk, litellm, sys; print(sys.version)"], "harness_import")
    sh([uv, "pip", "freeze", "--python", py], "harness_freeze", check=False)   # compared across the gold and teacher runs
    log("harness ready:", py, "| /wheels ->", cw)
    return py


NEWEST = r'''
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
'''


def make_bundle(py):
    out = subprocess.run([py, str(ROOT / "aws" / "jobs" / "g1_race.py"), "bundle", "--base", str(ROOT / "submissions" / "v12b"),
                          "--dest", str(SCRATCH), "--min", "20", "--calls", "100"], capture_output=True, text=True, check=True,
                         env=clean_env()).stdout.split("\n")
    bundle, budget = Path(out[0].strip()), json.loads(out[1])
    assert budget["max_time_minutes"] == 20.0 and budget["max_tool_calls"] == 100, budget
    shutil.copy(bundle / "eval_config.yaml", W / "bundle_eval_config.yaml")
    flags = (f"--max-time-minutes {budget['max_time_minutes']} --max-tool-calls {budget['max_tool_calls']} "
             f"--max-turns {budget['max_turns']} --timeout-seconds {budget['timeout_seconds']}")
    log("bundle", bundle, flags)
    return bundle, flags


def task_cmd(py, bundle, flags, task, results, oracle=False):
    """p2_race.item_script's run_eval_pallets call, without the container."""
    return ([py, str(ROOT / "scripts" / "pallets" / "run_eval_pallets.py")] + (["--oracle"] if oracle else []) +
            ["eval", "--tasks", str(H / "tasks.jsonl"), "--snapshots-dir", str(H / "snapshots"), "--submission-dir", str(bundle),
             "--results-dir", str(results), "--sandbox", "subprocess", *flags.split(), "--concurrency", "1", "--display", "quiet",
             "--task-ids", task])


def task_env(port, sbx):
    env = clean_env()
    env.update({"PYTHONDONTWRITEBYTECODE": "1", "UV_LINK_MODE": "copy", "G4_WHEELHOUSE": str(H / "wheels"), "G4_COMPACTION": "1",
                "G4_L4_SCALE": "1.0", "G4_NO_EDITABLE": "1", "LITELLM_LOCAL_MODEL_COST_MAP": "True", "OPENAI_API_KEY": "EMPTY",
                "OPENAI_BASE_URL": f"http://127.0.0.1:{port}/v1", "TMPDIR": str(sbx)})
    return env


def run_tasks(py, bundle, flags, ids, out, port, conc, oracle=False, per_task_timeout=2700):
    """Each task through run_eval_pallets.py, conc at a time; out/items/<arm>/<task>/task_results.jsonl, out/items.jsonl."""
    (out / "items" / ARM).mkdir(parents=True, exist_ok=True)
    todo = [t for t in ids if not (out / "items" / ARM / t / "task_results.jsonl").is_file()]
    lock, idx, done = threading.Lock(), [0], [0]

    def worker():
        while True:
            with lock:
                if idx[0] >= len(todo):
                    return
                t = todo[idx[0]]; idx[0] += 1
            sbx = Path(f"/tmp/g1_sbx_{'gold' if oracle else 'run'}_{t}"); sbx.mkdir(parents=True, exist_ok=True)
            res = out / "items" / ARM / t
            t0 = time.time(); rc = None
            try:
                with open(out / "items" / ARM / f"{t}.out", "w") as fo:
                    rc = subprocess.run(task_cmd(py, bundle, flags, t, res, oracle), stdout=fo, stderr=subprocess.STDOUT,
                                        env=task_env(port, sbx), cwd=str(sbx), timeout=per_task_timeout).returncode
            except subprocess.TimeoutExpired:
                rc = "timeout"
            shutil.rmtree(sbx, ignore_errors=True)
            row = {"arm": ARM, "task": t, "pass": 1, "t0": round(t0, 1), "t1": round(time.time(), 1), "wall_s": round(time.time() - t0, 1), "rc": rc}
            with lock:
                done[0] += 1
                with open(out / "items.jsonl", "a") as f:
                    f.write(json.dumps(row) + "\n")
                log(f"{'gold' if oracle else 'task'} {done[0]}/{len(todo)} {t} rc={rc} {row['wall_s']:.0f}s")

    ths = [threading.Thread(target=worker) for _ in range(max(1, conc))]
    [t.start() for t in ths]; [t.join() for t in ths]
    return summarise(out, ids)


def summarise(out, ids):
    rows = []
    for t in ids:
        f = out / "items" / ARM / t / "task_results.jsonl"
        r = json.loads(f.read_text().splitlines()[0]) if f.is_file() and f.read_text().strip() else {}
        rows.append({"id": t, "resolved": bool(r.get("resolved")), "tool_calls": r.get("tool_calls"), "has_result": bool(r)})
    with open(W / "results.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    s = {"n": len(rows), "resolved": sum(r["resolved"] for r in rows), "with_result": sum(r["has_result"] for r in rows),
         "resolved_ids": [r["id"] for r in rows if r["resolved"]]}
    log("SUMMARY", json.dumps({k: v for k, v in s.items() if k != "resolved_ids"}))
    return s


def conc_default(f, teacher=False):
    """Tasks at a time. Gold runs only tests (CPU-bound): cpus // 4. Teacher tasks mostly wait on the model, and the
    notebook-hours per usable criterion rewards overlap: cpus // 2, at least 4 and at most 8 (the EC2 plan ran 6)."""
    cpus = f.get("cpus") or 8
    return int(E("G1_CONC") or (max(4, min(8, cpus // 2)) if teacher else max(2, min(8, cpus // 4))))


# ------------------------------------------------------------------------------------------------------------- modes
def gold_mode():
    f = facts(); mark("facts")
    unpack("harness_g1", H); ids = check_tasks(); mark("unpacked")
    py = setup_harness(); mark("harness_ready")
    bundle, flags = make_bundle(py)
    s = run_tasks(py, bundle, flags, ids, W / "gold", port=9, conc=conc_default(f), oracle=True)
    (W / "gold_summary.json").write_text(json.dumps(s, indent=1))
    STATUS.update(ok=True, gold_resolved=s["resolved"], gold_with_result=s["with_result"])
    mark("gold_done")


def pick_model_dir(need_gb):
    cands = [Path(E("G1_MODELS"))] if E("G1_MODELS") else [Path("/tmp/g1_models"), Path("/root/g1_models"), Path("/kaggle/tmp/g1_models")]
    best = max(cands, key=lambda p: free_gb(p))
    have = free_gb(best)
    return best, have


def download(dest, out):
    if E("G1_SKIP_DOWNLOAD"):
        out.update(ok=True, gb=0, skipped=True); return
    if OFF:
        sizes, missing = link_weights(dest)
        if sizes is None:
            out.update(ok=False, error=f"offline and no input holds {missing}"); return
        shards = sum(v for k, v in sizes.items() if k.startswith("consolidated-")) / 1e9
        out.update(ok=shards > TEACHER["weights_gb"] * 0.98, gb=round(shards, 2), linked=sizes); return
    try:
        try:
            from huggingface_hub import snapshot_download
        except ImportError:
            sh([sys.executable, "-m", "pip", "install", "-q", "huggingface_hub"], "hf_hub")
            from huggingface_hub import snapshot_download
        snapshot_download(TEACHER["repo"], local_dir=str(dest), allow_patterns=TEACHER["allow"], max_workers=8)
        got = sum(p.stat().st_size for p in dest.glob("consolidated-*.safetensors")) / 1e9
        out["gb"] = round(got, 2)
        out["ok"] = got > TEACHER["weights_gb"] * 0.98 and (dest / "params.json").is_file() and (dest / "tekken.json").is_file()
    except Exception as e:
        out["error"] = repr(e)[:500]
        out["ok"] = False


def teacher_env():
    """The teacher install runs while the harness install does, from the same wheels: with one uv cache the two processes
    cross-locked (offline run 1, 2026-10-26: the harness install timed out after 300 s waiting for nvidia-cusparse's cache
    lock). Its own cache, and a long lock timeout as a backstop."""
    return dict(offline_env(), UV_CACHE_DIR=E("G1_TV_CACHE", "/root/.cache/uv-teacher"), UV_LOCK_TIMEOUT="1800")


def install_teacher_vllm(uv, out):
    tv = Path(E("G1_TV", "/tmp/g1_tvllm"))
    if E("G1_TV_VLLM"):
        out.update(ok=True, vllm=E("G1_TV_VLLM"), versions="override (test)"); return
    try:
        sh([uv, "venv", "-q", "-p", OFF.get("py", "3.12"), str(tv)], "teacher_venv", env=teacher_env())
        sh([uv, "pip", "install", "-q", "--python", str(tv / "bin" / "python"), *(["--no-index", "--find-links", OFF["wheels"]] if OFF else []),
            f"vllm=={VLLM_VERSION}", *TEACHER_PINS], "teacher_venv", env=teacher_env())
        r = subprocess.run([str(tv / "bin" / "python"), "-c", "import vllm, torch, mistral_common, transformers; "
                            "import vllm.model_executor.models.pixtral; print(vllm.__version__, transformers.__version__, torch.__version__, "
                            "torch.version.cuda, mistral_common.__version__, torch.cuda.is_available(), torch.cuda.device_count())"],
                           capture_output=True, text=True, env=clean_env())
        out["versions"] = r.stdout.strip() or r.stderr.strip()[-500:]
        out["ok"] = r.returncode == 0 and r.stdout.strip().endswith("True 4")
        out["vllm"] = str(tv / "bin" / "vllm")
    except Exception as e:
        out["error"] = repr(e)[:500]
        out["ok"] = False


def http_ok(url, timeout=5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


TOOLS = [{"type": "function", "function": {"name": "run_shell", "description": "Run a shell command",
          "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}}]


def direct(body, name, port=None):
    """One request to vLLM (or the strip proxy in front of it), never through the capturing proxy; kept as W/<name>.json."""
    req = urllib.request.Request(f"http://127.0.0.1:{port or VPORT}/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            out = json.load(r)
        msg = out["choices"][0]["message"]
        res = {"status": 200, "tool_calls": msg.get("tool_calls"), "content": (msg.get("content") or "")[:300], "usage": out.get("usage")}
    except urllib.error.HTTPError as e:
        res = {"status": e.code, "error": e.read()[:800].decode("utf-8", "replace")}
    except Exception as e:
        res = {"status": None, "error": repr(e)[:500]}
    (W / f"{name}.json").write_text(json.dumps(res, indent=1))
    log(name.upper(), json.dumps(res)[:400])
    return res


def tool_probe():
    """Does the mistral parser return a tool call at all?"""
    res = direct({"model": TEACHER["served"], "max_tokens": 200, "temperature": 0.2, "tools": TOOLS,
                  "messages": [{"role": "user", "content": "List the files in the current directory using the tool."}]}, "tool_probe")
    return bool(res.get("tool_calls"))


def harness_probe():
    """A body shaped like the harness's (eval/collect captures: chat_template_kwargs, float top_k, max_completion_tokens,
    tools), sent the way task calls go: through the strip proxy. If this is refused, every task call would be; offline run 4
    caught vLLM refusing chat_template_kwargs this way, before any task ran."""
    res = direct({"model": TEACHER["served"], "max_completion_tokens": 256, "temperature": 0.2, "top_p": 0.95, "top_k": 64.0,
                  "chat_template_kwargs": {"enable_thinking": True}, "tools": TOOLS,
                  "messages": [{"role": "system", "content": "You are a coding agent."},
                               {"role": "user", "content": "Show the files in the repository."}]}, "harness_probe", port=SPORT)
    if res.get("status") != 200:
        raise RuntimeError(f"vLLM refused a harness-shaped request: {res}")
    return res


def teacher_mode():
    f = facts(); mark("facts")
    if len(f.get("gpus") or []) < 4 and not E("G1_ALLOW_FEWER_GPUS"):
        raise RuntimeError(f"needs 4 GPUs, found {f.get('gpus')}")
    prepare_offline()
    mdir, have = pick_model_dir(TEACHER["weights_gb"])
    need = (0 if OFF else TEACHER["weights_gb"]) + 14   # + the teacher venv (torch + vLLM + CUDA libs) and uv's cache; offline weights are links
    STATUS.update(model_dir=str(mdir), model_dir_free_gb=have)
    if have < need:
        STATUS.update(stage="disk", error=f"only {have} GB free at {mdir}, need {need}"); save()
        log("STOP: not enough disk for the weights:", have, "GB free, need", need); return
    uv = None if E("G1_TV_VLLM") else ensure_uv()
    dl, tv = {}, {}
    threads = [threading.Thread(target=download, args=(mdir / TEACHER["name"], dl)), threading.Thread(target=install_teacher_vllm, args=(uv, tv))]
    [t.start() for t in threads]
    unpack("harness_g1", H); ids = check_tasks(); mark("unpacked")
    py = setup_harness(); mark("harness_ready")
    bundle, flags = make_bundle(py)
    [t.join() for t in threads]
    STATUS.update(download=dl, teacher_venv=tv); mark("weights_and_venv")
    if not (dl.get("ok") and tv.get("ok")):
        raise RuntimeError(f"download {dl} / teacher venv {tv}")
    env = dict(clean_env(), VLLM_NO_USAGE_STATS="1", VLLM_WORKER_MULTIPROC_METHOD="spawn", DO_NOT_TRACK="1",
               **({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"} if OFF else {}))
    vlog = open(W / "vllm.log", "w")
    server = subprocess.Popen([tv["vllm"], "serve", str(mdir / TEACHER["name"]), "--served-model-name", TEACHER["served"],
                               "--tensor-parallel-size", "4", "--gpu-memory-utilization", "0.90", *TEACHER["flags"],
                               "--host", "127.0.0.1", "--port", str(VPORT)], stdout=vlog, stderr=subprocess.STDOUT, env=env)
    procs = [server]   # stopped on every path out, success or failure (a failed probe used to leave vLLM running)
    try:
        for _ in range(240):
            if http_ok(f"http://127.0.0.1:{VPORT}/v1/models"):
                break
            if server.poll() is not None:
                raise RuntimeError("vLLM exited while loading: " + (W / "vllm.log").read_text()[-2000:])
            time.sleep(10)
        else:
            raise RuntimeError("vLLM not up after 40 min")
        mark("vllm_up")
        STATUS["tool_probe_tool_call"] = tool_probe()
        strip = subprocess.Popen([py, str(Path(__file__).resolve().parent / "strip_proxy.py"), "--listen", str(SPORT),
                                  "--upstream", f"http://127.0.0.1:{VPORT}", "--log", str(W / "strip_proxy.jsonl")],
                                 stdout=open(W / "strip_proxy.out", "w"), stderr=subprocess.STDOUT, env=clean_env())
        procs.append(strip)
        for _ in range(30):
            if http_ok(f"http://127.0.0.1:{SPORT}/v1/models") or strip.poll() is not None:
                break
            time.sleep(1)
        STATUS["upstream_strips"] = ["chat_template_kwargs", "chat_template"]
        harness_probe()
        base = f"http://127.0.0.1:{SPORT}/v1"   # or_proxy captures the harness's own request; vLLM gets it minus those keys
        probe = subprocess.run([py, str(ROOT / "scripts" / "or_proxy.py"), "--upstream", "vllm", "--base", base, "--model", TEACHER["served"], "--probe"],
                               capture_output=True, text=True, env=clean_env())
        (W / "probe.out").write_text(probe.stdout + probe.stderr)
        if probe.returncode != 0:
            raise RuntimeError("or_proxy probe failed: " + (probe.stdout + probe.stderr)[-500:])
        out = W / TEACHER["name"]; out.mkdir(exist_ok=True)
        proxy = subprocess.Popen([py, str(ROOT / "scripts" / "or_proxy.py"), "--upstream", "vllm", "--base", base, "--model", TEACHER["served"],
                                  "--capture", str(W / f"capture_{TEACHER['name']}.jsonl"), "--max-usd", "1000", "--port", str(PPORT),
                                  "--log", str(out / "proxy.jsonl")], stdout=open(out / "proxy.out", "w"), stderr=subprocess.STDOUT, env=clean_env())
        procs.append(proxy)
        for _ in range(30):
            if http_ok(f"http://127.0.0.1:{PPORT}/v1/models") or proxy.poll() is not None:
                break
            time.sleep(1)
        mark("race_start")
        conc = conc_default(f, teacher=True); STATUS["conc"] = conc
        s = run_tasks(py, bundle, flags, ids, out, PPORT, conc)
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                proc.kill()
    STATUS.update(ok=True, resolved=s["resolved"], with_result=s["with_result"],
                  capture_rows=sum(1 for _ in open(W / f"capture_{TEACHER['name']}.jsonl")) if (W / f"capture_{TEACHER['name']}.jsonl").exists() else 0)
    mark("race_done")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("mode", choices=["gold", "teacher"])
    a = ap.parse_args(argv)
    W.mkdir(parents=True, exist_ok=True)
    STATUS["mode"] = a.mode
    log("G1 kaggle", a.mode, "start; t0", T0)
    try:
        (gold_mode if a.mode == "gold" else teacher_mode)()
    except Exception as e:
        STATUS.update(ok=False, error=repr(e)[:3000], traceback=traceback.format_exc()[-3000:])
        log("FAILED at", STATUS.get("stage"), repr(e)[:500])
    save()
    log("END", json.dumps({k: STATUS.get(k) for k in ("mode", "stage", "ok", "error")})[:600])
    return 0


if __name__ == "__main__":
    sys.exit(main())
