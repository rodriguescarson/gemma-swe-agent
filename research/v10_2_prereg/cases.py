"""The pre-registered v10.2 evaluation population (docs/eval/V10_2_EVAL.md section 3): dev-split tasks that are runnable
and gradable in suite F and runnable in suite L, ordered per repo by sha256("v10.2-eval:" + task); the first 15 rich and
the first 15 fastapi. Holdout tasks are never read (the datasets used are the dev files only)."""
import json, hashlib, collections
F = json.load(open("eval/golden/datasets/F_dev.json"))["eval_cases"]
L = json.load(open("eval/golden/datasets/L_dev.json"))["eval_cases"]
fg = {c["golden"]["task"]: c["golden"] for c in F}
lg = {c["golden"]["task"]: c["golden"] for c in L}
ok = sorted(t for t, g in fg.items() if g["runnable"] and g["gradable"] and t in lg and lg[t]["runnable"])
key = lambda t: hashlib.sha256(("v10.2-eval:" + t).encode()).hexdigest()
by = collections.defaultdict(list)
for t in ok:
    by[fg[t]["repo"]].append(t)
cases = sorted(sorted(by["rich"], key=key)[:15] + sorted(by["fastapi"], key=key)[:15])
print("eligible", {r: len(v) for r, v in sorted(by.items())}, "selected", len(cases))
print(",".join(cases))
print("strata", dict(collections.Counter(lg[t]["stratum"] for t in cases)),
      "reproducible", sum(bool(lg[t]["reproducible"]) for t in cases))
print("fixture_sha L", {t: lg[t]["fixture_sha"][:12] for t in cases})
print("fixture_sha F", {t: fg[t]["fixture_sha"][:12] for t in cases})
