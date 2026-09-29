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

# edit.py: the only edit channel (SPEC 4.7).
# Modes: SEARCH/REPLACE blocks (default; several blocks are all-or-nothing), --lines A-B, --lines A-B --delete,
# --insert-after N (0 = top), --create. Skill form: --file F --lines A-B --text "...".
# Bytes are split on b"\n" only (never str.splitlines) and decoded UTF-8 with surrogateescape, so line numbers equal
# git's and view.py's and untouched bytes round-trip exactly. Stdlib only; difflib and warnings are imported lazily
# and hashing uses C.sha1_hex (the builtin _sha1, not the OpenSSL-backed hashlib import).
import re

NAME = "edit"
USAGE = "python3 /tmp/swe/edit.py FILE [--lines A-B [--delete] | --insert-after N | --create] <<'EOF' ... EOF"
FLAGS = {"file": "str", "lines": "range", "delete": "bool", "insert-after": "int", "create": "bool", "text": "str",
         "start": "int", "end": "int", "after": "int"}
REGION_MAX = 30          # numbered lines shown after an edit
LINE_CUT = 150           # a displayed code line is cut to this many chars
RESERVE = 330            # chars kept free for the footer, a late-guard prefix, NEXT and hygiene lines
RECIPE = "python3 /tmp/swe/edit.py %s --lines %d-%d <<'EOF' ... EOF"
RETRY_WHY = ("NO MATCH", "AMBIGUOUS", "REVERTED", "NO CHANGE", "ALREADY TRIED")
# v10.1 (race 2, fastapi_14873 steps 36-37): a stray EOF line inside the block ends the heredoc early; the rest of the
# block then runs as shell commands ("=======: command not found") and only the SEARCH half reaches this script.
EARLY_EOF = ("ERROR: the edit ended early: no ======= line and no >>>>>>> REPLACE line arrived, so nothing changed. A "
             "line EOF inside the block ends the heredoc and the rest ran as shell commands. Put EOF once, as the last "
             "line, and send the whole edit again.")

_MS = re.compile(r"^[ \t]*<{5,9} ?(?:SEARCH|ORIGINAL|FIND|OLD)[ \t]*$", re.I)
_MD = re.compile(r"^[ \t]*={5,9}[ \t]*$")
_MR = re.compile(r"^[ \t]*>{5,9} ?(?:REPLACE|UPDATED|NEW)[ \t]*$", re.I)
_NUM = re.compile(r"^\s*\d+\| ?")
_ROW = re.compile(r"^\s*\d+\| ")
_FENCE = re.compile(r"^[ \t]*```[\w+.-]*[ \t]*$")
_ESC = re.compile("|".join(re.escape(e) for e in ('\\\\\\"', "\\\\n", "\\\\t", '\\"', "\\'", "\\n", "\\t", "\\\\")))
_ESC_TO = {'"': '"', "'": "'", "n": "\n", "t": "\t", "\\": "\\"}
_TOK = re.compile(r"[A-Za-z_]\w{2,}")
_COMMON = frozenset("self cls def class return None True False and not for with while elif else try except finally "
                    "import from raise pass yield lambda async await assert print len str int list dict set tuple "
                    "isinstance super kwargs args".split())


class Fail(Exception):
    """A non-OK outcome: first line, body lines, journal reason, hint range (a, b) for the loop breaker, whether it
    counts towards the three-failures rule, and extra journal fields."""

    def __init__(self, first, body=(), why="ERROR", hint=None, counts=True, ev=None):
        Exception.__init__(self, first)
        self.first, self.body, self.why, self.hint, self.counts, self.ev = first, list(body), why, hint, counts, ev or {}


# ----------------------------------------------------------------------------------------------------------- text model
def split_text(text):
    """-> (lines without their "\\n", final_nl). An empty file is ([], True) so inserted lines end with a newline."""
    if text == "":
        return [], True
    parts = text.split("\n")
    if text.endswith("\n"):
        parts.pop()
        return parts, True
    return parts, False


def join_text(lines, final_nl):
    return ("\n".join(lines) + ("\n" if final_nl else "")) if lines else ""


def decode(raw):
    bom = raw.startswith(b"\xef\xbb\xbf")
    return (raw[3:] if bom else raw).decode("utf-8", "surrogateescape"), bom


