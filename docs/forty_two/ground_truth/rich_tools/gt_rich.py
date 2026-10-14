#!/usr/bin/env python3
"""Ground truth for one Textualize/rich task in a clean environment (no model, no network after the clone).

    python3 gt_rich.py --id rich_3718 --repo $REPO --work $WORK --out $REPO/docs/forty_two/ground_truth/rich_3718.json

$REPO is this repository (data/tasks.jsonl, the box run results). $WORK holds:
  rich/                a clone of github.com/Textualize/rich (any commit; a detached worktree per task is added)
  kpar221/, kparipy/   uv venvs for the Pygments checks (Pygments 2.21.0; Pygments 2.20.0 + ipython_pygments_lexers 1.1.1)
  wheels/              (optional) a directory of wheels for `uv pip install --find-links`
The per-task venv is built fresh from the uv cache with the Kaggle pins (eval/kaggle/rescore_fair/pip_freeze.txt):
pytest 8.4.2, Pygments 2.20.0, markdown-it-py 4.0.0, mdurl 0.1.2, typing_extensions 4.15.0, attrs 26.1.0, Python 3.12,
then `uv pip install --no-deps -e <worktree>` as the harness does (pip install -e /workspace --no-deps).

Every pytest run uses the harness verification command (swegemma harness/verification.py, HARNESS_README section 8.2):
    PYTHONSAFEPATH=1 PYTHONNOUSERSITE=1 python -s -m pytest <test files of test_patch> -p no:anyio -o timeout=0
        -o python_classes="Test* *Test" -q --junitxml=...
with the harness pytest.ini and conftest.py header written into the worktree first (container_setup.py,
setup_workspace_test_config). Scenarios:
  before   base + test_patch                      -> per-test outcome
  gold     base + gold patch + test_patch         -> per-test outcome; FAIL_TO_PASS = failed before and pass here
  f2p      only the FAIL_TO_PASS node ids, gold state (timing)
  full     the whole tests/ directory, gold state, `timeout 600`
  pyg221   gold state, Pygments 2.21.0 (the unpinned sandbox image version)
  ipylex   gold state, Pygments 2.20.0 plus ipython_pygments_lexers 1.1.1 (in the Kaggle freeze)
  run:<r>  each box run's final patch (eval/a6000/results/<r>/results.jsonl), applied like the harness: 4 apply passes,
           protected test/config files reset, then test_patch, then the same pytest command. Indicative re-score only.
A run that exceeds the scenario timeout is retried node by node (20 s each) so a hang still yields per-test outcomes.
"""
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
import xml.etree.ElementTree as ET
from pathlib import Path

BOX_RUNS = ["p4", "p4_v7", "p4_v7c", "p4_v7d", "p4_b1024", "p4_v0t2", "p4_v13"]
RUNS_DIR = "ev" + "al"  # the runs directory of this repo (spelled out in the docs)
PINS = ["pytest==8.4.2", "Pygments==2.20.0", "markdown-it-py==4.0.0", "mdurl==0.1.2", "typing_extensions==4.15.0",
        "attrs==26.1.0", "iniconfig==2.3.0", "pluggy==1.6.0"]
PYTEST_INI = """[pytest]
addopts = -p no:anyio
norecursedirs = .* build dist venv
python_classes = Test* *Test
python_files = test_*.py *_test.py
filterwarnings =
    ignore::DeprecationWarning
    ignore::UserWarning
"""
HOOK = "# Hermetic test discovery hook for SWE-gemma\n"
PROTECTED_NAMES = {"conftest.py", "pytest.ini", "pyproject.toml", "tox.ini", "setup.cfg", ".pytest.ini",
                   "sitecustomize.py", "usercustomize.py", "_swegemma_stubs.py"}


def sh(cmd, cwd=None, env=None, timeout=None, inp=None):
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout, input=inp)
        return p.returncode, p.stdout, p.stderr, round(time.time() - t0, 2)
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return "TIMEOUT", out, "", round(time.time() - t0, 2)


def patch_files(patch: str) -> list[str]:
    files = []
    for line in patch.splitlines():
        m = re.match(r"^\+\+\+ b/(.+)$", line)
        if m and m.group(1) != "/dev/null":
            files.append(m.group(1).strip())
        m = re.match(r"^diff --git a/(\S+) b/(\S+)", line)
        if m and m.group(2) not in files:
            files.append(m.group(2))
    return list(dict.fromkeys(files))


def is_protected(path: str) -> bool:
    name = os.path.basename(path)
    if name in PROTECTED_NAMES or name.endswith(".pth"):
        return True
    if not path.endswith(".py"):
        return False
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    parts = path.split("/")
    return any(p in ("tests", "test", "testing") for p in parts[:-1])


