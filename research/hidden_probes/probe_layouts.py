"""Robustness probes: run the v10.1 helpers (copied, never in-bundle) under a Docker-like env on Python 3.13
(PYTHONPATH unset, TEST_TMPDIR set, TMPDIR unset, the package reachable only through a workspace_paths.pth written
the way sandbox/setup.py's fast path does) against layouts the public set never had. No LLM, no GPU, no network.
Driver: the project .venv (for tests/v10_support.repo); helpers and their children: scratchpad/hidden/v313."""
import json, os, pathlib, shutil, subprocess, sys, time, textwrap

HERE = pathlib.Path(__file__).resolve().parent
R = pathlib.Path("/Users/carson/Projects/gemma-swe-agent")
sys.path.insert(0, str(R / "tests"))
from v10_support.repo import make_repo, copy_helpers, git  # noqa: E402

import tempfile
V313 = pathlib.Path(os.environ.get("PROBE_VENV313", str(HERE / "v313")))   # python3.13 -m venv; pip install --no-index --find-links data/raw/wheels pytest
PY = str(V313 / "bin" / "python3")
SITE = next((V313 / "lib").glob("python3.*/site-packages"))
OUT = pathlib.Path(os.environ.get("PROBE_OUT", os.path.join(tempfile.gettempdir(), "g4_hidden_probe_out")))
shutil.rmtree(OUT, ignore_errors=True)
OUT.mkdir()
SCRIPTS = copy_helpers(OUT)
results = {}


def pth_for(ws):
    """fast-path: workspace_paths.pth = ws + every non-hidden top-level dir (sandbox/setup.py execute_fast_path)."""
    paths = [str(ws)] + [str(p) for p in sorted(ws.iterdir()) if p.is_dir() and not p.name.startswith(".")]
    (SITE / "workspace_paths.pth").write_text("\n".join(paths) + "\n")


def env_for(ws, name):
    tmp = OUT / (name + "_tmp")
    tmp.mkdir(exist_ok=True)
    e = {"PATH": str(V313 / "bin") + ":/usr/bin:/bin:/opt/homebrew/bin", "HOME": str(tmp), "TEST_TMPDIR": str(tmp),
         "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
         "SWE_DOCKER_TMP_FOR_TESTS": str(tmp / "docker_tmp"), "SWE_DOCKER_WS_FOR_TESTS": str(tmp / "no_ws"),
         "PWD": str(ws), "GIT_AUTHOR_NAME": "a", "GIT_AUTHOR_EMAIL": "a@b", "GIT_COMMITTER_NAME": "a",
         "GIT_COMMITTER_EMAIL": "a@b"}
    return e, tmp / "swe"


def run(ws, env, argv, stdin=None, timeout=120):
    t0 = time.time()
    r = subprocess.run([PY] + [str(a) for a in argv], cwd=str(ws), env=env, input=stdin, capture_output=True,
                       text=True, timeout=timeout)
    return (r.stdout + r.stderr).strip(), round(time.time() - t0, 1)


sys.path.insert(0, str(R / "data"))
import sandbox_setup as SS  # noqa: E402  (the public sandbox/setup.py: its fast path writes the scorer's pytest.ini)


def scorer_test_config(files):
    tmpd = OUT / "_cfg"
    shutil.rmtree(tmpd, ignore_errors=True)
    tmpd.mkdir()
    SS.configure_workspace_pytest_ini(tmpd)
    SS.configure_workspace_conftest(tmpd)
    f = dict(files)
    f["pytest.ini"] = (tmpd / "pytest.ini").read_text()
    f["conftest.py"] = (tmpd / "conftest.py").read_text()
    return f


def setup(name, files):
    ws = make_repo(OUT, scorer_test_config(files), name=name)
    pth_for(ws)
    env, swe = env_for(ws, name)
    out, _ = run(ws, env, [SCRIPTS / "install.py"])
    return ws, env, swe, out


def helper(swe, n):
    return swe / (n + ".py")


def record(name, **kw):
    results[name] = kw
    print("=" * 30, name)
    for k, v in kw.items():
        print("--", k)
        print(v if isinstance(v, str) else json.dumps(v))


REPRO = """from {mod} import area
# CLAIM 1: area of a 2x3 rectangle is 6
assert area(2, 3) == 6, repr(area(2, 3))
"""
BUGGY = "def area(w, h):\n    return w + h\n"
FIXED = "def area(w, h):\n    return w * h\n"
TEST = "from {mod} import area, keep\n\n\ndef test_keep():\n    assert keep() == 1\n"
KEEP = "\n\ndef keep():\n    return 1\n"


def layout_probe(name, files, modpath, mod, break_keep=False):
    """Locator repro, then a correct fix (plus, optionally, a regression in keep()), then verify."""
    ws, env, swe, inst = setup(name, files)
    o1, t1 = run(ws, env, [helper(swe, "verify"), "--repro-only"], stdin=REPRO.format(mod=mod))
    new = FIXED + (KEEP.replace("return 1", "return 2") if break_keep else KEEP)
    (ws / modpath).write_text(new)
    o2, t2 = run(ws, env, [helper(swe, "verify")])
    record(name, install=inst.splitlines()[0], repro_only=o1, repro_secs=t1, verify=o2, verify_secs=t2)


# A. control: flat package
layout_probe("A_flat", {"pkg/__init__.py": "", "pkg/geo.py": BUGGY + KEEP,
                        "tests/test_geo.py": TEST.format(mod="pkg.geo")}, "pkg/geo.py", "pkg.geo", break_keep=True)
