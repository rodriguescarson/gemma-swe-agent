"""The RunPod Linux gate (2026-11-03): scripts/runpod/bin/docker stands in for `docker run` so scripts/linux_test.sh runs
unchanged on a RunPod CPU pod, and scripts/runpod/pod_watchdog.py removes that pod when it is idle, past its hard limit or
told to go. These tests use the shim's dry run (no network) and the watchdog's pure parts; the live check is a real run."""
import importlib.util
import json
import os
import re
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHIM = ROOT / "scripts" / "runpod" / "bin" / "docker"


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


WD = _module("pod_watchdog", ROOT / "scripts" / "runpod" / "pod_watchdog.py")
BODY = _module("pod_body", ROOT / "scripts" / "runpod" / "pod_body.py")


def _dry(tmp_path, **env):
    """linux_test.sh's own container command, through the shim's dry run."""
    e = dict(os.environ, PATH=f"{SHIM.parent}:{os.environ['PATH']}", G4_POD_DRY="1", MIN_FREE_GB="0",
             LINUX_TEST_OUT=str(tmp_path / "out"), G4_WS=str(tmp_path / "ws"), **env)
    r = subprocess.run(["bash", str(ROOT / "scripts" / "linux_test.sh")], cwd=ROOT, env=e, capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, r.stderr[-1000:]
    plan, script = r.stdout.split("--- pod-side script\n", 1)
    return plan.splitlines(), script, r.stderr


def test_shim_and_the_pod_start_script_lint(tmp_path):
    start = tmp_path / "start.sh"
    start.write_text(json.loads(BODY.body()["args"])["cmd"][0])
    for p in (SHIM, start):
        assert subprocess.run(["bash", "-n", str(p)]).returncode == 0, p
        if shutil.which("shellcheck"):
            r = subprocess.run(["shellcheck", "-S", "warning", "-s", "bash", str(p)], capture_output=True, text=True)
            assert r.returncode == 0, r.stdout


def test_the_full_suite_command_maps_every_mount(tmp_path):
    plan, script, _ = _dry(tmp_path)
    assert "image python:3.12-slim" in plan and "workdir /tmp" in plan
    up = {l.split()[1]: l for l in plan if l.startswith("upload ")}
    repo = up[str(ROOT)]
    assert " -> /g4 " in repo
    for nested in ("/data", "/eval/golden", "/eval/kaggle", "/eval/collect"):     # uploaded on their own, not twice
        assert f"--exclude={nested} " in repo, nested
    assert "--exclude=/.venv" in repo and "--exclude=__pycache__" in repo
    assert up[str(ROOT / "data")].split()[3] == "/tmp/g4/data"
    assert "volume g4-pip-cache -> /root/.cache/pip" in plan
    assert "empty /root/.cache/g4/ws" in plan                       # 24 GB on the Mac; every reader skips without snapshots
    assert f"out /out -> {tmp_path / 'out'}" in plan
    assert subprocess.run(["bash", "-n"], input=script, text=True).returncode == 0


def test_the_pod_runs_the_containers_script_verbatim_in_a_fresh_layout(tmp_path):
    _, script, _ = _dry(tmp_path)
    lines = script.splitlines()
    assert lines[1].startswith("find /tmp -mindepth 1 -maxdepth 1 -exec rm -rf")      # /tmp as a new container has it
    # real directories, never symlinks: a symlinked data/ broke path relativisation (test_linux_test_script.py)
    assert "cp -a /root/g4m/store/tmp__g4__data/. /tmp/g4/data/" in script and "ln -s /root/g4m/store" not in script
    prefix = 'exec env -i "${img[@]}" HOME=/root TESTS= bash -c '
    assert lines[-1].startswith(prefix)
    body = subprocess.run(["bash", "-c", 'eval "a=($1)"; printf %s "${a[0]}"', "_", lines[-1][len(prefix):]],
                          capture_output=True, text=True).stdout
    full = (ROOT / "scripts" / "linux_test.sh").read_text()
    assert "pip -q install peft==" in body and body.rstrip().endswith("exit $rc")
    assert body.splitlines()[0] in full                         # the STAGE_SCRIPT's first line, as linux_test.sh wrote it


def test_the_pods_secrets_never_reach_the_suite(tmp_path):
    _, script, _ = _dry(tmp_path)
    env_line = next(l for l in script.splitlines() if l.startswith("img=()"))
    for dropped in ("RUNPOD_*", "PUBLIC_KEY=*", "G4_POD_*"):
        assert dropped in env_line
    assert "env -i" in script.splitlines()[-1]


def test_the_v10_branch_reports_what_it_cannot_emulate(tmp_path):
    plan, _, err = _dry(tmp_path, V10_ONLY="1")
    assert "--cpus 2 is not emulated" in err and "--memory 4g is not emulated" in err
    assert "image python:3.12-slim" in plan


def test_unsupported_calls_fail_like_a_docker_error(tmp_path):
    for argv in (["ps"], ["run", "--privileged", "img", "true"], ["run"]):
        r = subprocess.run(["bash", str(SHIM), *argv], capture_output=True, text=True, timeout=30,
                           env=dict(os.environ, G4_POD_DRY="1"))
        assert r.returncode == 125, (argv, r.stderr)


def test_a_real_run_needs_the_pod(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("G4_POD")}
    r = subprocess.run(["bash", str(SHIM), "run", "python:3.12-slim", "true"], capture_output=True, text=True, env=env,
                       timeout=30)
    assert r.returncode == 125 and "G4_POD" in r.stderr


@pytest.mark.parametrize("case,want", [
    (dict(now=100, busy=False, hb=99, stop=False), None),
    (dict(now=4 * 3600 + 1, busy=True, hb=4 * 3600, stop=False), "hard limit"),
    (dict(now=200, busy=True, hb=0, stop=True), "terminate_now"),
    (dict(now=41 * 60 + 1, busy=False, hb=0, stop=False), "idle"),
    (dict(now=41 * 60 + 1, busy=True, hb=0, stop=False), None),          # a long run is not idle
])
def test_watchdog_reasons(case, want):
    assert WD.reason(case["now"], 0, 4, 40, case["busy"], case["hb"], case["stop"]) == want


def test_watchdog_tries_rest_then_graphql_and_never_logs_the_key():
    seen, logged = [], []

    class Resp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def opener(req, timeout):
        seen.append((req.get_method(), req.full_url, req.headers.get("Authorization")))
        if "rest.runpod.io" in req.full_url:
            raise OSError("down")
        return Resp()

    WD.terminate("pod123", "sekrit-key", logged.append, opener=opener)
    assert [s[0] for s in seen] == ["DELETE", "POST"] and seen[0][1].endswith("/pods/pod123")
    assert all(s[2] == "Bearer sekrit-key" for s in seen)
    assert len(logged) == 2 and not any("sekrit" in l for l in logged)


def test_pod_body_starts_the_watchdog_before_anything_can_fail():
    b = BODY.body()
    assert b["image"] == "python:3.12-slim" == b["env"]["G4_POD_IMAGE"] and BODY.body("3.13")["image"] == "python:3.13-slim"
    assert b["cpu"] == {"id": "cpu3g", "vcpuCount": 8} and b["ports"] == ["22/tcp"] and b["startSsh"] is True
    start = json.loads(b["args"])["cmd"][0]
    assert (ROOT / "scripts" / "runpod" / "pod_watchdog.py").read_text().rstrip("\n") in start
    assert start.index("watchdog.py > /root/g4m/watchdog.out") < start.index("apt-get update") < start.index("/usr/sbin/sshd -e")


def test_the_repo_comes_from_git_and_only_small_files_and_the_manifest_from_the_mac(tmp_path):
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    plan, _, _ = _dry(tmp_path)
    assert f"git {ROOT} at {head}" in plan
    up = {l.split()[1]: l for l in plan if l.startswith("upload ")}
    assert re.search(r"\[git seed \+ \d+ files, [\d.]+ MB up to 1048576 B\]", up[str(ROOT)]), up[str(ROOT)]
    assert "[git seed data + manifest " in up[str(ROOT / "data")]
    assert "[git seed eval/collect + manifest " in up[str(ROOT / "eval" / "collect")]


def test_manifest_entries_are_split_by_mount(tmp_path):
    m = tmp_path / "manifest.txt"
    m.write_text("# comment\ndata/heldout1k/tasks.jsonl   # why\neval/golden/runs/x.json\n\ndata/raw/wheels/a.whl\n")
    plan, _, _ = _dry(tmp_path, G4_POD_MANIFEST=str(m))
    up = {l.split()[1]: l for l in plan if l.startswith("upload ")}
    assert "manifest 2 files" in up[str(ROOT / "data")] and "manifest 1 files" in up[str(ROOT / "eval" / "golden")]
    assert "manifest 0 files" in up[str(ROOT / "eval" / "kaggle")]


def test_pod_helpers_lint_and_the_chain_retires_the_pod_only_in_runpod_mode():
    for name in ("retire.sh", "keepalive.sh"):
        p = ROOT / "scripts" / "runpod" / name
        assert subprocess.run(["bash", "-n", str(p)]).returncode == 0
        if shutil.which("shellcheck"):
            assert subprocess.run(["shellcheck", "-S", "warning", str(p)]).returncode == 0, name
    chain = (ROOT / "eval" / "arm_sub28_v12b55.sh").read_text()
    assert chain.index("keepalive.sh $$") < chain.index('ship.sh "submissions/$B" "$EVAL" eval')
    assert chain.index("retire.sh") > chain.index('ship.sh "submissions/$B" "$SLUG" submit')
    assert chain.count('if [ "${SHIP_LINUX:-docker}" = runpod ]') == 2


def test_the_pod_installs_git_for_the_clone():
    start = json.loads(BODY.body()["args"])["cmd"][0]
    assert "openssh-server rsync git ca-certificates" in start


def test_only_files_that_differ_from_head_and_fit_the_cap_are_sent(tmp_path):
    """A throwaway repo: tracked unchanged / modified, untracked small / big, ignored small, a nested mount's files, .venv
    and __pycache__. The repo mount sends the modified, untracked-small and ignored-small files (3); the nested mount's own
    files and everything over the cap stay behind."""
    r = tmp_path / "repo"; (r / "data").mkdir(parents=True); (r / ".venv").mkdir(); (r / "pkg" / "__pycache__").mkdir(parents=True)
    run = lambda *a: subprocess.run(["git", "-C", str(r), *a], check=True, capture_output=True)
    run("init", "-q"); (r / ".gitignore").write_text("*.log\n.venv/\n")
    (r / "same.txt").write_text("a"); (r / "mod.txt").write_text("a"); (r / "data" / "t.json").write_text("a")
    run("add", "-A"); run("-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "x")
    (r / "mod.txt").write_text("b"); (r / "new.txt").write_text("n"); (r / "big.bin").write_bytes(b"x" * 500)
    (r / "out.log").write_text("l"); (r / "data" / "t.json").write_text("b"); (r / "data" / "u.bin").write_text("u")
    (r / ".venv" / "v.py").write_text("v"); (r / "pkg" / "__pycache__" / "m.pyc").write_bytes(b"c")
    e = dict(os.environ, G4_POD_DRY="1", G4_POD_MAX_BYTES="100")
    out = subprocess.run(["bash", str(SHIM), "run", "-v", f"{r}:/g4:ro", "-v", f"{r}/data:/tmp/g4/data:ro", "python:3.12-slim",
                          "bash", "-c", "true"], env=e, capture_output=True, text=True, timeout=60).stdout
    line = next(l for l in out.splitlines() if l.startswith(f"upload {r} "))
    assert "[git seed + 3 files," in line, line