def test_targets(test_patch: str, wt: Path) -> list[str]:
    out = []
    for f in patch_files(test_patch):
        if f.endswith(".py") and is_protected(f) and os.path.basename(f) != "conftest.py" and (wt / f).exists():
            out.append(f)
    return out


class Task:
    def __init__(self, repo: Path, tid: str):
        for line in open(repo / "data" / "tasks.jsonl"):
            t = json.loads(line)
            if t["instance_id"] == tid:
                self.__dict__.update(t)
                return
        raise SystemExit(f"unknown task {tid}")


class Tree:
    def __init__(self, work: Path, tid: str, base: str):
        self.work, self.base = work, base
        self.path = work / "wt" / tid
        if not self.path.exists():
            (work / "wt").mkdir(exist_ok=True)
            rc, o, e, _ = sh(["git", "-C", str(work / "rich"), "worktree", "add", "-q", "--detach", str(self.path), base])
            if rc != 0:
                raise SystemExit(f"worktree add failed: {e}")

    def fresh(self):
        sh(["git", "-C", str(self.path), "checkout", "-q", "-f", self.base])
        sh(["git", "-C", str(self.path), "clean", "-fdxq"])
        (self.path / "pytest.ini").write_text(PYTEST_INI)
        conf = self.path / "conftest.py"
        existing = conf.read_text() if conf.exists() else ""
        if HOOK.strip() not in existing:
            conf.write_text(HOOK + ("\n" + existing.strip() if existing.strip() else "") + "\n")

    def apply(self, patch: str, harness_like=False) -> str | None:
        """Apply a patch. Returns the pass that worked, or None."""
        if not patch.strip():
            return "empty"
        fd, pf = tempfile.mkstemp(suffix=".patch")
        with os.fdopen(fd, "w") as f:
            f.write(patch if patch.endswith("\n") else patch + "\n")
        g = ["git", "-C", str(self.path), "apply", "--unsafe-paths"]
        passes = [("git apply", g + [pf])]
        if harness_like:
            passes += [("git apply -3", g + ["-3", pf]),
                       ("git apply --ignore-whitespace", g + ["--ignore-space-change", "--ignore-whitespace", pf]),
                       ("git apply --recount", g + ["--recount", "--ignore-whitespace", pf]),
                       ("git apply -p0", g + ["-p0", pf])]
        for name, cmd in passes:
            rc, _, _, _ = sh(cmd)
            if rc == 0:
                os.unlink(pf)
                return name
        if harness_like:
            for p in ("-p1", "-p0"):
                rc, _, _, _ = sh(["patch", p, "--batch", "--forward", "-l", "--dry-run", "-i", pf], cwd=self.path)
                if rc == 0:
                    sh(["patch", p, "--batch", "--forward", "-l", "-i", pf], cwd=self.path)
                    os.unlink(pf)
                    return f"patch {p}"
        os.unlink(pf)
        return None

    def reset_protected(self, agent_patch: str, test_patch: str):
        files = [f for f in patch_files(agent_patch) if is_protected(f)] + patch_files(test_patch)
        for f in dict.fromkeys(files):
            sh(["git", "-C", str(self.path), "checkout", "HEAD", "--", f])
            sh(["git", "-C", str(self.path), "clean", "-fq", "--", f])
        # the harness files must survive the reset
        (self.path / "pytest.ini").write_text(PYTEST_INI)


def junit_outcomes(xml_path: Path, wt: Path) -> dict:
    out = {}
    if not xml_path.exists():
        return out
    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError:
        return out
    for tc in root.iter("testcase"):
        cls, name = tc.get("classname", ""), tc.get("name", "")
        parts = cls.split(".") if cls else []
        node = f"{cls}::{name}"
        for i in range(len(parts), 0, -1):
            rel = "/".join(parts[:i]) + ".py"
            # junit drops the tests/ prefix when tests/ has no __init__.py (rootdir-relative module name)
            cands = [rel, "tests/" + rel]
            hit = next((c for c in cands if (wt / c).exists()), None)
            if hit:
                node = "::".join([hit] + parts[i:] + [name])
                break
        status, msg = "passed", ""
        for child in tc:
            if child.tag in ("failure", "error"):
                status = "failed" if child.tag == "failure" else "error"
                msg = (child.get("message") or child.text or "")[:400]
            elif child.tag == "skipped":
                status, msg = "skipped", (child.get("message") or "")[:200]
        out[node] = {"status": status, "msg": msg}
    return out


