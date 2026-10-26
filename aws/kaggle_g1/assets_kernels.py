"""Write the three CPU kernels (internet on) that stage the offline G1 4x L4 kernel's inputs on Kaggle, with no Mac uploads.
Kaggle gives the 4x L4 machine only with the competition attached, and then refuses internet (aws/kaggle_g1/make_kernels.py).

    python aws/kaggle_g1/assets_kernels.py   # -> kernels/g1_assets, kernels/g1_w1, kernels/g1_w2; push each with
                                              #    .venv/bin/kaggle kernels push -p kernels/<dir> (CPU, no accelerator)

  g4-g1-assets  uv, CPython 3.12 (py312.tgz, relocatable), and one wheel pool for the teacher (vllm==0.19.1), the harness
                (harness/wheels under the box constraints) and buildenv (pod/buildenv.sh's list + data/kaggle_pins.txt);
                each set is proven to resolve offline (uv --no-index --find-links) before the kernel ends.
  g4-g1-w1      Devstral-Small-2-24B-Instruct-2512 consolidated shard 1 (19.84 GB: inside the 20 GB output limit)
  g4-g1-w2      shard 2 + consolidated.safetensors.index.json, params.json, tekken.json
Both weight kernels check every file's size against the Hub. First run 2026-10-26: 314 wheels (5.37 GB), all three proofs
"resolves offline"; weights 19,839,869,982 + 5,953,165,906 bytes."""
import json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parents[2] / "kernels"
REPO = "mistralai/Devstral-Small-2-24B-Instruct-2512"
BUILDENV = ["pytest==8.3.4", "pytest-timeout==2.1.0", "typer", "pdm-backend", "setuptools", "wheel", "poetry-core", "hatchling",
            "flit-core", "editables", "pip", "typing-inspection", "inline-snapshot", "dirty-equals", "pytest-httpbin", "trustme",
            "pytest-asyncio", "anyio", "python-multipart"]   # pod/buildenv.sh's list, verbatim

ASSETS = r'''# G1 offline assets: uv, CPython 3.12, and one wheel pool (teacher vLLM 0.19.1, harness under the box constraints, buildenv)
import glob, json, os, shutil, subprocess, sys, tarfile, time
from pathlib import Path
W = Path("/kaggle/working"); T0 = time.time()
ENV = {k: v for k, v in os.environ.items() if not k.startswith(("UV_", "PIP_")) and k not in ("PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE", "VIRTUAL_ENV", "CONDA_PREFIX")}
LOG = open(W / "assets.log", "a")
def sh(cmd):
    cmd = [str(c) for c in cmd]; print("+", " ".join(cmd)[:300], round(time.time() - T0), "s", flush=True); LOG.write("+ " + " ".join(cmd) + "\n"); LOG.flush()
    r = subprocess.run(cmd, env=ENV, stdout=LOG, stderr=subprocess.STDOUT)
    if r.returncode: raise SystemExit("FAILED %d: %s (see assets.log)" % (r.returncode, " ".join(cmd)[:300]))
code = sorted(glob.glob("/kaggle/input/**/g1_code.tgz", recursive=True))[0]
G4 = Path("/root/g4"); G4.mkdir(exist_ok=True); sh(["tar", "xzf", code, "-C", G4])
uv = shutil.which("uv")
if not uv:
    sh([sys.executable, "-m", "pip", "install", "-q", "uv"]); uv = shutil.which("uv")
(W / "bin").mkdir(exist_ok=True); shutil.copy(uv, W / "bin" / "uv"); os.chmod(W / "bin" / "uv", 0o755)
sh([uv, "python", "install", "3.12"])
py = subprocess.run([uv, "python", "find", "3.12"], env=ENV, capture_output=True, text=True, check=True).stdout.strip()
home = Path(py).resolve().parents[1]
with tarfile.open(W / "py312.tgz", "w:gz") as t:
    t.add(home, arcname="py312")
sh([uv, "venv", "-q", "--seed", "-p", py, "/tmp/wv"])
PIP, WH = "/tmp/wv/bin/pip", W / "wheels"; WH.mkdir(exist_ok=True)
CON = G4 / "harness/constraints/box_venv_2026-10-18.txt"; HW = sorted(G4.glob("harness/wheels/*.whl")); PINS = G4 / "data/kaggle_pins.txt"
BUILDENV = @BUILDENV@
sh([PIP, "wheel", "-q", "-w", WH, "--find-links", WH, "--extra-index-url", "https://download.pytorch.org/whl/cu128", "-c", CON, *HW])
sh([PIP, "wheel", "-q", "-w", WH, "--find-links", WH, "vllm==0.19.1"])
sh([PIP, "wheel", "-q", "-w", WH, "--find-links", WH, *BUILDENV, "-r", PINS])
proofs = {}
for name, args in (("harness", ["-c", CON, *HW]), ("teacher", ["vllm==0.19.1"]), ("buildenv", [*BUILDENV, "-r", PINS])):
    v = Path("/tmp/proof_" + name); sh([uv, "venv", "-q", "-p", py, v])
    sh([uv, "pip", "install", "--dry-run", "--python", v / "bin/python", "--no-index", "--find-links", WH, *args]); proofs[name] = "resolves offline"
whl = sorted(WH.glob("*.whl"))
man = {"wheels": len(whl), "wheels_gb": round(sum(w.stat().st_size for w in whl) / 1e9, 2), "python": py, "py_home": str(home),
       "uv": subprocess.run([uv, "--version"], capture_output=True, text=True).stdout.strip(), "proofs": proofs,
       "torch": [w.name for w in whl if w.name.startswith("torch-")], "vllm": [w.name for w in whl if w.name.startswith("vllm-")],
       "seconds": round(time.time() - T0)}
(W / "assets_manifest.json").write_text(json.dumps(man, indent=1)); print(json.dumps(man, indent=1))
shutil.rmtree("/root/g4", ignore_errors=True)
'''

