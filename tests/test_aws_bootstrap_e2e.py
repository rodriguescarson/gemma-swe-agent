"""aws/bootstrap.sh end to end, as root in a python:3.12-slim container: the REAL user-data that aws/launch.py builds runs
with fake `aws` (S3 = a local directory), `shutdown` (records its arguments), `curl` (no IMDS), `systemctl` and `uv` on
PATH. Proves the self-shutdown contract on the actual script: the hard timer is set first; S3 is proven writable before
any work; job outputs reach S3 before `shutdown -h now`; that holds when the job fails, when S3 is down and when the
machine is told to stop mid-job (SIGTERM = timer, spot reclaim or API terminate); a relaunch of the same run resumes.
Skipped without Docker or the image (never pulled here)."""
import shutil
import subprocess
import sys
import tarfile
import time
import types
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "aws"))
IMAGE = "python:3.12-slim"


def _docker_ok():
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, timeout=30).returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


pytestmark = pytest.mark.skipif(not _docker_ok(), reason=f"docker or the {IMAGE} image is not available")

FAKE_AWS = r'''#!/usr/bin/env python3
"""aws s3 {cp,sync,ls} against /s3/<bucket>/<key>; /stub/AWS_FAIL makes every call fail (S3 unreachable)."""
import fnmatch, os, shutil, sys
from pathlib import Path
if os.path.exists("/stub/AWS_FAIL"):
    sys.stderr.write("stub aws: S3 unreachable\n"); sys.exit(1)
a = sys.argv[1:]
assert a[0] == "s3", a
cmd, rest = a[1], a[2:]
dry = "--dryrun" in rest
excl = [rest[i + 1] for i, x in enumerate(rest) if x == "--exclude"]
pos = [x for i, x in enumerate(rest) if not x.startswith("--") and (i == 0 or rest[i - 1] != "--exclude")]
loc = lambda u: Path("/s3") / u[5:] if u.startswith("s3://") else Path(u)
if cmd == "ls":
    p = loc(pos[0])
    ok = (p.is_dir() and any(p.iterdir())) if pos[0].endswith("/") else (p.exists() or (p.parent.is_dir() and any(x.name.startswith(p.name) for x in p.parent.iterdir())))
    print(pos[0]) if ok else None; sys.exit(0 if ok else 1)
if cmd == "cp":
    src, dst = loc(pos[0]), loc(pos[1])
    if not src.is_file():
        sys.stderr.write(f"stub aws: no such object {pos[0]}\n"); sys.exit(1)
    dst = dst / src.name if pos[1].endswith("/") else dst
    dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy(src, dst); sys.exit(0)
if cmd == "sync":
    src, dst = loc(pos[0]), loc(pos[1])
    if not src.is_dir():
        sys.exit(0)
    for f in sorted(src.rglob("*")):
        rel = str(f.relative_to(src))
        if not f.is_file() or any(fnmatch.fnmatch(rel, e) for e in excl):
            continue
        t = dst / rel
        if t.is_file() and t.stat().st_size == f.stat().st_size and t.stat().st_mtime + 1 >= f.stat().st_mtime:
            continue   # real S3: same size and uploaded after the last local change (1 s slack for bind-mount mtimes)
        if dry:
            print(f"(dryrun) upload: {f} to {pos[1]}{rel}"); continue
        t.parent.mkdir(parents=True, exist_ok=True); shutil.copy(f, t)   # an upload is stamped now, like LastModified
    sys.exit(0)
sys.exit(2)
'''
FAKE_SHUTDOWN = '#!/bin/sh\necho "$*" >> /stub/shutdown.log\ncase "$2" in +*) mkdir -p /run/systemd/shutdown && touch /run/systemd/shutdown/scheduled ;; esac\n'
NOOP = "#!/bin/sh\nexit 0\n"
FAIL = "#!/bin/sh\nexit 22\n"


def build(tmp_path, job, keep="eval/collect", hours="10", prior=None, s3_down=False, stall_min="30"):
    import launch
    a = launch.parse(["cpu-collect", "--hours", hours, "--run", "s3://g4-e2e/runs/r1", "--job", job, "--setup", "", "--keep", keep,
                      "--stall-min", stall_min])
    launch.validate_args(a)
    image = {"ImageId": "ami-0e2e", "RootDeviceName": "/dev/sda1", "BlockDeviceMappings": [{"DeviceName": "/dev/sda1", "Ebs": {"VolumeSize": 8}}]}
    req = launch.build_request(a, image)
    launch.check_request(req, "cpu-collect", float(hours))
    stub, s3, box = tmp_path / "stub", tmp_path / "s3", tmp_path / "box"
    (stub / "bin").mkdir(parents=True); box.mkdir()
    for name, body in (("aws", FAKE_AWS), ("shutdown", FAKE_SHUTDOWN), ("systemctl", NOOP), ("uv", NOOP), ("curl", FAIL)):
        (stub / "bin" / name).write_text(body); (stub / "bin" / name).chmod(0o755)
    (stub / "userdata.sh").write_text(req["UserData"])
    if s3_down:
        (stub / "AWS_FAIL").write_text("")
    src = tmp_path / "src"
    (src / "eval").mkdir(parents=True); (src / "eval" / "README").write_text("repo\n")
    run = s3 / "g4-e2e" / "runs" / "r1"
    (run / "in").mkdir(parents=True)
    with tarfile.open(run / "in" / "code.tgz", "w:gz") as t:
        t.add(src / "eval", arcname="eval")
    (run / "in" / "overlay" / "data").mkdir(parents=True); (run / "in" / "overlay" / "data" / "ids.txt").write_text("t1\n")
    for rel, text in (prior or {}).items():
        (run / "out" / "keep" / rel).parent.mkdir(parents=True, exist_ok=True); (run / "out" / "keep" / rel).write_text(text)
    return types.SimpleNamespace(stub=stub, s3=s3, box=box, run=run, name=f"g4e2e-{uuid.uuid4().hex[:8]}")