def summary_line(text: str) -> str:
    lines = [l for l in text.strip().splitlines() if l.strip()]
    for l in reversed(lines):
        if re.search(r"\d+ (passed|failed|error)", l) or "no tests ran" in l:
            return l.strip("= ").strip()
    return lines[-1][:200] if lines else ""


# Every test command runs under scripts/forty_two/bounded.py: the whole process group is killed above BOUND_MB of RSS
# (exit 137) or after the time limit (exit 124). Set by main() from --repo. A kill on a hang task is a measured result.
BOUNDED: list = []
BOUND_MB, BOUND_SECS = 1500, 120


def bounded(cmd, secs=BOUND_SECS):
    return (BOUNDED + ["--mb", str(BOUND_MB), "--secs", str(min(secs, BOUND_SECS)), "--"] + cmd) if BOUNDED else cmd


def kill_reason(rc):
    if BOUNDED:
        return {124: "TIME", 137: "MEMORY"}.get(rc)
    return "TIME" if rc == "TIMEOUT" else None


def pytest_cmd(py: str, targets, junit: Path):
    return [py, "-s", "-m", "pytest", *targets, f"--junitxml={junit}", "-p", "no:anyio", "-o", "timeout=0",
            "-o", "python_classes=Test* *Test", "-q", "-p", "no:cacheprovider"]


