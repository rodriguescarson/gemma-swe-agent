"""Shared repository index for locate.py / investigate.py. Stdlib only. Cached per task in /tmp/swe (keyed on HEAD + dirty state)."""
import ast, collections, hashlib, math, os, pickle, re, subprocess
SKIP = {".git", "node_modules", "__pycache__", "build", "dist", ".venv", "venv", ".tox", "site-packages"}
STOP = set("""fix fixes fixed fixing issue issues github com https http www the a an and or of to in on for with is are be this that it its as by
from at not no bug feature new add added adds adding support update updated use used using when should would could can may
pr pull request type changes change checklist run latest black tests test docs documentation docstrings other please make sure
thanks thank you see also closes close resolve resolves resolved version release x none true false self return returns""".split())
_split = lambda s: [t.lower() for t in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", s) if len(t) > 1]
def toks(s):
    out = []
    for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", s):
        out.append(w.lower()); out += _split(w)
    return out
def is_test(rel): return bool(re.search(r"(^|/)(tests?|testing)/|(^|/)test_[^/]*\.py$|_test\.py$|conftest\.py$", rel))
def clean_query(q):
    q = re.sub(r"<!--.*?-->", " ", q, flags=re.S)
    q = "\n".join(l for l in q.splitlines() if not re.match(r"\s*(- \[[ xX]\]|#+\s*(type of changes|checklist|description|related issues?)\b)", l, re.I))
    return re.sub(r"https?://\S+", " ", q)
def identifiers(q):
    """Exact code identifiers named in the issue: backticked, snake_case, CamelCase or dotted names."""
    q = clean_query(q); ids = re.findall(r"`([A-Za-z_][\w.]*)`", q)
    ids += [w for w in re.findall(r"[A-Za-z_][\w]*(?:\.[A-Za-z_]\w*)*", q) if ("_" in w.strip("_") or re.search(r"[a-z][A-Z]", w) or "." in w) and len(w) > 3]
    seen, out = set(), []
    for w in ids:
        w = w.strip(".")
        if w.lower() not in STOP and w not in seen: seen.add(w); out.append(w)
    return out[:12]
def _state(root):
    try:
        h = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
        d = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True).stdout
        return hashlib.sha1((h + d).encode()).hexdigest()[:16]
    except Exception: return "nogit"
def build(root):
    cache = f"/tmp/swe/index_{hashlib.sha1(root.encode()).hexdigest()[:8]}_{_state(root)}.pkl"
    if os.path.exists(cache):
        try: return pickle.load(open(cache, "rb"))
        except Exception: pass
    docs = []   # (rel, qualname, start, end, kind, istest, tokens)
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP and not d.startswith(".")]
        for fn in fns:
            if not fn.endswith(".py"): continue
            p = os.path.join(dp, fn); rel = os.path.relpath(p, root)
            try: src = open(p, encoding="utf-8", errors="ignore").read(); tree = ast.parse(src)
            except Exception: continue
            t = is_test(rel)
            def visit(node, prefix):
                for ch in ast.iter_child_nodes(node):
                    if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        qn = f"{prefix}.{ch.name}" if prefix else ch.name
                        kind = "class" if isinstance(ch, ast.ClassDef) else ("async def" if isinstance(ch, ast.AsyncFunctionDef) else "def")
                        body = ast.get_source_segment(src, ch) or ""
                        docs.append((rel, qn, ch.lineno, getattr(ch, "end_lineno", ch.lineno), kind, t, toks(qn) * 3 + toks(rel) + toks(body[:3000])))
                        visit(ch, qn)
            visit(tree, "")
            docs.append((rel, "<module>", 1, 1, "module", t, toks(rel) * 2 + toks(src[:2000])))
    idx = {"docs": docs, "df": collections.Counter(tk for d in docs for tk in set(d[6])), "avg": sum(len(d[6]) for d in docs) / max(1, len(docs))}
    try:
        os.makedirs("/tmp/swe", exist_ok=True); pickle.dump(idx, open(cache, "wb"))
    except Exception: pass
    return idx
def rank(idx, q, boost_files=()):
    q = clean_query(q); qc = collections.Counter(t for t in toks(q) if t not in STOP)
    qids = {w for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", q) if w.lower() not in STOP}
    N = len(idx["docs"]) or 1; df = idx["df"]; avg = idx["avg"]
    def score(d):
        tf = collections.Counter(d[6]); L = len(d[6]); s = 0.0
        for t, w in qc.items():
            if t in tf:
                s += w * math.log(1 + (N - df[t] + .5) / (df[t] + .5)) * tf[t] * 2.2 / (tf[t] + 1.2 * (.25 + .75 * L / avg))
        if d[1].split(".")[-1] in qids: s *= 2.5
        stem = os.path.splitext(os.path.basename(d[0]))[0].lstrip("_").lower()
        if stem in qc or stem.replace("_", "") in qc: s *= 1.8
        if d[0] in boost_files: s *= 1.6
        if d[5]: s *= 0.35
        return s
    by = collections.defaultdict(list)
    for d in idx["docs"]:
        s = score(d)
        if s > 0: by[d[0]].append((s, d))
    for v in by.values(): v.sort(key=lambda x: -x[0])
    return sorted(by.items(), key=lambda kv: -(kv[1][0][0] + 0.3 * (kv[1][1][0] if len(kv[1]) > 1 else 0)))
