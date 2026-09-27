"""LoRA SFT of Gemma 4 31B (QAT bf16 weights, same June lineage as the served W4A16 checkpoint) on harness-format trajectories.
Loss only on assistant turns (tool outputs, system and user masked). Model split across all visible GPUs (device_map=auto).
Usage: python sft.py --data file.jsonl --out /root/train_out/run1 [--limit 50] [--epochs 1] [--rank 16] [--max_len 16384]"""
import argparse, json, math, os, random, time
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
from peft import LoraConfig, get_peft_model

ap = argparse.ArgumentParser()
ap.add_argument("--data", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--base", default="google/gemma-4-31B-it-qat-q4_0-unquantized")
ap.add_argument("--limit", type=int, default=0); ap.add_argument("--epochs", type=float, default=1.0)
ap.add_argument("--rank", type=int, default=16); ap.add_argument("--alpha", type=int, default=32)
ap.add_argument("--lr", type=float, default=1e-4); ap.add_argument("--max_len", type=int, default=16384)
ap.add_argument("--grad_accum", type=int, default=8); ap.add_argument("--render_only", action="store_true")
a = ap.parse_args()
ARGS_MAX = a.max_len

tok = AutoTokenizer.from_pretrained(a.base)

def render(messages, tools, add_gen=False):
    return tok.apply_chat_template(messages, tools=tools, tokenize=False, add_generation_prompt=add_gen)

MODEL_OPEN, TURN_CLOSE, TR_OPEN, TR_CLOSE = "<|turn>model\n", "<turn|>", "<|tool_response>", "<tool_response|>"

def supervised_char_spans(text):
    """Char spans the model itself produced: inside each model turn, minus inline tool-response blocks.
    Gemma 4 merges consecutive assistant messages into one model turn and renders tool results inline, so
    prefix-diff masking fails; span masking on the final rendering does not."""
    spans, pos = [], 0
    while True:
        s = text.find(MODEL_OPEN, pos)
        if s < 0: break
        s += len(MODEL_OPEN)
        e = text.find(TURN_CLOSE, s)
        e = len(text) if e < 0 else e + len(TURN_CLOSE)       # train on the turn-close token too (the model must stop)
        cur = s
        while True:
            t = text.find(TR_OPEN, cur, e)
            if t < 0: spans.append((cur, e)); break
            spans.append((cur, t + len(TR_OPEN)))              # the model emits <|tool_response> to hand over, then waits
            c = text.find(TR_CLOSE, t, e)
            if c < 0: break
            cur = c + len(TR_CLOSE)
        pos = e
    return [(a, b) for a, b in spans if b > a]

def encode(ex):
    full = tok.apply_chat_template(ex["messages"], tools=ex["tools"], tokenize=False)
    enc = tok(full, add_special_tokens=False, return_offsets_mapping=True)
    ids, offs = enc["input_ids"], enc["offset_mapping"]
    spans = supervised_char_spans(full); labels = [-100] * len(ids); k = 0
    for j, (a, b) in enumerate(offs):
        while k < len(spans) and spans[k][1] <= a: k += 1
        if k < len(spans) and spans[k][0] <= a < spans[k][1]: labels[j] = ids[j]
    return ids[:ARGS_MAX], labels[:ARGS_MAX]

rows = [json.loads(l) for l in open(a.data)]
random.Random(0).shuffle(rows)
if a.limit: rows = rows[:a.limit]
data = [encode(r) for r in rows]
data = [(i, l) for i, l in data if any(x != -100 for x in l)]
n_tok = sum(len(i) for i, _ in data); n_sup = sum(sum(x != -100 for x in l) for _, l in data)
if not data:
    raise SystemExit(f"NO TRAINABLE EXAMPLES in {a.data} (limit={a.limit}); refusing to train")
print(f"examples {len(data)} tokens {n_tok} supervised {n_sup} ({n_sup / max(1, n_tok):.1%})", flush=True)
if a.render_only:
    i, l = data[0]; print(tok.decode([t for t, y in zip(i, l) if y != -100])[:1500]); raise SystemExit

model = AutoModelForCausalLM.from_pretrained(a.base, dtype=torch.bfloat16, device_map="auto", attn_implementation="sdpa")
model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
model.enable_input_require_grads()
cfg = LoraConfig(r=a.rank, lora_alpha=a.alpha, lora_dropout=0.0, bias="none", task_type="CAUSAL_LM",
                 target_modules=r".*language_model.*\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)$")
model = get_peft_model(model, cfg); model.print_trainable_parameters()
opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=a.lr, weight_decay=0.0)
steps = max(1, math.ceil(len(data) * a.epochs / a.grad_accum)); warm = max(1, int(0.03 * steps))
sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1, (s + 1) / warm) * 0.5 * (1 + math.cos(math.pi * min(1, s / steps))))
dev = next(model.parameters()).device; model.train(); t0 = time.time(); step = 0; order = list(range(len(data)))
for ep in range(math.ceil(a.epochs)):
    random.Random(ep).shuffle(order)
    for k, idx in enumerate(order):
        if ep + k / len(order) >= a.epochs: break
        ids, lab = data[idx]
        x = torch.tensor([ids], device=dev); y = torch.tensor([lab], device=dev)
        loss = model(input_ids=x, labels=y, mm_token_type_ids=torch.zeros_like(x)).loss / a.grad_accum
        loss.backward()
        if (k + 1) % a.grad_accum == 0:
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0); opt.step(); sched.step(); opt.zero_grad(); step += 1
            print(f"step {step}/{steps} loss {loss.item() * a.grad_accum:.4f} {time.time() - t0:.0f}s", flush=True)
os.makedirs(a.out, exist_ok=True); model.save_pretrained(a.out)
cfgj = json.load(open(os.path.join(a.out, "adapter_config.json"))); cfgj["base_model_name_or_path"] = "google/gemma-4-31b-it-qat-w4a16-ct"
json.dump(cfgj, open(os.path.join(a.out, "adapter_config.json"), "w"), indent=2)
print("SAVED", a.out, "in", round(time.time() - t0), "s", flush=True)
