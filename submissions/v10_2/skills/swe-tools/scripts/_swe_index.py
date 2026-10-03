"""AST symbol index of the workspace's Python files, with a marshal cache and BM25 scoring (library, stdlib only).

Pinned API (SPEC 4.3), used by locate.py, grep.py, view.py and _swe_gate.py:
  build(ws, deadline_s=LOCATE_PARSE) -> Index
  Index.files                          indexed .py paths (relative to ws, "/"-separated, sorted)
  Index.partial                        True when the parse deadline expired (the rest is scored by path tokens only)
  Index.symbols(path) -> [Sym]         Sym = (qualname, kind, start, end, params); kind in {"def", "async def", "class"}
  Index.defs_named(name) -> [(path, Sym)]
  Index.enclosing(path, line) -> Sym | None
  Index.span(path, qualname) -> (start, end) | None
  Index.outline(path) -> [Sym]
  Index.module_assigns(path) -> set
  Index.bm25(query_tokens) -> [(score, path, Sym)]   raw v9 BM25 (locate.py applies the boosts)
Extras: Index.find(path, name) -> [Sym], Index.class_attrs(path, qualname) -> set, toks(text), split_word(word).

Ties are broken by path, then line.  `start` includes decorators; `params` is a tuple of parameter names, with "*name"
for *args and "**name" for **kwargs.  Line numbers equal git's (bytes split on \\n).

Caches (per baseline, under $SWE): index_<b12>.marshal (symbols, keyed per file by (mtime_ns, size)) and
index_<b12>.bm25.marshal (global inverted index; docs of changed files are marked dead and re-appended).
"""
import os, sys, re, ast, math, time, marshal, subprocess, signal, warnings
from array import array

try:
    from collections import _count_elements
except ImportError:  # pragma: no cover - non-CPython
    def _count_elements(mapping, iterable):
        for x in iterable:
            mapping[x] = mapping.get(x, 0) + 1

IDX_VERSION = 6
TF_BITS = 16                        # a posting is one int: doc << 16 | min(tf, 65535)
TF_MASK = (1 << TF_BITS) - 1
MAX_BYTES = 1000000                 # files over 1 MB are skipped
BODY_CHARS = 3000                   # v9: first 3,000 chars of a symbol's source
MODULE_CHARS = 2000                 # v9: first 2,000 chars of the module
SKIP_DIRS = frozenset(("site-packages", "node_modules", ".tox", "build", "dist", "_vendor", "vendor",
                       "__pycache__", "venv"))
MODULE_SYM = ("<module>", "module", 1, 1, ())
_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_BLOCKS = ("body", "orelse", "finalbody", "handlers", "cases")
_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SPLIT = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")
_MEMO = {}
_intern = sys.intern



class _Quiet(object):
    """Silence SyntaxWarning/DeprecationWarning (invalid escapes in repo code) while parsing, then restore filters."""

    def __enter__(self):
        self._c = warnings.catch_warnings()
        self._c.__enter__()
        warnings.simplefilter("ignore")
        return self

    def __exit__(self, *exc):
        return self._c.__exit__(*exc)


# ---------------------------------------------------------------- tokens (v9 rules, memoised)
def split_word(w):
    """v9 camel/snake split of one identifier: lower-cased parts of 2+ chars."""
    return [t.lower() for t in _SPLIT.findall(w) if len(t) > 1]


def _word(w):
    r = _MEMO.get(w)
    if r is None:
        r = tuple(_intern(t) for t in [w.lower()] + split_word(w))
        _MEMO[w] = r
    return r


def toks(s):
    """v9 toks(): every identifier lower-cased, followed by its camel/snake parts."""
    out = []
    for w in _ID.findall(s):
        out.extend(_word(w))
    return out


def _add_tf(s, tf, mult=1):
    """Add the v9 token counts of s (times mult) into tf; return the number of tokens added."""
    wc = {}
    _count_elements(wc, _ID.findall(s))
    n = 0
    for w, c in wc.items():
        ts = _word(w)
        c *= mult
        n += c * len(ts)
        for t in ts:
            tf[t] = tf.get(t, 0) + c
    return n


