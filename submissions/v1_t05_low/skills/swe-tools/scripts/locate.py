"""Rank source files and symbols (incl. async defs, methods, classes) for a query. Stdlib only.
Usage: run_skill_script(skill_name="swe_tools", file_path="locate.py", args={"query": "<identifiers, error text, keywords>"})"""
import ast, math, os, re, sys, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ws import ws
args = sys.argv[1:]; q = ""
if "--query" in args: q = args[args.index("--query") + 1]
elif args: q = " ".join(a for a in args if a != "--")
ROOT = ws(); SKIP = {".git", "node_modules", "__pycache__", "build", "dist", ".venv", "venv", ".tox", "site-packages"}
split = lambda s: [t.lower() for t in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", s) if len(t) > 1]
def toks(s):
    out = []
    for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", s):
        out.append(w.lower()); out += split(w)
    return out
qt = toks(q); qids = {w for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", q)}
docs = []  # (path, qualname, line, kind, tokens)
for dp, dns, fns in os.walk(ROOT):
    dns[:] = [d for d in dns if d not in SKIP and not d.startswith(".")]
    for fn in fns:
        if not fn.endswith(".py"): continue
        p = os.path.join(dp, fn); rel = os.path.relpath(p, ROOT)
        try: src = open(p, encoding="utf-8", errors="ignore").read(); tree = ast.parse(src)
        except Exception: continue
        istest = bool(re.search(r"(^|/)(tests?|testing)/|(^|/)test_[^/]*\.py$|_test\.py$", rel))
        def visit(node, prefix):
            for ch in ast.iter_child_nodes(node):
                if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    qn = f"{prefix}.{ch.name}" if prefix else ch.name
                    kind = "class" if isinstance(ch, ast.ClassDef) else ("async def" if isinstance(ch, ast.AsyncFunctionDef) else "def")
                    body = ast.get_source_segment(src, ch) or ""
                    docs.append((rel, qn, ch.lineno, getattr(ch, "end_lineno", ch.lineno), kind, istest,
                                 toks(qn) * 3 + toks(rel) + toks(body[:3000])))
                    visit(ch, qn)
        visit(tree, "")
        docs.append((rel, "<module>", 1, 1, "module", istest, toks(rel) * 2 + toks(src[:2000])))
N = len(docs) or 1; avg = sum(len(d[6]) for d in docs) / N
df = collections.Counter(t for d in docs for t in set(d[6]))
qc = collections.Counter(qt)
def bm25(d):
    tf = collections.Counter(d[6]); L = len(d[6]); s = 0.0
    for t, w in qc.items():
        if t in tf:
            idf = math.log(1 + (N - df[t] + .5) / (df[t] + .5))
            s += w * idf * tf[t] * 2.2 / (tf[t] + 1.2 * (.25 + .75 * L / avg))
    name = d[1].split(".")[-1]
    if name in qids: s *= 2.5
    if d[5]: s *= 0.35
    return s
scored = sorted(((bm25(d), d) for d in docs), key=lambda x: -x[0])
files = collections.OrderedDict()
for s, d in scored:
    if s <= 0: break
    files.setdefault(d[0], []).append((s, d))
    if len(files) >= 8 and all(len(v) >= 1 for v in files.values()): pass
print(f"workspace={ROOT} symbols={N}")
for i, (f, lst) in enumerate(list(files.items())[:8]):
    tag = " [test]" if lst[0][1][5] else ""
    print(f"{i+1}. {f}{tag}  score={lst[0][0]:.1f}")
    for s, d in lst[:4]:
        if d[1] != "<module>": print(f"     {d[4]} {d[1]}  L{d[2]}-{d[3]}")
if not files: print("no matches; try other identifiers or `git grep -n <word>`")
