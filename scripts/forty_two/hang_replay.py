"""Lever 2 evidence (docs/forty_two/LEVERS.md): every command that hung on the box until the per-command timeout (or the cap),
re-run on the Mac with a 60 s bound, in a copy of the task snapshot brought to the state the agent had at that moment.

    python scripts/forty_two/hang_replay.py [--runs p4_b1024 p4_v0t2] [--bound 60] [--json OUT]

State: ~/.cache/g4/ws/<id>/base (read only) copied to a temp dir, then the agent's earlier successful write_file / edit_file calls
(swegemma's own edit engine) and its `cat > file <<EOF` commands, in trace order. Interpreter: the task's offline venv
~/.cache/g4/kpar/<repo>/bin first on PATH (the snapshot's own package imports from the working directory). A watchdog kills a
command whose resident memory passes 3 GB (an infinite loop that appends); that counts as still running.
Outcome per command: finished (seconds, exit code) or still running at the bound."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
G4 = Path.home() / ".cache" / "g4"
REPO = {"fastapi": "fastapi", "rich": "rich", "requests": "requests"}
CAT_RE = re.compile(r"^\s*cat\s+>\s*\S+\s+<<\s*'?(\w+)'?\s*\n", re.S)


def hung_commands(run: str):
    for f in sorted((ROOT / "eval" / "a6000" / "results" / run / "results" / "traces").glob("trace_*.json")):
        task = f.stem[len("trace_"):]
        steps = json.loads(f.read_text())["steps"]
        for k, s in enumerate(steps):
            for c in s.get("tool_calls") or []:
                ob = s.get("observation")
                if c["function_name"] == "run_command" and ("TimeoutExceeded" in str((ob or {}).get("content"))[:300]
                                                            or (ob is None and k == len(steps) - 1)):
                    yield task, k, str(c["arguments"].get("command") or "")


def unescape(s: str) -> str:
    """The box's edit engine has an 'unescaped' tier the Mac's adk_eval_core 0.1.0 lacks: the model's over-escaped quotes."""
    return s.replace('\\"', '"').replace("\\'", "'")


def prepare(task: str, upto: int, steps: list, dst: Path, apply_replacement):
    """-> files whose recorded edit could not be re-applied (the replayed state is then incomplete)."""
    lost = []
    shutil.copytree(G4 / "ws" / task / "base", dst, symlinks=True, ignore=shutil.ignore_patterns(".git"))
    for s in steps[:upto]:
        for c in s.get("tool_calls") or []:
            a, obs = c.get("arguments") or {}, str((s.get("observation") or {}).get("content") or "")
            ok = obs.lstrip().startswith('{"status": "ok"')
            fp = str(a.get("filepath") or "").removeprefix("/workspace/")
            if c["function_name"] == "write_file" and ok and fp and not fp.startswith("/"):
                (dst / fp).parent.mkdir(parents=True, exist_ok=True); (dst / fp).write_text(str(a.get("content") or ""))
            elif c["function_name"] == "edit_file" and ok and (dst / fp).is_file():
                cur = (dst / fp).read_text()
                for o, n in ((a["old_string"], a["new_string"]), (unescape(a["old_string"]), unescape(a["new_string"]))):
                    try:
                        (dst / fp).write_text(apply_replacement(cur, o, n, filepath=fp).new_content); break
                    except Exception:
                        continue
                else:
                    lost.append(fp)
            elif c["function_name"] == "run_command" and CAT_RE.match(str(a.get("command") or "")):
                cmd = str(a["command"]).replace("/tmp/", str(dst) + "/_tmp/")
                (dst / "_tmp").mkdir(exist_ok=True)
                subprocess.run(["bash", "-c", cmd], cwd=dst, capture_output=True, timeout=30)
    return lost


def rss_mb(pid: int) -> float:
    r = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip() or 0) / 1024
    except ValueError:
        return 0.0


def run_bounded(cmd: str, cwd: Path, repo: str, bound: float):
    env = dict(os.environ, PATH=str(G4 / "kpar" / repo / "bin") + os.pathsep + os.environ.get("PATH", ""), PYTHONDONTWRITEBYTECODE="1")
    cmd = cmd.replace("/tmp/", str(cwd) + "/_tmp/")
    t0 = time.monotonic()
    p = subprocess.Popen(["bash", "-c", cmd], cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         start_new_session=True)
    peak, why = 0.0, None
    while p.poll() is None:
        el = time.monotonic() - t0
        peak = max(peak, rss_mb(p.pid))
        if el >= bound:
            why = "bound"
        elif peak > 3000:
            why = "memory"
        if why:
            os.killpg(p.pid, 9); p.wait()
            return {"finished": False, "secs": round(el, 1), "killed_by": why, "peak_rss_mb": round(peak)}
        time.sleep(0.5)
    out, err = p.communicate()
    return {"finished": True, "secs": round(time.monotonic() - t0, 1), "exit": p.returncode, "stdout": out[-300:], "stderr": err[-300:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", default=["p4_b1024", "p4_v0t2"])
    ap.add_argument("--bound", type=float, default=60.0)
    ap.add_argument("--json")
    ap.add_argument("--tasks", nargs="*")
    a = ap.parse_args()
    from swegemma.edit import apply_replacement
    rows = []
    for run in a.runs:
        for task, k, cmd in hung_commands(run):
            if a.tasks and task not in a.tasks:
                continue
            steps = json.loads((ROOT / "eval" / "a6000" / "results" / run / "results" / "traces" / f"trace_{task}.json").read_text())["steps"]
            with tempfile.TemporaryDirectory() as d:
                ws = Path(d) / "workspace"
                lost = prepare(task, k, steps, ws, apply_replacement)
                res = run_bounded(cmd, ws, REPO[task.split("_")[0]], a.bound)
            row = {"run": run, "task": task, "step": k, "command": cmd[:120], "state_incomplete": lost, **res}
            rows.append(row)
            print(json.dumps(row), flush=True)
    n_still = sum(not r["finished"] for r in rows)
    print(f"SUMMARY {len(rows)} recorded hangs re-run with a {a.bound:.0f} s bound: still running at the bound {n_still}, "
          f"finished {len(rows) - n_still}")
    if a.json:
        Path(a.json).write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
