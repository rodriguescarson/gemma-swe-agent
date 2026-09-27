"""Generate a Kaggle notebook that evaluates a bundle exactly like the scorer (official Getting Started recipe):
wheelhouse install, vLLM on 4x L4 (TP=4, gemma4 parsers, thinking default on), subprocess sandbox, sequential tasks.
Usage: python scripts/make_eval_kernel.py <bundle_dir> <slug> --ids ids.txt [--oracle | --patches labels.json] [--min 6] [--calls 60] [--turns 80] [--timeout 180]"""
import argparse, base64, json, os
ap = argparse.ArgumentParser(); ap.add_argument("bundle"); ap.add_argument("slug"); ap.add_argument("--ids")
ap.add_argument("--oracle", action="store_true"); ap.add_argument("--min", type=float, default=6); ap.add_argument("--calls", type=int, default=60)
ap.add_argument("--patches", help="rescore agent patches: json list of {task,cfg,patch} (CPU, Kaggle env)")
ap.add_argument("--helper-check", help="skill scripts dir to test for sandbox reachability on the Kaggle image (CPU)")
ap.add_argument("--turns", type=int, default=80); ap.add_argument("--timeout", type=int, default=180)
a = ap.parse_args()
PATCHES = {}
if a.patches:
    a.oracle = True
    for r in json.load(open(a.patches)):
        if r["patch"].strip(): PATCHES.setdefault(r["cfg"], {})[r["task"]] = r["patch"]
files = {}
for root, _, fs in os.walk(a.bundle):
    for f in fs:
        rel = os.path.relpath(os.path.join(root, f), a.bundle)
        if rel.startswith(".") or "__pycache__" in rel or f.endswith(".pyc") or f.startswith("._"): continue
        files[rel] = base64.b64encode(open(os.path.join(root, f), "rb").read()).decode()
