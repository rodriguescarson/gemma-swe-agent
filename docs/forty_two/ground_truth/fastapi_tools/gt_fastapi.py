#!/usr/bin/env python3
"""Ground truth for one public task in a real environment (docs/forty_two, fastapi/requests batch).

    python3 docs/forty_two/ground_truth/fastapi_tools/gt_fastapi.py TASK_ID --scr DIR [--no-full] [--out FILE]

What it does, in order (every step timed with the wall clock):
  1. checkout: a git worktree of a blob-less clone of github.com/<repo> (DIR/src/<name>) at base_commit, in DIR/ws/<id>.
  2. install: a fresh uv venv (Python 3.12) with the Kaggle-parity pins (scripts/build_kpar.sh lists = the versions of
     eval/kaggle/rescore_fair/pip_freeze.txt; python-multipart 0.0.26 and Pygments 2.20.0 as in data/kaggle_pins.txt),
     then the workspace itself with `uv pip install --no-deps -e` (the harness's `pip install --no-deps -e /workspace`).
  3. the harness's own test config: data/sandbox_setup.py configure_workspace_pytest_ini + configure_workspace_conftest
     (HARNESS_README 4.2 step 6), then test_patch, then the harness's verification line (HARNESS_README 8.2 step 4):
        PYTHONSAFEPATH=1 PYTHONNOUSERSITE=1 python -s -m pytest <test files> --junitxml=... -p no:anyio -o timeout=0
            -o python_classes="Test* *Test" -q          (+ -o junit_family=xunit1 so each case carries its file)
     on the base tree (before) and after the gold patch (after). FAIL_TO_PASS = not passed before and passed after;
     PASS_TO_PASS = passed both.
  4. timings: the F2P node ids alone, the touched test files, and the full tests/ directory
     (--continue-on-collection-errors, capped at 600 s).
  5. every recorded agent patch of the six box runs (eval/a6000/results/<run>/results.jsonl) and of the Kaggle L4 runs
     that resolved the task is re-verified the harness's way (4-pass apply, reset of protected test/config paths,
     test_patch, same pytest line). This separates "the agent's patch is wrong" from "the box's env failed it".

requests (src layout): the harness's subprocess sandbox imports the site-packages copy of requests, not /workspace
(the repo's documented F10 finding). Both modes are run: mode "ws" (workspace installed editable) and mode "site"
(Kaggle's requests 2.32.4 in site-packages, the workspace not installed).

No model, no paid API, no Kaggle. Paths in the output are relative ($SCR = the scratch dir, . = this repo).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
RUNS = ["p4", "p4_v7", "p4_v7c", "p4_v7d", "p4_b1024", "p4_v0t2"]
RUN_BUNDLE = {"p4": "v5h2", "p4_v7": "v7", "p4_v7c": "v7c", "p4_v7d": "v7d", "p4_b1024": "v12-b1024", "p4_v0t2": "v0-think"}
PROTECTED_NAMES = {"conftest.py", "pytest.ini", "pyproject.toml", "tox.ini", "setup.cfg", ".pytest.ini",
                   "sitecustomize.py", "usercustomize.py", "_swegemma_stubs.py"}
HARNESS_PYTEST = ["-p", "no:anyio", "-o", "timeout=0", "-o", "python_classes=Test* *Test", "-q",
                  "-o", "junit_family=xunit1"]


def sh(cmd, cwd=None, env=None, timeout=None, check=False):
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
        out = SimpleRes(r.returncode, r.stdout, r.stderr, time.time() - t0, False)
    except subprocess.TimeoutExpired as e:
        out = SimpleRes(124, (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or ""),
                        (e.stderr or b"").decode("utf-8", "replace") if isinstance(e.stderr, bytes) else (e.stderr or ""),
                        time.time() - t0, True)
    if check and out.rc != 0:
        raise RuntimeError(f"command failed rc={out.rc}: {' '.join(map(str, cmd))}\n{out.out[-2000:]}\n{out.err[-2000:]}")
    return out


class SimpleRes:
    def __init__(self, rc, out, err, secs, timed_out):
        self.rc, self.out, self.err, self.secs, self.timed_out = rc, out, err, secs, timed_out


def load_task(tid):
    with open(ROOT / "data" / "tasks.jsonl", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r["instance_id"] == tid:
                return r
    raise SystemExit(f"unknown task {tid}")


def bash_array(name):
    text = (ROOT / "scripts" / "build_kpar.sh").read_text()
    m = re.search(rf"^{name}=\((.*?)\)", text, re.S | re.M)
    toks = []
    for line in m.group(1).splitlines():
        line = line.split("#", 1)[0]
        toks += line.split()
    return toks


def freeze_pin(pkg):
    for line in (ROOT / "eval" / "kaggle" / "rescore_fair" / "pip_freeze.txt").read_text().splitlines():
        if line.lower().startswith(pkg.lower() + "=="):
            return line.strip()
    raise KeyError(pkg)


def patch_files(patch):
    return re.findall(r"^\+\+\+ b/(\S+)", patch, re.M) or re.findall(r"^--- a/(\S+)", patch, re.M)


def normalize_new_files(patch, ws):
    """`--- a/x` + `@@ -0,0 ...` on a file that does not exist at base -> `--- /dev/null` (git apply then creates it)."""
    out, lines, i = [], patch.splitlines(keepends=True), 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("--- a/") and i + 2 < len(lines) and lines[i + 1].startswith("+++ b/") \
                and lines[i + 2].startswith("@@ -0,0 "):
            path = ln[len("--- a/"):].split("\t")[0].strip()
            if not (ws / path).exists():
                out.append("--- /dev/null\n")
                i += 1
                continue
        out.append(ln)
        i += 1
    return "".join(out)


def apply_patch(ws, patch, label, tmpdir):
    """The harness's 4-pass resilient apply (HARNESS_README 8.2 step 2), returning the pass that worked."""
    if not patch.strip():
        return "empty"
    p = Path(tmpdir) / f"{label}.diff"
    p.write_text(normalize_new_files(patch if patch.endswith("\n") else patch + "\n", ws))
    tries = [["git", "apply", "--unsafe-paths", "-p1", str(p)],
             ["git", "apply", "-3", str(p)],
             ["git", "apply", "--ignore-space-change", "--ignore-whitespace", str(p)],
             ["git", "apply", "--recount", str(p)],
             ["git", "apply", "--unsafe-paths", "-p0", str(p)]]
    for c in tries:
        if sh(c, cwd=ws).rc == 0:
            return " ".join(c[1:-1])
    for c in (["patch", "-p1", "--batch", "--forward", "-i", str(p)], ["patch", "-p1", "-l", "--batch", "--forward", "-i", str(p)]):
        if sh(c[:1] + ["--dry-run"] + c[1:], cwd=ws).rc == 0:
            sh(c, cwd=ws)
            return " ".join(c[:-2])
    r = sh(["git", "apply", "--unsafe-paths", "-p1", str(p)], cwd=ws)
    return "FAILED: " + (r.err or r.out).strip()[:300]


