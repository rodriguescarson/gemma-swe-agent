import os, sys
sys.dont_write_bytecode = True
_HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("SWE_PATH0", sys.path[0] if sys.path else "")
_STD = tuple({os.path.realpath(p) for p in (sys.base_prefix, sys.base_exec_prefix)})
sys.path[:] = [_HERE] + [p for p in sys.path if p and os.path.realpath(p).startswith(_STD) and "-packages" not in p]
for _n in [n for n, m in list(sys.modules.items()) if n.split(".")[0] in getattr(sys, "stdlib_module_names", ())
           and getattr(m, "__file__", None) and not os.path.realpath(m.__file__).startswith(_STD)]:
    del sys.modules[_n]
import _swe_common as C

# Rank the repository's files and symbols for a query (v9 BM25 over AST symbols, plus layout and related tests).
# Never reads stdin. Output 1,800 chars or fewer.
import re, json

USAGE = 'python3 /tmp/swe/locate.py "QUERY"'
FLAGS = {"query": "str", "text": "str"}
NAME = "locate"
MAX_QUERY = 4000          # v9 recall (21/28/34 of 40) was measured with the statement cut at 4,000 chars
SHOW_FILES = 6            # files listed with their symbols
RANK_FILES = 8            # ranked file lines in total (7-8 without symbols)
SYMS_PER_FILE = 3
FOOTER_RESERVE = 300      # footer line plus the longest hint (and a possible RESTORED prefix)
DOC_DIRS = frozenset(("docs", "docs_src", "examples", "benchmarks"))
NOT_PACKAGES = frozenset(("tests", "test", "testing", "docs", "doc", "docs_src", "examples", "benchmarks", "scripts",
                          "tools"))
TEST_DIRS = ("tests", "test", "testing")
NOTE_3RD = "NOTE: 3rd locate call; stop searching and use what you have."

STOP = frozenset("""fix fixes fixed fixing issue issues github com https http www the a an and or of to in on for with is are be
this that it its as by from at not no bug feature new add added adds adding support update updated use used using when
should would could can may pr pull request type changes change checklist run latest black tests test docs documentation
docstrings other please make sure thanks thank you see also closes close resolve resolves resolved version release x none
true false self return returns""".split())
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_TEMPLATE_LINE = re.compile(r"\s*(- \[[ xX]\]|#+\s*(type of changes|checklist|description|related issues?)\b)", re.I)
_URL = re.compile(r"https?://\S+")
_ISSUE_NO = re.compile(r"(?i)\bgh-\d+\b|#\d+\b")
_HEX = re.compile(r"\b(?=[0-9a-fA-F]*\d)(?=[0-9a-fA-F]*[a-fA-F])[0-9a-fA-F]{7,40}\b")
_QID = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_TESTPATH = re.compile(r"(^|/)(tests?|testing)/|(^|/)test_[^/]*\.py$|_test\.py$")

PROBE = r"""
import sys, json, importlib.util
r = {}
for p in sys.argv[1:]:
    try:
        s = importlib.util.find_spec(p)
        o = None
        if s is not None:
            o = s.origin if s.origin not in (None, "namespace", "built-in", "frozen") else None
            if o is None and s.submodule_search_locations:
                o = list(s.submodule_search_locations)[0]
        r[p] = o
    except BaseException as e:
        r[p] = "!" + type(e).__name__
print("\x1eORIGIN " + json.dumps(r))
"""


def clean_query(q):
    """v9 cleaning (HTML comments, PR checklists and template headings, URLs) plus issue numbers and hex hashes."""
    q = (q or "")[:MAX_QUERY]
    q = _COMMENT.sub(" ", q)
    q = "\n".join(l for l in q.splitlines() if not _TEMPLATE_LINE.match(l))
    q = _URL.sub(" ", q)
    q = _ISSUE_NO.sub(" ", q)
    return _HEX.sub(" ", q)


