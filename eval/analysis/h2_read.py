"""Read a Harness² pilot archive against its pre-registered rules (docs/GAPS_2026-10-06.md: 'Harness² pilot pre-registration'
and 'Phase 1 reading clarified'), so the reading is computed from the files, not typed.

    python eval/analysis/h2_read.py eval/a6000/results/h2_gemma [--mode seq] [--out eval/analysis/out/h2_gemma_read.md]

Per task: the INV / DOM / COMPOSE stages (kept_base, fell_back, error), rollouts with a staged record but no result (crashes),
the selection (ok or its error, chosen label), the chosen run's verdict (judged.json), the base run's verdict
(base_judged.json), and whether a library entry was written. Readings, as pre-registered:
  MECHANICS  PASS iff >= 6 tasks have all three stages returning valid trees (fell_back false, no error) and no crashed rollout
  ADOPTIONS  tasks with a successful selection and a library entry (reported next to MECHANICS, 19 Oct clarification)
  SIGNAL     chosen-run solves >= 4 of 8, or >= 3 with one of the never-solved three among them; a failed selection is unsolved
The archive may be a box archive (<dir>/root/...) or a runs root itself."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

NEVER_SOLVED = {"arrow_22acd93", "arrow_30d16c1", "arrow_384fb74"}   # 0 of 14 earlier box runs each (pre-registration)
STAGES = ("inv", "dom", "c")


def _root(d: Path) -> Path:
    return d / "root" if (d / "root" / "adapt").is_dir() else d


def _load(p: Path, default):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return default


def read(d: Path, mode: str = "seq") -> dict:
    r = _root(Path(d))
    summaries = sorted((r / "adapt").glob("*/*/summary.json"))
    if not summaries:
        raise SystemExit(f"no summary.json under {r / 'adapt'}")
    ns = summaries[0].parent.parent
    judged = {row.get("task_id"): row for row in _load(ns / "judged.json", []) if row.get("mode", mode) in (mode, "")}
    base = {}
    for row in _load(ns / "base_judged.json", []):
        sc = row.get("score") or {}
        base.setdefault(row.get("task"), []).append(bool(sc.get("all_pass")))
    staged = {}
    for rec in (r / "race" / "staged").glob("*/*.json") if (r / "race" / "staged").is_dir() else []:
        staged.setdefault(rec.stem, []).append(rec.parent.name)
    rows = []
    for sp in summaries:
        s = _load(sp, {})
        t = s.get("task_id") or sp.parent.name
        m = (s.get("modes") or {}).get(mode) or {}
        st = {x.get("label", ""): x for x in m.get("stages") or []}
        stages = {}
        for prefix in STAGES:
            lab = next((k for k in st if k.rstrip("0123456789") == prefix), None)
            stages[prefix] = st.get(lab) if lab else None
        crashed = [a for a in staged.get(t, []) if not (r / "race" / "items" / a / t / "task_results.jsonl").is_file()]
        valid = all(x is not None and not x.get("fell_back") and not x.get("error") for x in stages.values())
        sel = (s.get("selections") or {}).get(mode) or {}
        lib = any(r.glob(f"library/**/harnesses/{t}/harness"))
        j = judged.get(t) or {}
        rows.append({
            "task": t, "status": s.get("status", ""),
            "stages": {k: (None if v is None else {"kept_base": bool(v.get("kept_base")), "fell_back": bool(v.get("fell_back")),
                                                   "error": v.get("error", "")}) for k, v in stages.items()},
            "rollouts": len(staged.get(t, [])), "crashed": crashed, "mechanics": valid and not crashed,
            "selection_ok": bool(sel.get("ok")), "selection_error": sel.get("error", ""), "chosen": sel.get("chosen_label", ""),
            "chosen_is_base_tree": sel.get("chosen_tree_is_base"),
            "solved": bool(j.get("all_pass")) if sel.get("ok") else False, "judged": t in judged,
            "base_solved": base.get(t, []), "library_entry": lib,
        })
    n = len(rows)
    mech = sum(x["mechanics"] for x in rows)
    adopt = sum(x["selection_ok"] and x["library_entry"] for x in rows)
    solved = [x["task"] for x in rows if x["solved"]]
    base_solved = sum(any(x["base_solved"]) for x in rows)
    signal = len(solved) >= 4 or (len(solved) >= 3 and bool(NEVER_SOLVED & set(solved)))
    return {"tasks": n, "rows": rows, "mechanics": mech, "mechanics_pass": mech >= 6, "adoptions": adopt,
            "solved": solved, "base_solved": base_solved, "signal": signal}


def sessions(d: Path) -> dict:
    """Improver-session audit from adapt/_audit/<stage>.*.response.md (post hoc, 19 Oct): per stage, how many sessions
    overflowed the model's context (OpenCode's compaction notice in the reply), how many answered a bare KEEP_BASE, and how
    many ended by asking a question instead of acting."""
    r = _root(Path(d))
    out = {}
    for f in sorted((r / "adapt" / "_audit").glob("*.response.md")):
        stage = f.name.split(".")[0]
        t = f.read_text(encoding="utf-8", errors="replace")
        c = out.setdefault(stage, {"sessions": 0, "overflowed": 0, "bare_keep_base": 0, "ended_with_question": 0})
        c["sessions"] += 1
        c["overflowed"] += "exceeded the provider's size limit" in t or "was compacted" in t
        c["bare_keep_base"] += t.strip() == "KEEP_BASE"
        c["ended_with_question"] += t.strip().endswith("?")
    return out


def replays(d: Path) -> dict:
    """Same-tree rollouts on the same task (post hoc, box B-216): groups of >= 2 rollouts with one fingerprint, and how many
    pairs within them repeat exactly (same resolved, llm calls, patch size, and seconds within 2 s)."""
    r = _root(Path(d))
    groups = {}
    for rec in (r / "race" / "staged").glob("*/*.json") if (r / "race" / "staged").is_dir() else []:
        meta = _load(rec, {})
        res = r / "race" / "items" / rec.parent.name / rec.stem / "task_results.jsonl"
        lines = [x for x in res.read_text().splitlines() if x.strip()] if res.is_file() else []
        if lines and meta.get("fingerprint"):
            row = json.loads(lines[-1])
            groups.setdefault((rec.stem, meta["fingerprint"]), []).append(
                (bool(row.get("resolved")), row.get("total_llm_calls"), row.get("agent_patch_size"),
                 float(row.get("duration_seconds") or 0)))
    pairs = same = outcome_same = 0
    for runs in groups.values():
        for i in range(len(runs)):
            for j in range(i + 1, len(runs)):
                a, b = runs[i], runs[j]
                pairs += 1
                outcome_same += a[0] == b[0]
                same += a[:3] == b[:3] and abs(a[3] - b[3]) <= 2
    return {"groups": sum(len(v) >= 2 for v in groups.values()), "pairs": pairs, "exact": same, "same_outcome": outcome_same}


def render(res: dict) -> str:
    out = ["| task | INV | DOM | COMPOSE | rollouts | crashed | selection | chosen solved | base solved | library |",
           "|---|---|---|---|---|---|---|---|---|---|"]

    def cell(v):
        if v is None:
            return "missing"
        return "fell back" if v["fell_back"] else ("error" if v["error"] else ("kept base" if v["kept_base"] else "new tree"))
    for x in res["rows"]:
        sel = (f"ok ({x['chosen']})" if x["selection_ok"] else f"failed: {x['selection_error'][:50]}")
        out.append(f"| {x['task']} | {cell(x['stages']['inv'])} | {cell(x['stages']['dom'])} | {cell(x['stages']['c'])} | "
                   f"{x['rollouts']} | {len(x['crashed'])} | {sel} | {x['solved']} | "
                   f"{', '.join(str(b) for b in x['base_solved']) or '-'} | {x['library_entry']} |")
    out.append("")
    out.append(f"MECHANICS {'PASS' if res['mechanics_pass'] else 'FAIL'}: {res['mechanics']} of {res['tasks']} tasks with three "
               f"valid stages and no crashed rollout (pass >= 6).")
    out.append(f"ADOPTIONS: {res['adoptions']} of {res['tasks']} (successful selection and a library entry).")
    out.append(f"SIGNAL {'YES' if res['signal'] else 'NO'}: chosen runs solved {len(res['solved'])} of {res['tasks']} "
               f"({', '.join(res['solved']) or 'none'}); base runs solved {res['base_solved']}; pre-registered base "
               f"expectation 1.8 of 8. n = 8 is descriptive.")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("archive", type=Path)
    ap.add_argument("--mode", default="seq")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    text = render(read(a.archive, a.mode))
    ss = sessions(a.archive)
    if ss:
        text += "\nImprover sessions (post hoc audit of the replies):\n" + "\n".join(
            f"  {k}: {v['sessions']} sessions, {v['overflowed']} overflowed the context, {v['bare_keep_base']} bare KEEP_BASE, "
            f"{v['ended_with_question']} ended with a question" for k, v in sorted(ss.items())) + \
            f"\n  all: {sum(v['sessions'] for v in ss.values())} sessions, {sum(v['overflowed'] for v in ss.values())} overflowed\n"
    rp = replays(a.archive)
    if rp["pairs"]:
        text += (f"\nSame-tree replays (post hoc): {rp['pairs']} pairs of rollouts of one tree on one task; {rp['exact']} repeat "
                 f"exactly (outcome, calls, patch size, seconds within 2 s); {rp['same_outcome']} have the same outcome.\n")
    print(text, end="")
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(f"<!-- eval/analysis/h2_read.py {a.archive} --mode {a.mode} -->\n" + text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
