"""Rebuild SWE-Pallets-X problem statements in the competition's format: PR title + "\\n\\n" + PR body.

  python3 scripts/pallets/pr_statements.py [-j 8]

Why: the competition's problem_statement is exactly `title + "\\n\\n" + body` of the task's pull request (checked
against GitHub for rich_3063, rich_4075, fastapi_14479, fastapi_15661, requests_6644: 5/5 byte-identical, 2026-09-30),
while the dataset's pipeline (pipeline/pipeline/enrich.py) prefers the LINKED ISSUE's title and body when the PR body
says "fixes #N". Needs `gh` (authenticated, public reads only). Uses the dataset's pr_number.
Writes data/pallets/pr_statements.json ({tid: {pr, title, body, same_as_dataset}}, or {error}) and
data/pallets/tasks_prstyle.jsonl (tasks.jsonl with problem_statement replaced where the PR was found).
"""
import argparse
import concurrent.futures as cf
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAL = ROOT / "data" / "pallets"


def fetch(row):
    tid, repo, n = row["instance_id"], row["repo"], row.get("pr_number")
    if not n:
        return tid, {"error": "no pr_number"}
    p = subprocess.run(["gh", "api", f"repos/{repo}/pulls/{n}", "--jq", "{title: .title, body: .body}"],
                       capture_output=True, text=True)
    if p.returncode != 0:
        return tid, {"pr": n, "error": (p.stderr or p.stdout)[-200:]}
    d = json.loads(p.stdout)
    stmt = d["title"] + "\n\n" + (d["body"] or "")
    return tid, {"pr": n, "title": d["title"], "body": d["body"] or "",
                 "same_as_dataset": stmt == row["problem_statement"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-j", type=int, default=8)
    a = ap.parse_args()
    rows = [json.loads(ln) for ln in open(PAL / "tasks.jsonl") if ln.strip()]
    out = {}
    with cf.ThreadPoolExecutor(a.j) as ex:
        for tid, rec in ex.map(fetch, rows):
            out[tid] = rec
    (PAL / "pr_statements.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    n_ok = 0
    with open(PAL / "tasks_prstyle.jsonl", "w") as fh:
        for r in rows:
            rec = out[r["instance_id"]]
            if "title" in rec:
                r = dict(r, problem_statement=rec["title"] + "\n\n" + rec["body"])
                n_ok += 1
            fh.write(json.dumps(r) + "\n")
    same = sum(1 for v in out.values() if v.get("same_as_dataset"))
    print(f"pr_statements: {n_ok}/{len(rows)} fetched, {same} identical to the dataset statement, "
          f"{sum(1 for v in out.values() if 'error' in v)} errors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