def query_terms(q):
    """(query tokens with repeats, identifiers of 3+ chars, title-line bigrams) of a cleaned query."""
    import _swe_index as I
    qt = [t for t in I.toks(q) if t not in STOP]
    qids = {w for w in _QID.findall(q) if w.lower() not in STOP}
    title = next((l for l in q.splitlines() if l.strip()), "")
    seq = [t for w in I._ID.findall(title) for t in I.split_word(w) if t not in STOP]
    return qt, qids, set(zip(seq, seq[1:]))


def is_test_path(rel):
    return bool(_TESTPATH.search(rel))


def rank(idx, q):
    """[(file_score, path, [(score, Sym)...])] best first; ties by path. v9 boosts plus docs x0.6 and bigrams x1.5."""
    import _swe_index as I
    qt, qids, bigrams = query_terms(q)
    if not qt:
        return []
    qc = set(qt)
    by = {}
    stems = {}
    bi_hit = {}
    for s, path, sym in idx.bm25(qt):
        name = sym[0].rsplit(".", 1)[-1]
        if name in qids:
            s *= 2.5
        st = stems.get(path)
        if st is None:
            stem = os.path.splitext(os.path.basename(path))[0].lstrip("_").lower()
            st = stems[path] = (1.8 if (stem in qc or stem.replace("_", "") in qc) else 1.0,
                                0.35 if is_test_path(path) else 1.0,
                                0.6 if DOC_DIRS.intersection(path.split("/")[:-1]) else 1.0)
        s *= st[0]
        s *= st[1]
        s *= st[2]
        if bigrams and sym[1] != "module":
            hit = bi_hit.get(name)
            if hit is None:
                sp = I.split_word(name)
                hit = bi_hit[name] = bool(bigrams.intersection(zip(sp, sp[1:])))
            if hit:
                s *= 1.5
        if s > 0:
            by.setdefault(path, []).append((s, sym))
    out = []
    for path, lst in by.items():
        lst.sort(key=lambda x: (-x[0], x[1][2], x[1][0]))
        fs = lst[0][0] + 0.3 * (lst[1][0] if len(lst) > 1 else 0)
        out.append((fs, path, lst))
    out.sort(key=lambda x: (-x[0], x[1]))
    return out


# ---------------------------------------------------------------- layout and import origin
def layout(files):
    """(packages, layout 'src'|'flat', test dirs) from the indexed file list."""
    flat, src = [], []
    for rel in files:
        parts = rel.split("/")
        if parts[-1] != "__init__.py":
            continue
        if len(parts) == 2 and parts[0] not in NOT_PACKAGES:
            flat.append(parts[0])
        elif len(parts) == 3 and parts[0] == "src" and parts[1] not in NOT_PACKAGES:
            src.append(parts[1])
    tdirs = set()
    for rel in files:
        parts = rel.split("/")
        for i, p in enumerate(parts[:-1]):
            if p in TEST_DIRS:
                tdirs.add("/".join(parts[:i + 1]) + "/")
                break
    tests = sorted(tdirs, key=lambda d: (d.count("/"), d))[:3]
    if src:
        return sorted(set(src)), "src", tests
    return sorted(set(flat)), "flat", tests


def _classify(ws, pkg, origin):
    """(display, dir-under-ws or None) for one probed package."""
    if origin is None:
        return "(NOT IMPORTABLE with the test PYTHONPATH)", None
    if origin.startswith("!"):
        return "(import check failed: %s)" % origin[1:], None
    p = os.path.realpath(origin)
    pkgdir = os.path.dirname(p) if os.path.basename(p).startswith("__init__.") else p
    w = os.path.realpath(ws)
    if pkgdir == w or pkgdir.startswith(w + os.sep):
        d = os.path.relpath(os.path.dirname(pkgdir), w)
        return "(workspace)", ("" if d == "." else d.replace(os.sep, "/"))
    return "(OUTSIDE WORKSPACE: %s; tests import that copy, not your edit)" % C.unrewrite(pkgdir), None


