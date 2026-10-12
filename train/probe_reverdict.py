#!/usr/bin/env python3
"""Re-derive a feasibility probe's verdict from its probe_report.json under the current rules (train/qlora_lib.probe_throughput +
probe_verdict, docs/a6000/TRAIN_LOCAL.md). 2026-10-12: the box's probe ran on code that averaged tok/s over the thrashing
13-16k bucket (four steps at 6 tok/s, 47.8 GB); the rule changed while it ran (TRAIN_LOCAL "Probe rule added 2026-10-12"), so
its report carries the old verdict and this prints the new one beside it. Every raw measurement is taken from the report;
nothing is re-run. The same forward2k checks as run_probe apply (|logit| <= softcap + 0.5, base NLL in [0.3, 1.5]).

    python train/probe_reverdict.py ~/g4/runs/train_think1/probe/probe_report.json [--write] [--softcap 30]
--write saves probe_reverdict.json next to the report. Exit 0 for FULL / REDUCED, 3 for FALLBACK."""
import argparse, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from train.qlora_lib import THRASH_TOK_S, bucket_unusable, probe_throughput, probe_verdict  # noqa: E402


def reverdict(rep, softcap=30.0, max_tokens=None):
    buckets = rep["buckets"]
    tok_s, excluded = probe_throughput(buckets)
    top_unusable = bucket_unusable(buckets[3]) if len(buckets) > 3 else False
    b12 = buckets[2] if len(buckets) > 2 else {"oom": False, "steps": []}
    peak12 = 99.0 if b12.get("oom") else max((s["peak_reserved_gb"] for s in b12["steps"] if "peak_reserved_gb" in s), default=None)
    losses, gns = rep.get("repeat_losses", []), rep.get("grad_norms", [])
    nan = any(x != x for x in losses)
    loss_first = sum(losses[:2]) / 2 if len(losses) >= 2 else (losses[0] if losses else None)
    loss_last = sum(losses[-2:]) / 2 if len(losses) >= 2 else None
    verdict, reasons = probe_verdict(peak12, tok_s, loss_first, loss_last, nan=nan, max_grad=max(gns, default=0.0))
    f2k = rep.get("forward2k") or {}
    if f2k.get("max_abs_logit") is not None and f2k["max_abs_logit"] > softcap + 0.5:
        verdict, reasons = "FALLBACK", [f"max |logit| {f2k['max_abs_logit']} > softcap {softcap}"] + reasons
    if f2k.get("base_nll") is not None and not (0.3 <= f2k["base_nll"] <= 1.5):
        verdict, reasons = "FALLBACK", [f"base NLL {f2k['base_nll']:.3f} outside [0.3, 1.5]: the base is not the served model"] + reasons
    if peak12 is None:
        reasons.append("no sequence in the 9k-13k bucket: the 12k memory check did not run")
    if excluded:
        reasons.append(f"buckets {excluded} OOM'd or thrashed (< {THRASH_TOK_S:.0f} tok/s): excluded from tok/s; the run caps at 12,288")
    mt = max_tokens if max_tokens is not None else rep.get("max_tokens", 16384)
    cap_tokens = 12288 if (top_unusable or verdict == "REDUCED" or mt <= 12288) else 14336
    return {"old_verdict": rep.get("verdict"), "old_reasons": rep.get("reasons"), "old_tok_s": rep.get("tok_s"),
            "verdict": verdict, "reasons": reasons, "tok_s": round(tok_s, 1), "excluded_buckets": excluded, "thrash_at_16k": top_unusable and not buckets[3].get("oom"),
            "peak_gb_at_12k": peak12, "cap_tokens": cap_tokens, "loss_first": round(loss_first, 4) if loss_first is not None else None,
            "loss_last": round(loss_last, 4) if loss_last is not None else None, "max_grad": max(gns, default=0.0),
            "bucket_peaks": [{"range": b["range"], "peak_gb": max((s.get("peak_reserved_gb", 0) for s in b["steps"]), default=None),
                              "tok_s": [s.get("tok_s") for s in b["steps"]]} for b in buckets]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("report"); ap.add_argument("--write", action="store_true"); ap.add_argument("--softcap", type=float, default=30.0)
    ap.add_argument("--max-tokens", type=int, default=None, help="the probe's own --max-tokens when the report does not carry it (default: the report's, else 16384)")
    a = ap.parse_args(argv)
    rep = json.load(open(a.report))
    out = reverdict(rep, a.softcap, a.max_tokens)
    print(json.dumps(out, indent=1))
    if a.write:
        Path(a.report).with_name("probe_reverdict.json").write_text(json.dumps(out, indent=1))
    return 0 if out["verdict"] != "FALLBACK" else 3


if __name__ == "__main__":
    sys.exit(main())
