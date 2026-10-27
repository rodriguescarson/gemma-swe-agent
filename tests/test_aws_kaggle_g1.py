"""aws/kaggle_g1 (the G1 teacher pilot on a Kaggle 4x L4 notebook, GAPS 'G1 amendment 2'): the driver run end to end on
this machine against stubs. The harness Python is this interpreter (G1_PY312), vLLM is a fake HTTP server (G1_TV_VLLM),
run_eval_pallets.py is a fake that sends one harness-shaped call per task through the REAL scripts/or_proxy.py, and the
weights download is skipped. Proves the orchestration: the scratch bundle's 20 min / 100 calls reach every task, TP=4 and
the Mistral flags reach vLLM, the capture holds the 30 task calls and not the probes, results land where usable.py reads,
a disk shortfall stops cleanly before any download, and every failure ends in status.json. Plus the kernels' metadata."""
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "aws" / "kaggle_g1" / "g1_kaggle.py"
sys.path.insert(0, str(ROOT / "aws" / "kaggle_g1"))
IDS = [ln.strip() for ln in open(ROOT / "data" / "distill" / "g1_ids.txt") if ln.strip()]

FAKE_VLLM = r'''#!/usr/bin/env python3
import json, os, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
a = sys.argv[1:]
name, port = a[a.index("--served-model-name") + 1], int(a[a.index("--port") + 1])
print("ARGS", " ".join(a), flush=True)
print("PID", os.getpid(), flush=True)
class H(BaseHTTPRequestHandler):
    def log_message(self, *x): pass
    def _send(self, obj):
        b = json.dumps(obj).encode(); self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        self._send({"object": "list", "data": [{"id": name}]})
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        print("REQUEST model=%s tools=%s" % (body.get("model"), bool(body.get("tools"))), flush=True)
        msg = {"role": "assistant", "content": "ok"}
        if body.get("tools"):
            msg = {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function",
                   "function": {"name": "run_shell", "arguments": "{\"command\": \"ls\"}"}}]}
        self._send({"id": "x", "object": "chat.completion", "model": name, "choices": [{"index": 0, "finish_reason": "stop", "message": msg}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6}})
ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
'''
FAKE_RUNNER = r'''#!/usr/bin/env python3
"""Stands in for scripts/pallets/run_eval_pallets.py: one model call per task through OPENAI_BASE_URL, then a result row."""
import json, os, sys, urllib.request
from pathlib import Path
a = sys.argv[1:]
oracle = "--oracle" in a
res, task = Path(a[a.index("--results-dir") + 1]), a[a.index("--task-ids") + 1]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({"argv": a, "wheelhouse": os.environ.get("G4_WHEELHOUSE"), "scale": os.environ.get("G4_L4_SCALE"),
                        "tmpdir": os.environ.get("TMPDIR"), "base": os.environ.get("OPENAI_BASE_URL")}) + "\n")
if not oracle:
    req = urllib.request.Request(os.environ["OPENAI_BASE_URL"] + "/chat/completions", method="POST", headers={"Content-Type": "application/json"},
        data=json.dumps({"model": "gemma-4-31b-it-qat-w4a16-ct", "messages": [{"role": "user", "content": "fix " + task}], "max_tokens": 8}).encode())
    urllib.request.urlopen(req, timeout=30).read()
res.mkdir(parents=True, exist_ok=True)
(res / "task_results.jsonl").write_text(json.dumps({"instance_id": task, "resolved": oracle or task.startswith("tomlkit"), "tool_calls": 3}) + "\n")
'''


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); return s.getsockname()[1]