def probe_origins(ws, pkgs, state):
    """Display strings per package; probes once per package set and caches the result in the state."""
    cached = state.get("origin_probe") or {}
    if cached.get("pkgs") == pkgs and isinstance(cached.get("show"), dict):
        return cached["show"], None
    show, origin = {}, {}
    try:
        env = C.grader_env(ws, "cur")
    except Exception:
        env = dict(os.environ)
    rc, out = C.sh([_py(env), "-s", "-c", PROBE] + pkgs, C.real_budget(C.ORIGIN_PROBE), cwd=ws, env=env)
    m = re.search(r"\x1eORIGIN (\{.*\})", out or "")
    res = None
    if m:
        try:
            res = json.loads(m.group(1))
        except ValueError:
            res = None
    for p in pkgs:
        if res is None:
            show[p] = "(origin unknown: import probe %s)" % ("timed out" if rc is None else "failed")
            origin[p] = None
        else:
            show[p], origin[p] = _classify(ws, p, res.get(p))
    return show, {"pkgs": pkgs, "show": show, "origin": origin}


def layout_line(ws, idx, state_view, updates):
    pkgs, lay, tests = layout(idx.files)
    parts = []
    if pkgs:
        shown = pkgs[:4]
        show, probe = probe_origins(ws, shown, state_view)
        if probe is not None:
            updates["origin_probe"] = probe
        txt = ", ".join("%s %s" % (p, show.get(p, "")) for p in shown)
        if len(pkgs) > 4:
            txt += ", +%d more" % (len(pkgs) - 4)
        parts.append("packages " + txt)
    else:
        parts.append("packages none")
    parts.append("tests " + (" ".join(tests) if tests else "none"))
    parts.append("layout " + lay)
    return "LAYOUT: " + " | ".join(parts)


# ---------------------------------------------------------------- related tests
def _collectable(rel):
    b = rel.rsplit("/", 1)[-1]
    return b.endswith(".py") and b != "conftest.py" and (b.startswith("test_") or b.endswith("_test.py"))


def related_tests(ws, idx, ranked):
    cands = [f for f in idx.files if _collectable(f)]
    if not cands:
        return "RELATED TESTS: none"
    order = {}
    for i, (_fs, path, _l) in enumerate(ranked[:SHOW_FILES]):
        if is_test_path(path):
            continue
        stem = os.path.splitext(os.path.basename(path))[0].lstrip("_")
        for c in cands:
            b = c.rsplit("/", 1)[-1][:-3]
            if b in ("test_" + stem, "test__" + stem, stem + "_test") and c not in order:
                order[c] = i
    names = []
    for _fs, path, lst in ranked[:3]:
        if is_test_path(path):
            continue
        for _s, sym in lst:
            if sym[1] == "module":
                continue
            n = sym[0].rsplit(".", 1)[-1]
            if len(n) >= 4 and not (n.startswith("__") and n.endswith("__")) and n not in names:
                names.append(n)
            if len(names) >= 8:
                break
    counts = {}
    if names:
        argv = ["git", "-c", "core.quotepath=off", "grep", "-c", "-z", "-w", "-I", "-F"]
        for n in names:
            argv += ["-e", n]
        argv += ["--", ":(glob)**/test_*.py", ":(glob)**/*_test.py"]
        rc, out = C.sh(argv, C.real_budget(5), cwd=ws)
        for ln in (out or "").splitlines():
            if "\0" in ln:
                p, _, c = ln.partition("\0")
                if c.strip().isdigit() and _collectable(p):
                    counts[p] = int(c.strip())
    pool = set(order) | set(counts)
    if not pool:
        return "RELATED TESTS: none found (no test file names the top symbols)"
    best = sorted(pool, key=lambda p: (order.get(p, 99), -counts.get(p, 0), p))[:3]
    return "RELATED TESTS: " + " ".join(best)


