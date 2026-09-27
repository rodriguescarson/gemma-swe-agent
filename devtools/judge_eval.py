"""Score a judge file against our evaluator: AUROC + selection on mixed tasks, vs free baselines."""
import json, sys, collections, random
J = [j for j in map(json.loads, open(sys.argv[1])) if j["p"] is not None]
L = {(r["task"], r["cfg"]): r for r in json.load(open("data/patch_labels.json"))}
def auroc(xs):  # xs = [(score, label)]
    pos = [s for s, y in xs if y]; neg = [s for s, y in xs if not y]
    return sum((p > n) + 0.5 * (p == n) for p in pos for n in neg) / (len(pos) * len(neg))
print(f"n={len(J)} pass={sum(j['resolved'] for j in J)}")
print(f"AUROC judge        {auroc([(j['p'], j['resolved']) for j in J]):.3f}")
print(f"AUROC -patch_len   {auroc([(-len(L[j['task'], j['cfg']]['patch']), j['resolved']) for j in J]):.3f}")
by = collections.defaultdict(list)
for j in J: by[j["task"]].append(j)
mixed = {t: v for t, v in by.items() if len({x["resolved"] for x in v}) == 2}
pick = sum(max(v, key=lambda x: x["p"])["resolved"] for v in mixed.values())
v4 = sum(any(x["cfg"] == "p_v4" and x["resolved"] for x in v) for v in mixed.values())
short = sum(min(v, key=lambda x: len(L[x["task"], x["cfg"]]["patch"]))["resolved"] for v in mixed.values())
rnd = sum(sum(x["resolved"] for x in v) / len(v) for v in mixed.values())
print(f"mixed tasks {len(mixed)}: judge picks passing {pick} | always-v4 {v4} | shortest {short} | random {rnd:.1f}")