# B. src layout with __init__
layout_probe("B_src", {"src/pkg/__init__.py": "", "src/pkg/geo.py": BUGGY + KEEP,
                       "tests/test_geo.py": TEST.format(mod="pkg.geo")}, "src/pkg/geo.py", "pkg.geo", break_keep=True)
# C. namespace package (no __init__.py anywhere), flat
layout_probe("C_namespace", {"nspkg/geo.py": BUGGY + KEEP, "tests/test_geo.py": TEST.format(mod="nspkg.geo")},
             "nspkg/geo.py", "nspkg.geo", break_keep=True)
# D. package under a non-src top dir (python/pkg), importable only through the .pth line for /ws/python
layout_probe("D_pythondir", {"python/pkg/__init__.py": "", "python/pkg/geo.py": BUGGY + KEEP,
                             "python/pkg/geo_test.py": TEST.format(mod="pkg.geo")},
             "python/pkg/geo.py", "pkg.geo", break_keep=True)

# E. slow import (a heavy dependency: 12 s at import, e.g. TF/JAX on 2 vCPUs)
SLOW = "import time\ntime.sleep(12)\n"
ws, env, swe, inst = setup("E_slow_import", {"pkg/__init__.py": SLOW, "pkg/geo.py": BUGGY + KEEP,
                                             "tests/test_geo.py": TEST.format(mod="pkg.geo")})
o1, t1 = run(ws, env, [helper(swe, "verify"), "--repro-only"], stdin=REPRO.format(mod="pkg.geo"))
(ws / "pkg/geo.py").write_text(FIXED + KEEP)
o2, t2 = run(ws, env, [helper(swe, "verify")])
o3, t3 = run(ws, env, [helper(swe, "finalize")])
record("E_slow_import", repro_only=o1, repro_secs=t1, verify=o2, verify_secs=t2, finalize=o3, finalize_secs=t3)

# F. new root-level module whose name starts with a scratch prefix, in a flat root-module repo
ws, env, swe, inst = setup("F_root_template", {"app.py": "def render(x):\n    return str(x)\n",
                                               "helpers.py": "X = 1\n",
                                               "test_app.py": "from app import render\n\ndef test_r():\n    assert render(1) == '1'\n"})
(ws / "templates_engine.py").write_text("def fill(t, **kw):\n    return t.format(**kw)\n")
(ws / "app.py").write_text("from templates_engine import fill\n\n\ndef render(x):\n    return fill('{x}', x=x)\n")
fin, _ = run(ws, env, [helper(swe, "finalize")])
# what the harness would submit: git add -N . ; git diff --binary _swegemma_baseline (repo config honoured)
subprocess.run(["git", "add", "-N", "."], cwd=ws, env=env)
d = subprocess.run(["git", "diff", "--binary", "_swegemma_baseline", "--stat"], cwd=ws, env=env, capture_output=True,
                   text=True).stdout
exc = subprocess.run(["git", "config", "--local", "--get", "core.excludesFile"], cwd=ws, env=env, capture_output=True,
                     text=True).stdout.strip()
record("F_root_template", finalize=fin, harness_diff_stat=d, excludesFile=exc)

# G. Google-style colocated test with camelCase unittest methods
ws, env, swe, inst = setup("G_colocated_unittest", {
    "pkg/__init__.py": "", "pkg/geo.py": BUGGY + KEEP,
    "pkg/geo_test.py": "import unittest\nfrom pkg.geo import area, keep\n\n\nclass GeoTest(unittest.TestCase):\n\n"
                       "  def testKeep(self):\n    self.assertEqual(keep(), 1)\n\n\n"
                       "if __name__ == '__main__':\n  unittest.main()\n"})
o1, _ = run(ws, env, [helper(swe, "verify"), "--repro-only"], stdin=REPRO.format(mod="pkg.geo"))
(ws / "pkg/geo.py").write_text(FIXED + KEEP.replace("return 1", "return 2"))
o2, t2 = run(ws, env, [helper(swe, "verify")])
record("G_colocated_unittest", repro_only=o1, verify=o2, verify_secs=t2)

# H. two-space indentation (Google internal style): SEARCH/REPLACE with a 4-space REPLACE body
two = ("class Box(object):\n\n  def __init__(self, w, h):\n    self.w = w\n    self.h = h\n\n"
       "  def area(self):\n    return self.w + self.h\n")
ws, env, swe, inst = setup("H_two_space", {"pkg/__init__.py": "", "pkg/box.py": two})
blk = ("<<<<<<< SEARCH\n  def area(self):\n    return self.w + self.h\n=======\n"
       "  def area(self):\n      if self.w < 0:\n          raise ValueError('neg')\n      return self.w * self.h\n"
       ">>>>>>> REPLACE\n")
o, _ = run(ws, env, [helper(swe, "edit"), "pkg/box.py"], stdin=blk)
body = (ws / "pkg/box.py").read_text()
comp = subprocess.run([PY, "-c", "import ast,sys;ast.parse(open(sys.argv[1]).read());print('parses')", "pkg/box.py"],
                      cwd=ws, capture_output=True, text=True)
record("H_two_space", edit=o, file_after=body, parse=(comp.stdout + comp.stderr).strip())

json.dump(results, open(HERE / "probe_results.json", "w"), indent=1)
(SITE / "workspace_paths.pth").unlink(missing_ok=True)
