"""File recall@k of the shipped locator on heldout1k (GAPS N1, 2026-10-06). Free: CPU only, no model calls.

Two arms per task, same locator, same snapshot:
  query  deterministic approximation of what prompts/locator.md tells the model to pass ("identifiers, error text and
         keywords from the issue", leaving out URLs, version numbers, environment dumps and doc links). It is NOT the
         model's actual query; it is a fixed, reproducible stand-in for it.
  raw    the problem statement itself (first 4,000 chars), as eval/locate_recall.py does on the public tasks.
The shipped locate.py prints its top 8 files; a temp copy with the cut-off raised to 10 is run so R@10 exists (ranking
is unchanged). Rank = best rank of any gold-patch .py file; None = not in the top 10 or no .py file in the gold patch.

  .venv/bin/python eval/locate_recall_heldout.py --ids data/heldout1k/all_valid_ids.txt --out rows.jsonl
  .venv/bin/python eval/locate_recall_heldout.py --summarize rows.jsonl [--public rows74.jsonl]
"""
import argparse, collections, concurrent.futures as cf, gzip, json, os, re, shutil, statistics, subprocess, sys, \
    tarfile, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCATOR = ROOT / "submissions" / "v5h2" / "skills" / "swe-tools" / "scripts" / "locate.py"
MAX_QUERY_CHARS = 300
TOPN = 10
KS = (1, 3, 5, 10)

STOP = set("""fix fixes fixed fixing issue issues github com https http www the and for with are this that its from not
bug feature new add added adds adding support update updated use used using when should would could can may might will
pr pull request type changes change checklist run latest tests test docs documentation docstrings other please make sure
thanks thank you see also closes close resolve resolves resolved version release none true false self return returns
was were been being have has had does did doing but than then there here what which who whom why how all any some
such only own same too very just into over under again further once about above below between both each few more most
off out because until while also like get gets got want wants need needs think expected actual behavior behaviour
reproduce steps example code following error errors work works working problem currently instead still now one two
however since would they them their our your mine yours his her him she let lets via etc file files line lines
case cases way able something anything nothing get set ref refs related description summary additional context""".split())

ENV_LINE = re.compile(
    r"^\s*[-*>]?\s*(\*\*)?(python|os|platform|operating system|version|versions|environment|env|pip|conda|"
    r"sys\.version|installed|package versions?|distro|kernel|uname|cpu|arch)\b[^\n]*\d", re.I)
PIN_LINE = re.compile(r"^\s*[-*]?\s*[A-Za-z0-9_.\-\[\]]+\s*(==|>=|<=|~=)\s*\d[^\s]*\s*$|^\s*[A-Za-z0-9_.\-]+\s{2,}v?\d+(\.\d+)+\S*\s*$")
URL = re.compile(r"(https?|ftp)://\S+|www\.\S+")
MDLINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
VERSION = re.compile(r"\bv?\d+(\.\d+)+[A-Za-z0-9]*\b")
FRAME = re.compile(r'File "([^"]+)", line \d+(?:, in (\w+))?')
EXC_LINE = re.compile(r"^\s*([A-Za-z_][\w.]*(?:Error|Exception|Warning|Exit|Interrupt))\s*:\s*(.*)$", re.M)
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
WORD = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")


def gold_files(patch, py_only=False):
    fs = [f for f in re.findall(r"^\+\+\+ b/(\S+)", patch or "", re.M)]
    return [f for f in fs if f.endswith(".py")] if py_only else fs


def _is_identifier_like(tok):
    """snake_case, CamelCase, dotted names, file names, exception names: the 'code identifiers' of the prompt."""
    return ("_" in tok or "." in tok or re.search(r"[a-z][A-Z]", tok) or re.match(r"[A-Z][a-z]+[A-Z]", tok)
            or re.search(r"(Error|Exception|Warning)$", tok)) and not tok.lower() in STOP


def _norm_line(l):
    return re.sub(r"\s+", " ", l).strip().lower()


def boilerplate_lines(tasks, share=0.15, floor=3):
    """Per repo, the (normalised) lines that recur in >= max(floor, share * n) statements: PR/issue template text the
    model would not copy into a query. Data-driven, so it needs the whole task file, not one statement."""
    by = collections.defaultdict(list)
    for t in tasks: by[t["repo"]].append({_norm_line(l) for l in (t.get("problem_statement") or "").splitlines()} - {""})
    out = {}
    for repo, sets in by.items():
        c = collections.Counter(l for s in sets for l in s); cut = max(floor, share * len(sets))
        out[repo] = {l for l, n in c.items() if n >= cut}
    return out


