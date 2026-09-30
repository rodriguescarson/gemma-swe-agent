"""Download files of the public Kaggle dataset takumuhata/swe-pallets-x one by one, verifying each file's size against
the dataset listing (a file whose size differs is retried, then reported BAD; never trusted).

  source ~/Projects/kaggriculture/.venv/bin/activate
  python scripts/pallets/fetch.py [--ids FILE] [PREFIX ...]   # e.g. snapshots/snapshots/click_ (default: every snapshot)
  --ids FILE keeps only files whose stem is an id in FILE, e.g. the graphs+embeddings of the dev set:
  python scripts/pallets/fetch.py --ids data/pallets/dev_ids.txt graphs/graphs/ embeddings/embeddings/

Writes under data/pallets/ with the dataset's own paths flattened one level: snapshots/snapshots/x.tgz -> snapshots/x.tgz
(graphs/graphs/x.json -> graphs/x.json, embeddings/embeddings/x.npz -> embeddings/x.npz), i.e. the swegemma layout.
"""
import concurrent.futures as cf
import os
import subprocess
import sys
import time
import zipfile

from kaggle.api.kaggle_api_extended import KaggleApi

DS = "takumuhata/swe-pallets-x"
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT = os.path.join(ROOT, "data", "pallets")

api = KaggleApi()
api.authenticate()
files, tok = [], None
while True:
    r = api.dataset_list_files(DS, page_token=tok, page_size=200)
    files += [(f.name, int(f.total_bytes)) for f in r.files]
    tok = r.next_page_token
    if not tok:
        break
args = sys.argv[1:]
only = None
if "--ids" in args:
    i = args.index("--ids")
    only = {ln.strip() for ln in open(args[i + 1]) if ln.strip()}
    args = args[:i] + args[i + 2:]
prefixes = args or ["snapshots/snapshots/"]
files = [(n, s) for n, s in files if any(n.startswith(p) for p in prefixes)]
if only is not None:
    files = [(n, s) for n, s in files if os.path.splitext(os.path.basename(n))[0] in only]
print(f"{len(files)} files, {sum(s for _, s in files) / 1e9:.2f} GB", flush=True)


def local_path(name):
    parts = name.split("/")
    if len(parts) == 3 and parts[0] == parts[1]:
        parts = [parts[0], parts[2]]
    return os.path.join(OUT, *parts)


def get(item):
    name, size = item
    dest = local_path(name)
    if os.path.exists(dest) and os.path.getsize(dest) == size:
        return name, "skip"
    d = os.path.dirname(dest)
    os.makedirs(d, exist_ok=True)
    for attempt in range(5):
        subprocess.run([sys.executable, "-m", "kaggle", "datasets", "download", DS, "-f", name, "-p", d, "-q"],
                       capture_output=True)
        base = os.path.join(d, os.path.basename(name))
        z = base + ".zip"
        if os.path.exists(z) and zipfile.is_zipfile(z):
            with zipfile.ZipFile(z) as zz:
                zz.extractall(d)
            os.remove(z)
        if base != dest and os.path.exists(base):
            os.replace(base, dest)
        if os.path.exists(dest) and os.path.getsize(dest) == size:
            return name, "ok"
        time.sleep(10 * (attempt + 1))
    got = os.path.getsize(dest) if os.path.exists(dest) else None
    return name, f"BAD size={got} want={size}"


bad = 0
with cf.ThreadPoolExecutor(int(os.environ.get("FETCH_THREADS", "6"))) as ex:
    for i, (n, st) in enumerate(ex.map(get, sorted(files, key=lambda x: x[1]))):
        if st.startswith("BAD"):
            bad += 1
        if st != "skip":
            print(i, n, st, flush=True)
print(f"DONE bad={bad}", flush=True)
