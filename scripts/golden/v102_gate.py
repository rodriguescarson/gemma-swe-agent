"""The pre-registered decision of docs/eval/V10_2_EVAL.md (sections 5-7), computed, never read by eye (SPEC_v10_2 E7).

    .venv/bin/python scripts/golden/v102_gate.py L101 L102 F101 F102 [CHAIN101 CHAIN102] \
        [--canary DIR ...] [--extra-run DIR ...] [--holdout-lines N] [--precondition-skipped TEXT ...] [--out DIR]

Each argument is a golden run directory. The paired comparisons are summary.compare (the same code as `summary.py
compare`; the chain pair with --pair-by-task). Canary runs (v10.2 only) count toward G3's crash classes and the spend;
--extra-run adds any other run of this evaluation to the spend (e.g. a v10.1 canary, if one was made).

Verdict (section 7):
  1. INCONCLUSIVE (instrument): a precondition was skipped; a compare refused (more than 5 % infra_error after the one
     --resume, an interrupted run, mixed providers or clocks); more than 3 of a suite's tasks dropped from its gating
     metric; the arms' settings differ in anything but the bundle; a gating run not on the model clock (P2); the
     holdout log grew past --holdout-lines; or the billed spend of every run passed $4.00.
  2. SHIP-TO-POD: G1-G6 all pass and the chain (if it ran) does not veto.
  3. NOT READY otherwise, naming every failing gate.
Gates (v10.2 minus v10.1, compare's mean_diff over paired cases):
  G1 l_all_gold_files_named diff >= +0.10; G2 f_hidden_pass diff >= -0.05; G3 no crash class in a v10.2 run that no
  v10.1 run of this evaluation shows, and x_crash totals not higher per suite; G4 l_files_named_n diff <= +1.0; G5 per
  suite (L, F) each of x_invented_tool_calls, x_bare_helper_calls, x_malformed_calls, x_text_tool_calls,
  x_compaction_exceedances, x_runaway_outputs: v10.2 total <= v10.1 total + 1; G6 l_repro_valid diff x n >= -3;
  veto: chain f_hidden_pass diff <= -0.10.
Writes OUT/v102_gate.json and v102_gate.md (default OUT: the L102 run dir). Exit 0 always when it could decide; 2 on
unreadable input.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import summary as SM  # noqa: E402

EPS = 1e-9
SPEND_CAP = 4.00
MAX_DROPPED = 3
G1_MIN, G2_MIN, G4_MAX, G5_SLACK, G6_MIN, VETO_MAX = 0.10, -0.05, 1.0, 1, -3.0, -0.10
G5_METRICS = ("x_invented_tool_calls", "x_bare_helper_calls", "x_malformed_calls", "x_text_tool_calls",
              "x_compaction_exceedances", "x_runaway_outputs")
# run.json settings the two arms of a pair must share (the bundle is the only allowed difference)
PAIR_SETTINGS = ("suite", "split", "endpoint", "upstream_model", "or_provider", "upstream_extra", "seed_mode", "samples",
                 "l4_scale", "l4_clock", "dataset_sha", "task_filter", "agent_env", "faithful_env", "harness_verify",
                 "budgets")
CHAIN_SKIP = ("dataset_sha",)    # each chain arm's dataset carries its own locator's plans by design
HOLDOUT_LOG = os.path.join(ROOT, "eval", "golden", "holdout_log.jsonl")


def _read_json(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def run_info(run_dir):
    """{run, spent_usd, crash_classes, statuses} of one run directory, from run.json and the flat case records."""
    run = _read_json(os.path.join(run_dir, "run.json"))
    if not isinstance(run, dict):
        raise ValueError("no run.json in %s" % run_dir)
    crashes, statuses = collections.Counter(), collections.Counter()
    for fp in sorted(glob.glob(os.path.join(run_dir, "cases", "*.json"))):
        d = _read_json(fp) or {}
        statuses[d.get("status") or "?"] += 1
        if d.get("crash_class"):
            crashes[d["crash_class"]] += 1
    spent = run.get("spent_usd")
    return {"dir": run_dir, "run": run, "spent_usd": float(spent or 0.0), "crash_classes": dict(crashes),
            "statuses": dict(statuses)}


def _setting(run, k):
    v = run.get(k)
    if k == "l4_clock":
        return v or "wall"
    return v


def settings_diff(ra, rb, skip=()):
    return ["%s: %r vs %r" % (k, _setting(ra, k), _setting(rb, k)) for k in PAIR_SETTINGS
            if k not in skip and _setting(ra, k) != _setting(rb, k)]


def _m(C, name):
    return ((C or {}).get("metrics") or {}).get(name) or {}


def _expected_tasks(run):
    tf = run.get("task_filter")
    return len(tf) if isinstance(tf, list) and tf else None


def decide(inp):
    """The verdict from already computed inputs (pure; tests drive it with synthetic compares). inp:
    {"L": {"compare", "why", "base", "cand"}, "F": {...}, "chain": {...} | None, "canaries": [info], "extra": [info],
     "holdout_lines": int, "holdout_baseline": int, "preconditions_skipped": [str]}
    where compare is a summary.compare result (or None when it refused, with the reasons in why) and base/cand are
    run_info dicts."""
    inconc, gates = [], collections.OrderedDict()
    for s in inp.get("preconditions_skipped") or []:
        inconc.append("precondition skipped: %s" % s)
    pairs = [("L", inp["L"]), ("F", inp["F"])] + ([("chain", inp["chain"])] if inp.get("chain") else [])
    for name, P in pairs:
        for w in P.get("why") or []:
            inconc.append("%s compare refused: %s" % (name, w))
        d = settings_diff(P["base"]["run"], P["cand"]["run"], CHAIN_SKIP if name == "chain" else ())
        if d:
            inconc.append("%s arms differ in more than the bundle: %s" % (name, "; ".join(d)))
        for arm in ("base", "cand"):
            r = P[arm]["run"]
            if _setting(r, "l4_clock") != "model":
                inconc.append("%s %s run %s is on the %s clock (P2: no paid run without the model clock)" % (
                    name, arm, r.get("run_id"), _setting(r, "l4_clock")))
    # dropped cases (section 6): a suite's gating metric paired on fewer than its tasks minus 3
    dropped = {}
    for name, P, metric in (("L", inp["L"], "l_all_gold_files_named"), ("F", inp["F"], "f_hidden_pass")):
        exp = _expected_tasks(P["base"]["run"])
        n = _m(P.get("compare"), metric).get("n")
        if exp is not None and n is not None:
            dropped[name] = exp - n
            if exp - n > MAX_DROPPED:
                inconc.append("%s: %d of %d tasks dropped from %s (> %d)" % (name, exp - n, exp, metric, MAX_DROPPED))
    hb, hl = int(inp.get("holdout_baseline") or 0), int(inp.get("holdout_lines") or 0)
    if hl > hb:
        inconc.append("holdout log grew: %d lines, %d before the evaluation" % (hl, hb))
    runs = [P[a] for _, P in pairs for a in ("base", "cand")] + list(inp.get("canaries") or []) + \
        list(inp.get("extra") or [])
    seen, spend = set(), 0.0
    for r in runs:
        key = os.path.realpath(r["dir"]) if r.get("dir") else id(r)
        if key in seen:
            continue
        seen.add(key)
        spend += r["spent_usd"]
    spend_ok = spend <= SPEND_CAP + EPS
    if not spend_ok:
        inconc.append("billed spend $%.4f over the $%.2f cap" % (spend, SPEND_CAP))

    L, F, CH = inp["L"].get("compare"), inp["F"].get("compare"), (inp.get("chain") or {}).get("compare")

    def gate(name, ok, detail):
        gates[name] = {"pass": bool(ok), "detail": detail}

    g1 = _m(L, "l_all_gold_files_named").get("mean_diff")
    gate("G1", g1 is not None and g1 >= G1_MIN - EPS, {"diff": g1, "threshold": ">= %+.2f" % G1_MIN,
                                                       "n": _m(L, "l_all_gold_files_named").get("n")})
    g2 = _m(F, "f_hidden_pass").get("mean_diff")
    gate("G2", g2 is not None and g2 >= G2_MIN - EPS, {"diff": g2, "threshold": ">= %+.2f" % G2_MIN,
                                                       "n": _m(F, "f_hidden_pass").get("n")})
    old = set()
    for _, P in pairs:
        old |= set(P["base"]["crash_classes"])
    new_runs = [P["cand"] for _, P in pairs] + list(inp.get("canaries") or [])
    new = set()
    for r in new_runs:
        new |= set(r["crash_classes"])
    new_classes = sorted(new - old)
    x_up = {}
    for name, C in (("L", L), ("F", F), ("chain", CH)):
        if C is None:
            continue
        m = _m(C, "x_crash")
        if (m.get("cand_total") or 0) > (m.get("base_total") or 0) + EPS:
            x_up[name] = [m.get("base_total"), m.get("cand_total")]
    gate("G3", not new_classes and not x_up, {"new_crash_classes": new_classes, "x_crash_higher": x_up,
                                              "v101_classes": sorted(old), "v102_classes": sorted(new)})
    g4 = _m(L, "l_files_named_n").get("mean_diff")
    gate("G4", g4 is not None and g4 <= G4_MAX + EPS, {"diff": g4, "threshold": "<= %+.1f" % G4_MAX})
    over = {}
    for name, C in (("L", L), ("F", F)):
        for x in G5_METRICS:
            m = _m(C, x)
            b, c = m.get("base_total"), m.get("cand_total")
            if b is None or c is None:
                over.setdefault(name, {})[x] = "missing"
            elif c > b + G5_SLACK + EPS:
                over.setdefault(name, {})[x] = [b, c]
    gate("G5", not over, {"over": over, "rule": "v10.2 total <= v10.1 total + %d" % G5_SLACK})
    m6 = _m(L, "l_repro_valid")
    g6 = None if m6.get("mean_diff") is None or m6.get("n") is None else m6["mean_diff"] * m6["n"]
    gate("G6", g6 is not None and g6 >= G6_MIN - EPS, {"diff_x_n": g6, "diff": m6.get("mean_diff"), "n": m6.get("n"),
                                                       "threshold": ">= %+.0f" % G6_MIN})
    chain = {"ran": CH is not None}
    veto = False
    if CH is not None:
        vd = _m(CH, "f_hidden_pass").get("mean_diff")
        veto = vd is not None and vd <= VETO_MAX + EPS
        chain.update(diff=vd, n=_m(CH, "f_hidden_pass").get("n"), veto=veto, threshold="<= %+.2f vetoes" % VETO_MAX)
    elif inp.get("chain_skipped_reason"):
        chain["not_run"] = inp["chain_skipped_reason"]
    failing = [g for g, v in gates.items() if not v["pass"]]
    if inconc:
        verdict = "INCONCLUSIVE (instrument)"
    elif not failing and not veto:
        verdict = "SHIP-TO-POD"
    else:
        verdict = "NOT READY"
    return collections.OrderedDict([
        ("schema", "v102-gate-v1"), ("verdict", verdict), ("label", "PROXY"),
        ("failing_gates", failing), ("chain_veto", veto), ("inconclusive_reasons", inconc), ("gates", gates),
        ("chain", chain), ("dropped", dropped), ("spend_usd", round(spend, 6)), ("spend_ok", spend_ok),
        ("runs", [{"dir": r["dir"], "run_id": r["run"].get("run_id"), "bundle_sha": r["run"].get("bundle_sha"),
                   "spent_usd": r["spent_usd"], "statuses": r["statuses"], "crash_classes": r["crash_classes"]}
                  for r in runs])])


def gate_md(G):
    lines = ["# v10.2 vs v10.1 gate (PROXY): **%s**" % G["verdict"], "",
             "Computed by scripts/golden/v102_gate.py from docs/eval/V10_2_EVAL.md sections 6-7.", ""]
    if G["inconclusive_reasons"]:
        lines += ["Instrument problems:", ""] + ["- " + r for r in G["inconclusive_reasons"]] + [""]
    lines += ["| gate | pass | detail |", "|---|---|---|"]
    for g, v in G["gates"].items():
        lines.append("| %s | %s | %s |" % (g, "PASS" if v["pass"] else "FAIL", json.dumps(v["detail"], sort_keys=True)))
    lines += ["", "Chain: %s" % json.dumps(G["chain"], sort_keys=True),
              "Dropped tasks per suite: %s" % json.dumps(G["dropped"], sort_keys=True),
              "Billed spend over every run: $%.4f (cap $%.2f, %s)" % (G["spend_usd"], SPEND_CAP,
                                                                      "ok" if G["spend_ok"] else "OVER"), ""]
    return "\n".join(lines) + "\n"


def _pair(base, cand, pair_by_task=False):
    why, C = SM.compare(base, cand, False, pair_by_task)
    return {"compare": C, "why": why, "base": run_info(base), "cand": run_info(cand)}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="v102_gate.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("runs", nargs="+", help="L101 L102 F101 F102 [CHAIN101 CHAIN102]")
    ap.add_argument("--canary", action="append", default=[], help="a v10.2 canary run dir (G3 and spend)")
    ap.add_argument("--extra-run", action="append", default=[], help="any other run of this evaluation (spend)")
    ap.add_argument("--holdout-log", default=HOLDOUT_LOG)
    ap.add_argument("--holdout-lines", type=int, default=0, help="holdout log lines before the evaluation")
    ap.add_argument("--precondition-skipped", action="append", default=[])
    ap.add_argument("--chain-skipped", default=None, help="why the chain did not run (e.g. 'budget')")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    if len(a.runs) not in (4, 6):
        print("v102_gate: give 4 run dirs (L101 L102 F101 F102) or 6 (plus CHAIN101 CHAIN102)", file=sys.stderr)
        return 2
    try:
        inp = {"L": _pair(a.runs[0], a.runs[1]), "F": _pair(a.runs[2], a.runs[3]),
               "chain": _pair(a.runs[4], a.runs[5], True) if len(a.runs) == 6 else None,
               "canaries": [run_info(d) for d in a.canary], "extra": [run_info(d) for d in a.extra_run],
               "holdout_baseline": a.holdout_lines, "preconditions_skipped": a.precondition_skipped,
               "chain_skipped_reason": a.chain_skipped}
    except ValueError as e:
        print("v102_gate: %s" % e, file=sys.stderr)
        return 2
    try:
        with open(a.holdout_log, encoding="utf-8") as f:
            inp["holdout_lines"] = sum(1 for x in f if x.strip())
    except OSError:
        inp["holdout_lines"] = 0
    G = decide(inp)
    out = a.out or a.runs[1]
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "v102_gate.json"), "w", encoding="utf-8") as f:
        json.dump(G, f, indent=1, sort_keys=False, default=str)
        f.write("\n")
    with open(os.path.join(out, "v102_gate.md"), "w", encoding="utf-8") as f:
        f.write(gate_md(G))
    print("v10.2 gate (PROXY): %s%s%s" % (
        G["verdict"], (" (failing: %s)" % ", ".join(G["failing_gates"])) if G["failing_gates"] else "",
        " (chain veto)" if G["chain_veto"] else ""))
    for r in G["inconclusive_reasons"]:
        print("  instrument: " + r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
