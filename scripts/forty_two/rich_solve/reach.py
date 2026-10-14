"""Reach of a lever: how many public (74) and held-out (1,044 valid) tasks have a property, measured from gold patches and
statements (data/tasks.jsonl, data/heldout1k/tasks.jsonl.gz). Run from the repository root.

    python scripts/forty_two/rich_solve/reach.py backslash|envflag|noident"""
import gzip, json, re, sys
kind = sys.argv[1]
valid74 = set(open("data/kaggle_valid_ids.txt").read().split())
never = set(open("data/never_solved_box5_ids.txt").read().split())
pub = [json.loads(l) for l in open("data/tasks.jsonl") if l.strip()]
pub = [t for t in pub if t["instance_id"] in valid74]
ho_valid = set(open("data/heldout1k/all_valid_ids.txt").read().split())
ho = [json.loads(l) for l in gzip.open("data/heldout1k/tasks.jsonl.gz", "rt")]
ho = [t for t in ho if t["instance_id"] in ho_valid]


def changed_lines(t):
    return [l[1:] for l in t["patch"].splitlines() if l[:1] in "+-" and not l.startswith(("+++", "---"))]


def prop(t):
    if kind == "backslash":           # a changed source line of the gold patch contains a backslash
        return any("\\" in l for l in changed_lines(t))
    if kind == "envflag":             # the gold patch reads an environment variable in a changed line
        return any(re.search(r"environ|getenv", l) for l in changed_lines(t))
    if kind == "noident":             # the title has no code identifier (no `x`, no snake/Camel/dotted name, no call)
        title = t["problem_statement"].strip().split("\n")[0]
        return not re.search(r"`|\w+_\w+|[a-z][A-Z]|[A-Z][a-z]+[A-Z]|\w\.\w|\w\(", title)
    raise SystemExit(kind)


for name, rows in (("public74", pub), ("heldout", ho)):
    hits = [t["instance_id"] for t in rows if prop(t)]
    print(f"{kind} {name}: {len(hits)} of {len(rows)}")
    if name == "public74":
        print("   in the 42:", sorted(h for h in hits if h in never))
        print("   outside the 42:", sorted(h for h in hits if h not in never))
    else:
        print("   e.g.", hits[:8])
