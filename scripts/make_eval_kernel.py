"""Generate a Kaggle notebook that evaluates a bundle exactly like the host's Getting Started notebook
(ryanholbrook/getting-started-gemma-4-developer-agent, run of 2026-09-27 19:50 UTC, copy in ref/getting_started_20260927):
wheelhouse install, vLLM on 4x L4 (TP=4, gemma4 parsers, NO default_chat_template_kwargs, so the chat template's own
thinking default applies unless a stage sets it), subprocess sandbox, compaction 15/2/14,336/5, sequential tasks.

Budget (2026-09-29): the four keys come from the bundle's eval_config.yaml, read the way the host notebook reads them
(`evaluation:` section or top level; defaults timeout_seconds 300, max_tool_calls 100, max_time_minutes 60.0, max_turns
None, max_llm_calls as the turns fallback). CLI flags only override single keys. The kernel reads the bundle's file
itself with the host's code and stops before vLLM starts if the result differs from the budget printed here.

Usage: python scripts/make_eval_kernel.py <bundle_dir> <slug> --ids ids.txt [--oracle | --patches labels.json]
       [--min M] [--calls N] [--turns N] [--timeout S] [--helper-check scripts_dir]"""
import argparse, base64, json, os, re, sys

BUDGET_KEYS = ("max_time_minutes", "max_tool_calls", "max_turns", "timeout_seconds")
# The host notebook's defaults when a key is absent (cell 10 of the 2026-09-27 run; HARNESS_README 7.1 agrees).
HOST_DEFAULTS = {"timeout_seconds": 300, "max_tool_calls": 100, "max_time_minutes": 60.0, "max_turns": None}
# Settings the host notebook passes (ref/getting_started_20260927, cells 8 and 10); tests/test_make_eval_kernel.py
# checks the generated notebook against that copy.
COMPACTION = dict(compaction_interval=15, overlap_size=2, token_threshold=14336, event_retention_size=5)
CONTEXT_CACHE = dict(min_tokens=2048, ttl_seconds=1800, cache_intervals=10)


def _scalar(v):
    """A YAML 1.1 scalar as PyYAML's safe_load reads the forms eval_config.yaml uses (ints, floats, null, strings)."""
    v = v.strip()
    if " #" in v:
        v = v.split(" #", 1)[0].rstrip()
    if v in ("", "~", "null", "Null", "NULL"):
        return None
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        return v[1:-1]
    if v[0] in "{[&*!|>":
        raise ValueError("eval_config.yaml value %r needs a full YAML parser" % v)
    if re.fullmatch(r"[-+]?\d+", v):
        return int(v)
    if re.fullmatch(r"[-+]?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?", v) and ("." in v or "e" in v.lower()):
        return float(v)
    return v


def mini_yaml(text):
    """Stdlib reader for the two-level mappings eval_config.yaml uses ('key: value' and one nested block). Raises
    ValueError on anything else, so an unusual file is never guessed at."""
    root, cur = {}, None
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].rstrip() if not raw.lstrip().startswith(("'", '"')) else raw.rstrip()
        if not line.strip() or line.strip() == "---":
            continue
        m = re.fullmatch(r"(\s*)([A-Za-z_][\w-]*)\s*:\s*(.*)", line)
        if not m:
            raise ValueError("eval_config.yaml line %d is not 'key: value': %r" % (n, raw))
        ind, key, val = m.groups()
        if not ind:
            if val.strip():
                root[key], cur = _scalar(val), None
            else:
                root[key] = cur = {}
        elif cur is not None:
            cur[key] = _scalar(val)
        else:
            raise ValueError("eval_config.yaml line %d is indented under a scalar: %r" % (n, raw))
    return root


def load_eval_config(text, use_yaml=True):
    """The parsed file, with PyYAML when importable (what the host notebook uses), else mini_yaml."""
    if use_yaml:
        try:
            import yaml
        except ImportError:
            use_yaml = False
    raw = yaml.safe_load(text) if use_yaml else mini_yaml(text)
    return raw if isinstance(raw, dict) else {}


def host_budget(raw):
    """The host notebook's budget logic (cell 10), on an already-parsed eval_config mapping."""
    eval_section = raw.get("evaluation", raw)
    timeout_seconds = int(eval_section.get("timeout_seconds", 300))
    max_tool_calls = int(eval_section.get("max_tool_calls", 100))
    max_time_minutes = float(eval_section.get("max_time_minutes", 60.0))
    turns_raw = eval_section.get("max_turns", eval_section.get("max_llm_calls"))
    max_turns = int(turns_raw) if turns_raw is not None else None
    return dict(max_time_minutes=max_time_minutes, max_tool_calls=max_tool_calls, max_turns=max_turns,
                timeout_seconds=timeout_seconds)