def harness_config(ws):
    spec = importlib.util.spec_from_file_location("sandbox_setup", ROOT / "data" / "sandbox_setup.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.configure_workspace_pytest_ini(ws)
    m.configure_workspace_conftest(ws)


def reset_ws(ws, base):
    sh(["git", "checkout", "-q", "-f", base], cwd=ws, check=True)
    sh(["git", "clean", "-fdxq"], cwd=ws, check=True)
    harness_config(ws)


def is_protected(path, test_paths):
    name = path.rsplit("/", 1)[-1]
    parts = path.split("/")
    return (path in test_paths or name in PROTECTED_NAMES or name.endswith(".pth")
            or (name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py")
                                          or any(d in ("tests", "test", "testing") for d in parts[:-1]))))


def reset_protected(ws, base, files, test_paths):
    for f in files:
        if is_protected(f, test_paths):
            if sh(["git", "cat-file", "-e", f"{base}:{f}"], cwd=ws).rc == 0:
                sh(["git", "checkout", "-q", base, "--", f], cwd=ws)
            elif (ws / f).exists():
                (ws / f).unlink()
    harness_config(ws)


def parse_junit(path, ws):
    res = {}
    if not Path(path).exists():
        return res
    root = ET.parse(path).getroot()
    for tc in root.iter("testcase"):
        f, name, cls = tc.get("file"), tc.get("name"), tc.get("classname") or ""
        nodeid = None
        if f:
            parts = cls.split(".")
            mod_parts = f[:-3].replace("/", ".").split(".") if f.endswith(".py") else []
            if parts[:len(mod_parts)] == mod_parts:
                inner = parts[len(mod_parts):]
            else:  # importlib mode may shorten the module part of classname; keep a trailing class name only
                inner = parts[-1:] if parts and parts[-1][:1].isupper() else []
            nodeid = "::".join([f] + inner + [name])
        else:
            parts = cls.split(".")
            for k in range(len(parts), 0, -1):
                cand = "/".join(parts[:k]) + ".py"
                if (ws / cand).exists():
                    nodeid = "::".join([cand] + parts[k:] + [name])
                    break
            nodeid = nodeid or f"{cls}::{name}"
        kids = {c.tag for c in tc}
        if "failure" in kids:
            st = "failed"
        elif "error" in kids:
            st = "error"
        elif "skipped" in kids:
            st = "skipped"
        else:
            st = "passed"
        msg = ""
        for c in tc:
            if c.tag in ("failure", "error", "skipped"):
                msg = (c.get("message") or (c.text or ""))[:300]
        res[nodeid] = {"status": st, "msg": msg}
    return res


