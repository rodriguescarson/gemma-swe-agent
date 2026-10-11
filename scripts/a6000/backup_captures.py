#!/usr/bin/env python3
"""Interval backup of a collection run (its raw captures + per-item results) to a private Kaggle dataset.

    python scripts/a6000/backup_captures.py --run ~/g4/runs/p3_think --out ~/g4/backup/p3_think --slug g4-p3-think-captures \
        [--every 60] [--once] [--force] [--kaggle kaggle] [--owner carsonrodrigues]

The captures are the training data of P11 (train/build_sft.py reads them); they never enter git (scripts/a6000/backup_results.py
skips them on purpose) and the box is a shared lab machine, so until this ran a crash or a reimage lost everything but P2_LOG.
Each round: every capture*.jsonl is snapshotted up to its last complete line (the proxy appends while we read; a partial last
line would break json.loads on restore) and gzipped; proxy.jsonl likewise; ARM, ids.txt, items.jsonl and race.log are copied;
the per-item result files (task_results.jsonl, patches, summaries, ledgers: never logs/, traces/ or files over 8 MB, the
backup_results.py rules) go into items.tar.gz; MANIFEST.json records lines, bytes and sha256 per file; then the directory
--out/dataset is pushed as a new dataset version (`kaggle datasets create` on the first round, `version` after). A round is
skipped when neither the capture line count nor the item count changed since the last successful push (--out/state.json);
--force pushes anyway. The loop ends by itself after one last round once no autopilot.py process is alive (the collection has
ended), so it needs no stop command. Read-only on --run; CPU only (gzip); log at --out/backup.log. tests/test_backup_captures.py.
Restore: `kaggle datasets download -d <owner>/<slug> --unzip -p DIR`, gunzip the captures, untar items.tar.gz."""
import argparse, gzip, hashlib, json, os, shutil, subprocess, sys, tarfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from adapters_dataset import cli_command  # noqa: E402

MAX_BYTES = 8 * 1024 * 1024
SKIP_DIRS = ("logs", "traces")
TOP_FILES = ("ARM", "ids.txt", "items.jsonl", "race.log")
CHUNK = 1 << 20