def encode(text, bom):
    return (b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8", "surrogateescape")


def crlf_dominant(lines, final_nl):
    m = len(lines) if final_nl else len(lines) - 1          # lines followed by "\n"
    if m <= 0:
        return False
    return 2 * sum(1 for s in lines[:m] if s.endswith("\r")) > m


def with_eol(new, crlf):
    return [s if (not crlf or s.endswith("\r")) else s + "\r" for s in new] if crlf else list(new)


def indent_of(s):
    return s[:len(s) - len(s.lstrip(" \t"))]


def unescape(s):
    """One decode of the double-JSON artefacts: \\\\\\" \\" \\' \\\\n \\n \\t \\\\ (harness_runtime 3.1)."""
    return _ESC.sub(lambda m: _ESC_TO[m.group(0)[-1]], s)


_J1 = re.compile(r'\\(["\\/bfnrt]|u[0-9a-fA-F]{4})')
_J1_TO = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
_QESC = re.compile(r'(?:\\\\)?\\(["\'])')


def json1(s):
    """Exactly one JSON string level decoded (json.loads('"' + s + '"') semantics; unknown escapes kept): a SEARCH
    copied from tool output one encoding level deep, where source text with real escapes ("Hello, \\"%s\\"") shows
    as "Hello, \\\\\\"%s\\\\\\"" and the two-level unescape() would drop the backslashes."""
    return _J1.sub(lambda m: chr(int(m.group(1)[1:], 16)) if m.group(1)[0] == "u" else _J1_TO[m.group(1)], s)


def unquote(s):
    """Only the quote artefacts decoded: \\\\\\" and \\" to ", \\\\\\' and \\' to '. Legitimate \\n, \\t and \\\\ escapes
    written natively in the same text stay as they are."""
    return _QESC.sub(lambda m: m.group(1), s)


def replace_choices(S, Sd, R, dec, region):
    """REPLACE texts to try, best first, as (text, label) when SEARCH S matched only after `dec` decoded it to Sd.
    REPLACE is decoded only for artefacts it demonstrably carries, because the prompts ask for raw code, so its own
    escapes are real ("\\n".join(parts), r"\\\\s+"):
      - \\n joins ("full"): the decoded SEARCH gained lines and REPLACE contains \\n;
      - quote escapes ("quotes"): REPLACE has more \\" (or \\') than the matched code;
      - otherwise REPLACE as written ("raw").
    The other forms follow as compile fallbacks (edit.py keeps the first that compiles, and journals which)."""
    raw, quotes, full = (R, "raw"), (unquote(R), "quotes"), (dec(R), "full")
    nl = Sd.count("\n") > S.count("\n") and "\\n" in R
    q = R.count('\\"') > region.count('\\"') or R.count("\\'") > region.count("\\'")
    order = (full, quotes, raw) if nl else (quotes, full, raw) if q else (raw, quotes, full)
    out = []
    for text, label in order:
        if all(text != o[0] for o in out):
            out.append((text, label))
    return out


def disp(s, cut=LINE_CUT):
    """Printable form of file text: lone surrogates shown as U+FFFD, \\r dropped, long lines cut."""
    s = s.rstrip("\r").encode("utf-8", "surrogateescape").decode("utf-8", "replace")
    return s if len(s) <= cut else s[:cut - 16] + " ... [line cut]"


def clean_body(lines):
    """Strip view.py number columns when every non-blank line carries one (SPEC 4.7 normalisation 3)."""
    lines = list(lines)
    nb = [s for s in lines if s.strip()]
    if nb and all(_NUM.match(s) for s in nb):
        lines = [_NUM.sub("", s, count=1) if s.strip() else "" for s in lines]
    return lines


def has_fence(lines):
    return bool(lines) and bool(_FENCE.match(lines[0]) or _FENCE.match(lines[-1]))


def strip_fences(lines):
    """Drop a ``` line at either edge (markdown wrapping). Only used as a fallback: fence lines also occur inside
    Python strings (markdown docstrings, test data), so text is always tried as written first."""
    a, b = 0, len(lines)
    if a < b and _FENCE.match(lines[a]):
        a += 1
    if b > a and _FENCE.match(lines[b - 1]):
        b -= 1
    return clean_body(lines[a:b])


def text_lines(text):
    """Heredoc / --text payload -> the new lines (the final newline is implied)."""
    if text == "":
        return []
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return clean_body(lines)


def has_markers(text):
    return any(_MS.match(s) for s in text.split("\n"))


def parse_blocks(text):
    """-> list of blocks; each block is a list of candidate (search_lines, replace_lines) splits, one per ======= line
    (same indentation as the SEARCH marker first). A block without >>>>>>> REPLACE ends at the next SEARCH or the end."""
    L = text.split("\n")
    n, i, blocks = len(L), 0, []
    while i < n:
        if not _MS.match(L[i]):
            i += 1
            continue
        k = i + 1
        while k < n and not _MR.match(L[k]) and not _MS.match(L[k]):
            k += 1
        closed = k < n and bool(_MR.match(L[k]))
        body = L[i + 1:k]
        if not closed:
            while body and not body[-1].strip():
                body.pop()
        divs = [d for d, s in enumerate(body) if _MD.match(s)]
        if not divs and not closed and not any(_MD.match(s) or _MR.match(s) for s in L):
            raise Fail(EARLY_EOF, why="EARLY EOF", counts=False)
        if not divs:
            raise Fail("ERROR: block %d has no ======= line between <<<<<<< SEARCH and >>>>>>> REPLACE; nothing changed."
                       % (len(blocks) + 1), counts=False)
        ind = indent_of(L[i])
        # the real divider leaves an RST underline (=======) inside docstrings on both sides: prefer symmetric splits
        divs.sort(key=lambda d: (indent_of(body[d]) != ind, abs(sum(1 for q in body[:d] if _MD.match(q)) -
                                                               sum(1 for q in body[d + 1:] if _MD.match(q)))))
        cands = [(clean_body(body[:d]), clean_body(body[d + 1:])) for d in divs]
        cands += [(strip_fences(S), strip_fences(R) if has_fence(R) else R) for S, R in cands if has_fence(S)]
        blocks.append(cands)
        i = k + 1 if closed else k
    return blocks


# -------------------------------------------------------------------------------------------------------------- matching
class Hit(object):
    """A located block. Line hits: a (0-based first line), k (line count), new (list of lines).
    Char hits (exact tier): a (char offset), k (char length), new (str), chars = alignment level 0..2.
    rdec: for a SEARCH matched only after decoding, which REPLACE form was used (replace_choices label), and nalt
    how many forms there were."""
    __slots__ = ("tier", "a", "k", "new", "chars", "rdec", "nalt")

    def __init__(self, tier, a, k, new, chars=None, rdec="", nalt=1):
        self.tier, self.a, self.k, self.new, self.chars, self.rdec, self.nalt = tier, a, k, new, chars, rdec, nalt


def _find_all(T, S, limit=2000):
    out, i = [], T.find(S)
    while i >= 0 and len(out) < limit:
        out.append(i)
        i = T.find(S, i + 1)
    return out


def _level(T, S, p):
    """2: whole lines; 1: only indentation precedes the match and it ends at a line end; 0: mid-line fragment.
    The end is checked in the file: a SEARCH whose last line is blank ends right after a newline, so the file's next
    line must be blank too (T[j] == "\n"), never just any line."""
    j = p + len(S)
    end = j >= len(T) or T[j] == "\n" or (T[j] == "\r" and (j + 1 >= len(T) or T[j + 1] == "\n"))
    if not end:
        return 0
    if p == 0 or T[p - 1] == "\n":
        return 2
    return 1 if not T[T.rfind("\n", 0, p) + 1:p].strip(" \t") else 0


def _line_hits(keys, skeys, limit=50):
    k, n = len(skeys), len(keys)
    first = next((x for x in range(k) if skeys[x]), None)
    if first is None or k > n:
        return []
    key0, hits, p, stop = skeys[first], [], first, n - (k - 1 - first)
    while len(hits) < limit:
        try:
            p = keys.index(key0, p, stop)
        except ValueError:
            break
        a = p - first
        if keys[a:a + k] == skeys:
            hits.append(a)
        p += 1
    return hits


def _ambiguous(T, starts, chars):
    lines = sorted({(T.count("\n", 0, s) + 1) if chars else s + 1 for s in starts})
    shown = ", ".join(str(v) for v in lines[:12]) + (", ..." if len(lines) > 12 else "")
    raise Fail("AMBIGUOUS: SEARCH matches at lines %s; add context lines or use --lines" % shown, why="AMBIGUOUS",
               hint=(lines[0], lines[0]))


def _exact(T, S, levels):
    by = {2: [], 1: [], 0: []}
    for p in _find_all(T, S):
        by[_level(T, S, p)].append(p)
    for lv in levels:
        if len(by[lv]) == 1:
            return by[lv][0], lv
        if len(by[lv]) > 1:
            _ambiguous(T, by[lv], True)
    return None


def reindent(lines, s_ind, f_ind):
    """Shift every non-blank line by (file indent - SEARCH indent); negative shifts dedent."""
    if s_ind == f_ind:
        return list(lines)
    out = []
    for s in lines:
        if not s.strip():
            out.append("")
        elif f_ind.startswith(s_ind):
            out.append(f_ind[len(s_ind):] + s)
        elif s_ind.startswith(f_ind):
            rm = s_ind[len(f_ind):]
            out.append(s[len(rm):] if s.startswith(rm) else s[min(len(indent_of(s)), len(rm)):])
        else:
            out.append(f_ind + s[len(s_ind):] if s.startswith(s_ind) else s)
    return out


def find_block(lines, final_nl, Sl, Rl, keys=None, rpick=0):
    """Tiers, first unique hit wins: exact (whole lines, then lost first-line indent), rstrip, unescape (SEARCH decoded
    two JSON levels, then one level), indent (strip compare, re-indent REPLACE), then exact mid-line fragments. When
    SEARCH needed decoding, REPLACE is the rpick-th of replace_choices() for the matched region (0: the best guess;
    edit.py retries 1 and 2 when the result does not compile). Returns a Hit or None; raises Fail(AMBIGUOUS) at the
    first tier with several hits."""
    T = join_text(lines, final_nl)
    S, R = "\n".join(Sl), "\n".join(Rl)
    variants = [(S, None, "")]
    for dec in (unescape, json1):
        Sd = dec(S)
        if all(Sd != v[0] for v in variants):
            variants.append((Sd, dec, "unescape"))

    def rep(s, dec, region):
        if dec is None:
            return R, "", 1
        ch = replace_choices(S, s, R, dec, region)
        text, label = ch[min(rpick, len(ch) - 1)]
        return text, label, len(ch)
    keys = keys or {}
    rk = keys.get("r") or [x.rstrip() for x in lines]
    for s, dec, tag in variants:
        if s:
            got = _exact(T, s, (2, 1))
            if got:
                r, rd, n = rep(s, dec, T[got[0]:got[0] + len(s)])
                return Hit(tag or "exact", got[0], len(s), r if Rl else None, chars=got[1], rdec=rd, nalt=n)
        sl = s.split("\n")
        hits = _line_hits(rk, [x.rstrip() for x in sl])
        if len(hits) > 1:
            _ambiguous(T, hits, False)
        if hits:
            r, rd, n = rep(s, dec, "\n".join(lines[hits[0]:hits[0] + len(sl)]))
            return Hit(tag or "rstrip", hits[0], len(sl), r.split("\n") if Rl else [], rdec=rd, nalt=n)
    sk = keys.get("s") or [x.strip() for x in lines]
    for s, dec, tag in variants:
        sl = s.split("\n")
        hits = _line_hits(sk, [x.strip() for x in sl])
        if len(hits) > 1:
            _ambiguous(T, hits, False)
        if hits:
            a = hits[0]
            f = next(x for x in range(len(sl)) if sl[x].strip())
            r, rd, n = rep(s, dec, "\n".join(lines[a:a + len(sl)]))
            new = reindent(r.split("\n") if Rl else [], indent_of(sl[f]), indent_of(lines[a + f]))
            return Hit((tag + "+indent") if tag else "indent", a, len(sl), new, rdec=rd, nalt=n)
    for s, dec, tag in variants:
        if s.strip() and s == s.strip("\n"):      # fragments only; blank edge lines go to the edge-trim retry
            got = _exact(T, s, (0,))
            if got:
                r, rd, n = rep(s, dec, T[got[0]:got[0] + len(s)])
                return Hit(tag or "exact", got[0], len(s), r if Rl else "", chars=0, rdec=rd, nalt=n)
    return None


def apply_hit(lines, final_nl, hit, crlf):
    """-> (new_lines, new_final_nl, A, B, A2, B2): 1-based old range A-B and new range A2-B2 (B2 < A2 when deleted)."""
    if hit.chars is None:
        a, k = hit.a, hit.k
        new = with_eol(hit.new, crlf)
        out = lines[:a] + new + lines[a + k:]
        fnl = final_nl or (a + k >= len(lines) and bool(out))
        return out, fnl, a + 1, a + k, a + 1, a + len(new)
    T = join_text(lines, final_nl)
    i, j, R = hit.a, hit.a + hit.k, hit.new or ""
    S = T[i:j]
    A = T.count("\n", 0, i) + 1
    B = A + (S[:-1] if S.endswith("\n") else S).count("\n")
    Rx = R.replace("\n", "\r\n") if crlf else R
    if hit.new is None and hit.chars >= 1 and not S.endswith("\n"):   # an empty REPLACE deletes whole lines
        i = T.rfind("\n", 0, i) + 1
        if T[j:j + 2] == "\r\n":
            j += 1
        if j < len(T) and T[j] == "\n":
            j += 1
        elif i > 0:
            i -= 1
    out, fnl = split_text(T[:i] + Rx + T[j:])
    return out, fnl, A, B, A, B + len(out) - len(lines)


# --------------------------------------------------------------------------------------------------- compile and checks
def compile_error(data, path):
    """None when data compiles, else (lineno, msg). In memory: no .pyc; SyntaxWarnings silenced."""
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            compile(data, path, "exec", dont_inherit=True)
            return None
        except SyntaxError as e:
            return (e.lineno or 0, e.msg or "invalid syntax")
        except Exception as e:  # ValueError (NUL bytes), RecursionError, MemoryError
            return (0, "%s: %s" % (type(e).__name__, e))


def numbered(lines, a, b, budget=None):
    """view.py format "%5d| line" for 1-based lines a..b. -> (rows, last line shown)."""
    rows, used, last = [], 0, a - 1
    for n in range(max(1, a), min(len(lines), b) + 1):
        row = "%5d| %s" % (n, disp(lines[n - 1]))
        if budget is not None and rows and used + len(row) + 1 > budget:
            break
        rows.append(row)
        used += len(row) + 1
        last = n
    return rows, last


def region(lines, spans, budget, rel):
    """Numbered region +-2 around each new span: at most REGION_MAX lines and `budget` chars.
    -> (rows, shown ranges) where shown ranges are what the model saw (recorded as views)."""
    n, wins = len(lines), []
    for a2, b2 in spans:
        lo, hi = max(1, a2 - 2), min(n, max(b2, a2 - 1) + 2)
        if hi >= lo:
            wins.append([lo, hi])
    wins.sort()
    merged = []
    for w in wins:
        if merged and w[0] <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], w[1])
        else:
            merged.append(w)
    rows, shown, left = [], [], REGION_MAX
    for lo, hi in merged:
        if left < 3 or budget < 80:
            rows.append("  ... (more: python3 /tmp/swe/view.py %s %d %d)" % (rel, lo, hi))
            break
        pieces = [(lo, hi)] if hi - lo + 1 <= left else [(lo, lo + left - 7), (hi - 4, hi)]
        for pi, (pa, pb) in enumerate(pieces):
            if pi:
                rows.append("  ... (lines %d-%d not shown)" % (pieces[0][1] + 1, pa - 1))
            got, last = numbered(lines, pa, pb, budget)
            rows.extend(got)
            budget -= sum(len(r) + 1 for r in got)
            left -= len(got)
            if got:
                shown.append((pa, last))
            if last < pb:
                rows.append("  ... (more: python3 /tmp/swe/view.py %s %d %d)" % (rel, last + 1, hi))
                return rows, shown
    return rows, shown


