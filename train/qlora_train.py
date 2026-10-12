"""QLoRA of the served Gemma 4 31B on stitched thinking-on sequences, on one 48 GB A6000 (plan ~/.claude/plans/nifty-sleeping-liskov.md,
"Training step design"; thresholds in docs/a6000/TRAIN_LOCAL.md). NF4 base from the dequantised W4A16 checkpoint (train/dequant_ct.py),
LoRA r16/alpha32 on q,v,o,gate,up,down (+k on the sliding layers), loss only at supervised positions through a chunked soft-capped
lm_head (the 262,144-token vocabulary never materialises as full logits), one sequence per micro-batch, grad_accum 8, token-mean loss
per step, warmup+cosine, held-out NLL split text/tool every --eval-every steps with early stop, checkpoints + cursor for resume.

    python train/qlora_train.py --seqs seqs.jsonl --holdout holdout.jsonl --base ~/g4/model-bf16 --out ~/g4/runs/train_x/run [--resume]
    python train/qlora_train.py --probe --seqs seqs_probe.jsonl --holdout holdout.jsonl --base ... --out .../probe --max-tokens 16384
    python train/qlora_train.py --dry-run --seqs ... --tokenizer-json adapters/v11b/tokenizer.json     (CPU: data stats + the plan)

Exit codes: 0 done (probe: FULL or REDUCED), 2 environment, 3 GPU not idle / probe FALLBACK, 4 aborted on repeated OOM."""
import argparse
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from train.qlora_lib import THRASH_TOK_S, Cursor, bucket_unusable, epoch_order, lr_at, per_token_nll, probe_plan, probe_throughput, probe_verdict  # noqa: E402
from train.qlora_model import (SERVED_BASE, attach_lora, base_of, configure_training, evaluate, export_adapter, forward_hidden,  # noqa: E402
                               head_weight, load_base_nf4, prepare_item, sequence_loss, softcap_of, to_device)

BUCKETS = ((0, 5000), (5000, 9000), (9000, 13000), (13000, 10 ** 9))


