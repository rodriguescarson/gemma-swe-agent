"""The Kaggle kernel's run cell (scripts/make_eval_kernel.py CELL_RUN + CELL_BUDGET) against a vLLM that is already up
(scripts/a6000/serve.sh): swegemma Evaluator, SUBPROCESS sandbox (the scorer's backend), budgets read from the bundle's
eval_config.yaml, compaction 15/2/14336/5, context cache 2048/1800/10, tasks one after another like the scorer.

    ~/g4/venv/bin/python -I scripts/a6000/run_eval.py BUNDLE OUT_DIR [--ids FILE] [--n N] [--port 8000]

OUT_DIR/results.jsonl has the kernel's row fields; OUT_DIR/results/ holds the traces (what
scripts/analyze_helper_reachability.py reads). Env as in the kernel's install cell."""
import argparse, json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from make_eval_kernel import COMPACTION, CONTEXT_CACHE, read_budget  # noqa: E402

DATA = ROOT / "data" / "raw"
ENV = {"LITELLM_LOCAL_MODEL_COST_MAP": "True", "TRANSFORMERS_NO_TF": "1", "VLLM_WORKER_MULTIPROC_METHOD": "spawn",
       "VLLM_NO_USAGE_STATS": "1", "OTEL_SDK_DISABLED": "true"}


def first_ids(path, n):
    ids = [l.strip() for l in open(path) if l.strip()]
    return ids[:n] if n else ids


def done_ids(path):
    try:
        return {json.loads(l)["id"] for l in open(path) if l.strip()}
    except FileNotFoundError:
        return set()


def remaining(ids, done):
    return [i for i in ids if i not in done]


def budget_for(bundle):
    return read_budget(bundle)[0]


def result_row(cfg, tid, resolved, exit_code, calls, secs, err, patch, t=None):
    """t = the wall-clock finish time (epoch): lets the GPU-contention guard re-run what finished during a contended window."""
    return dict(cfg=cfg, id=tid, resolved=bool(resolved), exit=exit_code, calls=calls, secs=round(secs, 1), err=err, patch=patch, t=t)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("bundle"); ap.add_argument("out")
    ap.add_argument("--ids", default=str(ROOT / "data" / "kaggle_valid_ids.txt"))
    ap.add_argument("--n", type=int, default=None, help="first N ids of the file")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--resume", action="store_true", help="append to OUT/results.jsonl and skip ids already in it")
    a = ap.parse_args(argv)
    os.environ.update(ENV)
    import asyncio, concurrent.futures, subprocess
    import litellm
    from google.adk.agents.context_cache_config import ContextCacheConfig
    from google.adk.apps._configs import EventsCompactionConfig
    from adk_submission import VllmConfig, VllmServer, discover_adapters
    from swegemma.config import ALLOWED_ADAPTER_EXTENSIONS, EvalConfig, build_submission_limits
    from swegemma.evaluate import Evaluator
    from swegemma.models import load_tasks
    from swegemma.models.discovery import validate_single_declared_model
    litellm.drop_params = True
    bundle, out_dir = Path(a.bundle).resolve(), Path(a.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    budget = budget_for(str(bundle))
    done = done_ids(str(out_dir / "results.jsonl")) if a.resume else set()
    wanted = remaining(first_ids(a.ids, a.n), done)
    ids = set(wanted)
    tasks = [t for t in load_tasks(DATA / "tasks.jsonl") if t.instance_id in ids]
    order = {i: k for k, i in enumerate(wanted)}
    tasks.sort(key=lambda t: order[t.instance_id])
    declared = validate_single_declared_model(bundle)
    adapters = discover_adapters(str(bundle), adapter_extensions=ALLOWED_ADAPTER_EXTENSIONS)
    # a handle on the running server, only to build the model registry (never started or stopped here)
    cfg = VllmConfig(model=os.environ.get("MODEL_DIR", str(Path.home() / "g4" / "model")), port=a.port, host="127.0.0.1",
                     tool_call_parser="gemma4", reasoning_parser="gemma4", max_model_len=32768, dtype="bfloat16",
                     gpu_memory_utilization=0.90, enable_auto_tool_choice=True, enable_lora=True, max_loras=8,
                     max_lora_rank=128, tensor_parallel_size=1)
    models = VllmServer(cfg, adapter_manifest=adapters).create_model_registry(
        aliases=[declared, "gemma-4-31b-it-qat-w4a16-ct"], model_prefix="openai/", api_key="EMPTY")
    limits, gen = build_submission_limits()
    ec = EvalConfig(tasks_path=DATA / "tasks.jsonl", snapshots_dir=DATA / "snapshots", results_dir=out_dir / "results",
                    submission_dir=bundle, models=models, sandbox="subprocess", limits=limits, generation_constraints=gen,
                    adapter_manifest=adapters,
                    context_cache_config=ContextCacheConfig(min_tokens=CONTEXT_CACHE["min_tokens"], ttl_seconds=CONTEXT_CACHE["ttl_seconds"],
                                                            cache_intervals=CONTEXT_CACHE["cache_intervals"]),
                    events_compaction_config=EventsCompactionConfig(compaction_interval=COMPACTION["compaction_interval"],
                                                                    overlap_size=COMPACTION["overlap_size"],
                                                                    token_threshold=COMPACTION["token_threshold"],
                                                                    event_retention_size=COMPACTION["event_retention_size"]),
                    graph_dir=str(DATA / "graphs"), embeddings_dir=str(DATA / "embeddings"), wheels_dir=DATA / "wheels",
                    verbose=False, **budget)
    ev = Evaluator(ec)

    def run_sync(fn):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(1) as pool:
                return pool.submit(lambda: asyncio.run(fn())).result()
        return asyncio.run(fn())

    subprocess.run(f"{sys.executable} -m pip freeze > {out_dir}/pip_freeze.txt", shell=True)
    print(len(tasks), "tasks", budget, flush=True)
    t0 = time.time()
    with open(out_dir / "results.jsonl", "a" if a.resume else "w") as out:
        for i, t in enumerate(tasks, 1):
            s = time.time()
            try:
                r = run_sync(lambda: ev.evaluate_task(task=t, task_index=i, total_tasks=len(tasks)))
                row = result_row(None, t.instance_id, r.resolved, r.test_exit_code, r.tool_calls, time.time() - s,
                                 (str(r.error)[:300] if r.error else None), r.agent_patch or "", t=time.time())
            except Exception as e:
                row = dict(cfg=None, id=t.instance_id, resolved=False, err="EXC " + repr(e)[:300], secs=round(time.time() - s, 1), t=time.time())
            out.write(json.dumps(row) + "\n"); out.flush()
            print(i, row["id"], row["resolved"], row.get("calls"), row["secs"], (row.get("err") or "")[:80], flush=True)
    n = sum(json.loads(l)["resolved"] for l in open(out_dir / "results.jsonl"))
    print("TOTAL", n, "rows", len(tasks), "in", round(time.time() - t0), "s")


if __name__ == "__main__":
    main()
