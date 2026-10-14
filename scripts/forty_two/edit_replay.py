"""Lever 1 evidence (docs/forty_two/LEVERS.md): replay every edit_file call the model made on the box through v13's EDIT template.

    python scripts/forty_two/edit_replay.py [--runs p4_b1024 p4_v0t2] [--json OUT]

For each trace, file states start from the task snapshot (~/.cache/g4/ws/<id>/base, read only; copies go to a temp dir) and
follow the agent's real trajectory: every edit_file call is re-applied with swegemma's own engine (swegemma.edit.apply_replacement,
what the harness ran), and, on a copy of the same state, with v13's template filled with the same old/new text and run by bash.
A malformed call (vLLM's gemma4 parser swallowed old_string into new_string) is replayed with its intent: new_string minus the
swallowed tail (the parser leaves the rest of the string exact), and the old block located in the current file state from the
junk keys the parser produced (whitespace-insensitive, unique match only).
Outcome per call: same (template result byte-identical to edit_file's), refused (template wrote nothing; it prints why), differs.
Files later changed by a shell command are dropped from the replay (their state is unknown)."""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "tests"))
WS = Path.home() / ".cache" / "g4" / "ws"
MISSING = "mandatory input parameters are not present"
SLIP_TAIL = re.compile(r"[`\"']\s*,\s*old_string:\s*$")


def template():
    text = (ROOT / "submissions" / "v13" / "prompts" / "system.md").read_text()
    return [b for b in re.findall(r"```\n(.*?)```", text, re.S) if "<<'EDIT'" in b][0]


def fill(t, path, old, new):
    return t.replace("path/to/module.py", path).replace("<old lines, copied exactly>\n", old).replace("<new lines>\n", new)


def run_template(state: str, path: str, old: str, new: str):
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(state.encode())
        env = dict(os.environ, PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""))  # python3 = 3.12, as in the sandbox
        r = subprocess.run(["bash", "-c", fill(template(), path, old, new)], cwd=d, capture_output=True, text=True, timeout=60, env=env)
        return r.returncode, f.read_bytes().decode(), (r.stderr.strip().splitlines() or [""])[-1][:160]


def norm(s: str) -> str:
    return re.sub(r"[^0-9A-Za-z_]+", "", s)          # the parser ate delimiters, colons, commas and whitespace: compare the rest


def flat(v) -> str:
    if isinstance(v, dict):
        return "".join(k + flat(x) for k, x in v.items())
    if isinstance(v, list):
        return "".join(flat(x) for x in v)
    return "" if v is None else str(v)


def locate_old(state: str, junk: dict) -> str | None:
    """The unique block of whole lines in state whose letters, digits and underscores equal those of the junk keys and values
    the parser produced from the model's old block, in order."""
    target = norm(flat(junk))
    if len(target) < 8:
        return None
    lines = state.splitlines(keepends=True)
    hits = []
    for i in range(len(lines)):
        acc = ""
        for j in range(i, min(len(lines), i + 60)):
            acc += lines[j]
            n = norm(acc)
            if n == target:
                hits.append("".join(lines[i:j + 1]))
                break
            if len(n) > len(target) or not target.startswith(n):
                break
    return hits[0] if len(hits) == 1 else None


