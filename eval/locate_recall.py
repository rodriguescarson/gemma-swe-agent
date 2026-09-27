"""Offline recall of locate.py: rank of the gold-patch file(s) when the issue text is the query. Free (CPU only)."""
import json, os, re, subprocess, sys, tarfile, tempfile, collections
LOC = sys.argv[1]; SNAP = "data/raw/snapshots"; out = collections.defaultdict(list)
IDS = set(l.strip() for l in open(os.environ["IDS"])) if os.environ.get("IDS") else None
for line in open(os.environ.get("TASKS", "data/tasks.jsonl")):
    t = json.loads(line); snap = f"{SNAP}/{t['instance_id']}.tgz"
    if IDS and t["instance_id"] not in IDS: continue
    if not os.path.exists(snap): continue
    gold = [f for f in re.findall(r"^\+\+\+ b/(\S+)", t["patch"], re.M) if f.endswith(".py")]
    if not gold: continue
    with tempfile.TemporaryDirectory() as d:
        try: tarfile.open(snap).extractall(d)
        except Exception: continue
        root = next((os.path.join(d, x) for x in os.listdir(d) if os.path.isdir(os.path.join(d, x, ".git"))), d)
        r = subprocess.run([sys.executable, LOC] + (["--query"] if "locate" in LOC else []) + [t["problem_statement"][:4000]], capture_output=True, text=True, env={**os.environ, "SWE_WS": root, "PYTHONDONTWRITEBYTECODE": "1"})
        ranked = re.findall(r"^\d+\. (\S+)", r.stdout, re.M)
        rank = min((ranked.index(g) + 1 for g in gold if g in ranked), default=99)
    out[t["repo"]].append(rank); print(t["instance_id"], rank, flush=True)
allr = [r for v in out.values() for r in v]
for k, v in list(out.items()) + [("ALL", allr)]:
    print(f"{k:18} n={len(v):3}  R@1={sum(r<=1 for r in v)/len(v):.2f}  R@3={sum(r<=3 for r in v)/len(v):.2f}  R@8={sum(r<=8 for r in v)/len(v):.2f}")
