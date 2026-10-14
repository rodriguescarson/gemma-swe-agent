"""Where a rule would have fired in recorded box traces: every tool call of one task whose arguments (or, with --obs, whose
observation) match a regex, with the run, step, call number (malformed calls are not counted, as in the harness) and elapsed
seconds. Offline; reads eval/a6000/results/<run>/results/traces/trace_<id>.json.

    python scripts/forty_two/rich_solve/trace_hits.py rich_3777 "TTY_COMPATIBLE" --obs [--runs p4,p4_b1024] [--width 160]"""
import argparse, json, re
from pathlib import Path

RUNS = ["p4", "p4_v7", "p4_v7c", "p4_v7d", "p4_b1024", "p4_v0t2"]


def hits(root, run, tid, pat, obs=False):
    p = Path(root) / "eval/a6000/results" / run / "results/traces" / f"trace_{tid}.json"
    if not p.exists():
        return None
    n = 0
    out = []
    for s in json.loads(p.read_text())["steps"]:
        if s.get("source") != "agent":
            continue
        o = (s.get("observation") or {}).get("content", "") or ""
        for tc in s.get("tool_calls") or []:
            fn, a = tc.get("function_name"), tc.get("arguments") or {}
            if fn not in ("submit_patch", "get_status") and '"error": "Invoking' not in o:
                n += 1
            text = json.dumps(a, ensure_ascii=False)
            if pat.search(text) or (obs and pat.search(o)):
                out.append(dict(step=s["step_id"], call=n, t=round((tc.get("extra") or {}).get("elapsed_s") or 0, 1), fn=fn,
                                args=text, obs=o))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("id"); ap.add_argument("regex"); ap.add_argument("--obs", action="store_true")
    ap.add_argument("--runs", default=",".join(RUNS)); ap.add_argument("--width", type=int, default=160)
    ap.add_argument("--root", default=".")
    a = ap.parse_args()
    pat = re.compile(a.regex)
    for run in a.runs.split(","):
        h = hits(a.root, run, a.id, pat, a.obs)
        if h is None:
            print(f"{run}: no trace"); continue
        print(f"{run}: {len(h)} matching calls")
        for x in h:
            print(f"  step {x['step']} call {x['call']} t={x['t']}s {x['fn']} {x['args'][:a.width]}")
            if a.obs:
                m = pat.search(x["obs"])
                if m:
                    i = max(0, m.start() - a.width // 3)
                    print(f"      obs: ...{x['obs'][i:i + a.width]}...")


if __name__ == "__main__":
    main()
