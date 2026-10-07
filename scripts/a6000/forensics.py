"""Failure forensics driver (scripts/a6000/PROMPTS.md P5): reads the stored traces of stage 1a (v4h2, v6p, v6p-think), P4 (v5h2) and the v6p-b probe, and writes
docs/a6000/forensics_generated.md with the tables of sections 1 (tool and helper errors), 3 (loops), 4 (empty patches), 5 (v6p pipeline) and 6 (L4 losses).
Read-only; the logic is in forensics_lib.py (tests/test_a6000_forensics.py).

    python scripts/a6000/forensics.py [--out docs/a6000/forensics_generated.md]"""
import argparse
import collections
import glob
import json
import os
import re
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import forensics_lib as fx  # noqa: E402

G4 = Path.home() / "g4"
IDS50 = [l.strip() for l in open(ROOT / "data" / "heldout1k" / "s200_valid_ids.txt") if l.strip()][:50]


def load():
    traces, rows = {}, {}
    for arm in ("v4h2", "v6p", "v6p-think"):
        traces[arm], rows[arm] = {}, {}
        for t in IDS50:
            fs = glob.glob(str(G4 / "runs" / "p2" / "items" / arm / t / "traces" / "trace_*.json"))
            rf = G4 / "runs" / "p2" / "items" / arm / t / "task_results.jsonl"
            if fs and rf.exists():
                traces[arm][t] = fx.load_trace(fs[0])
                r = json.loads(rf.read_text().splitlines()[0])
                rows[arm][t] = {"error": r.get("error"), "patch_size": r.get("agent_patch_size") or 0, "resolved": bool(r.get("resolved")), "calls": r.get("tool_calls")}
    traces["v5h2"], rows["v5h2"] = {}, {}
    for line in (G4 / "runs" / "p4" / "results.jsonl").read_text().splitlines():
        r = json.loads(line)
        f = G4 / "runs" / "p4" / "results" / "traces" / f"trace_{r['id']}.json"
        if f.exists():
            traces["v5h2"][r["id"]] = fx.load_trace(f)
            rows["v5h2"][r["id"]] = {"error": r.get("err"), "patch_size": len(r.get("patch") or ""), "resolved": bool(r.get("resolved")), "calls": r.get("calls")}
    traces["v6p-b (probe)"], rows["v6p-b (probe)"] = {}, {}
    for f in glob.glob(str(G4 / "runs" / "p2" / "probe_v6p-b_T2" / "v6p-b" / "*" / "traces" / "trace_*.json")):
        t = os.path.basename(f)[6:-5]
        traces["v6p-b (probe)"][t] = fx.load_trace(f)
        rf = Path(f).parents[1] / "task_results.jsonl"
        r = json.loads(rf.read_text().splitlines()[0]) if rf.exists() else {}
        rows["v6p-b (probe)"][t] = {"error": r.get("error"), "patch_size": r.get("agent_patch_size") or 0, "resolved": bool(r.get("resolved")), "calls": r.get("tool_calls")}
    return traces, rows


def md_cell(s, n=120):
    return str(s).replace("\n", " ")[:n].replace("|", "\\|")


def section1(traces, rows):
    out = ["## 1. Tool and helper errors (every tool call of every trace, classified)", ""]
    tab = fx.mechanism_table(traces)
    for arm, t in tab.items():
        total = sum(r["calls"] for r in t.values())
        out += [f"### {arm}: {total} tool calls in {len(traces[arm])} tasks", "", "| mechanism | owner | calls | tasks | example task | call | reply (first 300 chars) |", "|---|---|---|---|---|---|---|"]
        for mech, r in sorted(t.items(), key=lambda kv: -kv[1]["calls"]):
            ex = r["example"]
            out.append(f"| {mech} | {r['owner']} | {r['calls']} | {len(r['tasks'])} | {ex['task']} | `{md_cell(ex['call'], 100)}` | `{md_cell(ex['reply'], 300)}` |")
        leaks = {t: fx.leaked_tool_calls(tr) for t, tr in traces[arm].items()}
        nl = sum(leaks.values())
        crash = [t for t, r in rows[arm].items() if r["error"] and ("TaskGroup" in r["error"] or "Sandbox execution error" in r["error"])]
        verify = [t for t, r in rows[arm].items() if r["error"] and "Failed to apply test_patch" in r["error"]]
        out += ["", f"- raw tool-call syntax leaked into the model's text (the server's gemma4 parser did not produce a tool call): {nl} messages in {sum(1 for v in leaks.values() if v)} tasks",
                f"- task-level harness crashes (sandbox execution error): {len(crash)} {crash}", f"- task-level verification failures (agent patch collides with the test patch): {len(verify)} {verify}", ""]
    # distinct helper usage errors
    out += ["### Distinct helper usage / argument errors (ours), all arms", "", "| helper | call shape (numbers -> N, paths -> FILE) | calls | tasks | example | what the prompt shows |", "|---|---|---|---|---|---|"]
    shapes = collections.defaultdict(lambda: {"calls": 0, "tasks": set(), "ex": None})
    for arm, by in traces.items():
        for tid, tr in by.items():
            for c in fx.iter_calls(tr):
                v = fx.classify(c.fn, c.args, c.payload)
                if v.mechanism.startswith("helper usage/argument error"):
                    cmd = str(c.args.get("command", ""))
                    m = re.search(r"/tmp/swe/(\w+)\.py(.*)", cmd, re.S)
                    tail = re.sub(r"\S+\.py", "FILE", (m.group(2) if m else "")).strip()
                    tail = re.sub(r"\d+", "N", tail)[:50]
                    k = (m.group(1) if m else "?", tail)
                    shapes[k]["calls"] += 1; shapes[k]["tasks"].add(f"{arm}/{tid}")
                    if shapes[k]["ex"] is None:
                        shapes[k]["ex"] = cmd[:100]
    hint = {"view": "`view.py path/to/file.py START END` (two numbers) next to `edit.py --lines 120-135` (a dash range): the model generalises the dash form",
            "test": "`test.py --target <test file>`", "edit": "`edit.py FILE <<'EOF'` with the SEARCH/REPLACE block", "locate": "`locate.py \"<identifiers ...>\"`", "check": "`check.py --mode preflight`"}
    for (h, shape), r in sorted(shapes.items(), key=lambda kv: -kv[1]["calls"]):
        out.append(f"| {h}.py | `{md_cell(shape, 50)}` | {r['calls']} | {len(r['tasks'])} | `{md_cell(r['ex'], 90)}` | {hint.get(h, '')} |")
    return "\n".join(out) + "\n"