# ---------------------------------------------------------------- small utilities
def _run_bytes(argv, cwd, timeout):
    """Run a child in its own session with stdin closed; kill the group on timeout. Returns (rc | None, stdout)."""
    try:
        p = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        return None, b""
    try:
        out, _ = p.communicate(timeout=timeout)
        return p.returncode, out
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            out, _ = p.communicate(timeout=2)
        except Exception:
            out = b""
        return None, out


def _skip_rel(rel):
    for d in rel.split("/")[:-1]:
        if d in SKIP_DIRS or d.startswith("."):
            return True
    return False


def list_py_files(ws):
    """Tracked .py files (git ls-files -z), else an os.walk; vendored and hidden dirs skipped; sorted."""
    rc, out = _run_bytes(["git", "-c", "core.quotepath=off", "ls-files", "-z", "--", "*.py"], ws, 10)
    if rc == 0:
        rels = sorted({os.fsdecode(b) for b in out.split(b"\0") if b})
    else:
        rels = []
        for dp, dns, fns in os.walk(ws):
            dns[:] = sorted(d for d in dns if d not in SKIP_DIRS and not d.startswith("."))
            base = os.path.relpath(dp, ws)
            for fn in fns:
                if fn.endswith(".py"):
                    rels.append(fn if base == "." else (base + "/" + fn).replace(os.sep, "/"))
        rels.sort()
    return [r for r in rels if r.endswith(".py") and not _skip_rel(r)]


def _stat_key(path):
    try:
        st = os.stat(path)
    except (OSError, ValueError):
        return None
    if not (st.st_mode & 0o170000 == 0o100000):  # regular files only (a symlink loop or a dir fails here)
        return None
    return (st.st_mtime_ns, st.st_size)


def _read_text(path):
    """Bytes -> text the way v9 read it: UTF-8 (errors ignored), universal newlines; a BOM is dropped."""
    with open(path, "rb") as f:
        data = f.read()
    text = data.decode("utf-8", "ignore")
    if "\r" in text:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    if text.startswith("﻿"):
        text = text[1:]
    return text


def _params(a):
    names = [x.arg for x in getattr(a, "posonlyargs", [])] + [x.arg for x in a.args]
    if a.vararg is not None:
        names.append("*" + a.vararg.arg)
    names += [x.arg for x in a.kwonlyargs]
    if a.kwarg is not None:
        names.append("**" + a.kwarg.arg)
    return tuple(names)


def _target_names(t, out):
    if isinstance(t, ast.Name):
        out.add(t.id)
    elif isinstance(t, (ast.Tuple, ast.List)):
        for e in t.elts:
            _target_names(e, out)
    elif isinstance(t, ast.Starred):
        _target_names(t.value, out)


def _assigns(stmts, out):
    """Names assigned in a statement list, looking into if/try/with/for blocks but not into defs or classes."""
    stack = list(stmts)
    while stack:
        s = stack.pop()
        if isinstance(s, ast.Assign):
            for t in s.targets:
                _target_names(t, out)
        elif isinstance(s, (ast.AnnAssign, ast.AugAssign)):
            _target_names(s.target, out)
        elif isinstance(s, _DEFS):
            continue
        else:
            for f in _BLOCKS:
                v = getattr(s, f, None)
                if v:
                    for x in v:
                        if isinstance(x, ast.AST):
                            stack.append(x)
    return out


def _walk_defs(tree):
    """All def/class nodes in source order: [(qualname, kind, start, end, params, v9_visible, node)].
    v9_visible: reachable through def/class bodies only (the symbols v9's BM25 indexed)."""
    out = []

    def visit(node, prefix, vis):
        for f in _BLOCKS:
            v = getattr(node, f, None)
            if not v:
                continue
            for ch in v:
                if isinstance(ch, _DEFS):
                    qn = prefix + "." + ch.name if prefix else ch.name
                    if isinstance(ch, ast.ClassDef):
                        kind, params = "class", ()
                    else:
                        kind = "async def" if isinstance(ch, ast.AsyncFunctionDef) else "def"
                        params = _params(ch.args)
                    start = ch.lineno
                    for d in ch.decorator_list:
                        start = min(start, d.lineno)
                    end = getattr(ch, "end_lineno", None) or ch.lineno
                    out.append((qn, kind, start, end, params, vis and f == "body", ch))
                    visit(ch, qn, vis and f == "body")
                elif isinstance(ch, ast.AST):
                    visit(ch, prefix, False)

    visit(tree, "", True)
    return out