def clean_statement(s, boiler=None):
    s = re.sub(r"<!--.*?-->", " ", s or "", flags=re.S)
    s = MDLINK.sub(lambda m: m.group(1), s)  # doc links: keep the link text, drop the target
    s = URL.sub(" ", s)
    lines = [l for l in s.splitlines() if _norm_line(l) not in (boiler or ()) and not ENV_LINE.match(l) and not PIN_LINE.match(l)
             and not re.match(r"\s*(- \[[ xX]\]|#+\s*(type of changes|checklist|related issues?)\b)", l, re.I)]
    return VERSION.sub(" ", "\n".join(lines))


def extract_query(statement, boiler=None):
    """Deterministic stand-in for the model's locate.py query: identifiers first, then error text, then keywords."""
    s = clean_statement(statement, boiler)
    tiers = [[], [], []]
    for m in re.finditer(r"`([^`\n]+)`", s):  # backticked code spans
        tiers[0] += [t for t in IDENT.findall(m.group(1)) if len(t) > 2 and t.lower() not in STOP]
    for path, fn in FRAME.findall(s):  # traceback frames: file basename + function
        tiers[0].append(os.path.basename(path))
        if fn and fn != "<module>": tiers[0].append(fn)
    for exc, msg in EXC_LINE.findall(s):  # error text
        tiers[0].append(exc.split(".")[-1])
        tiers[1] += [w for w in WORD.findall(msg) if w.lower() not in STOP]
    for t in IDENT.findall(s):
        t = t.strip(".")
        if len(t) > 2 and _is_identifier_like(t): tiers[0].append(t)
    tiers[2] += [w for w in WORD.findall(s) if w.lower() not in STOP and not w.isdigit()]
    out, seen, n = [], set(), 0
    for tier in tiers:
        for t in tier:
            if t in seen or t.lower() in STOP: continue
            if n + len(t) + (1 if out else 0) > MAX_QUERY_CHARS: continue
            seen.add(t); out.append(t); n += len(t) + (1 if len(out) > 1 else 0)
    return " ".join(out)


def ranked_files(stdout):
    return re.findall(r"^\d+\. (\S+)", stdout, re.M)


def recall(ranks, ks=KS):
    n = len(ranks) or 1
    return {k: round(sum(1 for r in ranks if r is not None and r <= k) / n, 4) for k in ks}


def locator_copy(dst):
    """The shipped locator with its print cut-off raised from 8 to TOPN; everything else byte-identical."""
    src = LOCATOR.read_text()
    assert src.count("[:8]") == 1, "locate.py changed: re-check the top-N patch"
    Path(dst).mkdir(parents=True, exist_ok=True)
    shutil.copy(LOCATOR.parent / "_ws.py", Path(dst) / "_ws.py")
    p = Path(dst) / "locate.py"; p.write_text(src.replace("[:8]", f"[:{TOPN}]")); return p


def _run_locator(loc, root, query):
    t0 = time.perf_counter()
    r = subprocess.run([sys.executable, str(loc), "--query", query], capture_output=True, text=True, timeout=300,
                       env={**os.environ, "SWE_WS": root, "PYTHONDONTWRITEBYTECODE": "1"})
    return ranked_files(r.stdout), round(time.perf_counter() - t0, 3), r.returncode


def _rank(ranked, gold):
    return min((ranked.index(g) + 1 for g in gold if g in ranked), default=None)


def run_task(t, snapdir, loc, tmp, boiler=None):
    gold = gold_files(t["patch"], py_only=True)
    row = dict(id=t["instance_id"], repo=t["repo"], title_only=t.get("statement_title_only") in (True, "True", "true"), n_gold=len(gold_files(t["patch"])), n_gold_py=len(gold))
    snap = Path(snapdir) / f"{t['instance_id']}.tgz"
    if not snap.exists():
        row["error"] = "no snapshot"; return row
    d = tempfile.mkdtemp(dir=tmp)
    try:
        with tarfile.open(snap) as tf:
            tf.extractall(d, filter="data") if sys.version_info >= (3, 12) else tf.extractall(d)
        root = d if os.path.isdir(os.path.join(d, ".git")) else next(
            (os.path.join(d, x) for x in os.listdir(d) if os.path.isdir(os.path.join(d, x, ".git"))), d)
        q = extract_query(t["problem_statement"], boiler)
        for arm, text in (("query", q), ("raw", t["problem_statement"][:4000])):
            ranked, secs, rc = _run_locator(loc, root, text)
            row[f"rank_{arm}"] = _rank(ranked, gold); row[f"secs_{arm}"] = secs; row[f"rc_{arm}"] = rc
        row["query"] = q
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return row


