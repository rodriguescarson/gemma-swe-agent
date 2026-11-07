"""Step 3: the ladder. S(T,K) = number of tasks whose tree, at the first of (T seconds, K counted tool calls), passes the hidden-test verifier.
Inputs: L1 results.jsonl + snapshots.jsonl + results/traces/trace_<id>.json (per-call end times), versions.json + the rescore kernel's results.jsonl (cfg v<j>, id, resolved).
Usage : python ladder_analyze.py <L1_dir> <ladder_patches_out_dir> <rescore_results.jsonl> [--ids subset_E.txt] [--selftest]
Prints the S grid, the paired gains with task-bootstrap 95% CI, the A/A gate and the pre-registered decision."""
import json, sys, os, random, hashlib, collections
DT = collections.defaultdict(dict)
# Which trace calls the harness counted (swegemma tools/base.py budget_gated + context.check_budget, served build 9ad87658):
#  - submit_patch and get_status are budget_gated(count_tool_call=False): never counted, the hook takes no snapshot;
#  - a call ADK rejects for missing arguments ("Invoking `edit_file()` failed as the following mandatory input parameters
#    are not present") never reaches the wrapper: not counted, no snapshot (94 such edit_file calls in L1);
#  - a call refused by check_budget (BudgetExceeded / TimeoutExceeded) reaches the wrapper, so the hook snapshots it, but
#    tool_calls_used does not move: not counted;
#  - everything else (including CommandError, FileEditError, ValueError from the tool body) is counted.
# Fixed 2026-11-07 after the L1 read: the first version counted every non-get_status call, so on tasks with malformed calls
# the K index ran ahead of the harness count, looked up a snapshot k that does not exist and scored the task unsolved.
UNCOUNTED_TOOLS = ("get_status", "submit_patch")
PRE_WRAPPER = "failed as the following mandatory input parameters are not present"
# match check_budget's own messages: run_command's per-command timeout also reports error_type TimeoutExceeded, but it ran
# inside the wrapper and was counted (3 such calls in L1)
REFUSED = ("budget exhausted (",)
def classify(trace_path):
    """[(kind, end_s)] per tool call in order; kind in counted / refused / skipped."""
    t = json.load(open(trace_path)); out = []
    for s in t["steps"]:
        for tc in (s.get("tool_calls") or []):
            ob = s.get("observation") or {}; c = str(ob.get("content", ""))
            end = ((ob.get("extra") or {}).get("elapsed_s")) or (s.get("extra") or {}).get("elapsed_s") or 0.0
            if tc["function_name"] in UNCOUNTED_TOOLS or PRE_WRAPPER in c: kind = "skipped"
            elif any(r in c for r in REFUSED): kind = "refused"
            else: kind = "counted"
            out.append((kind, end))
    return out
def counted_ends(trace_path, task=None):
    ends = [e for kind, e in classify(trace_path) if kind == "counted"]
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
    if sha == EMPTY_SHA: return task in EMPTY_PASS                          # the empty tree is graded too (verify_task runs the tests on any patch)
    if sha is None or sha not in versions.get(task, []): return False      # missing snapshot: unsolved (counted by check_counts)
    return resolved.get((task, "v%d" % versions[task].index(sha)), False)
# Tasks whose hidden tests pass on the unmodified repo (scorer replay of an empty patch, GAPS "Label cleanup", 30 Oct): an
# empty tree counts as solved there, as the L1 kernel itself scored fastapi_14851 (empty patch, resolved).
EMPTY_SHA = hashlib.sha1(b"").hexdigest(); EMPTY_PASS = {"fastapi_14077", "fastapi_14851", "requests_6644"}
def check_counts(ids, rows, snaps, L1):
    """The classification must reproduce the harness: counted calls == the row's own `calls`, and counted + refused ==
    the hook's snapshot rows. Returns the list of disagreements (empty when the instrument and the analysis agree)."""
    bad = []
    nrows = collections.Counter(json.loads(l)["task"] for l in open(os.path.join(L1, "snapshots.jsonl")))
    for t in ids:
        k = collections.Counter(kind for kind, _ in classify(os.path.join(L1, "results", "traces", "trace_%s.json" % t)))
        if k["counted"] != rows[t].get("calls") or k["counted"] + k["refused"] != nrows[t]:
            bad.append((t, dict(k), rows[t].get("calls"), nrows[t]))
    return bad
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
    bad = check_counts(ids, rows, snaps, L1)
    print("call-count check (counted == row calls, counted + refused == snapshot rows):", "OK" if not bad else "MISMATCH %s" % bad)
    print("n tasks", len(ids)); print("S(T,K)   " + "".join("K=%-4d" % K for K in CALLS))
    for T in TIMES: print("T=%-4d   " % T + "".join("%-6d" % sum(G[(T, K)].values()) for K in CALLS))
    base = G[(300, 40)]
    for name, c in (("G55 (330 vs 300, 40 calls)", (330, 40)), ("G6 (360 vs 300)", (360, 40)), ("G7 (420 vs 300)", (420, 40)), ("G8 (480 vs 300)", (480, 40)),
                    ("public shape (480 s, 28 calls) vs v12b (300 s, 40)", (480, 28)), ("28-call truncation at 480 s (28 vs 40 calls)", None)):
        cur = G[c] if c else G[(480, 28)]; ref = base if c else G[(480, 40)]
        up = sum(cur[t] and not ref[t] for t in ids); dn = sum(ref[t] and not cur[t] for t in ids); net, lo, hi = boot(ref, cur, ids)
        print("%-52s net %+d (up %d, down %d)  95%% CI [%+d, %+d]" % (name, net, up, dn, lo, hi))
    print("S(300,40) on these tasks:", sum(base.values()))
    own = sum(bool(rows[t]["resolved"]) for t in ids); s480 = sum(G[(480, 40)].values())
    print("gate A(ii): kernel's own solved %d, S(480,40) %d, |diff| %d -> %s" % (own, s480, abs(own - s480), "PASS" if abs(own - s480) <= 1 else "FAIL"))
    for t in ids:
        if bool(rows[t]["resolved"]) != G[(480, 40)][t]: print("  disagree:", t, "kernel", bool(rows[t]["resolved"]), "S(480,40)", G[(480, 40)][t])
if __name__ == "__main__": main()