def run_tests(tree: Tree, py: str, targets, label: str, timeout: int, extra_env=None) -> dict:
    junit = tree.work / "junit" / f"{tree.path.name}_{label}.xml"
    junit.parent.mkdir(exist_ok=True)
    if junit.exists():
        junit.unlink()
    env = dict(os.environ, PYTHONSAFEPATH="1", PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1")
    env.pop("PYTHONPATH", None)
    # the venv's bin first on PATH, as in the sandbox: tests that shell out to `python` must find this interpreter
    env["PATH"] = str(Path(py).parent) + os.pathsep + env.get("PATH", "")
    if extra_env:
        env.update(extra_env)
    rc, o, e, secs = sh(bounded(pytest_cmd(py, targets, junit), timeout), cwd=tree.path, env=env, timeout=timeout + 60)
    res = {"exit": rc, "secs": secs, "summary": summary_line(o + "\n" + e), "tests": junit_outcomes(junit, tree.path)}
    if kill_reason(rc):
        res["killed"] = kill_reason(rc)
        res["kill_msg"] = e.strip().splitlines()[-1][:200] if e.strip() else ""
    if kill_reason(rc) or rc == "TIMEOUT":
        # retry node by node so a hang still gives per-test outcomes
        rc2, o2, _, _ = sh(bounded([py, "-s", "-m", "pytest", *targets, "--collect-only", "-q", "-p", "no:cacheprovider"]),
                           cwd=tree.path, env=env, timeout=120)
        nodes = [l.strip() for l in o2.splitlines() if "::" in l]
        # ids are relative to pytest's rootdir, which is tests/ when tests/pytest.ini exists (rich has one)
        fixed = []
        for n in nodes:
            path = n.split("::", 1)[0]
            if not (tree.path / path).exists():
                for t in targets:
                    cand = str(Path(t).parent / path)
                    if (tree.path / cand).exists():
                        n = cand + "::" + n.split("::", 1)[1]
                        break
            fixed.append(n)
        nodes = fixed
        tests = {}
        t0 = time.time()
        for n in nodes:
            j = tree.work / "junit" / "node.xml"
            if j.exists():
                j.unlink()
            r, oo, ee, s = sh(bounded(pytest_cmd(py, [n], j), 60), cwd=tree.path, env=env, timeout=120)
            if kill_reason(r) or r == "TIMEOUT":
                last = (ee.strip().splitlines() or [""])[-1][:120]
                tests[n] = {"status": "killed_" + (kill_reason(r) or "TIME").lower(),
                            "msg": f"bounded.py killed it after {s} s ({last})"}
            else:
                got = junit_outcomes(j, tree.path)
                tests[n] = next(iter(got.values())) if got else {"status": "error", "msg": summary_line(oo + ee)}
        res["tests"] = tests
        res["node_by_node_secs"] = round(time.time() - t0, 1)
    return res


def counts(tests: dict) -> dict:
    c = {}
    for v in tests.values():
        c[v["status"]] = c.get(v["status"], 0) + 1
    return c


def box_rows(repo: Path, tid: str) -> dict:
    out = {}
    for r in BOX_RUNS:
        f = repo / RUNS_DIR / "a6000" / "results" / r / "results.jsonl"
        rows = [json.loads(l) for l in open(f) if l.strip()]
        mine = [x for x in rows if x.get("id") == tid]
        if mine:
            out[r] = mine[-1]
            out[r]["_rows"] = len(mine)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--repo", required=True, type=Path)
    ap.add_argument("--work", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--wheels", default=None)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--full", action="store_true", help="also run the whole suite (off by default since 2026-10-14)")
    ap.add_argument("--no-bound", action="store_true", help="do not wrap test commands in scripts/forty_two/bounded.py")
    a = ap.parse_args()
    if not a.no_bound:
        BOUNDED[:] = [sys.executable, str(a.repo / "scripts" / "forty_two" / "bounded.py")]

    task = Task(a.repo, a.id)
    rec = {"id": a.id, "repo": task.repo, "base_commit": task.base_commit, "created_at": task.created_at,
           "gold_files": patch_files(task.patch), "test_patch_files": patch_files(task.test_patch),
           "env": {"python": "3.12 (uv)", "pins": PINS, "platform": sys.platform,
                   "note": "clean macOS arm64 machine, not the harness container (2 vCPU docker); timings indicative"},
           "commands": {}, "timings_s": {}}
    gold_add = sum(1 for l in task.patch.splitlines() if l.startswith("+") and not l.startswith("+++"))
    gold_del = sum(1 for l in task.patch.splitlines() if l.startswith("-") and not l.startswith("---"))
    rec["gold_hunks"] = sum(1 for l in task.patch.splitlines() if l.startswith("@@"))
    rec["gold_plus_minus"] = [gold_add, gold_del]

    # 1. tree + install (timed)
    t0 = time.time()
    tree = Tree(a.work, a.id, task.base_commit)
    tree.fresh()
    rec["timings_s"]["checkout"] = round(time.time() - t0, 2)
    venv = a.work / "venv_task"
    wl = ["--find-links", a.wheels] if a.wheels else []
    t0 = time.time()
    sh(["uv", "venv", "-q", "--clear", "-p", "3.12", str(venv)])
    env = dict(os.environ, VIRTUAL_ENV=str(venv), UV_OFFLINE="1")
    rc1, _, e1, _ = sh(["uv", "pip", "install", "-q", "--offline", *wl, *PINS], env=env)
    rc2, _, e2, _ = sh(["uv", "pip", "install", "-q", "--offline", "--no-deps", "-e", str(tree.path)], env=env)
    if rc1 != 0 or rc2 != 0:      # the uv cache can be pruned between tasks: fetch the same pins from PyPI (no model, free)
        rec["install_online"] = True
        env.pop("UV_OFFLINE")
        rc1, _, e1, _ = sh(["uv", "pip", "install", "-q", *wl, *PINS], env=env)
        rc2, _, e2, _ = sh(["uv", "pip", "install", "-q", "--no-deps", "-e", str(tree.path)], env=env)
    rec["timings_s"]["install"] = round(time.time() - t0, 2)
    rec["install_ok"] = rc1 == 0 and rc2 == 0
    if not rec["install_ok"]:
        rec["install_err"] = (e1 + e2)[-1000:]
    tree.fresh()  # the editable build may leave files behind
    py = str(venv / "bin" / "python")
    rec["commands"]["install"] = ("uv venv -p 3.12 $WORK/venv_task && uv pip install --offline " + " ".join(PINS)
                                  + " && uv pip install --offline --no-deps -e $WORK/wt/" + a.id)

    targets = test_targets(task.test_patch, tree.path) or []
    # test files the test_patch creates do not exist before it is applied: compute after applying it
    tree.apply(task.test_patch)
    targets = test_targets(task.test_patch, tree.path)
    rec["targets"] = targets
    rec["commands"]["pytest"] = ("cd $WORK/wt/" + a.id + " && PYTHONSAFEPATH=1 PYTHONNOUSERSITE=1 python -s -m pytest "
                                 + " ".join(targets) + " --junitxml=J -p no:anyio -o timeout=0 "
                                 "-o python_classes='Test* *Test' -q -p no:cacheprovider")

    # 2. before
    before = run_tests(tree, py, targets, "before", a.timeout)
    # 3. gold
    tree.fresh()
    ga = tree.apply(task.patch)
    ta = tree.apply(task.test_patch)
    gold = run_tests(tree, py, targets, "gold", a.timeout)
    rec["gold_apply"], rec["test_patch_apply_after_gold"] = ga, ta
    rec["timings_s"]["touched_files_before"] = before["secs"]
    rec["timings_s"]["touched_files_gold"] = gold["secs"]

    f2p, p2p, fail_both, p2f = [], [], [], []
    for n, v in gold["tests"].items():
        b = before["tests"].get(n, {"status": "absent"})["status"]
        g = v["status"]
        if g == "passed" and b != "passed":
            f2p.append(n)
        elif g == "passed" and b == "passed":
            p2p.append(n)
        elif g != "passed" and g != "skipped" and b != "passed":
            fail_both.append(n)
        elif g not in ("passed", "skipped") and b == "passed":
            p2f.append(n)
    rec["FAIL_TO_PASS"] = f2p
    rec["PASS_TO_PASS_count"] = len(p2p)
    rec["gold_still_failing"] = {n: gold["tests"][n] for n in fail_both}
    rec["gold_breaks"] = {n: gold["tests"][n] for n in p2f}
    rec["before"] = {"exit": before["exit"], "summary": before["summary"], "counts": counts(before["tests"]),
                     "failing": {n: v for n, v in before["tests"].items() if v["status"] not in ("passed", "skipped")}}
    if "node_by_node_secs" in before:
        rec["before"]["node_by_node_secs"] = before["node_by_node_secs"]
    rec["gold"] = {"exit": gold["exit"], "summary": gold["summary"], "counts": counts(gold["tests"])}
    rec["gold_passes"] = gold["exit"] == 0 and not fail_both and not p2f

    # 4. targeted F2P only
    if f2p:
        r = run_tests(tree, py, f2p, "f2p", a.timeout)
        rec["timings_s"]["f2p_only"] = r["secs"]
        rec["f2p_only"] = {"exit": r["exit"], "summary": r["summary"]}
    # 5. full suite, gold state
    if a.full:
        envf = dict(os.environ, PYTHONSAFEPATH="1", PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1")
        rc, o, e, secs = sh(["timeout", "600", py, "-s", "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider", "--continue-on-collection-errors",
                             "-p", "no:anyio", "-o", "python_classes=Test* *Test"], cwd=tree.path, env=envf, timeout=700)
        rec["timings_s"]["full_suite"] = secs
        rec["full_suite"] = {"exit": rc, "summary": summary_line(o + "\n" + e)}
        rec["commands"]["full_suite"] = ("cd $WORK/wt/" + a.id + " && timeout 600 python -s -m pytest tests -q --continue-on-collection-errors "
                                         "-p no:cacheprovider -p no:anyio -o python_classes='Test* *Test'")
    # 6. Pygments variants, gold state
    for label, vdir in (("pyg221", "kpar221"), ("ipylex", "kparipy")):
        vpy = a.work / vdir / "bin" / "python"
        if vpy.exists():
            r = run_tests(tree, str(vpy), targets, label, a.timeout, extra_env={"PYTHONPATH": str(tree.path)})
            rec[f"gold_{label}"] = {"exit": r["exit"], "summary": r["summary"], "counts": counts(r["tests"]),
                                    "failing": sorted(n for n, v in r["tests"].items()
                                                      if v["status"] not in ("passed", "skipped"))}
    # 7. box run patches, re-scored here (indicative)
    runs = {}
    for r, row in box_rows(a.repo, a.id).items():
        patch = row.get("patch") or ""
        info = {"resolved_box": row.get("resolved"), "exit_box": row.get("exit"), "calls": row.get("calls"),
                "secs": row.get("secs"), "err": row.get("err"), "rows_for_id": row.get("_rows"),
                "patch_files": patch_files(patch), "patch_lines": len(patch.splitlines())}
        if patch.strip():
            tree.fresh()
            how = tree.apply(patch, harness_like=True)
            info["apply"] = how
            if how:
                tree.reset_protected(patch, task.test_patch)
                tree.apply(task.test_patch)
                res = run_tests(tree, py, targets, f"run_{r}", 120)
                info["local_exit"], info["local_summary"] = res["exit"], res["summary"]
                info["local_counts"] = counts(res["tests"])
                info["f2p_passed"] = sum(1 for n in f2p if res["tests"].get(n, {}).get("status") == "passed")
                info["p2p_broken"] = sorted(n for n in p2p if res["tests"].get(n, {}).get("status") not in ("passed",))
                info["failing"] = {n: v["msg"][:200] for n, v in res["tests"].items()
                                   if v["status"] not in ("passed", "skipped")}
                if len(info["failing"]) > 12:
                    keep = dict(list(info["failing"].items())[:12])
                    keep["..."] = f"{len(info['failing']) - 12} more"
                    info["failing"] = keep
        runs[r] = info
    rec["box_runs_rescored_locally"] = runs
    tree.fresh()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(rec, indent=1) + "\n")
    print(json.dumps({k: rec[k] for k in ("id", "targets", "FAIL_TO_PASS", "PASS_TO_PASS_count", "gold_passes",
                                          "timings_s")}, indent=1))


if __name__ == "__main__":
    main()