def complete_prefix(path):
    """Bytes of `path` up to and including its last newline (0 when it has none)."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        pos = size
        while pos > 0:
            step = min(1 << 16, pos)
            f.seek(pos - step)
            chunk = f.read(step)
            i = chunk.rfind(b"\n")
            if i >= 0:
                return pos - step + i + 1
            pos -= step
    return 0


def snapshot_gz(src, dst):
    """gzip the complete lines of src into dst -> (lines, bytes)."""
    n = complete_prefix(src)
    lines = 0
    with open(src, "rb") as f, gzip.open(dst, "wb", compresslevel=6) as g:
        left = n
        while left > 0:
            chunk = f.read(min(CHUNK, left))
            if not chunk:
                break
            lines += chunk.count(b"\n")
            g.write(chunk)
            left -= len(chunk)
    return lines, n


def item_files(run, max_bytes=MAX_BYTES):
    """Relative paths (posix) of the per-item files worth keeping, the backup_results.py rules."""
    run = Path(run)
    base = run / "items"
    out = []
    if not base.is_dir():
        return out
    for dirpath, dirs, files in os.walk(base):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(files):
            p = Path(dirpath) / name
            try:
                if p.stat().st_size > max_bytes:
                    continue
            except OSError:
                continue
            out.append(p.relative_to(run).as_posix())
    return sorted(out)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def stage(run, out, owner, slug):
    """Build the dataset directory `out` from the run -> manifest dict."""
    run, out = Path(run), Path(out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    captures = {}
    for src in sorted(run.glob("capture*.jsonl")):
        lines, nbytes = snapshot_gz(src, out / (src.name + ".gz"))
        captures[src.name + ".gz"] = {"lines": lines, "bytes": nbytes}
    if (run / "proxy.jsonl").is_file():
        snapshot_gz(run / "proxy.jsonl", out / "proxy.jsonl.gz")
    for name in TOP_FILES:
        if (run / name).is_file():
            shutil.copyfile(run / name, out / name)
    items = item_files(run)
    with tarfile.open(out / "items.tar.gz", "w:gz", compresslevel=6) as t:
        for rel in items:
            t.add(run / rel, arcname=rel, recursive=False)
    files = {p.name: {"bytes": p.stat().st_size, "sha256": _sha256(p)} for p in sorted(out.iterdir()) if p.is_file()}
    man = {"run": str(run), "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "slug": f"{owner}/{slug}",
           "captures": captures, "capture_lines": sum(c["lines"] for c in captures.values()), "items": len(items), "files": files}
    with open(out / "MANIFEST.json", "w") as fh:
        json.dump(man, fh, indent=2)
    with open(out / "dataset-metadata.json", "w") as fh:
        json.dump({"title": slug, "id": f"{owner}/{slug}", "licenses": [{"name": "CC0-1.0"}]}, fh, indent=2)
    return man


def changed(state, man):
    return not state or state.get("capture_lines") != man["capture_lines"] or state.get("items") != man["items"]


def autopilot_alive(run=subprocess.run):
    r = run(["pgrep", "-f", "autopilot.py"], capture_output=True, text=True)
    return r.returncode == 0 and bool((r.stdout or "").strip())


def push(kaggle, ds, owner, slug):
    """-> (rc, kind, tail): create or version the dataset from `ds`."""
    r = subprocess.run([kaggle, "datasets", "status", f"{owner}/{slug}"], capture_output=True, text=True)
    text = (r.stdout or "") + (r.stderr or "")
    exists = r.returncode == 0 and "not found" not in text.lower() and "404" not in text
    cmd = cli_command(kaggle, str(ds), exists)
    out = subprocess.run(cmd, capture_output=True, text=True)
    tail = ((out.stdout or "") + (out.stderr or "")).strip().replace("\n", " | ")[-300:]
    return out.returncode, cmd[2], tail


def _log(path, line):
    msg = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {line}"
    print(msg, flush=True)
    with open(path, "a") as fh:
        fh.write(msg + "\n")


def one_round(a):
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    log, state_path, ds = out / "backup.log", out / "state.json", out / "dataset"
    try:
        man = stage(a.run, ds, a.owner, a.slug)
    except Exception as e:  # noqa: BLE001
        _log(log, f"FAILED stage: {e!r}")
        return 1
    state = json.load(open(state_path)) if state_path.is_file() else None
    nbytes = sum(c["bytes"] for c in man["captures"].values())
    if not a.force and not changed(state, man):
        _log(log, f"skip (unchanged: lines {man['capture_lines']} items {man['items']})")
        return 0
    rc, kind, tail = push(a.kaggle, ds, a.owner, a.slug)
    if rc != 0:
        _log(log, f"FAILED {kind} rc={rc} lines {man['capture_lines']} items {man['items']} | {tail}")
        return 1
    new = {"capture_lines": man["capture_lines"], "items": man["items"], "pushes": (state or {}).get("pushes", 0) + 1,
           "last": man["time"], "kind": kind, "slug": man["slug"]}
    with open(state_path, "w") as fh:
        json.dump(new, fh, indent=2)
    _log(log, f"pushed {kind} #{new['pushes']} lines {man['capture_lines']} bytes {nbytes} items {man['items']} "
              f"gz {man['files'].get('items.tar.gz', {}).get('bytes', 0) + sum(man['files'][k]['bytes'] for k in man['captures'])} rc=0 | {tail}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", required=True); ap.add_argument("--out", required=True); ap.add_argument("--slug", required=True)
    ap.add_argument("--owner", default="carsonrodrigues"); ap.add_argument("--kaggle", default="kaggle")
    ap.add_argument("--every", type=float, default=60, help="minutes between rounds")
    ap.add_argument("--once", action="store_true"); ap.add_argument("--force", action="store_true", help="push even when unchanged")
    a = ap.parse_args(argv)
    a.run = os.path.expanduser(a.run); a.out = os.path.expanduser(a.out); a.kaggle = os.path.expanduser(a.kaggle)
    while True:
        alive = autopilot_alive()
        rc = one_round(a)
        if a.once:
            return rc
        if not alive:
            _log(Path(a.out) / "backup.log", "autopilot not alive: that was the final round, exiting")
            return rc
        time.sleep(a.every * 60)


if __name__ == "__main__":
    sys.exit(main())