def closest(lines, Sl):
    """Closest same-length window: per-line prefilter (identical stripped line 3, distinctive shared tokens up to 2),
    the top 5 non-overlapping windows, then difflib ratio. -> (ratio, a, b) 1-based, or None."""
    n = len(lines)
    body = [s for s in Sl if s.strip()]
    if n == 0 or not body:
        return None
    k = min(max(1, len(Sl)), n)
    sset = {s.strip() for s in body}
    stok = {w for w in _TOK.findall("\n".join(body)) if w not in _COMMON}
    sc = []
    for s in lines:
        t = s.strip()
        if not t:
            sc.append(0)
        elif t in sset:
            sc.append(3)
        elif stok:
            c = 0
            for w in _TOK.findall(t):
                if w in stok:
                    c += 1
                    if c == 2:
                        break
            sc.append(c)
        else:
            sc.append(0)
    if not any(sc):
        return None
    pre = [0]
    for v in sc:
        pre.append(pre[-1] + v)
    order = sorted(range(n - k + 1), key=lambda a: (-(pre[a + k] - pre[a]), a))
    picked, gap = [], max(1, k // 2)
    for a in order:
        if pre[a + k] - pre[a] <= 0:
            break
        if all(abs(a - p) >= gap for p in picked):
            picked.append(a)
            if len(picked) == 5:
                break
    import difflib
    want = "\n".join(s.strip() for s in Sl)
    best = None
    for a in picked:
        r = difflib.SequenceMatcher(None, want, "\n".join(s.strip() for s in lines[a:a + k])).ratio()
        if best is None or r > best[0] + 1e-9:
            best = (r, a + 1, a + k)
    return best


def first_difference(lines, Sl, a):
    for d, s in enumerate(Sl):
        if a - 1 + d >= len(lines):
            break
        f = lines[a - 1 + d]
        if s.strip() != f.strip():
            return d, s, f
    return None


# ---------------------------------------------------------------------------------------------------------- stale guard
def norm_rel(p):
    p = os.path.normpath(str(p or "")).replace(os.sep, "/")
    while p.startswith("./"):
        p = p[2:]
    return p


def stale_check(rel, A, B, edits, views, strong=False):
    """B's delta rule. Evidence: the latest view whose range contains A (view.py ranges, edit displays, and the lines
    grep, locate and verify printed, which C.record_views stores as derived views with a 4th field "d"). Every later
    edit of this file with delta != 0 that ended above A shifts the range by its delta (d = their sum); a later edit
    overlapping A..B marks it `over`. Edits are applied in journal order. strong=True (--insert-after, where the new
    text cannot break a tie): a derived view is not enough evidence to redirect. -> None (fresh) or (A2, B2, d, over)."""
    tv, weak = None, False
    for key, vs in (views or {}).items():
        if norm_rel(key) != rel:
            continue
        for v in vs or ():
            try:
                va, vb, vt = int(v[0]), int(v[1]), float(v[2])
            except (TypeError, ValueError, IndexError):
                continue
            if va <= A <= vb and (tv is None or vt > tv or (vt == tv and weak)):
                tv, weak = vt, len(v) > 3 and v[3] == "d"
    if tv is None:
        return None
    A2, B2, d, over = A, B, 0, False
    for e in edits or ():
        try:
            if norm_rel(e.get("file")) != rel or not int(e.get("delta") or 0) or float(e.get("t", 0)) <= tv:
                continue
            s, en, dl = int(e["start"]), int(e["end"]), int(e["delta"])
        except (TypeError, ValueError, KeyError, AttributeError):
            continue
        if en < A2:
            A2, B2, d = A2 + dl, B2 + dl, d + dl
        elif s <= B2:
            over = True
    if d == 0 and not over:
        return None
    if strong and weak:
        return None
    return A2, B2, d, over


def content_shift(rel, A, B, new, lines, edits):
    """No view vouches for A (the numbers came from locate, grep or the plan): compare the new text with lines A-B and
    with A-B shifted by the last k line-shifting edits of this file (k = 1..10, newest last). -> (A2, B2, d) when a
    shifted range fits the text clearly better (similarity >= 0.5 and 0.25 above A-B), else None."""
    es = []
    for e in edits or ():
        try:
            if norm_rel(e.get("file")) == rel and int(e.get("delta") or 0):
                es.append((int(e["start"]), int(e["end"]), int(e["delta"])))
        except (TypeError, ValueError, KeyError, AttributeError):
            continue
    es = es[-10:]
    if not es:
        return None
    n, here, best = len(lines), _similarity(new, lines[A - 1:B]), None
    for k in range(1, len(es) + 1):
        a2, b2, d, ok = A, B, 0, True
        for s, en, dl in es[-k:]:
            if en < a2:
                a2, b2, d = a2 + dl, b2 + dl, d + dl
            elif s <= b2:
                ok = False
                break
        if not ok or d == 0 or a2 < 1 or b2 > n:
            continue
        sim = _similarity(new, lines[a2 - 1:b2])
        if best is None or sim > best[0]:
            best = (sim, a2, b2, d)
    if best and best[0] >= 0.5 and best[0] >= here + 0.25:
        return best[1], best[2], best[3]
    return None


# ----------------------------------------------------------------------------------------------------------- arguments
def parse_range(v):
    """'120-135', '120:135', '120,135', '120..135', '120 135', 'L120-L135', (120, 135) or 120 -> (A, B)."""
    if isinstance(v, (tuple, list)) and len(v) == 2:
        return int(v[0]), int(v[1])
    if isinstance(v, int):
        return v, v
    m = re.match(r"^\s*L?(\d+)\s*(?:(?:-|:|,|\.\.|\s)\s*L?(\d+))?\s*$", str(v))
    if not m:
        raise Fail("ERROR: --lines wants A-B, for example --lines 120-135 (got %r)." % (str(v)[:40],), counts=False)
    a = int(m.group(1))
    return a, int(m.group(2)) if m.group(2) else a


def _flag(opts, name):
    v = opts.get(name)
    if v is None:
        return False
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y", "on", "")
    return bool(v)


# ------------------------------------------------------------------------------------------------------------ workspace
def resolve(ws, fname):
    """-> (abs real path, rel posix path); REFUSED when outside the workspace."""
    ws_real = os.path.realpath(ws)
    f = str(fname).strip().strip("'\"")
    cands = [f] if os.path.isabs(f) else [os.path.join(ws_real, f)]
    if not os.path.isabs(f) and os.path.realpath(os.getcwd()) != ws_real:
        cands.append(os.path.join(os.getcwd(), f))
    if os.path.isabs(f) and not os.path.lexists(f):
        # a path the model wrote for another root (skill args are not rewritten): keep the longest suffix that exists
        parts = [q for q in f.split("/") if q]
        cands += [os.path.join(ws_real, *parts[i:]) for i in range(1, len(parts))
                  if len(parts) - i >= min(2, len(parts) - 1)]
    ab = next((os.path.realpath(c) for c in cands if os.path.lexists(c)), None)
    if ab is None:   # a new file: the first candidate whose directory exists
        ab = next((os.path.realpath(c) for c in cands if os.path.isdir(os.path.dirname(c) or ".")),
                  os.path.realpath(cands[0]))
    try:
        inside = os.path.commonpath([ab, ws_real]) == ws_real and ab != ws_real
    except ValueError:
        inside = False
    if not inside:
        raise Fail("REFUSED: outside the repository (%s). Installed dependencies are read-only; change the repository "
                   "code instead." % disp(f, 120), why="REFUSED", counts=False)
    return ab, os.path.relpath(ab, ws_real).replace(os.sep, "/")


def suggest(rel):
    base = os.path.basename(rel)
    try:
        out = C.git(["ls-files", "-z"], timeout=5)
        text = out[1] if isinstance(out, tuple) else out
    except Exception:
        return ""
    names = [p for p in (text or "").split("\0") if p and os.path.basename(p) == base][:3]
    return (" Did you mean: %s?" % ", ".join(names)) if names else ""


# ------------------------------------------------------------------------------------------------------------- journal
def journal_entries():
    """edit.py's own entries from the journal tail (oldest first)."""
    try:
        return [e for e in C.journal_entries() if e.get("h") == "edit"]
    except Exception:
        return []


def consecutive_failures(entries, rel):
    c = 0
    for e in reversed(entries):
        if e.get("file") != rel:
            continue
        if e.get("ok"):
            break
        if e.get("counts", True):
            c += 1
    return c


def _journal(ev):
    try:
        C.journal(ev)
    except Exception:
        pass


# ---------------------------------------------------------------------------------------------------------------- main
class Hygiene(object):
    """C.hygiene_revert() in a thread. edit.py never writes a protected path, so its result does not depend on the edit;
    running it beside the in-memory compile and the write hides its two git calls (waits release the GIL)."""

    def __init__(self):
        import threading
        self.res, self.err = [], None
        self.th = threading.Thread(target=self._run)
        self.th.daemon = True
        self.th.start()

    def _run(self):
        try:
            self.res = C.hygiene_revert() or []
        except Exception as e:  # reported, never fatal
            self.err = e

    def note(self):
        self.th.join(30)
        if self.th.is_alive():
            return "NOTE: the test/config revert check is still running."
        if self.err is not None:
            return "NOTE: the test/config revert check failed (%s)." % type(self.err).__name__
        return C.hygiene_note(self.res)


class Ctx(object):
    def __init__(self):
        self.t = 0.0
        self.first, self.body, self.extra = "", [], []
        self.rel = self.ab = self.key = self.fsha = None
        self.mode, self.lines, self.entries, self.views, self.ok, self.hyg = "", None, [], [], False, None
        self.rdec = []


def main():
    C.bootstrap()
    x = Ctx()
    x.t = round(C.clock(), 2)
    try:
        run(x, *get_args(sys.argv[1:]))
    except Fail as f:
        on_fail(x, f)
    C.emit(NAME, x.first, "\n".join(x.body), C.CAPS[NAME], tail=x.extra, src=True if x.ok else None)


def get_args(argv):
    """-> (opts, extra positionals) from C.parse_args (an Args dict; '_' holds the unassigned positionals)."""
    opts = C.parse_args(argv, FLAGS, ["file"])
    bad = dict(opts.get("_bad") or {})
    for k in ("insert-after", "after", "start", "end"):
        if k in bad:
            raise Fail("ERROR: --%s wants a line number (got %r)." % (k, str(bad[k])[:40]), counts=False)
    return opts, [str(p) for p in (opts.get("_") or [])]


def on_fail(x, f):
    x.first, x.body = f.first, list(f.body)
    if x.hyg is not None:
        note = x.hyg.note()
        if note:
            x.extra.append(note)
    if x.rel is None:
        return
    if f.counts and x.lines is not None and consecutive_failures(x.entries, x.rel) + 1 >= 3:
        x.body += third_failure(x, f)
    save_state(x, [])
    ev = {"h": "edit", "ok": False, "file": x.rel, "mode": x.mode, "why": f.why, "key": x.key, "t": x.t,
          "counts": f.counts}
    if f.hint:
        ev["hint"] = [int(f.hint[0]), int(f.hint[1])]
    ev.update(f.ev)
    _journal(ev)


def third_failure(x, f):
    """After three failed edits in a row on one file: the numbered current region and the --lines recipe."""
    if any(s.startswith("use: ") for s in f.body) and any(_ROW.match(s) for s in f.body):
        return ["3 failed edits in a row on %s: stop retrying SEARCH blocks; replace by line numbers with the recipe "
                "above." % x.rel]
    n = len(x.lines)
    if n == 0:
        return []
    a, b = f.hint if f.hint else (1, min(n, 12))
    a = min(max(1, a), n)
    b = min(max(a, b), n)
    lo, hi = max(1, a - 3), min(n, b + 3)
    rows, last = numbered(x.lines, lo, hi, 650)
    if rows:
        x.views.append([lo, last, x.t])
    return ["3 failed edits in a row on %s. Current lines %d-%d:" % (x.rel, lo, last)] + rows + \
           ["use: " + RECIPE % (x.rel, a, b)]


def save_state(x, edits):
    views = [v for v in x.views if v[1] >= v[0]]
    if not edits and not views:
        return

    def fn(st):
        if edits:
            lst = st.get("edits")
            if not isinstance(lst, list):
                lst = st["edits"] = []
            lst.extend(edits)
            del lst[:-200]
        if views:
            vv = st.get("views")
            if not isinstance(vv, dict):
                vv = st["views"] = {}
            cur = vv.get(x.rel)
            if not isinstance(cur, list):
                cur = vv[x.rel] = []
            cur.extend(views)
            del cur[:-60]
        return st
    try:
        C.state_update(fn)
    except Exception:
        pass
    x.views = []


def run(x, opts, pos):
    fname = opts.get("file") or (pos[0] if pos else None)
    rest = [p for p in pos if p != fname]
    if opts.get("file") and pos and not rest:
        rest = pos
    create, delete = _flag(opts, "create"), _flag(opts, "delete")
    lines_opt, ins = opts.get("lines"), opts.get("insert-after")
    if ins is None:
        ins = opts.get("after")
    if lines_opt is None and opts.get("start") is not None:
        lines_opt = (int(opts["start"]), int(opts["end"] if opts.get("end") is not None else opts["start"]))
    if not fname:
        raise Fail("USAGE: " + USAGE, why="USAGE", counts=False)
    rng = parse_range(lines_opt) if lines_opt is not None else None
    if rng and rng[0] == rng[1] and rest and re.match(r"^\d+$", str(rest[0]).strip()):
        rng = (rng[0], int(rest[0]))                          # --lines 120 135
    if ins is not None:
        try:
            ins = int(str(ins).strip())
        except ValueError:
            raise Fail("ERROR: --insert-after wants a line number, for example --insert-after 40.", counts=False)
    if sum((rng is not None, ins is not None, create)) > 1:
        raise Fail("ERROR: use only one of --lines, --insert-after, --create. Usage: " + USAGE, counts=False)
    if delete and rng is None:
        raise Fail("ERROR: --delete needs --lines A-B (the lines to delete).", counts=False)

    text = C.unrewrite(C.input_text(opts).replace("\r\n", "\n"))
    if opts.get("text") not in (None, False) and text and not text.endswith("\n"):
        text += "\n"                       # --text behaves like a heredoc, which always ends in a newline

    x.ab, x.rel = resolve(C.ws(), fname)
    rel, ab = x.rel, x.ab
    reason = C.is_protected(rel)
    if reason:
        raise Fail("REFUSED: %s (%s); graders replace test files; this edit would make grading fail; put checks in a "
                   "reproduction." % (reason, rel), why="REFUSED", counts=False)
    py = rel.endswith(".py")
    markers = has_markers(text)
    mode = "create" if create else "delete" if delete else "lines" if rng else "insert" if ins is not None else "search"
    note = ""
    if markers and mode in ("lines", "insert"):
        note = "(ignored --%s: your text has SEARCH/REPLACE blocks) " % ("lines" if mode == "lines" else "insert-after")
        mode = "search"
    if os.path.isdir(ab):
        raise Fail("ERROR: %s is a directory, not a file." % rel, counts=False)
    exists = os.path.isfile(ab)
    if mode == "search" and not exists and markers and _single_empty_search(text):
        mode = "create"                                        # an empty SEARCH on a missing file means create
    if mode == "create" and markers:
        blocks = parse_blocks(text)
        if len(blocks) != 1 or "".join(blocks[0][0][0]).strip():
            raise Fail("ERROR: --create takes the file's content, not SEARCH/REPLACE blocks.", counts=False)
        text = "\n".join(blocks[0][0][1]) + ("\n" if blocks[0][0][1] else "")
    x.mode = mode
    if mode == "create":
        if os.path.lexists(ab):
            raise Fail("REFUSED: %s already exists; change it with SEARCH/REPLACE blocks or --lines." % rel,
                       why="REFUSED", counts=False)
        raw, lines, final_nl, bom = b"", [], True, False
    elif not exists:
        raise Fail("ERROR: %s does not exist (for a new file add --create).%s" % (rel, suggest(rel)), counts=False)
    else:
        with open(ab, "rb") as fh:
            raw = fh.read()
        if b"\0" in raw[:8192]:
            raise Fail("REFUSED: %s looks binary (NUL bytes); only text files can be edited." % rel, why="REFUSED",
                       counts=False)
        txt, bom = decode(raw)
        lines, final_nl = split_text(txt)
    x.lines = lines
    fsha = x.fsha = C.sha1_hex(raw)
    rkey = ("%d-%d" % rng) if rng else (str(ins) if ins is not None else "")
    x.key = C.sha1_hex("\0".join((rel, mode, rkey, text, fsha)))
    x.entries = journal_entries()
    for e in reversed(x.entries):
        if e.get("key") == x.key and not e.get("ok") and e.get("why") in RETRY_WHY:
            h = e.get("hint") or ([rng[0], rng[1]] if rng else [1, max(1, min(len(lines), 20))])
            a, b = int(h[0]), int(h[1])
            why = e.get("first_why") or e.get("why")
            raise Fail("ALREADY TRIED: this exact edit failed at t=%ds (%s). Do something different: python3 "
                       "/tmp/swe/view.py %s %d %d, then python3 /tmp/swe/edit.py %s --lines %d-%d."
                       % (int(float(e.get("t") or 0)), why, rel, max(1, a - 3), b + 3, rel, a, b),
                       why="ALREADY TRIED", hint=(a, b), ev={"first_why": why})

    crlf = crlf_dominant(lines, final_nl)
    warn = []
    if mode == "search":
        if not markers:
            raise Fail("ERROR: no <<<<<<< SEARCH / ======= / >>>>>>> REPLACE block in your text; nothing changed. To "
                       "replace lines by number add --lines A-B; for a new file add --create.", counts=False)
        blocks = parse_blocks(text)
        res = search_mode(x, lines, final_nl, blocks, crlf, warn, note)
        alts = [("rpick", (lambda k=k: search_mode(x, lines, final_nl, blocks, crlf, [], note, None, k)))
                for k in (1, 2)]
        alts += [(f, (lambda f=f: search_mode(x, lines, final_nl, blocks, crlf, [], note, f)))
                 for f in ("unescape", "fence")]
    else:
        res, alts = line_mode(x, mode, lines, final_nl, rng, ins, text, crlf, warn)
    new_lines, new_fnl, head, edits, spans = res
    if mode != "create" and new_lines == lines and new_fnl == final_nl:
        raise Fail("NO CHANGE: the new text equals the old text.", why="NO CHANGE",
                   hint=(spans[0][0], max(spans[0])) if spans else None)
    x.hyg = Hygiene()
    data = encode(join_text(new_lines, new_fnl), bom)
    if py:
        err = compile_error(data, ab)
        for fix, alt in (alts if err else ()):
            got = alt()
            if got is None:
                continue
            a_data = encode(join_text(got[0], got[1]), bom)
            if compile_error(a_data, ab) is None:
                new_lines, new_fnl, head, edits, spans = got
                data, err = a_data, None
                if fix == "rpick":
                    how = {"raw": "as you wrote it", "quotes": "with only its \\\" escapes decoded",
                           "full": "with its escapes decoded"}
                    warn.append("NOTE: SEARCH matched after decoding escapes; your new text compiled only %s." %
                                how.get((x.rdec or ["raw"])[0], "decoded"))
                elif fix == "unescape":
                    warn = [w for w in warn if '\\"' not in w]
                    warn.append("NOTE: your new text had \\\" or \\n escapes and did not compile as written; they were "
                                "decoded once.")
                else:
                    warn.append("NOTE: your new text had ``` fence lines and did not compile as written; they were "
                                "dropped.")
                break
        if err:
            if mode == "create" or compile_error(raw, ab) is None:
                raise revert_fail(x, err, new_lines, spans, edits)
            warn.insert(0, "WARNING: %s does not compile (line %d: %s); it did not compile before this edit either, so "
                           "the edit was applied. Fix that error too." % (rel, err[0], disp(err[1], 120)))
    if mode == "create":
        d = os.path.dirname(ab)
        try:
            if d:
                os.makedirs(d, exist_ok=True)
        except OSError as e:
            raise Fail("ERROR: could not create the directory of %s (%s); nothing changed." % (rel, e.strerror or e),
                       counts=False)
    try:
        with open(ab, "wb") as fh:
            fh.write(data)
    except OSError as e:
        raise Fail("ERROR: could not write %s (%s: %s); nothing changed." % (rel, type(e).__name__, e.strerror or e),
                   counts=False)
    report_ok(x, head, new_lines, spans, edits, warn, py)


def report_ok(x, head, new_lines, spans, edits, warn, py):
    """Everything after the write is bookkeeping: it never turns a written edit into an error."""
    rel = x.rel
    try:
        budget = C.CAPS[NAME] - RESERVE - len(head) - sum(len(w) + 1 for w in warn)
        rows, shown = region(new_lines, spans, max(160, budget), rel)
    except Exception:
        rows, shown = [], []
    x.views.extend([a2, b2, x.t] for a2, b2 in spans if b2 >= a2)
    first = head + " " + (", ".join("%d-%d" % s for s in shown) if shown else "none (the file is empty)") + ":"
    if warn and warn[0].startswith("WARNING: %s does not compile" % rel):
        x.first, x.body = warn[0], [first] + warn[1:] + rows
    else:
        x.first, x.body = first, warn + rows
    x.ok = True
    save_state(x, [{"file": rel, "start": int(a), "end": int(b), "delta": int(dl), "t": x.t} for a, b, dl in edits])
    tier = head[4:head.index(")")] if head.startswith("OK (") and ")" in head else ""
    ev = {"h": "edit", "ok": True, "file": rel, "mode": x.mode, "tier": tier,
          "start": int(edits[0][0]) if edits else 0, "end": int(edits[-1][1]) if edits else 0,
          "delta": int(sum(dl for _, _, dl in edits)), "key": x.key, "t": x.t}
    if x.rdec:
        ev["rdec"] = list(x.rdec)          # which REPLACE form a decoded SEARCH used: raw, quotes or full
    _journal(ev)
    note = x.hyg.note() if x.hyg is not None else C.hygiene_note(C.hygiene_revert() or [])
    if note:
        x.extra.append(note)
    try:                                     # v10.1: a landed edit is restorable even if it is undone later
        d = C.diff_bytes()
        if d:
            import _swe_ckpt as K
            # the edited file is in the diff: a source change for sure (a quoted path falls back to the full check)
            K.save_edited(d if (" b/%s\n" % rel).encode("utf-8", "surrogateescape") in d else None)
    except Exception:
        pass
    if py:
        x.extra.append("NEXT: python3 /tmp/swe/verify.py")


def _single_empty_search(text):
    try:
        blocks = parse_blocks(text)
    except Fail:
        return False
    return len(blocks) == 1 and not "".join(blocks[0][0][0]).strip()


def _trim_edges(Sl, Rl):
    """SEARCH without its leading/trailing blank lines; REPLACE loses as many blank edge lines as it has."""
    a, b = 0, len(Sl)
    while a < b and not Sl[a].strip():
        a += 1
    while b > a and not Sl[b - 1].strip():
        b -= 1
    if (a, b) == (0, len(Sl)) or a == b:
        return None
    ra, rb = 0, len(Rl)
    for _ in range(a):
        if ra < rb and not Rl[ra].strip():
            ra += 1
    for _ in range(len(Sl) - b):
        if rb > ra and not Rl[rb - 1].strip():
            rb -= 1
    return Sl[a:b], Rl[ra:rb]


def _fix_replace(Rl, fix):
    if fix == "unescape":
        return unescape("\n".join(Rl)).split("\n") if Rl else Rl
    if fix == "fence":
        return strip_fences(Rl)
    return Rl


def search_mode(x, lines, final_nl, blocks, crlf, warn, note, fix=None, rpick=0):
    """Apply every block in order to an in-memory copy (all-or-nothing). fix ("unescape" or "fence") rewrites every
    REPLACE once: the fallback when the result does not compile as written. rpick > 0 takes the next REPLACE form for
    blocks whose SEARCH matched only after decoding (replace_choices). -> (lines, final_nl, head, edits, spans), or
    None when the fix or rpick changes nothing or a block no longer applies. x.rdec gets the forms used."""
    if fix and not any(_fix_replace(R, fix) != R for c in blocks for _, R in c):
        return None
    infos, cur, fnl = [], list(lines), final_nl
    for bi, cands in enumerate(blocks):
        keys = {"r": [s.rstrip() for s in cur], "s": [s.strip() for s in cur]}
        hit, fail, used = None, None, None
        for Sl, Rl in cands:
            Rl = _fix_replace(Rl, fix)
            if not "".join(Sl).strip():
                if not cur:
                    hit, used = Hit("exact", 0, 0, list(Rl)), (Sl, Rl)
                    break
                fail = fail or Fail("ERROR: block %d has an empty SEARCH; to add lines use --insert-after N, for a new "
                                    "file --create." % (bi + 1), counts=False)
                continue
            try:
                h = find_block(cur, fnl, Sl, Rl, keys, rpick)
                if h is None:
                    tr = _trim_edges(Sl, Rl)
                    if tr:
                        h = find_block(cur, fnl, tr[0], tr[1], keys, rpick)
                        if h is not None:
                            Sl, Rl = tr
            except Fail as e:
                fail = fail or e
                continue
            if h is not None:
                hit, used = h, (Sl, Rl)
                break
        if hit is None:
            if fix:
                return None
            if fail is None:
                fail = no_match(x, lines, cands[0][0])
            if len(blocks) > 1 and fail.why in ("NO MATCH", "AMBIGUOUS"):
                fail.first = fail.first.replace(": ", " (block %d of %d; no block was applied): " % (bi + 1,
                                                                                                    len(blocks)), 1)
            raise fail
        Sl, Rl = used
        cur2, fnl2, A, B, A2, B2 = apply_hit(cur, fnl, hit, crlf)
        delta = len(cur2) - len(cur)
        tier = hit.tier + (("+" + fix) if fix and fix not in hit.tier else "")
        new_txt = "\n".join(hit.new) if isinstance(hit.new, list) else (hit.new or "")
        old_txt = "\n".join(cur[A - 1:B])
        if '\\"' in new_txt and '\\"' not in "\n".join(Sl) and '\\"' not in old_txt:
            warn.append('WARNING: block %d new text contains \\" but the code it replaced does not; heredoc text needs '
                        'no escaping, so if you meant a plain quote, fix it.' % (bi + 1))
        if hit.chars in (None, 2):
            fn = next((s for s in new_txt.split("\n") if s.strip()), None)
            if fn is not None and not indent_of(fn) and indent_of(next((s for s in cur[A - 1:B] if s.strip()), "")):
                warn.append("WARNING: block %d new text starts at column 0 but line %d was indented; check the "
                            "indentation." % (bi + 1, A))
        for i in infos:                          # earlier blocks' new spans below this edit move with it
            if i["A2"] > B:
                i["A2"] += delta
                i["B2"] += delta
        infos.append({"tier": tier, "A": A, "B": B, "A2": A2, "B2": B2, "delta": delta, "rdec": hit.rdec,
                      "nalt": hit.nalt})
        cur, fnl = cur2, fnl2
    if rpick and not any(i["nalt"] > rpick for i in infos):
        return None                              # no decoded block has a form this far down the list
    x.rdec = [i["rdec"] for i in infos if i["rdec"]]
    tiers = []
    for i in infos:
        if i["tier"] not in tiers:
            tiers.append(i["tier"])
    if len(infos) == 1:
        i = infos[0]
        head = "OK (%s): %s%s lines %d-%d replaced (%d old, %d new). Now lines" % (
            i["tier"], note, x.rel, i["A"], i["B"], i["B"] - i["A"] + 1, max(0, i["B2"] - i["A2"] + 1))
    else:
        parts = "; ".join("%d-%d (%d old, %d new)" % (i["A"], i["B"], i["B"] - i["A"] + 1,
                                                      max(0, i["B2"] - i["A2"] + 1)) for i in infos)
        head = "OK (%s): %s%s %d blocks: lines %s. Now lines" % (", ".join(tiers), note, x.rel, len(infos), parts)
    return cur, fnl, head, [(i["A"], i["B"], i["delta"]) for i in infos], [(i["A2"], i["B2"]) for i in infos]


def no_match(x, lines, Sl):
    """NO MATCH on the unchanged file: the closest numbered window, the first difference and the --lines recipe."""
    rel = x.rel
    c = closest(lines, Sl)
    if c is None:
        return Fail("NO MATCH: %s unchanged. No similar lines found; look first: python3 /tmp/swe/view.py %s" % (rel, rel),
                    why="NO MATCH")
    r, a, b = c
    rows, last = numbered(lines, a, b, 700)
    body = list(rows)
    if last < b:
        body.append("  ... (more: python3 /tmp/swe/view.py %s %d %d)" % (rel, last + 1, b))
    if rows:
        x.views.append([a, last, x.t])
    diff = first_difference(lines, Sl, a)
    if diff:
        d, s, f = diff
        body.append("first difference: your line %d: %s" % (d + 1, disp(s.strip(), 110)))
        body.append("                  file line %d: %s" % (a + d, disp(f.strip(), 110)))
    body.append("use: " + RECIPE % (rel, a, b))
    return Fail("NO MATCH: %s unchanged. Closest lines (similarity %.2f) are %d-%d:" % (rel, r, a, b), body,
                why="NO MATCH", hint=(a, b))


def revert_fail(x, err, new_lines, spans, edits):
    L, msg = err
    where = ""
    for i, (a2, b2) in enumerate(spans):
        if a2 <= L <= b2:
            where = (" (line %d of your new text)" % (L - a2 + 1)) if len(spans) == 1 else \
                (" (line %d of block %d's new text)" % (L - a2 + 1, i + 1))
            break
    if not where and spans:
        a2, b2 = min(s[0] for s in spans), max(s[1] for s in spans)
        if L > b2:
            where = " (%d lines after your new text, which ends at line %d; check brackets and quotes)" % (L - b2, b2)
        elif 0 < L < a2:
            where = " (before your new text, which starts at line %d)" % a2
    body = []
    if 0 < L <= len(new_lines):
        body.append("your edit would give:")
        for n in range(max(1, L - 1), min(len(new_lines), L + 1) + 1):
            body.append("%5d|%s%s" % (n, ">" if n == L else " ", disp(new_lines[n - 1])))
    a0, b0 = (edits[0][0], max(edits[0][0], edits[0][1])) if edits else (1, 1)
    return Fail("REVERTED: syntax error at line %d%s: %s. %s unchanged." % (L, where, disp(msg, 160), x.rel), body,
                why="REVERTED", hint=(a0, b0))


def line_mode(x, mode, lines, final_nl, rng, ins, text, crlf, warn):
    """--lines / --delete / --insert-after / --create. -> ((lines, final_nl, head, edits, spans), alternatives) where the
    alternatives rebuild the edit with the text unescaped / without fence lines (compile-failure fallbacks).
    Final newline: an existing one is never removed; when the edit reaches the end of the file, the text decides
    (a heredoc always ends in a newline; stdin without one keeps a missing final newline missing)."""
    rel, n = x.rel, len(lines)
    clamp, tail_nl = "", text.endswith("\n")
    if mode in ("lines", "delete"):
        A, B = rng
        if A < 1 or B < A:
            raise Fail("ERROR: bad range %d-%d; lines are 1-based and A <= B (to insert, use --insert-after N)." % (A, B),
                       counts=False)
        if A > n:
            raise Fail("ERROR: %s has only %d lines; --lines %d-%d is past the end (to append, use --insert-after %d)."
                       % (rel, n, A, B, n), counts=False)
        if B > n:
            clamp, B = " (end clamped from %d to %d)" % (B, n), n
        if mode == "delete" and text.strip():
            raise Fail("ERROR: --delete takes no text; to replace the lines, drop --delete.", counts=False)
        if mode == "lines" and text == "":
            raise Fail("ERROR: no text on stdin (to delete lines add --delete)", counts=False)
        new = [] if mode == "delete" else text_lines(text)
        stale_gate(x, A, B, mode, new)

        def build(nl, tag=""):
            nl = with_eol(nl, crlf)
            out = lines[:A - 1] + nl + lines[B:]
            fnl = final_nl or (B >= n and bool(out) and (tail_nl or mode == "delete" or not nl))
            if mode == "delete":
                h = "OK (delete): %s lines %d-%d deleted (%d old). Now lines" % (rel, A, B, B - A + 1)
            else:
                h = "OK (lines%s): %s lines %d-%d replaced (%d old, %d new)%s. Now lines" % (
                    tag, rel, A, B, B - A + 1, len(nl), clamp)
            return out, fnl, h, [(A, B, len(nl) - (B - A + 1))], [(A, A + len(nl) - 1)]
        old = lines[A - 1:B]
        if '\\"' in "\n".join(new) and '\\"' not in "\n".join(old):
            warn.append('WARNING: your new text contains \\" but the lines it replaced do not; heredoc text needs no '
                        'escaping, so if you meant a plain quote, fix it.')
        fn = next((s for s in new if s.strip()), None)
        if fn is not None and not indent_of(fn) and indent_of(next((s for s in old if s.strip()), "")):
            warn.append("WARNING: your new text starts at column 0 but line %d was indented; check the indentation." % A)
    elif mode == "insert":
        if ins < 0:
            raise Fail("ERROR: --insert-after wants 0 (the top of the file) or a line number.", counts=False)
        N = ins
        if N > n:
            clamp, N = " (clamped from %d to the end, %d)" % (N, n), n
        if text == "":
            raise Fail("ERROR: no text on stdin to insert.", counts=False)
        new = text_lines(text)
        if N >= 1:
            stale_gate(x, N, N, mode, new)

        def build(nl, tag=""):
            nl = with_eol(nl, crlf)
            out = lines[:N] + nl + lines[N:]
            fnl = final_nl or (N >= n and tail_nl)
            h = "OK (insert%s): %s %d new lines after line %d%s. Now lines" % (tag, rel, len(nl), N, clamp)
            return out, fnl, h, [(N + 1, N, len(nl))], [(N + 1, N + len(nl))]
        if '\\"' in "\n".join(new) and '\\"' not in "\n".join(lines):
            warn.append('WARNING: your new text contains \\" but this file has none; heredoc text needs no escaping, so '
                        'if you meant a plain quote, fix it.')
    else:
        new = text_lines(text)

        def build(nl, tag=""):
            h = "OK (create%s): %s created (%d lines). Now lines" % (tag, rel, len(nl))
            return list(nl), tail_nl, h, [(1, 0, len(nl))], [(1, len(nl))]

    def unesc():
        joined = "\n".join(new)
        dec = unescape(joined)
        return None if dec == joined else build(dec.split("\n"), ", unescape")

    def unfence():
        return build(strip_fences(new), ", fence") if has_fence(new) else None
    return build(new), [("unescape", unesc), ("fence", unfence)]


def _similarity(new, old):
    import difflib
    return difflib.SequenceMatcher(None, "\n".join(s.strip() for s in new),
                                   "\n".join(s.strip() for s in old)).ratio()


def stale_gate(x, A, B, mode, new):
    """Refuse --lines / --insert-after numbers that predate a line-shifting edit (SPEC 4.7 STALE). For --lines the new
    text breaks the tie: when it clearly resembles the lines as numbered now (similarity +0.15 over the shifted
    region), the numbers are current (they came from grep, verify or the last edit's display) and are accepted."""
    skey = C.sha1_hex("%s\0%s\0%d-%d\0%s" % (x.rel, mode, A, B, x.fsha))
    for e in reversed(x.entries):
        if e.get("file") == x.rel and e.get("ok"):
            break
        if e.get("why") == "STALE" and e.get("skey") == skey and e.get("stale"):
            A2, B2, d = e["stale"]
            raise Fail(_stale_line(A2, B2, d, mode), why="STALE", counts=False, ev={"skey": skey, "stale": [A2, B2, d]})
    try:
        st = C.state_load() or {}
    except Exception:
        return
    got = stale_check(x.rel, A, B, st.get("edits") or [], st.get("views") or {}, strong=mode == "insert")
    if got is None and mode == "lines" and "".join(new).strip():
        cs = content_shift(x.rel, A, B, new, x.lines, st.get("edits") or [])
        got = (cs[0], cs[1], cs[2], False) if cs else None
    if got is None:
        return
    A2, B2, d, over = got
    n = len(x.lines)
    if mode == "lines" and new and "".join(new).strip():
        here = _similarity(new, x.lines[A - 1:B])
        there = _similarity(new, x.lines[max(0, A2 - 1):max(0, B2)]) if (not over and 1 <= A2 <= n) else 0.0
        if here >= there + 0.15:
            return
    if over:
        raise Fail("STALE: %s lines %d-%d were changed by an edit after your last view of them; view them again: "
                   "python3 /tmp/swe/view.py %s %d %d" % (x.rel, A, B, x.rel, max(1, A2 - 2), min(n, B2 + 2)),
                   why="STALE", counts=False)
    body = []
    if 1 <= A2 <= n:
        body, last = numbered(x.lines, A2, min(n, max(A2, B2), A2 + 11), 600)
        if body:
            x.views.append([A2, last, x.t])
    raise Fail(_stale_line(A2, B2, d, mode), body, why="STALE", counts=False, ev={"skey": skey, "stale": [A2, B2, d]})


def _stale_line(A2, B2, d, mode):
    word = ("--insert-after %d" % A2) if mode == "insert" else ("--lines %d-%d" % (A2, B2))
    return ("STALE: lines moved by %+d since your last view of this region; the same code is now at %d-%d. Re-run with "
            "%s or view it again." % (d, A2, B2, word))


if __name__ == "__main__":
    C.safe_main(NAME, main)
