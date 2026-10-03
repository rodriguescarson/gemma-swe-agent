"""Two more probes: (I) the submit guard alone on a new root module named template*.py (no finalize), and
(J) first-call cost of locate/verify on a large repo (20,000 .py files), Docker-like env, Python 3.13."""
import os, pathlib, shutil, subprocess, sys, time
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import probe_layouts as P  # noqa: E402  (re-runs A-H on import; cheap)

# I. guard only
ws, env, swe, inst = P.setup("I_guard_only", {"app.py": "def render(x):\n    return str(x)\n", "helpers.py": "X = 1\n"})
(ws / "template.py").write_text("def fill(t):\n    return t\n")
(ws / "app.py").write_text("from template import fill\n\n\ndef render(x):\n    return fill(str(x))\n")
subprocess.run(["git", "add", "-N", "."], cwd=ws, env=env)
stat = subprocess.run(["git", "diff", "--binary", "_swegemma_baseline", "--stat"], cwd=ws, env=env,
                      capture_output=True, text=True).stdout
P.record("I_guard_only", harness_diff_stat=stat)

# J. large repo
files = {"pkg/__init__.py": ""}
for i in range(200):
    files["pkg/sub%03d/__init__.py" % i] = ""
    for j in range(100):
        files["pkg/sub%03d/m%03d.py" % (i, j)] = ("import os\n\n\ndef f_%d_%d(x):\n    return x + %d\n\n\n"
                                                  "class C_%d_%d(object):\n    def g(self):\n        return %d\n"
                                                  % (i, j, j, i, j, i)) * 8
files["pkg/special.py"] = "def area(w, h):\n    return w + h\n\n\ndef keep():\n    return 1\n"
files["tests/test_special.py"] = "from pkg.special import area, keep\n\n\ndef test_keep():\n    assert keep() == 1\n"
t0 = time.time()
ws, env, swe, inst = P.setup("J_big", files)
build = round(time.time() - t0, 1)
o1, t1 = P.run(ws, env, [P.helper(swe, "locate"), "area of rectangle special"])
o2, t2 = P.run(ws, env, [P.helper(swe, "verify"), "--repro-only"], stdin=P.REPRO.format(mod="pkg.special"))
(ws / "pkg/special.py").write_text("def area(w, h):\n    return w * h\n\n\ndef keep():\n    return 1\n")
o3, t3 = P.run(ws, env, [P.helper(swe, "verify")])
o4, t4 = P.run(ws, env, [P.helper(swe, "grep"), "def area"])
P.record("J_big", files=len(files), repo_build_secs=build, locate=o1[:600], locate_secs=t1, repro=o2[:400],
         repro_secs=t2, verify=o3[:900], verify_secs=t3, grep=o4[:300], grep_secs=t4)
(P.SITE / "workspace_paths.pth").unlink(missing_ok=True)