def section3(traces):
    out = ["## 3. Loops (an identical call repeated 5 or more times in a row)", ""]
    for arm, by in traces.items():
        loops = [(t, l) for t, tr in by.items() for l in fx.find_loops(tr)]
        by_kind = collections.Counter((l.reply_kind, l.owner) for _, l in loops)
        out += [f"### {arm}: {len(loops)} loops in {len({t for t, _ in loops})} of {len(by)} tasks; by stage {dict(collections.Counter(l.author for _, l in loops))}", "",
                "| what the tool returned each time | owner | loops | identical replies | longest | example task / stage / call | text between calls |", "|---|---|---|---|---|---|---|"]
        for (kind, owner), n in by_kind.most_common():
            ls = [(t, l) for t, l in loops if l.reply_kind == kind]
            t, l = max(ls, key=lambda x: x[1].count)
            ident = sum(1 for _, x in ls if x.identical_replies)
            between = (l.text_between[0][:90] if l.text_between else "(none)")
            out.append(f"| {kind} | {owner} | {n} | {ident} | x{l.count} | {t} / {l.author} / `{md_cell(l.args, 80)}` | {md_cell(between, 90)} |")
        out.append("")
    return "\n".join(out) + "\n"


def section4(traces, rows):
    out = ["## 4. Empty patches: which stage ended the task", ""]
    for arm, by in traces.items():
        empties = [t for t, r in rows[arm].items() if not r["patch_size"] and t in by]
        causes = collections.defaultdict(list)
        for t in empties:
            causes[re.sub(r"\(\d+ refused.*\)|after \d+ successful edit\(s\)", "", fx.empty_patch_cause(by[t], rows[arm][t])).strip()].append(t)
        out += [f"### {arm}: {len(empties)} empty patches of {len(by)} tasks", "", "| cause | tasks | ids |", "|---|---|---|"]
        for cause, ts in sorted(causes.items(), key=lambda kv: -len(kv[1])):
            out.append(f"| {cause} | {len(ts)} | {' '.join(sorted(ts))[:300]} |")
        out.append("")
    return "\n".join(out) + "\n"


def section5(traces):
    out = ["## 5. v6p pipeline check (per task; v6p-think runs the same pipeline)", ""]
    for arm in ("v6p", "v6p-think", "v6p-b (probe)"):
        by = traces.get(arm, {})
        if not by:
            continue
        ps = {t: fx.v6p_pipeline(tr) for t, tr in by.items()}
        n = len(ps)
        steps = collections.OrderedDict()
        for p in ps.values():
            for name, v in p["checks"]:
                steps.setdefault(name, 0)
                steps[name] += bool(v)
        first = collections.Counter(p["first_broken"] or "nothing broken" for p in ps.values())
        how = collections.Counter(p["repro_run_how"] or "never ran it" for p in ps.values())
        sr = collections.Counter(p["select_repro"] or ("no report" if not p["select_ran"] else "?") for p in ps.values())
        picks = collections.Counter(p["pick"] or "-" for p in ps.values())
        diffs = collections.Counter(p["nonempty_diffs"] for p in ps.values())
        out += [f"### {arm}: {n} tasks", "", "| step | tasks where it held |", "|---|---|"] + [f"| {k} | {v}/{n} |" for k, v in steps.items()]
        out += ["", f"- first broken step: {dict(first.most_common())}", f"- how the locator ran the reproduction: {dict(how)} (the prompt says `python3 /tmp/swe/repro.py`; a direct `python3 /tmp/repro.py` skips the helper's PYTHONPATH and status line)",
                f"- select_best's own repro verdict: {dict(sr)}", f"- PICK: {dict(picks)}; non-empty candidate diffs per task: {dict(sorted(diffs.items()))}", ""]
        worst = first.most_common(1)[0][0]
        out += [f"- tasks whose first broken step is `{worst}`: {' '.join(sorted(t for t, p in ps.items() if (p['first_broken'] or 'nothing broken') == worst))[:400]}", ""]
    return "\n".join(out) + "\n"


