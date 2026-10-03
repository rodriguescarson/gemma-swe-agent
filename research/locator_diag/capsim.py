"""Upper bound on locator L4 seconds removed by the proposed caps, applied together per case: reproduction attempts
(stop after the first failing one, at most 2), run.py/bare-shell probes (at most 2), then at most N helper calls in
total. Removed calls are assumed not to be replaced by others (an upper bound). L: per-call L4 latency from the router
token model; P: helper-footer deltas on the pod's L4 clock."""
import json, re, os, sys, io, contextlib, glob, statistics
SP = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SP)
with contextlib.redirect_stdout(io.StringIO()):
    from analyze import cls, case_p1, case_golden_L
FOOT = re.compile(r"\[t=(\d+)s\]")
RUN = "/Users/carson/Projects/gemma-swe-agent/eval/golden/runs/L_dev_v101"
lat_by = {}
for f in sorted(glob.glob(RUN + "/cases/*/router.jsonl")):
    recs = [json.loads(l) for l in open(f)]
    live = [r for r in recs if r.get("agent") == "locator" and r.get("served") == "upstream"]
    prev = None; lat = []
    for r in live:
        p, cc = r["prompt_tokens"], r["completion_tokens"]
        unc = p if prev is None else max(0, p - prev["prompt_tokens"] - prev["completion_tokens"])
        lat.append(0.102 + 0.02815 * cc + 0.000921 * unc); prev = r
    lat_by[f.split("/")[-2].split("__")[1]] = lat
def per_call_secs(c):
    if c["src"] == "L":
        lat = lat_by[c["task"]]
        return [lat[i] if i < len(lat) else 0.0 for i in range(len(c["uses"]))]
    out, last = [], 0
    for u in c["uses"]:
        m = FOOT.findall(u["out"])
        if m:
            t = int(m[-1]); out.append(max(0, t - last)); last = t
        else:
            out.append(0.0)
    return out
for N in (12, 14, 16):
    for src, cases in (("L", case_golden_L()), ("P", case_p1())):
        rem = []; tot = []
        for c in cases:
            secs = per_call_secs(c)
            keep = []
            nrep = nrun = 0; got_f = False
            for u, s in zip(c["uses"], secs):
                k = cls(u["cmd"], u["name"])
                if k == "repro":
                    if got_f or nrep >= 2:
                        continue
                    nrep += 1
                    if re.search(r"^REPRO: (fails|hangs) on original|^REPRO: .*hangs", u["out"], re.M):
                        got_f = True
                if k in ("run", "bare_shell"):
                    if nrun >= 2:
                        continue
                    nrun += 1
                keep.append(s)
            keep = keep[:N]
            rem.append(sum(secs) - sum(keep)); tot.append(sum(secs))
        print("cap N=%d %s: locator L4 s per task %.1f -> %.1f (removed mean %.1f, median %.1f; %.0f%%)" % (
            N, src, statistics.mean(tot), statistics.mean(tot) - statistics.mean(rem), statistics.mean(rem), statistics.median(rem), 100 * sum(rem) / sum(tot)))
