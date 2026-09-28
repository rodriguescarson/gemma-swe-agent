"""swegemma eval with a faithful per-task Python environment for the subprocess sandbox.

Why: SubprocessManager builds each sandbox venv with system_site_packages=True, so the harness's own packages
(requests, rich, httpx, starlette via litellm/ADK) shadow the repository under test, and install_test_dependencies
is a no-op for subprocess sandboxes. Here each sandbox (agent phase and verification phase alike) drops the host link and
pip-installs /workspace plus its test requirements from the competition wheels, letting pip honour version pins.
Usage: python scripts/run_eval.py [--oracle] eval <swegemma eval args>

Faithfulness switches (SPEC section 10.1, R115); every default leaves other callers of swegemma untouched:
  G4_COMPACTION   default 1: EvalConfig gets EventsCompactionConfig(compaction_interval=5, overlap_size=2,
                  token_threshold=14336, event_retention_size=5), the organiser README value (HARNESS_README 553-561).
                  Pod races never compacted before this (config_space finding 6). 0 disables it.
  G4_L4_SCALE=s   divides --max-time-minutes and --timeout-seconds by s (H100 -> L4 wall ratio, time_model 6) and
                  writes s to /tmp/swe/clock_scale in every AGENT sandbox (the command text is rewritten by the
                  subprocess sandbox, so it lands in <sandbox>/tmp/swe), so v10 helper footers fire at L4-equivalent times.
  G4_NO_EDITABLE  1: skip the `pip install -e /workspace` step (Kaggle installs nothing into /workspace, F9d).
  G4_FAITHFUL_ENV default 1: the pod environment install below. 0 keeps the stock harness environment (the offline
                  Mac flow tests use it; /root/buildenv does not exist there).
Importing this module changes nothing; only main() patches the harness.
"""
import logging
import os
import shlex
import sys

log = logging.getLogger("run_eval")

COMPACTION = {"compaction_interval": 5, "overlap_size": 2, "token_threshold": 14336, "event_retention_size": 5}

SETUP_HEAD = r'''
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
'''
EDITABLE_STEP = "python3 -m pip install -q --no-index --find-links=/wheels --no-deps --force-reinstall --no-build-isolation -e /workspace 2>>/tmp/_pip.err || true\n"
SETUP_TAIL = "echo ENV_OK\n"


def setup_script(no_editable=False):
    """The pod environment script; with no_editable the repo is only importable through PYTHONPATH, as on Kaggle."""
    return SETUP_HEAD + ("" if no_editable else EDITABLE_STEP) + SETUP_TAIL


SETUP = setup_script(False)   # backwards-compatible name (the historical script, editable install included)


def env_flag(name, default="0"):
    return (os.environ.get(name, default) or default).strip().lower() in ("1", "true", "yes", "on")


def faithful_install(docker, container_id, repo="", *, fast_path=True, config=None):
    pkg = (repo or "").rsplit("/", 1)[-1].lower()
    script = setup_script(no_editable=env_flag("G4_NO_EDITABLE"))
    res = docker.exec(container_id, "REPO_PKG=" + shlex.quote(pkg) + " bash -c " + shlex.quote(script))
    if "ENV_OK" not in (res.stdout or ""):
        log.warning("env setup failed for %s: %s", repo, (res.stderr or "")[-800:])


faithful_install._g4 = True
_HARNESS_ORIG = {}   # module name -> the harness's own install_test_dependencies (main() may run more than once)


def _harness_original(mod):
    cur = mod.install_test_dependencies
    if not getattr(cur, "_g4", False):
        _HARNESS_ORIG[mod.__name__] = cur
    return _HARNESS_ORIG.get(mod.__name__, cur)


def l4_scale():
    """G4_L4_SCALE as a float > 0, or None when unset/empty. Invalid values stop the run before any GPU time."""
    raw = (os.environ.get("G4_L4_SCALE") or "").strip()
    if not raw:
        return None
    try:
        s = float(raw)
    except ValueError:
        raise SystemExit(f"run_eval: G4_L4_SCALE must be a number, got {raw!r}")
    if not 0.2 <= s <= 5.0:   # the helpers clamp clock_scale to 0.2..5 (SPEC 4.1.5); refuse what they would ignore
        raise SystemExit(f"run_eval: G4_L4_SCALE must be within 0.2..5, got {s}")
    return s


