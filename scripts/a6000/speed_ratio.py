"""A6000 vs modelled Kaggle-L4 speed on the SAME model calls: for every LLM step of a run's traces, the measured seconds
(difference of consecutive extra.elapsed_s, which is cumulative from the task's start; it includes the tool run time of the
previous step, so the A6000 side is slightly pessimistic) against scripts/golden/router.l4_model_s(completion, uncached) with the or_proxy.Pacer's uncached rule
(prompt - previous prompt - previous completion within one author's conversation, else the whole prompt).

    python scripts/a6000/speed_ratio.py RUN_DIR [RUN_DIR ...]      (RUN_DIR holds results/traces/trace_*.json)

Prints per task: calls, completion tokens, A6000 seconds, modelled L4 seconds, ratio = A6000 / L4 (below 1 = A6000 faster)."""
import glob, json, os, statistics, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "golden"))
from router import l4_model_s  # noqa: E402


def task_stats(trace):
    prev, a6000, l4, n, comp, last = {}, 0.0, 0.0, 0, 0, 0.0
    for s in trace.get("steps", []):
        cur = float((s.get("extra") or {}).get("elapsed_s") or last)
        dt, last = max(0.0, cur - last), max(cur, last)
        m = s.get("metrics") or {}
        if not m.get("completion_tokens") and not m.get("prompt_tokens"):
            continue
        ex = s.get("extra") or {}
        author = ex.get("author", "")
        p, c = int(m.get("prompt_tokens") or 0), int(m.get("completion_tokens") or 0)
        pp, pc = prev.get(author, (0, 0))
        prev[author] = (p, c)
        uncached = p if p < pp else p - pp - pc
        a6000 += dt
        l4 += l4_model_s(c, max(0, uncached)); n += 1; comp += c
    return n, comp, a6000, l4


def main(runs):
    allr = []
    for run in runs:
        for f in sorted(glob.glob(os.path.join(run, "results", "traces", "trace_*.json"))):
            n, comp, a, l = task_stats(json.load(open(f)))
            tid = os.path.basename(f)[6:-5]
            r = a / l if l else float("nan")
            allr.append((tid, n, comp, a, l, r))
            print(f"{tid:16s} calls {n:3d} completion {comp:6d}  A6000 {a:7.1f}s  L4-model {l:7.1f}s  ratio {r:.2f}")
    if allr:
        print("TOTAL calls %d  A6000 %.1fs  L4-model %.1fs  ratio %.2f  (median per task %.2f)" % (
            sum(r[1] for r in allr), sum(r[3] for r in allr), sum(r[4] for r in allr),
            sum(r[3] for r in allr) / sum(r[4] for r in allr), statistics.median(r[5] for r in allr)))


if __name__ == "__main__":
    main(sys.argv[1:])
