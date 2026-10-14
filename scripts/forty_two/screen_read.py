"""The pre-registered read of the v13 box screen (docs/forty_two/BOX_SCREEN.md). Mechanical: run it on the screen's results dir.

    python scripts/forty_two/screen_read.py RUN_DIR [--ref eval/a6000/results/p4_b1024] [--json OUT]

RUN_DIR holds results.jsonl (+ results/traces/ for the mechanism counters). Prints the verdict line first:
    PASS | FAIL | NO EVIDENCE | INVALID  solved S/74 (ref R) paired +W -L net N p P | the 42: K | counters ...
Rules (fixed in BOX_SCREEN.md before any v13 result exists):
  INVALID      the run is not a full, clean read of v13: < 74 ids, any crash/errored row (scripts/box_p4_gate.py's definitions),
               or the traces show v12-b1024's mechanics (an edit_file/write_file call that succeeded, i.e. the tool was declared;
               or a run_command that lasted >= 61 s and returned, i.e. the 60 s limit was not applied).
  PASS         solved >= 28 and paired net vs the ref >= +2 and >= 2 of the 42 solved.
  FAIL         solved <= 25 or paired net <= -3.
  NO EVIDENCE  anything else.
Reported, not gated: exact two-sided sign test on the discordant pairs, cap hits, malformed-parameter replies (any tool),
attempts to call the dropped tools (an error reply), template edits and refusals."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(ROOT / "scripts" / "forty_two"))
MISSING = "mandatory input parameters are not present"


def load(run_dir) -> dict:
    p = Path(run_dir); p = p / "results.jsonl" if p.is_dir() else p
    out = {}
    for line in p.read_text().splitlines():
        if line.strip():
            r = json.loads(line); out[r["id"]] = r
    return out


def sign_p(w: int, l: int) -> float:
    n = w + l
    if n == 0:
        return 1.0
    k = min(w, l)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def counters(run_dir) -> dict:
    import timing
    c = {"malformed_replies": 0, "edit_or_write_ok": 0, "edit_or_write_attempts": 0, "long_commands_ge_61s": 0,
         "template_refusals": 0, "template_edits": 0, "traces": 0}
    tdir = Path(run_dir) / "results" / "traces"
    for f in sorted(tdir.glob("trace_*.json")) if tdir.is_dir() else []:
        t = json.loads(f.read_text()); c["traces"] += 1
        for s in t.get("steps") or []:
            obs = str((s.get("observation") or {}).get("content") or "")
            for x in s.get("tool_calls") or []:
                if MISSING in obs:
                    c["malformed_replies"] += 1
                if x.get("function_name") in ("edit_file", "write_file"):
                    c["edit_or_write_attempts"] += 1
                    c["edit_or_write_ok"] += obs.lstrip().startswith('{"status": "ok"')
                cmd = str((x.get("arguments") or {}).get("command") or "")
                if x.get("function_name") == "run_command" and "<<'EDIT'" in cmd:
                    c["template_edits"] += 1
                    if '"status": "error"' in obs[:40]:
                        c["template_refusals"] += 1
        try:
            _, calls = timing.model_calls(t)
        except ValueError:
            continue
        for call in calls:
            for x in call["tools"]:
                if x["name"] == "run_command" and x.get("has_obs", True) and x["end"] - x["start"] >= 61:
                    c["long_commands_ge_61s"] += 1
    return c


def read(run_dir, ref_dir, ids_path=ROOT / "data" / "kaggle_valid_ids.txt", never_path=ROOT / "data" / "never_solved_box5_ids.txt"):
    from box_p4_gate import judge
    ids = Path(ids_path).read_text().split()
    never = set(Path(never_path).read_text().split())
    rows, ref = load(run_dir), load(ref_dir)
    _, gate = judge(list(rows.values()), ids, floor=0)
    solved = {i for i in ids if i in rows and rows[i].get("resolved")}
    rsolved = {i for i in ids if i in ref and ref[i].get("resolved")}
    w, l = len(solved - rsolved), len(rsolved - solved)
    k42 = sorted(solved & never)
    cnt = counters(run_dir)
    cap = sum("session timeout" in str(rows[i].get("err") or "").lower() for i in ids if i in rows)
    invalid = gate["missing"] or gate["crash_rows"] or gate["errored_rows"] or cnt["edit_or_write_ok"] or cnt["long_commands_ge_61s"]
    if invalid:
        verdict = "INVALID"
    elif len(solved) >= 28 and w - l >= 2 and len(k42) >= 2:
        verdict = "PASS"
    elif len(solved) <= 25 or w - l <= -3:
        verdict = "FAIL"
    else:
        verdict = "NO EVIDENCE"
    rep = {"verdict": verdict, "solved": len(solved), "ref_solved": len(rsolved), "wins": sorted(solved - rsolved),
           "losses": sorted(rsolved - solved), "net": w - l, "sign_p": round(sign_p(w, l), 3), "the_42_solved": k42, "cap_hits": cap,
           "gate": {k: (len(v) if isinstance(v, list) else v) for k, v in gate.items()}, "counters": cnt}
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir"); ap.add_argument("--ref", default=str(ROOT / "eval" / "a6000" / "results" / "p4_b1024"))
    ap.add_argument("--json")
    a = ap.parse_args()
    r = read(a.run_dir, a.ref)
    c = r["counters"]
    print(f"{r['verdict']} solved {r['solved']}/74 (ref {r['ref_solved']}) paired +{len(r['wins'])} -{len(r['losses'])} net {r['net']:+d} "
          f"p {r['sign_p']} | the 42: {len(r['the_42_solved'])} | cap {r['cap_hits']} | malformed {c['malformed_replies']} "
          f"edit/write ok {c['edit_or_write_ok']} attempts {c['edit_or_write_attempts']} commands>=61s {c['long_commands_ge_61s']} template edits {c['template_edits']} "
          f"refused {c['template_refusals']}")
    print("wins:", " ".join(r["wins"]) or "-"); print("losses:", " ".join(r["losses"]) or "-")
    print("the 42 solved:", " ".join(r["the_42_solved"]) or "-")
    if a.json:
        Path(a.json).write_text(json.dumps(r, indent=1))


if __name__ == "__main__":
    main()