def read_budget(bundle, overrides=None, use_yaml=True):
    """-> (budget, source): the bundle's eval_config.yaml read like the host notebook, then `overrides` (only keys whose
    value is not None). A bundle without the file would crash the host notebook, so it needs all four overrides."""
    overrides = {k: v for k, v in (overrides or {}).items() if v is not None}
    path = os.path.join(bundle, "eval_config.yaml")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            budget = host_budget(load_eval_config(f.read(), use_yaml))
        src = "eval_config.yaml"
    elif set(overrides) >= set(BUDGET_KEYS):
        budget, src = dict(HOST_DEFAULTS), "flags"
    else:
        raise SystemExit("make_eval_kernel: %s has no eval_config.yaml (the host notebook would fail reading it); pass "
                         "all of --min --calls --turns --timeout" % bundle)
    for k, v in overrides.items():
        budget[k] = float(v) if k == "max_time_minutes" else int(v)
    if overrides and src == "eval_config.yaml":
        src += " + flags " + ",".join(sorted(overrides))
    return budget, src


def bundle_files(bundle):
    files = {}
    for root, _, fs in os.walk(bundle):
        for f in fs:
            rel = os.path.relpath(os.path.join(root, f), bundle)
            if rel.startswith(".") or "__pycache__" in rel or f.endswith(".pyc") or f.startswith("._") or f == ".DS_Store":
                continue
            with open(os.path.join(root, f), "rb") as fh:
                files[rel] = base64.b64encode(fh.read()).decode()
    return files


CELL_INSTALL = r'''
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
# The wheel set this run used, by content: the host rebuilt vllm and adk_submission in place under the same version
# strings (org_update_0928 1.1), so A/B arms are paired only when these files are identical (scripts/ab_l4_decide.py).
import hashlib
with open('/kaggle/working/wheelhouse_sha256.txt', 'w') as _f:
    for w in sorted(WHEELHOUSE_DIR.glob('*.whl')):
        _h = hashlib.sha256()
        with open(w, 'rb') as _fh:
            for _b in iter(lambda: _fh.read(1 << 22), b''): _h.update(_b)
        _f.write(_h.hexdigest() + '  ' + w.name + '\n')
'''

# Budget cell body: the host notebook's own reading of the bundle's eval_config.yaml (cell 10), then the CLI overrides,
# then a stop before any GPU time is spent when the kernel's reading differs from the one the builder printed.
CELL_BUDGET = r'''
import yaml
eval_config_file = AGENT_DIR / 'eval_config.yaml'
raw_eval_cfg = (yaml.safe_load(eval_config_file.read_text(encoding='utf-8')) if eval_config_file.exists() else None) or {}
eval_section = raw_eval_cfg.get('evaluation', raw_eval_cfg)
timeout_seconds = int(eval_section.get('timeout_seconds', 300))
max_tool_calls = int(eval_section.get('max_tool_calls', 100))
max_time_minutes = float(eval_section.get('max_time_minutes', 60.0))
turns_raw = eval_section.get('max_turns', eval_section.get('max_llm_calls'))
max_turns = int(turns_raw) if turns_raw is not None else None
BUDGET = dict(max_time_minutes=max_time_minutes, max_tool_calls=max_tool_calls, max_turns=max_turns, timeout_seconds=timeout_seconds)
BUDGET.update(BUDGET_OVERRIDE)
assert BUDGET == EXPECTED_BUDGET, ('budget differs from the builder', BUDGET, EXPECTED_BUDGET)
'''

CELL_DATA_TAIL = r'''
from swegemma.models import load_tasks
tasks = load_tasks(DATA_DIR / 'tasks.jsonl')
if IDS: tasks = [t for t in tasks if t.instance_id in set(IDS)]
print(len(tasks), 'tasks', 'ORACLE' if ORACLE else 'AGENT', BUDGET)
'''

CELL_VLLM = r'''
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
        max_model_len=32768, dtype='bfloat16' if torch.cuda.is_bf16_supported() else 'auto', gpu_memory_utilization=0.90,
        enable_auto_tool_choice=True, enable_lora=True, max_loras=8, max_lora_rank=128, tensor_parallel_size=tp,
        startup_timeout=60 * 20)
    t0 = time.time(); server = VllmServer(cfg, adapter_manifest=adapters); server.start()
    print('vLLM up in', round(time.time() - t0), 's, tp', tp, 'gpus', n)
    models = server.create_model_registry(aliases=[declared, 'gemma-4-31b-it-qat-w4a16-ct'], model_prefix='openai/', api_key='EMPTY')
'''