def _line_starts(text):
    starts = [0]
    pos = 0
    for ln in text.split("\n"):
        pos += len(ln) + 1
        starts.append(pos)
    return starts


def _char_off(text, starts, lineno, col, ascii_text):
    base = starts[lineno - 1]
    if ascii_text:
        return base + col
    line = text[base:starts[lineno]]
    if line.isascii():
        return base + col
    return base + len(line.encode("utf-8")[:col].decode("utf-8", "ignore"))


def parse_file(path, rel, want_terms=True):
    """Parse one file. Returns (status, syms, assigns, docs); status 1 parsed, 0 unreadable/SyntaxError.
    docs (when want_terms) = [(sym_index or -1, length, tf_dict)] in v9's document definition."""
    with _Quiet():
        return _parse_file(path, rel, want_terms)


def _parse_file(path, rel, want_terms):
    try:
        text = _read_text(path)
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError, MemoryError, OSError, UnicodeError, TypeError):
        return 0, [], (), []
    try:
        defs = _walk_defs(tree)
    except RecursionError:
        return 0, [], (), []
    syms = [(_intern(d[0]), d[1], d[2], d[3], d[4]) for d in defs]
    assigns = tuple(sorted(_assigns(tree.body, set())))
    docs = []
    if want_terms:
        rel_tf = {}
        rel_len = _add_tf(rel, rel_tf)
        starts = _line_starts(text)
        asc = text.isascii()
        for i, d in enumerate(defs):
            if not d[5]:
                continue
            node = d[6]
            try:
                a = _char_off(text, starts, node.lineno, node.col_offset, asc)
                b = _char_off(text, starts, node.end_lineno, node.end_col_offset, asc)
            except (IndexError, AttributeError, TypeError):
                a, b = 0, 0
            body = text[a:min(b, a + BODY_CHARS)]
            tf = dict(rel_tf)
            n = _add_tf(d[0], tf, 3) + rel_len + _add_tf(body, tf)
            docs.append((i, n, tf))
        tf = {}
        n = _add_tf(rel, tf, 2) + _add_tf(text[:MODULE_CHARS], tf)
        docs.append((-1, n, tf))
    return 1, syms, assigns, docs


def _path_doc(rel):
    tf = {}
    n = _add_tf(rel, tf, 2)
    return [(-1, n, tf)]


def _load_marshal(path):
    try:
        with open(path, "rb") as f:
            obj = marshal.load(f)
        if isinstance(obj, dict) and obj.get("v") == IDX_VERSION:
            return obj
    except Exception:
        pass
    return None


def _save_marshal(path, obj):
    tmp = "%s.%d.tmp" % (path, os.getpid())
    try:
        with open(tmp, "wb") as f:
            marshal.dump(obj, f)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def default_cache_path():
    """$SWE/index_<baseline12>.marshal, or None when the core helpers are unavailable."""
    try:
        import _swe_common as C
        return os.path.join(C.swe_dir(), "index_%s.marshal" % (C.baseline() or "nobase")[:12])
    except Exception:
        return None


def default_deadline():
    """LOCATE_PARSE (15 s) clamped to the remaining task time."""
    try:
        import _swe_common as C
        return C.real_budget(C.LOCATE_PARSE)
    except Exception:
        return 15.0


