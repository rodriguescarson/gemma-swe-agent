"""File recall of the SHIPPED graph tools (as a graph-first agent would call them) vs locate.py, on the Kaggle-valid tasks.
Graph agent: identifiers from the issue text -> resolve_node_name (exact tool behaviour) + get_similar_nodes(k=10);
files ranked by first appearance. Gold = non-test .py files touched by the reference patch.
Usage: python eval/graph_recall.py [locate.py path]"""
import json, os, re, sys, tarfile, tempfile, subprocess, collections, logging
logging.disable(logging.CRITICAL)
from swegemma.graph import graph_utils as gu, retrieval_utils as ru
STOP = set("the and for with this that from into when should would could have has not are was fix issue bug add support none true false self return".split())
ids = [l.strip() for l in open("data/kaggle_valid_ids.txt") if l.strip()]
T = {json.loads(l)["instance_id"]: json.loads(l) for l in open("data/tasks.jsonl")}
is_test = lambda p: bool(re.search(r"(^|/)(tests?|testing)/|(^|/)test_[^/]*\.py$|_test\.py$|conftest\.py$", p))
def modname(path):
    m = path[:-3].replace("/", ".")
    m = re.sub(r"^src\.", "", m); return re.sub(r"\.__init__$", "", m)
def file_rank(node_ids, gold_mods):
    seen = []
    for n in node_ids:
        f = next((g for g in gold_mods if n == g or n.startswith(g + ".")), None)
        key = f or n.rsplit(".", 1)[0]
        if key not in seen: seen.append(key)
        if f: return seen.index(key) + 1
    return 99
res = collections.defaultdict(dict)
for iid in ids:
    t = T[iid]; repo = t["repo"]
    gold = [g for g in re.findall(r"^\+\+\+ b/(\S+)", t["patch"], re.M) if g.endswith(".py") and not is_test(g)]
    if not gold: continue
    gmods = [modname(g) for g in gold]
    try:
        G = gu.get_graph(repo_name=repo, graph_dir="data/raw/graphs", embeddings_dir="data/raw/embeddings", base_commit=t["base_commit"])
    except Exception as e:
        res[iid]["graph"] = 99; continue
    q = t["problem_statement"]
    idents = [w for w in dict.fromkeys(re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", q)) if w.lower() not in STOP and ("_" in w or re.search(r"[a-z][A-Z]", w) or w[0].isupper())][:6]
    nodes = []
    for w in idents:
        try:
            r = gu.resolve_node_name(G, w)
            if r: nodes.append(r if isinstance(r, str) else str(r))
        except Exception: pass
        try:
            for x in ru.get_similar_nodes(node=w, repo_name=repo, k=10, graph=G, graph_dir="data/raw/graphs", embeddings_dir="data/raw/embeddings", base_commit=t["base_commit"]):
                nodes.append(x.get("node_name", ""))
        except Exception: pass
    res[iid]["graph"] = file_rank(nodes, gmods); res[iid]["n_idents"] = len(idents)
    loc = sys.argv[1] if len(sys.argv) > 1 else None
    snap = f"data/raw/snapshots/{iid}.tgz"
    if loc and os.path.exists(snap):
        try:
            with tempfile.TemporaryDirectory() as d:
                tarfile.open(snap).extractall(d)
                root = next((os.path.join(d, x) for x in os.listdir(d) if os.path.isdir(os.path.join(d, x, ".git"))), d)
                out = subprocess.run([sys.executable, loc, "--query", q[:4000]], capture_output=True, text=True, env={**os.environ, "SWE_WS": root, "PYTHONDONTWRITEBYTECODE": "1"}).stdout
                ranked = re.findall(r"^\d+\. (\S+)", out, re.M)
                res[iid]["locate"] = min((ranked.index(g) + 1 for g in gold if g in ranked), default=99)
        except Exception: pass
def summ(key, sub=None):
    v = [r[key] for i, r in res.items() if key in r and (sub is None or i in sub)]
    return f"n={len(v):3} R@1={sum(x<=1 for x in v)/len(v):.2f} R@3={sum(x<=3 for x in v)/len(v):.2f} R@10={sum(x<=10 for x in v)/len(v):.2f}" if v else "n=0"
both = {i for i, r in res.items() if "locate" in r}
print("graph tools, all valid tasks :", summ("graph"))
print("graph tools, paired subset   :", summ("graph", both))
print("locate.py,   paired subset   :", summ("locate", both))
print("tasks with no usable identifier:", sum(1 for r in res.values() if r.get("n_idents") == 0))