def run_pytest(py, ws, targets, label, logdir, timeout=900, extra=()):
    junit = Path(logdir) / f"junit_{label}.xml"
    if junit.exists():
        junit.unlink()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "VIRTUAL_ENV", "UV_"))}
    env.update({"PYTHONSAFEPATH": "1", "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"})
    cmd = [str(py), "-s", "-m", "pytest", *targets, f"--junitxml={junit}", *HARNESS_PYTEST, *extra]
    r = sh(cmd, cwd=ws, env=env, timeout=timeout)
    (Path(logdir) / f"pytest_{label}.log").write_text(f"$ {' '.join(cmd)}\nrc={r.rc} secs={r.secs:.2f}\n{r.out}\n{r.err}")
    cases = parse_junit(junit, ws)
    counts = {}
    for c in cases.values():
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    tail = [ln for ln in r.out.strip().splitlines() if ln.strip()][-1:] if r.out.strip() else []
    return {"exit": r.rc, "secs": round(r.secs, 2), "timed_out": r.timed_out, "counts": counts,
            "summary_line": tail[0][:300] if tail else "", "cases": cases,
            "collection_errors": len(re.findall(r"^ERROR collecting", r.out, re.M))}


def build_venv(venv, pins, ws_editable, logdir):
    t0 = time.time()
    if venv.exists():
        shutil.rmtree(venv)
    sh(["uv", "venv", "-q", "-p", "3.12", str(venv)], check=True)
    env = dict(os.environ, VIRTUAL_ENV=str(venv))
    r1 = sh(["uv", "pip", "install", "-q", "--python", str(venv / "bin" / "python"), *pins], env=env)
    if r1.rc != 0:
        raise RuntimeError(r1.err[-3000:])
    t_pins = time.time() - t0
    r2 = None
    if ws_editable:
        r2 = sh(["uv", "pip", "install", "-q", "--python", str(venv / "bin" / "python"), "--no-deps", "-e", str(ws_editable)], env=env)
        if r2.rc != 0:
            raise RuntimeError(r2.err[-3000:])
    return {"secs_total": round(time.time() - t0, 2), "secs_pins": round(t_pins, 2),
            "secs_editable": round(r2.secs, 2) if r2 else None}