# ---------------------------------------------------------------- the index
class Index(object):
    def __init__(self, ws):
        self.ws = os.path.abspath(ws)
        self.files = []
        self.partial = False
        self.n_parsed = 0
        self.parsed = []         # files (re)parsed by this build (cache misses)
        self.cache_path = None
        self._recs = {}          # rel -> [key, status, n_syms, syms | None, assigns | None, blob | None]
        self._partial_set = set()
        self._pkeys = {}         # rel -> stat key of files left unparsed by the deadline
        self._fresh = {}         # rel -> docs computed in this process
        self._by_name = None
        self._deadline = None

    # -- paths
    def rel(self, path):
        p = str(path)
        if os.path.isabs(p):
            try:
                r = os.path.relpath(os.path.realpath(p), os.path.realpath(self.ws))
            except ValueError:
                return p
            if not r.startswith(".."):
                return r.replace(os.sep, "/")
            return p
        p = p.replace(os.sep, "/")
        while p.startswith("./"):
            p = p[2:]
        return p

    def _abs(self, rel):
        return rel if os.path.isabs(rel) else os.path.join(self.ws, rel)

    def _rec(self, path):
        rel = self.rel(path)
        r = self._recs.get(rel)
        if r is None and rel not in self._partial_set:
            a = self._abs(rel)
            key = _stat_key(a)
            if key is None or key[1] > MAX_BYTES:
                return None
            status, syms, assigns, _ = parse_file(a, rel, want_terms=False)
            r = [key, status, len(syms), syms, assigns, None]
            self._recs[rel] = r
            self._by_name = None
        return self._full(r) if r else None

    @staticmethod
    def _full(r):
        """Decode a cached record's symbols on first use (the cache keeps them as one marshal blob per file)."""
        if r[3] is None:
            try:
                r[3], r[4] = marshal.loads(r[5]) if r[5] else ([], ())
            except Exception:
                r[3], r[4] = [], ()
        return r

    # -- symbol API
    def symbols(self, path):
        r = self._rec(path)
        return list(r[3]) if r else []

    def outline(self, path):
        return sorted(self.symbols(path), key=lambda s: (s[2], s[3], s[0]))

    def module_assigns(self, path):
        r = self._rec(path)
        return set(r[4]) if r else set()

    def n_symbols(self):
        return sum(r[2] for r in self._recs.values())

    def defs_named(self, name):
        if self._by_name is None:
            m = {}
            for rel in sorted(self._recs):
                for s in self._full(self._recs[rel])[3]:
                    m.setdefault(s[0].rsplit(".", 1)[-1], []).append((rel, s))
            for v in m.values():
                v.sort(key=lambda x: (x[0], x[1][2]))
            self._by_name = m
        return list(self._by_name.get(name, []))

    def enclosing(self, path, line):
        best = None
        for s in self.symbols(path):
            if s[2] <= line <= s[3]:
                if best is None or (s[2], -s[3]) > (best[2], -best[3]):
                    best = s
        return best

    def find(self, path, name):
        """Symbols matching name: exact qualname first, then qualnames ending in '.name', each in line order."""
        n = normalize_name(name)
        if not n:
            return []
        syms = self.outline(path)
        exact = [s for s in syms if s[0] == n]
        suffix = [s for s in syms if s[0] != n and s[0].endswith("." + n)]
        return exact + suffix

    def span(self, path, qualname):
        m = self.find(path, qualname)
        return (m[0][2], m[0][3]) if m else None

    def class_attrs(self, path, qualname):
        """Names a class defines: class-level assignments, defs, nested classes and self.x assignments in methods."""
        try:
            with _Quiet():
                tree = ast.parse(_read_text(self._abs(self.rel(path))))
        except Exception:
            return set()
        for d in _walk_defs(tree):
            if d[0] == qualname and d[1] == "class":
                node = d[6]
                out = _assigns(node.body, set())
                for ch in node.body:
                    if isinstance(ch, _DEFS):
                        out.add(ch.name)
                for sub in ast.walk(node):
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub.args.args:
                        me = sub.args.args[0].arg
                        for x in ast.walk(sub):
                            tgt = []
                            if isinstance(x, ast.Assign):
                                tgt = x.targets
                            elif isinstance(x, (ast.AnnAssign, ast.AugAssign)):
                                tgt = [x.target]
                            for t in tgt:
                                if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == me:
                                    out.add(t.attr)
                return out
        return set()

    # -- BM25 (v9 formula, unchanged)
    def _bm25_path(self):
        if not self.cache_path:
            return None
        base = self.cache_path[:-8] if self.cache_path.endswith(".marshal") else self.cache_path
        return base + ".bm25.marshal"

    def _wanted_status(self, rel):
        r = self._recs.get(rel)
        if r is None or rel in self._partial_set:
            return 2, self._pkeys.get(rel)
        return r[1], r[0]

    def _docs_for(self, rel, want, allow_parse):
        """(status, docs) for a file: 1 parsed, 0 unparsable (no docs), 2 path tokens only."""
        if rel in self._fresh:
            return want, self._fresh[rel]
        if want == 0:
            return 0, []
        if want == 2 or not allow_parse:
            return 2, _path_doc(rel)
        status, _syms, _a, docs = parse_file(self._abs(rel), rel, want_terms=True)
        return (1, docs) if status else (0, [])

    def _load_inv(self):
        """Bring the inverted index up to date with self.files (dead-marking replaced docs); save it when changed."""
        path = self._bm25_path()
        inv = _load_marshal(path) if path else None
        if inv is None:
            inv = {"v": IDX_VERSION, "files": {}, "names": [], "dfile": b"", "dsym": b"", "dlen": b"",
                   "dead": b"", "inv": {}, "nlive": 0, "totlen": 0}
        files = inv["files"]
        names = inv["names"]
        dfile = array("I"); dfile.frombytes(inv["dfile"])
        dsym = array("i"); dsym.frombytes(inv["dsym"])
        dlen = array("I"); dlen.frombytes(inv["dlen"])
        dead = bytearray(inv["dead"])
        postings = inv["inv"]
        st = [inv["nlive"], inv["totlen"]]
        name_id = None
        pend = {}
        changed = False

        def kill(rel):
            e = files.pop(rel, None)
            if e is not None:
                for d in range(e[3], e[3] + e[4]):
                    if not dead[d]:
                        dead[d] = 1
                        st[0] -= 1
                        st[1] -= dlen[d]

        want_set = set(self.files)
        for rel in [r for r in files if r not in want_set]:
            kill(rel)
            changed = True
        for rel in self.files:
            want, key = self._wanted_status(rel)
            e = files.get(rel)
            if e is not None and key is not None and (e[0], e[1]) == tuple(key):
                if e[2] == want or (want == 2 and e[2] == 1):
                    continue
            allow = self._deadline is None or time.monotonic() < self._deadline
            status, docs = self._docs_for(rel, want, allow)
            if status == 2 and want != 2:
                self.partial = True
            kill(rel)
            if name_id is None:
                name_id = {n: i for i, n in enumerate(names)}
            fid = name_id.get(rel)
            if fid is None:
                fid = len(names)
                names.append(rel)
                name_id[rel] = fid
            first = len(dlen)
            for si, n, tf in docs:
                d = len(dlen)
                dfile.append(fid)
                dsym.append(si)
                dlen.append(n)
                dead.append(0)
                st[0] += 1
                st[1] += n
                base = d << TF_BITS
                for t, c in tf.items():
                    try:
                        pend[t].append(base | (c if c < TF_MASK else TF_MASK))
                    except KeyError:
                        pend[t] = [base | (c if c < TF_MASK else TF_MASK)]
            k = key or (0, 0)
            files[rel] = (k[0], k[1], status, first, len(dlen) - first)
            changed = True
        for t, a in pend.items():
            b = postings.get(t)
            a = array("Q", a).tobytes()
            postings[t] = a if b is None else b + a
        nlive, totlen = st
        ndead = len(dlen) - nlive
        if ndead > 2000 and ndead > nlive:
            dfile, dsym, dlen, dead, postings, files = _compact(dfile, dsym, dlen, dead, postings, files)
            changed = True
        if changed:
            inv.update({"files": files, "names": names, "dfile": dfile.tobytes(), "dsym": dsym.tobytes(),
                        "dlen": dlen.tobytes(), "dead": bytes(dead), "inv": postings, "nlive": nlive,
                        "totlen": totlen})
            if path:
                _save_marshal(path, inv)
        return inv, dfile, dsym, dlen, dead

    def bm25(self, query_tokens):
        """[(score, path, Sym)] for every document with a positive v9 BM25 score, sorted by (-score, path, line)."""
        inv, dfile, dsym, dlen, dead = self._load_inv()
        n_all = len(dlen)
        N = inv["nlive"]
        if not N or not query_tokens:
            return []
        avg = inv["totlen"] / N
        qc = {}
        for t in query_tokens:
            qc[t] = qc.get(t, 0) + 1
        K = [1.2 * (.25 + .75 * L / avg) for L in dlen]
        sc = [0.0] * n_all
        postings = inv["inv"]
        has_dead = N != n_all
        log = math.log
        for t, w in qc.items():
            b = postings.get(t)
            if not b:
                continue
            arr = array("Q")
            arr.frombytes(b)
            if has_dead:
                arr = [v for v in arr if not dead[v >> TF_BITS]]
            df = len(arr)
            if not df:
                continue
            x = w * log(1 + (N - df + .5) / (df + .5))
            for v in arr:
                d = v >> TF_BITS
                tf = v & TF_MASK
                sc[d] += x * tf * 2.2 / (tf + K[d])
        names = inv["names"]
        out = []
        for d in range(n_all):
            s = sc[d]
            if s > 0 and not dead[d]:
                rel = names[dfile[d]]
                si = dsym[d]
                if si < 0:
                    sym = MODULE_SYM
                else:
                    r = self._recs.get(rel)
                    if r is None or si >= r[2]:
                        continue
                    sym = self._full(r)[3][si]
                out.append((s, rel, sym))
        out.sort(key=lambda x: (-x[0], x[1], x[2][2], x[2][0]))
        return out