CELL_RUN = r'''
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
    context_cache_config=ContextCacheConfig(min_tokens=@MIN_TOKENS@, ttl_seconds=@TTL@, cache_intervals=@CACHE_INTERVALS@),
    events_compaction_config=EventsCompactionConfig(compaction_interval=@INTERVAL@, overlap_size=@OVERLAP@, token_threshold=@THRESHOLD@, event_retention_size=@RETENTION@),
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
'''

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


CELL_PROBE = r'''
# G-A LoRA probe (docs/v11/GA_PROBE.md): does an adapter change this server's outputs at all? Runs before the agent smoke.
import json, statistics, time, urllib.request
BASE = 'http://127.0.0.1:8000/v1'
def _get(path):
    with urllib.request.urlopen(BASE + path, timeout=120) as r: return json.load(r)
def chat(model, content, max_tokens=32, timeout=600):
    body = json.dumps({'model': model, 'messages': [{'role': 'user', 'content': content}], 'max_tokens': max_tokens, 'temperature': 0, 'seed': 1}).encode()
    req = urllib.request.Request(BASE + '/chat/completions', data=body, headers={'Content-Type': 'application/json', 'Authorization': 'Bearer EMPTY'})
    t = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r: out = json.load(r)
    return (out['choices'][0]['message'].get('content') or ''), int((out.get('usage') or {}).get('completion_tokens') or 0), time.time() - t
ids = [m['id'] for m in _get('/models')['data']]
print('MODELS', ids)
def adapter_id(name): return next((i for i in ids if i == name or i.endswith(':' + name) or i.endswith('/' + name)), None)
base_id = next(i for i in ids if ':' not in i and i.split('/')[-1] not in ADAPTER_NAMES)
PROMPTS = ['List the first ten prime numbers.', 'Write a Python function that reverses a string.', 'What is the capital of Portugal?',
  'Explain what a race condition is in two sentences.', 'Give three synonyms for the word fast.', 'Write a haiku about rain.',
  'What does the git stash command do?', 'Convert 100 degrees Fahrenheit to Celsius.', 'Name four sorting algorithms.',
  'Write a regular expression that matches an email address.', 'What is the difference between a list and a tuple in Python?',
  'Summarise the plot of Romeo and Juliet in one sentence.', 'How many bits are in a byte?', 'Write a SQL query that counts rows in a table named users.',
  'What is the time complexity of binary search?', 'Translate good morning into French.', 'Write a bash one-liner that counts lines in all .py files.',
  'What is a Python decorator?', 'Name the planets of the solar system in order.', 'Explain the difference between TCP and UDP briefly.']
def run_all(model): return [chat(model, p)[0] for p in PROMPTS]
res = {'models': ids, 'base_id': base_id, 'adapters': {}}
base1 = run_all(base_id); base2 = run_all(base_id)
res['noise_floor'] = sum(a != b for a, b in zip(base1, base2))
for name in ADAPTER_NAMES:
    mid = adapter_id(name)
    if mid is None: res['adapters'][name] = {'listed': False}; continue
    try: res['adapters'][name] = {'listed': True, 'id': mid, 'diff_vs_base': sum(a != b for a, b in zip(base1, run_all(mid)))}
    except Exception as e: res['adapters'][name] = {'listed': True, 'id': mid, 'error': repr(e)[:200]}
    print(name, res['adapters'][name], flush=True)
long_prompt = 'Summarise this text in one sentence. ' + 'The quick brown fox jumps over the lazy dog. ' * 150
def tps(model):
    xs = []
    for _ in range(3):
        _, n, dt = chat(model, long_prompt, max_tokens=128); xs.append(n / max(dt, 1e-6))
    return round(statistics.median(xs), 2)
res['tps_base'] = tps(base_id)
zb = adapter_id('zb')
if zb:
    try: res['tps_zb'] = tps(zb)
    except Exception as e: res['tps_zb'] = 0; res['tps_zb_error'] = repr(e)[:200]
    try:
        _, n, dt = chat(zb, 'Reply with the single word ok. ' + 'word ' * 24000, max_tokens=8, timeout=900); res['long_ctx_zb_s'] = round(dt, 1)
    except Exception as e: res['long_ctx_zb_s'] = 'ERROR ' + repr(e)[:200]
A = res['adapters']
checks = {'P1_applied': any(A.get(n, {}).get('diff_vs_base', 0) >= 18 for n in ('loud', 'loud2')),
          'P2_zero_b_harmless': A.get('zb', {}).get('diff_vs_base', 99) <= res['noise_floor'] + 1,
          'P3_listed': all(A.get(n, {}).get('listed') for n in ADAPTER_NAMES),
          'P4_decode_tax_le_10pct': res.get('tps_zb', 0) >= 0.9 * res['tps_base'],
          'P5_long_ctx_returns': isinstance(res.get('long_ctx_zb_s'), (int, float))}
res['checks'] = checks
res['prefix'] = 'plan_A' if A.get('loud', {}).get('diff_vs_base', 0) >= 18 else ('loud2' if A.get('loud2', {}).get('diff_vs_base', 0) >= 18 else 'none')
res['GA_pre_smoke'] = 'PASS' if checks['P1_applied'] and checks['P2_zero_b_harmless'] and checks['P5_long_ctx_returns'] else 'FAIL'
json.dump(res, open(W / 'lora_probe.json', 'w'), indent=1); print(json.dumps(res, indent=1))
for k, v in checks.items(): print(('PASS ' if v else 'FAIL ') + k)
print('GA_PRE_SMOKE', res['GA_pre_smoke'], 'prefix', res['prefix'], flush=True)
'''

