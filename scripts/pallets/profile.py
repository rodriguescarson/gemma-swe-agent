"""Profile task sets (statement style, gold patch size, test style) for research/pallets.md.

  python3 scripts/pallets/profile.py [--valid data/pallets/valid_ids.txt] > data/pallets/profile.json
Groups: competition 74 (data/kaggle_valid_ids.txt), competition 129, pallets repos (all, and valid when --valid given:
pallets_valid = every valid task, pallets_valid_org = the pallets-org repos only (no sympy), and the same with the PR-style
statements of data/pallets/tasks_prstyle.jsonl, overall and per repo).
Every number is computed from the tasks.jsonl text only (no snapshot needed).
"""
import argparse
import json
import re
import statistics as st
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(p):
    return [json.loads(line) for line in open(p, encoding="utf-8") if line.strip()]


def patch_stats(p):
    files = re.findall(r"^\+\+\+ b/(\S+)", p, re.M)
    new = len(re.findall(r"^--- /dev/null", p, re.M))
    add = sum(1 for ln in p.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
    rem = sum(1 for ln in p.splitlines() if ln.startswith("-") and not ln.startswith("---"))
    hunks = len(re.findall(r"^@@ ", p, re.M))
    return {"files": len(files), "new_files": new, "added": add, "removed": rem, "changed": add + rem, "hunks": hunks}


URL_ONLY = re.compile(r"^\s*(fix(es|ed)?|close[sd]?|resolve[sd]?|refs?)\b[^\n]*(https?://|#\d+)", re.I)


def statement_stats(s):
    body = s.strip()
    lines = [ln for ln in body.splitlines() if ln.strip()]
    rest = "\n".join(lines[1:])
    # a statement whose body (after the title) is only issue references / checklist boilerplate
    prose = re.sub(r"<!--.*?-->", "", rest, flags=re.S)
    prose = "\n".join(ln for ln in prose.splitlines()
                      if ln.strip() and not URL_ONLY.match(ln.strip().lstrip("-* "))
                      and not re.match(r"^\s*[-*]\s*\[[ xX]\]", ln))
    return {
        "chars": len(body),
        "words": len(body.split()),
        "title_only": len(prose.strip()) < 40,
        "code_block": "```" in body,
        "traceback": "Traceback (most recent call last)" in body,
        "py_path": bool(re.search(r"[\w/]+\.py\b", body)),
        "checklist": bool(re.search(r"^\s*[-*]\s*\[[ xX]\]", body, re.M)),
        "pr_voice": bool(re.search(r"\b(this pr|this pull request|i (have )?(added|changed|updated|fixed)|"
                                   r"## pull request|fixes #|fixes https://github\.com/[^\s]+/issues/)", body, re.I)),
        "issue_link": bool(re.search(r"(#\d+|github\.com/[^\s]+/(issues|pull)/\d+)", body)),
    }


def test_stats(tp):
    added_tests = re.findall(r"^\+\s*(?:async\s+)?def\s+(test_\w+)", tp, re.M)
    return {
        "test_files": len(re.findall(r"^\+\+\+ b/(\S+)", tp, re.M)),
        "new_test_files": len(re.findall(r"^--- /dev/null", tp, re.M)),
        "added_tests": len(added_tests),
        "parametrize": "pytest.mark.parametrize" in tp,
        "class_tests": bool(re.search(r"^\+\s*class\s+Test\w*", tp, re.M)),
        "tp_changed": sum(1 for ln in tp.splitlines() if ln[:1] in "+-" and not ln.startswith(("+++", "---"))),
    }


def q(vals):
    vals = sorted(vals)
    if not vals:
        return {}
    def pct(p):
        return vals[min(len(vals) - 1, int(round(p * (len(vals) - 1))))]
    return {"n": len(vals), "p25": pct(0.25), "median": st.median(vals), "p75": pct(0.75), "p90": pct(0.9),
            "max": vals[-1], "mean": round(st.mean(vals), 1)}


def summarize(rows):
    S = [statement_stats(r["problem_statement"]) for r in rows]
    P = [patch_stats(r["patch"]) for r in rows]
    T = [test_stats(r["test_patch"]) for r in rows]
    n = len(rows)
    def frac(xs, k):
        return round(sum(1 for x in xs if x[k]) / n, 3) if n else None
    return {
        "n": n,
        "statement_chars": q([s["chars"] for s in S]),
        "statement_words": q([s["words"] for s in S]),
        **{f"statement_{k}": frac(S, k) for k in ("title_only", "code_block", "traceback", "py_path", "checklist",
                                                  "pr_voice", "issue_link")},
        "patch_files": q([p["files"] for p in P]),
        "patch_changed_lines": q([p["changed"] for p in P]),
        "patch_hunks": q([p["hunks"] for p in P]),
        "patch_new_file_tasks": round(sum(1 for p in P if p["new_files"]) / n, 3) if n else None,
        "patch_single_file": round(sum(1 for p in P if p["files"] == 1) / n, 3) if n else None,
        "test_files": q([t["test_files"] for t in T]),
        "test_added_tests": q([t["added_tests"] for t in T]),
        "test_no_added_def": round(sum(1 for t in T if t["added_tests"] == 0) / n, 3) if n else None,
        "test_parametrize": frac(T, "parametrize"),
        "test_class_tests": frac(T, "class_tests"),
        "test_new_file": round(sum(1 for t in T if t["new_test_files"]) / n, 3) if n else None,
        "test_changed_lines": q([t["tp_changed"] for t in T]),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--valid", default=None)
    a = ap.parse_args()
    comp = load(ROOT / "data" / "tasks.jsonl")
    kv = set((ROOT / "data" / "kaggle_valid_ids.txt").read_text().split())
    pal = load(ROOT / "data" / "pallets" / "tasks.jsonl")
    groups = {"competition_74": [r for r in comp if r["instance_id"] in kv], "competition_129": comp}
    for repo in ("fastapi/fastapi", "Textualize/rich"):
        groups["competition_74:" + repo.split("/")[1]] = [r for r in comp if r["instance_id"] in kv and r["repo"] == repo]
    groups["pallets_all"] = pal
    groups["pallets_core181"] = [r for r in pal if r["repo"] in ("pallets/flask", "pallets/click", "pallets/werkzeug")]
    for repo in sorted({r["repo"] for r in pal}):
        groups["pallets_all:" + repo.split("/")[1]] = [r for r in pal if r["repo"] == repo]
    if a.valid:
        v = set(Path(a.valid).read_text().split())
        groups["pallets_valid"] = [r for r in pal if r["instance_id"] in v]
        groups["pallets_valid_org"] = [r for r in pal if r["instance_id"] in v and r["repo"].startswith("pallets/")]
        prs = ROOT / "data" / "pallets" / "tasks_prstyle.jsonl"
        if prs.is_file():            # PR title + body statements (scripts/pallets/pr_statements.py)
            prow = [r for r in load(prs) if r["instance_id"] in v]
            groups["pallets_valid_prstyle"] = prow
            groups["pallets_valid_org_prstyle"] = [r for r in prow if r["repo"].startswith("pallets/")]
            for repo in sorted({r["repo"] for r in prow}):
                groups["pallets_valid_prstyle:" + repo.split("/")[1]] = [r for r in prow if r["repo"] == repo]
        for repo in sorted({r["repo"] for r in pal}):
            rows = [r for r in pal if r["repo"] == repo and r["instance_id"] in v]
            if rows:
                groups["pallets_valid:" + repo.split("/")[1]] = rows
    print(json.dumps({k: summarize(v) for k, v in groups.items()}, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
