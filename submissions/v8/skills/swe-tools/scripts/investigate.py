"""One-call repository investigation: ranked files + exact identifier hits + code of the top symbols + tests to run.
Replaces many exploratory tool calls. Searches run in parallel threads; output stays under the harness's 5,000-char cap.
Usage: python3 /tmp/swe/investigate.py "<issue title and key identifiers / error text>" """
import os, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ws import ws
import repoindex as ri
BUDGET = 4700
q = " ".join(a for a in sys.argv[1:] if a not in ("--", "--query"))
if not q: q = sys.stdin.read() if not sys.stdin.isatty() else ""
ROOT = ws(); ids = ri.identifiers(q)
def grep(word):
    last = word.split(".")[-1]
    r = subprocess.run(["git", "grep", "-n", "-w", "-I", "--", last, "*.py"], cwd=ROOT, capture_output=True, text=True)
    hits = [l for l in r.stdout.splitlines() if not ri.is_test(l.split(":", 1)[0])]
    defs = [l for l in hits if re.search(rf"(def|class)\s+{re.escape(last)}\b", l)]
    return word, defs[:3], hits[:40]
with ThreadPoolExecutor(max_workers=4) as ex:
    fut_idx = ex.submit(ri.build, ROOT)
    greps = list(ex.map(grep, ids))
    idx = fut_idx.result()
def_files = {l.split(":", 1)[0] for _, defs, _ in greps for l in defs}
hit_files = {l.split(":", 1)[0] for _, _, hits in greps for l in hits}
files = ri.rank(idx, q, boost_files=def_files | hit_files)
out = [f"ISSUE IDENTIFIERS: {', '.join(ids) or '(none found; ranking by keywords)'}"]
for w, defs, hits in greps:
    if defs: out.append(f"  defined: {w} -> " + "; ".join(d.split(':')[0] + ':' + d.split(':')[1] for d in defs))
    elif hits: out.append(f"  used: {w} -> {len(hits)} hits, e.g. {hits[0][:110]}")
out.append("LIKELY FILES:")
for i, (f, lst) in enumerate([x for x in files if not x[1][0][1][5]][:6]):
    syms = ", ".join(f"{d[1]} L{d[2]}-{d[3]}" for s, d in lst[:3] if d[1] != "<module>")
    out.append(f"{i+1}. {f}  {syms}")
top = [d for f, lst in [x for x in files if not x[1][0][1][5]][:2] for s, d in lst[:1] if d[1] != "<module>"]
for d in top:
    try:
        lines = open(os.path.join(ROOT, d[0]), encoding="utf-8", errors="ignore").read().splitlines()
        own = set(d[1].split("."))
        keys = [k for k in ([w.split(".")[-1] for w in ids] or re.findall(r"[A-Za-z_]\w{3,}", q)[:8]) if k not in own]
        hit = next((n for n in range(d[2], d[3] + 1) if n <= len(lines) and any(re.search(rf"\b{re.escape(k)}\b", lines[n-1]) for k in keys)), d[2])
        a = max(d[2], hit - 12); b = min(d[3], a + 35)
        body = "\n".join(f"{n}: {lines[n-1]}" for n in range(a, b + 1))
        out.append(f"--- {d[0]} {d[1]} (L{a}-{b} of L{d[2]}-{d[3]})\n{body}")
    except Exception: pass
tests = []
for f, lst in files[:3]:
    if lst[0][1][5]: continue
    stem = os.path.splitext(os.path.basename(f))[0].lstrip("_")
    r = subprocess.run(["git", "ls-files", f"*test*{stem}*.py", f"*{stem}*test*.py"], cwd=ROOT, capture_output=True, text=True)
    tests += [t for t in r.stdout.split() if ri.is_test(t) and t not in tests]
out.append("TESTS TO RUN: " + (" ".join(tests[:4]) if tests else "(none found; git grep -ln <symbol> -- tests)"))
text = "\n".join(out)
print(text if len(text) <= BUDGET else text[:BUDGET] + "\n...[trimmed]")