def _compact(dfile, dsym, dlen, dead, postings, files):
    remap = {}
    nf, ns, nl = array("I"), array("i"), array("I")
    for d in range(len(dlen)):
        if not dead[d]:
            remap[d] = len(nl)
            nf.append(dfile[d]); ns.append(dsym[d]); nl.append(dlen[d])
    newp = {}
    for t, b in postings.items():
        arr = array("Q"); arr.frombytes(b)
        out = []
        for v in arr:
            nd = remap.get(v >> TF_BITS)
            if nd is not None:
                out.append((nd << TF_BITS) | (v & TF_MASK))
        if out:
            newp[t] = array("Q", out).tobytes()
    newfiles = {}
    for rel, e in files.items():
        firsts = [remap[d] for d in range(e[3], e[3] + e[4]) if d in remap]
        newfiles[rel] = (e[0], e[1], e[2], firsts[0] if firsts else len(nl), len(firsts))
    return nf, ns, nl, bytearray(len(nl)), newp, newfiles


def normalize_name(name):
    n = (name or "").strip().strip("`'\"")
    for pre in ("async def ", "def ", "class "):
        if n.startswith(pre):
            n = n[len(pre):].strip()
    n = n.split("(", 1)[0].strip().rstrip(":")
    return n.replace("::", ".")


