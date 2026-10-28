"""Why 27 public tasks were never solved by any of the 2,442 agent runs (eval/analysis/out/task_reach.json): per task,
the gold patch's size, names the hidden tests use that the issue never mentions, URL-only statements, and how often runs
edited a gold file at all. Read with the forum threads on unsolvable-from-the-prompt tasks (745855) and URL-only tasks
(746944).

    python eval/analysis/never_solved.py [--json eval/analysis/out/never_solved.json]
"""
import argparse, collections, glob, json, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FILE_RE = re.compile(r"^(?:diff --git a/|\+\+\+ b/)(\S+)", re.M)
IMPORT_RE = re.compile(r"^\+\s*from\s+[\w.]+\s+import\s+\(?([\w ,\n]+)\)?", re.M)
URL_RE = re.compile(r"https?://\S+")


def added_names(test_patch):
    names = set()
    for m in IMPORT_RE.finditer(test_patch or ""):
        names |= {n.strip() for n in m.group(1).replace("\n", ",").split(",") if n.strip().isidentifier()}
    return names


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    tasks = {}
    for line in open(os.path.join(ROOT, "data/tasks.jsonl")):
        t = json.loads(line)
        tasks[t["instance_id"]] = t
    reach = json.load(open(os.path.join(ROOT, "eval/analysis/out/task_reach.json")))
    touched = collections.defaultdict(lambda: [0, 0])          # runs that edited a gold file / runs with a patch
    for rj in glob.glob(os.path.join(ROOT, "eval/kaggle/*/results.jsonl")) + glob.glob(os.path.join(ROOT, "eval/a6000/results/*/results.jsonl")):
        if "oracle" in rj or "rescore" in rj:
            continue
        for line in open(rj):
            r = json.loads(line)
            t = tasks.get(r.get("id"))
            if not t or not (r.get("patch") or "").strip():
                continue
            gold = set(FILE_RE.findall(t["patch"]))
            touched[r["id"]][1] += 1
            touched[r["id"]][0] += bool(gold & set(FILE_RE.findall(r["patch"])))
    rows = []
    for tid in reach["never"]:
        t = tasks[tid]
        st = t.get("problem_statement") or ""
        gold_files = sorted(set(FILE_RE.findall(t["patch"])))
        plus = sum(1 for l in t["patch"].splitlines() if l.startswith("+") and not l.startswith("+++"))
        minus = sum(1 for l in t["patch"].splitlines() if l.startswith("-") and not l.startswith("---"))
        unmentioned = sorted(n for n in added_names(t.get("test_patch")) if n not in st and len(n) > 3)
        new_defs = sorted(n for n in unmentioned if re.search(rf"^\+\s*(def|class)\s+{re.escape(n)}\b|^\+\s*{re.escape(n)}\s*=", t["patch"], re.M))
        url_only = bool(URL_RE.search(st)) and len(URL_RE.sub("", st).split()) < 25
        hit, n = touched[tid]
        cls = ("url_only" if url_only else "hidden_names" if new_defs else
               "large_fix" if plus + minus > 60 or len(gold_files) > 3 else "never_localized" if n and hit / n < 0.2 else "hard")
        rows.append(dict(id=tid, cls=cls, statement_chars=len(st), gold_files=len(gold_files), lines=plus + minus,
                         new_names_not_in_issue=new_defs[:6], runs_with_patch=n, gold_file_hit=round(hit / n, 2) if n else None))
    rows.sort(key=lambda r: (r["cls"], r["id"]))
    for r in rows:
        print(f"{r['id']:16s} {r['cls']:16s} chars {r['statement_chars']:5d}  gold files {r['gold_files']}  lines {r['lines']:4d}  "
              f"gold-file hit {r['gold_file_hit']}  new names {','.join(r['new_names_not_in_issue'])}")
    print(dict(collections.Counter(r["cls"] for r in rows)))
    if a.json:
        json.dump(rows, open(a.json, "w"), indent=1)


if __name__ == "__main__":
    main()
