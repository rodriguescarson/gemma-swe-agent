"""aws/jobs/g1_teacher.sh end to end in a python:3.12-slim container with the repo mounted READ-ONLY: fake nvidia-smi (4 GPUs),
fake `hf` (writes weights), a fake vLLM (a real HTTP server answering /v1/models and /v1/chat/completions), and a fake
/usr/bin/docker whose item scripts send one chat call per task through the REAL scripts/or_proxy.py. Proves the job's
control flow before it spends money: per-teacher GPUs, TP and parsers; weights on the NVMe path; the scratch bundle with
20 min / 100 calls (never submissions/); proxy capture at $OUT/capture_<teacher>.jsonl; results under $OUT/<teacher>/;
a teacher whose server dies is skipped; no teacher up = exit 1. Skipped without Docker or the image (never pulled)."""
import json
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "python:3.12-slim"
IDS = ["tomlkit_4b38bec", "more_itertools_7b9889c", "boltons_ead236e"]


def _docker_ok():
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, timeout=30).returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


pytestmark = pytest.mark.skipif(not _docker_ok(), reason=f"docker or the {IMAGE} image is not available")

FAKE_VLLM = r'''#!/usr/bin/env python3
import json, os, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
a = sys.argv[1:]
name, port = a[a.index("--served-model-name") + 1], int(a[a.index("--port") + 1])
print("ARGS", " ".join(a), flush=True)
print("CUDA_VISIBLE_DEVICES", os.environ.get("CUDA_VISIBLE_DEVICES"), flush=True)
if name in os.environ.get("FAKE_VLLM_FAIL", "").split():
    print("ERROR: fake vLLM refuses to start", name, flush=True); sys.exit(1)
class H(BaseHTTPRequestHandler):
    def log_message(self, *x): pass
    def _send(self, obj):
        b = json.dumps(obj).encode(); self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        self._send({"object": "list", "data": [{"id": name, "object": "model"}]})
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        print("REQUEST model=" + str(body.get("model")), flush=True)
        self._send({"id": "x", "object": "chat.completion", "model": name, "choices": [{"index": 0, "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "ok"}}], "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6}})
ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
'''
FAKE_HF = r'''#!/bin/sh
# hf download REPO --local-dir DIR [--exclude ...]
repo=$2; shift 2; dir=""; args="$*"
while [ $# -gt 0 ]; do [ "$1" = "--local-dir" ] && dir=$2; shift; done
mkdir -p "$dir" && echo "$repo $args" > "$dir.hfargs" && echo '{}' > "$dir/config.json" && echo w > "$dir/model.safetensors"
echo "downloaded $repo"
'''
FAKE_CURL = r'''#!/usr/bin/env python3
import sys, urllib.request
url = [x for x in sys.argv[1:] if x.startswith("http") or x.startswith("localhost")][-1]
url = url if url.startswith("http") else "http://" + url
try:
    print(urllib.request.urlopen(url, timeout=5).read().decode())
except Exception:
    sys.exit(22)
'''
FAKE_DOCKER = r'''#!/usr/bin/env python3
"""docker rm/run/exec for aws/jobs/g1_race.py: run records the mounts; exec SETUP prints SETUP_DONE; an item script sends one
harness-shaped chat call through the proxy on its OPENAI_BASE_URL port and writes the task's task_results.jsonl to /out."""
import json, re, sys, urllib.request
from pathlib import Path
state = Path("/work/dockerstate"); state.mkdir(exist_ok=True)
a = sys.argv[1:]
if a[0] == "rm":
    sys.exit(0)
if a[0] == "run":
    name = a[a.index("--name") + 1]
    mounts = {a[i + 1].split(":")[1]: a[i + 1].split(":")[0] for i, x in enumerate(a) if x == "-v"}
    env = [a[i + 1] for i, x in enumerate(a) if x == "-e"]
    (state / f"{name}.json").write_text(json.dumps({"mounts": mounts, "env": env, "cpus": a[a.index("--cpus") + 1]}))
    print("cid"); sys.exit(0)
if a[0] == "exec":
    name, script = a[1], a[-1]
    st = json.loads((state / f"{name}.json").read_text())
    if "SETUP_DONE" in script:
        print("SETUP_DONE"); sys.exit(0)
    with open(state / f"{name}.items", "a") as f:
        f.write(script + "\n")
    task = re.search(r"--task-ids (\S+)", script).group(1)
    port = re.search(r"OPENAI_BASE_URL=http://host.docker.internal:(\d+)/v1", script).group(1)
    arm, rdir = re.search(r"--results-dir /out/items/([^/ ]+)/(\S+)", script).groups()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", method="POST", headers={"Content-Type": "application/json"},
        data=json.dumps({"model": "gemma-4-31b-it-qat-w4a16-ct", "messages": [{"role": "user", "content": f"fix {task}"}], "max_tokens": 8}).encode())
    reply = json.loads(urllib.request.urlopen(req, timeout=30).read())
    d = Path(st["mounts"]["/out"]) / "items" / arm / rdir; d.mkdir(parents=True, exist_ok=True)
    (d / "task_results.jsonl").write_text(json.dumps({"instance_id": task, "resolved": task.startswith("tomlkit"), "tool_calls": 3,
                                                      "reply_model": reply.get("model")}) + "\n")
    sys.exit(0)
sys.exit(2)
'''
FAKE_SMI = '#!/bin/sh\nfor i in 0 1 2 3; do echo "GPU $i: NVIDIA L40S (UUID: GPU-fake-$i)"; done\n'
FAKE_TV_PY = '#!/bin/sh\necho "teacher vllm 0.31.0-fake mistral_common 1.8.6-fake"\n'


