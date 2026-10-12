"""Build a Kaggle notebook that writes a submission bundle and zips it to /kaggle/working/submission.zip.
Usage: python scripts/make_kernel.py submissions/v0 [slug] [--adapters-dataset OWNER/SLUG]

Every bundle file is embedded base64 in the notebook, except adapter weights when --adapters-dataset is given (2026-10-13,
sub15: a 242 MB safetensors cannot ride inside a notebook): the kernel then takes <name>__adapter_model.safetensors from that
private dataset (scripts/adapters_dataset.py layout), checks its sha256 against adapters/MANIFEST.json, and zips it at
adapters/<name>/adapter_model.safetensors next to the embedded files. The notebook is a CPU kernel (no GPU quota)."""
import base64, hashlib, json, os, sys

args = [a for a in sys.argv[1:] if not a.startswith("--")]
dataset = sys.argv[sys.argv.index("--adapters-dataset") + 1] if "--adapters-dataset" in sys.argv else None
src = args[0]; name = os.path.basename(src.rstrip('/'))
slug = args[1] if len(args) > 1 else f"g4agent-{name}"
files, weights = {}, []
for root, _, fs in os.walk(src):
    for f in fs:
        p = os.path.join(root, f); rel = os.path.relpath(p, src)
        if rel.startswith('.') or f == '.DS_Store' or '__pycache__' in rel or f.endswith('.pyc') or f.startswith('._'): continue
        if dataset and f.endswith('.safetensors'):
            weights.append(rel); continue
        files[rel] = base64.b64encode(open(p, 'rb').read()).decode()
if dataset:
    man = json.loads(base64.b64decode(files["adapters/MANIFEST.json"]))["files"]
    missing = [rel.split("/", 1)[1] if rel.startswith("adapters/") else rel for rel in weights]
    missing = [w for w in missing if w not in man]
    if missing:
        sys.exit(f"adapters/MANIFEST.json names no sha256 for {missing}")
digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()[:12]
adapter_cell = '''
if DATASET:
    import hashlib, pathlib
    owner, dslug = DATASET.split("/")
    src = pathlib.Path("/kaggle/input/datasets") / owner / dslug
    if not src.exists(): src = pathlib.Path("/kaggle/input") / dslug
    man = json.loads(base64.b64decode(FILES["adapters/MANIFEST.json"]))["files"]
    for rel, sha in sorted(man.items()):
        if not rel.endswith(".safetensors"): continue
        p = src / rel.replace("/", "__")
        assert p.exists(), f"adapter weights {rel} missing from dataset {DATASET} at {src}"
        got = hashlib.sha256(p.read_bytes()).hexdigest()
        assert got == sha, f"sha mismatch for {rel}: manifest {sha[:12]} vs dataset {got[:12]}"
        WEIGHTS["adapters/" + rel] = str(p)
    print("adapter weights from dataset:", sorted(WEIGHTS))
''' if dataset else ''
code = f'''import base64, json, os, zipfile
FILES = {json.dumps(files)}
DATASET = {json.dumps(dataset)}
WEIGHTS = {{}}
{adapter_cell}
out = "/kaggle/working/submission.zip"
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for rel in sorted(FILES):
        info = zipfile.ZipInfo(rel, date_time=(1980, 1, 1, 0, 0, 0)); info.external_attr = 0o644 << 16
        z.writestr(info, base64.b64decode(FILES[rel]))
    for rel in sorted(WEIGHTS):
        info = zipfile.ZipInfo(rel, date_time=(1980, 1, 1, 0, 0, 0)); info.external_attr = 0o644 << 16
        with open(WEIGHTS[rel], "rb") as f: z.writestr(info, f.read())
with zipfile.ZipFile(out) as z: names = z.namelist()
assert any(n in names for n in ("agent.yaml", "root_agent.yaml")), names
assert all(w in names for w in WEIGHTS), (sorted(WEIGHTS), names)
print("bundle {name} sha {digest}:", os.path.getsize(out), "bytes", names)
'''
nb = {"cells": [{"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": code}],
      "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}},
      "nbformat": 4, "nbformat_minor": 5}
kd = os.path.join("kernels", slug); os.makedirs(kd, exist_ok=True)
json.dump(nb, open(os.path.join(kd, f"{slug}.ipynb"), "w"))
meta = {"id": f"carsonrodrigues/{slug}", "title": slug, "code_file": f"{slug}.ipynb", "language": "python",
        "kernel_type": "notebook", "is_private": True, "enable_gpu": False, "enable_tpu": False,
        "enable_internet": False, "dataset_sources": [dataset] if dataset else [], "competition_sources": ["gemma-4-developer-agent"],
        "kernel_sources": [], "model_sources": []}
json.dump(meta, open(os.path.join(kd, "kernel-metadata.json"), "w"), indent=2)
print(kd, digest, len(files), "files", f"+ {len(weights)} adapter weights from {dataset}" if dataset else "")
