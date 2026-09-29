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

# Numbered file views (range, symbol, outline) and the source of any importable object (--obj).
# Lines are numbered by splitting the bytes on \n only, so the numbers equal git's and edit.py's.
import re, json

USAGE = "python3 /tmp/swe/view.py FILE [START END | NAME] | --obj DOTTED.NAME"
FLAGS = {"file": "str", "start": "int", "end": "int", "name": "str", "obj": "str"}
NAME = "view"
MAX_LINES = 100
OUTLINE_MAX = 60
LONG_LINE, HEAD, TAIL = 400, 200, 100
FOOTER_RESERVE = 300
VIEWS_KEPT = 60
NON_UTF8 = "[non-UTF-8 bytes shown as U+FFFD]"
_MARK = "\x1eSWEOBJ "

DRIVER = r"""
import sys, json, importlib, inspect
M = "\x1eSWEOBJ "
def say(k, v):
    sys.stdout.write(M + json.dumps([k, v]) + "\n")
    sys.stdout.flush()
name = sys.argv[1]
parts = [p for p in name.split(".") if p]
try:
    say("import", parts[0])
    try:
        obj = importlib.import_module(parts[0])
    except ImportError:
        import builtins
        if not hasattr(builtins, parts[0]):
            raise
        obj = getattr(builtins, parts[0])
    owner, definer, raw = None, None, None
    for i, p in enumerate(parts[1:], 1):
        if inspect.ismodule(obj) and not hasattr(obj, p):
            sub = ".".join(parts[:i + 1])
            say("import", sub)
            obj = importlib.import_module(sub)
            owner = definer = raw = None
            continue
        owner, definer, raw = obj, None, None
        if inspect.isclass(obj):
            for k in inspect.getmro(obj):
                if p in vars(k):
                    definer, raw = k, vars(k)[p]
                    break
        obj = getattr(obj, p)
    target = obj
    if isinstance(raw, property):
        target = raw.fget
    elif isinstance(raw, (staticmethod, classmethod)):
        target = raw.__func__
    if hasattr(target, "func") and type(target).__name__ == "partial":
        target = target.func
    try:
        target = inspect.unwrap(target)
    except Exception:
        pass
    if inspect.ismethod(target):
        target = target.__func__
    kind = ("module" if inspect.ismodule(obj) else "class" if inspect.isclass(obj) else
            "property" if isinstance(raw, property) else "function" if callable(obj) else type(obj).__name__)
    res = {"kind": kind}
    try:
        res["sig"] = str(inspect.signature(obj))
    except Exception:
        pass
    if definer is not None:
        res["defined_in"] = definer.__module__ + "." + definer.__qualname__
    try:
        res["file"] = inspect.getsourcefile(target) or inspect.getfile(target)
    except Exception as e:
        res["nosrc"] = type(e).__name__
    if kind == "module":
        res["file"] = getattr(obj, "__file__", None) or res.get("file")
    else:
        try:
            lines, start = inspect.getsourcelines(target)
            res["start"], res["end"] = max(1, start), max(1, start) + len(lines) - 1
        except Exception as e:
            res["nosrc"] = type(e).__name__
    doc = inspect.getdoc(obj) or ""
    res["doc"] = doc.strip().split("\n")[0][:160]
    if not (inspect.ismodule(obj) or inspect.isclass(obj) or callable(obj) or isinstance(raw, property)):
        try:
            res["value"] = repr(obj)[:300]
        except Exception:
            pass
    say("result", res)
except BaseException as e:
    say("error", "%s: %s" % (type(e).__name__, str(e)[:200]))
"""


# ---------------------------------------------------------------- file reading and formatting
def read_lines(path):
    """([line bytes], n_lines). Bytes are split on \\n only; a trailing newline does not start a new line."""
    with open(path, "rb") as f:
        data = f.read()
    if not data:
        return [], 0, data
    lines = data.split(b"\n")
    if data.endswith(b"\n"):
        lines.pop()
    return lines, len(lines), data


