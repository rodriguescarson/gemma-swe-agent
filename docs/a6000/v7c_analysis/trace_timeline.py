import json, sys
d = json.load(open(sys.argv[1])); steps = d["steps"]
def t(x, n):
    x = x if isinstance(x, str) else json.dumps(x, default=str)
    x = x.replace("\n", "|").replace("\n", "|")
    return x if len(x) <= n else x[:n] + "..."
rows = []
for s in steps:
    if s["step_id"] == 1: continue
    ex = s.get("extra") or {}
    tcs = s.get("tool_calls") or []
    if not tcs:
        rows.append((s["step_id"], ex.get("author", "?"), ex.get("elapsed_s", 0), "TEXT", t(s.get("message", ""), 300), "")); continue
    for c in tcs:
        e = c.get("extra") or {}
        obs = (s.get("observation") or {}).get("content", "")
        rows.append((s["step_id"], e.get("author", "?"), e.get("elapsed_s", 0), c["function_name"] + " " + t(c.get("arguments"), 230), t(obs, 230), ""))
# collapse identical consecutive (call, obs)
out = []; i = 0
while i < len(rows):
    j = i
    while j + 1 < len(rows) and rows[j + 1][3] == rows[i][3] and rows[j + 1][4] == rows[i][4]: j += 1
    n = j - i + 1
    r = rows[i]
    out.append(f"#{r[0]}{'-%d' % rows[j][0] if n > 1 else ''} [{r[1]} @{r[2]:.0f}s]{' x%d' % n if n > 1 else ''} {r[3]}\n      -> {r[4]}")
    i = j + 1
print("\n".join(out))