def run_job(tmp_path, fail=""):
    stub, work = tmp_path / "stub", tmp_path / "work"
    for d in (stub / "bin", stub / "tv" / "bin", work / "harness", work / "nvme"):
        d.mkdir(parents=True)
    files = {stub / "bin" / "nvidia-smi": FAKE_SMI, stub / "bin" / "mountpoint": "#!/bin/sh\nexit 0\n", stub / "bin" / "curl": FAKE_CURL,
             stub / "docker": FAKE_DOCKER, stub / "tv" / "bin" / "vllm": FAKE_VLLM, stub / "tv" / "bin" / "hf": FAKE_HF,
             stub / "tv" / "bin" / "python": FAKE_TV_PY}
    for p, body in files.items():
        p.write_text(body); p.chmod(0o755)
    tasks = [json.loads(ln) for ln in open(ROOT / "data/heldout1k/harness_all/tasks.jsonl")] if (ROOT / "data/heldout1k/harness_all/tasks.jsonl").is_file() else []
    (work / "harness" / "tasks.jsonl").write_text("".join(json.dumps(t) + "\n" for t in tasks if t["instance_id"] in IDS) or "{}\n")
    (work / "ids.txt").write_text("".join(i + "\n" for i in IDS))
    env = {"PATH": "/stub/bin:/usr/local/bin:/usr/bin:/bin", "G1_OUT": "/work/out", "G1_SCRATCH": "/work/scratch", "G1_NVME": "/work/nvme",
           "TEACHER_VENV": "/stub/tv", "G1_PY": "python3", "G1_HARNESS": "/work/harness", "G1_IDS": "/work/ids.txt", "G1_CONC": "2",
           "FAKE_VLLM_FAIL": fail, "PYTHONDONTWRITEBYTECODE": "1"}
    name = f"g1e2e-{uuid.uuid4().hex[:8]}"
    cmd = ["docker", "run", "--rm", "--name", name, "-v", f"{ROOT}:/root/g4:ro", "-v", f"{stub}:/stub:ro", "-v", f"{work}:/work",
           "-v", f"{stub / 'docker'}:/usr/bin/docker:ro", *sum((["-e", f"{k}={v}"] for k, v in env.items()), []),
           IMAGE, "bash", "/root/g4/aws/jobs/g1_teacher.sh"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    return r, work / "out", work


def test_one_teacher_dies_the_other_runs_the_whole_pilot(tmp_path):
    r, out, work = run_job(tmp_path, fail="gpt-oss-120b")
    log = (out / "job.log").read_text() if (out / "job.log").exists() else r.stdout + r.stderr
    assert r.returncode == 0, log
    st = json.loads((out / "status.json").read_text())
    assert st["teachers"]["devstral"] == {"ran": True, "results": 3, "resolved": 1, "capture_rows": 3, "downloaded": True}
    assert st["teachers"]["gptoss"]["ran"] is False and st["teachers"]["gptoss"]["results"] == 0
    assert "gptoss vLLM died" in log and "gptoss SKIPPED" in log and "devstral READY on proxy :8201" in log
    dv, go = (out / "devstral" / "vllm.log").read_text(), (out / "gptoss" / "vllm.log").read_text()
    assert "CUDA_VISIBLE_DEVICES 0\n" in dv and "--tensor-parallel-size 1" in dv and "--tool-call-parser mistral --enable-auto-tool-choice" in dv
    assert "CUDA_VISIBLE_DEVICES 2,3\n" in go and "--tensor-parallel-size 2" in go
    assert "--tool-call-parser openai --enable-auto-tool-choice --reasoning-parser openai_gptoss" in go
    assert "/work/nvme/models/devstral" in dv and "--served-model-name devstral-small-2-24b" in dv
    assert dv.count("REQUEST model=devstral-small-2-24b") >= 4             # the probe + 3 tasks, renamed by the proxy
    assert (work / "nvme" / "models" / "gptoss.hfargs").read_text().split() == ["openai/gpt-oss-120b", "--local-dir", "/work/nvme/models/gptoss",
                                                                               "--exclude", "original/*", "metal/*"]
    caps = [json.loads(ln) for ln in (out / "capture_devstral.jsonl").read_text().splitlines()]
    assert len(caps) == 3                                                      # the probe is not captured
    items = (work / "dockerstate" / "g4-g1-devstral.items").read_text()
    assert items.count("cp -r /scratch/g1_v12b_t20 /tmp/bundle_g1_v12b_t20") == 3 and "/g4/submissions" not in items
    assert items.count("--max-time-minutes 20.0 --max-tool-calls 100 --max-turns 150 --timeout-seconds 180") == 3
    run = json.loads((work / "dockerstate" / "g4-g1-devstral.json").read_text())
    assert run["mounts"]["/scratch"] == "/work/scratch" and "ARMS=" in run["env"] and run["cpus"] == "20"
    for t in IDS:
        assert (out / "devstral" / "items" / "g1_v12b_t20" / t / "task_results.jsonl").is_file()
    cfg = (work / "scratch" / "g1_v12b_t20" / "eval_config.yaml").read_text()
    assert "max_time_minutes: 20" in cfg and "max_tool_calls: 100" in cfg


def test_no_teacher_up_fails_the_job(tmp_path):
    r, out, _ = run_job(tmp_path, fail="devstral-small-2-24b gpt-oss-120b")
    assert r.returncode == 1
    assert "FAIL: no teacher came up" in (out / "job.log").read_text()
    st = json.loads((out / "status.json").read_text())
    assert not any(t["ran"] for t in st["teachers"].values())
