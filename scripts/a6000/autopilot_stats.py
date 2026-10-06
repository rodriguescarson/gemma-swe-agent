"""Live-reloaded stats collectors for the supervisor's health lines (editable while the supervisor runs)."""
import glob, json, os, statistics, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent))


def _empty():
    return dict(done=0, solved=0, empty=0, errors=0, cap=0, durations=[])


def p2(spec):
    """spec: {"out": dir, "arms": [...], "ids": [...]} -> counts over every arm's rows of the ids in this step."""
    import p2_report as rep
    s = _empty(); ids = set(spec["ids"])
    for arm in spec["arms"]:
        for t, r in rep.load_rows(spec["out"], arm).items():
            if t not in ids:
                continue
            tags = rep.classify(r)
            s["done"] += 1; s["solved"] += "solved" in tags; s["empty"] += "empty" in tags
            s["errors"] += "error" in tags; s["cap"] += "cap" in tags
            s["durations"].append(float(r.get("duration_seconds") or 0))
    return s


def results_jsonl(spec):
    """The kernel-format rows of scripts/a6000/run_eval.py (P4): id, resolved, secs, err, patch."""
    s = _empty(); f = Path(spec["file"])
    rows = [json.loads(l) for l in f.read_text().splitlines() if l.strip()] if f.exists() else []
    for r in rows:
        err = r.get("err") or ""
        s["done"] += 1; s["solved"] += bool(r.get("resolved")); s["empty"] += not (r.get("patch") or "").strip()
        s["cap"] += "session timeout" in err; s["errors"] += bool(err) and "session timeout" not in err and "budget" not in err
        s["durations"].append(float(r.get("secs") or 0))
    return s


def collect(spec):
    s = globals()[spec["type"]](spec)
    s["median_s"] = statistics.median(s["durations"]) if s["durations"] else None
    return s
