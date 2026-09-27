"""Download every non-wheel competition file, one by one, verifying size against the listing."""
import os, subprocess, sys, zipfile, concurrent.futures as cf
from kaggle.api.kaggle_api_extended import KaggleApi

COMP = "gemma-4-developer-agent"
OUT = os.path.abspath("data/raw")
api = KaggleApi(); api.authenticate()

files, token = [], None
while True:
    r = api.competition_list_files(COMP, page_size=200, page_token=token)
    files += [(f.name, int(f.total_bytes)) for f in r.files]
    token = r.next_page_token
    if not token: break
files = [(n, s) for n, s in files if not (n.endswith(".whl") and "/" not in n)]
if len(sys.argv) > 1: files = [(n, s) for n, s in files if n.startswith(sys.argv[1])]
print(f"{len(files)} files, {sum(s for _,s in files)/1e9:.1f} GB", flush=True)

def get(item):
    name, size = item
    dest = os.path.join(OUT, name)
    if os.path.exists(dest) and os.path.getsize(dest) == size:
        return name, "skip"
    d = os.path.dirname(dest); os.makedirs(d, exist_ok=True)
    for attempt in range(6):
        subprocess.run([sys.executable, "-m", "kaggle", "competitions", "download", COMP, "-f", name, "-p", d, "-q", "--force"],
                       capture_output=True)
        z = dest + ".zip"
        if os.path.exists(z) and zipfile.is_zipfile(z):
            with zipfile.ZipFile(z) as zz: zz.extractall(d)
            os.remove(z)
        if os.path.exists(dest) and os.path.getsize(dest) == size:
            return name, "ok"
        import time; time.sleep(20 * (attempt + 1))
    return name, f"BAD size={os.path.getsize(dest) if os.path.exists(dest) else None} want={size}"

with cf.ThreadPoolExecutor(int(os.environ.get("FETCH_THREADS", "6"))) as ex:
    for i, (n, st) in enumerate(ex.map(get, sorted(files, key=lambda x: x[1]))):
        if st != "skip": print(i, n, st, flush=True)
print("DONE", flush=True)
