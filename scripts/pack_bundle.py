"""Pack a submission bundle into a deterministic zip and print its sha256 (SPEC v10 R83).

Usage: python scripts/pack_bundle.py submissions/v10 out.zip

Same bundle bytes -> same zip bytes on every run and machine with the same zlib: entries sorted by path, every
mtime 1980-01-01 00:00:00, every mode 0644 (regular file), Unix create_system, DEFLATE level 9, no directory entries,
no extra fields, no comment. Skipped (named on stderr): __pycache__ dirs, *.pyc/*.pyo, dotfiles and dot-dirs
(including AppleDouble ._* and .DS_Store), extensionless files, symlinks, and the output zip itself when it lies
inside the bundle. A file with an extension the organisers' compiler rejects, or a bundle without a root agent.yaml,
is an error (exit 1): a silently dropped helper would ship a broken agent.
stdout, line 1: "<sha256>  <out.zip>" (sha256sum format); line 2: "files=N bytes=B".
"""
import hashlib, os, stat, sys, zipfile

ALLOWED_EXT = frozenset({".yaml", ".yml", ".md", ".txt", ".py", ".json", ".safetensors"})
SKIP_EXT = frozenset({".pyc", ".pyo"})
FIXED_TIME = (1980, 1, 1, 0, 0, 0)
FILE_MODE = stat.S_IFREG | 0o644


def collect(src, out_abs=None):
    """Return (sorted [(rel, abs)], [skipped rel], [rejected rel]) for the bundle at src."""
    keep, skipped, rejected = [], [], []
    for dp, dns, fns in os.walk(src):  # followlinks=False: a symlinked dir is listed but never entered
        for d in list(dns):
            full = os.path.join(dp, d)
            if d == "__pycache__" or d.startswith(".") or os.path.islink(full):
                dns.remove(d)
                skipped.append(os.path.relpath(full, src).replace(os.sep, "/") + "/")
        for f in fns:
            full = os.path.join(dp, f)
            rel = os.path.relpath(full, src).replace(os.sep, "/")
            ext = os.path.splitext(f)[1].lower()
            if (f.startswith(".") or os.path.islink(full) or not ext or ext in SKIP_EXT
                    or (out_abs is not None and os.path.abspath(full) == out_abs)):
                skipped.append(rel)
            elif ext not in ALLOWED_EXT or not os.path.isfile(full):
                rejected.append(rel)
            else:
                keep.append((rel, full))
    keep.sort()
    return keep, sorted(skipped), sorted(rejected)


def pack(src, out):
    """Write the zip; return (sha256 hex, number of files). Raises SystemExit(1) on a bundle that must not ship."""
    src = os.path.abspath(src)
    out_abs = os.path.abspath(out)
    if not os.path.isfile(os.path.join(src, "agent.yaml")):
        raise SystemExit(f"pack_bundle: {src} has no root agent.yaml")
    keep, skipped, rejected = collect(src, out_abs)
    if rejected:
        raise SystemExit("pack_bundle: extensions the compiler rejects: " + ", ".join(rejected))
    for rel in skipped:
        print(f"skipped {rel}", file=sys.stderr)
    os.makedirs(os.path.dirname(out_abs) or ".", exist_ok=True)
    tmp = out_abs + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel, full in keep:
            info = zipfile.ZipInfo(rel, date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = FILE_MODE << 16
            with open(full, "rb") as fh:
                z.writestr(info, fh.read(), compresslevel=9)
    os.replace(tmp, out_abs)
    h = hashlib.sha256()
    with open(out_abs, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest(), len(keep)


def main(argv):
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    digest, n = pack(argv[0], argv[1])
    print(f"{digest}  {argv[1]}")
    print(f"files={n} bytes={os.path.getsize(argv[1])}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