def outcome_sets(before, after, test_files):
    ids = sorted(set(before["cases"]) | set(after["cases"]))
    f2p, p2p, f2f, p2f = [], [], [], []
    for i in ids:
        b = before["cases"].get(i, {}).get("status", "absent")
        a = after["cases"].get(i, {}).get("status", "absent")
        if a == "passed" and b != "passed":
            f2p.append(i)
        elif a == "passed" and b == "passed":
            p2p.append(i)
        elif a != "passed" and b != "passed":
            f2f.append(f"{i} [{b}->{a}]")
        else:
            p2f.append(f"{i} [{b}->{a}]")
    return f2p, p2p, f2f, p2f


def eval_patch(py, ws, base, patch, test_patch, test_files, label, logdir, f2p, p2p):
    reset_ws(ws, base)
    how = apply_patch(ws, patch, label, logdir)
    if how.startswith("FAILED"):
        return {"apply": how, "resolved": False}
    files = patch_files(patch) if patch.strip() else []
    reset_protected(ws, base, files, set(test_files))
    how_t = apply_patch(ws, test_patch, label + "_tp", logdir)
    r = run_pytest(py, ws, test_files, label, logdir)
    need = set(f2p) | set(p2p)
    bad = sorted(i for i in need if r["cases"].get(i, {}).get("status") != "passed")
    resolved = r["exit"] == 0 and not bad and r["counts"].get("passed", 0) > 0 \
        and r["counts"].get("failed", 0) == 0 and r["counts"].get("error", 0) == 0
    failing = {i: c["msg"][:200] for i, c in r["cases"].items() if c["status"] in ("failed", "error")}
    return {"apply": how, "test_patch_apply": how_t, "resolved": resolved, "exit": r["exit"], "counts": r["counts"],
            "secs": r["secs"], "f2p_failing": [i for i in bad if i in set(f2p)], "p2p_failing": [i for i in bad if i in set(p2p)],
            "failing_msgs": dict(list(failing.items())[:8]), "summary_line": r["summary_line"],
            "files": files}


