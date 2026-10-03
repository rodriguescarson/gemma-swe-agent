import json, re, os, sys, io, contextlib, collections
SP = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SP)
with contextlib.redirect_stdout(io.StringIO()):
    from analyze import case_p1, case_golden_L
patch = {}
for l in open("/Users/carson/Projects/gemma-swe-agent/data/tasks.jsonl"):
    r = json.loads(l); patch[r["instance_id"]] = r["patch"]
def changed_lines(p):
    """{file: set(old line numbers changed, plus insertion points)}; whitespace/comment/docstring-only lines excluded"""
    out = collections.defaultdict(set); f = None; old = None
    for ln in p.splitlines():
        if ln.startswith("--- a/"): f = ln[6:]; continue
        if ln.startswith("+++ "): continue
        m = re.match(r"@@ -(\d+)(?:,(\d+))? \+", ln)
        if m: old = int(m.group(1)); continue
        if f is None or old is None: continue
        body = ln[1:].strip()
        trivial = (not body) or body.startswith("#") or body.startswith('"""') or body.startswith("'''")
        if ln.startswith("-"):
            if not trivial: out[f].add(old)
            old += 1
        elif ln.startswith("+"):
            if not trivial: out[f].add(old)
        else:
            old += 1
    return out
def plan_ranges(reply):
    rs = []
    for m in re.finditer(r"([\w./-]+\.py):(\d+)(?:\s*-\s*(\d+))?", reply):
        a = int(m.group(2)); b = int(m.group(3) or a)
        rs.append((m.group(1).lstrip("./").replace("/workspace/", ""), a, b))
    return rs
res = collections.Counter(); per = []
for c in case_golden_L() + case_p1():
    ch = changed_lines(patch[c["task"]])
    ch = {f: s for f, s in ch.items() if s}
    rs = plan_ranges(c["reply"])
    if not ch:
        continue
    hit = any(f in ch and any(a - 5 <= x <= b + 5 for x in ch[f]) for f, a, b in rs)
    file_ok = any(f in ch for f, _, _ in rs)
    key = "no ranges" if not rs else ("lines overlap a gold change" if hit else ("right file, lines miss" if file_ok else "wrong file"))
    res[(c["src"], key)] += 1
    per.append((c["src"], c["task"], key))
for k, v in sorted(res.items()): print(k, v)
print([p for p in per if p[2] == "right file, lines miss"])