def fmt(n, raw):
    """(formatted line, non_utf8 flag): '%5d| text', \\r stripped at the end, long lines cut 200 + ... + 100."""
    bad = False
    try:
        t = raw.decode("utf-8")
    except UnicodeDecodeError:
        t = raw.decode("utf-8", "replace")
        bad = True
    if t.endswith("\r"):
        t = t[:-1]
    if len(t) > LONG_LINE:
        t = t[:HEAD] + " ... " + t[-TAIL:]
    return "%5d| %s" % (n, t), bad


def render_range(lines, a, b, budget):
    """Numbered lines a..b within MAX_LINES and the char budget; returns (text lines, last shown, non_utf8)."""
    out, used, bad, last = [], 0, False, a - 1
    for n in range(a, min(b, len(lines)) + 1):
        if n - a >= MAX_LINES:
            break
        s, bd = fmt(n, lines[n - 1])
        if out and used + len(s) + 1 > budget:
            break
        out.append(s)
        used += len(s) + 1
        bad = bad or bd
        last = n
    return out, last, bad


def clamp_hint(disp, last):
    return "range clamped; next: python3 /tmp/swe/view.py %s %d %d" % (disp, last + 1, last + MAX_LINES)


def _py(env):
    import shutil
    return "python3" if shutil.which("python3", path=(env or os.environ).get("PATH")) else (sys.executable or "python3")


def _int(v):
    try:
        s = str(v).strip().rstrip(",")
        return int(s[1:] if s[:1] in ("L", "l") and s[1:].isdigit() else s)
    except (TypeError, ValueError):
        return None


def record_view(ws, rel, a, b):
    t = round(float(C.clock()), 1)

    def upd(s):
        views = s.get("views")
        if not isinstance(views, dict):
            views = {}
        lst = list(views.get(rel) or [])
        lst.append([int(a), int(b), t])
        views[rel] = lst[-VIEWS_KEPT:]
        s["views"] = views
        return s
    C.state_update(upd)


def resolve(ws, f):
    """(abs path, display path, rel-in-ws or None)."""
    ap = f if os.path.isabs(f) else os.path.join(ws, f)
    ap = os.path.normpath(ap)
    rw = os.path.realpath(ws)
    rp = os.path.realpath(ap)
    if rp == rw or rp.startswith(rw + os.sep):
        rel = os.path.relpath(rp, rw).replace(os.sep, "/")
        return ap, rel, rel
    return ap, C.unrewrite(ap), None


def suggest(ws, f):
    base = os.path.basename(f.rstrip("/"))
    if not base:
        return ""
    rc, out = C.sh(["git", "-c", "core.quotepath=off", "ls-files", "-z"], C.real_budget(5), cwd=ws)
    allf = [p for p in (out or "").split("\0") if p]
    cands = [p for p in allf if p.rsplit("/", 1)[-1] == base][:3]
    if not cands and allf:
        import difflib
        cands = difflib.get_close_matches(f.strip("/"), allf, 3, 0.75)
    return (" Did you mean: %s?" % ", ".join(cands)) if cands else ""


def split_spec(ws, f):
    """FILE:A-B, FILE:A (as in the locator's plan) -> (file, a, b) when FILE itself does not exist."""
    ap = f if os.path.isabs(f) else os.path.join(ws, f)
    if os.path.exists(ap):
        return f, None, None
    m = re.match(r"^(.*?):[Ll]?(\d+)(?:\s*[-:,]\s*[Ll]?(\d+))?$", f)
    if m:
        return m.group(1), int(m.group(2)), (int(m.group(3)) if m.group(3) else None)
    return f, None, None


