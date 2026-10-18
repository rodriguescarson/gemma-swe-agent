"""Chronology of every paper claim (eval/analysis/claims.json): for a pre-registered claim, the commit that first added its
GAPS section must be an ancestor of the commit that first added each of its result paths, and older than each Kaggle
submission it reads; observed claims are listed as post hoc. Pending results are reported, not failed.
    python eval/analysis/check_claims.py > eval/analysis/out/claims_chronology.md     (exit 1 on any order violation)"""
import glob, json, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GAPS = "docs/GAPS_2026-10-06.md"


def git(*a):
    return subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True).stdout.strip()


def first_commit_adding(text=None, path=None, rule_file=GAPS):
    args = ["log", "--reverse", "--format=%H %ct"] + (["-S", text, "--", rule_file] if text else ["--diff-filter=A", "--", path])
    line = (git(*args).splitlines() or [""])[0]
    return (line.split()[0], int(line.split()[1])) if line else (None, None)


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%MZ")


def main():
    spec = json.loads((ROOT / "eval/analysis/claims.json").read_text())
    subs = {s["ref"]: s for s in json.load(open(sorted(glob.glob(str(ROOT / "eval/analysis/out/kaggle_submissions_*.json")))[-1]))["submissions"]}
    bad = 0
    print("| claim | kind | rule commit | results (first commit) | order |\n|---|---|---|---|---|")
    for cid, c in spec["claims"].items():
        rc, rt = first_commit_adding(text=c["rule"], rule_file=c.get("rule_file", GAPS)) if c["rule"] else (None, None)
        if c["rule"] and not rc:
            print(f"| {cid} | {c['kind']} | NOT FOUND: {c['rule']!r} | | FAIL |"); bad += 1; continue
        cells, verdicts = [], []
        for p in c.get("results", []):
            h, t = first_commit_adding(path=p)
            if not h:
                cells.append(f"{p.split('/')[-1]}: pending"); verdicts.append("pending"); continue
            ok = rc is None or subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", rc, h]).returncode == 0
            cells.append(f"{p.split('/')[-1]}: {h[:8]} {iso(t)}"); verdicts.append("ok" if ok else "VIOLATION")
        for ref in c.get("kaggle", []):
            s = subs.get(ref)
            if not s:
                cells.append(f"kaggle {ref}: not in snapshot"); verdicts.append("pending"); continue
            st = datetime.fromisoformat(s["date"]).replace(tzinfo=timezone.utc).timestamp()
            ok = rt is None or rt < st
            cells.append(f"kaggle {ref}: {iso(st)}"); verdicts.append("ok" if ok else "VIOLATION")
        v = "FAIL" if "VIOLATION" in verdicts else ("pending" if "pending" in verdicts else ("post hoc" if rc is None else "ok"))
        bad += v == "FAIL"
        rule = f"{rc[:8]} {iso(rt)}" if rc else "none (observed)"
        print(f"| {cid} | {c['kind']} | {rule} | {'; '.join(cells)} | {v} |")
    print("\nExceptions (disclosed in-place edits):")
    for e in spec["exceptions"]:
        print(f"- {e['commit']}: {e['what']} (commit date {git('show', '-s', '--format=%ci', e['commit'])})")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
