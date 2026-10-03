"""(K) an import-time NameError introduced in a changed module: flat package (control) vs namespace package vs a
package under python/ with no test importing it; does verify flag it?"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import probe_layouts as P
for name, files, path, mod in (
    ("K_flat", {"pkg/__init__.py": "", "pkg/geo.py": P.BUGGY + P.KEEP, "pkg/other.py": "X = 1\n"}, "pkg/geo.py", "pkg.geo"),
    ("K_namespace", {"nspkg/geo.py": P.BUGGY + P.KEEP, "nspkg/other.py": "X = 1\n"}, "nspkg/geo.py", "nspkg.geo"),
    ("K_pythondir", {"python/pkg/__init__.py": "", "python/pkg/geo.py": P.BUGGY + P.KEEP}, "python/pkg/geo.py", "pkg.geo")):
    ws, env, swe, inst = P.setup(name, files)
    o1, _ = P.run(ws, env, [P.helper(swe, "verify"), "--repro-only"], stdin=P.REPRO.format(mod=mod))
    (ws / path).write_text(P.FIXED + P.KEEP + "\nundefined_helper_zz()\n")
    o2, t2 = P.run(ws, env, [P.helper(swe, "verify")])
    o3, _ = P.run(ws, env, [P.helper(swe, "finalize")])
    P.record(name, verify=o2, finalize=o3)
(P.SITE / "workspace_paths.pth").unlink(missing_ok=True)