# ---------------------------------------------------------------- output
def render(idx, ranked, budget, spans=None):
    """The ranked list as lines within `budget` chars. spans (a list) receives (path, start, end) of every symbol
    line kept, so main() can record them as views (their numbers are current)."""
    lines = []
    for i, (fs, path, lst) in enumerate(ranked[:RANK_FILES]):
        tag = " [test]" if is_test_path(path) else ""
        lines.append(("%d. %s%s  score=%.1f" % (i + 1, path, tag, fs), i, None, None))
        if i < SHOW_FILES:
            k = 0
            for _s, sym in lst:
                if sym[1] == "module":
                    continue
                lines.append(("     %s %s  L%d-%d" % (sym[1], sym[0][:100], sym[2], sym[3]), i, k,
                              (path, sym[2], sym[3])))
                k += 1
                if k >= SYMS_PER_FILE:
                    break
    # drop symbols of lower-ranked files, then whole lower-ranked files, until the list fits the budget
    def size(ls):
        return sum(len(x[0]) + 1 for x in ls)
    for depth in (2, 1, 0):
        if size(lines) <= budget:
            break
        lines = [x for x in lines if x[2] is None or x[2] < depth or x[1] < 2]
    while size(lines) > budget and lines:
        last = max(x[1] for x in lines)
        if last == 0:
            lines = [(x[0][:200], x[1], x[2], x[3]) for x in lines][:4]
            break
        lines = [x for x in lines if x[1] != last]
    if spans is not None:
        spans.extend(x[3] for x in lines if x[3])
    return [x[0] for x in lines]


def get_query(argv):
    opts = C.parse_args(argv, FLAGS, ["query*"])
    q = opts.get("text") or opts.get("query") or " ".join(opts.get("_") or [])
    return str(q or "").strip()


def _py(env):
    import shutil
    return "python3" if shutil.which("python3", path=(env or os.environ).get("PATH")) else (sys.executable or "python3")


def main():
    C.bootstrap()
    q = get_query(sys.argv[1:])
    if not q:
        C.print_usage(NAME, USAGE)
        return
    import _swe_index as I
    ws = C.ws()
    idx = I.build(ws)
    cleaned = clean_query(q)
    ranked = rank(idx, cleaned)
    st = C.state_load()
    upd = {}
    lay = layout_line(ws, idx, st, upd)
    rel_tests = related_tests(ws, idx, ranked) if ranked else "RELATED TESTS: none"
    n_calls = int(st.get("locate_calls") or 0) + 1
    first = "LOCATE: %d symbols in %d files" % (idx.n_symbols(), len(idx.files))
    tail = [rel_tests]
    if idx.partial:
        tail.append("NOTE: partial index (parse deadline); unparsed files were ranked by their path only.")
    if not ranked:
        tail.insert(0, 'no matches; try other identifiers, or python3 /tmp/swe/grep.py "regex"')
    if n_calls >= 3:
        tail.append(NOTE_3RD)
    cap = C.CAPS["locate"]
    budget = cap - FOOTER_RESERVE - len(first) - 1 - sum(len(x) + 1 for x in tail) - min(len(lay), 400) - 1
    spans = []
    body = [lay[:400]] + render(idx, ranked, max(200, budget), spans)
    t_now = round(float(C.clock()), 1)

    def _upd(s):
        s["locate_calls"] = int(s.get("locate_calls") or 0) + 1
        vv = s.get("views") if isinstance(s.get("views"), dict) else {}
        for path, a, b in spans:           # the printed Lstart-end numbers are current: views for edit.py's STALE guard
            lst = vv.get(path)
            if not isinstance(lst, list):
                lst = vv[path] = []
            for n in sorted({int(a), int(b)}):   # only the two numbers shown, never the lines between them
                lst.append([n, n, t_now, "d"])
            del lst[:-C.VIEWS_KEPT]
        s["views"] = vv
        if "origin_probe" in upd:
            s["origin_probe"] = upd["origin_probe"]
            o = dict(s.get("origin") or {})
            o.update(upd["origin_probe"]["origin"])
            s["origin"] = o
        return s
    C.state_update(_upd)
    top = ranked[0][1] if ranked else ""
    C.journal({"h": "locate", "ok": bool(ranked), "files": min(len(ranked), RANK_FILES), "top": top,
               "msg": "%d files (top %s)" % (min(len(ranked), RANK_FILES), top or "none")})
    C.emit(NAME, first, "\n".join(body), cap, tail=tail)


if __name__ == "__main__":
    C.safe_main(NAME, main)
