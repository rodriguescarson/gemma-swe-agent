"""scripts/arm_box_submit.sh against a bare origin: it reads the box's pushed P2_LOG END line and results.jsonl with git show,
applies box_p4_gate.py, and (DRY_RUN) would submit on PASS, logs FAIL, and gives up at the deadline (2026-10-13, sub15b)."""
import json, os, pathlib, shutil, subprocess, sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x", "GIT_CONFIG_NOSYSTEM": "1"}


def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, env=ENV, capture_output=True, text=True, check=True).stdout


def setup(tmp_path, end=True, solved=30, results=True):
    bare = tmp_path / "o.git"; git(tmp_path, "init", "-q", "--bare", "-b", "wip/gemma-agent", str(bare))
    box = tmp_path / "box"; git(tmp_path, "clone", "-q", str(bare), str(box)); git(box, "checkout", "-q", "-b", "wip/gemma-agent")
    ids = [l.strip() for l in open(ROOT / "data" / "kaggle_valid_ids.txt") if l.strip()]
    (box / "docs" / "a6000").mkdir(parents=True)
    (box / "docs" / "a6000" / "P2_LOG.md").write_text("- x | step=p4_b1024 | EVENT started\n" + ("- y | step=p4_b1024 | END done: done=74/74 solved=30\n" if end else ""))
    if results:
        d = box / "eval" / "a6000" / "results" / "p4_b1024"; d.mkdir(parents=True)
        d.joinpath("results.jsonl").write_text("".join(json.dumps({"id": t, "resolved": i < solved, "secs": 100, "err": None}) + "\n" for i, t in enumerate(ids)))
    git(box, "add", "-A"); git(box, "commit", "-q", "-m", "box"); git(box, "push", "-q", "-u", "origin", "wip/gemma-agent")
    mac = tmp_path / "mac"; git(tmp_path, "clone", "-q", "-b", "wip/gemma-agent", str(bare), str(mac))
    for rel in ("scripts/arm_box_submit.sh", "scripts/box_p4_gate.py", "data/kaggle_valid_ids.txt"):
        (mac / rel).parent.mkdir(parents=True, exist_ok=True); shutil.copy(ROOT / rel, mac / rel)
    return mac


def run(mac, deadline="2099-01-01T00:00:00Z"):
    env = {**ENV, "DRY_RUN": "1", "POLL_S": "1", "PY": sys.executable, "SUBMIT_LOG": str(mac / "log.txt")}
    return subprocess.run(["bash", str(mac / "scripts/arm_box_submit.sh"), "p4_b1024", "g4agent-v12-b1024", "2", deadline, "sub15b: v12-b1024 test", "26"],
                          cwd=mac, env=env, capture_output=True, text=True, timeout=60)


def test_pass_would_submit_with_the_gate_numbers_in_the_message(tmp_path):
    mac = setup(tmp_path)
    head = git(mac, "rev-parse", "HEAD")
    r = run(mac); log = (mac / "log.txt").read_text()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "gate: PASS solved 30/74 crash 0 errored 0" in log and "DRY_RUN: would submit g4agent-v12-b1024 v2: sub15b: v12-b1024 test; box 74 public: solved 30/74 crash 0 errored 0" in log
    assert git(mac, "rev-parse", "HEAD") == head and subprocess.run(["git", "diff", "--quiet"], cwd=mac).returncode == 0   # fetch only


def test_fail_logs_and_does_not_submit(tmp_path):
    mac = setup(tmp_path, solved=10)
    r = run(mac); log = (mac / "log.txt").read_text()
    assert r.returncode == 1 and "gate: FAIL solved 10/74" in log and "would submit" not in log


def test_deadline_without_an_end_line(tmp_path):
    mac = setup(tmp_path, end=False)
    r = run(mac, deadline="2000-01-01T00:00:00Z")
    assert r.returncode == 3 and "deadline 2000-01-01T00:00:00Z passed before a decision" in (mac / "log.txt").read_text()


@pytest.mark.parametrize("submit_rc", [0, 1, 3, 4])
def test_a_pass_without_dry_run_exits_with_submit_ats_status(tmp_path, submit_rc):
    # the mac clone carries its own scripts/: put a stub submit_at.sh there, so nothing reaches Kaggle. A give-up (1) must not be read as success.
    mac = setup(tmp_path)
    (mac / "scripts" / "submit_at.sh").write_text(
        '#!/bin/bash\necho "kernel=$1 at=$2 tag=$4 ver=$KERNEL_VERSION epoch=$SUBMIT_TARGET_EPOCH msg=$3" >> "$STUB_LOG"\nexit "$STUB_RC"\n')
    env = {**ENV, "POLL_S": "1", "PY": sys.executable, "SUBMIT_LOG": str(mac / "log.txt"), "STUB_LOG": str(mac / "stub.log"), "STUB_RC": str(submit_rc)}
    r = subprocess.run(["bash", str(mac / "scripts/arm_box_submit.sh"), "p4_b1024", "g4agent-v12-b1024", "2", "2099-01-01T00:00:00Z", "sub15b: v12-b1024 test", "26"],
                       cwd=mac, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == submit_rc, r.stdout + r.stderr
    call = (mac / "stub.log").read_text().splitlines()
    assert len(call) == 1 and call[0].startswith("kernel=g4agent-v12-b1024 at=0000 tag=sub15b: ver=2 epoch=0 msg=sub15b: v12-b1024 test; box 74 public: solved 30/74")
    assert "PASS -> submitting g4agent-v12-b1024 v2 now" in (mac / "log.txt").read_text()
