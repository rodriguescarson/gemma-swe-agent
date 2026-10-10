"""The CPU-testable core of train/qlora_train.py (plan ~/.claude/plans/nifty-sleeping-liskov.md, "Training step design"):
token-level supervision from stitched char spans, the chunked soft-capped cross-entropy over supervised positions only (the
262,144-token vocabulary makes full logits 21-42 GB at 8k-16k tokens), the warmup+cosine schedule, the probe plan and the
resumable cursor. No peft / bitsandbytes imports here; the GPU driver adds them."""
import json
import math
import random
from pathlib import Path

import torch
import torch.nn.functional as F
from torch.utils.checkpoint import checkpoint


def token_targets(text, spans, tok, max_tokens=None, with_index=False):
    """Tokenise a stitched sequence and project its weighted char spans onto tokens.

    -> ids [T], positions [N] (indices i whose NEXT token is supervised), targets [N] (= ids[i+1]), weights [N] (the span's weight)
       [, span_index [N] (which span the supervised token belongs to, in the sorted order) when with_index]
    A token is supervised when it begins inside a span with weight > 0; the loss sits at the previous position (next-token
    prediction). The weighted rule of train/spans.py arrives here as the 3rd span element."""
    enc = tok.encode(text, add_special_tokens=False)
    ids, offs = enc.ids, enc.offsets
    if max_tokens is not None and len(ids) > max_tokens:
        ids, offs = ids[:max_tokens], offs[:max_tokens]
    w_tok, s_tok = [0.0] * len(ids), [-1] * len(ids)
    k = 0
    spans = sorted(spans)
    for j, (a, b) in enumerate(offs):
        while k < len(spans) and spans[k][1] <= a:
            k += 1
        if k < len(spans) and spans[k][0] <= a < spans[k][1]:
            w_tok[j], s_tok[j] = float(spans[k][2]), k
    positions = [j - 1 for j in range(1, len(ids)) if w_tok[j] > 0]
    targets = [ids[j + 1] for j in positions]
    weights = [w_tok[j + 1] for j in positions]
    if with_index:
        return ids, positions, targets, weights, [s_tok[j + 1] for j in positions]
    return ids, positions, targets, weights


def chunked_weighted_ce(hidden, lm_head_weight, targets, weights, softcap=30.0, chunk=1024, use_checkpoint=True, denom=None):
    """hidden [N, H] (the gathered rows, grad-carrying), lm_head_weight [V, H], targets [N], weights [N] -> scalar loss = the
    weight-normalised token mean (sum w * nll / sum w), or sum w * nll / denom when denom is given (a step's micro-batches share
    one denominator = the step's total weight, so the step is a token mean over all its sequences). Logits for one chunk live at
    a time; softcap applied by hand (the model's forward does it after lm_head: logits = softcap * tanh(logits / softcap))."""
    def part(h, t, w):
        logits = F.linear(h, lm_head_weight.to(h.dtype)).float()
        if softcap:
            logits = torch.tanh(logits / softcap) * softcap
        nll = F.cross_entropy(logits, t, reduction="none")
        return (nll * w).sum()
    total = hidden.new_zeros((), dtype=torch.float32)
    for s in range(0, hidden.shape[0], chunk):
        h, t, w = hidden[s:s + chunk], targets[s:s + chunk], weights[s:s + chunk]
        total = total + (checkpoint(part, h, t, w, use_reentrant=False) if use_checkpoint and hidden.requires_grad else part(h, t, w))
    return total / (weights.sum().clamp_min(1e-6) if denom is None else denom)


def per_token_nll(hidden, lm_head_weight, targets, softcap=30.0, chunk=1024):
    """[N] next-token NLLs at the gathered rows, no grad (held-out evaluation)."""
    out = []
    with torch.no_grad():
        for s in range(0, hidden.shape[0], chunk):
            logits = F.linear(hidden[s:s + chunk], lm_head_weight.to(hidden.dtype)).float()
            if softcap:
                logits = torch.tanh(logits / softcap) * softcap
            out.append(F.cross_entropy(logits, targets[s:s + chunk], reduction="none"))
    return torch.cat(out) if out else hidden.new_zeros((0,), dtype=torch.float32)


def full_weighted_ce(hidden, lm_head_weight, targets, weights, softcap=30.0):
    """The same loss without chunking (tests)."""
    logits = F.linear(hidden, lm_head_weight).float()
    if softcap:
        logits = torch.tanh(logits / softcap) * softcap
    nll = F.cross_entropy(logits, targets, reduction="none")
    return (nll * weights).sum() / weights.sum().clamp_min(1e-6)


def lr_at(step, total, peak, warmup_frac=0.03, floor_frac=0.10):
    """Linear warmup over warmup_frac of the steps, then cosine from peak to floor_frac * peak."""
    warm = max(1, int(round(warmup_frac * total)))
    if step < warm:
        return peak * (step + 1) / warm
    p = min(1.0, (step - warm) / max(1, total - warm))
    return peak * (floor_frac + (1 - floor_frac) * 0.5 * (1 + math.cos(math.pi * p)))


def probe_plan(seqs, per_bucket=5, buckets=((0, 5000), (5000, 9000), (9000, 13000), (13000, 10 ** 9))):
    """The feasibility probe's sequences: per_bucket per token bucket, longest first within a bucket (an OOM shows up early)."""
    out = []
    for lo, hi in buckets:
        c = sorted((s for s in seqs if lo <= s["meta"]["tokens"] < hi), key=lambda s: -s["meta"]["tokens"])
        out.append(c[:per_bucket])
    return out


def epoch_order(n, seed=0):
    idx = list(range(n))
    random.Random(seed).shuffle(idx)
    return idx


class Cursor:
    """Where the run is: the step and the sequence index inside the epoch; written next to the checkpoint for resume."""

    def __init__(self, path):
        self.path = Path(path)
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {"step": 0, "seq": 0, "epoch": 0, "best": None}

    def save(self, **kw):
        self.state.update(kw)
        self.path.write_text(json.dumps(self.state))

    def __getitem__(self, k):
        return self.state[k]


def probe_verdict(peak_gb_at_12k, tok_s, loss_first, loss_last, nan=False, max_grad=0.0):
    """The pre-registered thresholds of docs/a6000/TRAIN_LOCAL.md -> ('FULL'|'REDUCED'|'FALLBACK', reasons)."""
    reasons = []
    if nan:
        reasons.append("NaN loss")
    if peak_gb_at_12k is not None and peak_gb_at_12k > 44.0:
        reasons.append(f"peak {peak_gb_at_12k:.1f} GB > 44 at 12k")
    if loss_first and loss_last is not None and loss_last > 0.7 * loss_first:
        reasons.append(f"loss fell {100 * (1 - loss_last / loss_first):.0f}% < 30% over the repeated steps")
    if max_grad > 100:
        reasons.append(f"grad norm {max_grad:.0f} > 100")
    if reasons:
        return "FALLBACK", reasons
    if tok_s >= 150:
        return "FULL", [f"{tok_s:.0f} tok/s >= 150"]
    if tok_s >= 100:
        return "REDUCED", [f"{tok_s:.0f} tok/s in [100, 150): cap 12,288 and <= 6 segments per task-stage"]
    return "FALLBACK", [f"{tok_s:.0f} tok/s < 100"]
