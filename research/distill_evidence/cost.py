# Per-task-run teacher cost through the v10.1 pipeline, from the Gemma-token profile of pair1 p1_v10 (73 traced tasks).
UNC, CAC, OUT = 27618, 249239, 3384   # mean uncached prompt, cached prompt, completion tokens per task (Gemma tokenizer)
# (name, in $/M, out $/M, cache-read $/M or None, cache-write multiplier on uncached input, tokenizer factor vs Gemma, licence note)
T = [
 ("google/gemma-4-31b-it (self, bf16)",   0.09, 0.34, 0.05,  1.0, 1.00, "own model: allowed 09-28 (checkpoint differs)"),
 ("openai/gpt-oss-120b",                  0.037,0.17, None,  1.0, 1.10, "Apache-2.0"),
 ("qwen/qwen3-coder-next",                0.12, 0.80, 0.07,  1.0, 1.10, "Apache-2.0"),
 ("qwen/qwen3-coder (480B-A35B)",         0.30, 1.00, 0.10,  1.0, 1.10, "Apache-2.0"),
 ("deepseek/deepseek-v4.1-flash",         0.30, 1.20, 0.006, 1.0, 1.10, "MIT"),
 ("deepseek/deepseek-v4-pro",             0.924,1.849,0.077, 1.0, 1.10, "MIT"),
 ("z-ai/glm-5.3",                         1.40, 4.40, 0.26,  1.0, 1.10, "licence 'other' on HF"),
 ("moonshotai/kimi-k2.7-code",            0.656,3.30, 0.18,  1.0, 1.10, "modified MIT ('other')"),
 ("google/gemini-3.8-flash",              0.75, 3.75, 0.075, 1.0, 1.10, "API terms: no competing models"),
 ("openai/gpt-5.6-sol",                   2.00, 10.0, 0.20,  1.0, 1.10, "API terms"),
 ("anthropic/claude-sonnet-5.5",          2.00, 10.0, 0.20,  1.25,1.25, "API terms: no competing models"),
 ("anthropic/claude-opus-5.5",            4.00, 20.0, 0.20,  1.25,1.25, "API terms: no competing models"),
]
def cost(pin,pout,pcr,cw,f,m_out=1.0,cache=True):
    if cache and pcr is not None:
        c = UNC*pin*cw + CAC*pcr
    else:
        c = (UNC+CAC)*pin
    return f*(c + OUT*m_out*pout)/1e6
print(f"{'teacher':38s} {'$/run cached':>12s} {'$/run out x2':>12s} {'$/run no-cache':>14s}  {'$/1k verified @50% (range 35-60%)':>34s}")
for n,pin,pout,pcr,cw,f,lic in T:
    a=cost(pin,pout,pcr,cw,f); b=cost(pin,pout,pcr,cw,f,2.0); c=cost(pin,pout,pcr,cw,f,1.0,False)
    per1k=lambda x,s: x/s*1000
    print(f"{n:38s} {a:12.4f} {b:12.4f} {c:14.4f}  ${per1k(a,0.5):8.0f} (${per1k(a,0.6):.0f}-${per1k(b,0.35):.0f})   {lic}")
