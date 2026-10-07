"""Rank source files and symbols (incl. async defs, methods, classes) for a query. Stdlib only.
Usage: run_skill_script(skill_name="swe_tools", file_path="locate.py", args={"query": "<identifiers, error text, keywords>"})"""
import ast, math, os, re, sys, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ws import ws
import _budget                                      # v6p-b: the locator's counted share (docs/v4h/GATE.md addendum 10)
_refusal, _footer = _budget.enter(ws())
if _refusal:
    print(_refusal); sys.exit(0)
if _footer:
    print(_footer)                                  # first line: the harness truncates long tool output
args = sys.argv[1:]; q = ""
if "--query" in args: q = args[args.index("--query") + 1]
elif args: q = " ".join(a for a in args if a != "--")
if not q: q = sys.stdin.read() if not sys.stdin.isatty() else ""
ROOT = ws(); SKIP = {".git", "node_modules", "__pycache__", "build", "dist", ".venv", "venv", ".tox", "site-packages"}
split = lambda s: [t.lower() for t in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", s) if len(t) > 1]
def toks(s):
    out = []
    for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", s):
        out.append(w.lower()); out += split(w)
    return out
# strip PR-template boilerplate, links and checklists
q = re.sub(r"<!--.*?-->", " ", q, flags=re.S)
q = "\n".join(l for l in q.splitlines() if not re.match(r"\s*(- \[[ xX]\]|#+\s*(type of changes|checklist|description|related issues?)\b)", l, re.I))
q = re.sub(r"https?://\S+", " ", q)
STOP = set("""fix fixes fixed fixing issue issues github com https http www the a an and or of to in on for with is are be this that it its as by
from at not no bug feature new add added adds adding support update updated use used using when should would could can may
pr pull request type changes change checklist run latest black tests test docs documentation docstrings other please make sure
thanks thank you see also closes close resolve resolves resolved version release x none true false self return returns""".split())
qt = [t for t in toks(q) if t not in STOP]; qids = {w for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", q) if w.lower() not in STOP}
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
    stem = os.path.splitext(os.path.basename(d[0]))[0].lstrip("_").lower()
    if stem in qc or stem.replace("_", "") in qc: s *= 1.8
    if d[5]: s *= 0.35
    return s
scored = sorted(((bm25(d), d) for d in docs), key=lambda x: -x[0])
by = collections.defaultdict(list)
for s, d in scored:
    if s > 0: by[d[0]].append((s, d))
fs = sorted(by.items(), key=lambda kv: -(kv[1][0][0] + 0.3 * (kv[1][1][0] if len(kv[1]) > 1 else 0)))
files = collections.OrderedDict(fs)
print(f"workspace={ROOT} symbols={N}")
for i, (f, lst) in enumerate(list(files.items())[:8]):
    tag = " [test]" if lst[0][1][5] else ""
    print(f"{i+1}. {f}{tag}  score={lst[0][0]:.1f}")
    for s, d in lst[:4]:
        if d[1] != "<module>": print(f"     {d[4]} {d[1]}  L{d[2]}-{d[3]}")
if not files: print("no matches; try other identifiers or `git grep -n <word>`")