def recorded_patches(tid):
    out = {}
    for run in RUNS:
        for line in open(ROOT / "eval" / "a6000" / "results" / run / "results.jsonl"):
            x = json.loads(line)
            if x["id"] == tid:
                out[f"box:{run}"] = x
    for d in sorted((ROOT / "eval" / "kaggle").iterdir()):
        f = d / "results.jsonl"
        if not f.exists() or d.name == "oracle_all":
            continue
        rows = [json.loads(l) for l in open(f) if l.strip()]
        if len(rows) != 74:
            continue
        for x in rows:
            if (x.get("id") or x.get("instance_id")) == tid and x.get("resolved"):
                out[f"l4:{d.name}"] = x
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tid")
    ap.add_argument("--scr", required=True)
    ap.add_argument("--no-full", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()
    scr = Path(a.scr).resolve()
    t = load_task(a.tid)
    name = t["repo"].split("/")[1]
    src = scr / "src" / name
    ws = scr / "ws" / a.tid
    logdir = scr / "logs" / a.tid
    logdir.mkdir(parents=True, exist_ok=True)
    base = t["base_commit"]
    test_files = sorted(set(patch_files(t["test_patch"])))
    gold_files = sorted(set(patch_files(t["patch"])))
    rel = lambda s: str(s).replace(str(scr), "$SCR").replace(str(ROOT), ".").replace(str(Path.home()), "~")
    commands = []

    # 1. checkout
    t0 = time.time()
    if sh(["git", "cat-file", "-e", base + "^{commit}"], cwd=src).rc != 0:
        sh(["git", "fetch", "-q", "origin", base], cwd=src, check=True)
    if ws.exists():
        sh(["git", "worktree", "remove", "--force", str(ws)], cwd=src)
        shutil.rmtree(ws, ignore_errors=True)
    sh(["git", "worktree", "prune"], cwd=src)
    sh(["git", "worktree", "add", "-q", "--detach", str(ws), base], cwd=src, check=True)
    t_checkout = time.time() - t0
    commands.append(f"git clone --filter=blob:none --no-checkout https://github.com/{t['repo']}.git $SCR/src/{name}")
    commands.append(f"git -C $SCR/src/{name} worktree add --detach $SCR/ws/{a.tid} {base}")

    # 2. venv(s)
    if name == "fastapi":
        pins = bash_array("FASTAPI_PINS")
        modes = {"ws": (pins, ws)}
    else:
        base_pins = bash_array("BASE_PINS")
        deps = [freeze_pin(p) for p in ("urllib3", "idna", "charset-normalizer", "certifi", "PySocks")]
        modes = {"ws": (base_pins + deps, ws), "site": (base_pins + deps + [freeze_pin("requests")], None)}
    installs, pys = {}, {}
    for mode, (pins, editable) in modes.items():
        venv = scr / "venv" / f"{a.tid}-{mode}"
        installs[mode] = build_venv(venv, pins, editable, logdir)
        installs[mode]["pins"] = pins
        installs[mode]["editable_workspace"] = bool(editable)
        pys[mode] = venv / "bin" / "python"
        commands.append(f"uv venv -p 3.12 $SCR/venv/{a.tid}-{mode} && uv pip install --python $SCR/venv/{a.tid}-{mode}/bin/python "
                        + " ".join(pins) + (f" && uv pip install --no-deps -e $SCR/ws/{a.tid}" if editable else ""))
    pyver = sh([str(pys["ws"]), "-V"]).out.strip()

    results = {}
    pt_line = ("cd $SCR/ws/{id} && PYTHONSAFEPATH=1 PYTHONNOUSERSITE=1 $SCR/venv/{id}-{mode}/bin/python -s -m pytest {targets} "
               "--junitxml=/tmp/j.xml -p no:anyio -o timeout=0 -o python_classes='Test* *Test' -q -o junit_family=xunit1")
    commands.append("harness test config: python -c 'import data.sandbox_setup as s; s.configure_workspace_pytest_ini(ws); "
                    "s.configure_workspace_conftest(ws)' (HARNESS_README 4.2 step 6)")
    commands.append("test_patch / gold / agent patches: git apply [-p1 | -3 | --ignore-whitespace | --recount | -p0], then patch -p1 "
                    "(HARNESS_README 8.2 step 2); new files declared as '--- a/x' with '@@ -0,0' are applied as '--- /dev/null'")
    for mode, py in pys.items():
        reset_ws(ws, base)
        tp_how = apply_patch(ws, t["test_patch"], f"{mode}_test_patch", logdir)
        before = run_pytest(py, ws, test_files, f"{mode}_before", logdir)
        gold_how = apply_patch(ws, t["patch"], f"{mode}_gold", logdir)
        after = run_pytest(py, ws, test_files, f"{mode}_after", logdir)
        f2p, p2p, f2f, p2f = outcome_sets(before, after, test_files)
        gold_passes = after["exit"] == 0 and after["counts"].get("failed", 0) == 0 and after["counts"].get("error", 0) == 0 \
            and after["counts"].get("passed", 0) > 0
        timing = {"touched_files_before": before["secs"], "touched_files_after_gold": after["secs"]}
        if f2p:
            r = run_pytest(py, ws, f2p, f"{mode}_f2p_only", logdir)
            timing["f2p_targeted"] = r["secs"]
            timing["f2p_targeted_exit"] = r["exit"]
        if not a.no_full and mode == "ws":
            full_target = ["tests"] if (ws / "tests").is_dir() else ["."]
            r = run_pytest(py, ws, full_target, f"{mode}_full", logdir, timeout=600, extra=("--continue-on-collection-errors",))
            timing["full_suite"] = {"secs": r["secs"], "exit": r["exit"], "timed_out": r["timed_out"], "counts": r["counts"],
                                    "collection_errors": r["collection_errors"], "summary_line": r["summary_line"]}
            commands.append(pt_line.format(id=a.tid, mode=mode, targets=" ".join(full_target)) + " --continue-on-collection-errors"
                            + "   (full suite, 600 s cap)")
        first_fail_after = {i: c["msg"] for i, c in after["cases"].items() if c["status"] in ("failed", "error")}
        results[mode] = {
            "test_patch_apply": tp_how, "gold_apply": gold_how,
            "before": {"exit": before["exit"], "counts": before["counts"], "summary_line": before["summary_line"],
                       "not_passed": {i: c["status"] + ": " + c["msg"][:160] for i, c in before["cases"].items() if c["status"] != "passed"}},
            "after": {"exit": after["exit"], "counts": after["counts"], "summary_line": after["summary_line"],
                      "not_passed": {i: c["status"] + ": " + c["msg"][:160] for i, c in after["cases"].items() if c["status"] != "passed"}},
            "FAIL_TO_PASS": f2p, "PASS_TO_PASS": p2p, "FAIL_BOTH": f2f, "PASS_TO_FAIL": p2f,
            "gold_passes": gold_passes, "gold_error": dict(list(first_fail_after.items())[:5]) if not gold_passes else None,
            "timings_s": timing,
        }
        commands.append(pt_line.format(id=a.tid, mode=mode, targets=" ".join(test_files)) + "   (before: base + test_patch; after: + gold)")

    # 5. recorded agent patches, re-verified in mode ws (and site for requests)
    agent = {}
    rec = recorded_patches(a.tid)
    for key, x in rec.items():
        entry = {"recorded_resolved": x.get("resolved"), "recorded_exit": x.get("exit"), "calls": x.get("calls"),
                 "secs": x.get("secs"), "err": x.get("err"), "patch_chars": len(x.get("patch") or "")}
        for mode, py in pys.items():
            res = results[mode]
            entry[f"clean_env_{mode}"] = eval_patch(py, ws, base, x.get("patch") or "", t["test_patch"], test_files,
                                                    f"{mode}_{key.replace(':', '_')}", logdir, res["FAIL_TO_PASS"], res["PASS_TO_PASS"])
        agent[key] = entry
    reset_ws(ws, base)

    oracle = None
    for line in open(ROOT / "eval" / "kaggle" / "oracle_all" / "results.jsonl"):
        x = json.loads(line)
        if x["id"] == a.tid:
            oracle = {"resolved": x["resolved"], "exit": x["exit"], "secs": x["secs"], "source": "eval/kaggle/oracle_all/results.jsonl"}
    out = {
        "id": a.tid, "repo": t["repo"], "base_commit": base,
        "measured_on": {"platform": f"{platform.system()} {platform.machine()}", "python": pyver,
                        "note": "clean local machine, not the harness container (Linux, 2 vCPU, 4 GiB): timings are indicative"},
        "gold_files": gold_files, "test_files": test_files,
        "install": installs, "checkout_secs": round(t_checkout, 2),
        "modes": results,
        "agent_patches_reverified": agent,
        "kaggle_oracle_gold": oracle,
        "commands": [rel(c) for c in commands],
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "generator": "docs/forty_two/ground_truth/fastapi_tools/gt_fastapi.py",
    }
    text = json.dumps(out, indent=1, sort_keys=False)
    text = text.replace(str(scr), "$SCR").replace(str(ROOT), ".").replace(str(Path.home()), "~")
    if a.out:
        Path(a.out).write_text(text + "\n")
    print(text[:200000])


if __name__ == "__main__":
    main()
