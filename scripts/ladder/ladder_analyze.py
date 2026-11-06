"""Step 3: the ladder. S(T,K) = number of tasks whose tree, at the first of (T seconds, K counted tool calls), passes the hidden-test verifier.
Inputs: L1 results.jsonl + snapshots.jsonl + results/traces/trace_<id>.json (per-call end times), versions.json + the rescore kernel's results.jsonl (cfg v<j>, id, resolved).
Usage : python ladder_analyze.py <L1_dir> <ladder_patches_out_dir> <rescore_results.jsonl> [--ids subset_E.txt] [--selftest]
Prints the S grid, the paired gains with task-bootstrap 95% CI, the A/A gate and the pre-registered decision."""
import json, sys, os, random, hashlib, collections
DT = collections.defaultdict(dict)
def counted_ends(trace_path, task=None):
    t = json.load(open(trace_path)); ends = []
    for s in t["steps"]:
        for tc in (s.get("tool_calls") or []):
            if tc["function_name"] == "get_status": continue       # not counted by the harness (budget_gated count_tool_call=False)
            ob = s.get("observation") or {}
            ends.append(((ob.get("extra") or {}).get("elapsed_s")) or (s.get("extra") or {}).get("elapsed_s") or 0.0)
    # remove the hook's own time from the agent's clock: end of call k includes the snapshots taken at the start of calls 1..k (rows with k' <= k-1)
    return [e - sum(v for kk, v in DT[task].items() if kk <= i) for i, e in enumerate(ends)] if task else ends
def load(L1, VER, RES, ids):
    rows = {}
    for l in open(os.path.join(L1, "results.jsonl")):
        r = json.loads(l); rows[r["id"]] = r
    snaps = collections.defaultdict(dict); DT.clear()       # task -> k -> sha; DT[task] = {k: snapshot seconds spent at the start of call k+1}
    for l in open(os.path.join(L1, "snapshots.jsonl")):
        r = json.loads(l); snaps[r["task"]][r["k"]] = r["sha"]; DT[r["task"]][r["k"]] = r.get("dt", 0.0)
    versions = json.load(open(os.path.join(VER, "versions.json")))
    resolved = {}
    for l in open(RES):
        r = json.loads(l); resolved[(r["id"], r["cfg"])] = bool(r["resolved"])
    return rows, snaps, versions, resolved
def solved_at(task, T, K, rows, snaps, versions, resolved, L1):
    r = rows[task]; ends = counted_ends(os.path.join(L1, "results", "traces", "trace_%s.json" % task), task); n = len(ends)
    kT = sum(1 for e in ends if e <= T)
    k = min(K, kT, n)
    if k >= n: patch = r.get("patch") or ""; sha = hashlib.sha1(patch.encode()).hexdigest()
    else: sha = snaps[task].get(k)
    if sha is None or sha not in versions.get(task, []): return False      # empty tree (or missing) cannot pass
    return resolved.get((task, "v%d" % versions[task].index(sha)), False)
TIMES = (240, 300, 330, 360, 420, 480); CALLS = (28, 34, 40)
def grid(ids, ctx):
    return {(T, K): {t: solved_at(t, T, K, *ctx) for t in ids} for T in TIMES for K in CALLS}
def boot(a, b, ids, n=4000, seed=1):
    rnd = random.Random(seed); d = [int(b[t]) - int(a[t]) for t in ids]; out = []
    for _ in range(n): out.append(sum(rnd.choice(d) for _ in d))
    out.sort(); return sum(d), out[int(.025 * n)], out[int(.975 * n)]
def main():
    a = sys.argv[1:]; L1, VER, RES = a[0], a[1], a[2]
    ids = [l.strip() for l in open(a[a.index("--ids") + 1])] if "--ids" in a else None
    rows, snaps, versions, resolved = load(L1, VER, RES, ids); ids = ids or list(rows)
    ids = [t for t in ids if t in rows]; ctx = (rows, snaps, versions, resolved)
    ctx = (rows, snaps, versions, resolved, L1); G = grid(ids, ctx)
    print("n tasks", len(ids)); print("S(T,K)   " + "".join("K=%-4d" % K for K in CALLS))
    for T in TIMES: print("T=%-4d   " % T + "".join("%-6d" % sum(G[(T, K)].values()) for K in CALLS))
    base = G[(300, 40)]
    for name, c in (("G55 (330 vs 300, 40 calls)", (330, 40)), ("G6 (360 vs 300)", (360, 40)), ("G7 (420 vs 300)", (420, 40)), ("G8 (480 vs 300)", (480, 40)),
                    ("public shape (480 s, 28 calls) vs v12b (300 s, 40)", (480, 28)), ("28-call truncation at 480 s (28 vs 40 calls)", None)):
        cur = G[c] if c else G[(480, 28)]; ref = base if c else G[(480, 40)]
        up = sum(cur[t] and not ref[t] for t in ids); dn = sum(ref[t] and not cur[t] for t in ids); net, lo, hi = boot(ref, cur, ids)
        print("%-52s net %+d (up %d, down %d)  95%% CI [%+d, %+d]" % (name, net, up, dn, lo, hi))
    print("S(300,40) on these tasks:", sum(base.values()))
if __name__ == "__main__": main()
