"""Driver: scripts/run_eval.py unchanged, plus one wrapper that appends -rA to the scorer's pytest command so the
full output lists every PASSED/FAILED test id. Outcomes (exit code, pass/fail) are unaffected by -rA."""
import importlib.util, sys
R = "<repo>"
spec = importlib.util.spec_from_file_location("run_eval_nm", R + "/scripts/run_eval.py")
m = importlib.util.module_from_spec(spec); sys.modules["run_eval_nm"] = m; spec.loader.exec_module(m)
import swegemma.harness.verification as V
orig = V.sandbox_exec
async def wrapped(docker, sid, cmd, *a, **k):
    if isinstance(cmd, str) and "-m pytest" in cmd and "--junitxml" in cmd and cmd.rstrip().endswith("-q"):
        cmd = cmd.rstrip() + " -rA"
    return await orig(docker, sid, cmd, *a, **k)
V.sandbox_exec = wrapped
sys.exit(m.main(sys.argv[1:]))