def scale_argv(argv, s):
    """Divide --max-time-minutes (float) and --timeout-seconds (int, rounded, >= 1) by s; both '--k v' and '--k=v'."""
    def conv(key, val):
        if key == "--max-time-minutes":
            return repr(round(float(val) / s, 6))
        return str(max(1, int(round(float(val) / s))))
    out, i = [], 0
    keys = ("--max-time-minutes", "--timeout-seconds")
    while i < len(argv):
        a = argv[i]
        k, eq, v = a.partition("=")
        if k in keys and eq:
            out.append(f"{k}={conv(k, v)}")
        elif a in keys and i + 1 < len(argv):
            out += [a, conv(a, argv[i + 1])]
            i += 1
        else:
            out.append(a)
        i += 1
    return out


def clock_scale_cmd(s):
    # /tmp is rewritten to <sandbox>/tmp in command text by the subprocess sandbox (subprocess.py:432-481), so this
    # lands exactly where the helpers look ($TEST_TMPDIR/swe); in Docker /tmp is the container's own.
    return f"mkdir -p /tmp/swe && printf '%s\\n' {shlex.quote(repr(s))} > /tmp/swe/clock_scale"


def agent_install(base, s):
    """The agent-phase install_test_dependencies: base behaviour, then the clock_scale write."""
    def install(docker, container_id, repo="", *, fast_path=True, config=None):
        base(docker, container_id, repo, fast_path=fast_path, config=config)
        res = docker.exec(container_id, clock_scale_cmd(s))
        if getattr(res, "exit_code", 0) not in (0, None):
            log.warning("clock_scale write failed in %s: %s", container_id, getattr(res, "stderr", ""))
    install.__name__ = "agent_install_with_clock_scale"
    install._g4 = True
    return install


def install_patches(faithful, scale):
    """Patch the harness module globals (idempotent: always built from the harness originals).

    Returns the harness originals so callers (tests) can restore them."""
    import swegemma.harness.agent_runner as ar
    import swegemma.harness.container_setup as cs
    import swegemma.harness.verification as vf
    orig = {m: _harness_original(m) for m in (ar, vf, cs)}
    base = faithful_install if faithful else orig[ar]
    ar.install_test_dependencies = agent_install(base, scale) if scale else base
    for m in (vf, cs):
        m.install_test_dependencies = faithful_install if faithful else orig[m]
    return orig


def compaction_config():
    import warnings
    try:
        from google.adk.apps._configs import EventsCompactionConfig
    except ImportError:
        from google.adk.apps.app import EventsCompactionConfig
    with warnings.catch_warnings():   # ADK flags the class [EXPERIMENTAL] on every construction; the scorer uses it
        warnings.simplefilter("ignore", UserWarning)
        return EventsCompactionConfig(**COMPACTION)


def wrap_eval_config(enabled):
    """cli.EvalConfig -> a factory that adds the compaction config unless the caller passed one."""
    import swegemma.cli as cli
    base = getattr(cli.EvalConfig, "__wrapped__", cli.EvalConfig)   # re-entrant: never wrap our own wrapper

    def EvalConfig(*a, **kw):
        if enabled and kw.get("events_compaction_config") is None:
            kw["events_compaction_config"] = compaction_config()
        return base(*a, **kw)

    EvalConfig.__wrapped__ = base
    cli.EvalConfig = EvalConfig
    return base


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    oracle = "--oracle" in argv
    if oracle:
        argv.remove("--oracle")
    scale = l4_scale()
    if scale:
        argv = scale_argv(argv, scale)
    install_patches(faithful=env_flag("G4_FAITHFUL_ENV", "1"), scale=scale)
    wrap_eval_config(enabled=env_flag("G4_COMPACTION", "1"))
    log.info("run_eval: compaction=%s l4_scale=%s no_editable=%s", env_flag("G4_COMPACTION", "1"), scale,
             env_flag("G4_NO_EDITABLE"))
    if oracle:
        from adk_eval_core.tracing import SessionTrace
        import swegemma.evaluate as ev

        async def _oracle(self, task, snapshot_path, task_index, total_tasks, **kw):
            return task.patch, None, SessionTrace()
        ev.Evaluator._run_agent_sandbox = _oracle
    from swegemma.cli import main as cli_main
    return cli_main(argv)


if __name__ == "__main__":
    sys.exit(main())
