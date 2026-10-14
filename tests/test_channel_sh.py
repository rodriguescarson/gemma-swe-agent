"""scripts/a6000/channel.sh: the Mac <-> box channel through git (docs/a6000/channel/README.md). A bare origin and two clones
play the two sides; written before the script was first used (2026-10-12)."""
import os, pathlib, shutil, subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "a6000" / "channel.sh"
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x", "GIT_CONFIG_NOSYSTEM": "1"}


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, env=ENV, capture_output=True, text=True, check=True).stdout


def ch(cwd, side, *args, check=True):
    r = subprocess.run(["bash", str(cwd / "scripts" / "a6000" / "channel.sh"), *args], cwd=cwd, env={**ENV, "CHANNEL_SIDE": side}, capture_output=True, text=True)
    if check:
        assert r.returncode == 0, r.stdout + r.stderr
    return r


def _clones(tmp_path):
    bare = tmp_path / "origin.git"; git(tmp_path, "init", "-q", "--bare", "-b", "wip", str(bare))
    mac = tmp_path / "mac"; git(tmp_path, "clone", "-q", str(bare), str(mac))
    (mac / "docs" / "a6000" / "channel").mkdir(parents=True); (mac / "scripts" / "a6000").mkdir(parents=True)
    for n in ("mac_to_box.md", "box_to_mac.md"):
        (mac / "docs" / "a6000" / "channel" / n).write_text(f"# {n}\n")
    shutil.copy(SCRIPT, mac / "scripts" / "a6000" / "channel.sh")
    git(mac, "checkout", "-q", "-b", "wip"); git(mac, "add", "-A"); git(mac, "commit", "-q", "-m", "init"); git(mac, "push", "-q", "-u", "origin", "wip")
    box = tmp_path / "box"; git(tmp_path, "clone", "-q", "-b", "wip", str(bare), str(box))
    return mac, box


def test_round_trip_send_read_pending_reply_wait_tail(tmp_path):
    mac, box = _clones(tmp_path)
    assert ch(mac, "mac", "send", "hello box, do X").stdout.strip() == "M-001 sent"
    assert "### M-001 |" in (mac / "docs/a6000/channel/mac_to_box.md").read_text()
    r = ch(box, "box", "read"); assert "### M-001" in r.stdout and "hello box, do X" in r.stdout
    assert ch(box, "box", "read").stdout.strip() == ""                       # nothing new the second time
    assert ch(box, "box", "pending").stdout.split() == ["M-001"]
    note = tmp_path / "report.md"; note.write_text("done: 3 passed\nnumbers verbatim\n")
    assert ch(box, "box", "send", f"@{note}", "--re", "M-001").stdout.strip() == "B-001 sent"
    assert ch(box, "box", "pending").stdout.strip() == ""
    r = ch(mac, "mac", "wait", "1", "1"); assert "### B-001 |" in r.stdout and "re: M-001" in r.stdout and "numbers verbatim" in r.stdout
    assert ch(mac, "mac", "pending").stdout.split() == ["B-001"]          # their reply is open on my side until I answer it
    assert ch(mac, "mac", "send", "next: do Y", "--re", "B-001").stdout.strip() == "M-002 sent"
    assert ch(mac, "mac", "pending").stdout.strip() == ""
    assert ch(box, "box", "pending").stdout.split() == ["M-002"]
    t = ch(box, "box", "tail", "1").stdout; assert "### M-002" in t and "### B-001" in t and "### M-001" not in t
    log = git(mac, "log", "--oneline", "origin/wip"); assert "channel: M-002 re B-001" in log and "channel: B-001 re M-001" in log


def test_send_refuses_a_misordered_call_and_sends_nothing(tmp_path):
    """Regression 2026-10-14: `send B-054 "<the real text>"` sent M-017 as the bare text "B-054" and silently dropped the
    real message; the box sat idle for 9 h. A trailing argument other than `--re <id>`, or a text that is only a message
    id, must fail before anything is committed."""
    mac, box = _clones(tmp_path)
    f = mac / "docs/a6000/channel/mac_to_box.md"; before = f.read_text(); head = git(mac, "rev-parse", "HEAD")
    for args in (["B-054", "the real instructions"], ["B-054", "--re", "B-054"], ["the text", "--re", "B-054", "extra"], ["B-054"]):
        r = ch(mac, "mac", "send", *args, check=False)
        assert r.returncode == 2 and "send:" in r.stderr, (args, r.stdout + r.stderr)
    assert f.read_text() == before and git(mac, "rev-parse", "HEAD") == head and git(box, "ls-remote", "origin", "wip").split()[0] == head.strip()
    assert ch(mac, "mac", "send", "B-054 read, thank you", "--re", "B-054").stdout.strip() == "M-001 sent"  # an id inside text is fine


def test_read_survives_one_concurrent_fetch_failure(tmp_path):
    """Regression 2026-10-14: the Mac's submitter fetches the same branch every 5 min; twice a channel pull collided with it
    ("fatal: Cannot rebase onto multiple branches") and the waiter exited without printing the message. One failed sync is
    retried."""
    mac, box = _clones(tmp_path)
    ch(box, "box", "send", "hourly: 42/74")
    real = shutil.which("git"); bindir = tmp_path / "bin"; bindir.mkdir(); mark = tmp_path / "failed_once"
    (bindir / "git").write_text(f'#!/bin/bash\ncase " $* " in *" pull "*|*" rebase "*) if [ ! -e "{mark}" ]; then touch "{mark}"; '
                                f'echo "fatal: Cannot rebase onto multiple branches." >&2; exit 128; fi ;; esac\nexec "{real}" "$@"\n')
    (bindir / "git").chmod(0o755)
    r = subprocess.run(["bash", str(mac / "scripts/a6000/channel.sh"), "read"], cwd=mac, capture_output=True, text=True,
                       env={**ENV, "CHANNEL_SIDE": "mac", "PATH": f"{bindir}:{os.environ['PATH']}"})
    assert mark.exists() and r.returncode == 0 and "hourly: 42/74" in r.stdout, r.stdout + r.stderr


def test_wait_times_out_cleanly_and_side_detection_defaults_to_mac_here(tmp_path):
    mac, box = _clones(tmp_path)
    r = ch(mac, "mac", "wait", "1", "0", check=False); assert r.returncode == 2 and "no message" in r.stdout
    r = subprocess.run(["bash", str(mac / "scripts/a6000/channel.sh"), "send", "x"], cwd=mac, env=ENV, capture_output=True, text=True)
    assert r.returncode == 0 and (r.stdout.strip() == "M-001 sent" or r.stdout.strip() == "B-001 sent")  # WSL => box, else mac
    assert (ROOT / "scripts/a6000/channel.sh").read_text().count("Carson") == 0
