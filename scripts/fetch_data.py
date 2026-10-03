"""Download every non-wheel competition file, one by one, verifying what was written against the listing.

    python scripts/fetch_data.py [PREFIX]      e.g. snapshots/fastapi_5077.tgz (one file) or snapshots/ (all of them)

Each file: the Kaggle CLI (a zip is unpacked), then the size must equal the listing's non-zero size and a .tgz/.gz must
decompress to the end. A download whose file stops growing for FETCH_STALL_S seconds (default 120) is killed and
retried: the CLI has no read timeout, and one stalled at 8 MB for 15 minutes on 2026-09-30. Env: FETCH_THREADS
(parallel files, default 6; use 1 for one downloader at a time), FETCH_STALL_S.
"""
import concurrent.futures as cf
import gzip
import os
import signal
import subprocess
import sys
import time
import zipfile

COMP = "gemma-4-developer-agent"
ATTEMPTS = 6


def kaggle_cmd(name: str, d: str) -> list:
    return [sys.executable, "-m", "kaggle", "competitions", "download", COMP, "-f", name, "-p", d, "-q", "--force"]


def _size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return -1


def gzip_ok(path: str) -> bool:
    """True when a .tgz/.gz decompresses to the end (a size match alone does not prove the bytes are right)."""
    try:
        with gzip.open(path, "rb") as f:
            while f.read(1 << 20):
                pass
        return True
    except (OSError, EOFError, zipfile.BadZipFile):
        return False


def run_watched(cmd: list, watch: list, stall_s: float, poll_s: float = 2.0) -> str:
    """Run cmd in its own process group; kill the group when none of the `watch` files has grown for stall_s.
    -> 'exit' or 'stalled'."""
    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    last, since = None, time.monotonic()
    try:
        while p.poll() is None:
            cur = tuple(_size(w) for w in watch)
            if cur != last:
                last, since = cur, time.monotonic()
            elif time.monotonic() - since >= stall_s:
                return "stalled"
            time.sleep(poll_s)
        return "exit"
    finally:
        if p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                p.kill()
            p.wait()


def verify(dest: str, size: int) -> str:
    """'' when dest is complete, else why not."""
    if size <= 0:
        return f"listing size {size}: nothing to verify against"
    got = _size(dest)
    if got != size:
        return f"size={got if got >= 0 else None} want={size}"
    if dest.endswith((".tgz", ".gz")) and not gzip_ok(dest):
        return "gzip stream truncated or corrupt"
    if os.path.exists(dest + ".kaggle-partial"):
        return "the CLI's .kaggle-partial sidecar is still there"
    return ""


def get(item, out: str, cmd=kaggle_cmd, stall_s: float = None, poll_s: float = 2.0, attempts: int = ATTEMPTS,
        backoff_s: float = 20.0):
    """-> (name, 'skip' | 'ok' | 'BAD ...')."""
    name, size = item
    stall_s = float(os.environ.get("FETCH_STALL_S", "120")) if stall_s is None else stall_s
    dest = os.path.join(out, name)
    if size > 0 and not verify(dest, size):
        return name, "skip"
    d = os.path.dirname(dest)
    os.makedirs(d, exist_ok=True)
    z = dest + ".zip"
    why = "not attempted"
    for attempt in range(attempts):
        how = run_watched(cmd(name, d), [dest, z], stall_s, poll_s)
        if os.path.exists(z) and zipfile.is_zipfile(z):
            with zipfile.ZipFile(z) as zz:
                zz.extractall(d)
            os.remove(z)
        why = verify(dest, size)
        if not why:
            return name, "ok" + (f" (after {attempt} retr{'y' if attempt == 1 else 'ies'})" if attempt else "")
        if how == "stalled":
            why += f"; stalled {stall_s:g}s"
        if size <= 0:
            break
        time.sleep(backoff_s * (attempt + 1))
    return name, f"BAD {why}"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    from kaggle.api.kaggle_api_extended import KaggleApi
    api = KaggleApi()
    api.authenticate()
    out = os.path.abspath("data/raw")
    files, token = [], None
    while True:
        r = api.competition_list_files(COMP, page_size=200, page_token=token)
        files += [(f.name, int(f.total_bytes)) for f in r.files]
        token = r.next_page_token
        if not token:
            break
    files = [(n, s) for n, s in files if not (n.endswith(".whl") and "/" not in n)]
    if argv:
        files = [(n, s) for n, s in files if n.startswith(argv[0])]
    print(f"{len(files)} files, {sum(s for _, s in files) / 1e9:.1f} GB", flush=True)
    bad = 0
    with cf.ThreadPoolExecutor(int(os.environ.get("FETCH_THREADS", "6"))) as ex:
        for i, (n, st) in enumerate(ex.map(lambda it: get(it, out), sorted(files, key=lambda x: x[1]))):
            bad += st.startswith("BAD")
            if st != "skip":
                print(i, n, st, flush=True)
    print("DONE" + (f" ({bad} BAD)" if bad else ""), flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
