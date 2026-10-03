"""Shared support for the v10.2 test modules (tests/test_v10_2_*.py, docs/v10/SPEC_v10_2.md section 7).

The v10.2 bundle under test is always submissions/v10_2, whatever G4_BUNDLE says (G4_BUNDLE points the v10 suite at a
bundle; these modules pin v10.2's own behaviour). Helpers are copied to a temp dir and run as subprocesses against a
harness-like repo (tests/v10_support/repo.py), exactly as the model runs them through run_command; nothing ever runs
inside submissions/.

- Box: one workspace, one $SWE, one copy of the helpers. box.h(name, args, stdin=None, t=None, **env) runs a helper
  and returns its stdout (asserting exit 0, empty stderr and no HELPER ERROR); box.state() reads $SWE/state.json;
  box.py(code) runs code after `import _swe_common as C` in the helpers' dir; box.harness_diff() is the fallback diff
  the harness submits (`git add -N . && git diff --binary _swegemma_baseline`, repo config honoured).
- shim_path(tmp): a PATH dir whose git and python3 log every invocation, so a test can prove a refusal started no
  child process.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

from v10_support.repo import copy_helpers, git, helper_env, make_repo, run_helper, run_py

ROOT = pathlib.Path(__file__).resolve().parents[2]
V101 = ROOT / "submissions" / "v10"
V102 = ROOT / "submissions" / "v10_2"
V101_SCRIPTS = V101 / "skills" / "swe-tools" / "scripts"
V102_SCRIPTS = V102 / "skills" / "swe-tools" / "scripts"
PY = sys.executable


class Box(object):
    """A workspace, a $SWE and the v10.2 helpers (or `src`), ready to run."""

    def __init__(self, tmp_path, files=None, src=V102_SCRIPTS, install=True, **extra_env):
        self.tmp = pathlib.Path(tmp_path)
        self.scripts = copy_helpers(self.tmp, src)
        self.ws = make_repo(self.tmp, files)
        self.swe = self.tmp / "sbx" / "swe"
        self.env = helper_env(self.ws, self.swe, **extra_env)
        # the grader's python3 is the one on PATH: this venv's (pytest installed), as in tests/test_v10_1.py
        self.env["PATH"] = os.path.dirname(PY) + os.pathsep + self.env.get("PATH", "")
        if install:
            self.h("install")

    def run(self, name, args=(), stdin=None, t=None, timeout=60, **env):
        e = dict(self.env)
        if t is not None:
            e["SWE_FAKE_CLOCK"] = str(t)
        e.update({k: str(v) for k, v in env.items()})
        return run_helper(self.scripts, name, list(args), ws=self.ws, env=e, stdin=stdin, timeout=timeout)

    def h(self, name, args=(), stdin=None, t=None, timeout=60, **env):
        r = self.run(name, args, stdin=stdin, t=t, timeout=timeout, **env)
        assert r.returncode == 0 and r.stderr == "" and "HELPER ERROR" not in r.stdout, r.stdout + r.stderr
        return r.stdout

    def timed(self, name, args=(), stdin=None, t=None, **env):
        t0 = time.monotonic()
        out = self.h(name, args, stdin=stdin, t=t, **env)
        return out, time.monotonic() - t0

    def state(self):
        try:
            return json.loads((self.swe / "state.json").read_text())
        except (OSError, ValueError):
            return {}

    def journal(self):
        p = self.swe / "journal.jsonl"
        return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []

    def py(self, code, t=None, timeout=60, **env):
        e = dict(self.env)
        if t is not None:
            e["SWE_FAKE_CLOCK"] = str(t)
        e.update({k: str(v) for k, v in env.items()})
        r = run_py(self.scripts, code, env=e, cwd=self.ws, timeout=timeout)
        assert r.returncode == 0, r.stdout + r.stderr
        return r.stdout

    def write(self, rel, text):
        p = self.ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def harness_diff(self):
        """What the harness submits at a timeout or nudge end: `git add -N . && git diff --binary <tag>` with the
        repository's own config (the submit guard's core.excludesFile included)."""
        e = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        e.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        subprocess.run(["git", "add", "-N", "."], cwd=str(self.ws), env=e, capture_output=True)
        return subprocess.run(["git", "diff", "--binary", "_swegemma_baseline"], cwd=str(self.ws), env=e,
                              capture_output=True, text=True).stdout

    def git(self, *args):
        return git(self.ws, *args)


def lines(out):
    return out.rstrip("\n").split("\n")


SHIM = """#!/bin/sh
echo "$(basename "$0") $*" >> "%s"
exec "%s" "$@"
"""


def shim_path(tmp, env):
    """A PATH whose git and python3 append each call to <tmp>/calls.log before running the real binary."""
    d = pathlib.Path(tmp) / "shim"
    d.mkdir(exist_ok=True)
    log = pathlib.Path(tmp) / "calls.log"
    for name, real in (("git", shutil.which("git", path=env["PATH"])),
                       ("python3", shutil.which("python3", path=env["PATH"]) or PY)):
        p = d / name
        p.write_text(SHIM % (log, real))
        p.chmod(0o755)
    return "%s%s%s" % (d, os.pathsep, env["PATH"]), log
