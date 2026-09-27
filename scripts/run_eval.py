"""swegemma eval with a faithful per-task Python environment for the subprocess sandbox.

Why: SubprocessManager builds each sandbox venv with system_site_packages=True, so the harness's own packages
(requests, rich, httpx, starlette via litellm/ADK) shadow the repository under test, and install_test_dependencies
is a no-op for subprocess sandboxes. Here each sandbox (agent phase and verification phase alike) drops the host link and
pip-installs /workspace plus its test requirements from the competition wheels, letting pip honour version pins.
Usage: python scripts/run_eval.py [--oracle] eval <swegemma eval args>"""
import sys, logging
log = logging.getLogger("run_eval")

SETUP = r'''
set -e
SP=$(python3 -c "import sysconfig;print(sysconfig.get_paths()['purelib'])")
echo /root/buildenv/lib/python3.12/site-packages > "$SP/_host_env.pth"
REPO_PKG="${REPO_PKG:-}"
cd /workspace
python3 - <<'PY' > /tmp/_reqs.txt
import os, re, glob, tomllib
have = {re.split(r"-", f)[0].lower().replace("_", "-") for f in os.listdir("/wheels") if f.endswith(".whl")}
have -= {os.environ.get("REPO_PKG", "").lower()}
lines = ["pytest"]
def keep(req):
    req = req.split(";")[0].strip()
    m = re.match(r"([A-Za-z0-9_.\-]+)(\[[^\]]*\])?\s*(.*)", req)
    if not m: return
    name = m.group(1).lower().replace("_", "-")
    if name in have: lines.append(name + " " + m.group(3).strip())
for f in sorted(set(glob.glob("requirements*.txt") + glob.glob("requirements/*.txt"))):
    if "doc" in f: continue
    for l in open(f):
        l = l.strip()
        if l and not l.startswith(("#", "-")): keep(l)
if os.path.exists("pyproject.toml"):
    d = tomllib.load(open("pyproject.toml", "rb"))
    for r in (d.get("project", {}).get("dependencies") or []): keep(r)
    for n in (d.get("tool", {}).get("poetry", {}).get("dependencies") or {}): keep(n)
    for grp in list((d.get("project", {}).get("optional-dependencies") or {}).values()) + list((d.get("dependency-groups") or {}).values()):
        for r in grp:
            if isinstance(r, str) and not any(k in r for k in ("doc", "mkdocs")): keep(r)
    poetry = d.get("tool", {}).get("poetry", {})
    for sec in [poetry.get("dev-dependencies") or {}] + [g.get("dependencies", {}) for g in (poetry.get("group") or {}).values()]:
        for n in sec: keep(n)
print("\n".join(dict.fromkeys(l.strip() for l in lines)))
PY
printf "pydantic>=2\n" > /tmp/_cons.txt
python3 -m pip install -q --no-index --find-links=/wheels -c /tmp/_cons.txt -r /tmp/_reqs.txt 2>/tmp/_pip.err \
 || while read -r r; do python3 -m pip install -q --no-index --find-links=/wheels "$(echo $r | cut -d' ' -f1)" 2>>/tmp/_pip.err || true; done < /tmp/_reqs.txt
python3 -m pip install -q --no-index --find-links=/wheels "pydantic>=2" 2>>/tmp/_pip.err || true
python3 -m pip install -q --no-index --find-links=/wheels --no-deps --force-reinstall --no-build-isolation -e /workspace 2>>/tmp/_pip.err || true
echo ENV_OK
'''

def faithful_install(docker, container_id, repo="", *, fast_path=True, config=None):
    pkg = (repo or "").rsplit("/", 1)[-1].lower()
    res = docker.exec(container_id, "REPO_PKG=" + pkg + " bash -c " + __import__("shlex").quote(SETUP))
    if "ENV_OK" not in (res.stdout or ""):
        log.warning("env setup failed for %s: %s", repo, (res.stderr or "")[-800:])

import swegemma.harness.agent_runner as ar, swegemma.harness.verification as vf, swegemma.harness.container_setup as cs
for mod in (ar, vf, cs): mod.install_test_dependencies = faithful_install

if "--oracle" in sys.argv:
    sys.argv.remove("--oracle")
    from adk_eval_core.tracing import SessionTrace
    import swegemma.evaluate as ev
    async def _oracle(self, task, snapshot_path, task_index, total_tasks, **kw):
        return task.patch, None, SessionTrace()
    ev.Evaluator._run_agent_sandbox = _oracle

from swegemma.cli import main
sys.exit(main())