WEIGHTS = r'''# G1 offline weights: Devstral-Small-2-24B-Instruct-2512 (Mistral format), part @PART@, sizes checked against the Hub
import json, shutil, time
from pathlib import Path
from huggingface_hub import HfApi, hf_hub_download
W = Path("/kaggle/working"); T0 = time.time(); REPO = "@REPO@"; FILES = @FILES@
sizes = {s.rfilename: s.size for s in HfApi().model_info(REPO, files_metadata=True).siblings}
got = {}
for f in FILES:
    hf_hub_download(REPO, f, local_dir=str(W))
    got[f] = (W / f).stat().st_size
    assert got[f] == sizes[f], (f, got[f], sizes[f])
    print(f, got[f], "ok", round(time.time() - T0), "s", flush=True)
shutil.rmtree(W / ".cache", ignore_errors=True)
(W / "weights_manifest.json").write_text(json.dumps({"repo": REPO, "files": got, "seconds": round(time.time() - T0)}, indent=1))
'''


def kernel(d, kid, src, datasets):
    kd = HERE / d; kd.mkdir(parents=True, exist_ok=True)
    nb = {"cells": [{"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": src}],
          "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}}, "nbformat": 4, "nbformat_minor": 5}
    (kd / (kid + ".ipynb")).write_text(json.dumps(nb, indent=1))
    meta = {"id": "carsonrodrigues/" + kid, "title": kid, "code_file": kid + ".ipynb", "language": "python", "kernel_type": "notebook",
            "is_private": True, "enable_gpu": False, "enable_tpu": False, "enable_internet": True, "dataset_sources": datasets,
            "competition_sources": [], "kernel_sources": [], "model_sources": []}
    (kd / "kernel-metadata.json").write_text(json.dumps(meta, indent=2))
    compile(src, kid, "exec")
    print(kd, "->", meta["id"])


def main():
    kernel("g1_assets", "g4-g1-assets", ASSETS.replace("@BUILDENV@", json.dumps(BUILDENV)), ["carsonrodrigues/g4-g1-harness"])
    kernel("g1_w1", "g4-g1-w1", WEIGHTS.replace("@PART@", "1").replace("@REPO@", REPO).replace("@FILES@", json.dumps(["consolidated-00001-of-00002.safetensors"])), [])
    kernel("g1_w2", "g4-g1-w2", WEIGHTS.replace("@PART@", "2").replace("@REPO@", REPO).replace("@FILES@", json.dumps(
        ["consolidated-00002-of-00002.safetensors", "consolidated.safetensors.index.json", "params.json", "tekken.json"])), [])
    return 0


if __name__ == "__main__":
    sys.exit(main())