# ---------------------------------------------------------------- modes
def outline_body(idx, key, disp, n, budget):
    syms = idx.outline(key)
    head = "%s: %d lines, %d defs/classes (outline)" % (disp, n, len(syms))
    out, used = [], 0
    for s in syms[:OUTLINE_MAX]:
        ln = "  %s %s  L%d-%d" % (s[1], s[0][:110], s[2], s[3])
        if used + len(ln) + 1 > budget:
            break
        out.append(ln)
        used += len(ln) + 1
    if len(out) < len(syms):
        out.append("... %d more; view one with: python3 /tmp/swe/view.py %s NAME" % (len(syms) - len(out), disp))
    elif syms:
        out.append("view one with: python3 /tmp/swe/view.py %s NAME (or START END)" % disp)
    return head, out


def symbol_mode(ws, idx, key, disp, rel, lines, n, name, budget):
    import _swe_index as I
    ms = idx.find(key, name)
    if not ms:
        nm = I.normalize_name(name)
        low = nm.lower()
        ms = [s for s in idx.outline(key) if s[0].lower() == low or s[0].lower().endswith("." + low)]
    if not ms:
        import difflib
        names = [s[0] for s in idx.outline(key)]
        close = difflib.get_close_matches(I.normalize_name(name), names, 4, 0.6)
        if not close:
            last = I.normalize_name(name).rsplit(".", 1)[-1].lower()
            close = [q for q in names if last and last in q.lower()][:4]
        msg = "VIEW: no def or class named %s in %s." % (name, disp)
        if not names:
            try:
                big = os.path.getsize(idx._abs(key)) > I.MAX_BYTES
            except OSError:
                big = False
            if big:
                msg += " The file is over 1 MB (not parsed); use START END."
        if close:
            msg += " Close: %s." % ", ".join(close)
        msg += " Outline: python3 /tmp/swe/view.py %s" % disp
        return msg, [], None
    s = ms[0]
    a, b = max(1, s[2]), min(n, s[3])
    others = ["%s %s L%d-%d" % (x[1], x[0], x[2], x[3]) for x in ms[1:6]]
    tail = ["other matches: " + "; ".join(others)] if others else []
    if s[1] == "class" and b - a + 1 > MAX_LINES:
        members = [x for x in idx.outline(key) if x[0].startswith(s[0] + ".") and x[0].count(".") == s[0].count(".") + 1]
        first_member = min([x[2] for x in members] or [b + 1])
        body, last, bad = render_range(lines, a, min(b, first_member - 1, a + 24), budget // 2)
        mem, used = [], 0
        room = budget - sum(len(r) + 1 for r in body) - 200     # the member list gets what the class head leaves
        for x in members[:OUTLINE_MAX]:
            ln = "  %s %s  L%d-%d" % (x[1], x[0][:110], x[2], x[3])
            if used + len(ln) + 1 > room:
                break
            mem.append(ln)
            used += len(ln) + 1
        head = "%s lines %d-%d of %d (class %s, %d lines; members below)" % (disp, a, last, n, s[0], b - a + 1)
        body += ["members of %s (%d):" % (s[0], len(members))] + mem
        body.append("view one with: python3 /tmp/swe/view.py %s %s.NAME" % (disp, s[0]))
        if bad:
            body.append(NON_UTF8)
        return head, body + tail, (a, last)
    body, last, bad = render_range(lines, a, b, budget)
    head = "%s lines %d-%d of %d (%s %s)" % (disp, a, last, n, s[1], s[0])
    if last < b:
        body.append(clamp_hint(disp, last))
    if bad:
        body.append(NON_UTF8)
    return head, body + tail, (a, last)


def range_mode(disp, lines, n, a, b, budget):
    if n == 0:
        return "%s is empty (0 lines)" % disp, [], None
    a = 1 if a is None else a
    b = a + MAX_LINES - 1 if b is None else b
    if b < a:
        b = a + b - 1 if b > 0 else a
    a = max(1, a)
    if a > n:
        return ("VIEW: %s has %d lines; asked for %d-%d. Try: python3 /tmp/swe/view.py %s %d %d"
                % (disp, n, a, b, disp, max(1, n - MAX_LINES + 1), n)), [], None
    want = min(b, n)
    body, last, bad = render_range(lines, a, want, budget)
    head = "%s lines %d-%d of %d" % (disp, a, last, n)
    if last < want:
        body.append(clamp_hint(disp, last))
    if bad:
        body.append(NON_UTF8)
    return head, body, (a, last)


def obj_mode(ws, dotted, cap):
    import _swe_index as I
    dotted = I.normalize_name(dotted)
    if not re.match(r"^[A-Za-z_][\w.]*$", dotted or ""):
        C.emit(NAME, "VIEW: --obj needs a dotted name like package.module.Name", "", cap)
        return
    try:
        env = C.grader_env(ws, "cur")
    except Exception:
        env = dict(os.environ)
    rc, out = C.sh([_py(env), "-s", "-c", DRIVER, dotted], C.real_budget(C.VIEW_OBJ), cwd=ws, env=env)
    events = []
    for ln in (out or "").split("\n"):
        i = ln.find(_MARK)
        if i >= 0:
            try:
                events.append(json.loads(ln[i + len(_MARK):]))
            except ValueError:
                pass
    res = next((v for k, v in events if k == "result"), None)
    err = next((v for k, v in events if k == "error"), None)
    if res is None:
        if rc is None:
            mods = [v for k, v in events if k == "import"]
            what = ("importing " + mods[-1]) if mods else ("resolving " + dotted)
            C.emit(NAME, "HANG %s: no result within %ds (the import itself never finishes; read the file with "
                         "python3 /tmp/swe/view.py FILE instead)" % (what, int(C.real_budget(C.VIEW_OBJ))), "", cap)
        else:
            tailtxt = " ".join(l for l in (out or "").splitlines() if l.strip() and _MARK not in l)[-200:]
            C.emit(NAME, "VIEW: cannot load %s: %s" % (dotted, err or tailtxt or ("exit %s" % rc)), "", cap)
        return
    f = res.get("file")
    head = ["OBJ %s: %s" % (dotted, res.get("kind", "?"))]
    rel = None
    if f:
        ap, disp, rel = resolve(ws, f)
        head.append("origin: %s %s" % (disp, "[workspace]" if rel else "[installed dependency: read-only]"))
    if res.get("sig"):
        head.append("signature: %s%s" % (dotted.rsplit(".", 1)[-1], res["sig"][:300]))
    if res.get("defined_in"):
        head.append("defined in: %s" % res["defined_in"])
    if res.get("value") is not None:
        head.append("value: %s" % res["value"])
    budget = cap - FOOTER_RESERVE - sum(len(h) + 1 for h in head) - 80
    body, view = [], None
    if res.get("value") is not None:
        pass
    elif not f or not os.path.isfile(f) or res.get("nosrc") and res.get("kind") != "module":
        body.append("no Python source (builtin or C extension)%s" % (": " + res["doc"] if res.get("doc") else ""))
    else:
        try:
            lines, n, _data = read_lines(f)
        except OSError as e:
            lines, n = [], 0
            body.append("cannot read %s: %s" % (f, e))
        if n and res.get("kind") == "module":
            idx = I.build(ws, deadline_s=C.real_budget(3), only=[rel or ap], want_terms=False, use_cache=False)
            h2, b2 = outline_body(idx, rel or ap, disp, n, budget)
            body += [h2] + b2
        elif n:
            a, b = int(res.get("start") or 1), int(res.get("end") or 1)
            cls = None
            if res.get("kind") == "class" and b - a + 1 > MAX_LINES:
                idx = I.build(ws, deadline_s=C.real_budget(3), only=[rel or ap], want_terms=False, use_cache=False)
                cls = next((x for x in idx.outline(rel or ap) if x[1] == "class" and x[2] <= a <= x[3]), None)
            if cls is not None:
                h2, b2, view = symbol_mode(ws, idx, rel or ap, disp, rel, lines, n, cls[0], budget)
            else:
                h2, b2, view = range_mode(disp, lines, n, a, b, budget)
            if h2.startswith(disp + " lines "):
                h2 = h2[len(disp) + 1:]
            body += [h2] + b2
    if view and rel:
        record_view(ws, rel, view[0], view[1])
    C.emit(NAME, head[0], "\n".join(head[1:] + body), cap)


def main():
    C.bootstrap()
    opts = C.parse_args(sys.argv[1:], FLAGS, [])
    pos = list(opts.get("_") or [])
    cap = C.CAPS["view"]
    ws = C.ws()
    if opts.get("obj"):
        obj_mode(ws, str(opts["obj"]), cap)
        return
    pos = [str(p) for p in pos]
    f = opts.get("file") or (pos.pop(0) if pos else "")
    f = C.unrewrite(str(f).strip()) if f else ""
    if not f:
        C.print_usage(NAME, USAGE)
        return
    f, a, b = split_spec(ws, f)
    name = opts.get("name")
    if opts.get("start") not in (None, ""):
        a = _int(opts.get("start"))
    if opts.get("end") not in (None, ""):
        b = _int(opts.get("end"))
    if pos and a is None and not name:
        p = pos.pop(0).strip()
        # v10.1: also the L1191-1433 spans that locate.py and grep.py print (race 2: fastapi_14851, fastapi_5624)
        m = re.match(r"^[Ll]?(\d+)\s*(?:-|:|,|\.\.)\s*[Ll]?(\d+)$", p)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
        elif _int(p) is not None:
            a = _int(p)
            if pos and _int(pos[0]) is not None:
                b = _int(pos.pop(0))
        else:
            name = p
    ap, disp, rel = resolve(ws, f)
    if not os.path.exists(ap):
        C.emit(NAME, "VIEW: no such file: %s (paths are relative to the repository root).%s" % (f, suggest(ws, f)),
               "", cap)
        return
    if os.path.isdir(ap):
        try:
            ents = sorted(e.name + ("/" if e.is_dir() else "") for e in os.scandir(ap) if not e.name.startswith("."))
        except OSError:
            ents = []
        C.emit(NAME, ("VIEW: %s is a directory: %s" % (disp, " ".join(ents)))[:600], "", cap)
        return
    try:
        lines, n, data = read_lines(ap)
    except OSError as e:
        C.emit(NAME, "VIEW: cannot read %s: %s" % (disp, e), "", cap)
        return
    if b"\0" in data[:8192]:
        C.emit(NAME, "VIEW: %s looks binary (%d bytes); not shown" % (disp, len(data)), "", cap)
        return
    budget = cap - FOOTER_RESERVE - 200
    view = None
    if name:
        import _swe_index as I
        key = rel or ap
        idx = I.build(ws, deadline_s=C.real_budget(3), only=[key], want_terms=False, use_cache=False)
        head, body, view = symbol_mode(ws, idx, key, disp, rel, lines, n, str(name), budget)
    elif a is None and b is None and ap.endswith(".py") and n > MAX_LINES:
        import _swe_index as I
        key = rel or ap
        idx = I.build(ws, deadline_s=C.real_budget(3), only=[key], want_terms=False, use_cache=False)
        if idx.outline(key):
            head, body = outline_body(idx, key, disp, n, budget)
        else:
            head, body, view = range_mode(disp, lines, n, 1, MAX_LINES, budget)
    else:
        head, body, view = range_mode(disp, lines, n, a, b, budget)
    if view and rel:
        record_view(ws, rel, view[0], view[1])
    C.emit(NAME, head, "\n".join(body), cap)


if __name__ == "__main__":
    C.safe_main(NAME, main)