CELL_ROUTE = r'''
# P6: the agent smoke's fixer calls must have gone to the adapter-backed model.
import glob, json
n_fixer = n_zb = 0
for f in glob.glob(str(W / 'results' / '**' / 'trace_*.json'), recursive=True):
    for s in json.load(open(f)).get('steps', []):
        for c in s.get('tool_calls') or []:
            if (c.get('extra') or {}).get('author') == 'fixer':
                mv = str((c.get('extra') or {}).get('model_version') or s.get('model_name') or '')
                n_fixer += 1; n_zb += (':zb' in mv or mv.endswith('/zb') or mv == 'zb')
rows = [json.loads(l) for l in open(W / 'results.jsonl')]
crash = [r['id'] for r in rows if r.get('err') and 'timeout' not in str(r.get('err')).lower()]
p6 = len(rows) == len(IDS) and not crash and n_fixer > 0 and n_zb == n_fixer
print('ROUTING fixer calls', n_fixer, 'to :zb', n_zb, '| rows', len(rows), 'crash', crash)
print(('PASS ' if p6 else 'FAIL ') + 'P6_agent_smoke')
pre = json.load(open(W / 'lora_probe.json'))
pre['P6_agent_smoke'] = p6; pre['GA'] = 'PASS' if pre['GA_pre_smoke'] == 'PASS' and p6 else 'FAIL'
json.dump(pre, open(W / 'lora_probe.json', 'w'), indent=1); print('GA', pre['GA'])
'''


def adapter_names(bundle):
    d = os.path.join(bundle, "adapters")
    return sorted(n for n in os.listdir(d) if os.path.isfile(os.path.join(d, n, "adapter_model.safetensors"))) if os.path.isdir(d) else []