def replay_trace(task: str, trace: dict, apply_replacement):
    base = WS / task / "base"
    states, dead, out = {}, set(), []
    for s in trace.get("steps") or []:
        for c in s.get("tool_calls") or []:
            name, a = c.get("function_name"), c.get("arguments") or {}
            obs = str((s.get("observation") or {}).get("content") or "")
            if name == "run_command":
                cmd = str(a.get("command") or "")
                for p in list(states):
                    if p in cmd and re.search(r"sed -i|>|write_text|write_bytes|open\(|mv |cp |rm |git (checkout|restore|stash|apply)", cmd):
                        dead.add(p)
                continue
            if name == "write_file":
                fp = str(a.get("filepath") or "").removeprefix("/workspace/")
                if fp and obs.lstrip().startswith('{"status": "ok"'):
                    states[fp] = str(a.get("content") or "")
                continue
            if name != "edit_file":
                continue
            fp = str(a.get("filepath") or "").removeprefix("/workspace/")
            if not fp or fp in dead:
                continue
            if fp not in states:
                f = base / fp
                if not f.is_file():
                    continue
                states[fp] = f.read_bytes().decode(errors="replace")
            state = states[fp]
            malformed = MISSING in obs
            if malformed:
                if "new_string" not in a or "old_string" in a or not SLIP_TAIL.search(str(a["new_string"])):
                    out.append({"task": task, "file": fp, "kind": "malformed", "outcome": "not reconstructable"}); continue
                new = SLIP_TAIL.sub("", str(a["new_string"]))
                junk = {k: v for k, v in a.items() if k not in ("filepath", "new_string")}
                old = locate_old(state, junk)
                if old is None:
                    out.append({"task": task, "file": fp, "kind": "malformed", "outcome": "old block not located"}); continue
                rc, after, err = run_template(state, fp, old, new)
                out.append({"task": task, "file": fp, "kind": "malformed", "outcome": "applied" if rc == 0 else "refused",
                            "why": err if rc else "", "compiles": rc == 0})
                continue
            old, new = str(a.get("old_string") or ""), str(a.get("new_string") or "")
            try:
                ref = apply_replacement(state, old, new, filepath=fp)
            except ValueError:
                ref = None                                   # swegemma raises on "old_string not found" (the call failed live too)
            ok = obs.lstrip().startswith('{"status": "ok"')
            rc, after, err = run_template(state, fp, old, new)
            if ok and ref is None:
                dead.add(fp); out.append({"task": task, "file": fp, "kind": "state lost", "outcome": "skipped"}); continue
            if ok and not getattr(ref, "error_message", None):
                outcome = "same" if rc == 0 and after == ref.new_content else ("refused" if rc else "differs")
                out.append({"task": task, "file": fp, "kind": "ok:" + ref.strategy, "outcome": outcome, "why": err if rc else ""})
                states[fp] = ref.new_content
            else:
                out.append({"task": task, "file": fp, "kind": "failed", "outcome": "refused" if rc else "applied", "why": err if rc else ""})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", default=["p4_b1024", "p4_v0t2"])
    ap.add_argument("--json")
    a = ap.parse_args()
    from swegemma.edit import apply_replacement
    report = {}
    for run in a.runs:
        rows = []
        for f in sorted((ROOT / "eval" / "a6000" / "results" / run / "results" / "traces").glob("trace_*.json")):
            task = f.stem[len("trace_"):]
            rows += replay_trace(task, json.loads(f.read_text()), apply_replacement)
        report[run] = rows
        tally = collections.Counter((r["kind"].split(":")[0] if r["kind"].startswith("ok") else r["kind"], r["outcome"]) for r in rows)
        strat = collections.Counter((r["kind"], r["outcome"]) for r in rows if r["kind"].startswith("ok"))
        print(f"## {run}: {len(rows)} edit_file calls replayed")
        for k, v in sorted(tally.items()):
            print(f"- {k[0]} -> {k[1]}: {v}")
        print("  successful edit_file calls by the harness strategy: " + ", ".join(f"{k[0][3:]} -> {k[1]} {v}" for k, v in sorted(strat.items())))
        why = collections.Counter(r["why"] for r in rows if r["outcome"] == "refused" and r["kind"].startswith("ok"))
        if why:
            print("  why the template refused successful edit_file calls: " + "; ".join(f"{k} ({v})" for k, v in why.most_common(5)))
        mal = [r for r in rows if r["kind"] == "malformed"]
        if mal:
            by_task = collections.defaultdict(collections.Counter)
            for r in mal:
                by_task[r["task"]][r["outcome"]] += 1
            print("  malformed calls by task: " + "; ".join(f"{t} " + ", ".join(f"{k} {v}" for k, v in c.items()) for t, c in sorted(by_task.items())))
    if a.json:
        Path(a.json).write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
