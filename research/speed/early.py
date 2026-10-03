"""Sect. 3.3 queries: in v10.x solves, when the locator first VIEWED a file of the final patch, when a valid failing
reproduction first existed, which attempt produced it, and how many run.py probes the locator made. Stdlib only."""
import collections, json, os, re
from analyze import BY, T, tasks_of, task_metrics
P = {"p1_v10": "/Users/carson/Projects/gemma-swe-agent/eval/pair1/eval/runs/p1_v10",
     "r2_v10_1": "/Users/carson/Projects/gemma-swe-agent/eval/race2/eval/runs/r2_v10_1"}
seen, repro, n = collections.Counter(), collections.Counter(), 0
attempts, probes = collections.Counter(), collections.Counter()
for run, d in P.items():
    k0 = T[next(x for x in T if x[0] == run)]["scale"]
    for tid in tasks_of(run):
        m = task_metrics(run, tid)
        L = [s for s in BY[(run, tid)] if s["author"] == "locator"]
        R = [s for s in L if s.get("vk") == "repro"]
        idx = next((i for i, s in enumerate(R) if s["cat"] == "repro_ok"), None)
        out = "solved" if m["resolved"] else "unsolved"
        attempts[(out, "none written" if not R else ("never valid" if idx is None else ("first try" if idx == 0 else "retry")))] += 1
        np_ = sum(1 for s in L if s.get("helper") == "run")
        probes[(out, "0" if np_ == 0 else ("1-3" if np_ <= 3 else "4+"))] += 1
        if not m["resolved"] or not L:
            continue
        pf = os.path.join(d, "patches", tid + ".patch")
        files = {f for f in re.findall(r"^\+\+\+ b/(\S+)", open(pf).read(), re.M) if f.endswith(".py")} if os.path.exists(pf) else set()
        if not files:
            continue
        n += 1
        t0 = (L[0]["t_end"] - L[0]["llm_s"] - L[0]["tool_s"]) * k0
        sv = next((s["t_end"] * k0 - t0 for s in L if s.get("helper") in ("view", "read_file") and any(f in (s.get("cmd") or "") for f in files)), None)
        rv = next((s["t_end"] * k0 - t0 for s in L if s.get("cat") == "repro_ok"), None)
        for X in (15, 30, 60):
            seen[X] += sv is not None and sv <= X
            repro[X] += rv is not None and rv <= X
        seen["never"] += sv is None
print(f"solves with a .py patch: {n}")
print("patched file viewed by the locator within X s of locator time:", {X: seen[X] for X in (15, 30, 60)}, "never:", seen["never"])
print("valid failing reproduction within X s:", {X: repro[X] for X in (15, 30, 60)})
print("reproduction attempts:", dict(sorted(attempts.items())))
print("locator run.py probes:", dict(sorted(probes.items())))