def build(ws, deadline_s=None, cache_path=None, only=None, use_cache=True, want_terms=True):
    """Index the workspace (or just `only` paths). Files that cannot be parsed before the deadline are kept as
    path-only documents and Index.partial is set. Parsed files are cached per (mtime_ns, size)."""
    t0 = time.monotonic()
    if deadline_s is None:
        deadline_s = default_deadline()
    if cache_path is None and use_cache:
        cache_path = default_cache_path()
    idx = Index(ws)
    idx.cache_path = cache_path if use_cache else None
    idx._deadline = t0 + max(0.0, float(deadline_s))
    if only is not None:
        rels = []
        for p in only:
            r = idx.rel(p)
            if r not in rels:
                rels.append(r)
    else:
        rels = list_py_files(idx.ws)
    cache = _load_marshal(cache_path) if (use_cache and cache_path) else None
    crecs = cache["files"] if cache else {}
    todo = []
    for rel in rels:
        key = _stat_key(idx._abs(rel))
        if key is None or key[1] > MAX_BYTES:
            continue
        idx.files.append(rel)
        c = crecs.get(rel)
        if c is not None and (c[0], c[1]) == key:
            idx._recs[rel] = [key, c[2], c[3], None, None, c[4]]
        else:
            todo.append((rel, key))
    changed = False
    for rel, key in todo:
        if time.monotonic() >= idx._deadline:
            idx._partial_set.add(rel)
            idx._pkeys[rel] = key
            idx.partial = True
            continue
        status, syms, assigns, docs = parse_file(idx._abs(rel), rel, want_terms=want_terms)
        idx.parsed.append(rel)
        idx._recs[rel] = [key, status, len(syms), syms, assigns, None]
        if want_terms:
            idx._fresh[rel] = docs if status else []
        crecs[rel] = (key[0], key[1], status, len(syms), marshal.dumps((syms, assigns)))
        changed = True
    idx.n_parsed = sum(1 for r in idx._recs.values() if r[1])
    if only is None:
        listed = set(idx.files)
        for rel in [r for r in crecs if r not in listed]:
            del crecs[rel]
            changed = True
    if changed and use_cache and cache_path:
        _save_marshal(cache_path, {"v": IDX_VERSION, "files": crecs})
    return idx