ids = [l.strip() for l in open(a.ids) if l.strip()] if a.ids else []
cells = []
cells.append(r'''
import glob, importlib, os, shutil, subprocess, sys, json, time, base64
from pathlib import Path
os.environ.update({'LITELLM_LOCAL_MODEL_COST_MAP': 'True', 'TRANSFORMERS_NO_TF': '1', 'VLLM_WORKER_MULTIPROC_METHOD': 'spawn',
  'VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS': '1', 'VLLM_ENGINE_READY_TIMEOUT_S': '1200', 'VLLM_NO_USAGE_STATS': '1',
  'OTEL_SDK_DISABLED': 'true', 'PYTORCH_CUDA_ALLOC_CONF': 'expandable_segments:True'})
WHEELHOUSE_DIR = Path('/kaggle/input/datasets/metric/gemma-4-developer-agent-wheelhouse')
if not WHEELHOUSE_DIR.exists(): WHEELHOUSE_DIR = Path('/kaggle/input/gemma-4-developer-agent-wheelhouse')
for pat in ('/usr/local/lib/python*/dist-packages/*cutlass*.pth', '/usr/local/lib/python*/site-packages/*cutlass*.pth'):
    for p in glob.glob(pat):
        try: os.unlink(p)
        except OSError: pass
tmp = Path('/tmp/wheelhouse'); tmp.mkdir(parents=True, exist_ok=True)
for w in WHEELHOUSE_DIR.glob('*.whl'):
    if 'cutlass' in w.name.lower(): continue
    n = w.name.replace('cu128', '+cu128') if ('cu128' in w.name and '+' not in w.name) else w.name
    if not (tmp / n).exists(): os.symlink(w, tmp / n)
subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '--no-deps', '--force-reinstall', *sorted(str(w) for w in tmp.glob('*.whl'))], check=True)
importlib.invalidate_caches(); print('wheelhouse ok')
''')
cells.append("FILES = " + json.dumps(files) + "\nIDS = " + json.dumps(ids) + "\nPATCHES = " + json.dumps(PATCHES) + f"\nORACLE = {a.oracle}\nBUDGET = dict(max_time_minutes={a.min}, max_tool_calls={a.calls}, max_turns={a.turns}, timeout_seconds={a.timeout})\n" + r'''
DATA_DIR = Path('/kaggle/input/competitions/gemma-4-developer-agent')
if not DATA_DIR.exists(): DATA_DIR = Path('/kaggle/input/gemma-4-developer-agent')
W = Path('/kaggle/working'); AGENT_DIR = W / 'bundle'
shutil.rmtree(AGENT_DIR, ignore_errors=True)
for rel, b in FILES.items():
    p = AGENT_DIR / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(base64.b64decode(b))
from swegemma.models import load_tasks
tasks = load_tasks(DATA_DIR / 'tasks.jsonl')
if IDS: tasks = [t for t in tasks if t.instance_id in set(IDS)]
print(len(tasks), 'tasks', 'ORACLE' if ORACLE else 'AGENT', BUDGET)
''')
cells.append(r'''
import litellm, torch
from adk_submission import VllmConfig, VllmServer, discover_adapters
from swegemma.config import ALLOWED_ADAPTER_EXTENSIONS
from swegemma.models.discovery import validate_single_declared_model
litellm.drop_params = True
declared = validate_single_declared_model(AGENT_DIR)
adapters = discover_adapters(str(AGENT_DIR), adapter_extensions=ALLOWED_ADAPTER_EXTENSIONS)
models = None
if not ORACLE:
    MODEL_PATH = Path('/kaggle/input/models/google/gemma-4/other/gemma-4-31b-it-qat-w4a16-ct/2')
    n = torch.cuda.device_count(); tp = 4 if n >= 4 else (2 if n >= 2 else 1)
    cfg = VllmConfig(model=str(MODEL_PATH), port=8000, host='127.0.0.1', tool_call_parser='gemma4', reasoning_parser='gemma4',
        default_chat_template_kwargs={'enable_thinking': True}, max_model_len=32768,
        dtype='bfloat16' if torch.cuda.is_bf16_supported() else 'auto', gpu_memory_utilization=0.90, enable_auto_tool_choice=True,
        enable_lora=True, max_loras=8, max_lora_rank=128, tensor_parallel_size=tp, startup_timeout=60 * 20)
    t0 = time.time(); server = VllmServer(cfg, adapter_manifest=adapters); server.start()
    print('vLLM up in', round(time.time() - t0), 's, tp', tp, 'gpus', n)
    models = server.create_model_registry(aliases=[declared, 'gemma-4-31b-it-qat-w4a16-ct'], model_prefix='openai/', api_key='EMPTY')
''')
cells.append(r'''
import asyncio, concurrent.futures
from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps._configs import EventsCompactionConfig
from adk_eval_core.tracing import SessionTrace
from swegemma.config import EvalConfig, build_submission_limits
from swegemma.evaluate import Evaluator
from swegemma.models import setup_gemma_model_registry
def run_sync(fn):
    try: loop = asyncio.get_running_loop()
    except RuntimeError: loop = None
    if loop is not None and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(1) as pool: return pool.submit(lambda: asyncio.run(fn())).result()
    return asyncio.run(fn())
limits, gen = build_submission_limits()
ec = EvalConfig(tasks_path=DATA_DIR / 'tasks.jsonl', snapshots_dir=DATA_DIR / 'snapshots', results_dir=W / 'results',
    submission_dir=AGENT_DIR, models=models or setup_gemma_model_registry(), sandbox='subprocess', limits=limits,
    generation_constraints=gen, adapter_manifest=adapters,
    context_cache_config=ContextCacheConfig(min_tokens=2048, ttl_seconds=1800, cache_intervals=10),
    events_compaction_config=EventsCompactionConfig(compaction_interval=15, overlap_size=2, token_threshold=14336, event_retention_size=5),
    graph_dir=str(DATA_DIR / 'graphs'), embeddings_dir=str(DATA_DIR / 'embeddings'), wheels_dir=DATA_DIR / 'wheels', verbose=False, **BUDGET)
ev = Evaluator(ec)
subprocess.run(f'{sys.executable} -m pip freeze > {W}/pip_freeze.txt', shell=True)
RUNS = [(c, m) for c, m in PATCHES.items()] if PATCHES else [(None, None)]
out = open(W / 'results.jsonl', 'w'); T0 = time.time()
for cfg, pmap in RUNS:
    if ORACLE:
        async def _oracle(self, task, snapshot_path, task_index, total_tasks, _m=pmap, **kw):
            return (_m[task.instance_id] if _m is not None else task.patch), None, SessionTrace()
        Evaluator._run_agent_sandbox = _oracle
    run_tasks = [t for t in tasks if pmap is None or t.instance_id in pmap]
    for i, t in enumerate(run_tasks, 1):
        s = time.time()
        try:
            r = run_sync(lambda: ev.evaluate_task(task=t, task_index=i, total_tasks=len(run_tasks)))
            row = dict(cfg=cfg, id=t.instance_id, resolved=bool(r.resolved), exit=r.test_exit_code, calls=r.tool_calls, secs=round(time.time() - s, 1),
                       err=(str(r.error)[:300] if r.error else None), patch=r.agent_patch or '')
        except Exception as e:
            row = dict(cfg=cfg, id=t.instance_id, resolved=False, err='EXC ' + repr(e)[:300], secs=round(time.time() - s, 1))
        out.write(json.dumps(row) + '\n'); out.flush()
        print(cfg, i, row['id'], row['resolved'], row.get('calls'), row['secs'], (row.get('err') or '')[:80], flush=True)
out.close()
print('TOTAL', sum(json.loads(l)['resolved'] for l in open(W / 'results.jsonl')), 'rows', sum(1 for _ in open(W / 'results.jsonl')), 'in', round(time.time() - T0), 's')
shutil.make_archive(str(W / 'traces'), 'gztar', root_dir=W / 'results')
''')
HELPER_BODY = r'''
# Kaggle-image check (2026-09-27): helpers must be reachable from sandbox commands (v4 installed them to the host /tmp).
import base64, os, sys, tempfile
from swegemma.sandbox.subprocess import SubprocessManager
hdir = tempfile.mkdtemp(prefix="helpers_"); [open(os.path.join(hdir, f), "wb").write(base64.b64decode(b)) for f, b in HELPERS_B64.items()]
m = SubprocessManager(timeout_seconds=60, system_site_packages=True)
m.initialize({"pkg/__init__.py": "", "pkg/mod.py": "def parse_header(x):\n    return x\n", "tests/test_mod.py": "from pkg.mod import parse_header\ndef test_p(): assert parse_header(1) == 1\n"})
m.run_command("git init -q && git add -A && git -c user.email=a@b -c user.name=t commit -qm i")
code = ("import os, shutil, subprocess, sys, tempfile\nsrc = %r\nwith tempfile.TemporaryDirectory() as td:\n    d = os.path.join(td, 'scripts'); shutil.copytree(src, d)\n"
        "    r = subprocess.run([sys.executable, os.path.join(d, 'install.py')], cwd=td, capture_output=True, text=True); print(r.stdout, r.stderr)\n") % hdir
m.write_file(".adk_exec_chk.py", code); lines = ["install: " + m.run_command(f"python3 {m.work_dir}/.adk_exec_chk.py").stdout.strip()[:300]]
m.run_command(f"rm -f {m.work_dir}/.adk_exec_chk.py")
ok = True
for c in ('python3 /tmp/swe/locate.py "parse_header"', "python3 /tmp/swe/test.py --target tests/test_mod.py", 'python3 /tmp/swe/run.py --timeout 5 "echo hi"', "python3 /tmp/swe/gate.py", "cat /tmp/swe/last.log"):
    r = m.run_command(c); o = (r.stdout + r.stderr); bad = "can't open file" in o or "No such file" in o; ok &= not bad
    lines.append(("FAIL " if bad else "ok   ") + c + " -> " + o.strip().replace("\n", " | ")[:200])
lines.append("HELPER_CHECK " + ("PASS" if ok else "FAIL")); print("\n".join(lines)); open("/kaggle/working/helper_check.txt", "w").write("\n".join(lines) + "\n")
'''
if a.helper_check:
    hb = {f: base64.b64encode(open(os.path.join(a.helper_check, f), "rb").read()).decode() for f in os.listdir(a.helper_check) if f.endswith(".py")}
    cells.insert(1, "HELPERS_B64 = " + json.dumps(hb) + "\ndef _helper_check():" + HELPER_BODY.replace("\n", "\n    ") +
                 "\ntry: _helper_check()\nexcept Exception as e: print('HELPER_CHECK ERROR', repr(e)[:300])\n")

nb = {"cells": [{"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": c} for c in cells],
      "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}}, "nbformat": 4, "nbformat_minor": 5}
kd = os.path.join("kernels", a.slug); os.makedirs(kd, exist_ok=True)
json.dump(nb, open(os.path.join(kd, a.slug + ".ipynb"), "w"))
meta = {"id": "carsonrodrigues/" + a.slug, "title": a.slug, "code_file": a.slug + ".ipynb", "language": "python", "kernel_type": "notebook",
        "is_private": True, "enable_gpu": not a.oracle, "enable_tpu": False, "enable_internet": False,
        "dataset_sources": ["metric/gemma-4-developer-agent-wheelhouse"], "competition_sources": ["gemma-4-developer-agent"],
        "kernel_sources": [], "model_sources": [] if a.oracle else ["google/gemma-4/Other/gemma-4-31b-it-qat-w4a16-ct/2"]}
if not a.oracle: meta["machine_shape"] = "NvidiaL4"
json.dump(meta, open(os.path.join(kd, "kernel-metadata.json"), "w"), indent=2)
print(kd, len(files), "files", len(ids) or "all", "tasks")