def load_tasks(path):
    p = Path(path)
    if not p.exists() and Path(str(p) + ".gz").exists():
        return [json.loads(l) for l in gzip.open(str(p) + ".gz", "rt")]
    return [json.loads(l) for l in open(p)]


def main_run(a):
    ids = set(Path(a.ids).read_text().split()) if a.ids else None
    alltasks = load_tasks(a.tasks); boiler = boilerplate_lines(alltasks)  # from the whole file, not the id subset
    tasks = [t for t in alltasks if ids is None or t["instance_id"] in ids]
    Path(a.tmp).mkdir(parents=True, exist_ok=True)
    done = set()
    if a.resume and Path(a.out).exists():
        done = {json.loads(l)["id"] for l in open(a.out)}
    tasks = [t for t in tasks if t["instance_id"] not in done]
    with tempfile.TemporaryDirectory() as ld:
        loc = locator_copy(ld)
        with open(a.out, "a" if a.resume else "w") as fo, cf.ThreadPoolExecutor(a.jobs) as ex:
            for i, row in enumerate(ex.map(lambda t: run_task(t, a.snapshots, loc, a.tmp, boiler.get(t["repo"])), tasks), 1):
                fo.write(json.dumps(row) + "\n"); fo.flush()
                if i % 50 == 0: print(f"{i}/{len(tasks)}", flush=True)


def table(rows, arm, label):
    r = [x.get(f"rank_{arm}") for x in rows]; rec = recall(r)
    return f"| {label} | {len(rows)} | " + " | ".join(f"{rec[k]:.3f}" for k in KS) + " |"


def summarize(path, public=None):
    rows = [json.loads(l) for l in open(path)]
    ok = [x for x in rows if "error" not in x]
    py = [x for x in ok if x["n_gold_py"] > 0]
    out = [f"rows={len(rows)} errors={len(rows) - len(ok)} no_py_gold={len(ok) - len(py)}", ""]
    hdr = "| slice | n | R@1 | R@3 | R@5 | R@10 |\n|---|---|---|---|---|---|"
    for arm in ("query", "raw"):
        out += [f"### arm={arm}", hdr, table(ok, arm, "all tasks (no .py gold = miss)"), table(py, arm, "tasks with .py gold"),
                table([x for x in py if x["title_only"]], arm, "title-only statements"),
                table([x for x in py if not x["title_only"]], arm, "full statements")]
        if public:
            pr = [json.loads(l) for l in open(public)]; pr = [x for x in pr if "error" not in x and x["n_gold_py"] > 0]
            out.append(table(pr, arm, "public 74 (same script)"))
        secs = [x[f"secs_{arm}"] for x in ok]
        out += [f"median secs {statistics.median(secs):.2f}, p90 {sorted(secs)[int(.9 * len(secs))]:.2f}, "
                f"max {max(secs):.2f}; rc!=0: {sum(x[f'rc_{arm}'] != 0 for x in ok)}", ""]
    out += ["### by repo (tasks with .py gold)", "| repo | n | query R@1 | R@3 | R@5 | R@10 | raw R@1 | R@3 | R@5 | R@10 |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    by = collections.defaultdict(list)
    for x in py: by[x["repo"]].append(x)
    for repo, xs in sorted(by.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        q = recall([x["rank_query"] for x in xs]); w = recall([x["rank_raw"] for x in xs])
        out.append(f"| {repo} | {len(xs)} | " + " | ".join(f"{q[k]:.2f}" for k in KS) + " | "
                   + " | ".join(f"{w[k]:.2f}" for k in KS) + " |")
    return "\n".join(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=str(ROOT / "data/heldout1k/tasks.jsonl"))
    ap.add_argument("--snapshots", default=str(ROOT / "data/heldout1k/harness_all/snapshots"))
    ap.add_argument("--ids"); ap.add_argument("--out"); ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--tmp", default=tempfile.gettempdir() + "/locate_recall_heldout")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--summarize"); ap.add_argument("--public")
    a = ap.parse_args()
    if a.summarize: print(summarize(a.summarize, a.public))
    else: main_run(a)
