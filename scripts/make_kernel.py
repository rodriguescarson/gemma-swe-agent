"""Build a Kaggle notebook that writes a submission bundle and zips it to /kaggle/working/submission.zip.
Usage: python scripts/make_kernel.py submissions/v0 [slug]"""
import base64, json, os, sys, hashlib, zipfile, io
src = sys.argv[1]; name = os.path.basename(src.rstrip('/'))
slug = sys.argv[2] if len(sys.argv) > 2 else f"g4agent-{name}"
files = {}
for root, _, fs in os.walk(src):
    for f in fs:
        p = os.path.join(root, f); rel = os.path.relpath(p, src)
        if rel.startswith('.') or f == '.DS_Store' or '__pycache__' in rel or f.endswith('.pyc') or f.startswith('._'): continue
        files[rel] = base64.b64encode(open(p, 'rb').read()).decode()
digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()[:12]
code = f'''import base64, os, zipfile
FILES = {json.dumps(files)}
out = "/kaggle/working/submission.zip"
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for rel in sorted(FILES):
        info = zipfile.ZipInfo(rel, date_time=(1980, 1, 1, 0, 0, 0)); info.external_attr = 0o644 << 16
        z.writestr(info, base64.b64decode(FILES[rel]))
with zipfile.ZipFile(out) as z: names = z.namelist()
assert any(n in names for n in ("agent.yaml", "root_agent.yaml")), names
print("bundle {name} sha {digest}:", os.path.getsize(out), "bytes", names)
'''
nb = {"cells": [{"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": code}],
      "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}},
      "nbformat": 4, "nbformat_minor": 5}
kd = os.path.join("kernels", slug); os.makedirs(kd, exist_ok=True)
json.dump(nb, open(os.path.join(kd, f"{slug}.ipynb"), "w"))
meta = {"id": f"carsonrodrigues/{slug}", "title": slug, "code_file": f"{slug}.ipynb", "language": "python",
        "kernel_type": "notebook", "is_private": True, "enable_gpu": False, "enable_tpu": False,
        "enable_internet": False, "dataset_sources": [], "competition_sources": ["gemma-4-developer-agent"],
        "kernel_sources": [], "model_sources": []}
json.dump(meta, open(os.path.join(kd, "kernel-metadata.json"), "w"), indent=2)
print(kd, digest, len(files), "files")
