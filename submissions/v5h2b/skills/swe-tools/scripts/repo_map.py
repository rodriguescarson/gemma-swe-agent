"""Compact AST map of the repository: per file, top-level classes and functions with signatures, method names and
line numbers. Stdlib only. Skips tests, .git, venvs, docs; files with syntax errors are skipped, not fatal.
Usage: python3 /tmp/swe/repo_map.py [PATH_OR_PACKAGE] [--grep TERM]   (TERM may list alternatives as a|b)"""
import ast, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ws import ws

CAP = 4500          # run_command output is cut at 5,000 chars
SIG = 110           # max chars of one signature
METHODS = 30        # max methods listed per class without --grep
NAMES = 14          # max symbols per file in the names-only view
SKIP_DIRS = {".git", ".hg", ".svn", "__pycache__", "node_modules", ".venv", "venv", "env", ".env", ".tox", ".nox",
             "site-packages", "build", "dist", ".eggs", ".mypy_cache", ".pytest_cache", "tests", "test", "testing",
             "docs", "docs_src", "doc", "examples", "benchmarks"}


def is_test_file(name):
    return name == "conftest.py" or name.startswith("test_") or name.endswith("_test.py")


def resolve(root, arg):
    """A path (relative to cwd or the repo) or a package name (a.b -> a/b, also under src/ and lib/)."""
    if not arg:
        return root
    for base in (os.getcwd(), root):
        p = os.path.normpath(os.path.join(base, arg))
        if os.path.exists(p):
            return p
    rel = arg.replace(".", os.sep)
    for base in ("", "src", "lib"):
        for cand in (os.path.join(root, base, rel), os.path.join(root, base, rel + ".py")):
            if os.path.exists(cand):
                return cand
    return None


def py_files(target):
    if os.path.isfile(target):
        return [target]
    out = []
    for dp, dns, fns in os.walk(target):
        dns[:] = sorted(d for d in dns if d not in SKIP_DIRS and not d.endswith(".egg-info")
                        and not os.path.isfile(os.path.join(dp, d, "pyvenv.cfg")))
        out += [os.path.join(dp, f) for f in sorted(fns) if f.endswith(".py") and not is_test_file(f)]
    return out


def sig(node):
    a = ast.unparse(node.args)
    s = f"{node.name}({a})" + (f" -> {ast.unparse(node.returns)}" if node.returns else "")
    return s if len(s) <= SIG else s[:SIG - 3] + "..."


def top_defs(body):
    """Top-level defs, including those inside module-level if/try blocks (version and TYPE_CHECKING switches)."""
    for n in body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield n
        elif isinstance(n, ast.If):
            yield from top_defs(n.body); yield from top_defs(n.orelse)
        elif isinstance(n, ast.Try):
            for b in (n.body, n.orelse, n.finalbody, *[h.body for h in n.handlers]):
                yield from top_defs(b)


def file_block(path, rel, terms):
    """Lines for one file, or None when nothing in it matches; raises SyntaxError/ValueError on a broken file."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        src = fh.read()
    low = src.lower()
    path_hit = bool(terms) and any(t in rel.lower() for t in terms)
    if terms and not path_hit and not any(t in low for t in terms):
        return None
    hit = lambda name: not terms or path_hit or any(t in name.lower() for t in terms)
    lines, names = [], []
    for n in sorted(top_defs(ast.parse(src).body), key=lambda d: d.lineno):
        if isinstance(n, ast.ClassDef):
            meths = [m for m in n.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))]
            shown = meths if hit(n.name) else [m for m in meths if hit(m.name)]
            if not hit(n.name) and not shown:
                continue
            bases = ", ".join(ast.unparse(b) for b in n.bases + n.keywords)
            head = f"  {n.lineno} class {n.name}" + (f"({bases})" if bases else "")
            if len(head) > SIG + 20:
                head = head[:SIG + 17] + "..."
            meth = [("async " if isinstance(m, ast.AsyncFunctionDef) else "") + f"{m.name}:{m.lineno}" for m in shown]
            extra = ""
            if not terms and len(meth) > METHODS:
                extra = f" +{len(meth) - METHODS} more"; meth = meth[:METHODS]
            lines.append(head + (": " + " ".join(meth) + extra if meth else ""))
            if terms and not any(t in n.name.lower() for t in terms) and not path_hit:
                names += [f"{n.name}.{m.name}:{m.lineno}" for m in shown]
            else:
                names.append(f"{n.name}:{n.lineno}" + (f"({len(shown)}m)" if shown else ""))
        elif hit(n.name):
            kw = "async def" if isinstance(n, ast.AsyncFunctionDef) else "def"
            lines.append(f"  {n.lineno} {kw} {sig(n)}")
            names.append(f"{n.name}:{n.lineno}")
    if not lines:
        return None
    more = f" +{len(names) - NAMES}" if len(names) > NAMES else ""
    return [rel] + lines, f"{rel}: " + " ".join(names[:NAMES]) + more


def main(argv):
    terms, pos, i = [], [], 0
    while i < len(argv):
        if argv[i] == "--grep" and i + 1 < len(argv):
            terms += [t.strip().lower() for t in argv[i + 1].replace(",", "|").split("|") if t.strip()]; i += 2
        elif argv[i].startswith("--grep="):
            terms += [t.strip().lower() for t in argv[i][7:].replace(",", "|").split("|") if t.strip()]; i += 1
        else:
            pos.append(argv[i]); i += 1
    root = ws()
    if not os.path.isdir(root):
        root = os.getcwd()
    target = resolve(root, pos[0] if pos else "")
    if target is None:
        print(f"no path or package {pos[0]!r}; mapping the whole repository")
        target = root
    base = root if os.path.realpath(target).startswith(os.path.realpath(root)) else os.path.dirname(target)
    paths = sorted(py_files(target), key=lambda p: os.path.relpath(p, base).split(os.sep))
    blocks, broken = [], []
    for p in paths:
        rel = os.path.relpath(p, base).replace(os.sep, "/")
        try:
            b = file_block(p, rel, terms)
        except (SyntaxError, ValueError, RecursionError, OSError):
            broken.append(rel); continue
        if b:
            blocks.append(b)
    out, used = [], 0
    tail = f"(skipped, syntax errors: {', '.join(broken[:5])}{' ...' if len(broken) > 5 else ''})" if broken else ""
    budget = CAP - len(tail) - 80
    if len(blocks) == 1 and sum(len(x) + 1 for x in blocks[0][0]) > budget:   # one file over budget: its head
        b = blocks[0][0]
        for line in b:
            if used + len(line) + 1 > budget:
                break
            out.append(line); used += len(line) + 1
        out.append(f"... {len(b) - len(out)} more symbols in {b[0]}, narrow with PATH or --grep")
    else:
        full = sum(len(x) + 1 for b, _ in blocks for x in b) <= budget
        if not full:
            out.append("(names only, NAME:line (Nm = N methods); narrow with PATH or --grep for signatures)")
            used = len(out[0]) + 1
        for k, (b, compact) in enumerate(blocks):
            text = "\n".join(b) if full else compact
            if used + len(text) + 1 > budget:
                out.append(f"... {len(blocks) - k} more files, narrow with PATH or --grep")
                break
            out.append(text); used += len(text) + 1
    if not blocks:
        out.append("no matching classes or functions" + (f" for --grep {'|'.join(terms)}" if terms else ""))
    if tail:
        out.append(tail)
    print("\n".join(out)[:CAP - 1])


if __name__ == "__main__":
    main(sys.argv[1:])