def docker_args(w, detach=False):
    return ["docker", "run", "--rm", *(["-d"] if detach else []), "--name", w.name, "--hostname", "i-0e2e",
            "-v", f"{w.stub}:/stub", "-v", f"{w.s3}:/s3", "-v", f"{w.box}:/opt/g4/out",
            "-e", "PATH=/stub/bin:/usr/local/bin:/usr/bin:/bin", IMAGE, "bash", "/stub/userdata.sh"]


def run(w, timeout=120):
    try:
        return subprocess.run(docker_args(w), capture_output=True, text=True, timeout=timeout)
    finally:
        subprocess.run(["docker", "rm", "-f", w.name], capture_output=True)


def shutdowns(w):
    return (w.stub / "shutdown.log").read_text().splitlines()


def test_success_syncs_outputs_then_shuts_down(tmp_path):
    w = build(tmp_path, "test -f data/ids.txt && mkdir -p eval/collect && echo solved > eval/collect/a.txt && echo job-ran")
    r = run(w)
    assert r.returncode == 0, (r.stdout, r.stderr, (w.box / "boot.log").read_text())
    sd = shutdowns(w)
    assert sd[0].startswith("-h +600 gemma4-agent hard timer") and sd[-1] == "-h now" and len(sd) == 2
    box = w.run / "out" / "box" / "i-0e2e"
    assert (box / "job.out").read_text().strip() == "job-ran"
    assert "rc=0" in (box / "RESULT").read_text() and (box / "BOOT").is_file()
    assert (w.run / "out" / "keep" / "eval" / "collect" / "a.txt").read_text() == "solved\n"
    prog = (w.box / "progress.log").read_text()
    assert prog.index("JOB_DONE rc=0") < prog.index("SYNC_OK final") < prog.index("SHUTDOWN now")


def test_a_failing_job_still_syncs_and_shuts_down(tmp_path):
    w = build(tmp_path, "mkdir -p eval/collect && echo partial > eval/collect/p.txt && exit 7")
    r = run(w)
    assert r.returncode == 7
    assert shutdowns(w)[-1] == "-h now"
    assert "rc=7" in (w.run / "out" / "box" / "i-0e2e" / "RESULT").read_text()
    assert (w.run / "out" / "keep" / "eval" / "collect" / "p.txt").is_file()


def test_unwritable_s3_stops_before_any_work(tmp_path):
    w = build(tmp_path, "echo SHOULD-NOT-RUN > /opt/g4/out/ran", s3_down=True)
    t0 = time.monotonic()
    r = run(w)
    assert r.returncode == 3 and time.monotonic() - t0 < 60          # no final-sync retries when S3 never worked
    assert shutdowns(w)[-1] == "-h now"
    prog = (w.box / "progress.log").read_text()
    assert "S3 not writable" in prog and "JOB_START" not in prog and not (w.box / "ran").exists()


def test_a_relaunch_of_the_same_run_resumes_from_keep(tmp_path):
    w = build(tmp_path, "test -f eval/collect/prev.txt && echo more >> eval/collect/prev.txt",
              prior={"eval/collect/prev.txt": "from attempt 1\n"})
    r = run(w)
    assert r.returncode == 0, (w.box / "boot.log").read_text()
    assert (w.run / "out" / "keep" / "eval" / "collect" / "prev.txt").read_text() == "from attempt 1\nmore\n"


def test_sigterm_mid_job_kills_the_job_syncs_once_and_shuts_down(tmp_path):
    w = build(tmp_path, "mkdir -p eval/collect && echo checkpoint > eval/collect/ckpt.txt && sleep 300")
    try:
        assert subprocess.run(docker_args(w, detach=True), capture_output=True, timeout=60).returncode == 0
        prog = w.box / "progress.log"
        for _ in range(120):
            if prog.exists() and "JOB_START" in prog.read_text():
                break
            time.sleep(0.5)
        time.sleep(1)
        subprocess.run(["docker", "kill", "--signal", "TERM", w.name], capture_output=True, timeout=30)
        rc = subprocess.run(["docker", "wait", w.name], capture_output=True, text=True, timeout=120).stdout.strip()
    finally:
        subprocess.run(["docker", "rm", "-f", w.name], capture_output=True)
    assert rc == "143"
    assert shutdowns(w)[-1] == "-h now"
    text = prog.read_text()
    assert "SYNC_OK stop" in text and "SYNC_OK final" not in text      # one bounded try while the OS goes down
    assert "rc=143" in (w.run / "out" / "box" / "i-0e2e" / "RESULT").read_text()
    assert (w.run / "out" / "keep" / "eval" / "collect" / "ckpt.txt").read_text() == "checkpoint\n"


def test_a_silent_hung_job_is_ended_by_the_stall_rule_and_the_machine_stops(tmp_path):
    """No output change for G4_STALL_MIN (1 here) and no GPU: the watcher kills the job's group; the box syncs and stops."""
    w = build(tmp_path, "mkdir -p eval/collect && sleep 600", stall_min="1")
    t0 = time.monotonic()
    r = run(w, timeout=300)
    assert r.returncode == 143 and time.monotonic() - t0 < 240
    assert shutdowns(w)[-1] == "-h now"
    prog = (w.box / "progress.log").read_text()
    assert prog.index("ALERT STALL") < prog.index("JOB_DONE rc=143") < prog.index("SYNC_OK final")
