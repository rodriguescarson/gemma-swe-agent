"""Offline evidence for a title-to-identifier search: for public tasks whose title names no identifier, join the title's words
two at a time (any order, optional underscore, case-insensitive, so word_word and WordWord both match) and git grep the
task's base snapshot for them in non-test .py files, the one command the lever asks for. Reports how many files it hits and
where the gold source files rank (by matching lines). Extracts each snapshot into $WT/<id>, then deletes it.

    [SNAPSHOTS=<dir>] .venv/bin/python scripts/forty_two/rich_solve/ev_titlegrep.py $WT [ids...]   (default: every
    public task whose title has no identifier; appends one JSON line per task to $WT/titlegrep.jsonl)"""
import json, os, re, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SNAP = Path(os.environ.get("SNAPSHOTS", str(ROOT / "data/raw/snapshots")))
STOP = set("""the and for with when from into not are can was has its this that than then also only fix fixes fixed add adds
added support supports update updates use uses allow allows make makes handle handles handling improve improves improved
don does should would could new bug issue error errors problem correct correctly properly wrong missing""".split())
IDENT = re.compile(r"`|\w+_\w+|[a-z][A-Z]|[A-Z][a-z]+[A-Z]|\w\.\w|\w\(")


def title(t):
    return t["problem_statement"].strip().split("\n")[0]


def words(ttl):
    ws = [w.lower() for w in re.findall(r"[A-Za-z]{3,}", ttl)]
    out = []
    for w in ws:
        if w not in STOP and w not in out:
            out.append(w)
    return out


def gold_files(t):
    return sorted(set(re.findall(r"^\+\+\+ b/(\S+\.py)", t["patch"], re.M)))


def main():
    wt_root = Path(sys.argv[1])
    valid = set((ROOT / "data/kaggle_valid_ids.txt").read_text().split())
    never = set((ROOT / "data/never_solved_box5_ids.txt").read_text().split())
    tasks = {json.loads(l)["instance_id"]: json.loads(l) for l in open(ROOT / "data/tasks.jsonl") if l.strip()}
    ids = sys.argv[2:] or sorted(i for i in valid if not IDENT.search(title(tasks[i])))
    out = open(wt_root / "titlegrep.jsonl", "a")
    for i in ids:
        t = tasks[i]
        ws = words(title(t))
        rec = dict(id=i, in_42=i in never, title=title(t), words=ws, gold=gold_files(t))
        if len(ws) < 2 or not (SNAP / f"{i}.tgz").exists():
            rec["skipped"] = "fewer than 2 words" if len(ws) < 2 else "no snapshot"
        else:
            wt = wt_root / i
            wt.mkdir(parents=True, exist_ok=True)
            subprocess.run(["tar", "-xzf", str(SNAP / f"{i}.tgz"), "-C", str(wt)], check=True)
            alt = "|".join(ws)
            pat = f"({alt})_?({alt})"
            r = subprocess.run(["git", "grep", "-c", "-i", "-E", pat, "--", "*.py", ":!tests", ":!test", ":!docs", ":!docs_src"],
                               cwd=wt, capture_output=True, text=True, timeout=60)
            counts = {}
            for line in r.stdout.splitlines():
                f, _, n = line.rpartition(":")
                # a pair of the same word (inlineinline) is noise; keep files only if a distinct pair matches
                counts[f] = int(n)
            distinct = {}
            for f in counts:
                lines = subprocess.run(["git", "grep", "-h", "-o", "-i", "-E", pat, "--", f], cwd=wt, capture_output=True,
                                       text=True, timeout=60).stdout.lower().split()
                ok = [m for m in lines if len({w for w in ws if w in m}) >= 2]
                if ok:
                    distinct[f] = len(ok)
            ranked = sorted(distinct, key=lambda f: (-distinct[f], f))
            rec.update(pattern=pat, files_hit=len(ranked), top=ranked[:5],
                       gold_rank=[ranked.index(g) + 1 if g in ranked else None for g in rec["gold"]])
            shutil.rmtree(wt)
        out.write(json.dumps(rec, ensure_ascii=False) + "\n")
        out.flush()
        print(json.dumps({k: rec[k] for k in rec if k not in ("pattern",)}, ensure_ascii=False)[:300])


if __name__ == "__main__":
    main()