def parse(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--seqs", required=True); ap.add_argument("--holdout", default=None); ap.add_argument("--base", default=None); ap.add_argument("--out", default=None)
    ap.add_argument("--tokenizer-json", default=None, help="default <base>/tokenizer.json")
    ap.add_argument("--probe", action="store_true"); ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--resume", action="store_true")
    ap.add_argument("--max-tokens", type=int, default=14336); ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--r", type=int, default=16); ap.add_argument("--alpha", type=int, default=32); ap.add_argument("--dropout", type=float, default=0.05)
    ap.add_argument("--no-k", action="store_true", help="no k_proj LoRA at all (default: k on the sliding layers)")
    ap.add_argument("--lr", type=float, default=5e-5); ap.add_argument("--grad-accum", type=int, default=8); ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--max-steps", type=int, default=0); ap.add_argument("--clip", type=float, default=1.0); ap.add_argument("--chunk", type=int, default=1024)
    ap.add_argument("--eval-every", type=int, default=40); ap.add_argument("--save-every", type=int, default=40)
    ap.add_argument("--attn", default="sdpa", choices=["sdpa", "flex_attention", "eager"]); ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--served-base", default=SERVED_BASE)
    return ap.parse_args(argv)


def gb(x):
    return round(x / 1024 ** 3, 2)


def mem():
    if not torch.cuda.is_available():
        return {}
    return {"alloc_gb": gb(torch.cuda.memory_allocated()), "reserved_gb": gb(torch.cuda.memory_reserved()), "peak_reserved_gb": gb(torch.cuda.max_memory_reserved())}


def nvidia_smi_used_gb():
    """Device-level memory in use per nvidia-smi (GB; GPU 0), None when nvidia-smi is unavailable. Read BEFORE this process
    creates its CUDA context: torch.cuda.mem_get_info() counts the context itself (~1 GB), so on 2026-10-12 a bare torch
    process on the idle A6000 (533 MiB for the Windows display) read 1.56 GB and the 1.0 GB idle check could never pass."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=20)
        if out.returncode == 0 and out.stdout.strip():
            return round(float(out.stdout.strip().splitlines()[0].strip()) / 1024, 2)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return None


def used_before_load_gb(smi_gb, torch_gb):
    """The idle check's reading: nvidia-smi when available (device-level, without our own context), else torch's."""
    return smi_gb if smi_gb is not None else torch_gb


class Log:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, **kw):
        kw = {"t": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **kw}
        line = json.dumps(kw, default=str)
        print(line, flush=True)
        with open(self.path, "a") as f:
            f.write(line + "\n")


def load_items(path, tok, max_tokens, limit=0):
    items = []
    with open(path) as f:
        for line in f:
            if line.strip():
                items.append(prepare_item(json.loads(line), tok, max_tokens))
                if limit and len(items) >= limit:
                    break
    return items


def data_stats(items):
    return {"sequences": len(items), "tokens": sum(it["tokens"] for it in items), "supervised_tokens": sum(len(it["positions"]) for it in items),
            "weighted_tokens": round(sum(it["wsum"] for it in items)), "max_tokens": max((it["tokens"] for it in items), default=0),
            "buckets": [len(b) for b in probe_plan(items, per_bucket=10 ** 9, buckets=BUCKETS)]}


def lora_params(pm):
    return [p for p in pm.parameters() if p.requires_grad]


def one_sequence_backward(pm, item, denom, chunk, device):
    loss = sequence_loss(pm, to_device(item, device), denom, chunk)
    loss.backward()
    return float(loss.item())


def save_ckpt(pm, opt, out, cursor):
    d = Path(out) / "ckpt"
    d.mkdir(parents=True, exist_ok=True)
    pm.save_pretrained(str(d))
    torch.save(opt.state_dict(), d / "optimizer.pt")
    cursor.save()


def load_ckpt(pm, opt, out):
    from peft import set_peft_model_state_dict
    from safetensors.torch import load_file
    d = Path(out) / "ckpt"
    set_peft_model_state_dict(pm, load_file(str(d / "adapter_model.safetensors")))
    if (d / "optimizer.pt").exists():
        opt.load_state_dict(torch.load(d / "optimizer.pt", map_location="cuda"))


def truncate(item, n):
    keep = item["positions"] < n - 1
    return {**item, "ids": item["ids"][:n], "positions": item["positions"][keep], "targets": item["targets"][keep], "weights": item["weights"][keep],
            "kinds": item["kinds"][keep], "wsum": float(item["weights"][keep].sum()), "tokens": min(n, item["tokens"])}


def probe_cut(item, n=2048, min_supervised=64):
    """The forward2k window: the item's first max(n, enough to cover min_supervised supervised positions) tokens. 2026-10-12 on
    the box: a v12 sequence's first 2,048 tokens are the system prompt, the tool declarations and the task, so the plain 2k
    prefix held no supervised position and the check crashed on an empty logits tensor (probe log, box b4fa2359)."""
    pos = item["positions"]
    if len(pos) == 0:
        return truncate(item, n)
    k = min(min_supervised, len(pos)) - 1
    need = int(pos.sort().values[k]) + 2            # a position indexes the hidden state whose NEXT token is supervised
    return truncate(item, max(n, need))


def run_probe(a, pm, info, items, held, log, out, loaded):
    """docs/a6000/TRAIN_LOCAL.md, "The 1-hour feasibility probe": every number it needs, then the verdict."""
    dev = torch.device("cuda")
    base = base_of(pm)
    rep = {"load": loaded, "lora": info, "data": data_stats(items), "holdout": len(held)}
    import bitsandbytes as bnb
    rep["bitsandbytes"] = bnb.__version__
    # stage 3: a 2k forward on the base LoRA (B = 0): logits bounded by the softcap, base NLL in range
    pm.eval()
    probe_item = probe_cut(max(items, key=lambda it: it["tokens"]), 2048)
    if len(probe_item["positions"]) == 0:
        raise RuntimeError("forward2k: the longest sequence has no supervised position at all")
    with torch.no_grad():
        it = to_device(probe_item, dev)
        hs = forward_hidden(pm, it["ids"])
        g = hs[it["positions"]]
        logits = torch.nn.functional.linear(g[:256], head_weight(base).to(g.dtype)).float()
        cap = softcap_of(base)
        capped = torch.tanh(logits / cap) * cap if cap else logits
        nll = per_token_nll(g, head_weight(base), it["targets"], softcap=cap, chunk=a.chunk)
        base_nll = float((nll * it["weights"]).sum() / it["weights"].sum().clamp_min(1e-6))
    pm.train()
    rep["forward2k"] = {"tokens": probe_item["tokens"], "supervised": int(len(probe_item["positions"])), "max_abs_logit": round(float(capped.abs().max()), 3),
                        "base_nll": round(base_nll, 4), **mem()}
    log(event="probe_forward2k", **rep["forward2k"])
    opt = torch.optim.AdamW(lora_params(pm), lr=a.lr, betas=(0.9, 0.999), eps=1e-8, weight_decay=0.0)
    # stage 4a: single-sequence steps per token bucket, longest first
    buckets = []
    for (lo, hi), seqs in zip(BUCKETS, probe_plan(items, per_bucket=5, buckets=BUCKETS)):
        b = {"range": [lo, hi], "n": len(seqs), "steps": [], "oom": False}
        for it in seqs:
            torch.cuda.reset_peak_memory_stats(); torch.cuda.synchronize(); t = time.time()
            try:
                loss = one_sequence_backward(pm, it, it["wsum"] or 1.0, a.chunk, dev)
                gn = float(torch.nn.utils.clip_grad_norm_(lora_params(pm), a.clip))
                opt.step(); opt.zero_grad(set_to_none=True); torch.cuda.synchronize()
                dt = time.time() - t
                s = {"tokens": it["tokens"], "s": round(dt, 2), "tok_s": round(it["tokens"] / dt), "loss": round(loss, 4), "grad_norm": round(gn, 3), "peak_reserved_gb": gb(torch.cuda.max_memory_reserved())}
            except torch.cuda.OutOfMemoryError:
                opt.zero_grad(set_to_none=True); torch.cuda.empty_cache()
                s = {"tokens": it["tokens"], "oom": True, "peak_reserved_gb": gb(torch.cuda.max_memory_reserved())}
                b["oom"] = True
            b["steps"].append(s)
            log(event="probe_step", bucket=[lo, hi], **s)
            if b["oom"]:
                break
        buckets.append(b)
    # stage 4b: 24 steps over 8 sequences near 6k tokens, grad_accum 4: the loss must fall
    eight = sorted(items, key=lambda it: abs(it["tokens"] - 6000))[:8]
    losses, gns = [], []
    for step in range(24):
        batch = eight[(step % 2) * 4:(step % 2) * 4 + 4]
        W = sum(it["wsum"] for it in batch) or 1.0
        t = time.time(); lsum = 0.0
        try:
            for it in batch:
                lsum += one_sequence_backward(pm, it, W, a.chunk, dev)
        except torch.cuda.OutOfMemoryError:
            opt.zero_grad(set_to_none=True); torch.cuda.empty_cache(); log(event="probe_repeat_oom", step=step); continue
        gn = float(torch.nn.utils.clip_grad_norm_(lora_params(pm), a.clip)); opt.step(); opt.zero_grad(set_to_none=True); torch.cuda.synchronize()
        losses.append(lsum); gns.append(gn)
        log(event="probe_repeat", step=step, loss=round(lsum, 4), grad_norm=round(gn, 3), tokens=sum(it["tokens"] for it in batch), seconds=round(time.time() - t, 1))
    tok_s, excluded = probe_throughput(buckets)        # buckets that OOM'd or thrashed say nothing about the run's pace (TRAIN_LOCAL)
    top_unusable = bucket_unusable(buckets[3])
    b12 = buckets[2]
    peak12 = 99.0 if b12["oom"] else (max((s["peak_reserved_gb"] for s in b12["steps"]), default=None))
    nan = any(not math.isfinite(x) for x in losses)
    loss_first = sum(losses[:2]) / 2 if len(losses) >= 2 else (losses[0] if losses else None)
    loss_last = sum(losses[-2:]) / 2 if len(losses) >= 2 else None
    out_dir, erep = export_adapter(pm, Path(out) / "probe_adapter_bf16", a.served_base)
    verdict, reasons = probe_verdict(peak12, tok_s, loss_first, loss_last, nan=nan, max_grad=max(gns, default=0.0))
    if rep["forward2k"]["max_abs_logit"] > cap + 0.5:
        verdict, reasons = "FALLBACK", [f"max |logit| {rep['forward2k']['max_abs_logit']} > softcap {cap}"] + reasons
    if base_nll > 1.5:
        verdict, reasons = "FALLBACK", [f"base NLL {base_nll:.3f} > 1.5: the base is not the served model"] + reasons
    elif base_nll < 0.3:                                # informational since 2026-10-12: a low NLL on its own samples cannot mean a wrong base (TRAIN_LOCAL)
        reasons.append(f"base NLL {base_nll:.3f} < 0.3 on {len(probe_item['positions'])} supervised tokens: the model is confident on its own samples (informational)")
    if peak12 is None:
        reasons.append("no sequence in the 9k-13k bucket: the 12k memory check did not run")
    if excluded:
        reasons.append(f"buckets {excluded} OOM'd or thrashed (< {THRASH_TOK_S:.0f} tok/s): excluded from tok/s; the run caps at 12,288")
    cap_tokens = 12288 if (top_unusable or verdict == "REDUCED" or a.max_tokens <= 12288) else 14336
    rep.update({"buckets": buckets, "repeat_losses": [round(x, 4) for x in losses], "grad_norms": [round(x, 3) for x in gns], "tok_s": round(tok_s, 1),
                "excluded_buckets": excluded, "max_tokens": a.max_tokens, "peak_gb_at_12k": peak12, "oom_at_16k": buckets[3]["oom"], "thrash_at_16k": top_unusable and not buckets[3]["oom"],
                "cap_tokens": cap_tokens, "export": erep, "heldout_eval": evaluate(pm, held, a.chunk, dev) if held else None, "verdict": verdict, "reasons": reasons})
    (Path(out) / "probe_report.json").write_text(json.dumps(rep, indent=1, default=str))
    log(event="probe_verdict", verdict=verdict, reasons=reasons, tok_s=rep["tok_s"], peak_gb_at_12k=peak12, oom_at_16k=buckets[3]["oom"], thrash_at_16k=rep["thrash_at_16k"], cap_tokens=cap_tokens)
    return 0 if verdict != "FALLBACK" else 3


def train(a, pm, info, items, held, log, out):
    dev = torch.device("cuda")
    params = lora_params(pm)
    opt = torch.optim.AdamW(params, lr=a.lr, betas=(0.9, 0.999), eps=1e-8, weight_decay=0.0)
    n, ga = len(items), a.grad_accum
    spe = math.ceil(n / ga)
    total = a.max_steps or a.epochs * spe
    cursor = Cursor(Path(out) / "cursor.json")
    start, best, evals = 0, None, []
    if a.resume and (Path(out) / "ckpt" / "adapter_model.safetensors").exists():
        load_ckpt(pm, opt, out)
        start, best, evals = cursor["step"], cursor["best"], cursor.state.get("evals", [])
        log(event="resumed", step=start, best=best)
    log(event="train_start", steps=total, steps_per_epoch=spe, start_step=start, **data_stats(items), lora=info)   # data_stats carries "sequences"
    oom_skipped, tps_hist, t_begin = 0, [], time.time()
    step = start
    while step < total:
        epoch = step // spe
        order = epoch_order(n, a.seed + epoch)
        i0 = (step % spe) * ga
        batch = [items[j] for j in order[i0:i0 + ga]]
        if held and step % a.eval_every == 0:
            ev = evaluate(pm, held, a.chunk, dev)
            evals.append(ev["nll_text"])
            log(event="eval", step=step, **ev, best=best)
            if best is None or ev["nll_text"] < best:
                best = ev["nll_text"]
                export_adapter(pm, Path(out) / "best", a.served_base)
                cursor.save(best=best, best_step=step)
            if len(evals) >= 3 and all(e > 1.05 * min(evals) for e in evals[-2:]):
                log(event="early_stop", step=step, evals=evals[-3:], min=min(evals))
                break
        lr = lr_at(step, total, a.lr)
        for g in opt.param_groups:
            g["lr"] = lr
        W = sum(it["wsum"] for it in batch) or 1.0
        torch.cuda.reset_peak_memory_stats(); torch.cuda.synchronize(); t = time.time()
        lsum, toks = 0.0, 0
        try:
            for it in batch:
                lsum += one_sequence_backward(pm, it, W, a.chunk, dev)
                toks += it["tokens"]
        except torch.cuda.OutOfMemoryError:
            opt.zero_grad(set_to_none=True); torch.cuda.empty_cache()
            oom_skipped += 1
            log(event="oom", step=step, tokens=[it["tokens"] for it in batch], oom_skipped=oom_skipped)
            if oom_skipped > 5:
                log(event="abort", reason="more than 5 OOM steps: lower --max-tokens")
                save_ckpt(pm, opt, out, cursor)
                return 4
            step += 1
            continue
        gn = float(torch.nn.utils.clip_grad_norm_(params, a.clip))
        opt.step(); opt.zero_grad(set_to_none=True); torch.cuda.synchronize()
        dt = time.time() - t
        tps = toks / dt
        tps_hist.append(tps)
        med = sorted(tps_hist)[len(tps_hist) // 2]
        step += 1
        log(event="step", step=step, of=total, loss=round(lsum, 4), lr=lr, grad_norm=round(gn, 3), tokens=toks, tok_s=round(tps), seconds=round(dt, 1),
            alarm_tok_s_halved=bool(len(tps_hist) > 10 and tps < 0.5 * med), elapsed_h=round((time.time() - t_begin) / 3600, 2), **mem())
        cursor.save(step=step, seq=i0 + ga, epoch=epoch, evals=evals)
        if step % a.save_every == 0:
            save_ckpt(pm, opt, out, cursor)
    save_ckpt(pm, opt, out, cursor)
    final = evaluate(pm, held, a.chunk, dev) if held else None
    out_dir, erep = export_adapter(pm, Path(out) / "adapter_bf16", a.served_base)
    summary = {"steps": step, "best_nll_text": best, "final_eval": final, "oom_skipped": oom_skipped, "elapsed_h": round((time.time() - t_begin) / 3600, 2),
               "export": erep, "best_dir": str(Path(out) / "best") if best is not None else None, "final_dir": str(out_dir)}
    (Path(out) / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    log(event="done", **summary)
    return 0


def main(argv=None):
    a = parse(argv)
    out = Path(a.out or "runs/qlora")
    out.mkdir(parents=True, exist_ok=True)
    log = Log(out / "train_log.jsonl")
    tok_path = a.tokenizer_json or (Path(a.base) / "tokenizer.json" if a.base else None)
    if not tok_path or not Path(tok_path).exists():
        print(f"no tokenizer.json at {tok_path}: pass --tokenizer-json or a --base with one")
        return 2
    from tokenizers import Tokenizer
    tok = Tokenizer.from_file(str(tok_path))
    if a.dry_run:
        items = load_items(a.seqs, tok, a.max_tokens, a.limit)
        held = load_items(a.holdout, tok, a.max_tokens) if a.holdout and Path(a.holdout).exists() else []
        n, spe = len(items), math.ceil(len(items) / a.grad_accum)
        plan = {"data": data_stats(items), "holdout": len(held), "steps": a.max_steps or a.epochs * spe, "steps_per_epoch": spe,
                "probe_buckets": [[it["tokens"] for it in b] for b in probe_plan(items, per_bucket=5, buckets=BUCKETS)], "cuda": torch.cuda.is_available()}
        print(json.dumps(plan, indent=1))
        return 0
    smi_gb = nvidia_smi_used_gb()                      # before any CUDA context of ours exists (see the docstring)
    if not torch.cuda.is_available():
        print("needs a CUDA GPU (use --dry-run on a CPU box)")
        return 2
    if "expandable_segments" in os.environ.get("PYTORCH_CUDA_ALLOC_CONF", ""):
        print("PYTORCH_CUDA_ALLOC_CONF=expandable_segments breaks CUDA on this WSL2 box: unset it")
        return 2
    if a.attn == "sdpa":
        torch.backends.cuda.enable_math_sdp(False)       # an O(T^2) materialised attention would silently eat the memory budget
    torch.manual_seed(a.seed)
    free, total_mem = torch.cuda.mem_get_info()
    torch_gb = gb(total_mem - free)                     # includes this process's own CUDA context
    used_before = used_before_load_gb(smi_gb, torch_gb)
    log(event="start", args=vars(a), gpu=torch.cuda.get_device_name(0), total_gb=gb(total_mem), used_before_load_gb=used_before,
        used_nvidia_smi_gb=smi_gb, used_torch_incl_context_gb=torch_gb, torch=torch.__version__)
    if used_before > 1.0:
        log(event="refuse", reason=f"GPU not idle: {used_before} GB used before loading (nvidia-smi {smi_gb}; torch incl. own context {torch_gb})")
        return 3
    t0 = time.time()
    model = load_base_nf4(a.base, a.attn)
    configure_training(model)
    torch.cuda.synchronize()
    loaded = {"seconds": round(time.time() - t0, 1), **mem()}
    log(event="loaded", **loaded)
    pm, info = attach_lora(model, a.r, a.alpha, a.dropout, k_on_sliding=not a.no_k)
    pm.train()
    log(event="lora", **info, **mem())
    items = load_items(a.seqs, tok, a.max_tokens, a.limit)
    held = load_items(a.holdout, tok, a.max_tokens) if a.holdout and Path(a.holdout).exists() else []
    log(event="data", **data_stats(items), holdout=len(held))
    if not items:
        log(event="refuse", reason="no sequences")
        return 2
    return run_probe(a, pm, info, items, held, log, out, loaded) if a.probe else train(a, pm, info, items, held, log, out)


if __name__ == "__main__":
    sys.exit(main())