def build_cells(files, ids, patches, oracle, budget, override, helper_b64=None, probe=None, names=()):
    run = CELL_RUN
    for k, v in (("@MIN_TOKENS@", CONTEXT_CACHE["min_tokens"]), ("@TTL@", CONTEXT_CACHE["ttl_seconds"]),
                 ("@CACHE_INTERVALS@", CONTEXT_CACHE["cache_intervals"]), ("@INTERVAL@", COMPACTION["compaction_interval"]),
                 ("@OVERLAP@", COMPACTION["overlap_size"]), ("@THRESHOLD@", COMPACTION["token_threshold"]),
                 ("@RETENTION@", COMPACTION["event_retention_size"])):
        run = run.replace(k, repr(v))
    data = ("FILES = " + json.dumps(files) + "\nIDS = " + json.dumps(ids) + "\nPATCHES = " + json.dumps(patches) +
            "\nORACLE = %s\nBUDGET_OVERRIDE = %s\nEXPECTED_BUDGET = %s\n" % (oracle, repr(override), repr(budget)) + r'''
DATA_DIR = Path('/kaggle/input/competitions/gemma-4-developer-agent')
if not DATA_DIR.exists(): DATA_DIR = Path('/kaggle/input/gemma-4-developer-agent')
W = Path('/kaggle/working'); AGENT_DIR = W / 'bundle'
shutil.rmtree(AGENT_DIR, ignore_errors=True)
for rel, b in FILES.items():
    p = AGENT_DIR / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(base64.b64decode(b))
''' + CELL_BUDGET + CELL_DATA_TAIL)
    cells = [CELL_INSTALL, data, CELL_VLLM, run]
    if probe == "lora":
        if not names:
            raise SystemExit("--probe lora needs a bundle with adapters/<name>/adapter_model.safetensors (scripts/make_test_adapters.py)")
        cells = [CELL_INSTALL, data, CELL_VLLM, "ADAPTER_NAMES = " + json.dumps(list(names)) + "\n" + CELL_PROBE, run, CELL_ROUTE]
    if helper_b64 is not None:
        cells.insert(1, "HELPERS_B64 = " + json.dumps(helper_b64) + "\ndef _helper_check():" + HELPER_BODY.replace("\n", "\n    ") +
                     "\ntry: _helper_check()\nexcept Exception as e: print('HELPER_CHECK ERROR', repr(e)[:300])\n")
    return cells


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("bundle"); ap.add_argument("slug"); ap.add_argument("--ids")
    ap.add_argument("--oracle", action="store_true")
    ap.add_argument("--patches", help="rescore agent patches: json list of {task,cfg,patch} (CPU, Kaggle env)")
    ap.add_argument("--helper-check", help="skill scripts dir to test for sandbox reachability on the Kaggle image (CPU)")
    ap.add_argument("--probe", choices=["lora"], help="lora: run the G-A adapter probe (docs/v11/GA_PROBE.md) before the agent smoke")
    ap.add_argument("--min", type=float, default=None, help="override max_time_minutes (default: eval_config.yaml)")
    ap.add_argument("--calls", type=int, default=None, help="override max_tool_calls (default: eval_config.yaml)")
    ap.add_argument("--turns", type=int, default=None, help="override max_turns (default: eval_config.yaml)")
    ap.add_argument("--timeout", type=int, default=None, help="override timeout_seconds (default: eval_config.yaml)")
    a = ap.parse_args(argv)
    override = {k: v for k, v in (("max_time_minutes", a.min), ("max_tool_calls", a.calls), ("max_turns", a.turns),
                                   ("timeout_seconds", a.timeout)) if v is not None}
    if "max_time_minutes" in override:
        override["max_time_minutes"] = float(override["max_time_minutes"])
    budget, src = read_budget(a.bundle, override)
    patches = {}
    if a.patches:
        a.oracle = True
        with open(a.patches) as f:
            for r in json.load(f):
                if r["patch"].strip():
                    patches.setdefault(r["cfg"], {})[r["task"]] = r["patch"]
    files = bundle_files(a.bundle)
    ids = []
    if a.ids:
        with open(a.ids) as f:
            ids = [l.strip() for l in f if l.strip()]
    hb = None
    if a.helper_check:
        hb = {}
        for f in sorted(os.listdir(a.helper_check)):
            if f.endswith(".py"):
                with open(os.path.join(a.helper_check, f), "rb") as fh:
                    hb[f] = base64.b64encode(fh.read()).decode()
    cells = build_cells(files, ids, patches, a.oracle, budget, override, hb, probe=a.probe, names=adapter_names(a.bundle))
    nb = {"cells": [{"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": c} for c in cells],
          "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}}, "nbformat": 4, "nbformat_minor": 5}
    kd = os.path.join("kernels", a.slug)
    os.makedirs(kd, exist_ok=True)
    with open(os.path.join(kd, a.slug + ".ipynb"), "w") as f:
        json.dump(nb, f)
    meta = {"id": "carsonrodrigues/" + a.slug, "title": a.slug, "code_file": a.slug + ".ipynb", "language": "python", "kernel_type": "notebook",
            "is_private": True, "enable_gpu": not a.oracle, "enable_tpu": False, "enable_internet": False,
            "dataset_sources": ["metric/gemma-4-developer-agent-wheelhouse"], "competition_sources": ["gemma-4-developer-agent"],
            "kernel_sources": [], "model_sources": [] if a.oracle else ["google/gemma-4/Other/gemma-4-31b-it-qat-w4a16-ct/2"]}
    if not a.oracle:
        meta["machine_shape"] = "NvidiaL4"
    with open(os.path.join(kd, "kernel-metadata.json"), "w") as f:
        json.dump(meta, f, indent=2)
    print(kd, len(files), "files", len(ids) or "all", "tasks", "budget", json.dumps(budget, sort_keys=True), "from", src)
    return 0


if __name__ == "__main__":
    sys.exit(main())
