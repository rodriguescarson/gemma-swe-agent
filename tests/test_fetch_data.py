"""scripts/fetch_data.py: what it wrote is verified, and a stalled download is killed and retried (2026-09-30).

No network: the Kaggle CLI is replaced by a tiny python writer. Regressions:
- the CLI has no read timeout, and one download sat at 8 MB for 15 minutes (fastapi_14487.tgz) while fetch_data waited
  forever in subprocess.run;
- a size match alone accepted a file whose listed size was 0, and never checked that a .tgz decompresses.
"""
import gzip
import importlib.util
import io
import os
import sys
import time
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("fetch_data_under_test", ROOT / "scripts" / "fetch_data.py")
FD = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(FD)                 # importing must not authenticate or touch the network

WRITER = r"""
import os, sys, time
dest, payload, mode, state = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
n = int(open(state).read()) + 1 if os.path.exists(state) else 1
open(state, "w").write(str(n))
data = open(payload, "rb").read()
if mode == "stall_first" and n == 1:
    open(dest, "wb").write(data[:100]); open(dest + ".kaggle-partial", "w").write("{}")
    time.sleep(3600)
elif mode == "zip":
    import zipfile
    with zipfile.ZipFile(dest + ".zip", "w") as z:
        z.writestr(os.path.basename(dest), data)
elif mode == "truncate":
    open(dest, "wb").write(data[:-40] + b"\0" * 40)
else:
    open(dest + ".kaggle-partial", "w").write("{}")
    for i in range(0, len(data), 4096):
        with open(dest, "ab" if i else "wb") as f:
            f.write(data[i:i + 4096])
    os.remove(dest + ".kaggle-partial")
"""


def _payload(tmp_path, n=50_000):
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as g:
        g.write(os.urandom(n))
    p = tmp_path / "payload.tgz"
    p.write_bytes(buf.getvalue())
    return p


def _cmd(tmp_path, payload, mode):
    w = tmp_path / "writer.py"
    w.write_text(WRITER)
    state = tmp_path / f"state_{mode}"

    def cmd(name, d):
        return [sys.executable, str(w), os.path.join(d, os.path.basename(name)), str(payload), mode, str(state)]
    return cmd, state


def _get(tmp_path, cmd, size, **kw):
    kw = {"stall_s": 1.0, "poll_s": 0.1, "attempts": 3, "backoff_s": 0.0, **kw}
    return FD.get(("snapshots/t_1.tgz", size), str(tmp_path / "out"), cmd=cmd, **kw)


def test_ok_then_skip(tmp_path):
    payload = _payload(tmp_path)
    cmd, state = _cmd(tmp_path, payload, "plain")
    assert _get(tmp_path, cmd, payload.stat().st_size) == ("snapshots/t_1.tgz", "ok")
    dest = tmp_path / "out" / "snapshots" / "t_1.tgz"
    assert dest.read_bytes() == payload.read_bytes() and not Path(f"{dest}.kaggle-partial").exists()
    assert _get(tmp_path, cmd, payload.stat().st_size)[1] == "skip" and state.read_text() == "1"


def test_stalled_download_is_killed_and_retried(tmp_path):
    payload = _payload(tmp_path)
    cmd, state = _cmd(tmp_path, payload, "stall_first")
    t0 = time.monotonic()
    name, st = _get(tmp_path, cmd, payload.stat().st_size)
    assert st == "ok (after 1 retry)", st
    assert state.read_text() == "2" and time.monotonic() - t0 < 15          # not the writer's 3600 s sleep
    assert (tmp_path / "out" / "snapshots" / "t_1.tgz").read_bytes() == payload.read_bytes()


def test_stall_every_time_reports_bad(tmp_path):
    payload = _payload(tmp_path)
    w = tmp_path / "hang.py"
    w.write_text("import time; time.sleep(3600)\n")
    t0 = time.monotonic()
    name, st = _get(tmp_path, lambda n, d: [sys.executable, str(w)], payload.stat().st_size, attempts=2)
    assert st.startswith("BAD size=None") and "stalled 1s" in st, st
    assert time.monotonic() - t0 < 15


def test_zip_delivery_is_unpacked(tmp_path):
    payload = _payload(tmp_path)
    cmd, _ = _cmd(tmp_path, payload, "zip")
    assert _get(tmp_path, cmd, payload.stat().st_size)[1] == "ok"
    out = tmp_path / "out" / "snapshots"
    assert (out / "t_1.tgz").read_bytes() == payload.read_bytes() and not (out / "t_1.tgz.zip").exists()


def test_right_size_but_corrupt_gzip_is_bad(tmp_path):
    payload = _payload(tmp_path)
    cmd, state = _cmd(tmp_path, payload, "truncate")
    name, st = _get(tmp_path, cmd, payload.stat().st_size, attempts=2)
    assert st == "BAD gzip stream truncated or corrupt" and state.read_text() == "2", st


def test_zero_listed_size_is_never_ok(tmp_path):
    """The Vesuvius lesson: a 'size matches' check against a missing size (0) passes on an empty file."""
    payload = _payload(tmp_path)
    cmd, state = _cmd(tmp_path, payload, "plain")
    name, st = _get(tmp_path, cmd, 0)
    assert st.startswith("BAD listing size 0") and state.read_text() == "1", st
    assert FD.verify(str(tmp_path / "missing.tgz"), 0).startswith("listing size 0")


def test_leftover_sidecar_is_incomplete(tmp_path):
    payload = _payload(tmp_path)
    dest = tmp_path / "x.tgz"
    dest.write_bytes(payload.read_bytes())
    assert FD.verify(str(dest), payload.stat().st_size) == ""
    Path(f"{dest}.kaggle-partial").write_text("{}")
    assert "sidecar" in FD.verify(str(dest), payload.stat().st_size)
    assert FD.verify(str(dest), payload.stat().st_size + 1).startswith("size=")


def test_non_gzip_files_are_checked_by_size_only(tmp_path):
    p = tmp_path / "tasks.jsonl"
    p.write_text("{}\n")
    assert FD.verify(str(p), 3) == "" and FD.gzip_ok(str(_payload(tmp_path)))
    assert not FD.gzip_ok(str(p))


def test_cli_contract_is_unchanged():
    """tasks.fetch_cmd runs `python scripts/fetch_data.py snapshots/<tid>.tgz`: one positional prefix, the kaggle CLI
    with -f NAME -p DIR --force."""
    c = FD.kaggle_cmd("snapshots/a.tgz", "/d")
    assert c[1:] == ["-m", "kaggle", "competitions", "download", "gemma-4-developer-agent", "-f", "snapshots/a.tgz",
                     "-p", "/d", "-q", "--force"]
    assert not hasattr(FD, "api") and not hasattr(FD, "KaggleApi")           # the import stays lazy (inside main)