def make_world(tmp_path):
    root, inp = tmp_path / "root", tmp_path / "input" / "g4-g1-harness"
    for rel in ("scripts/or_proxy.py", "scripts/golden/router.py", "aws/jobs/g1_race.py", "scripts/a6000/p2_race.py",
                "scripts/a6000/p2_lib.py", "scripts/make_eval_kernel.py", "data/distill/g1_ids.txt"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True); shutil.copy(ROOT / rel, root / rel)
    shutil.copytree(ROOT / "submissions" / "v12b", root / "submissions" / "v12b", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "tests" / "v10_support", root / "tests" / "v10_support", ignore=shutil.ignore_patterns("__pycache__"))
    (root / "scripts" / "pallets").mkdir(parents=True); (root / "scripts" / "pallets" / "run_eval_pallets.py").write_text(FAKE_RUNNER)
    h = inp / "harness_g1"; (h / "snapshots").mkdir(parents=True); (h / "wheels").mkdir()
    (h / "tasks.jsonl").write_text("".join(json.dumps({"instance_id": i}) + "\n" for i in IDS))
    for i in IDS:
        (h / "snapshots" / f"{i}.tgz").write_bytes(b"x")
    (h / "wheels" / "a-1.0-py3-none-any.whl").write_bytes(b"x")
    vllm = tmp_path / "fake_vllm"; vllm.write_text(FAKE_VLLM); vllm.chmod(0o755)
    env = {**os.environ, "G1_W": str(tmp_path / "working"), "G1_ROOT": str(root), "G1_H": str(tmp_path / "h"), "G1_INPUT": str(tmp_path / "input"),
           "G1_SCRATCH": str(tmp_path / "scratch"), "G1_MODELS": str(tmp_path / "models"), "G1_PY312": sys.executable, "G1_TV_VLLM": str(vllm),
           "G1_SKIP_DOWNLOAD": "1", "G1_ALLOW_FEWER_GPUS": "1", "G1_WEIGHTS_GB": "0.1", "G1_CONC": "4", "G1_VPORT": str(free_port()),
           "G1_PPORT": str(free_port()), "FAKE_LOG": str(tmp_path / "runner.jsonl"), "PYTHONDONTWRITEBYTECODE": "1"}
    return env, tmp_path / "working", root