def _flags(tr):
    c = collections.Counter()
    for call in fx.iter_calls(tr):
        v = fx.classify(call.fn, call.args, call.payload)
        if v.mechanism != "ok":
            c[v.mechanism] += 1
    return c


def section6(traces, rows):
    out = ["## 6. The L4 losses: where the trajectories diverge", ""]
    l4 = {json.loads(l)["id"]: json.loads(l) for l in open(ROOT / "eval" / "kaggle" / "g4-l4-v4h2g-p312" / "results.jsonl")}
    l4tr = {}
    for f in glob.glob(str(G4 / "l4ref" / "tr" / "traces" / "trace_*.json")):
        l4tr[os.path.basename(f)[6:-5]] = fx.load_trace(f)
    p4 = rows["v5h2"]
    lost = [t for t in l4 if l4[t]["resolved"] and t in p4 and not p4[t]["resolved"]]
    out += [f"### Public tasks v4h2g solved on Kaggle L4 and v5h2 did not in P4: {len(lost)} ({' '.join(lost)})", "",
            "| task | L4 calls / secs | P4 calls / secs / patch | first differing call (after setup) | L4 call | P4 call | P4 non-ok mechanisms | L4 non-ok mechanisms |", "|---|---|---|---|---|---|---|---|"]
    for t in lost:
        if t not in l4tr or t not in traces["v5h2"]:
            continue
        d = fx.first_divergence(l4tr[t], traces["v5h2"][t])
        fp, fl = _flags(traces["v5h2"][t]), _flags(l4tr[t])
        out.append(f"| {t} | {l4[t]['calls']} / {l4[t]['secs']:.0f} | {p4[t]['calls']} / {rows['v5h2'][t].get('secs', '?') if 'secs' in rows['v5h2'][t] else ''}{p4[t]['patch_size']} chars | {d['index']} of {d['len_a']} / {d['len_b']} | "
                   f"{d['a']['author'] + ': `' + md_cell(d['a']['call'], 70) + '`' if d['a'] else '-'} | {d['b']['author'] + ': `' + md_cell(d['b']['call'], 70) + '`' if d['b'] else '-'} | "
                   f"{md_cell(dict(fp.most_common(4)), 160)} | {md_cell(dict(fl.most_common(4)), 120)} |")
    a, b = traces["v4h2"], traces["v6p"]
    s1 = [t for t in IDS50 if rows["v4h2"].get(t, {}).get("resolved") and t in rows["v6p"] and not rows["v6p"][t]["resolved"]]
    out += ["", f"### Stage 1a tasks v4h2 solved and v6p did not: {len(s1)} ({' '.join(s1)})", "",
            "| task | v4h2 calls / patch | v6p calls / patch / error | first differing call | v4h2 call | v6p call | v6p non-ok mechanisms | v6p pipeline first broken |", "|---|---|---|---|---|---|---|---|"]
    for t in s1:
        d = fx.first_divergence(a[t], b[t])
        fb = fx.v6p_pipeline(b[t])["first_broken"]
        out.append(f"| {t} | {rows['v4h2'][t]['calls']} / {rows['v4h2'][t]['patch_size']} | {rows['v6p'][t]['calls']} / {rows['v6p'][t]['patch_size']} / {md_cell(rows['v6p'][t]['error'] or '-', 40)} | {d['index']} of {d['len_a']} / {d['len_b']} | "
                   f"{d['a']['author'] + ': `' + md_cell(d['a']['call'], 60) + '`' if d['a'] else '-'} | {d['b']['author'] + ': `' + md_cell(d['b']['call'], 60) + '`' if d['b'] else '-'} | {md_cell(dict(_flags(b[t]).most_common(4)), 150)} | {fb or 'nothing'} |")
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=str(ROOT / "docs" / "a6000" / "forensics_generated.md"))
    a = ap.parse_args(argv)
    traces, rows = load()
    head = ["# Failure forensics: generated tables (scripts/a6000/forensics.py, read-only)", "",
            f"Inputs: stage 1a {', '.join(f'{k} {len(v)} tasks' for k, v in traces.items() if k in ('v4h2', 'v6p', 'v6p-think'))}; P4 v5h2 {len(traces['v5h2'])} tasks; v6p-b probe {len(traces['v6p-b (probe)'])} tasks. "
            "Owner: ours = our helper scripts / prompts / bundle wiring; harness = the competition harness, ADK or the vLLM gemma4 tool parser; model = the model's own choices.", ""]
    text = "\n".join(head) + "\n" + section1(traces, rows) + "\n" + section3(traces) + "\n" + section4(traces, rows) + "\n" + section5(traces) + "\n" + section6(traces, rows)
    Path(a.out).write_text(text)
    print(f"wrote {a.out} ({len(text)} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
