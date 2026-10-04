"""Train a Gemma 4 31B LoRA on Adaption (AutoScientist) from build_sft rows, then fetch the PEFT adapter.

    python train/adaption_train.py rows.jsonl --name v11a            # upload + print the exact run payload, no launch
    python train/adaption_train.py rows.jsonl --name v11a --launch   # also create the run (needs Carson's explicit go:
                                                                     # every AutoScientist run appears on their board)
    python train/adaption_train.py --status RUN_ID                   # poll
    python train/adaption_train.py --download RUN_ID --out adapters/v11a   # tarball -> dir, prints base/template facts

Recipe (docs/v11/PLAN.md 2026-10-02): platform-default LoRA (r 8, alpha 16, lr 1e-4, 1 epoch, batch max) on
q_proj,k_proj,v_proj,o_proj; data_format "instruction" (raw prompt+completion, loss on completion only:
train_on_inputs False); augmentation 0/0; max_iterations 1; training_method instruction. The upload is a raw dataset
with column_mapping prompt/completion. Key: ADAPTION_API_KEY (env or ~/Projects/env-backups/autoscientist-challenge/.env).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tarfile
import time
from pathlib import Path

MODEL = "google/gemma-4-31B-it"
HYPERPARAMS = {"training_type": "lora", "n_epochs": 1, "learning_rate": 1e-4, "batch_size": "max", "lora_r": 8,
               "lora_alpha": 16, "lora_dropout": 0.0, "lora_trainable_modules": "q_proj,k_proj,v_proj,o_proj",
               "lr_scheduler_type": "linear", "warmup_ratio": 0.03, "train_on_inputs": False}
MIN_ROWS = 10000     # Adaption: bases of 26B+ refuse fewer rows


def api_key(env_file=os.path.expanduser("~/Projects/env-backups/autoscientist-challenge/.env")):
    k = os.environ.get("ADAPTION_API_KEY")
    if not k and os.path.exists(env_file):
        for line in open(env_file):
            if line.startswith("ADAPTION_API_KEY="):
                k = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not k:
        raise SystemExit("ADAPTION_API_KEY not found")
    return k


def client():
    from adaption import Adaption
    return Adaption(api_key=api_key())


def run_payload(dataset_id: str, name: str, model: str = MODEL, hyperparams: dict | None = None) -> dict:
    """The exact create() arguments; pure, so a test can pin them."""
    hp = dict(HYPERPARAMS, **(hyperparams or {}))
    # no column_mapping / data_format here: create() refused them on 2026-10-03 ("Selected columns ... are not in this
    # dataset"); the mapping is given to upload_file() on a parquet file, as in every run that trained (adaption-leaderboard)
    return {"dataset_id": dataset_id, "model": model, "training_method": "instruction", "hyperparams": hp,
            "augmentation_domain_rows": 0, "augmentation_general_rows": 0, "max_iterations": 1,
            "idempotency_key": "g4-" + hashlib.sha1(f"{dataset_id}|{name}|{json.dumps(hp, sort_keys=True)}".encode()).hexdigest()[:16]}


def check_rows(path: str) -> int:
    n = 0
    for line in open(path):
        if line.strip():
            r = json.loads(line)
            if not isinstance(r.get("prompt"), str) or not isinstance(r.get("completion"), str) or not r["prompt"] or not r["completion"]:
                raise SystemExit(f"row {n} lacks a non-empty prompt/completion")
            n += 1
    return n


def strip_meta(src: str, dst: str) -> int:
    """Adaption only needs prompt/completion; the meta column stays local. Written as parquet: a JSONL upload came back
    with no usable columns on 2026-10-03, every upload that trained on the platform was parquet."""
    import pandas as pd
    rows = [json.loads(line) for line in open(src) if line.strip()]
    pd.DataFrame({"prompt": [r["prompt"] for r in rows], "completion": [r["completion"] for r in rows]}).to_parquet(dst, index=False)
    return len(rows)


def upload(c, rows_path: str, name: str) -> str:
    import httpx
    _put = httpx.put
    httpx.put = lambda *a, **k: _put(*a, **{**k, "timeout": httpx.Timeout(900.0)})   # large uploads stall the default
    ds = c.datasets.upload_file(rows_path, name=name, processing_mode="raw",
                                column_mapping={"prompt": "prompt", "completion": "completion"})
    c.datasets.wait_for_completion(ds.dataset_id, timeout=3600)
    return ds.dataset_id


def download(c, run_id: str, out_dir: str) -> dict:
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    tgz = out / "adapter.tgz"
    with c.autoscientist.with_streaming_response.download(run_id) as r:
        with open(tgz, "wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    with open(tgz, "rb") as f:
        magic = f.read(4)
    if magic == b"\x28\xb5\x2f\xfd":      # zstd-compressed tar (what the platform ships, 2026-10-03), not gzip
        import shutil, subprocess
        if shutil.which("zstd"):
            tar = out / "adapter.tar"
            with open(tar, "wb") as tf:
                subprocess.run(["zstd", "-dc", str(tgz)], stdout=tf, check=True)
            with tarfile.open(tar) as t:
                t.extractall(out)
            tar.unlink()
        else:
            import zstandard
            with open(tgz, "rb") as f, tarfile.open(fileobj=zstandard.ZstdDecompressor().stream_reader(f), mode="r|") as t:
                t.extractall(out)
    else:
        with tarfile.open(tgz) as t:
            t.extractall(out)
    facts = {"files": sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file())}
    for p in out.rglob("adapter_config.json"):
        cfg = json.load(open(p)); facts["adapter_config"] = {k: cfg.get(k) for k in ("base_model_name_or_path", "r", "lora_alpha", "target_modules", "revision")}
    for p in out.rglob("chat_template.jinja"):
        facts["chat_template_sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()[:12]
        facts["chat_template_bytes"] = p.stat().st_size
    for p in out.rglob("config.json"):
        cfg = json.load(open(p)); facts["config"] = {k: cfg.get(k) for k in ("_name_or_path", "architectures", "transformers_version", "torch_dtype")}
    for p in out.rglob("adapter_model.safetensors"):
        import struct
        with open(p, "rb") as f:
            n = struct.unpack("<Q", f.read(8))[0]; hdr = json.loads(f.read(n))
        keys = [k for k in hdr if k != "__metadata__"]
        facts["tensors"] = {"count": len(keys), "first": keys[:2], "dtype": hdr[keys[0]]["dtype"] if keys else None, "bytes": p.stat().st_size}
    return facts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rows", nargs="?")
    ap.add_argument("--name", default=None)
    ap.add_argument("--launch", action="store_true", help="create the AutoScientist run (asks nothing; get Carson's go first)")
    ap.add_argument("--dataset-id", default=None, help="reuse an uploaded dataset instead of uploading")
    ap.add_argument("--status", default=None, metavar="RUN_ID")
    ap.add_argument("--download", default=None, metavar="RUN_ID")
    ap.add_argument("--out", default="adapters/v11a")
    ap.add_argument("--allow-small", action="store_true", help="skip the 10k-row floor check (for a format probe)")
    ap.add_argument("--lr", type=float, default=None, help="learning_rate override (v11b: 5e-5)")
    a = ap.parse_args()
    c = client()
    if a.status:
        runs = c.autoscientist.list(limit=50)
        runs = runs.model_dump() if hasattr(runs, "model_dump") else runs
        for r in runs.get("runs", runs.get("data", [])):
            if r.get("id") == a.status:
                print(json.dumps(r, indent=1, default=str)); return
        print("run not found in the last 50"); return
    if a.download:
        print(json.dumps(download(c, a.download, a.out), indent=1)); return
    if not a.rows or not a.name:
        ap.error("rows and --name are required to upload")
    n = check_rows(a.rows)
    print(f"{n} rows in {a.rows}")
    if n < MIN_ROWS and not a.allow_small:
        raise SystemExit(f"{n} rows < {MIN_ROWS}: Adaption refuses 31B training below that; pass --allow-small only for a format probe on a small base")
    ds = a.dataset_id
    if not ds:
        clean = a.rows + ".upload.parquet"
        strip_meta(a.rows, clean)
        ds = upload(c, clean, a.name)
        print("dataset", ds, "processed")
    payload = run_payload(ds, a.name, hyperparams={"learning_rate": a.lr} if a.lr else None)
    print("run payload:", json.dumps(payload, indent=1))
    if not a.launch:
        print("not launched (pass --launch after Carson's go)"); return
    run = c.autoscientist.create(**payload)
    run = run.model_dump() if hasattr(run, "model_dump") else run
    print("LAUNCHED", json.dumps(run, indent=1, default=str))


if __name__ == "__main__":
    main()