def run(env, mode):
    r = subprocess.run([sys.executable, str(DRIVER), mode], env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    return r


def test_teacher_mode_end_to_end_against_stubs(tmp_path):
    env, w, root = make_world(tmp_path)
    run(env, "teacher")
    st = json.loads((w / "status.json").read_text())
    assert st["ok"] is True and st["resolved"] == sum(i.startswith("tomlkit") for i in IDS) and st["with_result"] == 30, st
    assert st["capture_rows"] == 30 and st["tool_probe_tool_call"] is True                 # the probes are not captured
    timing = json.loads((w / "timing.json").read_text())
    for k in ("facts", "unpacked", "harness_ready", "weights_and_venv", "vllm_up", "race_start", "race_done", "notebook_hours"):
        assert k in timing, k
    vlog = (w / "vllm.log").read_text()
    for flag in ("--tensor-parallel-size 4", "--tokenizer-mode mistral --config-format mistral --load-format mistral",
                 "--tool-call-parser mistral --enable-auto-tool-choice", "--max-model-len 65536", "--served-model-name devstral-small-2-24b",
                 "--language-model-only"):
        assert flag in vlog, flag
    assert vlog.count("REQUEST model=devstral-small-2-24b") == 33          # tool probe + harness probe + or_proxy probe + 30 tasks
    hp = json.loads((w / "harness_probe.json").read_text()); assert hp["status"] == 200
    runs = [json.loads(ln) for ln in (tmp_path / "runner.jsonl").read_text().splitlines()]
    assert sorted(r["argv"][r["argv"].index("--task-ids") + 1] for r in runs) == sorted(IDS)
    for r in runs:
        a = " ".join(r["argv"])
        assert "--max-time-minutes 20.0 --max-tool-calls 100 --max-turns 150 --timeout-seconds 180" in a
        assert f"--submission-dir {tmp_path / 'scratch' / 'g1_v12b_t20'}" in a and "--sandbox subprocess" in a and "--oracle" not in a
        assert r["wheelhouse"] == str(tmp_path / "h" / "wheels") and r["scale"] == "1.0" and r["base"] == f"http://127.0.0.1:{env['G1_PPORT']}/v1"
    for i in IDS:
        assert (w / "devstral" / "items" / "g1_v12b_t20" / i / "task_results.jsonl").is_file()   # usable.py's --results glob
    assert len((w / "results.jsonl").read_text().splitlines()) == 30
    cfg = (w / "bundle_eval_config.yaml").read_text()
    assert "max_time_minutes: 20" in cfg and "max_tool_calls: 100" in cfg
    assert not (root / "submissions" / "g1_v12b_t20").exists()


def test_gold_mode_runs_the_gold_patches_without_a_model(tmp_path):
    env, w, _ = make_world(tmp_path)
    run(env, "gold")
    s = json.loads((w / "gold_summary.json").read_text())
    assert s["resolved"] == 30 and s["with_result"] == 30
    runs = [json.loads(ln) for ln in (tmp_path / "runner.jsonl").read_text().splitlines()]
    assert len(runs) == 30 and all(r["argv"][0] == "--oracle" for r in runs)
    assert json.loads((w / "status.json").read_text())["gold_resolved"] == 30


def test_too_little_disk_stops_before_any_download(tmp_path):
    env, w, _ = make_world(tmp_path)
    env["G1_WEIGHTS_GB"] = "1000000"
    run(env, "teacher")
    st = json.loads((w / "status.json").read_text())
    assert st["stage"] == "disk" and "need" in st["error"] and not st["ok"]
    assert not (w / "vllm.log").exists() and not (tmp_path / "runner.jsonl").exists()


def test_a_failure_is_written_to_status_and_the_notebook_still_ends(tmp_path):
    env, w, _ = make_world(tmp_path)
    (tmp_path / "input" / "g4-g1-harness" / "harness_g1" / "snapshots" / f"{IDS[3]}.tgz").unlink()
    run(env, "teacher")
    st = json.loads((w / "status.json").read_text())
    assert st["ok"] is False and IDS[3] in st["error"] and "traceback" in st


def test_a_rerun_skips_finished_tasks(tmp_path):
    env, w, _ = make_world(tmp_path)
    run(env, "gold")
    n = len((tmp_path / "runner.jsonl").read_text().splitlines())
    run(env, "gold")
    assert len((tmp_path / "runner.jsonl").read_text().splitlines()) == n


def test_kernels_are_private_internet_on_and_run_the_driver(tmp_path, monkeypatch):
    import make_kernels
    monkeypatch.setattr(make_kernels, "ROOT", tmp_path)
    make_kernels.main()
    for d, kid, mode, gpu in (("g1_gold", "g4-g1-gold", "gold", False), ("g1_devstral", "g4-g1-devstral", "teacher", True)):
        meta = json.loads((tmp_path / "kernels" / d / "kernel-metadata.json").read_text())
        assert meta["id"] == "carsonrodrigues/" + kid and meta["is_private"] and meta["enable_gpu"] is gpu
        assert meta["dataset_sources"] == ["carsonrodrigues/g4-g1-harness"] and meta["competition_sources"] == ["gemma-4-developer-agent"]
        # 4x L4 only with the competition attached, and then no internet: the GPU kernel is offline, fed by three kernels
        assert meta["enable_internet"] is (not gpu)
        assert meta["kernel_sources"] == (["carsonrodrigues/g4-g1-assets", "carsonrodrigues/g4-g1-w1", "carsonrodrigues/g4-g1-w2"] if gpu else [])
        assert ("machine_shape" in meta) is gpu
        nb = json.loads((tmp_path / "kernels" / d / meta["code_file"]).read_text())
        src = nb["cells"][0]["source"]
        assert f'"/aws/kaggle_g1/g1_kaggle.py", "{mode}"]' in src and "G1_T0" in src
        compile(src, d, "exec")
        import base64, re
        b64 = re.search(r'b64decode\("([A-Za-z0-9+/=]+)"\)', src).group(1)
        assert base64.b64decode(b64) == DRIVER.read_bytes()            # the notebook carries the current driver verbatim


def test_stage_dataset_code_paths_exist_and_secret_scan_bites():
    import stage_dataset
    for p in stage_dataset.CODE_PATHS:
        assert (ROOT / p).exists(), p
    assert stage_dataset.SECRET_RE.search(b"key=AKIA" + b"ABCDEFGHIJKLMNOP")
    assert stage_dataset.SECRET_RE.search(b"-----BEGIN RSA PRIVATE KEY-----")
    assert not stage_dataset.SECRET_RE.search(b"AWS_ACCESS_KEY / AWS_SECRET_KEY (names only)")


def test_driver_never_writes_submissions_and_uses_its_own_vllm():
    s = DRIVER.read_text()
    code = "\n".join(ln for ln in s.splitlines() if not ln.lstrip().startswith("#"))
    assert 'VLLM_VERSION = E("G1_VLLM", "0.19.1")' in code and 'f"vllm=={VLLM_VERSION}"' in code
    assert "wheelhouse" not in code.lower().replace("g4_wheelhouse", "") or "gemma-4-developer-agent-wheelhouse" not in code
    assert '"--tensor-parallel-size", "4"' in code and "--probe" in code and '"--capture"' in code and '"--max-usd", "1000"' in code
    assert 'str(ROOT / "submissions" / "v12b")' in code and "SCRATCH" in code


@pytest.mark.parametrize("layout", ["unpacked_dir", "tar_root", "tar_folder"])
def test_the_harness_unpacks_from_any_form_kaggle_mounts(tmp_path, layout):
    import tarfile
    env, w, _ = make_world(tmp_path)
    ds = tmp_path / "input" / "g4-g1-harness"
    if layout != "unpacked_dir":
        h = ds / "harness_g1"
        with tarfile.open(ds / "harness_g1.tar", "w") as t:
            t.add(h, arcname="." if layout == "tar_root" else "harness_g1")
        shutil.rmtree(h)
    else:   # Kaggle unpacked an archive whose files sat at its root: tasks.jsonl and snapshots/ at the dataset root
        for item in (ds / "harness_g1").iterdir():
            shutil.move(str(item), str(ds / item.name))
        (ds / "harness_g1").rmdir()
    run(env, "gold")
    assert json.loads((w / "gold_summary.json").read_text())["resolved"] == 30
    assert (tmp_path / "h" / "tasks.jsonl").is_file() and (tmp_path / "h" / "snapshots" / f"{IDS[0]}.tgz").is_file()


def test_clean_env_scrubs_what_redirects_installs_and_imports():
    import g1_kaggle
    base = {"UV_SYSTEM_PYTHON": "1", "VIRTUAL_ENV": "/x", "PYTHONPATH": "/kaggle/lib", "PIP_TARGET": "/t", "PATH": "/usr/bin", "HOME": "/root",
            "UV_CONSTRAINT": "/kaggle/c.txt", "UV_BUILD_CONSTRAINT": "/kaggle/b.txt"}   # all set on Kaggle (gold run 2 facts)
    env = g1_kaggle.clean_env(base)
    assert env == {"PATH": "/usr/bin", "HOME": "/root"}


def test_every_harness_subprocess_gets_the_clean_env():
    src = DRIVER.read_text()
    assert "env = dict(os.environ)" not in src and "dict(os.environ," not in src
    for call in ("[py, \"-c\", NEWEST]", "\"python\", \"find\", \"3.12\"]", "\"--probe\"]"):
        i = src.index(call); assert "env=clean_env()" in src[i:i + 300], call


def test_uv_system_python_in_the_environment_does_not_reach_the_runner(tmp_path):
    env, w, _ = make_world(tmp_path)
    env.update(UV_SYSTEM_PYTHON="1", PYTHONPATH="/nonexistent/kaggle/lib")
    run(env, "gold")
    facts = json.loads((w / "facts.json").read_text())
    assert facts["scrubbed_env"] == {"UV_SYSTEM_PYTHON": "1", "PYTHONPATH": "/nonexistent/kaggle/lib"}
    assert json.loads((w / "gold_summary.json").read_text())["resolved"] == 30


def test_a_refused_harness_shaped_request_stops_before_the_race(tmp_path):
    env, w, _ = make_world(tmp_path)
    fake = Path(env["G1_TV_VLLM"])
    src = FAKE_VLLM.replace('        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")',
        '        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")\n'
        '        if "chat_template_kwargs" in body:\n'
        '            b = b"{\\"error\\": \\"bad kwargs\\"}"; self.send_response(400); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return')
    fake.write_text(src)
    run(env, "teacher")
    st = json.loads((w / "status.json").read_text())
    assert st["ok"] is False and "harness-shaped" in st["error"] and not (tmp_path / "runner.jsonl").exists()


def test_concurrency_defaults():
    import g1_kaggle
    os.environ.pop("G1_CONC", None)
    assert [g1_kaggle.conc_default({"cpus": c}, teacher=True) for c in (4, 8, 12, 16, 48)] == [4, 4, 6, 8, 8]
    assert [g1_kaggle.conc_default({"cpus": c}) for c in (4, 8, 16, 48)] == [2, 2, 4, 8]


@pytest.mark.parametrize("form", ["competition", "dataset_dir", "dataset_tar", "missing"])
def test_wheels_come_from_the_competition_or_the_datasets_copy(tmp_path, monkeypatch, form):
    import tarfile
    import g1_kaggle
    inp = tmp_path / "input"; monkeypatch.setattr(g1_kaggle, "INPUT", inp); monkeypatch.setattr(g1_kaggle, "W", tmp_path / "w")
    (tmp_path / "w").mkdir(); monkeypatch.setenv("G1_RAW_WHEELS", str(tmp_path / "x"))
    src = tmp_path / "src" / "raw_wheels"; src.mkdir(parents=True)
    for i in range(124):
        (src / f"p{i}-1.0-py3-none-any.whl").write_bytes(b"x")
    if form == "competition":
        shutil.copytree(src, inp / "competitions" / "gemma-4-developer-agent" / "wheels")
    elif form == "dataset_dir":
        shutil.copytree(src, inp / "datasets" / "carsonrodrigues" / "g4-g1-harness" / "raw_wheels")
    elif form == "dataset_tar":
        d = inp / "datasets" / "carsonrodrigues" / "g4-g1-harness"; d.mkdir(parents=True)
        with tarfile.open(d / "raw_wheels.tar", "w") as t:
            t.add(src, arcname="raw_wheels")
    else:
        inp.mkdir()
        with pytest.raises(FileNotFoundError):
            g1_kaggle.competition_wheels()
        return
    got = g1_kaggle.competition_wheels()
    assert len(list(got.glob("*.whl"))) == 124


def test_offline_mode_links_the_weights_and_uses_the_assets(tmp_path):
    import tarfile
    env, w, _ = make_world(tmp_path)
    env.pop("G1_SKIP_DOWNLOAD")
    inp = tmp_path / "input"
    a = inp / "notebooks" / "carsonrodrigues" / "g4-g1-assets"; (a / "bin").mkdir(parents=True); (a / "wheels").mkdir()
    (a / "bin" / "uv").write_text("#!/bin/sh\nexit 0\n")
    (a / "assets_manifest.json").write_text(json.dumps({"wheels": 412, "torch": ["torch-2.10.0"], "vllm": ["vllm-0.19.1"]}))
    pyd = tmp_path / "pysrc" / "py312" / "bin"; pyd.mkdir(parents=True); (pyd / "python3.12").symlink_to(sys.executable)
    with tarfile.open(a / "py312.tgz", "w:gz") as t:
        t.add(tmp_path / "pysrc" / "py312", arcname="py312")
    sizes = {"consolidated-00001-of-00002.safetensors": 70, "consolidated-00002-of-00002.safetensors": 31}
    for part, files in (("g4-g1-w1", ["consolidated-00001-of-00002.safetensors"]),
                        ("g4-g1-w2", ["consolidated-00002-of-00002.safetensors", "consolidated.safetensors.index.json", "params.json", "tekken.json"])):
        d = inp / "notebooks" / "carsonrodrigues" / part; d.mkdir(parents=True)
        for f in files:
            (d / f).write_bytes(b"w" * sizes.get(f, 5))
    env.update(G1_WEIGHTS_GB="0.0000001", G1_BIN=str(tmp_path / "g1bin"), G1_PYROOT=str(tmp_path / "py312"))
    run(env, "teacher")
    st = json.loads((w / "status.json").read_text())
    assert st["ok"] is True and st["offline"]["wheels"] == 412 and st["download"]["linked"]["params.json"] == 5
    model = tmp_path / "models" / "devstral"
    for f in ("consolidated-00001-of-00002.safetensors", "consolidated-00002-of-00002.safetensors", "params.json", "tekken.json"):
        assert (model / f).is_symlink() and (model / f).resolve().parent.name in ("g4-g1-w1", "g4-g1-w2")
    assert (tmp_path / "py312" / "bin" / "python3.12").exists() and os.access(tmp_path / "g1bin" / "uv", os.X_OK)
    assert f"serve {model}" in (w / "vllm.log").read_text()


def test_offline_without_the_weight_kernels_fails_cleanly(tmp_path):
    env, w, _ = make_world(tmp_path)
    env.pop("G1_SKIP_DOWNLOAD")
    a = tmp_path / "input" / "g4-g1-assets"; (a / "bin").mkdir(parents=True); (a / "wheels").mkdir()
    (a / "bin" / "uv").write_text(""); (a / "assets_manifest.json").write_text("{}")
    (tmp_path / "py312" / "bin").mkdir(parents=True)   # already unpacked: prepare_offline skips the tar
    env.update(G1_BIN=str(tmp_path / "g1bin"), G1_PYROOT=str(tmp_path / "py312"))
    run(env, "teacher")
    st = json.loads((w / "status.json").read_text())
    assert st["ok"] is False and "offline and no input holds" in st["error"] and not (w / "vllm.log").exists()


def test_asset_kernels_are_cpu_with_internet_and_buildenv_matches_pod(tmp_path, monkeypatch):
    import re
    import shlex
    import assets_kernels
    monkeypatch.setattr(assets_kernels, "HERE", tmp_path)
    assets_kernels.main()
    for d, kid in (("g1_assets", "g4-g1-assets"), ("g1_w1", "g4-g1-w1"), ("g1_w2", "g4-g1-w2")):
        meta = json.loads((tmp_path / d / "kernel-metadata.json").read_text())
        assert meta["id"] == "carsonrodrigues/" + kid and meta["enable_internet"] and not meta["enable_gpu"] and meta["is_private"]
        compile(json.loads((tmp_path / d / meta["code_file"]).read_text())["cells"][0]["source"], kid, "exec")
    line = next(ln for ln in (ROOT / "pod" / "buildenv.sh").read_text().replace("\\\n", " ").splitlines() if "pytest==8.3.4" in ln)
    assert assets_kernels.BUILDENV == [t for t in shlex.split(line.split("uv pip install -q", 1)[1]) if not t.startswith("-")]
    w2 = json.loads((tmp_path / "g1_w2" / "g4-g1-w2.ipynb").read_text())["cells"][0]["source"]
    import g1_kaggle
    assert all(f in w2 or f.startswith("consolidated-00001") for f in g1_kaggle.WEIGHT_FILES)   # w1 + w2 = what the GPU kernel links


def test_the_teacher_install_has_its_own_uv_cache(monkeypatch):
    """Offline run 1: the harness and teacher installs shared one uv cache and cross-locked (300 s lock timeout)."""
    import g1_kaggle
    monkeypatch.setitem(g1_kaggle.OFF, "wheels", "/w")
    te, oe = g1_kaggle.teacher_env(), g1_kaggle.offline_env()
    assert te["UV_CACHE_DIR"] != oe.get("UV_CACHE_DIR") and te["UV_CACHE_DIR"] == "/root/.cache/uv-teacher"
    assert te["UV_OFFLINE"] == "1" and te["UV_FIND_LINKS"] == "/w" and int(te["UV_LOCK_TIMEOUT"]) >= 1800
    src = DRIVER.read_text()
    assert src.count('"teacher_venv", env=teacher_env())') == 2


def test_the_teacher_pins_transformers_and_imports_pixtral_before_serving():
    """Offline run 2: vLLM 0.19.1 + transformers 5.20.2 failed to import its Pixtral module (Devstral's architecture)."""
    import g1_kaggle
    assert g1_kaggle.TEACHER_PINS == ["transformers==5.13.1"]
    src = DRIVER.read_text()
    assert 'f"vllm=={VLLM_VERSION}", *TEACHER_PINS]' in src and "import vllm.model_executor.models.pixtral" in src


def _fake_server_gone(w):
    import re, time
    pid = int(re.search(r"^PID (\d+)$", (w / "vllm.log").read_text(), re.M).group(1))
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.1)
    return False


def test_vllm_is_stopped_when_a_probe_fails_and_when_the_race_ends(tmp_path):
    env, w, _ = make_world(tmp_path)
    run(env, "teacher")
    assert json.loads((w / "status.json").read_text())["ok"] is True and _fake_server_gone(w)
    env2, w2, _ = make_world(tmp_path / "b")
    src = FAKE_VLLM.replace('        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")',
        '        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")\n'
        '        if "chat_template_kwargs" in body:\n'
        '            self.send_response(400); self.send_header("Content-Length", "2"); self.end_headers(); self.wfile.write(b"{}"); return')
    Path(env2["G1_TV_VLLM"]).write_text(src)
    run(env2, "teacher")
    assert json.loads((w2 / "status.json").read_text())["ok"] is False and _fake_server_gone(w2)   # the leak this fixes
